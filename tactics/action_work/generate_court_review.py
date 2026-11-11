#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成自包含浏览器点选页 court_review.html（替代 pick_court_lines.py 的 cv2 终端脚本）。

- 读取 routing_manifest.json 的 GAME 路由（A 步候选，剔 c17 特写）→ 19 簇。
- 每簇取首个窗口的中位帧作代表帧，base64 内嵌（页面自包含，无需 file://）。
- DISREGARD_BOARD / DISREGARD_GRAY / 特写 作为只读摘要卡，供老程一目判断。
- 交互：画布点 4 角点(f_l,f_r,n_r,n_l) → 导出 court_calib_picks.json
  （schema 兼容 pick_court_lines.py：{cluster:{seg,start,end,img_width,img_height,src_points,note}}）。
- 老程只需在浏览器打开、看帧、点 4 下、导出，不碰终端。
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import base64
import json
import os
from collections import defaultdict

from common.nba_paths import tactics_data_file

BASE = str(tactics_data_file("action_work/norm_calib"))
SEG = str(tactics_data_file("action_work/tactic_notes_batch_full/segments"))
rm = json.load(open(f"{BASE}/routing_manifest.json", encoding="utf-8"))

CLOSEUP = {17}  # ep13_s1#5-50 特写


def frame_path(seg, idx):
    return f"{SEG}/{seg}/frames/f{idx+1:05d}.jpg"  # 窗口 0-based -> 文件 1-based


def pick_rep(seg, start, end):
    mid = start + (end - start) // 2
    for d in (0, 1, -1, 2, -2, 3, -3):
        p = frame_path(seg, mid + d)
        if os.path.exists(p):
            return p
    return frame_path(seg, mid)


# A_STEP 簇（GAME 剔特写）
game = rm["routes"]["GAME_HALFCOURT_CANDIDATE"]["members"]
clusters = []
for m in game:
    c = m["cluster"]
    if c in CLOSEUP:
        continue
    w = m["members"][0]
    rep = pick_rep(w["seg"], w["start"], w["end"])
    with open(rep, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    clusters.append({
        "cluster": c, "seg": w["seg"], "start": w["start"], "end": w["end"],
        "frames": m["frames"], "img": f"data:image/jpeg;base64,{b64}",
    })
# 按帧数降序（Top-9 在前）
clusters.sort(key=lambda x: -x["frames"])

# DISREGARD 摘要
def disp_list(route):
    out = []
    for m in rm["routes"][route]["members"]:
        for w in m["members"]:
            out.append(f"{w['seg']}#{w['start']}-{w['end']}")
    return out

disregard = {
    "DISREGARD_BOARD": disp_list("DISREGARD_BOARD"),
    "DISREGARD_GRAY": disp_list("GRAY_VISUAL_SIGNOFF"),
    "DISREGARD_CLOSEUP": ["ep13_s1#5-50(c17)"],
}

payload = {"clusters": clusters, "disregard": disregard,
           "total_frames": rm["total_frames"]}

HTML = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>战术板点选 · 老程裁定页</title>
<style>
* {box-sizing:border-box}
body {font-family:system-ui,"PingFang SC",sans-serif;margin:0;background:#0f1115;color:#e6e6e6}
header {padding:14px 20px;background:#171a21;border-bottom:1px solid #2a2f3a;position:sticky;top:0;z-index:10}
header h1 {font-size:16px;margin:0 0 4px}
header p {font-size:12px;color:#9aa3b2;margin:0}
.wrap {padding:16px 20px;max-width:1100px;margin:0 auto}
.summary {background:#171a21;border:1px solid #2a2f3a;border-radius:8px;padding:12px 14px;margin-bottom:18px;font-size:13px}
.summary b {color:#7ee0a8}
.disp {color:#ff9b9b}
.card {background:#171a21;border:1px solid #2a2f3a;border-radius:10px;padding:12px;margin-bottom:18px}
.card.done {border-color:#3ec97a}
.card h3 {font-size:14px;margin:0 0 8px;display:flex;justify-content:space-between;align-items:center}
.tag {font-size:11px;padding:2px 8px;border-radius:10px;background:#2a2f3a;color:#9aa3b2}
.tag.done {background:#1f5e3a;color:#bff5d6}
.canvas-box {position:relative;max-width:960px}
canvas {display:block;max-width:100%;background:#000;border-radius:6px;cursor:crosshair;touch-action:none}
.btns {margin-top:8px;display:flex;gap:8px;flex-wrap:wrap}
button {background:#2a2f3a;color:#e6e6e6;border:1px solid #3a4150;border-radius:6px;padding:6px 12px;font-size:12px;cursor:pointer}
button:hover {background:#353c4a}
button.primary {background:#2f6df0;border-color:#2f6df0}
.hint {font-size:11px;color:#9aa3b2;margin-top:6px}
.grid {display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}
</style></head><body>
<header><h1>战术板点选 · 老程裁定页</h1>
<p>每簇点 4 角点：<b>f_l远左 → f_r远右 → n_r近右 → n_l近左</b>。点完点「导出JSON」。</p></header>
<div class="wrap">
<div class="summary" id="summary"></div>
<div id="cards"></div>
<div style="position:sticky;bottom:0;background:#171a21;border-top:1px solid #2a2f3a;padding:12px 0;margin-top:10px">
<button class="primary" onclick="exportJSON()">导出 court_calib_picks.json</button>
<span class="hint" id="prog"></span></div>
</div>
<script>
const PAYLOAD = __PAYLOAD__;
const ORDER = ["f_l(远左)","f_r(远右)","n_r(近右)","n_l(近左)"];
const picks = {};  // cluster -> {pts:[[x,y]x4], w, h}
const scaleOf = {};

function drawCard(c){
  const done = picks[c.cluster] && picks[c.cluster].pts.length===4;
  const div = document.createElement("div");
  div.className = "card" + (done?" done":"");
  div.id = "card-"+c.cluster;
  div.innerHTML = `<h3><span>#${c.cluster} ${c.seg}#${c.start}-${c.end} (${c.frames}帧)</span>
    <span class="tag ${done?'done':''}" id="tag-${c.cluster}">${done?'已点':'待点 0/4'}</span></h3>
    <div class="canvas-box"><canvas id="cv-${c.cluster}"></canvas></div>
    <div class="btns">
      <button onclick="undo(${c.cluster})">撤销</button>
      <button onclick="clearP(${c.cluster})">清空</button>
    </div>
    <div class="hint">点选顺序 f_l→f_r→n_r→n_l；右键/撤销可改</div>`;
  return div;
}
function setupCanvas(c){
  const img = new Image();
  img.onload = ()=>{
    const maxW = 960;
    const sc = Math.min(1, maxW/img.naturalWidth);
    const cv = document.getElementById("cv-"+c.cluster);
    cv.width = img.naturalWidth*sc; cv.height = img.naturalHeight*sc;
    scaleOf[c.cluster] = sc;
    const ctx = cv.getContext("2d");
    ctx.drawImage(img,0,0,cv.width,cv.height);
    cv._img = img; cv._sc = sc;
    redraw(c);
    cv.onclick = (e)=>onClick(e,c);
  };
  img.src = c.img;
}
function onClick(e,c){
  const cv = document.getElementById("cv-"+c.cluster);
  const r = cv.getBoundingClientRect();
  const px = (e.clientX-r.left)*(cv.width/r.width);
  const py = (e.clientY-r.top)*(cv.height/r.height);
  const sc = scaleOf[c.cluster];
  const x = px/sc, y = py/sc;  // 自然坐标
  if(!picks[c.cluster]) picks[c.cluster]={pts:[],w:cv._img.naturalWidth,h:cv._img.naturalHeight};
  if(picks[c.cluster].pts.length>=4) return;
  picks[c.cluster].pts.push([Math.round(x),Math.round(y)]);
  redraw(c); updateTag(c);
}
function redraw(c){
  const cv = document.getElementById("cv-"+c.cluster);
  const ctx = cv.getContext("2d");
  ctx.drawImage(cv._img,0,0,cv.width,cv.height);
  const pts = (picks[c.cluster]&&picks[c.cluster].pts)||[];
  const sc = scaleOf[c.cluster];
  pts.forEach((p,i)=>{
    const X=p[0]*sc, Y=p[1]*sc;
    ctx.beginPath();ctx.arc(X,Y,6,0,7);ctx.fillStyle="#ffcf3a";ctx.fill();
    ctx.fillStyle="#111";ctx.font="11px sans-serif";ctx.fillText(ORDER[i].slice(0,3),X+8,Y-8);
  });
  if(pts.length===4){
    ctx.beginPath();
    ctx.moveTo(pts[0][0]*sc,pts[0][1]*sc);
    [1,3,2,0].forEach(i=>ctx.lineTo(pts[i][0]*sc,pts[i][1]*sc));
    ctx.closePath();ctx.strokeStyle="#3ec97a";ctx.lineWidth=2;ctx.stroke();
  }
}
function updateTag(c){
  const n = picks[c.cluster]?picks[c.cluster].pts.length:0;
  const tag = document.getElementById("tag-"+c.cluster);
  const card = document.getElementById("card-"+c.cluster);
  if(n===4){tag.textContent="已点";tag.className="tag done";card.className="card done";}
  else {tag.textContent="待点 "+n+"/4";tag.className="tag";card.className="card";}
  refreshProg();
}
function undo(c){ if(picks[c]&&picks[c].pts.length){picks[c].pts.pop();redraw({cluster:c});updateTag({cluster:c});} }
function clearP(c){ if(picks[c])picks[c].pts=[]; redraw({cluster:c});updateTag({cluster:c}); }
function refreshProg(){
  const n = Object.values(picks).filter(p=>p.pts.length===4).length;
  document.getElementById("prog").textContent = ` 已点 ${n}/${PAYLOAD.clusters.length} 簇`;
}
function exportJSON(){
  const out = {};
  for(const c of PAYLOAD.clusters){
    const p = picks[c.cluster];
    if(!p||p.pts.length!==4) continue;
    out[c.cluster] = {seg:c.seg,start:c.start,end:c.end,
      img_width:p.w,img_height:p.h,src_points:p.pts,
      note:"未扩展真值;接HalfCourt.from_points守C4"};
  }
  const blob = new Blob([JSON.stringify(out,null,2)],{type:"application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "court_calib_picks.json";
  a.click();
  alert("已导出 "+Object.keys(out).length+" 簇 → court_calib_picks.json");
}
function init(){
  const s = document.getElementById("summary");
  const d = PAYLOAD.disregard;
  s.innerHTML = `总帧 <b>${PAYLOAD.total_frames}</b> ｜ A步候选 <b>${PAYLOAD.clusters.length}</b> 簇 ｜ `+
    `剔除：板帧 <span class="disp">${d.DISREGARD_BOARD.length}</span> · 灰区 <span class="disp">${d.DISREGARD_GRAY.length}</span> · 特写 <span class="disp">${d.DISREGARD_CLOSEUP.length}</span><br>`+
    `<span class="disp">板帧:</span> ${d.DISREGARD_BOARD.join(" ")}<br>`+
    `<span class="disp">灰区:</span> ${d.DISREGARD_GRAY.join(" ")}<br>`+
    `<span class="disp">特写:</span> ${d.DISREGARD_CLOSEUP.join(" ")}`;
  const wrap = document.getElementById("cards");
  const grid = document.createElement("div"); grid.className="grid";
  PAYLOAD.clusters.forEach(c=>{ grid.appendChild(drawCard(c)); });
  wrap.appendChild(grid);
  PAYLOAD.clusters.forEach(setupCanvas);
  refreshProg();
}
init();
</script></body></html>"""

html = HTML.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))
out = f"{BASE}/court_review.html"
open(out, "w", encoding="utf-8").write(html)
print("clusters(A_STEP) =", len(clusters))
print("embedded frames =", len(clusters), "; total html bytes =", len(html))
print("written ->", out)
