#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""geom_floor_region.py — 球场区域（填洞多边形）+ 四边越界量。

为什么要新写一个（不改 geom_floor_poly）
----------------------------------------
`geom_floor_poly.floor_mask()` 返回的是「地板**颜色**像素的最大连通域」。它有两个
结构性缺陷，导致它的包含判定不可用：

  ① **洞**：球员身体、球衣、球、影子在地板颜色掩膜里天然就是洞。原实现用
     `mask[cy, cx] > 0` 单像素测球员框中心 ⇒ 中心恰好落在球员自己的洞里 ⇒
     判成"不在场内"。实测覆盖率只有 0.24–0.44，而场内球员应接近 1.0。
  ② **单点无容差**：0.25 尺度掩膜 resize 回全分辨率后，边界量化误差 4px，
     足部点贴着边线时抖动极大。

本模块把外轮廓**填洞**成实心多边形（+ 少量膨胀做容差），包含判定用 `pointPolygonTest`
（精确），并额外给出**四条边的越界量**（上/下/左/右），因为看台在两处：
  - 远端看台：在图上方（框中心在球场上边线之上）；
  - **近端场边座**：在图下方（足点在球场下边线之下）——只测"上边线"会漏掉这一半。

⚠️ 掩膜参数（木色/紫涂装）源自 TOR 主场。跨域回测见 `_diag_pollution.py`：
   `sas_hou` 掩膜残缺（floor 占比 30.1%）。因此本模块**自带可靠性闸门**：
   `area_frac < 0.15` 或外轮廓触到画面边缘超过阈值 ⇒ `reliable=False`，
   下游必须**放弃该帧的 footprint 过滤**（宁漏不误杀），不得硬用。

用法（作为库）
    import geom_floor_region as gfr
    reg = gfr.build(img)                       # -> Region
    reg.contains(cx, cy) / reg.foot_out(fx, fy)
    f = gfr.feats(reg, [x1,y1,x2,y2])

命令行自检
    python engine/geom_floor_region.py --clip sas_hou --stride 40
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
W, H = 1920, 1080

MIN_AREA_FRAC = 0.15      # 掩膜面积低于此比例 ⇒ 该帧不可靠
PAD_PX = 6                # 多边形向外的容差（全分辨率像素）


def _load_base():
    spec = importlib.util.spec_from_file_location(
        "gfp", str(ROOT / "engine" / "geom_floor_poly.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_BASE = None


class Region:
    """一帧的球场区域。"""

    __slots__ = ("ok", "reason", "area_frac", "poly", "filled", "top_at", "bot_at", "contour")

    def __init__(self, ok, reason="", area_frac=0.0):
        self.ok = ok
        self.reason = reason
        self.area_frac = area_frac
        self.poly = None
        self.filled = None
        self.top_at = None
        self.bot_at = None
        self.contour = None

    def contains(self, x, y):
        """点是否在填洞后的球场多边形内（含 PAD 容差）。"""
        if not self.ok:
            return None
        Hh, Ww = self.filled.shape
        if not (0 <= x < Ww and 0 <= y < Hh):
            return False
        return bool(self.filled[int(y), int(x)] > 0)

    def feats(self, box):
        x1, y1, x2, y2 = box
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        fx, fy = cx, y2
        out = {"in_floor": -1, "foot_in_floor": -1, "above_top": None,
               "below_bot": None, "out_left": None, "out_right": None,
               "top_row": None, "bot_row": None, "region_ok": 0}
        if not self.ok:
            return out
        out["region_ok"] = 1
        out["in_floor"] = 1 if self.contains(cx, cy) else 0
        out["foot_in_floor"] = 1 if self.contains(fx, fy) else 0
        xi, fi = int(round(cx)), int(round(fx))
        xi = min(max(xi, 0), W - 1)
        fi = min(max(fi, 0), W - 1)
        t, b = self.top_at[xi], self.bot_at[xi]
        if t is not None:
            out["top_row"] = int(t)
            out["above_top"] = float(t - cy)          # >0 ⇒ 中心在球场上边线之上
        tf, bf = self.top_at[fi], self.bot_at[fi]
        if bf is not None:
            out["bot_row"] = int(bf)
            out["below_bot"] = float(fy - bf)         # >0 ⇒ 足点在球场下边线之下
        # 左右：用整帧球场轮廓的水平范围
        xs = self.contour[:, 0]
        out["out_left"] = float(xs.min() - x1)
        out["out_right"] = float(x2 - xs.max())
        return out


def build(img, min_area_frac=MIN_AREA_FRAC, pad=PAD_PX):
    """img: BGR 全分辨率帧 → Region"""
    global _BASE
    if _BASE is None:
        _BASE = _load_base()
    r = Region(False, "no_mask", 0.0)
    try:
        m25, sc = _BASE.floor_mask(img)
    except Exception as e:                                     # noqa: BLE001
        r.reason = f"mask_err:{e}"
        return r
    if m25 is None or (m25 > 0).mean() < 0.05:
        r.reason = "mask_empty"
        return r

    cs, _ = cv2.findContours(m25, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        r.reason = "no_contour"
        return r
    c = max(cs, key=cv2.contourArea)
    if cv2.contourArea(c) < 0.05 * m25.shape[0] * m25.shape[1]:
        r.reason = "contour_small"
        return r

    # 填洞：外轮廓实心化（在 25% 尺度上做，再放大；PAD 在全分辨率上加）
    fill25 = np.zeros_like(m25)
    cv2.drawContours(fill25, [c], -1, 255, -1)
    area_frac = float((fill25 > 0).mean())
    r.area_frac = round(area_frac, 4)
    if area_frac < min_area_frac:
        r.reason = f"area_low({area_frac:.3f})"
        return r

    filled = cv2.resize(fill25, (W, H), interpolation=cv2.INTER_NEAREST)
    if pad:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (pad * 2 + 1, pad * 2 + 1))
        filled = cv2.dilate(filled, k)

    poly = c.reshape(-1, 2).astype(np.float64) * (1.0 / 0.25)
    poly[:, 0] = np.clip(poly[:, 0], 0, W - 1)
    poly[:, 1] = np.clip(poly[:, 1], 0, H - 1)

    nz = filled > 0
    top_at = [None] * W
    bot_at = [None] * W
    cols = np.where(nz.any(0))[0]
    if cols.size:
        sub = nz[:, cols]
        tops = np.argmax(sub, axis=0)
        bots = H - 1 - np.argmax(sub[::-1, :], axis=0)
        for i, x in enumerate(cols):
            top_at[int(x)] = int(tops[i])
            bot_at[int(x)] = int(bots[i])

    r.ok = True
    r.reason = "ok"
    r.poly = poly
    r.filled = filled
    r.top_at = top_at
    r.bot_at = bot_at
    r.contour = poly.astype(np.int32)
    return r


def render(img, reg, box=None, out=None):
    """把区域可视化（供目视自证）。"""
    ov = img.copy()
    if reg.ok:
        ov[reg.filled > 0] = (ov[reg.filled > 0] * 0.7
                              + np.array([40, 130, 40]) * 0.3).astype(np.uint8)
        cv2.polylines(ov, [reg.contour.reshape(-1, 1, 2)], True, (0, 255, 255), 2)
        for x in range(0, W, W // 8):
            t, b = reg.top_at[x], reg.bot_at[x]
            if t is not None:
                cv2.circle(ov, (x, t), 5, (255, 0, 255), -1)
                cv2.circle(ov, (x, b), 5, (0, 165, 255), -1)
    if box is not None:
        x1, y1, x2, y2 = [int(v) for v in box]
        fx, fy = (x1 + x2) // 2, y2
        ins = reg.contains(fx, fy)
        col = (0, 255, 0) if ins else (0, 0, 255)
        cv2.rectangle(ov, (x1, y1), (x2, y2), col, 3)
        cv2.circle(ov, (fx, fy), 7, col, -1)
        cv2.putText(ov, f"foot_in={ins}", (x1, max(20, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, col, 2)
    txt = f"floor={reg.area_frac * 100:.1f}%  ok={reg.ok}  {reg.reason}"
    cv2.putText(ov, txt, (20, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
    if out:
        cv2.imwrite(str(out), ov, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return ov


def selftest(clip, stride=40, suffix="_poss_tile"):
    """逐帧建区域 + 对每个球员框算特征，给出覆盖率与可靠性统计。"""
    recs = json.loads((AW / f"{clip}{suffix}" / "ball_tracks.json").read_text())
    order = sorted(range(len(recs)), key=lambda i: str(recs[i].get("file", "")))
    idxs = order[::stride]
    if idxs[-1] != order[-1]:
        idxs.append(order[-1])
    n_ok = n_tot = 0
    rows = []
    for i in idxs:
        r = recs[i]
        img = cv2.imread(str(AW / clip / str(r["file"])))
        if img is None:
            continue
        reg = build(img)
        n_tot += 1
        n_ok += int(reg.ok)
        for pl in r.get("players", []):
            f = reg.feats(pl["bbox"])
            f.update({"file": r["file"], "track_id": pl["track_id"],
                      "h": round(pl["bbox"][3] - pl["bbox"][1], 1)})
            rows.append(f)
    ok_rows = [r for r in rows if r["region_ok"]]

    def _m(pred):
        v = [bool(pred(r)) for r in ok_rows if pred(r) is not None]
        return float(np.mean(v)) if v else float("nan")

    line = "  ".join(f"{k}={v:.3f}" for k, v in {
        "in_floor=1": _m(lambda r: r["in_floor"] == 1),
        "foot_in=1": _m(lambda r: r["foot_in_floor"] == 1),
        "above_top>0": _m(lambda r: (r["above_top"] > 0) if r["above_top"] is not None else None),
        "below_bot>0": _m(lambda r: (r["below_bot"] > 0) if r["below_bot"] is not None else None),
    }.items())
    print(f"[{clip}] 帧可靠 {n_ok}/{n_tot}  框 {len(ok_rows)}/{len(rows)}  {line}")
    return {"clip": clip, "frames_ok": n_ok, "frames_total": n_tot, "rows": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default="sas_hou")
    ap.add_argument("--stride", type=int, default=40)
    ap.add_argument("--suffix", default="_poss_tile")
    ap.add_argument("--render", action="store_true")
    a = ap.parse_args()
    res = selftest(a.clip, a.stride, a.suffix)
    if a.render:
        OUT = AW / "validate"
        OUT.mkdir(parents=True, exist_ok=True)
        recs = json.loads((AW / f"{a.clip}{a.suffix}" / "ball_tracks.json").read_text())
        for i in (0, len(recs) // 3, 2 * len(recs) // 3):
            r = recs[i]
            img = cv2.imread(str(AW / a.clip / str(r["file"])))
            if img is None:
                continue
            reg = build(img)
            render(img, reg, None, OUT / f"floorreg_{a.clip}_{Path(str(r['file'])).stem}.jpg")
        print(f"[out] {OUT}/floorreg_{a.clip}_*.jpg")


if __name__ == "__main__":
    main()
