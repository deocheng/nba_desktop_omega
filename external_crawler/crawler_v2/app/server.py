#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.py — BR 爬虫套装独立 App 的后端（零第三方依赖，stdlib http.server）。

提供：
  GET  /                      控制面板 (index.html)
  GET  /api/status            适配器就绪状态 + DB 在线 + 运行任务数
  POST /api/crawl             {data_item, season, dry_run, only_br_ids?} 单数据项爬取
  POST /api/fuse              {season, dry_run} 融合数据报告
  POST /api/season            {season, dry_run} 赛季全量爬取 (daemon.runner)
  POST /api/resume            {} 根据 worklog 续爬
  GET  /api/jobs              工作日志（job 列表）
  GET  /api/job_log?id=...    某 job 的日志尾部
  POST /api/stop?id=...       停止运行中任务

每个爬取任务由 job_manager 以独立子进程执行，server 不阻塞、日志落盘可续。
"""
import atexit
import importlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
CRAWLER_V2 = HERE.parent
ROOT = CRAWLER_V2.parents[1]
for p in (str(CRAWLER_V2), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from job_manager import build_cmd, manager  # noqa: E402

PORT = int(os.environ.get("CRAWLER_APP_PORT", 5757))
INDEX = HERE / "index.html"

ADAPTERS = ["gamelog", "pbp", "espn", "nba_api"]
# 真实模块名（gamelog/pbp 带 br_ 前缀，espn/nba_api 无前缀）
ADAPTER_MODULE = {
    "gamelog": "adapters.br_gamelog_adapter",
    "pbp": "adapters.br_pbp_adapter",
    "espn": "adapters.espn_adapter",
    "nba_api": "adapters.nba_api_adapter",
}

SEASON_FLOOR = 1946  # NBA 首个赛季 1946-47；低于此值（含负数）一律视为非法赛季

def _valid_season(s) -> bool:
    # 仅校验下界，故意不设上界：避免「来年到了 2027 就用不了」的失效问题。
    # 必须是 int（JSON 数字经 json.loads 后为 int/float；这里拒绝 float 与非整数）。
    return isinstance(s, int) and s >= SEASON_FLOOR


# ============================ 常驻基础设施托管 ============================
# 把 CDP Chrome(9223) 与 crawler 看门狗都收进 App 内，由 server 直接 spawn/管理，
# 用户只需在面板点开关，无需任何外部终端。复用仓库现有 launch 脚本（自带代理剥离/自管理）。
CHROME_LAUNCHER = ROOT / "external_crawler" / "crawler" / "launch_chrome_cdp.sh"
WATCHDOG = ROOT / "external_crawler" / "crawler" / "crawler_watchdog.sh"
CHROME_PORT = 9223

_chrome_proc = None
_watchdog_proc = None


def _clean_env() -> dict:
    # 剥离代理：避免把 127.0.0.1 请求错发到代理；保留必要的 PATH/HOME/LANG
    env = dict(os.environ)
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
              "ALL_PROXY", "all_proxy", "no_proxy_override"):
        env.pop(k, None)
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    env.setdefault("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    env.setdefault("HOME", os.path.expanduser("~"))
    env.setdefault("LANG", "en_US.UTF-8")
    return env


def _chrome_alive() -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{CHROME_PORT}/json/version", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _chrome_pid() -> int | None:
    # 优先用我们记录的子进程；兜底按端口特征查（[r] 括号技巧避免 pgrep 匹配自身命令行）
    if _chrome_proc and _chrome_proc.poll() is None:
        return _chrome_proc.pid
    try:
        out = subprocess.run(["pgrep", "-f", "[r]emote-debugging-port=9223"],
                             capture_output=True, text=True)
        pids = [int(x) for x in out.stdout.split() if x.strip().isdigit()]
        return pids[0] if pids else None
    except Exception:
        return None


def _start_chrome() -> bool:
    global _chrome_proc
    if _chrome_alive():
        return True
    if _chrome_proc and _chrome_proc.poll() is None:
        return True
    if not CHROME_LAUNCHER.exists():
        return False
    try:
        _chrome_proc = subprocess.Popen(
            ["bash", str(CHROME_LAUNCHER)],
            stdout=open("/tmp/brcrawler_chrome.out", "ab"),
            stderr=subprocess.STDOUT,
            env=_clean_env(),
            start_new_session=True,
        )
    except Exception:
        return False
    for _ in range(30):           # 最多等 30s 让 Chrome 起来
        if _chrome_alive():
            return True
        time.sleep(1)
    return _chrome_alive()


def _stop_chrome() -> bool:
    global _chrome_proc
    if _chrome_proc and _chrome_proc.poll() is None:
        _chrome_proc.terminate()
        try:
            _chrome_proc.wait(timeout=5)
        except Exception:
            _chrome_proc.kill()
    _chrome_proc = None
    # 兜底清理：按端口特征杀残留（防止窗口未真正退出）
    try:
        subprocess.run(["pkill", "-f", "remote-debugging-port=9223"], check=False)
    except Exception:
        pass
    return not _chrome_alive()


def _watchdog_alive() -> bool:
    if _watchdog_proc and _watchdog_proc.poll() is None:
        return True
    # 兜底（外部启动的看门狗）：[c] 括号技巧避免 pgrep 匹配自身命令行
    try:
        out = subprocess.run(["pgrep", "-f", "[c]rawler_watchdog.sh"],
                             capture_output=True, text=True)
        return bool(out.stdout.strip())
    except Exception:
        return False


def _start_watchdog() -> bool:
    global _watchdog_proc
    if _watchdog_alive():
        return True
    if _watchdog_proc and _watchdog_proc.poll() is None:
        return True
    if not WATCHDOG.exists():
        return False
    try:
        _watchdog_proc = subprocess.Popen(
            ["bash", str(WATCHDOG)],
            stdout=open("/tmp/brcrawler_watchdog.out", "ab"),
            stderr=subprocess.STDOUT,
            env=_clean_env(),
            start_new_session=True,
        )
    except Exception:
        return False
    return True


def _stop_watchdog() -> bool:
    global _watchdog_proc
    # 1) 写 stop 标志，看门狗下一循环优雅退出（其 trap 会清理 PIDFILE）
    try:
        subprocess.run(["bash", str(WATCHDOG), "stop"], check=False, env=_clean_env())
    except Exception:
        pass
    # 2) 立即 SIGTERM 看门狗自身（触发 trap 立即退出，不必苦等 30s 循环）
    if _watchdog_proc and _watchdog_proc.poll() is None:
        try:
            _watchdog_proc.terminate()
            _watchdog_proc.wait(timeout=8)
        except Exception:
            _watchdog_proc.kill()
    _watchdog_proc = None
    # 3) 看门狗 stop 不负责杀 driver —— app 这边一并停掉，避免「停止看门狗」后仍在爬
    #    [r]/[c] 括号技巧避免 pgrep/pkill 匹配自身命令行
    try:
        subprocess.run(["pkill", "-f", "[r]ecrawl_2004_2026_autofill.sh"], check=False)
        subprocess.run(["pkill", "-f", "[c]rawl_br_gamelog.py"], check=False)
    except Exception:
        pass
    return not _watchdog_alive()


def _cleanup_children():
    # app 退出时清理：Chrome 直接终止；看门狗写 stop 标志优雅退出
    try:
        if _chrome_proc and _chrome_proc.poll() is None:
            _chrome_proc.terminate()
    except Exception:
        pass
    try:
        if _watchdog_proc and _watchdog_proc.poll() is None:
            subprocess.run(["bash", str(WATCHDOG), "stop"], check=False, env=_clean_env())
    except Exception:
        pass


atexit.register(_cleanup_children)


def _boot_chrome_async():
    # 非阻塞：app 启动即在后台拉起 Chrome，使面板「开箱即用」，无需外部终端
    threading.Thread(target=_start_chrome, daemon=True).start()


def probe_adapters() -> dict:
    out = {}
    for name in ADAPTERS:
        modname = ADAPTER_MODULE[name]
        try:
            mod = importlib.import_module(modname)
            doc = (mod.__doc__ or "")
            if "SCAFFOLD" in doc.upper():
                status = "scaffold"
                note = "接口脚手架，待接入真实解析（不编造）"
            else:
                status = "ready"
                note = "可运行" + ("（需 Chrome/9223）" if name == "pbp" else
                                    "（cache-first 可离线）" if name == "gamelog" else "")
        except Exception as e:  # noqa: BLE001
            status = "broken"
            note = f"导入失败: {type(e).__name__}: {e}"
        out[name] = {"status": status, "note": note}
    return out


def db_online() -> bool:
    try:
        import psycopg2
        from core.config import get_db_config
        conn = psycopg2.connect(connect_timeout=4, **get_db_config())
        conn.close()
        return True
    except Exception:
        return False


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        # 允许 file:// 源（原生 app 内加载）跨域调用本机 API
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, ctype="text/html; charset=utf-8"):
        if not path.exists():
            self._send_json({"error": "not found"}, 404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            self._send_file(INDEX)
            return
        if u.path == "/api/status":
            mgr = manager()
            running = sum(1 for j in mgr.list_jobs() if j.get("status") == "running")
            self._send_json({
                "adapters": probe_adapters(),
                "db_online": db_online(),
                "running_jobs": running,
                "workdir": str(HERE),
            })
            return
        if u.path == "/api/jobs":
            self._send_json({"jobs": manager().list_jobs()})
            return
        if u.path == "/api/job_log":
            q = parse_qs(u.query)
            jid = q.get("id", [""])[0]
            self._send_json({"log": manager().job_log(jid, n=120)})
            return
        if u.path == "/api/chrome/status":
            self._send_json({"alive": _chrome_alive(), "pid": _chrome_pid() or None,
                             "port": CHROME_PORT})
            return
        if u.path == "/api/watchdog/status":
            self._send_json({"alive": _watchdog_alive(),
                             "pid": (_watchdog_proc.pid if _watchdog_proc and _watchdog_proc.poll() is None else None)})
            return
        self._send_json({"error": "unknown route"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        body = self._body()
        mgr = manager()
        if u.path == "/api/crawl":
            di = body.get("data_item")
            if di not in ADAPTERS:
                self._send_json({"error": f"未知数据项: {di}"}, 400)
                return
            season = body.get("season")
            if season is not None and not _valid_season(season):
                self._send_json({"error": f"非法赛季（必须 ≥ {SEASON_FLOOR}）: {season}"}, 400)
                return
            job = mgr.submit("crawl", di, season,
                             bool(body.get("dry_run", True)), body.get("only_br_ids"))
            self._send_json({"job": job})
            return
        if u.path == "/api/fuse":
            season = body.get("season")
            if season is not None and not _valid_season(season):
                self._send_json({"error": f"非法赛季（必须 ≥ {SEASON_FLOOR}）: {season}"}, 400)
                return
            job = mgr.submit("fuse", "fusion", season,
                             bool(body.get("dry_run", True)))
            self._send_json({"job": job})
            return
        if u.path == "/api/season":
            season = body.get("season")
            if season is not None and not _valid_season(season):
                self._send_json({"error": f"非法赛季（必须 ≥ {SEASON_FLOOR}）: {season}"}, 400)
                return
            job = mgr.submit("season", "season", season,
                             bool(body.get("dry_run", True)))
            self._send_json({"job": job})
            return
        if u.path == "/api/resume":
            ids = mgr.resume()
            self._send_json({"resumed": ids, "count": len(ids)})
            return
        if u.path == "/api/stop":
            jid = body.get("id")
            ok = mgr.stop(jid) if jid else False
            self._send_json({"stopped": ok})
            return
        if u.path == "/api/chrome/start":
            self._send_json({"ok": _start_chrome(), "alive": _chrome_alive()})
            return
        if u.path == "/api/chrome/stop":
            self._send_json({"ok": _stop_chrome(), "alive": _chrome_alive()})
            return
        if u.path == "/api/watchdog/start":
            self._send_json({"ok": _start_watchdog(), "alive": _watchdog_alive()})
            return
        if u.path == "/api/watchdog/stop":
            self._send_json({"ok": _stop_watchdog(), "alive": _watchdog_alive()})
            return
        self._send_json({"error": "unknown route"}, 404)

    def log_message(self, fmt, *args):
        sys.stderr.write("[app] " + (fmt % args) + "\n")


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    # 启动即非阻塞拉起 Chrome，使面板开箱即用（无需外部终端）
    _boot_chrome_async()
    print(f"BR 爬虫套装 App 已启动: http://127.0.0.1:{PORT}")
    print(f"工作目录: {HERE}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在关闭…")
        server.shutdown()


if __name__ == "__main__":
    main()
