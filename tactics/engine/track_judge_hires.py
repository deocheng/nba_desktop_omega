#!/usr/bin/env python3
"""A5.6b 单条轨迹的**高像素**复核图（老程要看清某条几乎没内容的裁剪图时用）。

输出两张：
  1) *_ctx.png  —— 中间帧**全画幅**（原生分辨率），把该轨迹的框画红框+帧号
                   ⇒ 让老程看清"这条轨迹在画面哪个位置/有多小"。
  2) *_hires.png —— 等距取 N 帧，裁剪后**放大到高像素**横排（不再压到 150px）。

用法：
  engine/track_judge_hires.py --seg ep24_s1 --tid 116 --src tracks_b.json [--n 10] [--h 420]
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUTD = ROOT / "action_work" / "track_judge" / "hires"


def seq_of(tr, tid):
    out = []
    for x in tr.get("frames") or []:
        for p in x.get("players") or []:
            if p["id"] == tid:
                out.append((x["idx"], p["box"]))
    out.sort()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", required=True)
    ap.add_argument("--tid", type=int, required=True)
    ap.add_argument("--src", default="tracks_b.json")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--h", type=int, default=420)
    a = ap.parse_args()

    d = SEGD / a.seg
    tr = json.load(open(d / a.src))
    frames = json.load(open(d / "frames.json"))
    by_idx = {int(Path(f["path"]).stem[1:]): f["path"] for f in frames}
    seq = seq_of(tr, a.tid)
    if not seq:
        print("未找到该轨迹"); return
    OUTD.mkdir(parents=True, exist_ok=True)
    tag = f"{a.seg}_{a.tid}_{a.src.replace('.json','')}"

    # 1) 上下文全画幅
    mid = seq[len(seq) // 2][0]
    img = cv2.imread(by_idx[mid])
    for fi, box in seq:
        if fi != mid:
            continue
        x1, y1, x2, y2 = [int(v) for v in box]
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 3)
        cv2.putText(img, f"tid{a.tid} f{fi}  {x2-x1}x{y2-y1}px",
                    (x1, max(20, y1 - 12)), cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, (0, 0, 255), 3)
    cv2.putText(img, f"{a.seg} tid={a.tid} ({a.src})  框尺寸 {int(seq[len(seq)//2][1][2]-seq[len(seq)//2][1][0])}x{int(seq[len(seq)//2][1][3]-seq[len(seq)//2][1][1])}px",
                (16, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 6)
    cv2.putText(img, f"{a.seg} tid={a.tid} ({a.src})", (16, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (80, 240, 255), 2)
    p1 = OUTD / f"{tag}_ctx.png"
    cv2.imwrite(str(p1), img)

    # 2) 高像素裁剪横排
    idxs = [s[0] for s in seq]
    k = min(a.n, len(idxs))
    pick = [idxs[round(i * (len(idxs) - 1) / (k - 1))] for i in range(k)] if k > 1 else idxs
    imgs = []
    for pi in pick:
        box = next((b for f, b in seq if f == pi), None)
        if box is None:
            continue
        im = cv2.imread(by_idx[pi])
        if im is None:
            continue
        bx1, by1, bx2, by2 = [int(v) for v in box]
        bw, bh = bx2 - bx1, by2 - by1
        pad = int(0.25 * bh) + 10
        H, W = im.shape[:2]
        x1, y1 = max(0, bx1 - pad), max(0, by1 - pad)
        x2, y2 = min(W, bx2 + pad), min(H, by2 + pad)
        c = im[y1:y2, x1:x2]
        if c.size == 0:
            continue
        h0, w0 = c.shape[:2]
        mag = a.h / h0
        c = cv2.resize(c, (max(10, int(w0 * mag)), a.h),
                       interpolation=cv2.INTER_CUBIC)
        # 在放大图上把"真实框"描红 —— 裁剪条本身=框+25%留白，红框标出框的确切边界
        rx1 = int((bx1 - x1) * mag)
        ry1 = int((by1 - y1) * mag)
        rx2 = int((bx2 - x1) * mag)
        ry2 = int((by2 - y1) * mag)
        cv2.rectangle(c, (rx1, ry1), (rx2, ry2), (0, 0, 255), 2)
        lab = f"f{pi}  box {bw}x{bh}px  x{mag:.0f}"
        cv2.putText(c, lab, (6, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                    (0, 0, 0), 6)
        cv2.putText(c, lab, (6, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                    (80, 240, 255), 2)
        imgs.append(c)
    p2 = OUTD / f"{tag}_hires.png"
    seps = [np.full((a.h, 6, 3), 255, np.uint8)] * (len(imgs) - 1)
    inter = []
    for i, im in enumerate(imgs):
        inter.append(im)
        if i < len(seps):
            inter.append(seps[i])
    cv2.imwrite(str(p2), np.hstack(inter))
    print(f"轨迹 {a.seg}#{a.tid} 共 {len(seq)} 帧 跨度 {seq[0][0]}–{seq[-1][0]}")
    print(f"-> {p1}")
    print(f"-> {p2}")


if __name__ == "__main__":
    main()
