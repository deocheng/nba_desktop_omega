#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
court_filter.py — 用「球场地面掩膜」把追踪到的**场上球员**从 观众/替补席 中筛出来（A4.60）
=========================================================================================
背景: 广播宽景镜头里有**大量观众/替补**(实测每帧 27–48 个 person, 场上仅 ~10) →
      配对几何被污染 ⇒ 掩护原语大量假阳性。
追踪器自带的「运动持久性」判据假设**固定机位**(观众不动); 广播**移动机位**下静止观众也产生
大幅视在位移 ⇒ 该判据失效。**球场地面掩膜**与相机运动无关(地板永远在场上), 故更稳。

方法: 每帧算「地板掩膜」(木地板亮黄棕 + 油漆区) → 最大连通域 → 凸包填洞 →
      人在其**脚点**落在掩膜内 = 场上。按**轨迹**聚合(脚点在场上帧占比 ≥ min_frac 才保留)。

🔴 局限: 远端边线的替补/教练坐在**地板区域内**(在界内地板延伸处) ⇒ 掩膜**筛不掉**, 需另法。
用法: court_filter.py <seg_dir> [--frame N]   # 打印统计并可视化 /tmp/court_filter_*.png
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

# 地板色: 木地板(亮黄棕) + 油漆区(紫/蓝等深色块) —— NBA 绝大多数地板是亮木
WOOD_LO, WOOD_HI = (10, 45, 140), (38, 255, 255)
PAINT_LO, PAINT_HI = (110, 60, 70), (170, 255, 255)
# 掩膜「合理面积」区间(占画面比)。落在区间外 = 该判据不可靠 → 换判据/跳过
# 实测: 宽景镜头地板可占 0.5–0.7; 太小(<0.12)=只抠到零星色块, 太大(>0.80)=把观众区也吞了。
AREA_LO, AREA_HI = 0.12, 0.78


def _largest_fill(m):
    """保留最大连通域, 并用其外轮廓填充(含洞), 不做凸包(凸包会过度扩张吞掉观众区)。"""
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((31, 31), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((15, 15), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    if n <= 1:
        return np.zeros_like(m)
    big = 1 + int(np.argmax(st[1:, 4]))
    m = np.where(lab == big, 255, 0).astype(np.uint8)
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = np.zeros_like(m)
    if cnts:
        cv2.drawContours(out, [max(cnts, key=cv2.contourArea)], -1, 255, -1)
    return out


def _mask_color(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    wood = cv2.inRange(hsv, WOOD_LO, WOOD_HI)
    paint = cv2.inRange(hsv, PAINT_LO, PAINT_HI)
    return _largest_fill(cv2.bitwise_or(wood, paint))


def _mask_texture(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    dens = cv2.boxFilter(cv2.Canny(gray, 60, 160), -1, (41, 41), normalize=True)
    return _largest_fill(cv2.inRange(dens, 0, 12))


def court_mask(img):
    """返回 (掩膜, 判据名)。优先色判据(亮木/油漆), 面积不合理则退回纹理判据;
    两者都不合理 → 返回 None(调用方**跳过过滤**, 绝不误删全场)。"""
    H, W = img.shape[:2]
    for name, fn in (("color", _mask_color), ("texture", _mask_texture)):
        m = fn(img)
        frac = (m > 0).mean()
        if AREA_LO <= frac <= AREA_HI:
            return m, name
    return None, "skip"


def _foot(box):
    return int((box[0] + box[2]) / 2), int(box[3])


def on_court_track_ids(tracks_json, frames_dir, min_frac=0.5, visualize=None):
    """按轨迹聚合: 脚点落在球场掩膜的帧占比 ≥ min_frac 的轨迹保留。
    返回 (keep_ids set, per_track dict)。"""
    tr = json.load(open(tracks_json, encoding="utf-8"))
    frames_dir = Path(frames_dir)
    fid2on = {}       # frame idx -> {track_id: bool}
    masks = {}
    # 用文件序号 = idx+1 命名约定(与抽帧一致)
    files = sorted(frames_dir.glob("f*.jpg"))
    for fr in tr["frames"]:
        idx = fr["idx"]
        if idx >= len(files):
            continue
        img = cv2.imread(str(files[idx]))
        if img is None:
            continue
        m, _mode = court_mask(img)
        masks[idx] = m
        fid2on[idx] = {}
        if m is None:            # 掩膜不可靠 → 该帧不过滤(视为全在场)
            for p in fr.get("players", []):
                fid2on[idx][int(p["id"])] = True
            continue
        H, W = m.shape
        for p in fr.get("players", []):
            fx, fy = _foot(p["box"])
            inside = 0 <= fx < W and 0 <= fy < H and m[min(fy, H - 1), min(fx, W - 1)] > 0
            fid2on[idx][int(p["id"])] = bool(inside)

    per = {}
    for fr in tr["frames"]:
        idx = fr["idx"]
        for p in fr.get("players", []):
            tid = int(p["id"])
            d = per.setdefault(tid, {"n": 0, "on": 0})
            d["n"] += 1
            d["on"] += 1 if fid2on.get(idx, {}).get(tid) else 0
    keep = {tid for tid, d in per.items() if d["n"] and d["on"] / d["n"] >= min_frac}
    if visualize is not None:
        idx = visualize if visualize in masks else next(iter(masks))
        img = cv2.imread(str(files[idx]))
        vis = img.copy()
        if masks[idx] is not None:
            vis = cv2.addWeighted(cv2.merge([masks[idx]] * 3), 0.25, img, 0.75, 0)
        n_on = n_off = 0
        for p in tr["frames"][idx].get("players", []):
            x0, y0, x1, y1 = p["box"]
            on = fid2on[idx].get(int(p["id"]))
            n_on += on; n_off += (not on)
            cv2.rectangle(vis, (int(x0), int(y0)), (int(x1), int(y1)),
                          (0, 255, 0) if on else (0, 0, 255), 2)
        cv2.imwrite("/tmp/court_filter_vis.png", vis)
        print(f"[vis] f{idx}: on={n_on} off={n_off} → /tmp/court_filter_vis.png")
    return keep, per


def filter_tracks_json(tracks_json, frames_dir, out_json, min_frac=0.5):
    """逐帧剔除「脚点不在球场掩膜内」的检出, 并把整条基本不在场上的轨迹删掉。
    写出新的 tracks.json(同 schema)。返回统计。"""
    tr = json.load(open(tracks_json, encoding="utf-8"))
    frames_dir = Path(frames_dir)
    files = sorted(frames_dir.glob("f*.jpg"))
    on_frac = {}
    new_frames = []
    dropped_det = kept_det = 0
    for fr in tr["frames"]:
        idx = fr["idx"]
        if idx >= len(files):
            new_frames.append(fr); continue
        img = cv2.imread(str(files[idx]))
        if img is None:
            new_frames.append(fr); continue
        m, mode = court_mask(img)
        if m is None:                       # 掩膜不可靠 → 本帧不过滤
            new_frames.append(fr); kept_det += len(fr.get("players", [])); continue
        H, W = m.shape
        keep_pl = []
        for p in fr.get("players", []):
            fx, fy = _foot(p["box"])
            inside = 0 <= fx < W and 0 <= fy < H and m[min(fy, H - 1), min(fx, W - 1)] > 0
            tid = int(p["id"])
            d = on_frac.setdefault(tid, [0, 0])
            d[1] += 1; d[0] += 1 if inside else 0
            if inside:
                keep_pl.append(p); kept_det += 1
            else:
                dropped_det += 1
        nf = dict(fr); nf["players"] = keep_pl
        new_frames.append(nf)
    # 整条基本不在场上的轨迹删掉
    bad = {t for t, (a, b) in on_frac.items() if b and a / b < min_frac}
    if bad:
        for nf in new_frames:
            nf["players"] = [p for p in nf["players"] if int(p["id"]) not in bad]
    tr["frames"] = new_frames
    tr["court_filter"] = {"kept_detections": kept_det, "dropped_detections": dropped_det,
                          "dropped_tracks": len(bad), "min_frac": min_frac}
    Path(out_json).write_text(json.dumps(tr, ensure_ascii=False), encoding="utf-8")
    return tr["court_filter"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("seg_dir")
    ap.add_argument("--frame", type=int, default=None)
    ap.add_argument("--min-frac", type=float, default=0.5)
    a = ap.parse_args()
    seg = Path(a.seg_dir)
    keep, per = on_court_track_ids(seg / "tracks.json", seg / "frames",
                                   a.min_frac, visualize=a.frame)
    n_on = len(keep)
    tot = len(per)
    import statistics as S
    # 每帧保留人数
    tr = json.load(open(seg / "tracks.json", encoding="utf-8"))
    per_frame = [sum(1 for p in fr.get("players", []) if int(p["id"]) in keep) for fr in tr["frames"]]
    print(f"[court_filter] {seg.name}: 轨迹 {tot} → 保留 {n_on} (场上占比≥{a.min_frac})")
    print(f"  每帧场上人数: min={min(per_frame)} med={S.median(per_frame):.0f} max={max(per_frame)}")


if __name__ == "__main__":
    main()
