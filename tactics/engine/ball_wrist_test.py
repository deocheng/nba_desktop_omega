#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""球检 FP 关键信号测试：球心到最近手腕/脚踝关键点的距离是否分离 TP/FP。

对 manifest 60 个标注样本逐窗批量跑 yolo11n-pose（COCO: 9/10=手腕, 15/16=脚踝），
联 labels.json 打印 TP/FP 的距离分布 + 若干候选阈值的精度/召回代价。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
MEAS = Path(str(tactics_data_file("reports/milestone_05/measure")))
POSE = AW / "weights" / "yolo11n-pose.pt"


def main():
    man = json.loads((MEAS / "manifest.json").read_text())
    lab = json.loads((MEAS / "labels.json").read_text())
    model = YOLO(str(POSE))
    # 逐窗批量推理
    byw = {}
    for i, m in enumerate(man):
        byw.setdefault(m["window"], []).append(i)
    kp_of = {}  # idx -> (min_wrist, min_ankle, n_person)
    for w, idxs in byw.items():
        paths = [str(AW / w / man[i]["frame"]) for i in idxs]
        res = model.predict(paths, conf=0.25, device="mps", verbose=False)
        for i, r in zip(idxs, res):
            bx = (man[i]["bbox"][0] + man[i]["bbox"][2]) / 2
            by = (man[i]["bbox"][1] + man[i]["bbox"][3]) / 2
            mw, ma = 1e9, 1e9
            if r.keypoints is not None and len(r.keypoints):
                kps = r.keypoints.data.cpu().numpy()  # [n,17,3]
                for k in kps:
                    for j in (9, 10):  # wrists
                        x, y, c = k[j]
                        if c > 0.3:
                            mw = min(mw, ((bx - x) ** 2 + (by - y) ** 2) ** 0.5)
                    for j in (15, 16):  # ankles
                        x, y, c = k[j]
                        if c > 0.3:
                            ma = min(ma, ((bx - x) ** 2 + (by - y) ** 2) ** 0.5)
            kp_of[i] = (mw if mw < 1e8 else None, ma if ma < 1e8 else None)
    rows = []
    for i, (m, l) in enumerate(zip(man, lab)):
        mw, ma = kp_of[i]
        rows.append({"w": m["window"], "f": m["frame"], "label": l["label"],
                     "wrist": round(mw) if mw else None, "ankle": round(ma) if ma else None,
                     "conf": m["conf"], "inP": m["inP"]})
    print(f"{'样本':<12}{'lab':<5}{'wrist':>7}{'ankle':>7}{'conf':>6}  inP")
    for r in rows:
        print(f"{r['w']}/{r['f'][1:6]:<9}{'TP' if r['label'] else 'FP':<5}"
              f"{str(r['wrist']):>7}{str(r['ankle']):>7}{r['conf']:>6}  {r['inP']}")
    # 分布
    for key in ("wrist", "ankle"):
        tp = [r[key] for r in rows if r["label"] and r[key] is not None]
        fp = [r[key] for r in rows if not r["label"] and r[key] is not None]
        tn = sum(1 for r in rows if r["label"] and r[key] is None)
        fn = sum(1 for r in rows if not r["label"] and r[key] is None)
        print(f"\n{key}: TP n={len(tp)} 中位={sorted(tp)[len(tp)//2] if tp else '-'} | "
              f"FP n={len(fp)} 中位={sorted(fp)[len(fp)//2] if fp else '-'} | 无关键点 TP={tn} FP={fn}")
        for th in (30, 50, 80, 120):
            tpk = sum(1 for v in tp if v <= th); fpk = sum(1 for v in fp if v <= th)
            print(f"  dist<={th}: 保留TP {tpk}/{len(tp)}  杀FP {fpk}/{len(fp)}")
    (MEAS / "wrist_features.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
