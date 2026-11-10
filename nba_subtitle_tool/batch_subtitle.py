#!/usr/bin/env python3
"""批量给某个目录下所有视频配字幕。

- 中文源视频：本地识别 → 直接出中文字幕/文稿（繁→简统一），跳过翻译。
- 英文/法文源视频：识别 → 本地大模型翻译 → 中文字幕/文稿。
输出 SRT / Markdown / JSON 与视频同目录（同名），播放器（VLC/Infuse 等）可自动加载字幕。
已存在 .srt 的视频会跳过，支持断点续跑。
"""
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from src.pipeline import run  # noqa: E402

VIDEO_EXTS = ("*.mp4", "*.mkv", "*.ts", "*.mov", "*.avi", "*.webm")
BASE = "/Volumes/12T/NBA/篮球训练"
CONFIG = os.path.join(HERE, "config.yaml")


def main():
    videos = []
    for ext in VIDEO_EXTS:
        videos += glob.glob(os.path.join(BASE, ext))
    videos = sorted(set(videos))
    print(f"找到 {len(videos)} 个视频")

    done = skipped = failed = 0
    for i, v in enumerate(videos, 1):
        name = os.path.splitext(os.path.basename(v))[0]
        srt = os.path.join(BASE, f"{name}.srt")
        if os.path.exists(srt):
            print(f"[{i}/{len(videos)}] 跳过（已存在字幕）：{os.path.basename(v)}")
            skipped += 1
            continue
        print(f"\n===== [{i}/{len(videos)}] {os.path.basename(v)} =====")
        try:
            # 自动检测语言 + 按识别内容判定是否翻译（中文源直出、英文段翻译，自动适配混排）
            res = run(v, config_path=CONFIG, output_dir=BASE)
            print(f"  完成：{res['segments']} 段，字幕 {res['srt']}")
            done += 1
        except Exception as e:
            print(f"  !! 处理失败：{e}")
            failed += 1

    print(f"\n全部处理完毕：完成 {done}，跳过 {skipped}，失败 {failed}。")


if __name__ == "__main__":
    main()
