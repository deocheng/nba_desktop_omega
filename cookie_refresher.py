#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cookie_refresher.py — 从本地 Chrome (CDP / 远程调试端口) 自动同步
basketball-reference.com 的 Cloudflare cookie (cf_clearance / __cf_bm)
到 BR crawler 使用的 cookie 文件，免去人工反复粘贴。

前置条件（一次性）：
  用 launch_chrome_cdp.sh 启动一个「独立临时 profile」的 Chrome（开启
  --remote-debugging-port=9222），手动过一次 CF 挑战，并保持该窗口打开。
  之后本脚本每隔 --interval 秒（默认 600 = 10 分钟）自动把有效 cookie
  同步到 --out 指向的文件。

重要现实（务必知悉）：
  - 本脚本只在「非 CDP 的无头模式（BR_COOKIE_FILE 注入）」下才被 crawler 实际
    读取。当前 crawler 跑的是 CDP 直连模式（BROWSER_BACKEND=cdp），它直接驱动
    9222 那扇 Chrome、用浏览器里的「实时 cookie」，根本不读这个文件。
  - 因此本脚本的 10 分钟刷新 = 给你留一份新鲜「回退 cookie 备份」+ 一个心跳告警
    （若发现浏览器里 cf_clearance 缺失/过期会 WARN，提醒你去点 CF）。
  - 它【无法】自动续期 cf_clearance：该 cookie 由 Cloudflare 绑死在真人点击上，
    过期后无论如何都得去 9222 窗口点一次。这是物理限制，不是脚本没写好。

实现要点（为什么不用 Playwright 的 connect_over_cdp）：
  - Playwright 的 connect_over_cdp 在连「非它自己拉起」的 Chrome 时会调用
    Browser.setDownloadBehavior，而手动机的 Chrome 不支持该指令，直接抛
    "Browser context management is not supported"。
  - 故本脚本改用「原始 CDP WebSocket」：先 GET /json/version 拿到
    webSocketDebuggerUrl，再 Network.enable + Network.getAllCookies（浏览器级，
    返回整个 profile 的所有 cookie，不依赖某个开着的标签页），过滤出 BR 域下的
    目标 cookie。完全绕过 Playwright，稳定无坑。

鲁棒性：
  - 首刷成功前用 --fast 秒（默认 30）快重试，避免最长等满一个 interval。
  - 连不上 / 读不到 BR cookie 时只记 WARN 并保留旧文件，不中断、不崩溃。
  - 原子写入（先写临时文件再 os.replace），crawler 不会读到半截 JSON。
  - 只读 CDP，绝不关闭/干扰用户的 Chrome 进程。
"""
import argparse
import asyncio
import json
import os
import tempfile
import time
import urllib.request

import websockets  # .venv 自带（playwright 依赖），无需额外安装

# 只关心这两个 Cloudflare cookie
TARGET_NAMES = ("cf_clearance", "__cf_bm")
BR_DOMAINS = ("basketball-reference.com",)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _cdp_ws_url(port: int) -> str:
    """从 CDP HTTP 端点拿到浏览器级 WebSocket 调试地址。"""
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/json/version", timeout=5
    ) as r:
        data = json.loads(r.read())
    ws = data.get("webSocketDebuggerUrl")
    if not ws:
        raise RuntimeError("CDP 未返回 webSocketDebuggerUrl（Chrome 没开远程调试？）")
    return ws


async def _get_all_cookies(ws_url: str) -> list:
    """走原始 CDP：启用 Network 域，取整个浏览器 profile 的所有 cookie。"""
    async with websockets.connect(
        ws_url, max_size=None, open_timeout=10, ping_interval=None
    ) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Network.enable", "params": {}}))
        await ws.recv()  # 收掉 Network.enable 的 ack
        await ws.send(
            json.dumps({"id": 2, "method": "Network.getAllCookies", "params": {}})
        )
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("id") == 2:
                return msg.get("result", {}).get("cookies", [])
            # 忽略其他事件 / ack


def collect(port: int) -> list:
    """从 CDP 浏览器读取 BR 域下的目标 cookie，返回 [{name,value}, ...]（按名去重）。"""
    try:
        ws_url = _cdp_ws_url(port)
        all_cookies = asyncio.run(_get_all_cookies(ws_url))
    except Exception as e:  # noqa: BLE001 - 连接/协议异常都降级为「本轮重试」
        log(f"WARN: CDP 读 cookie 失败: {e}（保留旧文件，下个周期重试）")
        return []
    seen = {}
    for c in all_cookies:
        dom = c.get("domain", "")
        name = c.get("name")
        if any(d in dom for d in BR_DOMAINS) and name in TARGET_NAMES:
            seen[name] = c.get("value")
    return [{"name": k, "value": v} for k, v in seen.items()]


def load_existing(path: str) -> list:
    """读取已有 cookie 文件，返回 [{name,value}, ...]；读不到返回 []。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = [data]
        out = []
        for c in data:
            n = c.get("name") or c.get("Name")
            v = c.get("value") or c.get("Value") or c.get("content")
            if n and v is not None:
                out.append({"name": n, "value": v})
        return out
    except Exception:  # noqa: BLE001 - 文件缺失/损坏都视为空
        return []


def merge_write(path: str, fresh: list) -> None:
    """合并写入：保留旧条目中「本次未读到同名」的部分，再追加本次读到的。"""
    fresh_names = {e["name"] for e in fresh}
    kept = [e for e in load_existing(path) if e["name"] not in fresh_names]
    merged = kept + fresh
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)
        os.replace(tmp, path)  # 原子替换
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Auto-sync BR CF cookies from local Chrome via raw CDP"
    )
    ap.add_argument("--port", type=int, default=9222, help="Chrome 远程调试端口 (默认 9222)")
    ap.add_argument("--interval", type=int, default=600, help="同步间隔秒数 (默认 600 = 10 分钟)")
    ap.add_argument("--fast", type=int, default=30, help="首刷成功前的快重试间隔秒数 (默认 30)")
    ap.add_argument("--out", default="/tmp/br_cf_cookies.json", help="输出 cookie 文件路径")
    ap.add_argument("--once", action="store_true", help="只同步一次即退出")
    args = ap.parse_args()

    log(f"cookie_refresher 启动: port={args.port} interval={args.interval}s fast={args.fast}s out={args.out}")
    first_ok = False
    while True:
        try:
            fresh = collect(args.port)
            names = {e["name"] for e in fresh}
            if "cf_clearance" not in names:
                log(
                    "WARN: 浏览器里 cf_clearance 缺失/已过期 —— 请去 9222 窗口点过 "
                    "CF 挑战（crawler 会因此暂停等待）"
                )
            if not fresh:
                log("WARN: 未读到 BR cookie（是否还没过 CF / Chrome 未开？保留旧文件）")
            else:
                merge_write(args.out, fresh)
                log(
                    f"OK: 已合并刷新 -> {args.out}（本次新增/覆盖: {sorted(names)}）"
                )
                first_ok = True
        except Exception as e:  # noqa: BLE001 - 任何意外都不退出循环
            log(f"WARN: 读取失败: {e}（保留旧文件，下个周期重试）")

        if args.once:
            break
        # 首刷成功前快重试；成功后按正式 interval 走
        time.sleep(args.interval if first_ok else args.fast)


if __name__ == "__main__":
    main()
