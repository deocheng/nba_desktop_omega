#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""player_pollution_filter.py — R4 污染过滤（观众席/替补席/教练/裁判框）。

规则哲学（为什么是保守的）
--------------------------
误删（丢掉场内球员）代价 **高**：直接毁掉战术分析；
误留（留下一个观众）代价 **中**：关系图多几条边，且实测 H1（holding→BALL）仍 100% 命中。
⇒ 规则一律「只在有把握时才删」，并**强制保护持球者**。

四层规则（每层可单独关）
------------------------
A1 微框     `h < hmin`（域标定）。依据：各域「最小 24 框」的裁剪目视复核——
           w1 最小 24 框 h∈[35,64] 全为看台观众；sas_hou 最小 24 框 h∈[81,148] 全为
           观众/替补（第 25 小的 h=161 才是场内球员）⇒ 阈值取在"观众天花板"之下留余量。
A2 深看台   `above_top > margin_px`：框中心显著高于球场区域上边线（大余量，避免掩膜残缺
           造成的误删）。只在 `region_ok` 帧生效。
A3 静+远球  该 track 整段位移 `span < span_max` **且** 全程与球框距离 `> dball_min`
           ⇒ 既没动过、也从不出现在球附近 ⇒ 看台/替补席静坐者。
A4 持球者保护 任一帧为持球者（poss_track_id）或与球框距离 ≤ poss_radius 的框**永不剔除**。

与颜色无关的第二信号
--------------------
`tex_below`：足点正下方一块窄横条内的高频能量（Sobel 幅度均值）。物理含义：
在场球员足下是**平滑大面积**地板（木/涂装/黑漆）；观众/替补足下是**座椅/台阶/别人身体**
（高频）。该量不依赖"木色 vs 黑漆"的颜色假设，故跨域可用。**只作为证据与辅助，不单独删框。**

用法
    python engine/player_pollution_filter.py --clip w1 --dump-feats
    python engine/player_pollution_filter.py --all-clips
    python engine/player_pollution_filter.py --clip w1 --sheets     # 渲染剔除物目视验收图
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW = ROOT / "action_work"
OUT = AW / "validate"
DIAG = (1920.0 ** 2 + 1080.0 ** 2) ** 0.5
POSS_RADIUS = round(0.04 * DIAG, 1)          # 88.1px，与 ball_possession 同源

# 域标定（依据见 docstring A1；"观众天花板"实测值 → 取余量）
HMIN = {"w1": 70.0, "w2": 70.0, "w3": 70.0, "w4": 70.0,
        "sas_hou": 120.0, "sas_nop": 120.0, "sas_det": 120.0}
HMIN_DEFAULT = 80.0

SPAN_MAX = 26.0        # 整段位移阈值（px）：看台静坐者仅检测抖动
DBALL_MIN = 380.0      # 全程离球阈值（px）：静坐者从不出现在球附近
ABOVE_MARGIN = 0.10    # above_top > 0.10*H = 108px 才算"深看台"


# ── 载入 ────────────────────────────────────────────────────────────────
def _load_region():
    spec = importlib.util.spec_from_file_location(
        "gfr", str(ROOT / "engine" / "geom_floor_region.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def load_recs(clip, suffix="_poss_tile"):
    p = AW / f"{clip}{suffix}" / "ball_tracks.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def rect_dist(a, b):
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return (dx * dx + dy * dy) ** 0.5


def tex_below(gray, cx, fy, w, band=26, frac=0.6):
    """足点下方横条的 Sobel 幅度均值（0-255）。0 表示采样越界。"""
    h, Wd = gray.shape
    bw = max(6, int(w * frac / 2))
    y0, y1 = int(fy + 4), int(fy + 4 + band)
    x0, x1 = int(cx - bw), int(cx + bw)
    y0, y1 = max(0, y0), min(h, y1)
    x0, x1 = max(0, x0), min(Wd, x1)
    if y1 - y0 < 6 or x1 - x0 < 6:
        return None
    p = gray[y0:y1, x0:x1].astype(np.float32)
    gx = cv2.Sobel(p, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(p, cv2.CV_32F, 0, 1, ksize=3)
    return float(np.mean(np.sqrt(gx * gx + gy * gy)))


# ── 特征与规则 ──────────────────────────────────────────────────────────
def analyze(clip, suffix="_poss_tile", hmin=None, span_max=SPAN_MAX,
            dball_min=DBALL_MIN, above_margin=ABOVE_MARGIN,
            use_footprint=True, use_static=True, use_hmin=True, geom=None):
    recs = load_recs(clip, suffix)
    if recs is None:
        raise SystemExit(f"[缺数据] {clip}{suffix}/ball_tracks.json 不存在")
    gfr = _load_region() if (use_footprint and geom is None) else geom
    hmin = HMIN.get(clip, HMIN_DEFAULT) if hmin is None else hmin

    # 逐 track 聚合
    tracks = {}
    for r in recs:
        ball = r.get("ball")
        bb = ball.get("bbox") if ball else None
        for pl in r.get("players", []):
            t = tracks.setdefault(pl["track_id"], {
                "track_id": pl["track_id"], "frames": [], "centers": [], "hs": [],
                "dball": [], "poss": False})
            x1, y1, x2, y2 = pl["bbox"]
            t["frames"].append(str(r["file"]))
            t["centers"].append(((x1 + x2) / 2, (y1 + y2) / 2))
            t["hs"].append(y2 - y1)
            if bb:
                t["dball"].append(rect_dist(pl["bbox"], bb))
            if r.get("poss_track_id") is not None and r["poss_track_id"] == pl["track_id"]:
                t["poss"] = True

    for t in tracks.values():
        c = np.asarray(t["centers"], float)
        if len(c) > 1:
            t["span"] = float(np.max(np.linalg.norm(c - c.mean(0), axis=1)) * 2)
        else:
            t["span"] = 0.0
        t["h_med"] = float(np.median(t["hs"]))
        t["h_max"] = float(np.max(t["hs"]))
        t["life"] = len(t["frames"])
        t["d_ball_min"] = float(np.min(t["dball"])) if t["dball"] else None

    # 逐帧判定
    rows = []
    for r in recs:
        fn = str(r["file"])
        img = cv2.imread(str(AW / clip / fn))
        if img is None:
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        reg = gfr.build(img) if gfr is not None else None
        ball = r.get("ball")
        bb = ball.get("bbox") if ball else None
        poss = r.get("poss_track_id")
        for pl in r.get("players", []):
            x1, y1, x2, y2 = pl["bbox"]
            h = y2 - y1
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            t = tracks[pl["track_id"]]
            d = {"file": fn, "track_id": pl["track_id"], "h": round(h, 1),
                 "cx": round(cx, 1), "cy": round(cy, 1), "bbox": [round(v, 1) for v in pl["bbox"]],
                 "conf": round(float(pl.get("conf", 0)), 4),
                 "span": round(t["span"], 1), "life": t["life"],
                 "d_ball_min": None if t["d_ball_min"] is None else round(t["d_ball_min"], 1),
                 "d_ball": None if bb is None else round(rect_dist(pl["bbox"], bb), 1),
                 "is_poss": bool(poss is not None and poss == pl["track_id"]),
                 "tex_below": None if (tb := tex_below(gray, cx, y2, x2 - x1)) is None else round(tb, 2),
                 }
            if reg is not None:
                f = reg.feats([x1, y1, x2, y2])
                d.update({"region_ok": f["region_ok"], "above_top": f["above_top"],
                          "below_bot": f["below_bot"], "in_floor": f["in_floor"],
                          "foot_in_floor": f["foot_in_floor"]})
            # ── 规则 ──
            keep, why = True, "keep"
            if d["is_poss"]:
                keep, why = True, "protect_poss"
            elif d["d_ball"] is not None and d["d_ball"] <= POSS_RADIUS:
                keep, why = True, "protect_near_ball"
            elif use_hmin and h < hmin:
                keep, why = False, f"A1_micro(h<{hmin:g})"
            elif (use_footprint and d.get("region_ok") == 1 and d.get("above_top") is not None
                  and d["above_top"] > above_margin * 1080):
                keep, why = False, "A2_deep_stand"
            elif (use_static and t["span"] < span_max
                  and (t["d_ball_min"] is None or t["d_ball_min"] > dball_min)):
                keep, why = False, "A3_static_far"
            d["keep"] = keep
            d["reason"] = why
            rows.append(d)
    return {"clip": clip, "n_frames": len(recs), "hmin": hmin,
            "n_boxes": len(rows), "n_kept": sum(r["keep"] for r in rows),
            "n_tracks": len(tracks), "rows": rows,
            "tracks": {k: {kk: vv for kk, vv in v.items() if kk not in ("frames", "centers")}
                       for k, v in tracks.items()}}


def summarize(res):
    c = res["clip"]
    nb, nk = res["n_boxes"], res["n_kept"]
    reasons = {}
    for r in res["rows"]:
        if not r["keep"]:
            reasons[r["reason"].split("(")[0]] = reasons.get(r["reason"].split("(")[0], 0) + 1
    nf = res["n_frames"]
    print(f"[{c}] 框 {nb} → {nk}（剔除 {nb - nk}，{100 * (nb - nk) / max(1, nb):.1f}%）"
          f"  每帧 {nb / nf:.2f} → {nk / nf:.2f}   帧={nf} tracks={res['n_tracks']}")
    print(f"     规则分布: {reasons}")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default=None)
    ap.add_argument("--all-clips", action="store_true")
    ap.add_argument("--suffix", default="_poss_tile")
    ap.add_argument("--hmin", type=float, default=None)
    ap.add_argument("--span-max", type=float, default=SPAN_MAX)
    ap.add_argument("--dball-min", type=float, default=DBALL_MIN)
    ap.add_argument("--no-footprint", action="store_true")
    ap.add_argument("--no-static", action="store_true")
    ap.add_argument("--dump", default=None, help="落盘特征+判定 JSON 路径")
    a = ap.parse_args()

    clips = ["w1", "w2", "w3", "w4", "sas_hou", "sas_nop", "sas_det"] if a.all_clips \
        else [a.clip or "w1"]
    allres = {}
    for c in clips:
        r = analyze(c, a.suffix, a.hmin, a.span_max, a.dball_min,
                    use_footprint=not a.no_footprint, use_static=not a.no_static)
        summarize(r)
        allres[c] = r
    p = Path(a.dump) if a.dump else OUT / "player_pollution.json"
    p.write_text(json.dumps(allres, ensure_ascii=False))
    print(f"\n[out] {p}")


if __name__ == "__main__":
    main()
