#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_human_labeler —— 生成 sas_det 人工标注本地 app（单帧向导，点选球候选 -> human_labels.json）。

用法:
  python engine/build_human_labeler.py
产出:
  action_work/validate/sas_det_sheets/label_sas_det.html   (自包含，双击用浏览器打开)
说明:
  - 每帧显示三面板合成图(全帧上下文 + 各候选 5x 放大, 格头 #i)；
  - 你点对应 #i 按钮 = 该候选是球；「无球」= 候选里没有球；「跳过」= 不确定(不进训练)；
  - 进度存 localStorage，关页不丢；「导出」下载 human_labels.json 交给本机 AI 转 bank。
  - 标注者 = human(老程)，可靠性远高于 AI 自标(74%) —— 这是唯一过门禁的自标路线。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
_ap = argparse.ArgumentParser()
_ap.add_argument("--clip", default="sas_det")
_ap.add_argument("--sheets", default=None, help="默认 action_work/validate/<clip>_sheets")
_ap.add_argument("--miss-frames", default=None,
                 help="待补标帧（有球但候选池没提出），逗号分隔帧号，如 11,41,46")
_ap.add_argument("--close-frames", default=None,
                 help="特写/无球硬负样本帧，逗号分隔帧号")
_a, _ = _ap.parse_known_args()
CLIP = _a.clip
SHEETS = Path(_a.sheets) if _a.sheets else AW / "validate" / f"{CLIP}_sheets"
MANIFEST = SHEETS / "manifest.json"
OUT = SHEETS / f"label_{CLIP}.html"

manifest = json.loads(MANIFEST.read_text())


def _parse_frames(spec):
    """'11,41,46' -> ['f00011.jpg', ...]；只保留 manifest 里真实存在的帧（防手写幻觉）。"""
    if not spec:
        return []
    out, missing = [], []
    for tok in str(spec).replace("f", "").replace(".jpg", "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        name = f"f{int(tok):05d}.jpg"
        (out if name in manifest else missing).append(name)
    if missing:
        print(f"[warn] --*-frames 中有 {len(missing)} 帧不在 manifest，已丢弃: {missing}")
    return out


PRIO = {}
for _n in _parse_frames(_a.miss_frames):
    PRIO[_n] = "miss"
for _n in _parse_frames(_a.close_frames):
    PRIO[_n] = "close"   # 硬负样本：真值无球，不覆盖已有 miss 标记
prio_json = json.dumps(PRIO, ensure_ascii=False)

# ── 原视频同页（老程 2026-09-27 约定：标注帧与原视频必须同页联动）──
# 探测顺序: ①SHEETS 同目录 <clip>_review_*.mp4（复制进来，单文件夹=完整工作台）
#           ②兄弟目录 ../<clip>_review/<clip>_review_*.mp4（review_clips 默认落点）
# 都没有 → VBASE=None，页面隐藏视频面板（向后兼容 sas_det 旧包）。
VBASE = None
same = SHEETS / f"{CLIP}_review_10fps_aligned.mp4"
sib = SHEETS.parent / f"{CLIP}_review" / f"{CLIP}_review_10fps_aligned.mp4"
if same.exists():
    VBASE = f"{CLIP}_review"
elif sib.exists():
    VBASE = f"../{CLIP}_review/{CLIP}_review"
frames = list(manifest.keys())
mjson = json.dumps(manifest, ensure_ascii=False)
TITLE = CLIP.replace("_", " ").upper()
LS_KEY = f"{CLIP}_human_labels_v1"

HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{TITLE} 人工标注 · 老程</title>
<style>
  :root{ --bg:#0f1115; --panel:#1a1d24; --line:#2a2f3a; --tx:#e6e9ef; --mut:#8b93a3;
         --acc:#46b46e; --acc2:#4a9ef0; --warn:#e0a83a; --bad:#e05a5a; }
  *{ box-sizing:border-box; }
  body{ margin:0; background:var(--bg); color:var(--tx); font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial; }
  header{ display:flex; align-items:center; gap:14px; padding:10px 16px; background:var(--panel);
          border-bottom:1px solid var(--line); position:sticky; top:0; z-index:10; }
  header h1{ font-size:15px; margin:0; font-weight:600; }
  .cnt{ color:var(--mut); font-variant-numeric:tabular-nums; }
  .main{ display:flex; gap:14px; padding:14px; align-items:flex-start; }
  .stage{ flex:1; min-width:0; background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:12px; }
  .imgwrap{ text-align:center; }
  img#sheet{ max-width:100%; width:auto; border-radius:8px; border:1px solid var(--line); background:#000; }
  /* 老程 2026-09-27 反馈「字太小分不清」：帧号/时间码一律大字 */
  .bigclock{ font-size:26px; font-weight:700; font-variant-numeric:tabular-nums;
             letter-spacing:.5px; color:var(--tx); }
  .bigclock .fno{ color:var(--acc2); }
  .bigclock .vtt{ color:var(--warn); }
  .fsbtn{ display:inline-block; margin-left:8px; padding:5px 12px; border-radius:7px;
          border:1px solid var(--acc2); color:var(--acc2); background:#16202c;
          cursor:pointer; font-size:14px; text-decoration:none; }
  .fsbtn:hover{ background:#1d2b3a; }
  .cand{ font-size:16px; padding:10px 16px; }
  .cell{ font-size:13px; }
  .hint{ color:var(--mut); font-size:12.5px; margin:8px 2px 0; }
  .btns{ display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }
  .cand{ padding:9px 14px; border-radius:8px; border:1px solid var(--line); background:#222733;
         color:var(--tx); cursor:pointer; font-size:13.5px; font-variant-numeric:tabular-nums; }
  .cand:hover{ border-color:var(--acc2); }
  .cand.on{ background:var(--acc); color:#06210f; border-color:var(--acc); font-weight:600; }
  .cand.none.on{ background:var(--warn); color:#2a1d00; border-color:var(--warn); }
  .cand.skip.on{ background:#3a3f4b; color:var(--tx); border-color:var(--mut); }
  .side{ width:210px; flex:none; background:var(--panel); border:1px solid var(--line);
         border-radius:10px; padding:10px; max-height:84vh; overflow:auto; }
  .side h2{ font-size:12px; color:var(--mut); margin:2px 0 8px; text-transform:uppercase; letter-spacing:.04em; }
  .grid{ display:grid; grid-template-columns:repeat(5,1fr); gap:5px; }
  .cell{ aspect-ratio:1; border-radius:6px; border:1px solid var(--line); background:#232834;
         display:flex; align-items:center; justify-content:center; font-size:11px; color:var(--mut);
         cursor:pointer; font-variant-numeric:tabular-nums; }
  .cell.ball{ background:var(--acc); color:#06210f; border-color:var(--acc); font-weight:700; }
  .cell.none{ background:var(--warn); color:#2a1d00; border-color:var(--warn); }
  .cell.skip{ background:#343a47; color:var(--tx); }
  .cell.cur{ outline:2px solid var(--acc2); outline-offset:1px; }
  .nav{ display:flex; gap:8px; align-items:center; margin-top:12px; flex-wrap:wrap; }
  .nav button,.nav a{ padding:8px 14px; border-radius:8px; border:1px solid var(--line);
         background:#222733; color:var(--tx); cursor:pointer; font-size:13px; text-decoration:none; }
  .nav button:hover{ border-color:var(--acc2); }
  .nav .primary{ background:var(--acc2); color:#04121f; border-color:var(--acc2); font-weight:600; }
  .status{ font-size:12.5px; color:var(--mut); margin-left:auto; }
  .legend{ font-size:11.5px; color:var(--mut); margin-top:10px; line-height:1.7; }
  .dot{ display:inline-block; width:9px; height:9px; border-radius:2px; vertical-align:middle; margin-right:4px; }
</style>
</head>
<body>
<header>
  <h1>{TITLE} 人工标注</h1>
  <span class="bigclock" id="cnt">0 / 0</span>
  <span class="status" id="status"></span>
</header>
<div class="main">
  <div class="stage">
    <div class="imgwrap"><img id="sheet" alt="sheet">
      <div><a class="fsbtn" id="sheetfs" href="#" target="_blank">⤢ sheet 原图全屏</a></div>
    </div>
    <div id="vidpanel" style="display:none; margin-top:10px; border-top:1px solid var(--line); padding-top:10px;">
      <video id="vid" controls preload="metadata" style="width:100%; max-height:420px; border-radius:8px; background:#000;"></video>
      <div class="bigclock" id="vclock" style="margin:8px 0 2px; padding:6px 12px;
           background:#10141b; border:1px solid var(--line); border-radius:8px;">—</div>
      <div class="btns" style="margin-top:8px">
        <button class="cand vbtn on" data-v="10fps_aligned">10fps 对齐</button>
        <button class="cand vbtn" data-v="25fps">25fps 原速</button>
        <button class="cand vbtn" data-v="slow05x">0.5x 慢速</button>
        <button class="cand" id="playhere">▶ 从本帧播放</button>
        <button class="cand" id="vseek">⇢ 视频对齐本帧</button>
      </div>
      <div class="hint">视频与帧号 1:1（f00001 = 0s）。切帧自动对齐（播放中不打断）；「从本帧播放」看连贯动作；0.5x 慢速卡疑难题。</div>
    </div>
    <div id="manualpanel" style="display:none; margin-top:10px; border-top:1px solid var(--line); padding-top:10px;">
      <div style="color:var(--mut); font-size:13px; margin-bottom:6px">
        【补标】候选里<b>没有</b>球？直接在原帧上<b>点球心</b>（看清了才点）：</div>
      <div style="position:relative; display:inline-block; width:100%;">
        <img id="fullimg" alt="full" style="width:100%; border-radius:8px; border:1px solid var(--line); cursor:crosshair;">
        <div id="marker" style="position:absolute; width:60px; height:60px; border:3px solid #46b46e;
             border-radius:50%; background:radial-gradient(circle, #46b46e 0 5px, rgba(70,180,110,0.20) 6px);
             box-shadow:0 0 0 6px rgba(70,180,110,0.22);
             transform:translate(-50%,-50%); pointer-events:none; display:none;"></div>
      </div>
      <div style="margin-top:6px">
        <a class="fsbtn" id="fullfs" href="#" target="_blank">⤢ 原帧全屏（1920×1080，字最大）</a>
      </div>
      <div class="btns" style="margin-top:8px">
        <button class="cand" id="visClear">✓ 球在此·清晰</button>
        <button class="cand" id="visBlur">◐ 球在此·模糊/部分遮挡</button>
        <button class="cand" id="visNone">✗ 完全看不见球（真漏检）</button>
        <button class="cand" id="manClear">清除补标</button>
      </div>
      <div class="hint">点图=标球心（自动记原帧坐标）。「完全看不见球」=真漏检，只进召回分母、不进训练。
        补标框默认 26×26px（与检测器小目标尺度一致）。</div>
    </div>
    <div class="hint">左=全帧上下文(绿框=候选位置) · 右=各候选 5x 放大(格头 #i)。点下方 <b>对应 #i</b> = 该候选是球；
      <b>无球</b>=候选里没有球；<b>跳过</b>=不确定(不进训练)。键：数字选候选 / n 无球 / s 跳过 / ←→ 翻页。</div>
    <div class="btns" id="btns"></div>
    <div class="nav">
      <button id="prev">← 上一帧</button>
      <button id="next">下一帧 →</button>
      <span id="prioTag" style="font-size:12.5px; padding:4px 9px; border-radius:6px; display:none;"></span>
      <button id="none" class="cand none">无球</button>
      <button id="skip" class="cand skip">跳过</button>
      <button id="export" class="primary">导出 human_labels.json</button>
      <button id="clear">清空本帧</button>
    </div>
  </div>
  <div class="side">
    <h2>帧进度 (点跳转)</h2>
    <div class="btns" style="margin:0 0 10px">
      <button class="cand fbtn on" data-f="all">全部</button>
      <button class="cand fbtn" data-f="miss">🎯 待补标</button>
      <button class="cand fbtn" data-f="close">🔍 特写</button>
      <button class="cand fbtn" data-f="todo">☐ 未完成</button>
    </div>
    <div class="grid" id="grid"></div>
    <div class="legend">
      <span class="dot" style="background:var(--acc)"></span>已标球
      <span class="dot" style="background:var(--warn); margin-left:8px"></span>无球<br>
      <span class="dot" style="background:#343a47"></span>跳过
      <span class="dot" style="background:#232834; border:1px solid var(--line); margin-left:8px"></span>未标
      <span class="dot" style="background:#46b46e; margin-left:8px"></span>补标球心
      <span class="dot" style="background:#e05a5a; margin-left:8px"></span>真漏检<br>
      <span style="color:var(--mut); font-size:12px">◆ = 待补标（有球未识别，优先点球心） · ○ = 特写硬负样本</span>
    </div>
  </div>
</div>
<script>
const MANIFEST = __MANIFEST__;
const FRAMES = Object.keys(MANIFEST);
const PRIO = __PRIO__;            // frame -> "miss"(有球未识别) | "close"(特写硬负样本)
let FILTER = "all";
let VIEW = FRAMES.slice();
const LS_KEY = "{LS_KEY}";
let labels = {};   // frame -> {ball: [idx...], none:bool, skip:bool}
try { labels = JSON.parse(localStorage.getItem(LS_KEY)) || {}; } catch(e){ labels = {}; }
let cur = 0;

const $ = s => document.querySelector(s);
const VBASE = "{VBASE}";
const HASFULL = {HASFULL};   // 是否存在原帧副本（补标功能开关）
let curV = "10fps_aligned";
function sheetSrc(f){ return f.replace(".jpg",".sheet.jpg"); }
function fnumOf(f){ return parseInt(f.slice(1,6), 10); }
function setVid(seek){
  if (!VBASE) return;
  const v = $("#vid"), t = (fnumOf(VIEW[cur])-1)/10.0;
  const want = VBASE + "_" + curV + ".mp4";
  const abs = new URL(want, location.href).href;
  if (v.src !== abs){
    v.addEventListener("loadedmetadata", () => { v.currentTime = t; }, {once:true});
    v.src = want; v.load();
  } else if (seek){ try{ v.currentTime = t; }catch(e){} }
}
// 大字时间码：视频播放时实时换算「视频秒 → 帧号」，消除 0:20.35/2035 这类歧义
function updClock(){
  const v = $("#vid");
  if (!VBASE || !v) return;
  const t = v.currentTime, n = Math.round(t*10) + 1;
  const nm = "f" + String(Math.min(n, 99999)).padStart(5, "0");
  $("#vclock").innerHTML = `<span class="vtt">视频 ${t.toFixed(2)}s</span>`
      + ` → <span class="fno">${nm}</span>`
      + ` &nbsp;<span style="font-size:15px;color:#8b93a3">(=${((n-1)/10).toFixed(2)}s · 当前帧 `
      + VIEW[cur].replace(".jpg","") + `)</span>`;
}
$("#vid").addEventListener("timeupdate", updClock);
$("#vid").addEventListener("seeked", updClock);
document.querySelectorAll(".vbtn").forEach(b => b.onclick = () => {
  curV = b.dataset.v;
  document.querySelectorAll(".vbtn").forEach(x => x.classList.toggle("on", x === b));
  setVid(true);
});
if (HASFULL){
  $("#fullimg").onclick = (e) => {
    const fi = $("#fullimg"), r = fi.getBoundingClientRect();
    const cx = Math.round((e.clientX - r.left) / r.width * fi.naturalWidth);
    const cy = Math.round((e.clientY - r.top) / r.height * fi.naturalHeight);
    const s = state(VIEW[cur]);
    s.manual = {cx, cy, vis: (s.manual ? s.manual.vis : "clear")};
    s.invisible = false; s.none = (s.ball.length===0);
    write(s);
  };
  $("#visClear").onclick = () => { const s=state(VIEW[cur]); if(!s.manual) return; s.manual.vis="clear"; s.invisible=false; write(s); };
  $("#visBlur").onclick  = () => { const s=state(VIEW[cur]); if(!s.manual) return; s.manual.vis="blur"; s.invisible=false; write(s); };
  $("#visNone").onclick  = () => { const s=state(VIEW[cur]); s.manual=null; s.invisible=!s.invisible; s.none=true; write(s); };
  $("#manClear").onclick = () => { const s=state(VIEW[cur]); s.manual=null; s.invisible=false; write(s); };
}
function save(){ localStorage.setItem(LS_KEY, JSON.stringify(labels)); }

function state(f){
  const l = labels[f];
  if (!l) return {ball:[], none:false, skip:false, manual:null, invisible:false};
  return {ball: l.ball||[], none: !!l.none, skip: !!l.skip,
          manual: l.manual||null, invisible: !!l.invisible};
}
function cls(f){
  const s = state(f);
  if (s.skip) return "skip";
  if (s.manual) return "manual";
  if (s.invisible) return "invisible";
  if (s.none) return "none";
  if (s.ball.length) return "ball";
  return "";
}

function applyFilter(){
  const keepFrame = (VIEW[cur] !== undefined) ? VIEW[cur] : FRAMES[cur];
  VIEW = FRAMES.filter(f => {
    if (FILTER === "miss")  return PRIO[f] === "miss";
    if (FILTER === "close") return PRIO[f] === "close";
    if (FILTER === "todo")  return cls(f) === "";
    return true;
  });
  if (!VIEW.length) VIEW = FRAMES.slice();
  const keep = VIEW.indexOf(keepFrame);
  cur = keep >= 0 ? keep : 0;
}
function prioTag(f){
  if (PRIO[f] === "miss")  return {txt:"🎯 待补标：有球但候选没提出 → 请在原帧点球心", bg:"#4a3410", fg:"#e0a83a"};
  if (PRIO[f] === "close") return {txt:"🔍 特写硬负样本：确认无球", bg:"#12304d", fg:"#4a9ef0"};
  return null;
}
function render(){
  const f = VIEW[cur];
  const s = state(f);
  $("#sheet").src = sheetSrc(f);
  if (VBASE && $("#vid").paused) setVid(true);
  const _n = parseInt(f.slice(1,6),10), _t = (_n-1)/10.0;
  $("#cnt").innerHTML = `<span class="fno">${f.replace(".jpg","")}</span>`
      + ` &nbsp;<span class="vtt">t=${_t.toFixed(2)}s</span>`
      + ` &nbsp;<span style="font-size:15px;color:#8b93a3">${cur+1}/${VIEW.length}`
      + (FILTER !== "all" ? " [" + FILTER + "]" : "") + `</span>`;
  $("#sheetfs").href = sheetSrc(f);
  if (HASFULL) $("#fullfs").href = f;
  const pt = prioTag(f), tg = $("#prioTag");
  if (pt){ tg.style.display="inline"; tg.textContent=pt.txt; tg.style.background=pt.bg; tg.style.color=pt.fg; }
  else { tg.style.display="none"; }
  const cs = MANIFEST[f];
  const b = $("#btns");
  b.innerHTML = "";
  cs.forEach((c,i) => {
    const el = document.createElement("button");
    const conf = (c.conf1!=null) ? " conf1="+c.conf1.toFixed(2) : "";
    el.className = "cand" + (s.ball.includes(i) ? " on" : "");
    el.textContent = "#"+i+"  ("+conf+")";
    el.onclick = () => toggle(i);
    b.appendChild(el);
  });
  // none / skip reflect
  $("#none").classList.toggle("on", s.none && !s.skip);
  $("#skip").classList.toggle("on", s.skip);
  if (HASFULL){
    const fi = $("#fullimg");
    fi.src = VIEW[cur].replace(".jpg", ".full.jpg");
    const mk = $("#marker");
    if (s.manual){
      mk.style.display = "block";
      mk.style.left = (s.manual.cx / fi.naturalWidth * 100) + "%";
      mk.style.top = (s.manual.cy / fi.naturalHeight * 100) + "%";
    } else { mk.style.display = "none"; }
    $("#visClear").classList.toggle("on", !!s.manual && s.manual.vis==="clear");
    $("#visBlur").classList.toggle("on", !!s.manual && s.manual.vis==="blur");
    $("#visNone").classList.toggle("on", s.invisible);
  }
  // grid
  const g = $("#grid"); g.innerHTML = "";
  VIEW.forEach((ff,i)=>{
    const cell = document.createElement("div");
    const c = cls(ff);
    cell.className = "cell " + c + (i===cur ? " cur":"");
    const n = ff.replace("f","").replace(".jpg","");
    const p = PRIO[ff];
    cell.textContent = (p==="miss" ? "◆" : p==="close" ? "○" : "") + n;
    cell.title = ff + (c?" ["+c+"]":"") + (p==="miss" ? " 待补标(有球未识别)" : p==="close" ? " 特写硬负样本" : "");
    if (p) cell.style.fontWeight = "700";
    cell.onclick = () => { cur=i; render(); };
    g.appendChild(cell);
  });
  const done = FRAMES.filter(f=>cls(f)!=="").length;
  const balls = FRAMES.filter(f=>cls(f)==="ball").length;
  const mans = FRAMES.filter(f=>cls(f)==="manual").length;
  const invs = FRAMES.filter(f=>cls(f)==="invisible").length;
  const missLeft = Object.keys(PRIO).filter(f=>PRIO[f]==="miss" && cls(f)==="").length;
  $("#status").textContent = `已标 ${done}/${FRAMES.length} · 含球 ${balls} · 补标 ${mans} · 真漏检 ${invs}`
      + (Object.keys(PRIO).length ? ` · 待补标剩余 ${missLeft}` : "");
}
function write(s){ labels[VIEW[cur]] = s; save(); render(); }
function toggle(i){
  const s = state(VIEW[cur]);
  if (s.skip) s.skip=false;
  s.none=false;
  s.ball = s.ball.includes(i) ? s.ball.filter(x=>x!==i) : [...s.ball, i];
  write(s);
}
function markNone(){ const s=state(VIEW[cur]); write({ball:[], none:!s.none, skip:false}); }
function markSkip(){ const s=state(VIEW[cur]); write({ball:[], none:false, skip:!s.skip}); }
function clearFrame(){ delete labels[VIEW[cur]]; save(); render(); }

$("#prev").onclick = ()=>{ if(cur>0){cur--; render();} };
$("#next").onclick = ()=>{ if(cur<VIEW.length-1){cur++; render();} };
document.querySelectorAll(".fbtn").forEach(b => b.onclick = () => {
  FILTER = b.dataset.f;
  document.querySelectorAll(".fbtn").forEach(x => x.classList.toggle("on", x === b));
  applyFilter(); render();
});
$("#none").onclick = markNone;
$("#skip").onclick = markSkip;
$("#clear").onclick = clearFrame;
$("#export").onclick = () => {
  const out = FRAMES.map(f=>{
    const s = state(f);
    if (s.skip) return {frame:f, ball_idx:[], skip:true};
    return {frame:f, ball_idx:s.ball.slice(), none:s.none,
            manual: s.manual, invisible: s.invisible};
  });
  const blob = new Blob([JSON.stringify(out,null,1)], {type:"application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "human_labels.json";
  a.click();
  $("#status").textContent = "已导出 " + out.length + " 帧标注 → human_labels.json";
};
document.addEventListener("keydown", e=>{
  if (e.key==="ArrowRight"){ if(cur<VIEW.length-1){cur++; render();} }
  else if (e.key==="ArrowLeft"){ if(cur>0){cur--; render();} }
  else if (e.key==="n"||e.key==="N"){ markNone(); }
  else if (e.key==="s"||e.key==="S"){ markSkip(); }
  else if (/^[0-9]$/.test(e.key)){ const i=parseInt(e.key); if(i<MANIFEST[VIEW[cur]].length) toggle(i); }
});
applyFilter(); render();
if (VBASE) $("#vidpanel").style.display = "block";
if (HASFULL) $("#manualpanel").style.display = "block";
</script>
</body>
</html>
"""

OUT.write_text(HTML.replace("__MANIFEST__", mjson)
               .replace("__PRIO__", prio_json)
               .replace("{TITLE}", TITLE).replace("{LS_KEY}", LS_KEY)
               .replace("{VBASE}", VBASE if VBASE else "")
               .replace("{HASFULL}", "true" if (SHEETS / "f00001.full.jpg").exists() else "false"))
print(f"[labeler] {OUT}  frames={len(frames)}  candidates/frame={[len(manifest[f]) for f in frames[:5]]}")
print(f"[labeler] 优先队列: miss={sum(1 for v in PRIO.values() if v=='miss')} "
      f"close={sum(1 for v in PRIO.values() if v=='close')} "
      f"video={'ON' if VBASE else 'off'}  full={ (SHEETS/'f00001.full.jpg').exists() }")
