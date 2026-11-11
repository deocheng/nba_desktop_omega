#!/usr/bin/env python3
"""A5.1 探针：镜头运动量级 —— 决定轨迹拼接是否需要「相机运动补偿」。

背景：球员 ID 碎片化(177段：中位 187 ID / 寿命 8 帧 / 9.5x 碎片)。
官方根因=「连续摇镜/变焦」=> 同一球员右出左进，图像坐标不连续。
若镜头位移确实显著，则纯图像空间拼接无效，必须先做运动补偿。

方法（只读，不重跑任何模型）：
  1. 对抽样的段，逐帧读 frames/*.jpg → 灰度 → 降采样。
  2. 相邻帧 cv2.phaseCorrelate 估全局平移 (dx,dy) + 响应。
  3. 报告：每帧位移中位/最大、全段累计镜头路径、与人数/段长对比。
  4. 交叉检验：从 tracks.json 取逐帧球员框中位位移，与镜头位移对比。
"""
import glob
import json
import statistics
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
W = 480  # 降采样宽度


def gray(p):
    img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    h = int(img.shape[0] * W / img.shape[1])
    return cv2.resize(img, (W, h))


def person_median_shift(tracks):
    """逐帧球员框中位位移（图像空间），用于与镜头位移交叉检验。"""
    fr = tracks.get("frames") or []
    shifts = []
    prev = None
    for x in fr:
        ps = x.get("players") or []
        if not ps:
            continue
        cen = np.array([[ (p["box"][0]+p["box"][2])/2,
                         (p["box"][1]+p["box"][3])/2] for p in ps])
        med = np.median(cen, axis=0)
        if prev is not None:
            shifts.append(float(np.linalg.norm(med - prev)))
        prev = med
    return statistics.median(shifts) if shifts else 0.0


def main():
    segs = sorted([d for d in SEGD.iterdir() if d.is_dir()])[:6]
    print(f"{'seg':10s} {'frames':>6s} {'medShift':>9s} {'maxShift':>9s} "
          f"{'respMed':>8s} {'camPath':>8s} {'pplShift':>9s}")
    allmag, allpath = [], []
    for sd in segs:
        fs = sorted((sd / "frames").glob("*.jpg"))
        if len(fs) < 5:
            continue
        prev = gray(fs[0])
        mags, resps, path = [], [], 0.0
        for p in fs[1:]:
            cur = gray(p)
            if cur is None or cur.shape != prev.shape:
                prev = cur
                continue
            try:
                (dx, dy), resp = cv2.phaseCorrelate(
                    np.float32(prev), np.float32(cur))
            except Exception:
                prev = cur
                continue
            m = float(np.hypot(dx, dy))
            mags.append(m)
            resps.append(resp)
            path += m
            prev = cur
        if not mags:
            continue
        tr = json.load(open(sd / "tracks.json"))
        pshift = person_median_shift(tr)
        allmag += mags
        allpath.append(path)
        print(f"{sd.name:10s} {len(fs):6d} {statistics.median(mags):9.2f} "
              f"{max(mags):9.2f} {statistics.median(resps):8.3f} "
              f"{path:8.1f} {pshift:9.2f}")

    if allmag:
        print("\n=== 抽样汇总（降采样 %dpx 宽，单位=像素）===" % W)
        print(f"每帧镜头位移: 中位 {statistics.median(allmag):.2f}px  "
              f"p90 {sorted(allmag)[int(len(allmag)*0.9)]:.2f}px  "
              f"max {max(allmag):.2f}px")
        print(f"全段镜头累计路径: 中位 {statistics.median(allpath):.1f}px")
        # 参照：1080p 全宽下球员框高约 130-170px；W=480 时约 x0.44
        print("→ 判读: 若每帧位移中位显著>1px 且累计路径 >> 球员框尺寸，"
              "则镜头运动主导，拼接必须补偿")


if __name__ == "__main__":
    main()
