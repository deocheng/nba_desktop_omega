#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sas_det 候选云三面板标注 sheet 渲染器（A4.23 自标，用户授权覆盖 74.4% 门禁）。

每帧输出一张合成图：
  左 = 全帧缩略(上下文否决) + 候选框#i；
  右 = 各候选 5× 紧放大(找球缝黑弧/十字纹) 横排，格头只印 #i（不印帧号，防记忆污染）。
并写 manifest.json：frame -> [{idx,bbox,conf1,conf2}]，供标注回映射。

用法:
  python engine/make_sas_det_sheet.py --stride 6 --max-frames 80 \
      --out action_work/validate/sas_det_sheets/ --manifest action_work/validate/sas_det_sheets/manifest.json
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default="sas_det")
    ap.add_argument("--cands", default=str(AW / "validate" / "sas_det_cands.json"))
    ap.add_argument("--frames-dir", default=str(AW / "sas_det"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--stride", type=int, default=6)
    ap.add_argument("--max-frames", type=int, default=80)
    ap.add_argument("--full-w", type=int, default=300)
    ap.add_argument("--zoom", type=int, default=150)
    ap.add_argument("--zfac", type=float, default=5.0)
    ap.add_argument("--extra-json", default=None,
                    help="shot_types.json：追加指定类型帧（close=特写硬负样本进真值）")
    ap.add_argument("--extra-type", default="close")
    ap.add_argument("--extra-cap", type=int, default=10)
    ap.add_argument("--extra-frames", default=None,
                    help="强制追加帧号（逗号分隔），如 204,205 —— 用于补齐采样遗漏帧")
    ap.add_argument("--copy-full", action="store_true", default=True,
                    help="把原分辨率帧复制为 <frame>.full.jpg（补标点球心用）")
    a = ap.parse_args()

    cands = json.loads(Path(a.cands).read_text())[a.clip]
    fdir = Path(a.frames_dir)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    frames = sorted(cands.keys())
    sel = frames[:: a.stride][: a.max_frames]
    print(f"selected {len(sel)} frames (stride={a.stride}, max={a.max_frames})")
    if a.extra_json:
        st = json.loads(Path(a.extra_json).read_text())["frames"]
        extra = [fn for fn, v in sorted(st.items())
                 if v["type"] == a.extra_type and fn not in set(sel)]
        sel = sel + extra[: a.extra_cap]
        print(f"+extra[{a.extra_type}]: 追加 {len(extra[:a.extra_cap])} 帧 (候选池外硬负样本)")
    if a.extra_frames:
        ef = [f"f{int(t):05d}.jpg" for t in str(a.extra_frames).replace("f","").replace(".jpg","").split(",") if t.strip()]
        ef = [x for x in ef if (Path(a.frames_dir) / x).exists() and x not in set(sel)]
        sel = sel + ef
        print(f"+extra-frames: 追加 {len(ef)} 帧 {ef}")

    manifest = {}
    for fr in sel:
        img = cv2.imread(str(fdir / fr))
        if img is None:
            continue
        H, W = img.shape[:2]
        scl = a.full_w / W
        fthumb = cv2.resize(img, (a.full_w, int(H * scl)))
        th = fthumb.shape[0]
        cs = cands[fr]
        # 全帧上画候选框 + #i
        for i, c in enumerate(cs):
            b = c["bbox"]
            x1, y1, x2, y2 = [int(v * scl) for v in b]
            cv2.rectangle(fthumb, (x1, y1), (x2, y2), (0, 255, 0), 1)
            cv2.putText(fthumb, f"#{i}", (x1, max(10, y1 - 3)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
        # 各候选 5× 放大
        zooms = []
        row = None
        for i, c in enumerate(cs):
            bx1, by1, bx2, by2 = c["bbox"]
            cx, cy = (bx1 + bx2) / 2, (by1 + by2) / 2
            h = (max(bx2 - bx1, by2 - by1) / 2) * a.zfac
            x1, y1 = int(cx - h), int(cy - h)
            x2, y2 = int(cx + h), int(cy + h)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(W, x2), min(H, y2)
            if x2 <= x1 or y2 <= y1:
                continue
            crop = img[y1:y2, x1:x2]
            z = cv2.resize(crop, (a.zoom, a.zoom), interpolation=cv2.INTER_CUBIC)
            cv2.putText(z, f"#{i}", (3, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            zooms.append(z)
        if zooms:
            zw = max(z.shape[1] for z in zooms)
            zh = max(z.shape[0] for z in zooms)
            zooms_p = [np.pad(z, ((0, zh - z.shape[0]), (0, zw - z.shape[1]), (0, 0)),
                              mode="constant") for z in zooms]
            row = np.hstack(zooms_p)
        # 纵向拼：全帧 + 放大行（高度对齐到全帧高）；无候选帧只出全帧（0 候选合法）
        if row is not None and row.size:
            if row.shape[0] < th:
                row = np.pad(row, ((0, th - row.shape[0]), (0, 0), (0, 0)), mode="constant")
            elif row.shape[0] > th:
                row = row[:th]
            composite = np.hstack([fthumb, row])
        else:
            composite = fthumb
        cv2.imwrite(str(out / fr.replace(".jpg", ".sheet.jpg")), composite)
        # 补标用：原分辨率帧也放进标注目录（点球心需要原分辨率，缩略图精度不够）
        if a.copy_full:
            import shutil
            shutil.copy(fdir / fr, out / fr.replace(".jpg", ".full.jpg"))
        manifest[fr] = [{"idx": i, "bbox": c["bbox"],
                         "conf1": c.get("conf1"), "conf2": c.get("conf2")}
                        for i, c in enumerate(cs)]

    Path(a.manifest).write_text(json.dumps(manifest, indent=1))
    print(f"[manifest] {a.manifest}  frames={len(manifest)}")


if __name__ == "__main__":
    raise SystemExit(main())
