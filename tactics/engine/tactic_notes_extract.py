#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tactic_notes_extract.py — 从《NBA战术笔记》视频里截取「完整战术」片段
=====================================================================
背景（老程 2026-09-29 指令）：
  「战术笔记里的片段都是战术，你可以自己截取完整战术然后对比战术解析」
  ⇒ 战术笔记视频里嵌入的**实战片段本身**就是战术（有讲解作为真值），
    把它截出来 → 跑我们的分析 → 与当期讲解对照，才是真正的验证。

本脚本只做「截取」这一件事（不做任何战术判断）：
  1) ffmpeg 按 --ss/--to 抽取帧(f%05d.jpg, 从 1 开始, 与既有 clip 命名一致)；
  2) 写 frames.json（segment_detect_track.py 的输入契约: [{idx,t,path}]）；
  3) 写 meta.json（来源视频/期号/战术名/时间窗/fps/帧数/ffprobe 决议，供追溯）；
  4) 可选写 preview.mp4（自证用，不改动分析）。

用法:
  tactic_notes_extract.py --video "<DATA_ROOT>/NBA战术笔记/第24期：….mp4" \
      --ss 82 --to 103 --fps 10 --ep ep24 --tactic "cross_screen" \
      --out action_work/tactic_notes_clips/ep24_crossscreen
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import subprocess
import sys
from pathlib import Path

from common.nba_paths import tactics_data_file

FFMPEG = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"
ROOT = Path(str(tactics_data_file("")))


def probe(video: Path):
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate,duration",
         "-of", "json", str(video)], capture_output=True, text=True).stdout
    s = json.loads(out)["streams"][0]
    return {"w": s["width"], "h": s["height"], "fps": s["r_frame_rate"], "dur": s.get("duration")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--ss", type=float, required=True, help="起点(秒)")
    ap.add_argument("--to", type=float, required=True, help="终点(秒)")
    ap.add_argument("--fps", type=float, default=10.0, help="抽帧帧率")
    ap.add_argument("--ep", default="", help="期号(如 ep24)")
    ap.add_argument("--tactic", default="", help="当期战术名(来自文件名/标题, 仅记录, 不作判断)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--preview", action="store_true", help="额外写 preview.mp4")
    a = ap.parse_args()

    video = Path(a.video)
    if not video.exists():
        sys.exit(f"视频不存在: {video}")
    outs = Path(a.out)
    if not outs.is_absolute():
        outs = ROOT / a.out
    if not outs.exists():
        outs.mkdir(parents=True)
    frames_dir = outs / "frames"
    if not frames_dir.exists():
        frames_dir.mkdir(parents=True)

    pr = probe(video)
    n_expected = int(round((a.to - a.ss) * a.fps))
    cmd = [FFMPEG, "-v", "error", "-y", "-ss", str(a.ss), "-to", str(a.to), "-i", str(video),
           "-vf", f"fps={a.fps}", "-q:v", "3", str(frames_dir / "f%05d.jpg")]
    subprocess.run(cmd, check=True)
    frames = sorted(frames_dir.glob("f*.jpg"))
    if not frames:
        sys.exit("抽帧为空")

    t0 = a.ss
    recs = []
    for i, p in enumerate(frames):
        recs.append({"idx": i, "t": round(t0 + i / a.fps, 3), "path": str(p)})
    (outs / "frames.json").write_text(json.dumps(recs, ensure_ascii=False, indent=2), encoding="utf-8")

    meta = {
        "source_video": str(video),
        "source_name": video.name,
        "episode": a.ep,
        "tactic_name_from_title": a.tactic,
        "window_sec": [a.ss, a.to],
        "out_fps": a.fps,
        "n_frames": len(frames),
        "n_expected": n_expected,
        "src_video": pr,
        "note": "仅截取; 不作战术判断。tactic_name_from_title 来自当期标题, 用作对照真值, 非本工具结论。",
    }
    (outs / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    if a.preview:
        subprocess.run([FFMPEG, "-v", "error", "-y", "-framerate", str(a.fps),
                        "-i", str(frames_dir / "f%05d.jpg"),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        str(outs / "preview.mp4")], check=True)

    print(f"[extract] {video.name}")
    print(f"  窗口 {a.ss}-{a.to}s @ {a.fps}fps → {len(frames)} 帧 (期望~{n_expected})  源 {pr['w']}x{pr['h']}@{pr['fps']}")
    print(f"  输出 {outs}  (frames.json/meta.json{'/preview.mp4' if a.preview else ''})")


if __name__ == "__main__":
    main()
