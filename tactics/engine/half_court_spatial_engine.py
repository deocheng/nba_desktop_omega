#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""半场空间几何层：梯形透视标定 + 虚拟边线扩展 + 场外噪声过滤 + 脚底点→战术板投射。

来源：老程《半场端到端处理与词表映射规范》§一 + 第二轮补充（per-clip 标定/可视化/扩展量估算）。
代码内**零坐标常量** —— 全部外置到 action_work/court_calib/。

落地时对原稿的改动（每条都有实测依据，见 CONFLICTS）：

  C1  src_points 不硬编码。原稿 [420,320]/[860,320]/[1100,680]/[180,680] 是
      「下宽上窄半场视角」示意值；ep24_s1 是**边线视角**（远边线近水平、底线近竖直）。
  C2  新增 from_lines()：由 4 条场地直线求交生成梯形，天然支持
      「虚拟边线 = 平行于识别出的边线」这一既有铁律。
  C3  过滤层默认不单靠 pointPolygonTest。R4(2026-09-26) 实测推翻多边形裁剪：
      ① 颜色地板掩膜跨域不可用（TOR 木+紫 vs HOU 黑+红+木 仅 30.1% 覆盖）；
      ② 球员身体在地板色掩膜里是「洞」，单像素测中心必落洞里；
      ③ 纯身高无间隙（近端场边座位框高 216–241px，与远场球员同量级）。
      现行判据 = 球场平面透视一致性 h = A·y_foot + B（engine/player_plane_filter.py）。
      ⇒ 过滤做成依赖注入，engine 不内置判据。
  C4  🔴 **单应必须用未扩展的点**。原稿 `estimate_virtual_expansion` 后接
      `engine.src_points = expanded; engine._update_homography()` 会把扩展量
      算进单应 ⇒ 所有球员脚底在战术板上系统性外扩，距离/速度全失真。
      本实现：src_geom(未扩展) 算 H；poly_admit(扩展后) 只做准入。
  C5  🔴 修 `src_expanded = src_points_raw.copy()` 的**浅拷贝污染 bug**：
      若传入 python list，`.copy()` 是浅拷贝，`src_expanded[3][0] = ...` 会
      写回 src_points_raw。统一转 np.float32 后 copy。
  C6  扩展量 20/40/60 三档硬编码 → 外置为 EXPAND_LADDER 参数（可配、可证伪），
      并新增"按底宽占比线性插值"模式，避免阶梯跳变。
  C7  🔴 dst_points 默认 [[200,0],[800,0],[1000,940],[0,940]] 上底 600/下底 1000
      是**梯形而非矩形** ⇒ 目标空间非正交，同一战术板 y 在不同 x 处尺度不同，
      距离/速度计算会失真。保留该默认（兼容老程原稿视觉），但提供
      `rect_dst=True` 切成真正矩形，并在 selfcheck() 里报 dst 是否矩形。
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
CALIB_DIR = ROOT / "action_work" / "court_calib"
DEFAULT_CALIB = CALIB_DIR / "half_court_calib.json"

# C6：扩展量阶梯外置（可被 from_calib / 调用方覆盖）
EXPAND_LADDER = [(0.85, 20.0), (0.70, 40.0), (0.00, 60.0)]

CONFLICTS = {
    "C1_no_hardcoded_src_points": "外置标定文件",
    "C2_from_lines": "支持由 4 条直线求交，兼容边线视角",
    "C3_polygon_filter_refuted": "R4 实测推翻多边形裁剪；过滤层依赖注入",
    "C4_H_uses_unexpanded": "单应只用未扩展点，扩展多边形只做准入",
    "C5_shallow_copy_bug": "list.copy() 浅拷贝会污染原数组，已修",
    "C6_expand_ladder_param": "20/40/60 外置为 EXPAND_LADDER",
    "C7_dst_trapezoid_warn": "默认 dst 是梯形非矩形，距离/速度会失真；rect_dst=True 可切",
}


def _intersect(l1, l2):
    """两条直线求交。('h', a, b) => y=a*x+b ；('v', m, c) => x=m*y+c"""
    if l1[0] == l2[0]:
        return None
    h, v = (l1, l2) if l1[0] == "h" else (l2, l1)
    _, a, b = h
    _, m, c = v
    den = 1.0 - m * a
    if abs(den) < 1e-9:
        return None
    x = (m * b + c) / den
    return (x, a * x + b)


def estimate_virtual_expansion(src_points_raw, img_width=1280, img_height=720,
                               img_height_unused=None, target_cover_ratio=0.92,
                               max_expand_px=80.0, ladder=None, mode="ladder"):
    """虚拟边线左右扩展量估算（只扩展近端两角，远端不动）。

    改动 vs 原稿：
      · C5 强转 np.float32 再 copy，修浅拷贝污染；
      · C6 ladder 外置；新增 mode="linear" 按底宽占比线性插值，消除阶梯跳变；
      · 返回 (expanded, expand_px)，**不改单应**（调用方需自行决定，见 C4）。

    注意：原稿签名里的 img_height 与 target_cover_ratio 实际未被使用，
    保留形参仅为兼容调用方，实现按底宽占比驱动。
    """
    raw = np.asarray(src_points_raw, dtype=np.float32).reshape(4, 2).copy()
    tl, tr, br, bl = raw[0], raw[1], raw[2], raw[3]
    bottom_width = float(br[0] - bl[0])
    bottom_ratio = bottom_width / float(img_width)

    if mode == "linear":
        # 底越窄 → 被遮挡越重 → 扩得越多；占比 1.0→0，扩展 0→max_expand_px
        expand = float(np.clip((1.0 - bottom_ratio) / 0.30, 0.0, 1.0)) * max_expand_px
    else:
        ladder = ladder or EXPAND_LADDER
        expand = ladder[-1][1]
        for thr, val in ladder:
            if bottom_ratio >= thr:
                expand = val
                break

    expand = float(min(expand, max_expand_px))
    out = raw.copy()
    out[3][0] = max(0.0, float(bl[0]) - expand)                    # 左下往左
    out[2][0] = min(float(img_width) - 1, float(br[0]) + expand)   # 右下往右
    return out, expand


class HalfCourtSpatialEngine:
    def __init__(self, src_points=None, dst_points=None,
                 img_width=1280, img_height=720,
                 dst_width=1000, dst_height=940,
                 calib_path=None, expand_px=0.0, rect_dst=False,
                 player_filter=None, filter_mode="injected", meta=None):
        if rect_dst:  # C7：真正矩形，保证目标空间正交
            dst_points = np.array([[0, 0], [dst_width, 0],
                                   [dst_width, dst_height], [0, dst_height]],
                                  dtype=np.float32)
        if dst_points is None:
            dst_points = np.array([[200, 0], [800, 0],
                                   [dst_width, dst_height], [0, dst_height]],
                                  dtype=np.float32)
        self.img_width, self.img_height = img_width, img_height
        self.dst_width, self.dst_height = dst_width, dst_height
        self.dst_points = np.asarray(dst_points, dtype=np.float32).reshape(4, 2)
        self.src_points = None
        self.calib_path = calib_path
        self.meta = meta or {}
        self.player_filter = player_filter
        self.filter_mode = filter_mode

        if src_points is not None:
            self.set_geometry(np.asarray(src_points, dtype=np.float32).reshape(4, 2),
                              expand_px=expand_px)
        elif calib_path and Path(calib_path).exists():
            self.load_calibration(calib_path)
        else:
            raise ValueError("必须给 src_points 或有效的 calib_path（禁默认硬编码点，见 C1）")

    # ---------- 几何 ----------

    def set_geometry(self, src_points, expand_px=0.0):
        """src_points 是**未扩展**的真值梯形。H 只用未扩展点（C4）。"""
        src = np.asarray(src_points, dtype=np.float32).reshape(4, 2)
        self.src_points = src
        self.src_points_raw = src.copy()          # 供 visualize 对比
        self.expand_px = float(expand_px)
        self.poly_admit = src if expand_px <= 0 else estimate_virtual_expansion(
            src, self.img_width, self.img_height, max_expand_px=expand_px)[0]
        H, _ = cv2.findHomography(self.src_points, self.dst_points)
        if H is None:
            raise ValueError("findHomography 失败：src/dst 退化")
        self.H = H
        self.H_inv = np.linalg.inv(H)
        self.polygon_mask = self.src_points.astype(np.int32)   # 兼容原字段
        return self

    def _update_homography(self):
        """兼容原稿调用习惯。⚠️ 它用 self.src_points（未扩展）算 H，符合 C4。"""
        H, _ = cv2.findHomography(self.src_points, self.dst_points)
        self.H = H
        self.H_inv = np.linalg.inv(H)
        self.polygon_mask = self.src_points.astype(np.int32)
        return self

    # ---------- per-clip 标定 ----------

    def load_calibration(self, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.src_points = np.asarray(data["src_points"], dtype=np.float32).reshape(4, 2)
        if "dst_points" in data:
            self.dst_points = np.asarray(data["dst_points"], dtype=np.float32).reshape(4, 2)
        self.img_width = int(data.get("img_width", self.img_width))
        self.img_height = int(data.get("img_height", self.img_height))
        self.calib_path = str(path)
        self.meta = data.get("note", self.meta)
        self.src_points_raw = self.src_points.copy()
        self.poly_admit = self.src_points
        self.expand_px = 0.0
        self._update_homography()
        print(f"[HalfCourt] loaded calibration from {path}")
        return self

    def save_calibration(self, path):
        p = Path(path)
        if not p.parent.exists():
            p.parent.mkdir(parents=True)
        p.write_text(json.dumps({
            "src_points": self.src_points.tolist(),
            "dst_points": self.dst_points.tolist(),
            "img_width": self.img_width,
            "img_height": self.img_height,
            "note": self.meta if isinstance(self.meta, str) else
                    "half-court trapezoid; src_points are UNEXPANDED (H 只用未扩展点, C4)",
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[HalfCourt] saved calibration to {path}")

    # ---------- 构造入口 ----------

    @classmethod
    def from_points(cls, src_points, **kw):
        return cls(src_points=src_points, **kw)

    @classmethod
    def from_lines(cls, far, near, base, mid, **kw):
        """由 4 条场地直线求交。far/near=('h',a,b)；base/mid=('v',m,c)。"""
        pts = [_intersect(far, base), _intersect(near, base),
               _intersect(far, mid), _intersect(near, mid)]
        if any(p is None for p in pts):
            raise ValueError("4 条直线交点缺失（存在平行退化）")

        def order(pb, pm):
            a, b = np.asarray(pb), np.asarray(pm)
            return (a, b) if a[0] <= b[0] else (b, a)
        f_l, f_r = order(pts[0], pts[2])
        n_l, n_r = order(pts[1], pts[3])
        src = np.array([f_l, f_r, n_r, n_l], dtype=np.float32)
        return cls(src_points=src, **kw)

    def ready(self):
        """半场梯形是否已标定完备（供流水线在欠定时显式失败，不静默出数）。"""
        return self.src_points is not None and self.H is not None

    # ---------- 核心 ----------

    def _foot(self, det):
        if "foot_x" in det and "foot_y" in det:
            return float(det["foot_x"]), float(det["foot_y"])
        x1, y1, x2, y2 = det.get("box", det.get("bbox", [0, 0, 0, 0]))
        return float((x1 + x2) / 2), float(y2)

    def filter_and_project(self, detections, mark_all=False):
        """过滤场外噪声并投射。返回 (valid_players, stats)。

        mark_all=True 时返回全量（含 on_court=False），便于 visualize。
        """
        poly = np.asarray(self.poly_admit, dtype=np.int32)
        valid, marked, stats = [], [], {"n_in": 0, "n_polygon_drop": 0,
                                        "n_filter_drop": 0, "n_kept": 0}
        for det in detections:
            fx, fy = self._foot(det)
            out = dict(det)
            out["foot_x"], out["foot_y"] = fx, fy
            if cv2.pointPolygonTest(poly, (float(fx), float(fy)), False) < 0:
                stats["n_polygon_drop"] += 1
                out["on_court"] = False
                marked.append(out)
                continue
            stats["n_in"] += 1
            if self.player_filter is not None and not self.player_filter(out):
                stats["n_filter_drop"] += 1
                out["on_court"] = False
                marked.append(out)
                continue
            p = cv2.perspectiveTransform(
                np.array([[[fx, fy]]], dtype=np.float32), self.H)[0][0]
            out["tactical_x"], out["tactical_y"] = float(p[0]), float(p[1])
            out["on_court"] = True
            valid.append(out)
            marked.append(out)
        stats["n_kept"] = len(valid)
        return (marked, stats) if mark_all else (valid, stats)

    # ---------- 可视化 ----------

    def visualize(self, frame, detections=None, save_path=None, show_expanded=True):
        vis = frame.copy()
        cv2.polylines(vis, [np.asarray(self.poly_admit, dtype=np.int32)], True, (0, 255, 0), 2)
        if show_expanded and getattr(self, "expand_px", 0) > 0:
            cv2.polylines(vis, [self.src_points_raw.astype(np.int32)], True, (0, 255, 255), 1)
        for i, pt in enumerate(self.src_points):
            cv2.circle(vis, (int(pt[0]), int(pt[1])), 6, (0, 0, 255), -1)
            cv2.putText(vis, str(i), (int(pt[0]) + 8, int(pt[1]) - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        if detections:
            for d in detections:
                x, y = int(d["foot_x"]), int(d["foot_y"])
                col = (0, 255, 0) if d.get("on_court") else (0, 0, 255)
                cv2.circle(vis, (x, y), 5, col, -1)
        cv2.putText(vis, "Green=on-court  Red=filtered  Yellow=raw boundary",
                    (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        if save_path:
            sp = Path(save_path)
            if not sp.parent.exists():
                sp.parent.mkdir(parents=True)
            cv2.imwrite(str(sp), vis)
            print(f"[HalfCourt] debug image saved: {save_path}")
        return vis

    # ---------- 自证 ----------

    def selfcheck(self):
        back = cv2.perspectiveTransform(self.src_points.reshape(-1, 1, 2), self.H)
        err = float(np.linalg.norm(back.reshape(4, 2) - self.dst_points, axis=1).max())
        top_w = float(abs(self.src_points[1][0] - self.src_points[0][0]))
        bot_w = float(abs(self.src_points[2][0] - self.src_points[3][0]))
        d_top = float(abs(self.dst_points[1][0] - self.dst_points[0][0]))
        d_bot = float(abs(self.dst_points[2][0] - self.dst_points[3][0]))
        return {
            "reproj_err_px_max": round(err, 4),
            "H_cond": round(float(np.linalg.cond(self.H)), 3),
            "src_is_convex": bool(cv2.isContourConvex(self.src_points.astype(np.int32))),
            "src_area_px2": round(float(cv2.contourArea(self.src_points.astype(np.int32))), 1),
            "src_trapezoid_ratio_bot_over_top": round(bot_w / max(top_w, 1e-6), 3),
            "dst_is_rectangle": bool(abs(d_top - d_bot) < 1e-6),
            "expand_px": self.expand_px,
            "filter_mode": self.filter_mode,
            "conflicts": list(CONFLICTS),
        }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--calib", default=None)
    ap.add_argument("--demo-expansion", action="store_true")
    a = ap.parse_args()

    if a.demo_expansion:
        raw = [[420, 320], [860, 320], [1050, 680], [230, 680]]
        exp, px = estimate_virtual_expansion(raw, 1280, 720)
        print(f"自动扩展量: {px}px")
        print("  expanded:", exp.tolist())
        print("  raw 未被污染:", raw[3][0] == 230 and raw[2][0] == 1050, "(C5 修复验证)")
        e = HalfCourtSpatialEngine(src_points=raw, expand_px=px)
        print("  selfcheck:", e.selfcheck())
    elif a.calib:
        e = HalfCourtSpatialEngine(calib_path=a.calib)
        print("selfcheck:", e.selfcheck())
