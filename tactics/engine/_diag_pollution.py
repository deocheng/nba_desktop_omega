#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_diag_pollution.py — R4 污染实测（观众/替补/裁判框）。

动机
----
用户 item 4 要求「结合球场 footprint + 身高阈值 + 持球者信息，把观众/替补/裁判框清干净」。
但污染到底长什么样、占比多少、几何可分性如何——**没量过就不能写规则**（否则等于拍脑袋）。
本脚本只做**测量 + 目视**，不做过滤，不产出任何"干净"结论。

与已有工具的差异（重要）
------------------------
`geom_floor_poly.py` 的 `floor_mask` 是按 **TOR 主场**（木色 + 紫涂装）调的。本轮回测
`sas_hou`（HOU 主场）时掩膜 **残缺**（floor 占比仅 30.1%，左侧/左上球场大块缺失）——
⇒ **footprint 不可跨域直用**，必须先量它到底漏多少。本脚本把 `in_floor` 的漏检一并量出来。

测量项（逐框）
    h / w / ar / cx / cy / foot_y / conf / track_id
    rel_y   = cy / H                —— 越靠上越可能是看台
    rel_foot= foot_y / H
    rel_h   = h / H
    in_floor / foot_in_floor / above_top（来自 geom_floor_poly，若掩膜有效）
    n_frame_seen（该 track_id 在该片段出现帧数）—— 静态观众 track 数会异常高/异常低
    d_ball  （该帧球框矩形中心到本框矩形的距离，仅带球帧）

产出
    <out>/pollution_stats.json        逐 clip 聚合 + 逐框明细（供后续定阈值）
    <out>/pollution_overlay_<clip>.jpg 采样帧叠加（绿=全框，红=h<hmin 候选，青=foot）
    <out>/pollution_small_<clip>.jpg   最小 N 个框的裁剪拼图（目视确认是否观众）

用法
    python engine/_diag_pollution.py --stride 40
    python engine/_diag_pollution.py --clips sas_hou --stride 25
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
OUT = AW / "validate"
H, W = 1080, 1920


def _load_geom():
    """复用 geom_floor_poly（掩膜 + 外轮廓），失败则返回 None（不阻断测量）。"""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("gfp", str(ROOT / "engine" / "geom_floor_poly.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    except Exception as e:                                  # noqa: BLE001
        print(f"[warn] geom_floor_poly 不可用：{e}")
        return None


def load_players(clip, suffix="_poss_tile"):
    p = AW / f"{clip}{suffix}" / "ball_tracks.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def q(v, ps=(5, 25, 50, 75, 95)):
    a = np.asarray([x for x in v if x is not None], float)
    if a.size == 0:
        return {}
    return {f"p{k}": round(float(np.percentile(a, k)), 1) for k in ps}


def diag_clip(clip, stride=40, suffix="_poss_tile", use_geom=True, small_k=24):
    recs = load_players(clip, suffix)
    if recs is None:
        print(f"[skip] {clip}: 无 {clip}{suffix}/ball_tracks.json")
        return None
    gfp = _load_geom() if use_geom else None

    # track_id 出现帧数（全片，不只采样帧）
    seen = {}
    for r in recs:
        for pl in r.get("players", []):
            seen[pl["track_id"]] = seen.get(pl["track_id"], 0) + 1

    order = sorted(range(len(recs)), key=lambda i: str(recs[i].get("file", "")))
    idxs = order[::stride]
    if idxs[-1] != order[-1]:
        idxs.append(order[-1])

    rows, samples = [], []
    for i in idxs:
        r = recs[i]
        fn = str(r.get("file", ""))
        img = cv2.imread(str(AW / clip / fn))
        if img is None:
            continue
        if img.shape[1] != W:
            sc = W / img.shape[1]
            img = cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA)
        else:
            sc = 1.0
        mask = None
        if gfp is not None:
            try:
                m25, s25 = gfp.floor_mask(img)
                mask = cv2.resize(m25, (W, H), interpolation=cv2.INTER_NEAREST)
            except Exception:                                # noqa: BLE001
                mask = None
        ball = r.get("ball")
        bb = None
        if ball and ball.get("bbox"):
            b = ball["bbox"]
            bb = [v * sc for v in b]
        fr = []
        for pl in r.get("players", []):
            x1, y1, x2, y2 = [v * sc for v in pl["bbox"]]
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            d = {
                "file": fn, "track_id": pl["track_id"], "conf": round(float(pl.get("conf", 0)), 4),
                "x1": round(x1, 1), "y1": round(y1, 1), "x2": round(x2, 1), "y2": round(y2, 1),
                "h": round(y2 - y1, 1), "w": round(x2 - x1, 1),
                "cx": round(cx, 1), "cy": round(cy, 1), "foot_y": round(y2, 1),
                "rel_y": round(cy / H, 4), "rel_foot": round(y2 / H, 4), "rel_h": round((y2 - y1) / H, 4),
                "n_seen": seen.get(pl["track_id"], 0),
            }
            if mask is not None and gfp is not None:
                f = gfp.feats_for(mask, [x1, y1, x2, y2])
                d.update({"in_floor": f["in_floor"], "foot_in_floor": f["foot_in_floor"],
                          "above_top": round(f["above_top"], 1)})
            if bb is not None:
                dx = max(x1 - bb[2], bb[0] - x2, 0.0)
                dy = max(y1 - bb[3], bb[1] - y2, 0.0)
                d["d_ball"] = round((dx * dx + dy * dy) ** 0.5, 1)
            fr.append(d)
        rows += fr
        samples.append((fn, img, fr, mask, bb))

    if not rows:
        return None

    out = {
        "clip": clip, "n_frames_total": len(recs), "n_sampled": len(samples),
        "stride": stride, "n_boxes": len(rows),
        "n_tracks": len(seen),
        "box_per_frame": round(len(rows) / max(1, len(samples)), 2),
        "h": q([r["h"] for r in rows]),
        "rel_y": q([r["rel_y"] for r in rows]),
        "rel_h": q([r["rel_h"] for r in rows]),
        "conf": q([r["conf"] for r in rows]),
        "frac": {},
    }
    for th in (40, 60, 80, 100, 120):
        out["frac"][f"h<{th}"] = round(float(np.mean([r["h"] < th for r in rows])), 4)
    for th in (0.25, 0.30, 0.35, 0.40):
        out["frac"][f"rel_y<{th}"] = round(float(np.mean([r["rel_y"] < th for r in rows])), 4)
    if "in_floor" in rows[0]:
        out["frac"]["in_floor=0"] = round(float(np.mean([r["in_floor"] == 0 for r in rows])), 4)
        out["frac"]["foot_in_floor=0"] = round(float(np.mean([r["foot_in_floor"] == 0 for r in rows])), 4)
        out["frac"]["above_top>0"] = round(float(np.mean([r["above_top"] > 0 for r in rows])), 4)
        out["frac"]["mask_cov"] = round(float(np.mean([r["in_floor"] for r in rows])), 4)
    out["rows"] = rows

    print(f"\n=== {clip}（{len(recs)} 帧 / 采样 {len(samples)} / {len(rows)} 框 / {len(seen)} tracks）===")
    print(f"  框/帧={out['box_per_frame']}  h: {out['h']}")
    print(f"  rel_y: {out['rel_y']}")
    print(f"  conf: {out['conf']}")
    fr_s = "  ".join(f"{k}={v}" for k, v in out["frac"].items())
    print(f"  占比: {fr_s}")

    # ── 目视 ①：采样帧叠加 ────────────────────────────────────────────
    hmin = 80
    tiles = []
    for fn, img, fr, mask, bb in samples[:3]:
        ov = img.copy()
        if mask is not None:
            ov[mask > 0] = (ov[mask > 0] * 0.75 + np.array([40, 120, 40]) * 0.25).astype(np.uint8)
        for d in fr:
            small = d["h"] < hmin
            col = (0, 0, 255) if small else (0, 255, 0)
            cv2.rectangle(ov, (int(d["x1"]), int(d["y1"])), (int(d["x2"]), int(d["y2"])), col, 2)
            cv2.circle(ov, (int(d["cx"]), int(d["foot_y"])), 4, (255, 255, 0), -1)
            cv2.putText(ov, f"{d['track_id']}:{int(d['h'])}", (int(d["x1"]), int(d["y1"]) - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 2)
        if bb is not None:
            cv2.rectangle(ov, (int(bb[0]), int(bb[1])), (int(bb[2]), int(bb[3])), (0, 165, 255), 2)
        cv2.putText(ov, f"{clip} {fn} hmin={hmin} 红=h<{hmin}", (14, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
        tiles.append(cv2.resize(ov, (760, 428), interpolation=cv2.INTER_AREA))
    if tiles:
        while len(tiles) % 2:
            tiles.append(np.zeros_like(tiles[0]))
        grid = np.vstack([np.hstack(tiles[i:i + 2]) for i in range(0, len(tiles), 2)])
        o = OUT / f"pollution_overlay_{clip}.jpg"
        cv2.imwrite(str(o), grid, [cv2.IMWRITE_JPEG_QUALITY, 90])
        print(f"  [out] {o}")

    # ── 目视 ②：最小 N 框裁剪拼图（含横坐标 → 判断是否看台） ──────────────
    small = sorted(rows, key=lambda r: r["h"])[:small_k]
    CROP = 150
    cells = []
    for d in small:
        img = cv2.imread(str(AW / clip / d["file"]))
        if img is None:
            continue
        if img.shape[1] != W:
            img = cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA)
        cx, cy = int(d["cx"]), int(d["cy"])
        x1, y1 = max(0, cx - CROP), max(0, cy - CROP)
        x2, y2 = min(W, cx + CROP), min(H, cy + CROP)
        c = img[y1:y2, x1:x2].copy()
        c = cv2.resize(c, (CROP, CROP))
        b = [int(d["x1"]) - x1, int(d["y1"]) - y1, int(d["x2"]) - x1, int(d["y2"]) - y1]
        b = [v * CROP / (x2 - x1) for v in b]
        cv2.rectangle(c, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (0, 255, 0), 2)
        cv2.putText(c, f"{d['file'][1:6]} t{d['track_id']}", (4, 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1)
        cv2.putText(c, f"h={int(d['h'])} y={int(d['cy'])}", (4, 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1)
        cells.append(c)
    if cells:
        while len(cells) % 6:
            cells.append(np.zeros_like(cells[0]))
        g = np.vstack([np.hstack(cells[i:i + 6]) for i in range(0, len(cells), 6)])
        o = OUT / f"pollution_small_{clip}.jpg"
        cv2.imwrite(str(o), g, [cv2.IMWRITE_JPEG_QUALITY, 90])
        print(f"  [out] {o}  （最小 {len(small)} 框，按 h 升序）")

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", default="w1,sas_hou,sas_nop,sas_det")
    ap.add_argument("--suffix", default="_poss_tile")
    ap.add_argument("--stride", type=int, default=40)
    ap.add_argument("--no-geom", action="store_true")
    a = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    allout = {}
    for c in a.clips.split(","):
        c = c.strip()
        if not c:
            continue
        r = diag_clip(c, a.stride, a.suffix, not a.no_geom)
        if r:
            allout[c] = r
    p = OUT / "pollution_stats.json"
    p.write_text(json.dumps(allout, ensure_ascii=False, indent=1))
    print(f"\n[out] {p}")

    print("\n" + "=" * 74)
    print(f"{'clip':10s} {'框/帧':>6s} {'h p5':>6s} {'h p50':>6s} {'h p95':>6s} "
          f"{'h<80':>6s} {'rel_y<.30':>9s} {'mask漏':>7s}")
    for c, r in allout.items():
        f = r["frac"]
        mc = f.get("in_floor=0")
        print(f"{c:10s} {r['box_per_frame']:6.2f} {r['h'].get('p5',0):6.0f} {r['h'].get('p50',0):6.0f} "
              f"{r['h'].get('p95',0):6.0f} {f['h<80']:6.3f} "
              f"{f['rel_y<0.3']:9.3f} {('n/a' if mc is None else f'{mc:.3f}'):>7s}")


if __name__ == "__main__":
    main()
