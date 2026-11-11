#!/usr/bin/env python3
"""把影片时间轴对齐到比赛读秒表（game clock）—— 扩样本的**唯一**前置基建。

为什么必须做这件事
------------------
里程碑 03 的致命错误就是**手写事件时刻**（4 个事件里 2 个错 16.4 / 19.7 秒）。
根因是没有一条可审计的「影片时间 → 比赛读秒」映射，只能靠人的印象填数字。
本脚本把这个映射**物化**成可复核的产物：
  1. 抽全片帧 + 镜头切分（找到剪辑断点，断点两侧映射不连续）
  2. 在固定网格上裁出读秒表 ROI，拼成对照表图（供**目视读数**，不是 OCR）
  3. 读数 → 单调分段线性映射 → **用已知真值表反向校验**

为什么用「目视对照表」而不是自动 OCR
------------------------------------
读秒表字体固定但背景（观众席）干扰大、且 <60s 会从 `M:SS` 切到 `SS.d`（位数变化）。
自动 OCR 需要额外一轮「OCR 自身的精度验证」，而验证本身就等价于目视抽样。
直接目视读数 + 保存对照表图（可追溯）+ 单调性/已知真值双重校验，链路更短、更可审计。

用法
----
  clock_align.py extract <video> <outdir> [--fps 2]
  clock_align.py cuts    <outdir> [--gray-thr 0.16] [--hist-thr 0.015]
  clock_align.py sheets  <outdir> [--every-sec 10] [--per-sheet 16] [--cols 2]

输出
----
  <outdir>/f%05d.jpg           全片帧
  <outdir>/frames.json         [{idx,t,path}]
  <outdir>/cuts.json           镜头切分明细
  <outdir>/anchors.json        待读数锚点清单（t → 裁剪图路径 + 拼图坐标）
  <outdir>/sheet_*.png         读秒对照表图（目视读数用）
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image

FFMPEG = "/opt/homebrew/bin/ffmpeg"

# 读秒表 ROI（1920×1080 转播画面，左下角），排除右侧红色进攻时限框。
# 标定依据：seg_possession 的 87 帧已知读数，逐帧目视确认边界不切字。
CLOCK_ROI = (330, 870, 484, 928)


# ---------------------------------------------------------------- extract
def cmd_extract(a) -> int:
    os.makedirs(a.outdir, exist_ok=True)
    for f in os.listdir(a.outdir):
        if f.startswith("f") and f.endswith(".jpg"):
            os.remove(os.path.join(a.outdir, f))
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error",
           "-i", a.video, "-vf", f"fps={a.fps}",
           "-q:v", "3", "-y", os.path.join(a.outdir, "f%05d.jpg")]
    subprocess.run(cmd, check=True)
    files = sorted(f for f in os.listdir(a.outdir) if f.startswith("f") and f.endswith(".jpg"))
    frames = [{"idx": i, "t": round(i / a.fps, 4),
               "path": os.path.join(a.outdir, f)} for i, f in enumerate(files)]
    with open(os.path.join(a.outdir, "frames.json"), "w") as fh:
        json.dump(frames, fh, ensure_ascii=False, indent=1)
    w = Image.open(frames[0]["path"]).size if frames else None
    print(f"[extract] {len(frames)} 帧 @ {a.fps}fps  尺寸={w}")
    print(f"[extract] 时长约 {len(frames)/a.fps:.1f}s -> {os.path.join(a.outdir,'frames.json')}")
    return 0


# ---------------------------------------------------------------- cuts
def _sig(path: str, size: int = 128):
    im = Image.open(path).convert("RGB").resize((size, size * 9 // 16), Image.BILINEAR)
    arr = np.asarray(im, dtype=np.float32)
    gray = arr.mean(axis=2).reshape(-1) / 255.0
    hist = np.concatenate([
        np.histogram(arr[:, :, c], bins=32, range=(0, 255), density=True)[0]
        for c in range(3)
    ])
    return gray, hist


def cmd_cuts(a) -> int:
    frames = json.load(open(os.path.join(a.outdir, "frames.json")))
    sigs = [_sig(f["path"]) for f in frames]
    rows, cuts = [], []
    for i in range(1, len(sigs)):
        dg = float(np.abs(sigs[i][0] - sigs[i - 1][0]).mean())
        dh = float(np.abs(sigs[i][1] - sigs[i - 1][1]).sum() / 6.0)
        hit = dg > a.gray_thr and dh > a.hist_thr
        if hit:
            cuts.append(i)
        rows.append({"frame": i, "t": frames[i]["t"],
                     "gray_d": round(dg, 4), "hist_d": round(dh, 4), "cut": hit})
    # 按灰度差排序输出 Top-20，便于人工判断「阈值是否漏掉真剪辑」
    top = sorted(rows, key=lambda r: -r["gray_d"])[:20]
    print(f"[cuts] 阈值 gray>{a.gray_thr} AND hist>{a.hist_thr} -> 检出 {len(cuts)} 个")
    for i in cuts:
        r = rows[i - 1]
        print(f"    t={r['t']:>8.2f}s  gray={r['gray_d']:.4f} hist={r['hist_d']:.4f}")
    print("[cuts] 灰度差 Top-10（用于判断是否漏检）：")
    for r in top[:10]:
        flag = "✓cut" if r["cut"] else "     "
        print(f"    t={r['t']:>8.2f}s  gray={r['gray_d']:.4f} hist={r['hist_d']:.4f} {flag}")
    with open(os.path.join(a.outdir, "cuts.json"), "w") as fh:
        json.dump({"gray_thr": a.gray_thr, "hist_thr": a.hist_thr,
                   "cuts": cuts, "detail": rows}, fh, ensure_ascii=False, indent=1)
    print(f"[out] {a.outdir}/cuts.json")
    return 0


# ---------------------------------------------------------------- sheets
def cmd_sheets(a) -> int:
    frames = json.load(open(os.path.join(a.outdir, "frames.json")))
    fps = 1.0 / (frames[1]["t"] - frames[0]["t"])
    step = max(1, int(round(a.every_sec * fps)))
    picks = frames[::step]
    if a.t_lo is not None:
        picks = [f for f in picks if f["t"] >= a.t_lo]
    if a.t_hi is not None:
        picks = [f for f in picks if f["t"] <= a.t_hi]

    # 统一裁剪尺寸（ROI 在 x 上留一点余量，兼容 <60s 时的 SS.d 格式）
    crops = []
    for f in picks:
        im = Image.open(f["path"]).crop(CLOCK_ROI)
        crops.append((f["t"], im))

    cw, ch = crops[0][1].size
    Z = a.zoom
    label_h = 26
    per = a.per_sheet
    sheets = [crops[i:i + per] for i in range(0, len(crops), per)]
    anchors = []
    for si, group in enumerate(sheets):
        cols = a.cols
        rows = (len(group) + cols - 1) // cols
        W = cols * cw * Z
        H = rows * (ch * Z + label_h)
        canvas = Image.new("RGB", (W, H), (18, 18, 18))
        for k, (t, im) in enumerate(group):
            r, c = divmod(k, cols)
            x = c * cw * Z
            y = r * (ch * Z + label_h)
            canvas.paste(im.resize((cw * Z, ch * Z), Image.LANCZOS), (x, y + label_h))
            anchors.append({"t": t, "sheet": si, "k": k,
                            "cell": [x, y + label_h, cw * Z, ch * Z]})
        out = os.path.join(a.outdir, f"sheet_{si:02d}.png")
        canvas.save(out)
        print(f"[sheet] {out}  {len(group)} 格  {canvas.size}  "
              f"t={group[0][0]:.1f}..{group[-1][0]:.1f}s")

    meta = {"roi": CLOCK_ROI, "zoom": Z, "cols": a.cols, "every_sec": a.every_sec,
            "n_anchors": len(anchors), "n_sheets": len(sheets), "anchors": anchors,
            "note": "每个锚点的 t 就是影片时间；读数填入 clock_sec 后用 fit 子命令拟合"}
    with open(os.path.join(a.outdir, "anchors.json"), "w") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)
    print(f"[out] {a.outdir}/anchors.json  ({len(anchors)} 锚点 / {len(sheets)} 表)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("extract")
    e.add_argument("video")
    e.add_argument("outdir")
    e.add_argument("--fps", type=float, default=2.0)
    e.set_defaults(func=cmd_extract)

    c = sub.add_parser("cuts")
    c.add_argument("outdir")
    c.add_argument("--gray-thr", type=float, default=0.16)
    c.add_argument("--hist-thr", type=float, default=0.015)
    c.set_defaults(func=cmd_cuts)

    s = sub.add_parser("sheets")
    s.add_argument("outdir")
    s.add_argument("--every-sec", type=float, default=10.0)
    s.add_argument("--per-sheet", type=int, default=16)
    s.add_argument("--cols", type=int, default=2)
    s.add_argument("--zoom", type=int, default=2)
    s.add_argument("--t-lo", type=float, default=None)
    s.add_argument("--t-hi", type=float, default=None)
    s.set_defaults(func=cmd_sheets)

    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
