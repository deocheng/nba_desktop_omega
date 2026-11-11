#!/usr/bin/env python3
"""A5.6 造尺子：单条轨迹裁定工具（老程目视裁定「这条轨迹是不是同一个人的连续移动」）。

为什么需要它（A5.5 教训）：
  我用「ID 数/寿命」当 KPI → 把「错并」误报成改善；那个指标恰好奖励"并得越多"。
  所以必须先有一把**可信标尺**：让老程对**单条轨迹**裁定，用它校准所有自动指标。

设计（针对"判同一人"这件事，而不是看全图轨迹叠加）：
  - 每条轨迹：等距取 ≤6 帧，把该球员框**裁剪放大**排成一行（看长相/球衣颜色是否同一人）。
  - 同时给出量化：跨度、路径长、最大帧间位移、大跳(>300px)次数。
  - **给出我的自动预判**（有大跳 ⇒ 预判"换人了"），裁定后即可算出预判的命中率 = 指标可信度。
  - 抽样分层：短(≤10帧)/中(11–40)/长(>40)，覆盖各类，避免只抽好的或只抽坏的。

用法：
  engine/track_judge_app.py [--per-seg 8]
  cd action_work && python3 -m http.server 8792
  打开 http://127.0.0.1:8792/track_judge/index.html
"""
import argparse
import json
import random
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUTD = ROOT / "action_work" / "track_judge"
CROPD = OUTD / "crops"
SEGS = ["ep12_s0", "ep1_s0", "ep10_s0", "ep24_s1", "ep46_s0"]
BIG_JUMP = 300.0
CROP_H = 150


def track_seqs(tr):
    by = {}
    for x in tr.get("frames") or []:
        for p in x.get("players") or []:
            b = p["box"]
            by.setdefault(p["id"], []).append(
                (x["idx"], (b[0] + b[2]) / 2, b[3], b))
    for k in by:
        by[k].sort()
    return by


def crop_strip(segdir, seq, out_path, k=6):
    """把该轨迹等距 k 帧的人像裁剪放大横排成一张图。"""
    frames = json.load(open(segdir / "frames.json"))
    path_by_idx = {int(Path(f["path"]).stem[1:]): f["path"] for f in frames}
    idxs = [s[0] for s in seq]
    pick = [idxs[round(i * (len(idxs) - 1) / (k - 1))] for i in range(k)] \
        if len(idxs) >= k else idxs
    imgs = []
    for fi, pick_i in enumerate(pick):
        box = None
        for s in seq:
            if s[0] == pick_i:
                box = s[3]
                break
        if box is None:
            continue
        p = path_by_idx.get(pick_i)
        if not p:
            continue
        img = cv2.imread(p)
        if img is None:
            continue
        x1, y1, x2, y2 = [int(v) for v in box]
        pad = int(0.12 * (y2 - y1)) + 4
        H, W = img.shape[:2]
        x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
        x2, y2 = min(W, x2 + pad), min(H, y2 + pad)
        c = img[y1:y2, x1:x2]
        if c.size == 0:
            continue
        h, w = c.shape[:2]
        c = cv2.resize(c, (max(8, int(w * CROP_H / h)), CROP_H))
        cv2.putText(c, f"f{pick_i}", (4, 20), cv2.FONT_HERSHEY_SIMPLEX,
                    0.62, (0, 0, 0), 4)
        cv2.putText(c, f"f{pick_i}", (4, 20), cv2.FONT_HERSHEY_SIMPLEX,
                    0.62, (80, 240, 255), 2)
        imgs.append(c)
    if not imgs:
        return None
    strip = np.hstack(imgs)
    cv2.imwrite(str(out_path), strip)
    return strip.shape[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-seg", type=int, default=8)
    ap.add_argument("--seed", type=int, default=3)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    OUTD.mkdir(parents=True, exist_ok=True)
    CROPD.mkdir(parents=True, exist_ok=True)

    items = []
    # ② 混入 B 里「有大跳」的轨迹（错并嫌疑）→ 双向检验，避免尺子只有一面
    for seg in SEGS:
        d = SEGD / seg
        fb = d / "tracks_b.json"
        if not fb.exists():
            continue
        seqs = track_seqs(json.load(open(fb)))
        cand = []
        for tid, seq in seqs.items():
            st = []
            for i in range(1, len(seq)):
                df = seq[i][0] - seq[i - 1][0]
                if df <= 0:
                    continue
                st.append(((seq[i][1] - seq[i - 1][1]) ** 2 +
                           (seq[i][2] - seq[i - 1][2]) ** 2) ** 0.5 / df)
            if st and max(st) > BIG_JUMP:
                cand.append((tid, seq))
        rng.shuffle(cand)
        for tid, seq in cand[:2]:      # 每段 2 条
            fn = f"b_{seg}_{tid}.png"
            if not crop_strip(d, seq, CROPD / fn):
                continue
            st = [((seq[i][1] - seq[i - 1][1]) ** 2 +
                   (seq[i][2] - seq[i - 1][2]) ** 2) ** 0.5 /
                  max(seq[i][0] - seq[i - 1][0], 1)
                  for i in range(1, len(seq))]
            items.append({
                "key": f"B:{seg}#{tid}", "seg": seg, "tid": int(tid),
                "bucket": "长", "crop": f"crops/{fn}",
                "n": len(seq), "span": f"{seq[0][0]}–{seq[-1][0]}",
                "path_len": round(sum(st), 1), "max_step": round(max(st), 1),
                "n_big": sum(1 for s in st if s > BIG_JUMP),
                "auto": "疑似换人(有大跳)",
            })

    for seg in SEGS:
        d = SEGD / seg
        if not (d / "tracks.json").exists():
            continue
        tr = json.load(open(d / "tracks.json"))
        seqs = track_seqs(tr)
        buckets = {"短": [], "中": [], "长": []}
        for tid, seq in seqs.items():
            n = len(seq)
            b = "短" if n <= 10 else ("中" if n <= 40 else "长")
            buckets[b].append((tid, seq))
        # 分层抽样：短2 中2 长2
        want = {"短": 2, "中": 2, "长": 2}
        picks = []
        for b, lst in buckets.items():
            rng.shuffle(lst)
            picks += [(b, t) for t in lst[:want[b]]]
        for b, (tid, seq) in picks:
            steps = []
            for i in range(1, len(seq)):
                df = seq[i][0] - seq[i - 1][0]
                if df <= 0:
                    continue
                steps.append(((seq[i][1] - seq[i - 1][1]) ** 2 +
                              (seq[i][2] - seq[i - 1][2]) ** 2) ** 0.5 / df)
            path_len = sum(steps)
            max_step = max(steps) if steps else 0.0
            n_big = sum(1 for s in steps if s > BIG_JUMP)
            fn = f"{seg}_{tid}.png"
            w = crop_strip(d, seq, CROPD / fn)
            if not w:
                continue
            items.append({
                "key": f"{seg}#{tid}", "seg": seg, "tid": int(tid),
                "bucket": b, "crop": f"crops/{fn}",
                "n": len(seq), "span": f"{seq[0][0]}–{seq[-1][0]}",
                "path_len": round(path_len, 1),
                "max_step": round(max_step, 1), "n_big": n_big,
                # 我的自动预判（待老程裁定校准）
                "auto": "疑似换人(有大跳)" if n_big > 0 else "疑似同一人",
            })
    rng.shuffle(items)   # 打乱顺序：base / B 样本混排，避免老程从位置猜到来源
    print(f"[尺子] 段 {len(SEGS)} ｜ 轨迹样本 {len(items)} 条")
    from collections import Counter
    print("分层:", dict(Counter(i["bucket"] for i in items)))
    print("自动预判:", dict(Counter(i["auto"] for i in items)))

    payload = json.dumps({"items": items, "big_jump": BIG_JUMP},
                         ensure_ascii=False)
    (OUTD / "index.html").write_text(HTML.replace("__PAYLOAD__", payload),
                                     encoding="utf-8")
    print(f"-> {OUTD/'index.html'}")
    print("起服务： cd action_work && python3 -m http.server 8792")
    print("打开： http://127.0.0.1:8792/track_judge/index.html")


HTML = r"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>单条轨迹裁定（校准尺子）</title>
<style>
 body{background:#111;color:#eee;font:15px/1.6 -apple-system,"PingFang SC",sans-serif;
   margin:0;padding:0 0 60px}
 .top{position:sticky;top:0;background:#111;padding:12px 28px;border-bottom:1px solid #333;
   z-index:9;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
 .num{font-size:26px;font-weight:700;color:#ffd166}
 button{background:#222;color:#eee;border:1px solid #555;border-radius:6px;padding:7px 14px;
   font-size:15px;cursor:pointer}
 button:hover{background:#333}
 .ok{background:#0a5;border-color:#0a5;font-weight:700}
 .no{background:#a33;border-color:#a33;font-weight:700}
 .bx{padding:18px 28px;border-bottom:1px solid #2a2a2a}
 img{display:block;max-width:100%;border:1px solid #444;margin:8px 0;cursor:zoom-in}
 .meta{color:#9cf;font-size:14px}
 .auto{color:#ffd166;font-size:15px;margin:6px 0}
 .hd{display:flex;gap:16px;align-items:center;flex-wrap:wrap}
 .tag{background:#2a2a3d;border:1px solid #555;border-radius:5px;padding:2px 9px;font-size:13px}
 input[type=text]{background:#1a1a1a;color:#eee;border:1px solid #555;border-radius:6px;
   padding:6px;font-size:15px;width:280px}
</style></head><body>
<div class="top">
 <b>单条轨迹裁定</b>
 <span class="num" id="prog">0/0</span>
 <progress id="bar" value="0" max="1" style="width:180px"></progress>
 <span style="color:#888;font-size:13px">这几张人像是不是同一个人？判定权归老程</span>
 <button class="ok" onclick="exp()">导出裁定 JSON</button>
</div>
<div id="wrap"></div>
<script>
const D=__PAYLOAD__, L={}; let i=0;
function cur(){return D.items[i]}
function render(){
 const s=cur();
 document.getElementById('wrap').innerHTML=`<div class="bx">
  <div class="hd"><span class="num">${i+1}</span>
    <span class="tag">${s.seg} #${s.tid}</span>
    <span class="tag">${s.bucket}轨迹</span>
    <span class="meta">帧 ${s.span}｜${s.n} 帧</span></div>
  <div class="meta">路径长 ${s.path_len}px｜最大帧间位移
    <span class="num" style="font-size:20px">${s.max_step}</span>px｜
    大跳(&gt;${D.big_jump}px) <span class="num" style="font-size:20px">${s.n_big}</span> 次</div>
  <div style="margin:6px 0">
    <button onclick="tog()">显示/隐藏 我的自动预判</button>
    <span class="auto" id="au" style="display:none">自动预判：<b>${s.auto}</b></span>
    <span style="color:#888;font-size:13px">（建议先盲评，再看预判对不对）</span></div>
  <img src="${s.crop}" onclick="zb(this)" title="点击看原图">
  <div style="margin-top:10px">
    <button class="ok" onclick="set('同一人')">✓ 同一人（连续移动）</button>
    <button class="no" onclick="set('换了人')">✗ 中间换了人</button>
    <button onclick="set('看不清')">? 看不清</button>
    <button onclick="set('不确定')">~ 不确定</button>
    <input type="text" id="rm" placeholder="备注（如：第3张起是另一个）">
  </div></div>`;
 const v=L[s.key];
 if(v){document.querySelectorAll('.bx button').forEach(b=>{
   if(b.textContent.indexOf(v.v.split('（')[0].replace('✓ ','').replace('✗ ',''))>=0)
     b.style.outline='2px solid #ffd166';});}
 const rm=document.getElementById('rm');
 rm.value=(v&&v.rm)||'';
 rm.oninput=()=>{stash()};
 document.getElementById('prog').textContent=(i+1)+'/'+D.items.length;
 document.getElementById('bar').value=(i+1)/D.items.length;
 window.scrollTo(0,0);
}
function set(v){
 const s=cur();
 L[s.key]={key:s.key,seg:s.seg,tid:s.tid,v:v,auto:s.auto,
   n_big:s.n_big,max_step:s.max_step,
   rm:(document.getElementById('rm')||{}).value||''};
 render();
}
function stash(){
 const s=cur(); if(!s)return;
 const rm=(document.getElementById('rm')||{}).value||'';
 if(L[s.key])L[s.key].rm=rm;
}
function tog(){const e=document.getElementById('au');
 e.style.display=(e.style.display==='none')?'inline':'none';}
function zb(img){const w=window.open('','_blank');
 w.document.write(`<body style="margin:0;background:#000"><img src="${img.src}"
  style="width:100%"></body>`);}
function exp(){stash();
 const b=new Blob([JSON.stringify(Object.values(L),null,1)],{type:'application/json'});
 const a=document.createElement('a');a.href=URL.createObjectURL(b);
 a.download='track_judge_labels.json';a.click();}
document.addEventListener('keydown',e=>{
 if(e.key==='ArrowRight'){stash();if(i<D.items.length-1){i++;render()}}
 if(e.key==='ArrowLeft'){stash();if(i>0){i--;render()}}
 if(e.key==='1')set('同一人'); if(e.key==='2')set('换了人');});
render();
</script></body></html>
"""

if __name__ == "__main__":
    main()
