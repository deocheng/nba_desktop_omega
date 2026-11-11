#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_sas_det_review_clips —— 把 sas_det 400 帧对应的视频段剪出来供人工核对标注。

源: <DATA_ROOT>/比赛录像/2024-25/24-25常规赛/2025.02/马刺vs活塞/02.22 活塞vs马刺 第一节.mp4
抽帧口径: -ss 60 -t 40 fps=10 -> action_work/sas_det/f00001..f00400（f00001 = 视频 60.04s）。
DELTA=1: -ss 60 解码后第 2 帧(0-based n=1) = f00001。

产出 (action_work/validate/sas_det_review/):
  sas_det_review_25fps.mp4          原速 25fps 全帧率, 烧录 f 编号, 含音频 (~40s)
  sas_det_review_10fps_aligned.mp4  10fps, 每帧=sheet 一帧 f 编号 1:1, 含音频 (40s)
  sas_det_review_slow05x.mp4        0.5x 慢速(帧重复), 烧录 f 编号, 无音频 (~80s)

烧录: 左下角黄字黑底 "f00123/400" —— 与标注 app 的帧号一一对应。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import data_file, tactics_data_file

_ap = argparse.ArgumentParser()
_ap.add_argument("--clip", default="sas_det")
_ap.add_argument("--src", default=str(data_file("比赛录像/2024-25/24-25常规赛/2025.02/马刺vs活塞/02.22 活塞vs马刺 第一节.mp4")))
_ap.add_argument("--ss", type=int, default=60, help="抽帧起点秒（须与当时 ffmpeg -ss 一致）")
_ap.add_argument("--nf", type=int, default=400)
_a, _ = _ap.parse_known_args()
SRC = _a.src
SS = _a.ss
NF = _a.nf
ROOT = Path(str(tactics_data_file("")))
FR = ROOT / "action_work" / _a.clip
OUT = ROOT / "action_work" / "validate" / f"{_a.clip}_review"
FF = "/opt/homebrew/bin/ffmpeg"
W, H, FPS = 1920, 1080, 25
DELTA = 1
FRM_SZ = W * H * 3


def read_frame(p):
    buf = b""
    while len(buf) < FRM_SZ:
        c = p.stdout.read(FRM_SZ - len(buf))
        if not c:
            return None
        buf += c
    return np.frombuffer(buf, np.uint8).reshape(H, W, 3)


def burn(img, txt):
    org = (24, H - 40)
    (tw, th), bl = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 1.5, 3)
    cv2.rectangle(img, (org[0] - 10, org[1] - th - 16), (org[0] + tw + 10, org[1] + bl + 10),
                  (0, 0, 0), -1)
    cv2.putText(img, txt, org, cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 255, 255), 3, cv2.LINE_AA)


def enc_proc(out_name, fps, audio):
    cmd = [FF, "-hide_banner", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "pipe:0"]
    if audio:
        cmd += ["-ss", f"{SS}.0", "-i", SRC, "-map", "0:v", "-map", "1:a",
                "-c:a", "aac", "-b:a", "128k", "-shortest"]
    else:
        cmd += ["-an"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(OUT / out_name)]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


def decode_pipe():
    return subprocess.Popen(
        [FF, "-hide_banner", "-loglevel", "error", "-ss", str(SS), "-i", SRC,
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "pipe:1"],
        stdout=subprocess.PIPE)


def main():
    CL = _a.clip
    OUT.mkdir(parents=True, exist_ok=True)

    # ---- A: 原速 25fps + C: 0.5x 慢速（同一路解码流）----
    dec = decode_pipe()
    CL = _a.clip
    pa = enc_proc(f"{CL}_review_25fps.mp4", FPS, audio=True)
    pc = enc_proc(f"{CL}_review_slow05x.mp4", FPS, audio=False)
    n_written = 0
    n = 0  # 1-based 解码帧计数（-ss 60 起第 1 帧 = n=1）
    while True:
        raw = read_frame(dec)
        if raw is None:
            break
        n += 1
        if n <= DELTA:
            continue  # 跳过 f00001 之前的帧
        jp = n - DELTA - 1  # 0-based, jp=0 即 f00001
        if jp >= 999:       # f400 覆盖到 jp=998 (99.96s)
            break
        fnum = min(int(jp * 0.4) + 1, NF)
        img = raw.copy()
        burn(img, f"f{fnum:05d}/{NF}")
        pa.stdin.write(img.tobytes())
        pc.stdin.write(img.tobytes())
        pc.stdin.write(img.tobytes())  # 帧重复 -> 0.5x
        n_written += 1
    dec.kill()
    pa.stdin.close(); pa.wait()
    pc.stdin.close(); pc.wait()
    print(f"[A/C] 写出 {n_written} 帧 (n=0..{n_written-1}) -> 25fps + slow05x", flush=True)

    # ---- B: 10fps 对齐版 = 直接编码 400 张 sheet 源帧 (1:1) ----
    pb = enc_proc(f"{CL}_review_10fps_aligned.mp4", 10, audio=True)
    for k in range(1, NF + 1):
        img = cv2.imread(str(FR / f"f{k:05d}.jpg"))
        if img is None:
            print(f"WARN f{k:05d}.jpg 缺失", flush=True)
            continue
        burn(img, f"f{k:05d}/{NF}")
        pb.stdin.write(img.tobytes())
    pb.stdin.close(); pb.wait()
    print(f"[B] 写出 {NF} 帧 -> 10fps_aligned", flush=True)


if __name__ == "__main__":
    sys.exit(main())
