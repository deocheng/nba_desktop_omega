#!/usr/bin/env python3
"""RelateAnything 权重下载器（sha256 官方校验 + 镜像直连 + 断点续传）

踩过的坑，逐条固化在这里：
  1. 出站代理在 HF /resolve/ 上返 502/000  -> 必须绕代理直连（ProxyHandler({})）
  2. HEAD 请求会超时                       -> 文件长度/校验值改从 HF API tree 取
  3. 单连接仅 ~48KB/s                      -> 16 路并行分片可达 ~1.6MB/s
  4. curl -s 与截断写入都会造成"尺寸对但内容错" -> 只校验字节数 = 假完整，
                                              必须用官方 sha256 校验内容
  5. 【2026-09-23 复盘】DNS 被污染：huggingface.co 被解析到 31.13.87.33（Facebook 段），
     直连必然超时；走 DoH 拿到的 202.160.128.203 也被墙。
     -> 唯一稳定路径 = hf-mirror.com（实测 206 / 1.25MB/s，单分片 2.5s）
  6. 【2026-09-23 复盘】旧版在**每次尝试后无条件 rmtree(cdir)**，未完成也清空，
     5 次重试全部从零开始 -> 3h50m 一个分片都没留住。
     -> 未完成的分片必须保留续下，只有"合并后校验失败"才清空重来。
  7. 【2026-09-23 复盘】hf-mirror 对 **Python 默认 UA 直接返 403 Forbidden**
     （`Python-urllib/3.13` 被拦，curl 因带 `curl/8.x` 能过）。
     -> 所有请求必须带浏览器 UA。加 UA 后：小文件 200 全量、大文件 206 正确分片。
     另注：镜像对非 LFS 小文件**忽略 Range、直接返整个文件（200）**，
     所以分片长度校验要额外接受"整文件"这一情形。
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import hashlib
import json
import os
import shutil
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from common.nba_paths import tactics_data_file, workspace_file

REPO = "maelic/relsgg-vits16plus"
CACHE = str(tactics_data_file("vocab/model_sizes.json"))
WANT = ["model.pth", "text_student.pt", "predicate_embeddings.npz", "predicate_bank.npz",
        "relateanything.onnx", "thresholds.json", "relateanything.json",
        "tokenizer.json", "tokenizer_config.json", "calibration.json", "config.json",
        "README.md"]
CHUNK = 3 * 1024 * 1024
WORKERS = 16
MAX_ATTEMPT = 8
CHUNK_TRIES = 6
TIMEOUT = 60

# hf-mirror / HF 都会拦 Python 默认 UA（403）-> 必须伪装成浏览器
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")
BASE_HEADERS = {
    "User-Agent": UA,
    "Accept": "*/*",
    "Connection": "close",
}

# 镜像优先。HF_BASE 可覆盖，逗号分隔多个候选。
BASES = [b.strip().rstrip("/") for b in
         os.environ.get("HF_BASE", "https://hf-mirror.com,https://huggingface.co").split(",")
         if b.strip()]

DEST = sys.argv[1] if len(sys.argv) > 1 else \
    str(workspace_file("action_work/models/relsgg-vits16plus"))

# 只用指定文件（逗号分隔），留空 = 全部
ONLY = [x.strip() for x in os.environ.get("HF_ONLY", "").split(",") if x.strip()]

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def url_for(base: str, name: str) -> str:
    return f"{base}/{REPO}/resolve/main/{name}"


def spec() -> dict[str, dict]:
    """{文件名: {'size': int, 'sha256': str|None}}，API 失败则读缓存。"""
    for base in BASES:
        api = f"{base}/api/models/{REPO}/tree/main?recursive=true"
        try:
            with _opener.open(urllib.request.Request(api, headers=BASE_HEADERS),
                              timeout=40) as r:
                tree = json.load(r)
            out = {}
            for e in tree:
                if e.get("type") != "file":
                    continue
                lfs = e.get("lfs") or {}
                out[e["path"]] = {"size": e.get("size", 0), "sha256": lfs.get("oid")}
            print(f"[spec] 来自 API: {base}")
            return out
        except Exception as e:
            print(f"[spec] {base} 失败 ({type(e).__name__}) -> 换下一个")
    print("[spec] 全部 API 失败 -> 读缓存表")
    d = json.load(open(CACHE))["files"]
    return {k: {"size": v["size"], "sha256": v.get("sha256")}
            for k, v in d.items()}


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def get_range(base: str, name: str, s: int, e: int) -> bytes:
    """带 Range 的取数。

    统一走这条路径，**不要**用不带 Range 的整取——实测整取在经 302 跳转到 CDN 后
    会挂死（每次要等满 timeout 才抛 URLError），而 Range 请求稳定返回 206。

    注意：hf-mirror 对**非 LFS 小文件忽略 Range、直接返 200 + 整个文件**，
    调用方需同时接受 `len(d) == want`（正常分片）与 `len(d) == size`（整文件）。
    """
    h = dict(BASE_HEADERS)
    h["Range"] = f"bytes={s}-{e}"
    req = urllib.request.Request(url_for(base, name), headers=h)
    with _opener.open(req, timeout=TIMEOUT) as r:
        return r.read()


def looks_zeroed(path: str, probe: int = 8192) -> bool:
    """文件头是否全为 0 字节。

    这是本机最容易踩的"假完整"：截断写入或分片静默失败后，文件尺寸完全正确
    但内容是一片 0，torch.load 会报 KeyError: 'storages'。
    """
    with open(path, "rb") as f:
        head = f.read(probe)
    return len(head) > 0 and not any(head)


def verified(path: str, meta: dict) -> bool:
    if not os.path.exists(path) or os.path.getsize(path) != meta["size"]:
        return False
    if looks_zeroed(path):
        print(f"    文件头全零 -> 判定损坏: {os.path.basename(path)}")
        return False
    if path.endswith(".json"):
        try:
            json.load(open(path, encoding="utf-8"))
        except Exception as e:
            print(f"    JSON 解析失败: {e}")
            return False
    if meta.get("sha256"):
        got = sha256(path)
        if got != meta["sha256"]:
            print(f"    sha256 不符: {got[:16]} != {meta['sha256'][:16]}")
            return False
    return True


def fetch(name: str, meta: dict) -> None:
    out = os.path.join(DEST, name)
    if verified(out, meta):
        print(f"  [skip] {name} ({meta['size']/1e6:.1f} MB, 校验通过)")
        return

    size = meta["size"]
    n = (size + CHUNK - 1) // CHUNK
    plan = [(i, i * CHUNK, min((i + 1) * CHUNK - 1, size - 1)) for i in range(n)]
    cdir = os.path.join(DEST, "_chunks", name)
    os.makedirs(cdir, exist_ok=True)

    def part(i: int) -> str:
        return os.path.join(cdir, f"p{i:06d}")

    def have(i: int) -> bool:
        p = part(i)
        want = plan[i][2] - plan[i][1] + 1
        return os.path.exists(p) and os.path.getsize(p) == want

    def one(c) -> None:
        i, s, e = c
        p = part(i)
        want = e - s + 1
        if os.path.exists(p) and os.path.getsize(p) == want:
            return
        for a in range(CHUNK_TRIES):
            base = BASES[a % len(BASES)]          # 换 base 重试
            try:
                d = get_range(base, name, s, e)
                # 正常分片 == want；镜像忽略 Range 时 == size（此时必为单分片文件）
                if len(d) != want and not (s == 0 and len(d) == size):
                    continue
                tmp = p + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(d)
                os.replace(tmp, p)
                return
            except Exception:
                time.sleep(0.6 + 0.6 * a)

    ok = False
    t0 = time.perf_counter()
    for attempt in range(1, MAX_ATTEMPT + 1):
        todo = [c for c in plan if not have(c[0])]
        if not todo:
            break
        print(f"    attempt {attempt}: 缺 {len(todo)}/{n} 分片，开始下载")
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            list(ex.map(one, todo))
        left = [i for i in range(n) if not have(i)]
        if left:
            done = n - len(left)
            print(f"    attempt {attempt}: 已补到 {done}/{n}（保留续下，不清空）")
            continue

        # 全齐 -> 合并
        with open(out, "wb") as fo:
            for i in range(n):
                with open(part(i), "rb") as fi:
                    shutil.copyfileobj(fi, fo, 1 << 20)
        dt = time.perf_counter() - t0
        if verified(out, meta):
            print(f"  [ok]   {name} ({size/1e6:.1f} MB, sha256 通过, {dt:.0f}s)")
            shutil.rmtree(cdir, ignore_errors=True)
            ok = True
            break
        # 只有"合并后校验失败"才清空重来
        print(f"  [retry] {name} 合并后校验未过 -> 清空分片重下")
        shutil.rmtree(cdir, ignore_errors=True)
        os.makedirs(cdir, exist_ok=True)
        if os.path.exists(out):
            os.remove(out)

    if not ok:
        left = [i for i in range(n) if not have(i)]
        print(f"  [FAIL] {name}: {MAX_ATTEMPT} 轮后仍缺 {len(left)}/{n} 分片"
              f"（分片已保留在 {cdir}，下次运行会续下）")
        raise SystemExit(2)


def main() -> int:
    os.makedirs(DEST, exist_ok=True)
    sp = spec()
    print(f"[dest] {DEST}")
    print(f"[base] {', '.join(BASES)}")
    want = [x for x in WANT if not ONLY or x in ONLY]
    t0 = time.perf_counter()
    fails = []
    for name in want:
        if name not in sp:
            print(f"  [warn] {name} 不在仓库列表")
            continue
        try:
            fetch(name, sp[name])
        except SystemExit:
            fails.append(name)
            print(f"  [cont] {name} 失败，跳过继续后面的文件")
    print(f"[done] {time.perf_counter()-t0:.0f}s"
          + (f" | 失败: {', '.join(fails)}" if fails else " | 全部通过"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
