#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全程相机对齐（「整体性」工作）：逐帧全局单应 → 轨迹累积 → 稳定化时间中值。

为什么必须做整体（而不是逐帧）
------------------------------
镜头变换（平移/俯仰/变焦）是**全局刚体变换**，场地形状的变化完全由它解释。
逐帧独立求掩膜/包络，等价于每帧重新猜一次同一个东西，既不稳也浪费。
正确做法：
  ① 用**背景静态特征**逐帧解全局单应 H(i→i+1)（RANSAC 自动剔除走动的球员）；
  ② 链式累积得 H(0→i)，把整段视频对齐到**统一的规范坐标系**；
  ③ 在规范坐标系里取**时间中值** —— 移动的人/球被中值抹掉，只剩静止的场地、
     场地线、看台 ⇒ 得到一张干净的「场地底板」（clean plate），线检测质量跃升；
  ④ 同时输出**逐像素观测支撑率**（有多少帧真的覆盖到该像素），< 阈值不采信。

用法:
  python engine/global_align.py --window w1 --track
  python engine/global_align.py --window w1 --median
  python engine/global_align.py --window w1 --check --frames 0 120 260 400
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
MS = Path(str(tactics_data_file("reports/milestone_05/measure")))
SC = 0.5          # 特征/匹配在 0.5 尺度上做
RANSAC_PX = 3.0   # 全分辨率像素
MIN_INLIER = 60

# 🔴🔴 静态叠加图形（广播台比分板/台标）—— 【必须在特征检测之前涂黑】
# 实证：不遮罩时，匹配两个**完全不同的镜头**也能拿到 373 内点"成功"，
# 内点全部落在比分板条带 x∈[94,538], y∈[906,986]（仅 16px 高）。
# 内点近共线 ⇒ 单应数值病态 ⇒ **尺度可以是任意值** ⇒ 链式累积漂到 1.55→0.55 的真根因。
OVERLAY_BOXES = [(60, 880, 580, 1020)]
# 内点包围盒必须铺开（占画幅比），否则判**失败**（退化门禁）。
MIN_SPREAD = (0.25, 0.20)


def frame_paths(win):
    return sorted((AW / win).glob("f*.jpg"))


def to_gray_small(p):
    img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
    for x0, y0, x1, y1 in OVERLAY_BOXES:
        img[y0:y1, x0:x1] = 0          # 【检测前】涂黑静态叠加图形
    return cv2.resize(img, None, fx=SC, fy=SC, interpolation=cv2.INTER_AREA), img.shape


def detect(gray, n=4000):
    orb = cv2.ORB_create(nfeatures=n, scaleFactor=1.2, nlevels=8,
                         fastThreshold=12, edgeThreshold=19)
    return orb.detectAndCompute(gray, None)


def euclid_ize(H):
    """把 2x2 块正交化为**纯旋转**（尺度强制 1）—— 物理先验：一帧（0.1s）内不可能变焦。

    为什么必须做（实测）：逐对单应的尺度估计有**系统性偏小**（Δlog s 中位 = −0.000551/帧），
    432 次复合后尺度漂到 0.637（−21%）。而"一帧内变焦 0.05%"物理上不成立 ⇒ 那是估计偏差。
    把尺度自由度直接**去掉**，链条在构造上就不可能发生尺度漂移。
    """
    A = H[:2, :2].copy()
    s = np.sqrt(abs(np.linalg.det(A)))
    if s < 1e-9:
        return H
    R = A / s
    try:
        U, _, Vt = np.linalg.svd(R)
        R = U @ Vt
    except np.linalg.LinAlgError:
        return H
    if np.linalg.det(R) < 0:
        U[:, -1] *= -1
        R = U @ Vt
    return np.array([[R[0, 0], R[0, 1], H[0, 2]],
                     [R[1, 0], R[1, 1], H[1, 2]],
                     [0.0, 0.0, 1.0]])


def match(da, db, large_px=30.0, force_scale1=True):
    """匹配 → 单应。**运动模型选择**：大位移帧对退化為纯平移。

    实证（diag_ecc.py）：静帧段（|t|<15px）逐对尺度中位 0.99994（无偏）；
    高速摇镜帧对（50–95px）尺度估到 0.97–0.99（噪声大），而 434 帧连乘会把这点噪声
    放大成尺度漂到 1.55→0.55（物理不可能）。一帧内真实变焦极小 ⇒ 对高速帧对
    强制平移模型，比让它自由估尺度更接近真值。
    """
    if da[1] is None or db[1] is None or len(da[1]) < 12 or len(db[1]) < 12:
        return None, None
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    ms = bf.match(da[1], db[1])
    if len(ms) < 12:
        return None, None
    ms = sorted(ms, key=lambda m: m.distance)
    keep = [m for m in ms if m.distance <= max(1.4 * ms[0].distance, 28)]
    if len(keep) < 12:
        keep = ms[: max(12, len(ms) // 2)]
    src = np.float32([da[0][m.queryIdx].pt for m in keep])
    dst = np.float32([db[0][m.trainIdx].pt for m in keep])
    H, inl = cv2.findHomography(src, dst, cv2.RANSAC, RANSAC_PX * SC, maxIters=4000,
                                confidence=0.995)
    if H is None or inl is None or int(inl.sum()) < MIN_INLIER:
        return None, None
    m = inl.ravel().astype(bool)
    P = src[m] * 2                                   # 回到原尺度
    bw = float(P[:, 0].max() - P[:, 0].min()) / 1920.0
    bh = float(P[:, 1].max() - P[:, 1].min()) / 1080.0
    if bw < MIN_SPREAD[0] or bh < MIN_SPREAD[1]:      # 🔴 退化门禁：内点必须铺开
        return None, None
    d = dst[m] - src[m]
    med = np.median(d, axis=0)
    if np.hypot(*med) / SC > large_px:      # 大位移 ⇒ 纯平移
        H = np.array([[1, 0, med[0]], [0, 1, med[1]], [0, 0, 1]], float)
    elif force_scale1:
        H = euclid_ize(H)
    return H, int(inl.sum())


def track(win, verbose=True):
    """逐帧全局单应 → 累积轨迹。返回 {frame: H(0->i)}（0.5 尺度像素坐标）。"""
    fs = frame_paths(win)
    cache = MS / f"align_{win}.json"
    if cache.exists():
        j = json.loads(cache.read_text())
        if j.get("n") == len(fs):
            return {int(k): np.array(v, float) for k, v in j["H"].items()}, j["stats"]
    t0 = time.time()
    Hs = {0: np.eye(3)}
    Hc = np.eye(3)
    stats = {"n": len(fs), "ok": 0, "fail_frames": [], "inliers": [], "resid": []}
    prev = detect(to_gray_small(fs[0])[0])
    for i in range(1, len(fs)):
        cur = detect(to_gray_small(fs[i])[0])
        H, nin = match(prev, cur)
        if H is not None:
            Hc = H @ Hc
            stats["ok"] += 1
            stats["inliers"].append(nin)
        else:
            stats["fail_frames"].append(i)
            stats["inliers"].append(0)
        Hs[i] = Hc.copy()
        prev = cur
        if verbose and (i % 60 == 0 or i == len(fs) - 1):
            print(f"  对齐 {i}/{len(fs)-1}  成功 {stats['ok']}  失败 {len(stats['fail_frames'])}"
                  f"  {time.time()-t0:.0f}s", flush=True)
    cache.write_text(json.dumps({
        "n": len(fs), "scale": SC,
        "H": {str(k): v.tolist() for k, v in Hs.items()},
        "stats": {"ok": stats["ok"], "fail_frames": stats["fail_frames"],
                  "inlier_med": float(np.median([x for x in stats["inliers"] if x > 0])) if stats["ok"] else 0.0,
                  "inlier_min": int(min([x for x in stats["inliers"] if x > 0], default=0))},
    }, ensure_ascii=False))
    print(f"[out] {cache}  成功 {stats['ok']}/{len(fs)-1} = {stats['ok']/(len(fs)-1)*100:.1f}%"
          f"  失败帧 {stats['fail_frames'][:12]}")
    return Hs, stats


def load_H(win):
    j = json.loads((MS / f"align_{win}.json").read_text())
    return {int(k): np.array(v, float) for k, v in j["H"].items()}, j["scale"], j["stats"]


def warp_to_ref(img, H0i, inv=False):
    """把 frame i 的图像变换到 frame 0 坐标系。

    注意矩阵语义：H0i 是「帧0 坐标 → 帧i 坐标」（findHomography(src=prev,dst=cur) 的累积）。
    cv2.warpPerspective(src, M, dsize) 中 M 是「**目标**坐标 → **源**坐标」。
    要生成「帧0 画布」的图像、源是帧 i ⇒ M 必须映射 帧0 → 帧i ⇒ M = H0i（**不取逆**）。
    """
    H = np.linalg.inv(H0i) if inv else H0i
    Hf = np.diag([1 / SC, 1 / SC, 1.0]) @ H @ np.diag([SC, SC, 1.0])
    h, w = img.shape[:2]
    return cv2.warpPerspective(img, Hf, (w, h), flags=cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def traj(win):
    """报告累积相机轨迹 + 检测硬切/异常帧对。

    逐帧对单应已由 diag_align_ab.py 的 A/B 对照验证正确；但整窗累积平移会远超画幅宽
    （43 秒跟拍会平移数千 px），故「整窗对齐到单一画布」物理上不成立 ——
    正解是：全局轨迹 + 在**重叠足够的局部区间**做稳定化。
    """
    Hs, sc, st = load_H(win)
    fs = frame_paths(win)
    print(f"[{win}] 帧数 {len(fs)}  逐对成功 {st['ok']}/{len(fs)-1} = "
          f"{st['ok']/(len(fs)-1)*100:.1f}%  inlier 中位 {st['inlier_med']:.0f}")
    print(f"{'frame':>7}{'累积tx':>10}{'累积ty':>10}{'累积|t|':>10}{'累积scale':>11}"
          f"{'单帧|t|':>10}")
    prev = None
    flags = []
    for i in range(0, len(fs), max(1, len(fs) // 22)):
        H = Hs[i]
        tx, ty = H[0, 2] / SC, H[1, 2] / SC
        sc_ = float(np.sqrt(abs(np.linalg.det(H[:2, :2]))))
        d = ""
        if prev is not None:
            Hin = np.linalg.inv(Hs[prev]) @ H
            dt = np.hypot(Hin[0, 2] / SC, Hin[1, 2] / SC)
            d = f"{dt:>10.1f}"
            if dt > 120:
                flags.append((prev, i, float(dt)))
        print(f"{i:>7}{tx:>10.0f}{ty:>10.0f}{np.hypot(tx,ty):>10.0f}{sc_:>11.4f}{d:>10}")
        prev = i
    print(f"  ⚠️ 大位移帧对（可能硬切/快摇）: {flags[:8] if flags else '无'}")


def build_median(win, step=4, out=None, span=None, ref=None):
    """局部稳定化时间中值：只在 [span] 区间内、以 ref 帧为坐标系。

    整窗不可行（画幅已完全改变）；局部区间内移动对象被中值抹除，静止场地/线保留。
    """
    Hs, sc, st = load_H(win)
    fs = frame_paths(win)
    if span is None:
        k0, k1 = 0, min(160, len(fs) - 1)
    else:
        k0, k1 = span
    ref = ref if ref is not None else (k0 + k1) // 2
    Href = Hs[ref]
    idx = list(range(k0, k1 + 1, step))
    stack, cnt = [], None
    for k in idx:
        img = cv2.imread(str(fs[k]))
        # 想要「参考帧画布」：M 必须映射 参考帧 → 该帧 = inv(H_ref) @ H_k（在 0.5 尺度上）
        Hk_ref = np.linalg.inv(Href) @ Hs[k]
        wimg = warp_to_ref(img, Hk_ref)
        valid = (wimg.sum(axis=2) > 0)
        stack.append(wimg)
        cnt = valid.astype(np.uint16) if cnt is None else cnt + valid
    A = np.stack(stack).astype(np.float32)
    med = np.median(A, axis=0).astype(np.uint8)
    support = cnt / len(idx)
    del A, stack
    out = out or str(MS / f"median_{win}_r{ref}.jpg")
    cv2.imwrite(out, med, [cv2.IMWRITE_JPEG_QUALITY, 93])
    cv2.imwrite(str(MS / f"support_{win}_r{ref}.png"), (support * 255).astype(np.uint8))
    # 与单帧对照（并排）
    single = cv2.imread(str(fs[ref]))
    cv2.imwrite(str(MS / f"median_vs_single_{win}.jpg"),
                np.concatenate([single, med], axis=1), [cv2.IMWRITE_JPEG_QUALITY, 92])
    print(f"[out] {out}   区间 [{k0},{k1}] 每 {step} 帧取 1（{len(idx)} 帧），坐标系=帧 {ref}")
    print(f"      支撑率 >0.9 的像素占比 {(support>0.9).mean()*100:.1f}%   "
          f">0.5 {(support>0.5).mean()*100:.1f}%")
    print(f"      对照图 median_vs_single_{win}.jpg（左=单帧 右=时间中值）")
    return med, support


def anaglyph(win, ks=(40, 200), out=None):
    """红=参考帧 / 绿=对齐后的第 K 帧。对齐正确 ⇒ 静态结构呈黄灰（红绿重合）；
    错位 ⇒ 红绿分离。同时给高梯度区光度一致性指标（对齐 vs 不对齐）。"""
    Hs, sc, st = load_H(win)
    fs = frame_paths(win)
    ref = cv2.imread(str(fs[0]), cv2.IMREAD_GRAYSCALE)
    gx = cv2.Sobel(ref, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(ref, cv2.CV_32F, 0, 1, ksize=3)
    grad = np.hypot(gx, gy)
    mask = grad > 30
    tiles, report = [], []
    for k in ks:
        if k >= len(fs):
            continue
        raw = cv2.imread(str(fs[k]), cv2.IMREAD_GRAYSCALE)
        war = warp_to_ref(cv2.imread(str(fs[k])), Hs[k])
        war = cv2.cvtColor(war, cv2.COLOR_BGR2GRAY)
        d_al = np.abs(ref.astype(np.float32) - war.astype(np.float32))[mask]
        d_raw = np.abs(ref.astype(np.float32) - raw.astype(np.float32))[mask]
        report.append((k, float(np.median(d_al)), float(np.median(d_raw)),
                       float((d_al < 25).mean())))
        rgb = np.zeros((ref.shape[0], ref.shape[1], 3), np.uint8)
        rgb[:, :, 2] = ref
        rgb[:, :, 1] = war
        tiles.append(rgb)
    out = out or str(MS / f"anaglyph_{win}.jpg")
    if tiles:
        cv2.imwrite(out, np.concatenate(tiles, axis=1), [cv2.IMWRITE_JPEG_QUALITY, 92])
        print(f"[out] {out}  （红=参考帧, 绿=对齐后第 K 帧）")
    print(f"{'K':>5}{'对齐后中位|Δ|':>14}{'未对齐中位|Δ|':>15}{'<25 比例':>10}")
    for k, a, r, f in report:
        print(f"{k:>5}{a:>14.1f}{r:>15.1f}{f*100:>9.1f}%")


def check(win, frames=(0, 120, 260, 400), out=None):
    Hs, sc, st = load_H(win)
    fs = frame_paths(win)
    frames = [k for k in frames if k < len(fs)]
    base = cv2.imread(str(fs[frames[0]]))
    acc = base.astype(np.float32)
    for k in frames[1:]:
        wimg = warp_to_ref(cv2.imread(str(fs[k])), Hs[k])
        acc += wimg.astype(np.float32)
    blend = (acc / len(frames)).astype(np.uint8)
    # 并排：左=参考帧，右=对齐平均
    side = np.concatenate([base, blend], axis=1)
    out = out or str(MS / f"aligncheck_{win}.jpg")
    cv2.imwrite(out, side, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print(f"[out] {out}  帧 {frames}（左=参考帧 右=对齐后平均；对齐好则静态结构清晰、人成鬼影）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", required=True)
    ap.add_argument("--track", action="store_true")
    ap.add_argument("--median", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--anaglyph", action="store_true")
    ap.add_argument("--ks", nargs="+", type=int, default=[40, 200])
    ap.add_argument("--frames", nargs="+", type=int, default=[0, 120, 260, 400])
    ap.add_argument("--step", type=int, default=4)
    ap.add_argument("--span", nargs=2, type=int, default=None)
    ap.add_argument("--ref", type=int, default=None)
    ap.add_argument("--traj", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    if a.track:
        track(a.window)
    if a.traj:
        traj(a.window)
    if a.median:
        build_median(a.window, a.step, a.out, a.span, a.ref)
    if a.check:
        check(a.window, a.frames, a.out)
    if a.anaglyph:
        anaglyph(a.window, tuple(a.ks), a.out)


if __name__ == "__main__":
    main()
