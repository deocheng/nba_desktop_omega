#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_ballfeed.py — 把「已验证的球事件轨迹」转成 ball_possession 的 --ball-json 喂入格式。

为什么需要它
------------
ball_possession.py 自带球检测走 YOLO COCO `sports ball`（召回~17–30%，对篮球置信偏低），
且默认 `--max-gap 15` 会**线性插值补洞** ⇒ 属 fabrication，与项目「平滑≠正确」「只消费真实检测」铁律冲突。
本脚本改用我们 A4.15/A4.16 已验证（7/7 PASS）的 Kalman 跟踪器输出：
  只取参与「≥3 帧持续轨迹」的**真实检测点**，不插值、不补预测帧。
喂入格式（ball_possession.py:210 读取处）
----------------------------------------
    ball_map.get(f.name) → [{bbox:[x1,y1,x2,y2], conf:prob}, ...]
键 = 帧文件名（f00001.jpg），与 scores/tracker 的键一致。

bbox 来源：轨迹只存 centers，故按「中心点」回查 scores 中对应候选的**原始 bbox**（非合成框），
保证中心精确且尺寸真实（ possession 判定用球心，尺寸仅用于一致性）。

用法
----
  python engine/make_ballfeed.py --clip sas_hou
  python engine/make_ballfeed.py --all
输出
----
  action_work/validate/<clip>_ballfeed.json
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import sys
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
sys.path.insert(0, str(ROOT / "engine"))

import court_render as cr  # 复用 load_scores / operating_th
import track_ball as tb


def build_feed(clip: str, min_track: int = 3):
    frames = cr.load_scores(clip)
    th = cr.operating_th(clip)
    tracks = tb.track_clip(frames, th, birth=th, gap=8)
    tracks = [t for t in tracks if len(t["frames"]) >= min_track]

    # 每帧：中心(两位小数) → 原始 bbox
    center2box = {}
    for fn, cands in frames.items():
        m = {}
        for c in cands:
            b = c["bbox"]
            cx = round((b[0] + b[2]) / 2, 1)
            cy = round((b[1] + b[3]) / 2, 1)
            m.setdefault((cx, cy), [float(v) for v in b])
        center2box[fn] = m

    feed = {}
    n_pts = 0
    for t in tracks:
        for f, c, p in zip(t["frames"], t["centers"], t["probs"]):
            fn = f"f{int(f):05d}.jpg"
            key = (round(float(c[0]), 1), round(float(c[1]), 1))
            box = center2box.get(fn, {}).get(key)
            if box is None:  # 兜底：合成小框（中心仍精确，尺寸不影响球心判定）
                box = [c[0] - 10, c[1] - 10, c[0] + 10, c[1] + 10]
            feed.setdefault(fn, []).append({"bbox": box, "conf": float(p)})
            n_pts += 1
    return feed, {"clip": clip, "th": th, "tracks": len(tracks), "points": n_pts,
                  "frames_with_ball": len(feed)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default=None)
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    clips = (["sas_hou", "sas_nop", "sas_det"] if a.all
             else ([a.clip] if a.clip else []))
    if not clips:
        ap.error("需要 --clip 或 --all")
    for c in clips:
        feed, meta = build_feed(c)
        out = AW / "validate" / f"{c}_ballfeed.json"
        out.write_text(json.dumps(feed, indent=1))
        print(f"{c}: th={meta['th']} 持续轨迹={meta['tracks']} 真实检测点={meta['points']} "
              f"覆盖帧={meta['frames_with_ball']} → {out.name}")


if __name__ == "__main__":
    main()
