#!/usr/bin/env python3
"""
server.py -- stdlib-only UNIFIED control panel for three crawler families:

  1. Metrics snapshot  (DPM / RAPM / LEBRON daily snapshot -> nba DB)
  2. FIBA             (fiba_scraper daily + batch -> fiba DB)
  3. BR crawler       (launch / stop the compiled BRCrawler.app via osascript)

This is CONTROL-ONLY: it never re-implements the crawlers. It shells out to
the existing, validated scripts (see job_manager.py) and to osascript for BR.
Stdlib + psycopg2 (already in the project venv) for read-only status queries.

Run:  <项目根>/.venv/bin/python \
          unified_crawler_app/server.py
Then open http://127.0.0.1:8793
"""
import io
import json
import os
import signal
import subprocess
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from job_manager import FIBA_DEFAULT_COMP, FIBA_DEFAULT_DAYS, METRICS, ROOT, JobManager

PORT = 8793
APP_DIR = Path(__file__).resolve().parent

# BR compiled app (launched / stopped via osascript; never modified here).
BR_APP = str(ROOT / "external_crawler" / "crawler_v2" / "app" / "BRCrawler.app")
BR_APP_NAME = "BR Crawler"


# --------------------------------------------------------------------- db
def db_config(dbname="nba"):
    env = {}
    dotenv = ROOT / ".env"
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return dict(host="127.0.0.1", port=5433, dbname=dbname, user="postgres",
                password=env.get("DB_PASSWORD", ""))


def query(dbname, sql, params=None, many=False):
    import psycopg2
    conn = psycopg2.connect(**db_config(dbname))
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SET max_parallel_workers_per_gather=0")
            cur.execute("SET statement_timeout = 30000")
            cur.execute(sql, params)
            if many:
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, r)) for r in cur.fetchall()]
            return cur.fetchone()
    finally:
        conn.close()


def db_online(dbname):
    try:
        query(dbname, "SELECT 1")
        return True
    except Exception:  # noqa: BLE001
        return False


# ----------------------------------------------------------- metrics (nba)
def metrics_status():
    try:
        latest = query("nba",
                       "SELECT max(snapshot_date) FROM public.player_metrics_daily")
        latest_date = latest[0].isoformat() if latest and latest[0] else None
    except Exception as exc:  # noqa: BLE001
        return {"db_online": False, "error": str(exc)}

    metrics = {}
    if latest_date:
        rows = query("nba", """
            SELECT metric,
                   count(*) AS rows,
                   count(*) FILTER (WHERE team_abbr IS NOT NULL
                                      AND trim(team_abbr) <> '') AS with_team,
                   round(min(val)::numeric, 3) AS min_val,
                   round(max(val)::numeric, 3) AS max_val,
                   round(avg(val)::numeric, 3) AS avg_val
            FROM public.player_metrics_daily
            WHERE snapshot_date = %s
            GROUP BY metric ORDER BY metric
        """, (latest_date,), many=True)
        for r in rows:
            metrics[r["metric"]] = {
                "rows": r["rows"],
                "with_team": r["with_team"],
                "coverage": (r["with_team"] / r["rows"]) if r["rows"] else 0,
                "min_val": float(r["min_val"]) if r["min_val"] is not None else None,
                "max_val": float(r["max_val"]) if r["max_val"] is not None else None,
                "avg_val": float(r["avg_val"]) if r["avg_val"] is not None else None,
            }
    total = 0
    try:
        total = query("nba", "SELECT count(*) FROM public.player_metrics_daily")[0]
    except Exception:  # noqa: BLE001
        pass
    return {
        "db_online": True,
        "latest_date": latest_date,
        "total_rows": total,
        "metrics": metrics,
        "missing": [m for m in METRICS if m not in metrics],
    }


def metrics_history(player_key=None, metric=None):
    if player_key:
        sql = """
            SELECT snapshot_date, metric, player_name, team_abbr,
                   round(val::numeric, 4) AS val,
                   round(val_o::numeric, 4) AS val_o,
                   round(val_d::numeric, 4) AS val_d
            FROM public.player_metrics_daily
            WHERE player_key = %s
        """
        params = [player_key]
        if metric:
            sql += " AND metric = %s"
            params.append(metric)
        sql += " ORDER BY metric, snapshot_date"
        return query("nba", sql, params, many=True) or []
    rows = query("nba", """
        SELECT snapshot_date, metric, count(*) AS rows
        FROM public.player_metrics_daily
        GROUP BY snapshot_date, metric
        ORDER BY snapshot_date DESC, metric LIMIT 400
    """, many=True) or []
    for r in rows:
        r["snapshot_date"] = r["snapshot_date"].isoformat()
    return rows


def metrics_search(q, limit=25):
    like = f"%{q}%"
    return query("nba", """
        SELECT DISTINCT player_key, player_name, nba_id
        FROM public.player_metrics_daily
        WHERE player_name ILIKE %s
        ORDER BY player_name LIMIT %s
    """, (like, limit), many=True) or []


# --------------------------------------------------------------- fiba (fiba)
def fiba_status():
    if not db_online("fiba"):
        return {"db_online": False,
                "error": "fiba 数据库不可达（尚未首次抓取？）"}
    try:
        games = query("fiba", "SELECT count(*) FROM games")[0]
        pbp_loaded = query("fiba",
                           "SELECT count(*) FROM games WHERE pbp_loaded")[0]
        pbp_rows = query("fiba", "SELECT count(*) FROM play_by_play")[0]
        comps = query("fiba",
                      "SELECT count(*) FROM competitions")[0]
        players = query("fiba", "SELECT count(*) FROM players")[0]
        gps = query("fiba", "SELECT count(*) FROM game_player_stats")[0]
        comps_list = query("fiba",
                           "SELECT competition_id, official_name, season "
                           "FROM competitions ORDER BY competition_id",
                           many=True) or []
    except Exception as exc:  # noqa: BLE001
        return {"db_online": False, "error": str(exc)}
    return {
        "db_online": True,
        "games": games,
        "games_pbp_loaded": pbp_loaded,
        "play_by_play_rows": pbp_rows,
        "competitions": comps,
        "competitions_list": [
            {"id": c["competition_id"], "name": c["official_name"],
             "season": c["season"]}
            for c in comps_list
        ],
        "players": players,
        "game_player_stats": gps,
    }


# -------------------------------------------------------------------- br
def br_is_running():
    """True if the compiled BR Crawler app is currently open."""
    try:
        out = subprocess.run(
            ["osascript", "-e", f'application "{BR_APP_NAME}" is running'],
            capture_output=True, text=True, timeout=8)
        return out.stdout.strip().lower() == "true"
    except Exception:  # noqa: BLE001
        # Fallback: pgrep for the app bundle name.
        try:
            r = subprocess.run(["pgrep", "-f", BR_APP_NAME],
                               capture_output=True, timeout=8)
            return r.returncode == 0
        except Exception:  # noqa: BLE001
            return False


def br_start():
    if br_is_running():
        return {"ok": True, "already_running": True}
    subprocess.Popen(["open", BR_APP])
    return {"ok": True, "launched": True}


def br_stop():
    if not br_is_running():
        return {"ok": True, "already_stopped": True}
    subprocess.run(["osascript", "-e",
                    f'tell application "{BR_APP_NAME}" to quit'],
                   capture_output=True, text=True, timeout=15)
    return {"ok": True, "quit_sent": True}


# ----------------------------------------------------------- autostart (macOS)
LAUNCH_AGENTS = os.path.expanduser("~/Library/LaunchAgents")
AUTOSTART_PLIST = os.path.join(LAUNCH_AGENTS, "com.nbacore.unifiedcrawler.plist")
APP_EXE = str(ROOT / "unified_crawler_app" / "UnifiedCrawler.app"
              / "Contents" / "MacOS" / "UnifiedCrawler")


def _autostart_plist():
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.nbacore.unifiedcrawler</string>
  <key>ProgramArguments</key>
  <array>
    <string>{APP_EXE}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>ProcessType</key>
  <string>Interactive</string>
</dict>
</plist>
"""


def autostart_status():
    return {"enabled": os.path.exists(AUTOSTART_PLIST),
            "plist": AUTOSTART_PLIST}


def autostart_set(enabled):
    """Write/remove a user LaunchAgent so the panel auto-starts at login.

    Non-destructive: only touches a plist in the user's ~/Library/LaunchAgents.
    If launchctl load is blocked by the sandbox, we still keep the plist and
    tell the user the manual fallback (System Settings -> Login Items).
    """
    if enabled:
        os.makedirs(LAUNCH_AGENTS, exist_ok=True)
        Path(AUTOSTART_PLIST).write_text(_autostart_plist(), encoding="utf-8")
        r = subprocess.run(["launchctl", "load", "-w", AUTOSTART_PLIST],
                           capture_output=True, text=True, timeout=15)
        note = ""
        if r.returncode != 0:
            note = ("plist 已写入，但 launchctl load 失败"
                    f"（{r.stderr.strip() or '权限/沙箱'}）。请注销重登，或在"
                    "系统设置 → 通用 → 登录项 手动添加「NBA 爬虫总控」。")
        return {"ok": True, "enabled": True, "note": note}
    subprocess.run(["launchctl", "unload", AUTOSTART_PLIST],
                   capture_output=True, text=True, timeout=15)
    try:
        os.remove(AUTOSTART_PLIST)
    except OSError:
        pass
    return {"ok": True, "enabled": False}


# ------------------------------------------------------------------ server
MANAGER = JobManager()


class Handler(BaseHTTPRequestHandler):
    server_version = "NBACrawlerUnified/1.0"

    def log_message(self, fmt, *args):  # keep the console readable
        if "/api/job_log" not in (self.path or ""):
            super().log_message(fmt, *args)

    # -- helpers -----------------------------------------------------------
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, default=str)
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path, ctype):
        data = Path(path).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        raw = self.rfile.read(n).decode("utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    # -- routes ------------------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path, qs = parsed.path, urllib.parse.parse_qs(parsed.query)
        try:
            if path in ("/", "/index.html"):
                return self._send_file(APP_DIR / "index.html",
                                       "text/html; charset=utf-8")
            if path == "/api/status":
                ms = metrics_status()
                fs = fiba_status()
                bs = {"running": br_is_running()}
                ms["running"] = sum(
                    1 for j in MANAGER.list_jobs() if j.get("status") == "running")
                ms["today"] = __import__("datetime").date.today().isoformat()
                ms["fiba"] = fs
                ms["br"] = bs
                return self._send(200, ms)
            if path == "/api/jobs":
                return self._send(200, {"jobs": MANAGER.list_jobs()})
            if path == "/api/job_log":
                jid = (qs.get("id") or [""])[0]
                body = MANAGER.get_log(jid)
                if body is None:
                    return self._send(404, {"error": "unknown job id"})
                return self._send(200, {"id": jid, "log": body})
            if path == "/api/history":
                pk = (qs.get("player_key") or [None])[0]
                metric = (qs.get("metric") or [None])[0]
                return self._send(200, {"rows": metrics_history(pk, metric)})
            if path == "/api/search":
                q = (qs.get("q") or [""])[0]
                if len(q) < 2:
                    return self._send(200, {"rows": []})
                return self._send(200, {"rows": metrics_search(q)})
            if path == "/api/fiba_status":
                return self._send(200, fiba_status())
            if path == "/api/br_status":
                return self._send(200, {"running": br_is_running()})
            if path == "/api/autostart_status":
                return self._send(200, autostart_status())
            return self._send(404, {"error": f"no route for {path}"})
        except Exception as exc:  # noqa: BLE001
            return self._send(500, {"error": str(exc)})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        body = self._body()
        try:
            # ---- metrics snapshot ----
            if path == "/api/snapshot":
                metrics = body.get("metrics") or list(METRICS)
                job = MANAGER.submit("snapshot", {
                    "metrics": metrics,
                    "date": body.get("date"),
                    "dry_run": body.get("dry_run", False),
                    "no_fetch": body.get("no_fetch", False),
                    "limit": body.get("limit", 0),
                    "lebron_season": body.get("lebron_season", "2025-26"),
                })
                return self._send(200, job)
            if path == "/api/enrich":
                job = MANAGER.submit("enrich", {
                    "date": body.get("date"),
                    "dry_run": body.get("dry_run", False),
                })
                return self._send(200, job)
            # ---- FIBA ----
            if path == "/api/fiba_daily":
                job = MANAGER.submit("fiba_daily", {
                    "competition_id": body.get("competition_id") or FIBA_DEFAULT_COMP,
                    "days": body.get("days") or FIBA_DEFAULT_DAYS,
                    "dry_run": body.get("dry_run", False),
                    "no_archive": body.get("no_archive", False),
                })
                return self._send(200, job)
            if path == "/api/fiba_batch":
                job = MANAGER.submit("fiba_batch", {
                    "competition_id": body.get("competition_id") or FIBA_DEFAULT_COMP,
                    "limit": body.get("limit", 0),
                    "no_leaders": body.get("no_leaders", False),
                    "no_archive": body.get("no_archive", False),
                })
                return self._send(200, job)
            # ---- BR ----
            if path == "/api/br_start":
                return self._send(200, br_start())
            if path == "/api/br_stop":
                return self._send(200, br_stop())
            if path == "/api/autostart":
                return self._send(200, autostart_set(bool(body.get("enabled", False))))
            # ---- shared ----
            if path == "/api/resume":
                return self._send(200, {"new_jobs": MANAGER.resume()})
            if path == "/api/stop":
                return self._send(200, MANAGER.stop(body.get("job_id")))
            if path == "/api/stop_server":
                threading.Timer(0.2, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
                return self._send(200, {"ok": True, "msg": "server stopping"})
            return self._send(404, {"error": f"no route for {path}"})
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            return self._send(500, {"error": str(exc)})


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[unified] serving http://127.0.0.1:{PORT}")
    print(f"[unified] project root: {ROOT}")
    print(f"[unified] BR app: {BR_APP}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[unified] bye")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
