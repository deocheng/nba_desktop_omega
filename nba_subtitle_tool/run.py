#!/usr/bin/env python3
"""CLI 入口：python run.py --video <视频路径> [--whisper medium] [--translator qwen2.5:14b]"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from src.pipeline import run  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="NBA 本地视频语音识别 → 中文字幕/文稿")
    ap.add_argument("--video", "-v", required=True, help="视频文件路径")
    ap.add_argument("--config", "-c", default=os.path.join(HERE, "config.yaml"))
    ap.add_argument("--whisper", help="覆盖 Whisper 模型 (tiny/base/small/medium/large-v3)")
    ap.add_argument("--translator", help="覆盖翻译模型 (Ollama 标签)")
    ap.add_argument("--backend", help="识别后端: fasterwhisper(默认) 或 whispercpp")
    ap.add_argument("--language", help="强制识别语言 (zh/en/fr…)；指定后跳过对该语言的翻译")
    ap.add_argument("--output", help="覆盖输出目录")
    args = ap.parse_args()

    if not os.path.exists(args.video):
        print(f"错误：视频不存在：{args.video}")
        sys.exit(1)

    overrides = {}
    if args.whisper:
        overrides["whisper"] = args.whisper
    if args.translator:
        overrides["translator"] = args.translator
    if args.backend:
        overrides["backend"] = args.backend
    if args.language:
        overrides["language"] = args.language

    run(args.video, config_path=args.config, output_dir=args.output, **overrides)


if __name__ == "__main__":
    main()
