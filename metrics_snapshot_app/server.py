#!/usr/bin/env python3
"""
server.py -- stdlib-only control panel for the daily metrics snapshot suite.

Wraps two existing scripts (never re-implements them):
  scripts/daily_metrics_snapshot.py    DPM / RAPM / LEBRON daily snapshot
  scripts/enrich_metrics_team_abbr.py  team_abbr normalise + backfill

Only the Python standard library plus psycopg2 (already in the project venv,
used for read-only status queries). No web framework, so the app stays
installable and runnable offline.

Run:  <项目根>/.venv/bin/python \
          metrics_snapshot_app/server.py
Then open http://127.0.0.1:8791
"""
import io
import json
import os
import signal
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from job_manager import METRICS, ROOT, JobManager

PORT = 8791
APP_DIR = Path(__file__).resolve().parent


# --------------------------------------------------------------------- db
def db_config():
    env = {}
    dotenv = ROOT / ".env"
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return dict(host="127.0.0.1", port=5433, dbname="nba", user="postgres",
                password=env.get("DB_PASSWORD", ""))


def query(sql, params=None, many=False):
    import psycopg2
    conn = psycopg2.connect(**db_config())
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


def db_status():
    """Latest snapshot per metric + all snapshot dates. Never raises."""
    try:
        latest = query("SELECT max(snapshot_date) FROM public.player_metrics_daily")
        latest_date = latest[0].isoformat() if latest and latest[0] else None
    except Exception as exc:  # noqa: BLE001
        return {"db_online": False, "error": str(exc)}

    metrics = {}
    if latest_date:
        rows = query("""
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

    dates = query("""
        SELECT snapshot_date, count(*) AS rows
        FROM public.player_metrics_daily
        GROUP BY snapshot_date ORDER BY snapshot_date DESC LIMIT 60
    """, many=True) or []

    try:
        total = query("SELECT count(*) FROM public.player_metrics_daily")[0]
    except Exception:  # noqa: BLE001
        total = 0

    return {
        "db_online": True,
        "latest_date": latest_date,
        "total_rows": total,
        "metrics": metrics,
        "dates": [{"date": d["snapshot_date"].isoformat(), "rows": d["rows"]}
                  for d in dates],
        "missing": [m for m in METRICS if m not in metrics],
    }


def history(player_key=None, metric=None):
    """Per-date counts, or one player's time series when player_key is given."""
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
        return query(sql, params, many=True) or []

    sql = """
        SELECT snapshot_date, metric, count(*) AS rows
        FROM public.player_metrics_daily
        GROUP BY snapshot_date, metric
        ORDER BY snapshot_date DESC, metric
        LIMIT 400
    """
    rows = query(sql, many=True) or []
    for r in rows:
        r["snapshot_date"] = r["snapshot_date"].isoformat()
    return rows


def search_players(q, limit=25):
    like = f"%{q}%"
    rows = query("""
        SELECT DISTINCT player_key, player_name, nba_id
        FROM public.player_metrics_daily
        WHERE player_name ILIKE %s
        ORDER BY player_name LIMIT %s
    """, (like, limit), many=True) or []
    return rows


# ------------------------------------------------------------------ server
MANAGER = JobManager()


class Handler(BaseHTTPRequestHandler):
    server_version = "MetricsSnapshotPanel/1.0"

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
                st = db_status()
                st["running"] = sum(
                    1 for j in MANAGER.list_jobs() if j.get("status") == "running")
                today = __import__("datetime").date.today().isoformat()
                st["today"] = today
                return self._send(200, st)
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
                return self._send(200, {"rows": history(pk, metric)})
            if path == "/api/search":
                q = (qs.get("q") or [""])[0]
                if len(q) < 2:
                    return self._send(200, {"rows": []})
                return self._send(200, {"rows": search_players(q)})
            return self._send(404, {"error": f"no route for {path}"})
        except Exception as exc:  # noqa: BLE001
            return self._send(500, {"error": str(exc)})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        body = self._body()
        try:
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
            if path == "/api/resume":
                return self._send(200, {"new_jobs": MANAGER.resume()})
            if path == "/api/stop":
                return self._send(200, MANAGER.stop(body.get("job_id")))
            if path == "/api/stop_server":
                # 优雅自停：延迟发 SIGTERM 给自身，确保先回 200 再退出。
                threading.Timer(0.2, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
                return self._send(200, {"ok": True, "msg": "server stopping"})
            return self._send(404, {"error": f"no route for {path}"})
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            return self._send(500, {"error": str(exc)})


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[panel] serving http://127.0.0.1:{PORT}")
    print(f"[panel] project root: {ROOT}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[panel] bye")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
