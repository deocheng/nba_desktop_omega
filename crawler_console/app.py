# -*- coding: utf-8 -*-
"""NBA 爬虫控制台 —— 统一 Web 应用。

启动：
    cd <项目根>
    .venv/bin/python -m uvicorn crawler_console.app:app --host 127.0.0.1 --port 5599

功能：
- 全部现役爬虫的状态总览（pgrep 实时探测，含控制台外启动的进程）
- 一键启动/停止（启动前 BR 并发守卫：同一时刻仅允许 1 个 BR 爬虫，防屏蔽）
- 实时日志尾部查看
- 数据库覆盖率统计面板
- 盯梢巡检（watch_crawlers.py 一键运行）
"""
import os
import shlex
import subprocess
import time
from typing import Optional

import psycopg2
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from .registry import CRAWLERS, CDP_ENV, DB, LOG_DIR, PROJECT_ROOT, VENV_PY, WATCHER

app = FastAPI(title="NBA 爬虫控制台")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
BY_ID = {c["id"]: c for c in CRAWLERS}


# ── 进程探测 ─────────────────────────────────────────────────────
def _pgrep(pattern: str):
    """返回 [(pid, etime, cmd)]，兼容 | 分隔的多模式。"""
    procs = []
    for pat in pattern.split("|"):
        try:
            out = subprocess.run(["pgrep", "-f", pat], capture_output=True, text=True, timeout=5)
            for pid in out.stdout.split():
                try:
                    ps = subprocess.run(
                        ["ps", "-p", pid, "-o", "etime=,command="],
                        capture_output=True, text=True, timeout=5)
                    line = ps.stdout.strip()
                    if not line:
                        continue
                    etime, cmd = line.split(None, 1)
                    # 排除 pgrep/tail/grep 自身与控制台
                    if "pgrep" in cmd or "crawler_console" in cmd or "tail " in cmd:
                        continue
                    procs.append({"pid": int(pid), "etime": etime, "cmd": cmd})
                except Exception:
                    continue
        except Exception:
            continue
    # 去重
    seen, uniq = set(), []
    for p in procs:
        if p["pid"] not in seen:
            seen.add(p["pid"])
            uniq.append(p)
    return uniq


def _start_cmd(c) -> str:
    """该爬虫在控制台点「启动」时实际执行的完整命令（展示用）。"""
    if c["kind"] == "py":
        exe = VENV_PY
    else:
        exe = "bash"
    return " ".join([exe, os.path.join(PROJECT_ROOT, c["script"])] + list(c["args"]))


def _last_start_banner(c) -> Optional[str]:
    """日志里最近一次启动横幅（控制台启动时写入的 ===== [控制台启动 ...] ===== 行）。"""
    if not os.path.exists(c["log"]):
        return None
    try:
        # 只扫日志末尾 ~200KB，避免大日志全量 grep（4s 轮询 × 15 爬虫）
        tail = subprocess.run(["tail", "-c", "200000", c["log"]],
                              capture_output=True, text=True, timeout=5)
        lines = [l.strip() for l in tail.stdout.splitlines() if "控制台启动" in l]
        return lines[-1] if lines else None
    except Exception:
        return None


def _status(c):
    procs = _pgrep(c["pattern"])
    log_mtime = None
    log_age = None
    if os.path.exists(c["log"]):
        log_mtime = os.path.getmtime(c["log"])
        log_age = int(time.time() - log_mtime)
    return {
        "id": c["id"], "name": c["name"], "group": c["group"], "desc": c["desc"],
        "kind": c["kind"], "script": c["script"], "args": c["args"],
        "br": c["br"], "needs_cdp": c["needs_cdp"], "log": c["log"],
        "running": len(procs) > 0, "procs": procs, "log_age_s": log_age,
        # 详情字段
        "tables": c.get("tables", []),
        "cache": c.get("cache", ""),
        "url": c.get("url", ""),
        "start_cmd": _start_cmd(c),
        "last_start": _last_start_banner(c),
    }


def _running_br(exclude_id: Optional[str] = None):
    """当前正在运行的 BR 爬虫列表（并发守卫）。"""
    out = []
    for c in CRAWLERS:
        if not c["br"] or c["id"] == exclude_id:
            continue
        if _pgrep(c["pattern"]):
            out.append(c["id"])
    return out


def _cdp_alive() -> bool:
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


# ── API ──────────────────────────────────────────────────────────
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/crawlers")
def list_crawlers():
    return {"crawlers": [_status(c) for c in CRAWLERS],
            "cdp_alive": _cdp_alive(),
            "running_br": _running_br()}


@app.post("/api/crawlers/{cid}/start")
def start_crawler(cid: str, force: bool = Query(False), extra_args: str = Query("")):
    c = BY_ID.get(cid)
    if not c:
        raise HTTPException(404, f"未知爬虫: {cid}")
    if _pgrep(c["pattern"]):
        raise HTTPException(409, f"{c['name']} 已在运行中")

    # 🔴 BR 并发守卫：同一时刻仅允许 1 个 BR 爬虫（防屏蔽铁律）
    if c["br"] and not force:
        busy = _running_br(exclude_id=cid)
        if busy:
            names = ", ".join(BY_ID[b]["name"] for b in busy)
            raise HTTPException(
                423, f"BR 并发守卫：{names} 正在运行。同时打 BR 会翻倍请求频率、"
                     f"有触发屏蔽风险（今日已发生过一次）。如确认要并行请用 force=true。")

    if c["needs_cdp"] and not _cdp_alive():
        raise HTTPException(424, "Chrome CDP 9222 不可达：请先打开过 CF 验证的 Chrome"
                                 "（launch_chrome_cdp.sh）再启动该爬虫。")

    env = dict(os.environ)
    env.update(CDP_ENV)
    args = list(c["args"]) + (shlex.split(extra_args) if extra_args else [])
    if c["kind"] == "py":
        cmd = [VENV_PY, os.path.join(PROJECT_ROOT, c["script"])] + args
    else:
        cmd = ["bash", os.path.join(PROJECT_ROOT, c["script"])] + args

    logf = open(c["log"], "a")
    logf.write(f"\n===== [控制台启动 {time.strftime('%F %T')}] {' '.join(cmd)} =====\n")
    logf.flush()
    proc = subprocess.Popen(cmd, cwd=PROJECT_ROOT, env=env,
                            stdout=logf, stderr=subprocess.STDOUT,
                            start_new_session=True)
    return {"ok": True, "pid": proc.pid, "cmd": " ".join(cmd)}


@app.post("/api/crawlers/{cid}/stop")
def stop_crawler(cid: str):
    c = BY_ID.get(cid)
    if not c:
        raise HTTPException(404, f"未知爬虫: {cid}")
    procs = _pgrep(c["pattern"])
    if not procs:
        return {"ok": True, "stopped": [], "msg": "本来就没在运行"}
    stopped = []
    for p in procs:
        try:
            subprocess.run(["kill", str(p["pid"])], timeout=5)
            stopped.append(p["pid"])
        except Exception:
            pass
    return {"ok": True, "stopped": stopped}


@app.get("/api/crawlers/{cid}/log")
def crawler_log(cid: str, lines: int = Query(80, le=500)):
    c = BY_ID.get(cid)
    if not c:
        raise HTTPException(404, f"未知爬虫: {cid}")
    if not os.path.exists(c["log"]):
        return {"log": "(日志文件不存在)"}
    out = subprocess.run(["tail", "-n", str(lines), c["log"]],
                         capture_output=True, text=True, timeout=10)
    return {"log": out.stdout}


@app.get("/api/stats")
def stats():
    """DB 覆盖率统计。大表用 reltuples 估算避免全表扫。"""
    conn = psycopg2.connect(**DB)
    conn.autocommit = True
    cur = conn.cursor()
    r = {}

    def q(sql):
        cur.execute(sql)
        return cur.fetchone()

    try:
        r["shot_chart"] = dict(zip(
            ["balls", "pairs", "players"],
            q("SELECT count(*), count(DISTINCT player_id||'|'||season), count(DISTINCT player_id) FROM player_shot_chart")))
        r["shot_chart"]["total_pairs"] = q("SELECT count(*) FROM (SELECT DISTINCT player_id, season FROM player_shooting) t")[0]
        # 马刺进度
        r["shot_chart"]["sas_done"] = q("""
            SELECT count(DISTINCT psc.player_id||'|'||psc.season) FROM player_shot_chart psc
            WHERE EXISTS (SELECT 1 FROM player_shooting ps WHERE ps.player_id=psc.player_id
                          AND ps.season=psc.season AND ps.team='SAS')""")[0]
        r["shot_chart"]["sas_total"] = q("SELECT count(DISTINCT player_id||'|'||season) FROM player_shooting WHERE team='SAS'")[0]

        r["team_pbp"] = dict(zip(
            ["team_seasons", "teams"],
            q("SELECT count(DISTINCT team_abbr||'|'||season), count(DISTINCT team_abbr) FROM team_pbp_raw")))

        # 大表估算
        for tbl, key in [("play_by_play", "pbp_rows"), ("player_gamelog", "gamelog_rows"),
                         ("player_shooting", "shooting_rows"), ("player_lineups", "lineup_rows")]:
            try:
                est = q(f"SELECT reltuples::bigint FROM pg_class WHERE relname='{tbl}'")
                r[key] = int(est[0]) if est else None
            except Exception:
                r[key] = None

        r["dim_games"] = q("SELECT count(*) FROM dim_games")[0]
    finally:
        cur.close()
        conn.close()
    return r


@app.get("/api/watch")
def run_watcher():
    """一键巡检：运行盯梢脚本并返回输出。"""
    try:
        out = subprocess.run([WATCHER["python"], WATCHER["script"]],
                             capture_output=True, text=True, timeout=60)
        return {"output": out.stdout + ("\n" + out.stderr if out.stderr.strip() else "")}
    except subprocess.TimeoutExpired:
        return JSONResponse(status_code=504, content={"output": "巡检超时（60s）"})
