#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_pollution_sheet.py — 生成「污染标注集」用的逐帧大图 + 索引旁表。

为什么要做标注集
----------------
R4 要"把观众/替补/裁判框清干净"，但**"清干净"没有分母**：不清点出每个框到底是什么，
任何过滤规则的效果都只能是自说自话。本脚本产出可目视判读的逐帧大图（框上带**序号**）
与同序号的旁表 JSON，人工（或本 AI 目视）据此标出 on/off-court。

⚠️ 诚实标注：本仓库既有的 A4.11/A4.12 结论是 **REJECT_SELF_AS_ANNOTATOR**（AI 自标
自评不可信，判读者系统性过判）。因此本标注集**只用于筛选规则、不用于宣称精度**：
最终报告里一律写成「与本次目视标注的一致率」，并同时给出可复核的渲染图。

用法
    python engine/_pollution_sheet.py --clips w1,sas_hou --frames 2 --stride 60
"""
from __future__ import annotations

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
OUT = AW / "validate" / "pollution"


def pick_frames(clip, n, stride, suffix="_poss_tile"):
    p = AW / f"{clip}{suffix}" / "ball_tracks.json"
    recs = json.loads(p.read_text())
    order = sorted(range(len(recs)), key=lambda i: str(recs[i].get("file", "")))
    idxs = order[::stride]
    if len(idxs) > n:
        sel = np.linspace(0, len(idxs) - 1, n).astype(int)
        idxs = [idxs[i] for i in sel]
    return recs, [int(i) for i in idxs]


def render(clip, recs, idxs, suffix="_poss_tile"):
    OUT.mkdir(parents=True, exist_ok=True)
    side = {}
    for i in idxs:
        r = recs[i]
        fn = str(r["file"])
        img = cv2.imread(str(AW / clip / fn))
        if img is None:
            continue
        H, W = img.shape[:2]
        ball = r.get("ball")
        if ball and ball.get("bbox"):
            b = [int(v) for v in ball["bbox"]]
            cv2.rectangle(img, (b[0], b[1]), (b[2], b[3]), (0, 165, 255), 3)
            cv2.putText(img, "BALL", (b[0], max(20, b[1] - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 165, 255), 3)
        rows = []
        for k, pl in enumerate(r.get("players", [])):
            x1, y1, x2, y2 = [int(v) for v in pl["bbox"]]
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 3)
            lab = f"#{k}"
            cv2.putText(img, lab, (x1 + 2, y1 + 26), cv2.FONT_HERSHEY_SIMPLEX, 0.95,
                        (0, 0, 0), 6, cv2.LINE_AA)
            cv2.putText(img, lab, (x1 + 2, y1 + 26), cv2.FONT_HERSHEY_SIMPLEX, 0.95,
                        (0, 255, 255), 2, cv2.LINE_AA)
            rows.append({"i": k, "track_id": pl["track_id"], "bbox": [x1, y1, x2, y2],
                         "h": y2 - y1, "cx": int((x1 + x2) / 2), "cy": int((y1 + y2) / 2),
                         "foot_y": y2, "conf": round(float(pl.get("conf", 0)), 3)})
        cv2.putText(img, f"{clip} {fn}  n={len(rows)}", (16, 40), cv2.FONT_HERSHEY_SIMPLEX,
                    1.1, (0, 0, 0), 7, cv2.LINE_AA)
        cv2.putText(img, f"{clip} {fn}  n={len(rows)}", (16, 40), cv2.FONT_HERSHEY_SIMPLEX,
                    1.1, (255, 255, 255), 3, cv2.LINE_AA)
        o = OUT / f"sheet_{clip}_{Path(fn).stem}.jpg"
        cv2.imwrite(str(o), img, [cv2.IMWRITE_JPEG_QUALITY, 93])
        side[f"{clip}/{Path(fn).stem}"] = {"clip": clip, "file": fn, "n": len(rows), "boxes": rows}
        print(f"[out] {o}  n={len(rows)}")
    return side


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", default="w1,sas_hou,sas_nop,sas_det")
    ap.add_argument("--frames", type=int, default=2)
    ap.add_argument("--stride", type=int, default=60)
    ap.add_argument("--suffix", default="_poss_tile")
    a = ap.parse_args()
    allside = {}
    for c in a.clips.split(","):
        c = c.strip()
        if not c:
            continue
        recs, idxs = pick_frames(c, a.frames, a.stride, a.suffix)
        allside.update(render(c, recs, idxs, a.suffix))
    if not allside:
        raise SystemExit("[缺数据] 未生成任何标注图（检查片段名/帧目录）")
    p = OUT / "index.json"
    p.write_text(json.dumps(allside, ensure_ascii=False, indent=1))
    n = sum(v["n"] for v in allside.values())
    print(f"\n[out] {p}  帧={len(allside)} 框={n}")


if __name__ == "__main__":
    main()
