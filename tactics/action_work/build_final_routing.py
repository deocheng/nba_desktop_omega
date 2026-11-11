#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按老程逐簇目测裁定，落最终处置清单 + 重生成点选页（剔除簇灰掉不可点）。

输入：routing_manifest.json + a_step_verdict.json（老程逐簇裁定）
输出：routing_final.json（最终处置，含理由）+ court_review.html（剔除簇灰掉只读）
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
verdicts = json.load(open(f"{BASE}/a_step_verdict.json", encoding="utf-8"))
CLOSEUP_PRE = {17: "ep13_s1#5-50"}  # 早前登记特写


def frame_path(seg, idx):
    return f"{SEG}/{seg}/frames/f{idx+1:05d}.jpg"


def pick_rep(seg, start, end):
    mid = start + (end - start) // 2
    for d in (0, 1, -1, 2, -2, 3, -3):
        if os.path.exists(frame_path(seg, mid + d)):
            return frame_path(seg, mid + d)
    return frame_path(seg, mid)


game = rm["routes"]["GAME_HALFCOURT_CANDIDATE"]["members"]
clusters = []
buckets = defaultdict(lambda: {"clusters": [], "frames": 0, "detail": []})
for m in game:
    c = m["cluster"]
    if c in CLOSEUP_PRE:
        v = {"verdict": "DISREGARD", "reason": "特写(无场地线)"}
    else:
        v = verdicts.get(str(c)) or verdicts.get(c)
        if not v:
            v = {"verdict": "PENDING", "reason": "未裁定"}
    w = m["members"][0]
    rep = pick_rep(w["seg"], w["start"], w["end"])
    with open(rep, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    clusters.append({
        "cluster": c, "seg": w["seg"], "start": w["start"], "end": w["end"],
        "frames": m["frames"], "img": f"data:image/jpeg;base64,{b64}",
        "verdict": v["verdict"], "reason": v.get("reason", ""),
        "method_note": v.get("method_note", ""),
    })
    key = {"KEEP": "A_STEP_FINAL", "PENDING": "PENDING",
           "DISREGARD": "DISREGARD_GAME"}.get(v["verdict"], "PENDING")
    buckets[key]["clusters"].append(c)
    buckets[key]["frames"] += m["frames"]
    buckets[key]["detail"].append(f"{w['seg']}#{w['start']}-{w['end']}({m['frames']}帧):{v.get('reason','')}")

# 汇总（含板帧/灰区/早前特写）
board = rm["routes"]["DISREGARD_BOARD"]
gray = rm["routes"]["GRAY_VISUAL_SIGNOFF"]
final = {
    "decided_by": "老程逐簇目测裁定(2026-10-04) + AI 结构推断(板帧/灰区)",
    "total_frames": rm["total_frames"],
    "buckets": {
        "A_STEP_FINAL": {"clusters": buckets["A_STEP_FINAL"]["clusters"],
                         "frames": buckets["A_STEP_FINAL"]["frames"],
                         "detail": buckets["A_STEP_FINAL"]["detail"]},
        "PENDING": {"clusters": buckets["PENDING"]["clusters"],
                    "frames": buckets["PENDING"]["frames"],
                    "detail": buckets["PENDING"]["detail"]},
        "DISREGARD_GAME": {"clusters": buckets["DISREGARD_GAME"]["clusters"],
                           "frames": buckets["DISREGARD_GAME"]["frames"],
                           "detail": buckets["DISREGARD_GAME"]["detail"]},
        "DISREGARD_BOARD": {"clusters": board["clusters"], "frames": board["frames"],
                            "detail": [f"{x['seg']}#{x['start']}-{x['end']}" for m in board["members"] for x in m["members"]]},
        "DISREGARD_GRAY": {"clusters": gray["clusters"], "frames": gray["frames"],
                           "detail": [f"{x['seg']}#{x['start']}-{x['end']}" for m in gray["members"] for x in m["members"]]},
        "DISREGARD_CLOSEUP_PRE": {"clusters": [17], "frames": 46,
                                  "detail": ["ep13_s1#5-50(c17)"]},
    },
    "summary": {
        "a_step_final_frames": buckets["A_STEP_FINAL"]["frames"],
        "pending_frames": buckets["PENDING"]["frames"],
        "total_disregard_frames": (buckets["DISREGARD_GAME"]["frames"] + board["frames"]
                                   + gray["frames"]),
    },
}
json.dump(final, open(f"{BASE}/routing_final.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)

# ---- 重生成 court_review.html（剔除簇灰掉只读）----
disregard_summary = {
    "板帧(讲解覆盖层)": final["buckets"]["DISREGARD_BOARD"]["detail"],
    "灰区(包装层/小板)": final["buckets"]["DISREGARD_GRAY"]["detail"],
    "GAME内剔除(讲解/特写/场外)": final["buckets"]["DISREGARD_GAME"]["detail"],
    "早前特写": final["buckets"]["DISREGARD_CLOSEUP_PRE"]["detail"],
}
payload = {"clusters": clusters, "disregard": disregard_summary,
           "total_frames": rm["total_frames"]}

HTML = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>战术板点选 · 老程裁定页（终版）</title>
<style>
*{box-sizing:border-box}body{font-family:system-ui,"PingFang SC",sans-serif;margin:0;background:#0f1115;color:#e6e6e6}
header{padding:14px 20px;background:#171a21;border-bottom:1px solid #2a2f3a;position:sticky;top:0;z-index:10}
header h1{font-size:16px;margin:0 0 4px}header p{font-size:12px;color:#9aa3b2;margin:0}
.wrap{padding:16px 20px;max-width:1180px;margin:0 auto}
.summary{background:#171a21;border:1px solid #2a2f3a;border-radius:8px;padding:12px 14px;margin-bottom:18px;font-size:12.5px;line-height:1.7}
.summary b{color:#7ee0a8}.disp{color:#ff9b9b}.pend{color:#ffd27e}
.card{background:#171a21;border:1px solid #2a2f3a;border-radius:10px;padding:12px;margin-bottom:16px}
.card.done{border-color:#3ec97a}.card.discard{opacity:.5;border-color:#5a3030}
.card.pend{border-color:#7a6320}
.card h3{font-size:14px;margin:0 0 8px;display:flex;justify-content:space-between;align-items:center}
.tag{font-size:11px;padding:2px 8px;border-radius:10px;background:#2a2f3a;color:#9aa3b2}
.tag.done{background:#1f5e3a;color:#bff5d6}.tag.discard{background:#5a3030;color:#ffc9c9}
.tag.pend{background:#7a6320;color:#ffe2a8}
.canvas-box{position:relative;max-width:960px}
canvas{display:block;max-width:100%;background:#000;border-radius:6px;touch-action:none}
canvas.click{cursor:crosshair}.card.discard canvas{filter:grayscale(1)}
.btns{margin-top:8px;display:flex;gap:8px;flex-wrap:wrap}
button{background:#2a2f3a;color:#e6e6e6;border:1px solid #3a4150;border-radius:6px;padding:6px 12px;font-size:12px;cursor:pointer}
button:hover{background:#353c4a}button.primary{background:#2f6df0;border-color:#2f6df0}
.hint{font-size:11px;color:#9aa3b2;margin-top:6px}.reason{font-size:11.5px;color:#ffb3b3;margin-top:6px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}
</style></head><body>
<header><h1>战术板点选 · 老程裁定页（终版）</h1>
<p>绿框=保留(点4角点)｜灰框=已剔(只读)｜黄框=待裁定。顺序 f_l→f_r→n_r→n_l。</p></header>
<div class="wrap"><div class="summary" id="summary"></div>
<div id="cards"></div>
<div style="position:sticky;bottom:0;background:#171a21;border-top:1px solid #2a2f3a;padding:12px 0;margin-top:10px">
<button class="primary" onclick="exportJSON()">导出 court_calib_picks.json</button>
<span class="hint" id="prog"></span></div></div>
<script>
const PAYLOAD=__PAYLOAD__;
const ORDER=["f_l(远左)","f_r(远右)","n_r(近右)","n_l(近左)"];
const picks={};const scaleOf={};
function drawCard(c){
  const disc=c.verdict==="DISREGARD";
  const pend=c.verdict==="PENDING";
  const div=document.createElement("div");
  div.className="card"+(disc?" discard":pend?" pend":"");div.id="card-"+c.cluster;
  const tagTxt=disc?"已剔":pend?"待裁定":"待点 0/4";
  const tagCls=disc?"discard":pend?"pend":"";
  div.innerHTML=`<h3><span>#${c.cluster} ${c.seg}#${c.start}-${c.end} (${c.frames}帧)</span>
    <span class="tag ${tagCls}" id="tag-${c.cluster}">${tagTxt}</span></h3>
    <div class="canvas-box"><canvas id="cv-${c.cluster}" class="${disc?'':'click'}"></canvas></div>`+
    (disc?`<div class="reason">剔除原因：${c.reason}</div>`:"")+
    (pend?`<div class="reason" style="color:#ffd27e">待裁定：${c.reason}</div>`:"")+
    (disc?"":`<div class="btns"><button onclick="undo(${c.cluster})">撤销</button>
      <button onclick="clearP(${c.cluster})">清空</button></div>
      <div class="hint">点选顺序 f_l→f_r→n_r→n_l</div>`);
  return div;
}
function setupCanvas(c){
  const img=new Image();
  img.onload=()=>{
    const maxW=960,sc=Math.min(1,maxW/img.naturalWidth);
    const cv=document.getElementById("cv-"+c.cluster);
    cv.width=img.naturalWidth*sc;cv.height=img.naturalHeight*sc;scaleOf[c.cluster]=sc;
    cv._img=img;cv._sc=sc;redraw(c);
    if(c.verdict!=="DISREGARD") cv.onclick=(e)=>onClick(e,c);
  };
  img.src=c.img;
}
function onClick(e,c){
  const cv=document.getElementById("cv-"+c.cluster);const r=cv.getBoundingClientRect();
  const px=(e.clientX-r.left)*(cv.width/r.width),py=(e.clientY-r.top)*(cv.height/r.height);
  const sc=scaleOf[c.cluster];const x=px/sc,y=py/sc;
  if(!picks[c.cluster])picks[c.cluster]={pts:[],w:cv._img.naturalWidth,h:cv._img.naturalHeight};
  if(picks[c.cluster].pts.length>=4)return;
  picks[c.cluster].pts.push([Math.round(x),Math.round(y)]);redraw(c);updateTag(c);
}
function redraw(c){
  const cv=document.getElementById("cv-"+c.cluster);const ctx=cv.getContext("2d");
  ctx.drawImage(cv._img,0,0,cv.width,cv.height);
  const pts=(picks[c.cluster]&&picks[c.cluster].pts)||[];const sc=scaleOf[c.cluster];
  pts.forEach((p,i)=>{const X=p[0]*sc,Y=p[1]*sc;
    ctx.beginPath();ctx.arc(X,Y,6,0,7);ctx.fillStyle="#ffcf3a";ctx.fill();
    ctx.fillStyle="#111";ctx.font="11px sans-serif";ctx.fillText(ORDER[i].slice(0,3),X+8,Y-8);});
  if(pts.length===4){ctx.beginPath();ctx.moveTo(pts[0][0]*sc,pts[0][1]*sc);
    [1,3,2,0].forEach(i=>ctx.lineTo(pts[i][0]*sc,pts[i][1]*sc));ctx.closePath();
    ctx.strokeStyle="#3ec97a";ctx.lineWidth=2;ctx.stroke();}
}
function updateTag(c){
  const n=picks[c.cluster]?picks[c.cluster].pts.length:0;
  const tag=document.getElementById("tag-"+c.cluster);const card=document.getElementById("card-"+c.cluster);
  if(n===4){tag.textContent="已点";tag.className="tag done";card.className="card done";}
  else{tag.textContent="待点 "+n+"/4";tag.className="tag";card.className="card";}
  refreshProg();
}
function undo(c){if(picks[c]&&picks[c].pts.length){picks[c].pts.pop();redraw({cluster:c});updateTag({cluster:c});}}
function clearP(c){if(picks[c])picks[c].pts=[];redraw({cluster:c});updateTag({cluster:c});}
function refreshProg(){const n=Object.values(picks).filter(p=>p.pts.length===4).length;
  const keep=PAYLOAD.clusters.filter(c=>c.verdict!=="DISREGARD").length;
  document.getElementById("prog").textContent=` 已点 ${n}/${keep} 簇（剔除簇已灰掉不参与）`;}
function exportJSON(){
  const out={};
  for(const c of PAYLOAD.clusters){if(c.verdict==="DISREGARD")continue;
    const p=picks[c.cluster];if(!p||p.pts.length!==4)continue;
    out[c.cluster]={seg:c.seg,start:c.start,end:c.end,img_width:p.w,img_height:p.h,
      src_points:p.pts,note:"未扩展真值;接HalfCourt.from_points守C4"};}
  const blob=new Blob([JSON.stringify(out,null,2)],{type:"application/json"});
  const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="court_calib_picks.json";a.click();
  alert("已导出 "+Object.keys(out).length+" 簇(保留/待裁定) → court_calib_picks.json");
}
function init(){
  const s=document.getElementById("summary");const d=PAYLOAD.disregard;
  const f=PAYLOAD.total_frames;
  const keep=PAYLOAD.clusters.filter(c=>c.verdict==="KEEP").length;
  const pend=PAYLOAD.clusters.filter(c=>c.verdict==="PENDING").length;
  const disc=PAYLOAD.clusters.filter(c=>c.verdict==="DISREGARD").length;
  s.innerHTML=`总帧 <b>${f}</b> ｜ 保留 <b>${keep}</b> 簇（绿，需点选）｜ 待裁定 <span class="pend">${pend}</span> 簇（黄）｜ 已剔 <span class="disp">${disc}</span> 簇（灰，只读）<br>`+
    Object.entries(d).map(([k,v])=>`<span class="disp">${k}：</span> ${v.join(" ")}`).join("<br>");
  const wrap=document.getElementById("cards");const grid=document.createElement("div");grid.className="grid";
  PAYLOAD.clusters.forEach(c=>grid.appendChild(drawCard(c)));wrap.appendChild(grid);
  PAYLOAD.clusters.forEach(setupCanvas);refreshProg();
}
init();
</script></body></html>"""
html = HTML.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))
open(f"{BASE}/court_review.html", "w", encoding="utf-8").write(html)
print("A_STEP_FINAL clusters =", final["buckets"]["A_STEP_FINAL"]["clusters"],
      "frames =", final["buckets"]["A_STEP_FINAL"]["frames"])
print("PENDING =", final["buckets"]["PENDING"]["clusters"])
print("DISREGARD_GAME =", final["buckets"]["DISREGARD_GAME"]["clusters"],
      "frames =", final["buckets"]["DISREGARD_GAME"]["frames"])
print("html bytes =", len(html))
print("written ->", f"{BASE}/routing_final.json", "&", f"{BASE}/court_review.html")
