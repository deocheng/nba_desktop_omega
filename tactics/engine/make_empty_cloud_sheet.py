#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_empty_cloud_sheet.py — 为 empty-cloud 帧生成「自由点击球心」标注页（中期检测器 fine-tune 素材）。

与 A4.32 标注页的区别：empty 帧无候选可点选，改为在 full.jpg 上自由点击球心，
输出坐标（1920×1080 口径）→ 可按 bank box_size=26 合成框，作检测器 fine-tune 硬例。

用法:
  python engine/make_empty_cloud_sheet.py \
      --empty-json action_work/validate/multiscale_empty_cloud.json \
      --sheets-dir action_work/validate/sas_lal_sheets \
      --out action_work/validate/sas_lal_sheets/label_empty_multiscale.html
产出: HTML 标注页（同目录引用 fNNNNN.full.jpg）；老程标注后 Export 下载 JSON：
  [{"frame": "f00317.jpg", "ball_xy": [x, y] | null}, ...]   # null = 本帧无球
"""
import argparse
import json
from pathlib import Path

HTML = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>empty-cloud 点球标注（multiscale 残留）</title>
<style>
 body{font-family:-apple-system,sans-serif;background:#111;color:#eee;margin:0;padding:12px}
 #bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:8px}
 button{background:#2b6cb0;color:#fff;border:0;border-radius:6px;padding:8px 14px;cursor:pointer;font-size:14px}
 button.warn{background:#c53030}
 button:disabled{opacity:.4;cursor:default}
 #info{font-size:14px}
 #imgwrap{position:relative;display:inline-block}
 img{max-width:100%;height:auto;display:block;cursor:crosshair}
 .dot{position:absolute;width:12px;height:12px;border:2px solid #ff3b30;border-radius:50%;
      transform:translate(-50%,-50%);pointer-events:none}
 .none-tag{position:absolute;top:6px;left:6px;background:#c53030;color:#fff;padding:2px 8px;border-radius:4px;font-size:12px}
 #done{color:#8f8}
</style></head><body>
<div id="bar">
 <button id="prev">◀ 上一帧</button>
 <button id="next">下一帧 ▶</button>
 <button id="none" class="warn">本帧无球</button>
 <button id="clear">清除本帧标注</button>
 <button id="export">Export JSON</button>
 <span id="info"></span><span id="done"></span>
</div>
<div id="imgwrap"><img id="img"><div id="overlay"></div></div>
<script>
const FRAMES = __FRAMES__;
const W = 1920, H = 1080;
let labels = {}, cur = 0;
const img = document.getElementById('img'), overlay = document.getElementById('overlay');
function save(){ localStorage.setItem('empty_cloud_labels', JSON.stringify(labels)); }
function load(){ try{ labels = JSON.parse(localStorage.getItem('empty_cloud_labels')||'{}'); }catch(e){ labels={}; } }
function render(){
  const f = FRAMES[cur];
  img.src = f; overlay.innerHTML='';
  const lab = labels[f];
  if(lab && lab.ball_xy){
    const imgW = img.clientWidth, imgH = img.clientHeight;
    const d = document.createElement('div'); d.className='dot';
    d.style.left = (lab.ball_xy[0]/W*imgW)+'px';
    d.style.top  = (lab.ball_xy[1]/H*imgH)+'px';
    overlay.appendChild(d);
  }
  if(lab && lab.ball_xy === null){
    const t = document.createElement('div'); t.className='none-tag'; t.textContent='无球';
    overlay.appendChild(t);
  }
  document.getElementById('info').textContent =
    `${f}  (${cur+1}/${FRAMES.length})` + (lab ? (lab.ball_xy?`  球心=(${lab.ball_xy[0]},${lab.ball_xy[1]})`:'  无球') : '  未标');
  const n = Object.keys(labels).length;
  document.getElementById('done').textContent = `  已标 ${n}/${FRAMES.length}`;
}
img.addEventListener('click', e=>{
  const r = img.getBoundingClientRect();
  const x = Math.round((e.clientX - r.left)/r.width*W);
  const y = Math.round((e.clientY - r.top)/r.height*H);
  labels[FRAMES[cur]] = {ball_xy:[x,y]}; save(); render();
});
document.getElementById('prev').onclick = ()=>{ cur=Math.max(0,cur-1); render(); };
document.getElementById('next').onclick = ()=>{ cur=Math.min(FRAMES.length-1,cur+1); render(); };
document.getElementById('none').onclick = ()=>{ labels[FRAMES[cur]]={ball_xy:null}; save(); render(); };
document.getElementById('clear').onclick = ()=>{ delete labels[FRAMES[cur]]; save(); render(); };
document.getElementById('export').onclick = ()=>{
  const out = FRAMES.map(f=>({frame:f, ball_xy:(labels[f]||{}).ball_xy===undefined?undefined:labels[f].ball_xy}));
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([JSON.stringify(out,null,1)],{type:'application/json'}));
  a.download='empty_cloud_ball_points.json'; a.click();
};
document.addEventListener('keydown',e=>{
  if(e.key==='ArrowLeft') cur=Math.max(0,cur-1), render();
  if(e.key==='ArrowRight') cur=Math.min(FRAMES.length-1,cur+1), render();
});
load(); render();
</script></body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--empty-json", required=True, help="multiscale_empty_cloud.json（含 new_empty 列表）")
    ap.add_argument("--key", default="new_empty")
    ap.add_argument("--sheets-dir", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    frames = json.loads(Path(a.empty_json).read_text())[a.key]
    sd = Path(a.sheets_dir)
    missing = [f for f in frames if not (sd / f.replace(".jpg", ".full.jpg")).exists()]
    if missing:
        print(f"⚠️ 缺 full.jpg 的帧 {len(missing)}: {missing}")
    out = Path(a.out)
    out.write_text(HTML.replace("__FRAMES__", json.dumps(frames)))
    print(f"[sheet] {out}  帧 {len(frames)}  缺图 {len(missing)}")
    print("标注后 Export 下载 empty_cloud_ball_points.json，放回 sheets 目录即可合成 fine-tune bank")


if __name__ == "__main__":
    main()
