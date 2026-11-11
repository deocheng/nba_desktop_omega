#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""assign_team.py —— 广播片段「逐帧队色分配」（A4.61 解锁路径①）

为什么逐帧、不依赖 track_id
---------------------------
A4.61 Phase1.5 诊断：广播追踪 track_id 中位寿命仅 1.3–1.7s，187 个 ID 承载 12 个位置
（复用/流失 15.6×）。任何「跨帧聚合 track_id 颜色」都会把同一真人多段碎片混成噪声。

**队色是逐帧独立判据**：第 f 帧里某个框的颜色只取决于那一帧画面，与「这个框是不是
上一帧同一个人」无关。所以：
  - 逐帧对场上所有人跑 2-means → 该帧两队主色 → 每人贴 0/1；
  - 再把每帧的两队色心对齐到「参考帧」的两队色心（按色心距离就近匹配），得到
    **跨帧一致的两队编号**，无需任何 ID 稳定性。

实现
----
  ① torso_median（移植 team_color）：躯干 ROI 去亮度分位 25–75% 取中位 RGB，抗号码/阴影；
  ② 逐帧 2-means（在 RGB 空间，k=2，固定 seed 可复现）确定该帧两队色心；
  ③ 参考帧 = 球员数最多的帧（最可靠）；其余帧色心按「最近色心」对齐到参考帧编号；
  ④ 小样本帧（场上 <4 个有效颜色）不跑 2-means，直接按「最近参考色心」贴标签，
     避免单队画面被 2-means 强行劈成两半。
  ⑤ 输出 team_of[(idx,tid)]=0/1（逐帧），外加段级全局两队色心 + 每 track 多数票 team_map。

用法
----
  模块:  from assign_team import compute_team_of
         team_of, info = compute_team_of(seg_dir)   # seg_dir 含 frames.json + tracks.json
  CLI:   assign_team.py <seg_dir> [--out team_assign.json] [--render-out DIR]
"""
from __future__ import annotations

import argparse
import json
import math
import statistics as _st
from collections import Counter
from pathlib import Path

import court_filter as cf_mod  # 复用球场地面掩膜(与相机运动无关)做「脚点是否在地板上」判定
import cv2
import numpy as np

# 移植自 team_color.py —— NBA 常见球衣/裁判服先验色心（sRGB），用于给段级色心命名
ANCHORS = {
    "white": (245, 245, 245), "lightgray": (190, 190, 190),
    "gray": (128, 128, 128), "black": (28, 28, 28),
    "red": (200, 30, 40), "darkred": (120, 20, 25),
    "orange": (225, 120, 30), "gold": (250, 200, 60),
    "yellow": (240, 220, 70), "green": (25, 130, 70),
    "blue": (30, 70, 175), "navy": (20, 35, 90),
    "purple": (105, 45, 150), "teal": (20, 120, 140),
    "maroon": (110, 30, 45), "silver": (170, 175, 180),
}

MIN_PLAYERS_FOR_KMEANS = 4  # 场上有效颜色少于此数 → 不用 2-means，直接贴参考色心


def torso_median(img, box):
    """躯干 ROI 中位 RGB（BGR 入，BGR 出）。移植 team_color.torso_median。"""
    x1, y1, x2, y2 = [int(v) for v in box]
    w, h = x2 - x1, y2 - y1
    if w < 8 or h < 16:
        return None
    rx1 = x1 + int(0.20 * w); rx2 = x1 + int(0.80 * w)
    ry1 = y1 + int(0.12 * h); ry2 = y1 + int(0.45 * h)
    rx1, rx2 = max(0, rx1), min(img.shape[1], rx2)
    ry1, ry2 = max(0, ry1), min(img.shape[0], ry2)
    if rx2 - rx1 < 5 or ry2 - ry1 < 5:
        return None
    roi = img[ry1:ry2, rx1:rx2].reshape(-1, 3).astype(np.float32)
    lum = roi @ np.array([0.114, 0.587, 0.299], dtype=np.float32)
    lo, hi = np.percentile(lum, [25, 75])
    sel = roi[(lum >= lo) & (lum <= hi)]
    if len(sel) < 20:
        sel = roi
    return np.median(sel, axis=0)  # BGR


def _kmeans2(X, iters=40, seed=1):
    """极简 2-means，返回 (centers[2], labels)。X: (n,3) float32。"""
    rng = np.random.default_rng(seed)
    ctr = X[rng.choice(len(X), 2, replace=False)].astype(np.float64)
    for _ in range(iters):
        d = ((X[:, None, :] - ctr[None, :, :]) ** 2).sum(-1)
        lab = d.argmin(1)
        for k in range(2):
            if (lab == k).sum() > 0:
                ctr[k] = X[lab == k].mean(0)
    d = ((X[:, None, :] - ctr[None, :, :]) ** 2).sum(-1)
    return ctr, d.argmin(1)


def _nearest_anchor_name(rgb):
    best, bd = "?", 1e18
    for k, v in ANCHORS.items():
        d = sum((a - b) ** 2 for a, b in zip(rgb, v))
        if d < bd:
            best, bd = k, d ** 0.5
    return best


def _scan_frames(seg_dir, tracks_name):
    """单趟扫描每帧: 生成 (idx, row[(tid,rgb)], foot[(tid,(fx,fy,inside,mask_valid))], diags[])。

    row       : 该帧有有效躯干色的 (tid, BGR中位) 列表
    foot      : 该帧每个 tid 的 (足点x, 足点y, 是否在地板上, 掩膜是否有效)
    diags     : 该帧每个框的对角线长度(px)
    颜色 + 球场掩膜(与相机运动无关) + 框对角线 在同一趟图像读取里算完, 避免重复 io。
    """
    seg_dir = Path(seg_dir)
    tracks = json.loads((seg_dir / tracks_name).read_text(encoding="utf-8"))
    frames_recs = json.loads((seg_dir / "frames.json").read_text(encoding="utf-8"))
    idx2path = {r["idx"]: r["path"] for r in frames_recs}
    for fr in tracks["frames"]:
        idx = fr["idx"]
        fp = idx2path.get(idx)
        if not fp or not Path(fp).exists():
            fp = seg_dir / "frames" / f"f{idx + 1:05d}.jpg"
        img = cv2.imread(str(fp))
        if img is None:
            continue
        m, _ = cf_mod.court_mask(img)      # 地板掩膜(与相机运动无关)
        H = W = 0
        if m is not None:
            H, W = m.shape
        row, foot, diags = [], {}, []
        for p in fr.get("players", []):
            rgb = torso_median(img, p["box"])
            if rgb is not None:
                row.append((int(p["id"]), rgb))
            x1, y1, x2, y2 = [int(v) for v in p["box"]]
            diags.append(math.hypot(x2 - x1, y2 - y1))
            fx, fy = (x1 + x2) // 2, y2
            inside = False
            mv = False
            if m is not None and 0 <= fx < W and 0 <= fy < H:
                inside = bool(m[min(fy, H - 1), min(fx, W - 1)] > 0)
                mv = True
            foot[int(p["id"])] = (fx, fy, inside, mv)
        yield idx, row, foot, diags


def _purify(foot_traj, foot_inside, med_diag, motion_frac, oncourt_min_frac):
    """候选池净化(A4.62 第一步)。

    两道数据驱动闸门(均为片段自身统计量的相对量, 与 probe 的 0.5·med_diag 同风格):
      ① 场上脚点门: 脚点在地板掩膜内的帧占比 ≥ oncourt_min_frac(仅统计掩膜有效帧)
         —— 剔 观众席/远端边线替补(脚点在地板外)
      ② 运动地板门: 整段「相邻帧」foot 位移累计 path_len ≥ motion_frac·med_diag
         —— 剔 坐姿替补/前排静坐观众(位移恒≈0)
      两门均过 → 入配对池(记为真实场上球员); 否则 team=None 掉出配对池。
      🔴 已知残留: 裁判也「在场上+移动」→ 两门过不了(需另用队色/衣条纹剔除, 待下一步)。
    返回 (keep_set, detail_dict)。
    """
    keep, detail = set(), {}
    for tid, traj in foot_traj.items():
        traj = sorted(traj, key=lambda t: t[0])
        plen = 0.0
        for k in range(1, len(traj)):
            if traj[k][0] - traj[k - 1][0] == 1:   # 仅相邻帧累计, 避免 track 丢失造成伪跳变
                plen += math.hypot(traj[k][1] - traj[k - 1][1],
                                   traj[k][2] - traj[k - 1][2])
        ins = foot_inside.get(tid, [])
        nvalid = sum(1 for _, mv in ins if mv)
        ninside = sum(1 for i, mv in ins if mv and i)
        on_frac = (ninside / nvalid) if nvalid else 1.0   # 无有效掩膜 → 视为在场(不误删)
        g1 = on_frac >= oncourt_min_frac
        g2 = plen >= motion_frac * med_diag
        ok = g1 and g2
        if ok:
            keep.add(tid)
        detail[tid] = {"on_frac": round(on_frac, 3), "path_len": round(plen, 1),
                       "med_diag": round(med_diag, 1),
                       "gate_oncourt": g1, "gate_motion": g2}
    return keep, detail


def player_track_ids(seg_dir, tracks_name="tracks.json", motion_frac=0.3, oncourt_min_frac=0.5):
    """独立求候选池(真实场上球员 tid 集合)。供 CLI / 探针复用。返回 (keep_set, detail)。"""
    foot_traj, foot_inside, diags_all = {}, {}, []
    for idx, _row, foot, diags in _scan_frames(seg_dir, tracks_name):
        for tid, (fx, fy, _inside, _mv) in foot.items():
            foot_traj.setdefault(tid, []).append((idx, fx, fy))
            foot_inside.setdefault(tid, []).append((_inside, _mv))
        diags_all.extend(diags)
    med_diag = _st.median(diags_all) if diags_all else 1.0
    return _purify(foot_traj, foot_inside, med_diag, motion_frac, oncourt_min_frac)


def compute_team_of(seg_dir, tracks_name="tracks.json", venv_py=None,
                    player_track_ids=None, motion_frac=0.3, oncourt_min_frac=0.5):
    """对一段 broadcast 片段做逐帧队色分配 + 候选池净化(A4.62 第一步)。

    参数
    ----
      seg_dir          : 含 frames.json（idx→path）与 tracks.json（frames[]/players[]）的目录
      player_track_ids : 可选 set[int]; 提供则只对其中 tid 赋队色(0/1), 其余 team=None(掉出配对池)。
                         默认 None → 内部用 _purify 算(场上脚点门 + 运动地板门)。
      motion_frac      : 运动地板门阈值(相对 med_diag); 默认 0.3
      oncourt_min_frac : 场上脚点门阈值(掩膜有效帧占比); 默认 0.5
    返回
    ----
      team_of : dict[(idx,int, tid,int)] -> 0/1/None   （逐帧队色; None=掉出配对池）
      info    : dict（参考帧、全局两队 RGB 色心、命名、每 track 多数票、净化统计）
    """
    seg_dir = Path(seg_dir)
    # 单趟扫描: 颜色 + 脚点 + 框对角线
    per_frame_rgb = {}
    foot_traj = {}      # tid -> [(idx,fx,fy)]
    foot_inside = {}    # tid -> [(inside_bool, mask_valid_bool)]
    diags_all = []
    for idx, row, foot, diags in _scan_frames(seg_dir, tracks_name):
        if row:
            per_frame_rgb[idx] = row
        for tid, (fx, fy, inside, mv) in foot.items():
            foot_traj.setdefault(tid, []).append((idx, fx, fy))
            foot_inside.setdefault(tid, []).append((inside, mv))
        diags_all.extend(diags)

    if not per_frame_rgb:
        return {}, {"error": "no frames with torso color",
                    "purify": {"n_tids": len(foot_traj), "n_purified": 0}}

    med_diag = _st.median(diags_all) if diags_all else 1.0

    # ── 候选池净化 ──
    if player_track_ids is None:
        player_track_ids, purify_detail = _purify(foot_traj, foot_inside, med_diag,
                                                  motion_frac, oncourt_min_frac)
    else:
        purify_detail = {tid: {"on_frac": None, "path_len": None, "med_diag": round(med_diag, 1),
                               "gate_oncourt": True, "gate_motion": True, "provided": True}
                         for tid in player_track_ids}

    # 2) 选参考帧 = 有效颜色最多的帧
    ref_idx = max(per_frame_rgb, key=lambda i: len(per_frame_rgb[i]))
    ref_arr = np.array([c for _, c in per_frame_rgb[ref_idx]], dtype=np.float32)
    ref_ctr, _ = _kmeans2(ref_arr)
    ref_ctr = ref_ctr.astype(np.float64)  # [2,3] BGR

    # 3) 逐帧对齐
    team_of = {}
    frame_centers = {}      # idx -> [[r,g,b],[r,g,b]] (RGB, 仅记录用)
    for idx, row in per_frame_rgb.items():
        tids = [t for t, _ in row]
        X = np.array([c for _, c in row], dtype=np.float32)
        if len(X) >= MIN_PLAYERS_FOR_KMEANS:
            ctr, lab = _kmeans2(X)
            # 对齐：把帧色心按最近匹配到参考色心编号
            d00 = float(np.sum((ctr[0] - ref_ctr[0]) ** 2))
            d11 = float(np.sum((ctr[1] - ref_ctr[1]) ** 2))
            d01 = float(np.sum((ctr[0] - ref_ctr[1]) ** 2))
            d10 = float(np.sum((ctr[1] - ref_ctr[0]) ** 2))
            if d00 + d11 <= d01 + d10:
                pass  # 0->0, 1->1
            else:
                lab = 1 - lab  # 翻转
            frame_centers[idx] = [[float(v) for v in ctr[k][::-1]] for k in range(2)]
        else:
            # 小样本：直接按最近参考色心贴标签
            d = ((X[:, None, :] - ref_ctr[None, :, :]) ** 2).sum(-1)
            lab = d.argmin(1)
            frame_centers[idx] = [[float(v) for v in ref_ctr[k][::-1]] for k in range(2)]
        for tid, l in zip(tids, lab.tolist()):
            # 候选池净化门: 不在池内的 tid → team=None(掉出两两配对池)
            team_of[(idx, tid)] = int(l) if tid in player_track_ids else None

    # 4) 每 track 多数票（仅统计被净化的真实球员; 便利量, 不用于逐帧判据）
    track_votes = {}
    for (idx, tid), t in team_of.items():
        if t is None:
            continue
        track_votes.setdefault(tid, Counter())[t] += 1
    team_map = {tid: int(c.most_common(1)[0][0]) for tid, c in track_votes.items()}

    centers_rgb = [[float(v) for v in ref_ctr[k][::-1]] for k in range(2)]  # RGB
    names = [_nearest_anchor_name(tuple(int(round(v)) for v in centers_rgb[k])) for k in range(2)]

    info = {
        "seg": seg_dir.name,
        "n_frames_with_color": len(per_frame_rgb),
        "n_players_assigned": len([t for t in team_of.values() if t is not None]),
        "n_players_dropped": len([t for t in team_of.values() if t is None]),
        "reference_frame_idx": ref_idx,
        "centers_rgb": centers_rgb,
        "center_names": names,
        "team_map": {str(k): v for k, v in team_map.items()},
        "team_map_majority_share": {str(tid): round(c.most_common(1)[0][1] / c.total(), 3)
                                    for tid, c in track_votes.items()},
        "purify": {
            "n_tids_total": len(foot_traj),
            "n_purified": len(player_track_ids),
            "med_diag": round(med_diag, 1),
            "motion_frac": motion_frac,
            "oncourt_min_frac": oncourt_min_frac,
            "detail": {str(k): v for k, v in purify_detail.items()},
        },
    }
    return team_of, info


def render_overlay(seg_dir, out_dir, team_of, info, frames=(0, 50, 100, 150), tracks_name="tracks.json"):
    """渲染「队色框 + 球 + 持球人」叠加图，用于目视自证。返回 png 路径列表。"""
    seg_dir = Path(seg_dir)
    tracks = json.loads((seg_dir / tracks_name).read_text(encoding="utf-8"))
    frames_recs = json.loads((seg_dir / "frames.json").read_text(encoding="utf-8"))
    idx2path = {r["idx"]: r["path"] for r in frames_recs}
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    pngs = []
    # 队色 → 画框色（BGR）：team0 红, team1 青
    col = {0: (40, 60, 230), 1: (230, 180, 40)}
    for fr in tracks["frames"]:
        idx = fr["idx"]
        if idx not in frames:
            continue
        fp = idx2path.get(idx)
        if not fp or not Path(fp).exists():
            fp = seg_dir / "frames" / f"f{idx+1:05d}.jpg"
        img = cv2.imread(str(fp))
        if img is None:
            continue
        for p in fr.get("players", []):
            t = team_of.get((idx, int(p["id"])))
            if t is None:
                continue
            x1, y1, x2, y2 = [int(v) for v in p["box"]]
            cv2.rectangle(img, (x1, y1), (x2, y2), col[t], 3)
            cv2.putText(img, f"{p['id']}", (x1, max(20, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, col[t], 2)
        b = fr.get("ball") or {}
        if b.get("box"):
            bx1, by1, bx2, by2 = [int(v) for v in b["box"]]
            cv2.rectangle(img, (bx1, by1), (bx2, by2), (0, 255, 0), 3)
        bh_id = fr.get("ball_handler")
        if bh_id is not None:
            cv2.putText(img, f"BH={bh_id}", (20, 30), cv2.FONT_HERSHEY_SIMPLEX,
                        0.9, (0, 255, 0), 2)
        cap = f"{seg_dir.name} f{idx}  team0={info['center_names'][0]}({info['centers_rgb'][0]}) team1={info['center_names'][1]}({info['centers_rgb'][1]})"
        cv2.putText(img, cap[:90], (20, img.shape[0] - 16), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, (230, 230, 230), 1)
        p = out / f"team_{seg_dir.name}_f{idx:05d}.jpg"
        cv2.imwrite(str(p), img)
        pngs.append(str(p))
    return pngs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("seg_dir")
    ap.add_argument("--tracks", default="tracks.json", help="tracks 文件名(tracks.json 或 tracks_cf.json)")
    ap.add_argument("--out", default=None, help="team_assign.json 路径(默认 seg_dir 下)")
    ap.add_argument("--render-out", default=None, help="渲染叠加图目录")
    ap.add_argument("--render-frames", default="0,50,100,150", help="渲染帧 idx 逗号列表")
    a = ap.parse_args()

    team_of, info = compute_team_of(a.seg_dir, tracks_name=a.tracks)
    out = Path(a.out) if a.out else Path(a.seg_dir) / "team_assign.json"
    out.write_text(json.dumps({"team_of": {f"{i}:{t}": v for (i, t), v in team_of.items()},
                                "info": info}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[assign_team] {a.seg_dir}  (tracks={a.tracks})")
    print(f"  参考帧={info['reference_frame_idx']}  有效帧={info['n_frames_with_color']}  "
          f"分配球员帧={info['n_players_assigned']}")
    print(f"  两队色心 RGB: team0={info['center_names'][0]}{info['centers_rgb'][0]}  "
          f"team1={info['center_names'][1]}{info['centers_rgb'][1]}")
    print(f"  每 track 多数票队色: {info['team_map']}")
    print(f"  -> {out}")

    if a.render_out:
        fs = [int(x) for x in a.render_frames.split(",") if x.strip()]
        pngs = render_overlay(a.seg_dir, a.render_out, team_of, info, frames=fs, tracks_name=a.tracks)
        print(f"  [图] 渲染 {len(pngs)} 张: {pngs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
