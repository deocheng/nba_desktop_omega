#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""expand_cand_pool.py —— 把指定帧的候选池从 top-4 扩到 top-N，并**按现役口径补算 conf2**。

为什么必须补算 conf2：现役管线 conf2 = 256px 裁切放大 384² 二次复验分数，是头特征之一。
若扩容候选直接 conf2=0，会比现役 top-4 系统性吃亏 → 人为制造「扩容无用」的假阴性（自证）。
本脚本对每个扩容候选实跑同口径复验，保证 top-4 vs top-5..N 的对照公平。

用法:
  python engine/expand_cand_pool.py --clip sas_det \
      --probe action_work/validate/cand_probe_frames.json --topn 20 \
      --out action_work/validate/sas_det_expanded_cands.json
产出: {"<clip>_expanded": {fn: [{bbox, conf1, conf2, src}]}}；src=live(现役top4) / expand(新增)
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import time
from pathlib import Path

import cv2
import torch
from transformers import AutoImageProcessor, AutoModelForObjectDetection

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
RF = (str(Path.home() / ".cache/huggingface/hub/models--koppolusameer--")
      + "rfdetr-basketball-player-ball-referee-detection/snapshots/"
      + "46c33088c790670a7e81e21e753fa368b2d77a70")
BALL = 0


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x2 - x1) * max(0, y2 - y1)
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - i
    return i / ua if ua > 0 else 0.0


def verify(proc, model, dev, img, bbox):
    """与 validate_clips.py 完全同口径的 256px 复验 → conf2"""
    x1, y1, x2, y2 = bbox
    cx, cy = (x1+x2)/2, (y1+y2)/2
    h = 128
    X1, Y1 = int(cx-h), int(cy-h)
    sx1, sy1 = max(0, X1), max(0, Y1)
    sx2, sy2 = min(img.shape[1], X1+256), min(img.shape[0], Y1+256)
    crop = img[sy1:sy2, sx1:sx2]
    if crop.shape[0] < 30 or crop.shape[1] < 30:
        return 0.0
    sc = 384.0 / crop.shape[1]
    mb = [(x1-X1)*sc, (y1-Y1)*sc, (x2-X1)*sc, (y2-Y1)*sc]
    rgb = cv2.cvtColor(cv2.resize(crop, (384, 384), interpolation=cv2.INTER_CUBIC), cv2.COLOR_BGR2RGB)
    inp = proc(images=rgb, return_tensors="pt").to(dev)
    with torch.no_grad():
        o = model(**inp)
    res = proc.post_process_object_detection(
        o, threshold=0.05, target_sizes=torch.tensor([[384, 384]]).to(dev))[0]
    best = 0.0
    for b, s, li in zip(res["boxes"].tolist(), res["scores"].tolist(), res["labels"].tolist()):
        if int(li) == BALL and iou(b, mb) > 0.3:
            best = max(best, float(s))
    return round(best, 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default="sas_det")
    ap.add_argument("--probe", default="action_work/validate/cand_probe_frames.json")
    ap.add_argument("--live-cands", default=None, help="现役 <clip>_cands.json（top4 的真实 conf2 来源）")
    ap.add_argument("--frames-dir", default=None)
    ap.add_argument("--topn", type=int, default=20)
    ap.add_argument("--device", default="mps")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    probe = json.loads((ROOT / a.probe).read_text())["frames"]
    livep = Path(a.live_cands) if a.live_cands else ROOT / "action_work/validate" / f"{a.clip}_cands.json"
    live = json.loads(livep.read_text())[a.clip]
    fdir = Path(a.frames_dir) if a.frames_dir else ROOT / "action_work" / a.clip
    dev = a.device if (a.device != "mps" or torch.backends.mps.is_available()) else "cpu"
    proc = AutoImageProcessor.from_pretrained(RF)
    model = AutoModelForObjectDetection.from_pretrained(RF).to(dev).eval()

    out = {}
    t0 = time.time()
    for fn, raw in probe.items():
        img = cv2.imread(str(fdir / fn))
        if img is None:
            print(f"  [skip] {fn}"); continue
        rows = []
        for i, c in enumerate(raw[:a.topn]):
            b = [float(v) for v in c["bbox"]]
            rows.append({"bbox": b, "conf1": round(float(c["conf"]), 3),
                         "conf2": verify(proc, model, dev, img, b),
                         "src": "live" if i < 4 else "expand"})
        out[fn] = rows
        print(f"  {fn}: n={len(rows)} conf1[0,3,7,-1]={[rows[j]['conf1'] for j in (0,3,7,len(rows)-1)]} "
              f"conf2max={max(r['conf2'] for r in rows):.3f}  ({time.time()-t0:.0f}s)", flush=True)

    clipexp = f"{a.clip}_expanded"
    op = Path(a.out) if a.out else ROOT / "action_work/validate" / f"{clipexp}_cands.json"
    op.write_text(json.dumps({clipexp: out}))
    print(f"[out] {op}  {len(out)} 帧 {sum(len(v) for v in out.values())} 候选  {time.time()-t0:.0f}s")
    print(f"→ 下一步: python engine/rescore_clip_heads.py --clip {clipexp} --cands {op}")


if __name__ == "__main__":
    main()
