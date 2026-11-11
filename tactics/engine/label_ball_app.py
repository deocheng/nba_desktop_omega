#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""label_ball_app.py — 路径 B 的钥匙：浏览器球标注工具（点哪儿是哪儿）。

背景
----
A4.12 已证明「AI 自标」不可靠（REJECT_SELF_AS_ANNOTATOR）。
路径 B（少样本域适应）需要**你手标**少量帧（每个新域 ~30–50 帧）作可信真值。
本工具起一个本地 HTTP 服务，浏览器打开后逐帧点球心（或标「无球」），存 JSON。

用法
----
  python engine/label_ball_app.py --clip sas_nop --n 50 [--port 8766]
  python engine/label_ball_app.py --clip sas_det --n 50
然后浏览器打开 http://127.0.0.1:8766

操作
----
  鼠标点画面 = 标球心（预填一个检测器建议点，点附近即采纳/微调）
  n 键 / 「无球」按钮 = 该帧无球
  → / 空格 = 下一帧    ← = 上一帧
  「保存」= 写 action_work/validate/<clip>_ball_labels.json
采样 = 置信帧（prob>th）全取 + 其余随机补足 --n 帧（正负样本兼有）。
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import random
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = str(tactics_data_file(""))
AW = Path(ROOT) / "action_work"

ARGS = None  # argparse 结果
SAMPLED = []  # [{"fn":..., "prefill":[x,y]|null}]


def build_sample():
    scores = json.loads((AW / "validate" / f"{ARGS.clip}_scores.json").read_text())[ARGS.clip]
    def fid(fn): return int(fn[1:6])
    confident, other = [], []
    for fn, cs in scores.items():
        best = max(cs, key=lambda c: c["prob"]) if cs else None
        if best and best["prob"] > ARGS.th:
            b = best["bbox"]
            confident.append({"fn": fn, "prefill": [round((b[0] + b[2]) / 2), round((b[1] + b[3]) / 2)]})
        else:
            other.append({"fn": fn, "prefill": None})
    random.Random(7).shuffle(other)
    out = confident + other[: max(0, ARGS.n - len(confident))]
    out.sort(key=lambda e: fid(e["fn"]))
    return out


HTML = """<!doctype html><html><head><meta charset="utf-8"><title>球标注 · __CLIP__</title>
<style>
 body{background:#111;color:#eee;font-family:system-ui;margin:0;padding:16px}
 #img{max-width:100%;cursor:crosshair;display:block;margin:auto}
 .bar{display:flex;gap:12px;align-items:center;margin-bottom:8px;flex-wrap:wrap}
 button{background:#2a6;border:0;color:#fff;padding:6px 14px;border-radius:6px;cursor:pointer}
 button.gray{background:#555}
 #pos{font-size:14px;color:#9cf}
 .done{color:#7f7}
</style></head><body>
<div class="bar">
 <b>球标注 · __CLIP__</b>
 <span id="pos"></span>
 <button onclick="nav(1)">下一帧 →</button>
 <button class="gray" onclick="nav(-1)">← 上一帧</button>
 <button class="gray" onclick="setNull()">无球 (n)</button>
 <button onclick="save()">保存</button>
 <span id="msg" class="done"></span>
</div>
<img id="img"><script>
let data=null, idx=0, labels={}, natural=null;
const $=id=>document.getElementById(id);
async function boot(){
  data = await (await fetch('/data')).json();
  labels = data.prefill_labels || {};
  show();
}
function show(){
  const e=data.frames[idx];
  $('img').src='/frame?i='+idx;
  $('pos').textContent=`第 ${idx+1}/${data.frames.length} 帧 · ${e.fn}` + (labels[e.fn]===null?' [无球]':(labels[e.fn]?` [已标 ${labels[e.fn].x},${labels[e.fn].y}]`:''));
}
$('img').onclick=ev=>{
  const r=$('img').getBoundingClientRect();
  const e=data.frames[idx];
  labels[e.fn]={x:Math.round((ev.clientX-r.left)/r.width*natural.w),
                y:Math.round((ev.clientY-r.top)/r.height*natural.h)};
  show();
};
function nav(d){idx=Math.min(data.frames.length-1,Math.max(0,idx+d));show();}
function setNull(){labels[data.frames[idx].fn]=null;show();}
document.onkeydown=ev=>{
  if(ev.key==='ArrowRight'||ev.key===' ')nav(1);
  else if(ev.key==='ArrowLeft')nav(-1);
  else if(ev.key==='n')setNull();
};
$('img').onload=function(){natural={w:this.naturalWidth,h:this.naturalHeight};
  const e=data.frames[idx],p=e.prefill;
  if(p&&!labels[e.fn]){labels[e.fn]={x:p[0],y:p[1]};}
  show();
};
async function save(){
  const r=await fetch('/save',{method:'POST',body:JSON.stringify({labels})});
  $('msg').textContent=r.ok?'已保存 ✓':'保存失败';
  setTimeout(()=>$('msg').textContent='',3000);
}
boot();
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/":
            b = HTML.replace("__CLIP__", ARGS.clip).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        elif self.path == "/data":
            pre = {}
            lp = AW / "validate" / f"{ARGS.clip}_ball_labels.json"
            if lp.exists():
                pre = json.loads(lp.read_text()).get("labels", {})
            self._json({"clip": ARGS.clip, "frames": SAMPLED, "prefill_labels": pre})
        elif self.path.startswith("/frame?i="):
            i = int(self.path.split("=")[1])
            p = AW / ARGS.clip / SAMPLED[i]["fn"]
            b = p.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/save":
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n))
            out = AW / "validate" / f"{ARGS.clip}_ball_labels.json"
            out.write_text(json.dumps({"clip": ARGS.clip, "labels": body["labels"]},
                                       ensure_ascii=False, indent=1))
            self._json({"ok": True, "path": str(out)})
        else:
            self.send_error(404)


def main():
    global ARGS, SAMPLED
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", required=True)
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--th", type=float, default=0.85)
    ARGS = ap.parse_args()
    SAMPLED = build_sample()
    n_conf = sum(1 for e in SAMPLED if e["prefill"])
    print(f"[{ARGS.clip}] 采样 {len(SAMPLED)} 帧（置信 {n_conf} + 其余 {len(SAMPLED)-n_conf}）")
    print(f"浏览器打开  http://127.0.0.1:{ARGS.port}   Ctrl-C 退出")
    ThreadingHTTPServer(("127.0.0.1", ARGS.port), H).serve_forever()


if __name__ == "__main__":
    main()
