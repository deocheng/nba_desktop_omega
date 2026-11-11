#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_sample_band.py — 目视取证：底部带里被 item4 **保留**的小框到底是不是观众。

为什么要专门看这个
------------------
R3-b 的网格图暴露：w1「框相交 + 足点同高(dy≈0)」的 pair 几乎全是**看台上并排坐着的观众**，
说明 item4（透视平面判据）在**近端看台**仍有系统性残余——而这些框 h≈80–150，
却因为 `HMIN(w1)=70` 被放行（70 是按**最小 24 框**标定的，只覆盖了最底排）。
本脚本把「底部带(y_foot≥0.80H) 且 h 低于候选阈值」的**保留框**全部摊开，
以确认「band 条件身高下限」这条规则打掉的到底是不是观众。
用法：
    python engine/_sample_band.py --clip w1 --ymin 0.80 --hmax 170 --per 20
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", required=True)
    ap.add_argument("--filter", default=str(AW / "validate" / "player_plane_filter.json"))
    ap.add_argument("--ymin", type=float, default=0.80, help="底部带起点 = ymin*1080")
    ap.add_argument("--hmax", type=float, default=170.0)
    ap.add_argument("--per", type=int, default=20, help="每张贴多少格")
    ap.add_argument("--side", type=int, default=240)
    a = ap.parse_args()

    d = json.loads(Path(a.filter).read_text())[a.clip]
    H = 1080.0
    rows = [r for r in d["rows"] if r.get("keep") and r["foot_y"] >= a.ymin * H
            and r["h"] < a.hmax]
    print(f"[{a.clip}] 底部带(y>={a.ymin*H:.0f}) 保留且 h<{a.hmax} 的框 = {len(rows)}")
    if not rows:
        return
    # 按 h 升序，均匀抽样铺开
    rows.sort(key=lambda r: r["h"])
    step = max(1, len(rows) // a.per)
    pick = rows[::step][:a.per]
    cells, meta = [], []
    for r in pick:
        fp = AW / a.clip / r["file"]
        img = cv2.imread(str(fp))
        if img is None:
            continue
        b = r["bbox"]
        h = max(10.0, b[3] - b[1])
        x1 = int(b[0] - 0.25 * h); y1 = int(b[1] - 0.35 * h)
        x2 = int(b[2] + 0.25 * h); y2 = int(b[3] + 0.45 * h)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(img.shape[1], x2), min(img.shape[0], y2)
        crop = img[y1:y2, x1:x2].copy()
        bx1, by1 = int(b[0]) - x1, int(b[1]) - y1
        bx2, by2 = int(b[2]) - x1, int(b[3]) - y1
        cv2.rectangle(crop, (bx1, by1), (bx2, by2), (0, 0, 255), 2)
        # 画该帧球场平面所预期的身高（用它来判断"矮"是否被合理化）
        sc = a.side / max(crop.shape[0], crop.shape[1])
        crop = cv2.resize(crop, (max(1, int(crop.shape[1] * sc)), max(1, int(crop.shape[0] * sc))))
        pad = np.full((a.side, a.side, 3), 35, np.uint8)
        pad[:crop.shape[0], :crop.shape[1]] = crop
        lab = f"{r['file'][:6]} t{r['track_id']} h={r['h']:.0f} rel={r['rel']:+.2f}"
        cv2.putText(pad, lab, (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1)
        cells.append(pad)
        meta.append({"file": r["file"], "track_id": r["track_id"], "h": round(r["h"], 1),
                     "foot_y": round(r["foot_y"], 1), "rel": round(r["rel"], 3)})
    if not cells:
        return
    cols = 5
    while len(cells) % cols:
        cells.append(np.full((a.side, a.side, 3), 35, np.uint8))
    rows_img = [np.hstack(cells[i:i + cols]) for i in range(0, len(cells), cols)]
    sheet = np.vstack(rows_img)
    out = AW / "validate" / "pollution" / f"band_{a.clip}_y{int(a.ymin*100)}_h{int(a.hmax)}.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), sheet)
    out.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print(f"[out] {out}  ({len(meta)} 格)")


if __name__ == "__main__":
    main()
