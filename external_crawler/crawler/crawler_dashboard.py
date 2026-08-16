#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NBA 爬虫控制面板（本地 Web UI，纯标准库，无外部依赖）
---------------------------------------------------------------------------
和「YouTube 下载器」同形态：在浏览器打开 http://127.0.0.1:8787 即可看到
爬虫状态、当前季、实时日志，并可用按钮 启动 / 停止 爬虫。

设计：
  - 后端用 http.server 起一个本地服务（不需要 Flask）。
  - 爬虫本身是一个【独立常驻进程】：后端通过 os.setsid 把它放进自己的
    会话/进程组，从而【脱离 WorkBuddy 任务树】（平台 killpg 回收只命中
    一组，不会连累爬虫）。
  - 停止 = 向爬虫进程组发 SIGTERM（supervisor + driver 一起停，Chrome 保留复用）。
  - DB 行数用 psql 子进程读（本地库，无需在面板里装驱动）。
"""
import os
import sys
import json
import time
import subprocess
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13"
CRAWLER = os.path.join(ROOT, "external_crawler", "crawler")
STANDALONE = os.path.join(CRAWLER, "start_crawler_standalone.sh")
MASTER_LOG = os.path.join(ROOT, "logs", "recrawl_2004_2026_autofill.log")
STANDALONE_LOG = os.path.join(ROOT, "logs", "standalone_crawler.out")
ENV_FILE = os.path.join(ROOT, ".env")
PORT = int(os.environ.get("PORT", "8787"))

# psql 候选路径
PSQL_CANDIDATES = [
    "/opt/homebrew/opt/postgresql@18/bin/psql",
    "/opt/homebrew/bin/psql",
    "/usr/local/bin/psql",
    "psql",
]

_db_cache = {"rows": None, "ts": 0.0}


def _psql_bin():
    for p in PSQL_CANDIDATES:
        if p == "psql":
            try:
                subprocess.run(["psql", "--version"], capture_output=True, timeout=5)
                return "psql"
            except Exception:
                continue
        if os.path.exists(p):
            return p
    return None


def load_db_conf():
    cfg = {}
    try:
        with open(ENV_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("DB_") or line.startswith("PG"):
                    if "=" in line:
                        k, v = line.split("=", 1)
                        cfg[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return cfg


def _run(cmd, timeout=12, env=None):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    except Exception as e:
        class _R:  # noqa
            returncode = -1
            stdout = ""
            stderr = str(e)
        return _R()


# ───────────────────────────── 状态探测 ─────────────────────────────
def crawler_procs_lines():
    """返回所有爬虫相关进程的 cmdline 行。"""
    r = _run(["pgrep", "-af", "crawl_br_gamelog.py"])
    out = r.stdout if r.returncode == 0 else ""
    r2 = _run(["pgrep", "-af", "start_crawler_standalone.sh"])
    if r2.returncode == 0:
        out += "\n" + r2.stdout
    return out.strip().splitlines()


def is_running():
    r = _run(["pgrep", "-f", "crawl_br_gamelog.py"])
    if r.returncode == 0:
        return True
    r = _run(["pgrep", "-f", "start_crawler_standalone.sh"])
    return r.returncode == 0


def current_season():
    r = _run(["pgrep", "-af", "crawl_br_gamelog.py"])
    if r.returncode == 0:
        m = re.search(r"--season\s+(\d{4})", r.stdout)
        if m:
            return m.group(1)
    # 退而求其次：从 master log 末尾推断当前季。
    # 注意：recrawl 日志对 1989/1988 等季用方括号格式 "[1989] attempt 1/6 START" /
    # "[selfcheck 1990]" 打印，而早季用旧格式 "season 1990"；两种都要识别，
    # 否则面板会卡在最后一个 "season NNNN" 头部（显示滞后 bug）。
    tail = tail_file(MASTER_LOG, 400)
    for line in reversed(tail.splitlines()):
        m = re.search(
            r"\[(\d{4})\]\s*(attempt|START|selfcheck|智能补齐|FAILURES|"
            r"已达最大重试|BYPASSED|skip)",
            line,
        )
        if m:
            return m.group(1)
        m = re.search(r"season\s+(\d{4})", line, re.I)
        if m:
            return m.group(1)
    return None


def tail_file(path, n=80):
    if not os.path.exists(path):
        return ""
    r = _run(["tail", "-n", str(n), path])
    return r.stdout if r.returncode == 0 else ""


def db_rows():
    now = time.time()
    if _db_cache["rows"] is not None and now - _db_cache["ts"] < 30:
        return _db_cache["rows"]
    cfg = load_db_conf()
    psql = _psql_bin()
    rows = None
    if cfg and psql:
        env = dict(os.environ, PGPASSWORD=cfg.get("DB_PASSWORD", ""))
        sql = "SELECT count(*) FROM player_gamelog;"
        r = _run([psql, "-h", cfg.get("DB_HOST", "localhost"),
                  "-p", cfg.get("DB_PORT", "5433"),
                  "-U", cfg.get("DB_USER", "postgres"),
                  "-d", cfg.get("DB_NAME", "nba"),
                  "-t", "-A", "-c", sql], env=env, timeout=10)
        if r.returncode == 0:
            rows = r.stdout.strip()
    _db_cache["rows"] = rows
    _db_cache["ts"] = now
    return rows


def get_status():
    running = is_running()
    season = current_season() if running else None
    rows = db_rows()
    return {
        "running": running,
        "current_season": season,
        "db_rows": rows,
        "pg_port": load_db_conf().get("DB_PORT", "5433"),
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


# ───────────────────────────── 启停控制 ─────────────────────────────
def start_crawler():
    if is_running():
        return {"ok": False, "msg": "爬虫已在运行中，无需重复启动。"}
    env = dict(os.environ, _CRAWLER_DETACHED="1")
    logf = open(STANDALONE_LOG, "a")
    try:
        subprocess.Popen(["/bin/bash", STANDALONE],
                         env=env, start_new_session=True,
                         stdout=logf, stderr=logf)
        return {"ok": True, "msg": "已启动爬虫（独立会话，脱离本面板进程）。"}
    except Exception as e:
        return {"ok": False, "msg": "启动失败: %s" % e}


def stop_crawler():
    # 先停 supervisor（否则会重启 driver），再停 driver
    _run(["pkill", "-f", "start_crawler_standalone.sh"])
    time.sleep(1)
    _run(["pkill", "-f", "recrawl_2004_2026_autofill.sh"])
    _run(["pkill", "-f", "crawl_br_gamelog.py"])
    return {"ok": True, "msg": "已发送停止信号（supervisor + driver）。Chrome 保留以便复用。"}


def crawl_season(season):
    """定向补爬某一季（先停当前，避免双 driver 抢 Chrome/DB）。"""
    season = str(season).strip()
    if not re.fullmatch(r"\d{4}", season):
        return {"ok": False, "msg": "季份格式应为 4 位数字，例如 2003。"}
    if is_running():
        stop_crawler()
        time.sleep(2)
    env = dict(os.environ, _CRAWLER_DETACHED="1", SEASONS_OVERRIDE=season)
    logf = open(STANDALONE_LOG, "a")
    try:
        subprocess.Popen(["/bin/bash", STANDALONE],
                         env=env, start_new_session=True,
                         stdout=logf, stderr=logf)
        return {"ok": True, "msg": "已启动【%s 季】定向补爬（独立会话，跑完即停）。" % season}
    except Exception as e:
        return {"ok": False, "msg": "启动失败: %s" % e}


# ───────────────────────────── HTTP 服务 ─────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a, **k):  # 静默默认访问日志
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            self._send(200, INDEX_HTML, "text/html; charset=utf-8")
        elif u.path == "/api/status":
            self._send(200, json.dumps(get_status(), ensure_ascii=False))
        elif u.path == "/api/log":
            q = parse_qs(u.query)
            n = int(q.get("n", ["100"])[0])
            parts = []
            if os.path.exists(STANDALONE_LOG):
                parts.append("===== standalone_crawler.out =====")
                parts.append(tail_file(STANDALONE_LOG, n))
            if os.path.exists(MASTER_LOG):
                parts.append("===== recrawl_2004_2026_autofill.log (tail) =====")
                parts.append(tail_file(MASTER_LOG, n))
            self._send(200, "\n".join(parts))
        elif u.path == "/api/procs":
            self._send(200, json.dumps({"procs": crawler_procs_lines()}))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/api/start":
            self._send(200, json.dumps(start_crawler(), ensure_ascii=False))
        elif u.path == "/api/stop":
            self._send(200, json.dumps(stop_crawler(), ensure_ascii=False))
        elif u.path == "/api/crawl-season":
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b"{}"
                data = json.loads(raw.decode("utf-8")) if raw else {}
            except Exception:
                data = {}
            self._send(200, json.dumps(crawl_season(data.get("season", "")), ensure_ascii=False))
        else:
            self._send(404, json.dumps({"error": "not found"}))


def main():
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as e:
        if "Address already in use" in str(e):
            print("端口 %d 已被占用（面板可能已在运行），本实例退出。" % PORT, flush=True)
            return
        raise
    print("NBA 爬虫控制面板已启动 -> http://127.0.0.1:%d" % PORT, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NBA 爬虫控制面板</title>
<style>
  :root{
    --bg:#0f1420; --panel:#171e2e; --panel2:#1e2740; --line:#2a3650;
    --txt:#e6ecf5; --muted:#8da0c0; --accent:#4f8cff; --green:#39d98a;
    --red:#ff6b6b; --amber:#ffb454;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--txt);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif}
  .wrap{max-width:980px;margin:0 auto;padding:24px 18px 60px}
  header{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px}
  h1{font-size:20px;margin:0;letter-spacing:.5px}
  .badge{font-size:12px;padding:4px 10px;border-radius:999px;border:1px solid var(--line);color:var(--muted)}
  .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:18px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px}
  .card .label{font-size:12px;color:var(--muted);margin-bottom:6px}
  .card .value{font-size:24px;font-weight:600}
  .dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px;vertical-align:middle}
  .on{background:var(--green);box-shadow:0 0 10px var(--green)}
  .off{background:var(--red)}
  .controls{display:flex;gap:12px;margin-bottom:18px}
  button{flex:1;padding:13px 0;font-size:15px;font-weight:600;border:none;border-radius:12px;
    cursor:pointer;transition:.15s;color:#fff}
  .start{background:linear-gradient(135deg,#3a7bff,#5a9bff)}
  .start:hover{filter:brightness(1.1)}
  .stop{background:linear-gradient(135deg,#c0392b,#e74c3c)}
  .stop:hover{filter:brightness(1.1)}
  .target{background:linear-gradient(135deg,#8a5cf6,#a87bff)}
  .target:hover{filter:brightness(1.1)}
  button:disabled{opacity:.4;cursor:not-allowed}
  .season-row{display:flex;gap:12px;margin-bottom:18px;align-items:center}
  .season-row input{flex:1;padding:12px 14px;font-size:15px;border-radius:12px;border:1px solid var(--line);
    background:var(--panel);color:var(--txt);outline:none}
  .season-row input:focus{border-color:var(--accent)}
  .season-row button{flex:0 0 160px}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}
  .panel .ph{display:flex;align-items:center;justify-content:space-between;
    padding:12px 16px;border-bottom:1px solid var(--line);background:var(--panel2)}
  .panel .ph span{font-size:13px;color:var(--muted)}
  pre{margin:0;padding:14px 16px;max-height:460px;overflow:auto;
    font-family:"SF Mono",ui-monospace,Menlo,Consolas,monospace;font-size:12.5px;line-height:1.55;color:#cfe0ff}
  #msg{margin:10px 0;font-size:13px;color:var(--amber);min-height:18px}
  .tip{margin-top:18px;font-size:12px;color:var(--muted);line-height:1.7}
  .tip code{background:var(--panel2);padding:2px 6px;border-radius:6px;color:#cfe0ff}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>🏀 NBA 爬虫控制面板</h1>
    <span class="badge" id="clock">--:--:--</span>
  </header>

  <div class="grid">
    <div class="card">
      <div class="label">运行状态</div>
      <div class="value"><span class="dot off" id="stDot"></span><span id="stTxt">检测中…</span></div>
    </div>
    <div class="card">
      <div class="label">当前爬取季</div>
      <div class="value" id="seasonTxt">--</div>
    </div>
    <div class="card">
      <div class="label">player_gamelog 总行数</div>
      <div class="value" id="rowsTxt">--</div>
    </div>
  </div>

  <div class="controls">
    <button class="start" id="btnStart">▶ 全量续补（自主补齐所有缺口季）</button>
    <button class="stop"  id="btnStop">■ 停止爬虫</button>
  </div>
  <div class="season-row">
    <input id="seasonInput" type="text" inputmode="numeric" placeholder="指定某一季，如 2003（仅补这一季）" />
    <button class="target" id="btnSeason">🎯 补指定季</button>
  </div>
  <div id="msg"></div>

  <div class="panel">
    <div class="ph"><span>实时日志（standalone + recrawl master）</span><span id="logMeta"></span></div>
    <pre id="log">加载中…</pre>
  </div>

  <div class="tip">
    说明：本面板是<strong>独立进程</strong>，爬虫经 <code>os.setsid</code> 脱离面板运行，
    关闭浏览器/重启面板都不会影响爬虫。停止只杀 supervisor+driver，保留 Chrome 以便下次复用。<br>
    重开面板：浏览器访问 <code>http://127.0.0.1:8787</code>。
  </div>
</div>

<script>
const $ = id => document.getElementById(id);
let timer = null;

async function refresh(){
  try{
    const r = await fetch('/api/status'); const s = await r.json();
    const dot = $('stDot'), txt = $('stTxt');
    if(s.running){ dot.className='dot on'; txt.textContent='运行中'; }
    else { dot.className='dot off'; txt.textContent='空闲'; }
    $('seasonTxt').textContent = s.current_season || (s.running? '检测中…':'—');
    $('rowsTxt').textContent = s.db_rows!=null ? Number(s.db_rows).toLocaleString() : '无法连接 DB';
    $('btnStart').disabled = s.running;
    $('btnStop').disabled = !s.running;
    $('clock').textContent = s.ts;
  }catch(e){ /* ignore */ }
  // 日志
  try{
    const lr = await fetch('/api/log?n=120'); const t = await lr.text();
    $('log').textContent = t || '(无日志)';
    $('log').scrollTop = $('log').scrollHeight;
    const lines = t.split('\\n').length;
    $('logMeta').textContent = lines + ' 行';
  }catch(e){}
}

async function post(path){
  const r = await fetch(path, {method:'POST'}); const j = await r.json();
  $('msg').textContent = (j.ok?'✅ ':'⚠️ ') + (j.msg||'');
  setTimeout(()=>{ $('msg').textContent=''; }, 6000);
  refresh();
}

$('btnStart').onclick = ()=>post('/api/start');
$('btnStop').onclick  = ()=>{ if(confirm('确定停止爬虫？当前季进度会保留（下次续跑）。')) post('/api/stop'); };

async function postJson(path, obj){
  const r = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(obj)});
  const j = await r.json();
  $('msg').textContent = (j.ok?'✅ ':'⚠️ ') + (j.msg||'');
  setTimeout(()=>{ $('msg').textContent=''; }, 6000);
  refresh();
}
$('btnSeason').onclick = ()=>{
  const s = $('seasonInput').value.trim();
  if(!s){ $('msg').textContent='⚠️ 请输入季份（4 位数字，如 2003）'; return; }
  if(confirm('将先停止当前爬虫，然后只补 '+s+' 季？')) postJson('/api/crawl-season', {season:s});
};

refresh();
timer = setInterval(refresh, 2500);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
