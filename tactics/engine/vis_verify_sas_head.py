#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vis_verify_sas_head —— 视觉先自证：把新 sas head(th=0.05 工作点) 的 top-1 拾取框渲染到原图，
确认跟踪器锁定的确是球（非广告板/人脸/光头/观众 FP）。

产出：
  action_work/validate/vis_full_th005.jpg       —— 全帧上下文接触表(20x20)，绿点=top1 球心，红点=其它候选
  action_work/validate/vis_zoom_th005_pNN.jpg   —— top1 放大接触表(6x6)，每格 200x200，标帧号/prob/对角长

⚠️ 新头标签=AI自标(≤74%可靠)，仅探索。本脚本只为人工目视验收门禁自指陷阱。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
FR = AW / "sas_det"
OUT = AW / "validate"

ap = argparse.ArgumentParser()
ap.add_argument("--scores", default=str(OUT / "ball_cand_scores_sas.json"))
ap.add_argument("--th", type=float, default=0.05)
ap.add_argument("--tag", default="th005")
a = ap.parse_args()
SCORES = Path(a.scores)
TH = a.th
MAX_PX = 60.0


def fid(fn):
    return int(fn[1:6])


def main():
    scores = json.loads(SCORES.read_text())
    frames = sorted(scores.keys(), key=fid)

    def top1(frame):
        best = None
        for c in scores.get(frame, []):
            p = c.get("prob", 0.0)
            b = c["bbox"]
            d = math.hypot(b[2] - b[0], b[3] - b[1])
            if p > TH and d < MAX_PX:
                if best is None or p > best[0]:
                    best = (p, b)
        return best

    # ---- 全帧上下文接触表 20x20 ----
    COLS, ROWS = 20, 20
    cw, ch = 160, 90
    sheet = np.full((ROWS * ch, COLS * cw, 3), 18, np.uint8)
    picked_frames = []
    for i, f in enumerate(frames):
        r, c = divmod(i, COLS)
        if r >= ROWS:
            break
        img = cv2.imread(str(FR / f))
        if img is None:
            continue
        cell = cv2.resize(img, (cw, ch))
        t1 = top1(f)
        if t1 is not None:
            p, b = t1
            picked_frames.append(f)
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            sx, sy = cw / img.shape[1], ch / img.shape[0]
            px, py = int(cx * sx), int(cy * sy)
            cv2.circle(cell, (px, py), 3, (0, 200, 0), -1)
            for cc in scores[f]:
                if cc.get("prob", 0.0) > TH:
                    bx, by = (cc["bbox"][0] + cc["bbox"][2]) / 2, (cc["bbox"][1] + cc["bbox"][3]) / 2
                    cv2.circle(cell, (int(bx * sx), int(by * sy)), 1, (0, 0, 200), -1)
        sheet[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw] = cell
    cv2.imwrite(str(OUT / f"vis_full_{a.tag}.jpg"), sheet)
    print(f"[full] {len(picked_frames)}/{len(frames)} 帧有 top1 拾取 -> vis_full_{a.tag}.jpg")

    # ---- top1 放大接触表 6x6 (每格 200x200) ----
    ZCOLS, ZROWS = 6, 6
    zc = 200
    picks = []
    for f in frames:
        t1 = top1(f)
        if t1 is not None:
            picks.append((f, t1))
    npages = (len(picks) + ZCOLS * ZROWS - 1) // (ZCOLS * ZROWS)
    for pg in range(npages):
        chunk = picks[pg * ZCOLS * ZROWS:(pg + 1) * ZCOLS * ZROWS]
        zsheet = np.full((ZROWS * zc, ZCOLS * zc, 3), 24, np.uint8)
        for j, (f, (p, b)) in enumerate(chunk):
            r, c = divmod(j, ZCOLS)
            img = cv2.imread(str(FR / f))
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            half = max(b[2] - b[0], b[3] - b[1]) / 2
            pad = max(half * 4, 40.0)
            x0, y0 = int(cx - pad), int(cy - pad)
            x1, y1 = int(cx + pad), int(cy + pad)
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(img.shape[1], x1), min(img.shape[0], y1)
            crop = img[y0:y1, x0:x1]
            if crop.size == 0:
                crop = np.full((zc, zc, 3), 40, np.uint8)
            crop = cv2.resize(crop, (zc, zc), interpolation=cv2.INTER_LINEAR)
            # 画回原始坐标框(在 crop 内)
            bx0, by0 = int((b[0] - x0) * zc / (x1 - x0)), int((b[1] - y0) * zc / (y1 - y0))
            bx1, by1 = int((b[2] - x0) * zc / (x1 - x0)), int((b[3] - y0) * zc / (y1 - y0))
            bx0, by0, bx1, by1 = max(0, bx0), max(0, by0), min(zc, bx1), min(zc, by1)
            cv2.rectangle(crop, (bx0, by0), (bx1, by1), (0, 200, 0), 2)
            diag = math.hypot(b[2] - b[0], b[3] - b[1])
            cv2.rectangle(crop, (0, 0), (zc, 16), (0, 0, 0), -1)
            cv2.putText(crop, f"{f[1:6]} p={p:.2f} d={diag:.0f}", (3, 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
            zsheet[r * zc:(r + 1) * zc, c * zc:(c + 1) * zc] = crop
        cv2.imwrite(str(OUT / f"vis_zoom_{a.tag}_p{pg+1:02d}.jpg"), zsheet)
        print(f"[zoom] page {pg+1}/{npages} ({len(chunk)} picks) -> vis_zoom_{a.tag}_p{pg+1:02d}.jpg")

    # 统计：对角长分布（球应 ~15-30px，过大会是脸/广告）
    diags = [math.hypot(b[2] - b[0], b[3] - b[1]) for _, (_, b) in picks]
    diags = np.array(diags)
    print(f"\n[pick stats] n={len(diags)} diag median={np.median(diags):.1f} "
          f"p90={np.percentile(diags,90):.1f} max={diags.max():.1f}")
    print(f"  diag<=40px(球尺度): {(diags<=40).sum()} ({(diags<=40).mean()*100:.1f}%)")
    print(f"  diag>50px(疑似脸/广告): {(diags>50).sum()} ({(diags>50).mean()*100:.1f}%)")


if __name__ == "__main__":
    main()
