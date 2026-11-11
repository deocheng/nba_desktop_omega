#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stabilize_tracks_v2 —— 外观(DINOv2)+几何 融合的球员轨迹重链器（A4.43）。

动机（已核实基线，sas_det_poss_tile/ball_tracks.json）：
  生产 BotSort(botsort_stable.yaml, with_reid=False) 在摇镜+遮挡下碎裂：
  distinct track_id=260，中位寿命仅 8 帧(≈0.8s)，而场上实约 12 人。
  ⇒ 战术层消费 track_id 时 ID 频繁切换，teamID 因此 NOT_QUALIFIED（t3b）。

做法（当前方案内，无新模型）：
  把现有 <clip>_poss_tile/ball_tracks.json 的「track_id」当作**逐帧检测标签**，
  重新做跨帧关联。代价 = 几何(脚点位移 + 尺寸对数比) + 外观(DINOv2-small 躯干嵌入余弦)，
  匈牙利匹配 + track_buffer 处理短暂遮挡/出框重入。外观特征复用 team_embed.py 已落的
  本地 DINOv2-small（facebook/dinov2-small，HF 镜像缓存）。

产出：<outdir>/ball_tracks.json —— 稳定 track_id + 每 track 的 team 标签(0/1)。
  不覆盖生产文件；生产战术链路可改指此文件重评 teamID。

用法:
  stabilize_tracks_v2.py <ball_tracks.json> <imgdir> --out <outdir>
      [--gate 0.14] [--size-gate 0.55] [--w-app 1.0] [--app-thresh 0.30]
      [--track-buffer 30] [--new-conf 0.30] [--k 2] [--render <dir>]
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

from common.nba_paths import tactics_data_file

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
AW = Path(str(tactics_data_file("action_work")))
MODEL = "facebook/dinov2-small"
_DEV = None
_PROC = None
_MOD = None


def _ensure_model():
    global _DEV, _PROC, _MOD
    if _MOD is not None:
        return
    import torch
    from transformers import AutoImageProcessor, AutoModel
    _PROC = AutoImageProcessor.from_pretrained(MODEL)
    _MOD = AutoModel.from_pretrained(MODEL).eval()
    _DEV = "mps" if torch.backends.mps.is_available() else "cpu"
    _MOD = _MOD.to(_DEV)


def embed_crops(crops):
    """crops: list[np.ndarray BGR]; 返回 L2-归一化 CLS 嵌入 [N,384]。"""
    _ensure_model()
    import torch
    if not crops:
        return np.zeros((0, 384), np.float32)
    rgbs = [cv2.cvtColor(c, cv2.COLOR_BGR2RGB) for c in crops]
    with torch.no_grad():
        inp = _PROC(images=rgbs, return_tensors="pt").to(_DEV)
        e = _MOD(**inp).last_hidden_state[:, 0]
        e = torch.nn.functional.normalize(e, dim=-1)
    return e.cpu().numpy().astype(np.float32)


def foot_of(bbox):
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, float(y2))


def torso_crop(bbox, img, ratio=0.62):
    """取 bbox 顶端 ratio 高度（躯干+头，去掉脚下场地噪声）喂 DINOv2。"""
    if img is None:
        return np.zeros((10, 10, 3), np.uint8)
    x1, y1, x2, y2 = [int(v) for v in bbox]
    x1, y1 = max(0, x1), max(0, y1)
    x2 = min(img.shape[1] - 1, x2)
    y2 = min(img.shape[0] - 1, y2)
    h = max(1, y2 - y1)
    yt = y1 + int(h * ratio)
    if yt - y1 < 8 or x2 - x1 < 8:
        return img[y1:y2, x1:x2].copy()
    return img[y1:yt, x1:x2].copy()


def pose_torso_crop(img, kps, pad=0.15, fill=114):
    """肩髋多边形掩膜躯干裁切（复刻 team_embed.torso_crop）：去掉背景/球场噪声。

    kps: COCO 17 点 [[x,y,conf]...]；idx=[5,6,12,11]=l_sh/r_sh/r_hip/l_hip。
    """
    if img is None or kps is None:
        return None
    idx = [5, 6, 12, 11]
    if min(kps[i][2] for i in idx) < 0.30:
        return None
    poly = np.array([[kps[i][0], kps[i][1]] for i in idx], np.float32)
    x1, y1 = poly[:, 0].min(), poly[:, 1].min()
    x2, y2 = poly[:, 0].max(), poly[:, 1].max()
    pw, ph = max(1.0, x2 - x1), max(1.0, y2 - y1)
    x1, x2 = x1 - pad * pw, x2 + pad * pw
    y1, y2 = y1 - pad * ph, y2 + pad * ph
    x1, y1 = max(0, int(x1)), max(0, int(y1))
    x2, y2 = min(img.shape[1] - 1, int(x2)), min(img.shape[0] - 1, int(y2))
    if x2 - x1 < 8 or y2 - y1 < 8:
        return None
    crop = img[y1:y2, x1:x2].copy()
    m = np.zeros(crop.shape[:2], np.uint8)
    cv2.fillPoly(m, [(poly - np.array([x1, y1])).astype(np.int32)], 255)
    crop[m == 0] = fill
    return crop


def match_person_iou(persons, box, thr=0.3):
    """把球员检测框匹配到姿态关键点 person（取最大 IoU）。"""
    if not persons:
        return None
    ax1, ay1, ax2, ay2 = box
    best, bdi = None, 0.0
    for p in persons:
        b = p["bbox"]
        ix1, iy1 = max(ax1, b[0]), max(ay1, b[1])
        ix2, iy2 = min(ax2, b[2]), min(ay2, b[3])
        iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
        inter = iw * ih
        if inter <= 0:
            continue
        aa = (ax2 - ax1) * (ay2 - ay1)
        ab = (b[2] - b[0]) * (b[3] - b[1])
        iou = inter / (aa + ab - inter)
        if iou > bdi:
            bdi, best = iou, p
    return best if bdi > thr else None


def pose_torso_crop_on_det(img, bbox, model, pad=0.18):
    """对单个 RF-DETR 球员检测框做 pose（保证关键点与该框对齐），再 torso 掩膜裁切。

    绕开「两套检测器框不对齐」陷阱：直接在检测框附近裁切跑 YOLO11n-pose，
    取裁剪内唯一人体关键点，平移回全图坐标后掩膜。无关键点则回退 None。
    """
    if img is None or model is None:
        return None
    x1, y1, x2, y2 = [int(v) for v in bbox]
    w, h = max(1, x2 - x1), max(1, y2 - y1)
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    nx1 = max(0, int(cx - pad * w))
    ny1 = max(0, int(cy - pad * h))
    nx2 = min(img.shape[1] - 1, int(cx + pad * w))
    ny2 = min(img.shape[0] - 1, int(cy + pad * h))
    crop_img = img[ny1:ny2, nx1:nx2]
    if crop_img.size == 0:
        return None
    res = model.predict(crop_img, conf=0.30, device="mps", verbose=False)[0]
    if res.keypoints is None or len(res.keypoints.data) == 0:
        return None
    kps0 = res.keypoints.data[0].tolist()
    kps = [[kp[0] + nx1, kp[1] + ny1, kp[2]] for kp in kps0]
    return pose_torso_crop(img, kps)


def kmeans(X, k, iters=100, seed=7):
    rng = np.random.default_rng(seed)
    C = X[rng.choice(len(X), k, replace=False)].copy()
    L = np.zeros(len(X), int)
    for _ in range(iters):
        L = ((X[:, None, :] - C[None, :, :]) ** 2).sum(-1).argmin(1)
        newC = np.array([X[L == j].mean(0) if (L == j).sum() else C[j]
                         for j in range(k)])
        if np.allclose(newC, C, atol=1e-6):
            C = newC
            break
        C = newC
    return C, L


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ball_tracks")
    ap.add_argument("imgdir")
    ap.add_argument("--out", required=True)
    ap.add_argument("--gate", type=float, default=0.14, help="脚点位移门控 / 画面高")
    ap.add_argument("--size-gate", type=float, default=0.90, help="|log(h1/h2)| 上限(放宽以容忍检测器尺寸抖动)")
    ap.add_argument("--w-app", type=float, default=1.0, help="外观代价权重")
    ap.add_argument("--app-thresh", type=float, default=0.15, help="最小余弦相似度(低于不许关联)")
    ap.add_argument("--torso-ratio", type=float, default=0.62, help="外观裁切取 bbox 顶端比例(去脚下场地)")
    ap.add_argument("--pose-cache", default=None, help="YOLO11n-pose 关键点缓存({fn.jpg:[{bbox,kps}]});⚠️ 若关键点来自不同检测器(RF-DETR 球员框)则 IoU 对齐率极低,勿用")
    ap.add_argument("--pose-masked", action="store_true", help="对每个 RF-DETR 球员框 on-the-fly 跑 YOLO11n-pose(框对齐)做 torso 掩膜外观——正确姿势(替代 --pose-cache)")
    ap.add_argument("--pose-model", default=str(Path(str(tactics_data_file("action_work/weights/yolo11n-pose.pt")))), help="YOLO11n-pose 权重")
    ap.add_argument("--pose-pad", type=float, default=0.18, help="on-the-fly pose 裁切框外扩比例")
    ap.add_argument("--track-buffer", type=int, default=60, help="丢失后保留帧数(放大以容忍遮挡/出框重入)")
    ap.add_argument("--zombie-buffer", type=int, default=120, help="死轨迹复活窗口(>track_buffer，长时间出框后同 ID 续接)")
    ap.add_argument("--zombie-app", type=float, default=0.45, help="僵尸复活最小外观余弦(高于普通匹配，防误合并)")
    ap.add_argument("--new-conf", type=float, default=0.30, help="起新轨迹的最小检测置信")
    ap.add_argument("--k", type=int, default=2, help="队色聚类数")
    ap.add_argument("--min-track", type=int, default=15, help="参与队色聚类的轨迹最小长度")
    ap.add_argument("--conf-min", type=float, default=0.0,
                    help="净化门前置：只保留 conf>= 该值的检测(0=不过滤)。ep*_sX 源未过滤，需设 ~0.5")
    ap.add_argument("--h-min", type=float, default=0.0,
                    help="净化门前置：只保留框高>= 该像素的检测(0=不过滤)，滤远景/观众"
                         "。⚠️ 绝对高度对镜头景别不鲁棒：宽景镜头里真球员框高就<80px，"
                         "用它会把人砍光（实测 ep69_s1 21→5、ep14_s1 20→6）。优先用 --topn")
    ap.add_argument("--topn", type=int, default=0,
                    help="净化门前置：每帧只保留 conf>=conf-min 里**框最高的至多 topn 个**(0=不限制)。"
                         "物理依据=篮球规则(半场同时 ≤10 球员+≤3 裁判)；与景别无关，故对全语料鲁棒。"
                         "实测 conf≥0.40+topn12 ⇒ 171/177 段落在 [8,16]，优于 h_min=80 的 122/177")
    ap.add_argument("--fps", type=float, default=2.0,
                    help="抽帧率(segment_frames.py 默认 2.0)；留痕用，用于把帧数换算成秒")
    ap.add_argument("--dump-emb", default=None,
                    help="①-B 身份正确性验收用：落盘每帧外观嵌入(json)；不改变任何匹配逻辑")
    ap.add_argument("--render", default=None)
    ap.add_argument("--img-h", type=float, default=1080.0)
    a = ap.parse_args()

    frames = json.load(open(a.ball_tracks))
    imgdir = Path(a.imgdir)
    gate = a.gate * a.img_h
    pose_cache = json.load(open(a.pose_cache)) if a.pose_cache else None
    pose_model = None
    if a.pose_masked:
        from ultralytics import YOLO
        pose_model = YOLO(a.pose_model)

    tracks: dict[int, dict] = {}
    nxt = 1
    out_frames = []
    emb_dump = []
    emb_buf = defaultdict(list)  # track_id -> [emb]

    for f in frames:
        fn = f.get("file")
        img = cv2.imread(str(imgdir / fn)) if fn else None
        # 净化门前置过滤：ep*_sX 段的源 ball_tracks.json 是**未过滤原始检测**
        # （conf 中位 0.41、33% 框高<60px 的远景/观众），直接跑会把并发顶到 25~27，
        # 撞死「并发∈[8,16]」硬门。故按 置信 + 最小框高 过滤后再做匹配。
        dets = f.get("players", []) or []
        if a.conf_min > 0 or a.h_min > 0 or a.topn > 0:
            dets = [p for p in dets
                    if (a.conf_min <= 0 or (p.get("conf") or 0.0) >= a.conf_min)
                    and (a.h_min <= 0 or ((p["bbox"][3] - p["bbox"][1]) >= a.h_min))]
            # 每帧保留框最高的 topn 个（景别无关，物理上界=篮球规则人数上限）
            if a.topn > 0 and len(dets) > a.topn:
                dets = sorted(dets, key=lambda p: -(p["bbox"][3] - p["bbox"][1]))[: a.topn]
        # 外观嵌入（批量）
        if a.pose_masked and pose_model is not None:
            crops = []
            for p in dets:
                crop = pose_torso_crop_on_det(img, p["bbox"], pose_model, a.pose_pad)
                if crop is None:
                    crop = torso_crop(p["bbox"], img, a.torso_ratio)
                crops.append(crop)
        elif pose_cache is not None:
            persons = pose_cache.get(fn, [])
            crops = []
            for p in dets:
                crop = None
                person = match_person_iou(persons, p["bbox"])
                if person is not None:
                    crop = pose_torso_crop(img, person.get("kps"))
                if crop is None:
                    crop = torso_crop(p["bbox"], img, a.torso_ratio)
                crops.append(crop)
        else:
            crops = [torso_crop(p["bbox"], img, a.torso_ratio) for p in dets]
        embs = embed_crops(crops) if img is not None else np.zeros((len(dets), 384), np.float32)
        # ①-B 身份正确性验收用：按 dets 顺序落盘每帧外观嵌入（与 new_players 同序）
        if a.dump_emb:
            emb_dump.append({"frame": f.get("frame"), "embs": [[float(v) for v in e] for e in embs]})

        cand = {t: v for t, v in tracks.items() if v["missed"] <= a.zombie_buffer}
        live_tids = [t for t in cand if cand[t]["missed"] <= a.track_buffer]
        zombie_tids = [t for t in cand if cand[t]["missed"] > a.track_buffer]
        det_foot = [foot_of(p["bbox"]) for p in dets]
        det_h = [p["bbox"][3] - p["bbox"][1] for p in dets]
        assign = {}
        used_det = set()

        def try_match(tids, app_min):
            if not tids or not dets:
                return
            C = np.full((len(tids), len(dets)), 1e6, np.float32)
            for i, tid in enumerate(tids):
                tr = cand[tid]
                for j, p in enumerate(dets):
                    if j in used_det:
                        continue
                    dp = math.hypot(det_foot[j][0] - tr["foot"][0],
                                   det_foot[j][1] - tr["foot"][1])
                    ds = abs(math.log(max(tr["h"], 1.0) / max(det_h[j], 1.0)))
                    cos = float(embs[j] @ tr["emb"]) if tr["emb"] is not None else 0.0
                    if dp > gate or ds > a.size_gate or cos < app_min:
                        continue
                    C[i, j] = dp / gate + 0.5 * ds + a.w_app * (1.0 - max(cos, 0.0))
            ri, ci = linear_sum_assignment(C)
            for kk, i in enumerate(ri):
                j = ci[kk]
                if j in used_det:
                    continue
                if C[i, j] < 1e5:
                    assign[j] = tids[i]
                    used_det.add(j)

        try_match(live_tids, a.app_thresh)
        try_match(zombie_tids, a.zombie_app)

        new_players = []
        for j, p in enumerate(dets):
            b = p["bbox"]
            foot = det_foot[j]
            h = det_h[j]
            if j in assign:
                tid = assign[j]
                tr = tracks[tid]
                # EMA 外观
                if tr["emb"] is None:
                    tr["emb"] = embs[j].copy()
                else:
                    tr["emb"] = (1 - 0.3) * tr["emb"] + 0.3 * embs[j]
                    tr["emb"] /= np.linalg.norm(tr["emb"]) + 1e-9
                tr["foot"] = foot
                tr["h"] = h
                tr["bbox"] = b
                tr["conf"] = p.get("conf", 0.0)
                tr["missed"] = 0
                tr["frames"].append(f.get("frame", 0))
            else:
                if p.get("conf", 0.0) >= a.new_conf:
                    tid = nxt
                    nxt += 1
                    tracks[tid] = {"foot": foot, "h": h, "bbox": b, "emb": embs[j].copy(),
                                   "conf": p.get("conf", 0.0), "missed": 0,
                                   "frames": [f.get("frame", 0)]}
                else:
                    tid = -1  # 低置信：不建轨迹，仅标注
            new_players.append({"track_id": tid, "bbox": b,
                                "conf": p.get("conf", 0.0)})

        for tid in cand:
            if tid not in assign.values():
                tracks[tid]["missed"] += 1

        out_frames.append({"frame": f.get("frame", 0), "file": fn,
                           "ball": f.get("ball"), "players": new_players})

    # 队色聚类（仅真实球员轨迹）
    real = [t for t, v in tracks.items()
            if len(v["frames"]) >= a.min_track and v["emb"] is not None]
    team_map = {}
    if len(real) >= a.k:
        X = np.stack([tracks[t]["emb"] for t in real])
        _, L = kmeans(X, a.k)
        for t, lab in zip(real, L):
            team_map[t] = int(lab)
        # 簇内/簇间余弦距离（应 簇内<<簇间）
        same = [float(1 - X[i] @ X[j]) for i in range(0, len(X), 5)
                for j in range(i + 1, len(X), 7) if L[i] == L[j]]
        diff = [float(1 - X[i] @ X[j]) for i in range(0, len(X), 5)
                for j in range(i + 1, len(X), 7) if L[i] != L[j]]
        if same and diff:
            print(f"[队色] k={a.k} 簇内余弦距离 {np.mean(same):.4f} / "
                  f"簇间 {np.mean(diff):.4f} / 比值 {np.mean(diff)/np.mean(same):.2f}×")
    for t in tracks:
        if t in team_map:
            tracks[t]["team"] = team_map[t]

    # 写回 team 标签
    for f in out_frames:
        for p in f["players"]:
            p["team"] = tracks.get(p["track_id"], {}).get("team", -1)

    os.makedirs(a.out, exist_ok=True)
    outp = Path(a.out) / "ball_tracks.json"
    json.dump(out_frames, open(outp, "w"), ensure_ascii=False, indent=1)
    if a.dump_emb:
        json.dump(emb_dump, open(Path(a.dump_emb), "w"), ensure_ascii=False)

    # 参数留痕：历史欠账是 stab/stab2/stab3 零留痕 ⇒「85ID/35帧」无法复现。
    # 这里把本次全部入参 + 帧率 + 源 + 时间戳写死，任何成绩可被第三方复跑。
    Path(a.out).mkdir(parents=True, exist_ok=True)
    json.dump({
        "script": "stabilize_tracks_v2.py",
        "argv": sys.argv[1:],
        "params": {k: v for k, v in vars(a).items() if k != "argv"},
        "fps": a.fps,
        "src_ball_tracks": str(a.ball_tracks),
        "imgdir": str(a.imgdir),
        "out": str(a.out),
        "n_frames": len(out_frames),
        "segment_seconds": round(len(out_frames) / a.fps, 2),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }, open(Path(a.out) / "run_meta.json", "w"), ensure_ascii=False, indent=2)

    # 稳定性统计（与基线同口径）
    tl = defaultdict(int)
    for f in out_frames:
        for p in f["players"]:
            if p["track_id"] > 0:
                tl[p["track_id"]] += 1
    lens = sorted(tl.values(), reverse=True)
    pf = [len([p for p in f["players"] if p["track_id"] > 0]) for f in out_frames]
    print(f"[稳定] distinct track_id={len(tl)} (基线 260) | "
          f"中位寿命={lens[len(lens)//2] if lens else 0} (基线 8) | "
          f"max={lens[0] if lens else 0}")
    print(f"[稳定] 轨迹≥{a.min_track}f: {sum(1 for v in lens if v>=a.min_track)} | "
          f"每帧球员 中位={int(np.median(pf))} 最大={max(pf)}")
    print(f"[out] {outp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
