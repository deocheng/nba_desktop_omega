#!/usr/bin/env python3
"""Generate a focused visual re-verification page for the 6 Tier-A frames
(detector FULLY silent: conf1==0 AND crop_any==0).

For each frame we render:
  - full frame with the clicked ball-center marker (green, 26px box)
  - a 512x512 crop centered on the clicked center (green marker redrawn)
  - a 5-frame neighbor strip (idx-2..idx+2) for the motion test
    (ball should translate across frames; a static blob = background)

Output: action_work/validate/tierA_verify/{tierA_verify.html, *_crop.jpg, *_neighbors.jpg}
"""
import json
import os
import sys

import cv2
import numpy as np

VAL = "action_work/validate"
SHEETS = os.path.join(VAL, "sas_lal_sheets")
OUT = os.path.join(VAL, "tierA_verify")
os.makedirs(OUT, exist_ok=True)

bank = json.load(open(os.path.join(VAL, "sas_lal_label_bank_manual.json")))
human = json.load(open(os.path.join(VAL, "sas_lal_label_bank_human.json")))
inhuman = {L["frame"]: L for L in human["labels"]}

manual = [L for L in bank["labels"] if L.get("source") == "manual"]
tierA = [L for L in manual
         if (L.get("conf1") or 0.0) == 0.0
         and (L.get("measure", {}).get("conf2_any_in_crop", 0.0) or 0.0) == 0.0]
tierA.sort(key=lambda L: int(L["frame"][1:6]))
print(f"Tier A frames: {[L['frame'] for L in tierA]}")

def cx_of(b):
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2

def read_full(frame):
    p = os.path.join(SHEETS, frame.replace(".jpg", ".full.jpg"))
    im = cv2.imread(p)
    if im is None:
        p2 = os.path.join(SHEETS, frame)
        im = cv2.imread(p2)
    return im

cards = []
for L in tierA:
    frame = L["frame"]
    idx = int(frame[1:6])
    bb = L["bbox"]
    cx, cy = cx_of(bb)
    vis = L.get("vis", "?")
    im = read_full(frame)
    if im is None:
        print("MISSING", frame); continue
    H, W = im.shape[:2]

    # 1) full-frame with marker
    full = im.copy()
    cv2.rectangle(full, (int(bb[0]), int(bb[1])), (int(bb[2]), int(bb[3])),
                  (70, 180, 110), 3)
    cv2.circle(full, (int(cx), int(cy)), 4, (70, 180, 110), -1)
    # shade 512 crop window for context
    x0 = max(0, int(cx) - 256); y0 = max(0, int(cy) - 256)
    x1 = min(W, int(cx) + 256); y1 = min(H, int(cy) + 256)
    cv2.rectangle(full, (x0, y0), (x1, y1), (120, 120, 120), 1)
    full_p = os.path.join(OUT, frame.replace(".jpg", "_full.jpg"))
    cv2.imwrite(full_p, full)

    # 2) 512 crop centered on click
    crop = np.full((512, 512, 3), 24, dtype=np.uint8)
    sx0 = int(cx) - 256; sy0 = int(cy) - 256
    src_x0 = max(0, sx0); src_y0 = max(0, sy0)
    src_x1 = min(W, sx0 + 512); src_y1 = min(H, sy0 + 512)
    if src_x1 > src_x0 and src_y1 > src_y0:
        dst_x0 = max(0, -sx0); dst_y0 = max(0, -sy0)
        dst_x1 = dst_x0 + (src_x1 - src_x0)
        dst_y1 = dst_y0 + (src_y1 - src_y0)
        crop[dst_y0:dst_y1, dst_x0:dst_x1] = im[src_y0:src_y1, src_x0:src_x1]
    # marker on crop (center relative to source origin)
    lx = int(cx - src_x0); ly = int(cy - src_y0)
    cv2.rectangle(crop, (lx - 13, ly - 13), (lx + 13, ly + 13), (70, 180, 110), 3)
    cv2.circle(crop, (lx, ly), 4, (70, 180, 110), -1)
    crop_p = os.path.join(OUT, frame.replace(".jpg", "_crop.jpg"))
    cv2.imwrite(crop_p, crop)

    # 3) neighbor strip idx-2..idx+2
    neigh = []
    for j in range(idx - 2, idx + 3):
        if 1 <= j <= 400:
            fn = f"f{j:05d}.jpg"
            imj = read_full(fn)
            if imj is not None:
                imj = cv2.resize(imj, (384, 216))
                cv2.rectangle(imj, (0, 0), (383, 215),
                              (70, 180, 110) if j == idx else (90, 90, 90), 3)
                cv2.putText(imj, f"f{j:05d}", (8, 22),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                neigh.append(imj)
    if neigh:
        strip = np.hstack(neigh)
        strip_p = os.path.join(OUT, frame.replace(".jpg", "_neighbors.jpg"))
        cv2.imwrite(strip_p, strip)

    # bank conflict note
    conflict = ""
    if frame in inhuman and isinstance(inhuman[frame], list):
        labels = [x["label"] for x in inhuman[frame]]
        conflict = f"⚠️ 人类 bank 同帧标为 {labels}（无球）— 与本次点击冲突"
    elif frame in inhuman:
        conflict = f"⚠️ 人类 bank 同帧：{inhuman[frame].get('label')}"

    cards.append(dict(frame=frame, idx=idx, cx=round(cx), cy=round(cy),
                      vis=vis, conflict=conflict,
                      full=os.path.basename(full_p),
                      crop=os.path.basename(crop_p),
                      neighbors=os.path.basename(strip_p) if neigh else ""))

# build interactive HTML
import json as _json

frames_json = _json.dumps(cards, ensure_ascii=False)

TEMPLATE = """<!doctype html><html><head><meta charset='utf-8'><title>Tier A 逐帧复裁</title>
<style>
body{background:#111;color:#eee;font:14px sans-serif;margin:20px}
.bar{position:sticky;top:0;background:#1a1a1a;padding:10px;border-bottom:1px solid #444;z-index:10;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.bar button{background:#2a4;color:#fff;border:0;padding:8px 14px;border-radius:6px;cursor:pointer;font-size:14px}
.bar button.alt{background:#357}
#prog{color:#6b6;font-weight:bold}
.card{border:1px solid #444;margin:18px 0;padding:12px;border-radius:8px}
h2{color:#6b6;margin:0 0 6px}h3{color:#ccc;margin:6px 0}
.row{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-start}
.full{max-width:560px}.crop{max-width:430px}.neigh{max-width:100%}
.warn{color:#f96;font-weight:bold}.meta{color:#9ad}
img{display:block;border:1px solid #333}
.vbtns{margin-top:8px;display:flex;gap:8px}
.vbtn{padding:7px 13px;border-radius:6px;cursor:pointer;border:1px solid #555;background:#222;color:#eee;font-size:13px}
.vbtn.sel-y{background:#161;color:#fff;border-color:#6b6}
.vbtn.sel-n{background:#611;border-color:#f66;color:#fff}
.vbtn.sel-i{background:#444;border-color:#999;color:#fff}
.vstat{margin-left:10px;color:#fd6;font-weight:bold}
</style></head><body>
<div class='bar'>
  <span id='prog'>已裁定 0/__N__</span>
  <button onclick='exportJSON()'>导出裁定 JSON</button>
  <button class='alt' onclick='copyText()'>复制裁定文本</button>
  <button class='alt' onclick='resetAll()'>清空全部</button>
</div>
<h1>Tier A 逐帧复裁（检测器完全沉默的 6 帧）</h1>
<p class='meta'>判定标准：球应沿邻帧连续移动（运动检验）；静止斑块=背景。
检测器在 512px 裁切内零响应 ⇒ 点击可能偏位或球确不可见。请逐帧点「是球 / 误点 / 不可见」。
裁定存本地（localStorage），可导出回贴给我。</p>
<div id='cards'></div>
<script>
const FRAMES = __FRAMES__;
const VMAP = {y:'是球（保留）', n:'误点（删除）', i:'不可见（invisible）'};
function load(f){ return localStorage.getItem('tierA_'+f) || ''; }
function save(f,v){ if(v) localStorage.setItem('tierA_'+f,v); else localStorage.removeItem('tierA_'+f); render(); }
function render(){
  const root=document.getElementById('cards'); root.innerHTML='';
  let done=0;
  FRAMES.forEach(c=>{
    const v=load(c.frame); if(v) done++;
    const card=document.createElement('div'); card.className='card';
    let h=`<h2>${c.frame}  (点击中心 x=${c.cx}, y=${c.cy}, vis=${c.vis})</h2>`;
    if(c.conflict) h+=`<p class='warn'>${c.conflict}</p>`;
    h+=`<div class='row'>`;
    h+=`<div><h3>原帧（绿框=你点的位置）</h3><img class='full' src='${c.full}'></div>`;
    h+=`<div><h3>512px 裁切（放大，绿圈=点击中心）</h3><img class='crop' src='${c.crop}'></div>`;
    h+=`</div>`;
    if(c.neighbors) h+=`<h3>邻帧运动条（idx-2..idx+2，绿框=本帧；看球是否连续移动）</h3><img class='neigh' src='${c.neighbors}'>`;
    h+=`<div class='vbtns'>`;
    h+=`<button class='vbtn ${v==='y'?'sel-y':''}' onclick="save('${c.frame}','y')">是球（保留）</button>`;
    h+=`<button class='vbtn ${v==='n'?'sel-n':''}' onclick="save('${c.frame}','n')">误点（删除）</button>`;
    h+=`<button class='vbtn ${v==='i'?'sel-i':''}' onclick="save('${c.frame}','i')">不可见</button>`;
    h+=`<span class='vstat'>${v?('裁定：'+VMAP[v]):'未裁定'}</span>`;
    h+=`</div>`;
    card.innerHTML=h; root.appendChild(card);
  });
  document.getElementById('prog').textContent='已裁定 '+done+'/'+FRAMES.length;
}
function verdicts(){
  const o={}; FRAMES.forEach(c=>{ const v=load(c.frame); if(v) o[c.frame]=VMAP[v]; }); return o;
}
function exportJSON(){
  const data={clip:'sas_lal', frames:FRAMES.map(c=>({frame:c.frame, cx:c.cx, cy:c.cy, verdict:load(c.frame)})),
              exported_at:new Date().toISOString()};
  const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});
  const a=document.createElement('a'); a.href=URL.createObjectURL(blob);
  a.download='tierA_verdicts.json'; a.click();
}
function copyText(){
  const v=verdicts(); let s='';
  FRAMES.forEach(c=>{ s+= c.frame+'='+(v[c.frame]||'未裁定')+'; '; });
  navigator.clipboard.writeText(s).then(()=>alert('已复制：'+s));
}
function resetAll(){ if(confirm('清空全部裁定？')){ FRAMES.forEach(c=>localStorage.removeItem('tierA_'+c.frame)); render(); } }
render();
</script>
</body></html>"""

html = TEMPLATE.replace("__FRAMES__", frames_json).replace("__N__", str(len(cards)))
with open(os.path.join(OUT, "tierA_verify.html"), "w") as f:
    f.write(html)
print("WROTE", os.path.join(OUT, "tierA_verify.html"))
print("cards:", len(cards))
