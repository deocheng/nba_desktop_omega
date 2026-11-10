#!/usr/bin/env python3
"""字幕 / 文本转换命令行入口（供 web.py 以子进程调用，与 run.py 同构）。

用法：
  # VTT → SRT（纯格式，无需模型）
  python convert_cli.py --input a.vtt --mode vtt2srt --out-srt a.srt

  # 英文/法文字幕或文本 → 中文
  python convert_cli.py --input a.srt --mode en2zh \
      --out-srt a.zh.srt --out-md a.zh.md --translator qwen2.5:7b
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from src import convert as _convert
from src.pipeline import load_config


def main():
    ap = argparse.ArgumentParser(description="字幕/文本转换工具")
    ap.add_argument("--input", required=True, help="输入文件路径")
    ap.add_argument("--mode", required=True, choices=["vtt2srt", "en2zh"])
    ap.add_argument("--out-srt", default="", help="VTT→SRT 或 en2zh 的中文 SRT 输出路径")
    ap.add_argument("--out-md", default="", help="en2zh 的中文 Markdown 输出路径")
    ap.add_argument("--translator", default="", help="en2zh 使用的 Ollama 模型")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    cfg = load_config(args.config)
    tcfg = cfg.get("translation", {})
    glossary_path = os.path.join(HERE, tcfg.get("glossary_path", "glossary.json"))
    model = args.translator or cfg["models"].get("translator")

    if args.mode == "vtt2srt":
        if not args.out_srt:
            stem = os.path.splitext(os.path.basename(args.input))[0]
            args.out_srt = os.path.join(os.path.dirname(args.input) or ".", stem + ".srt")
        srt = _convert.vtt_to_srt(args.input)
        with open(args.out_srt, "w", encoding="utf-8") as f:
            f.write(srt)
        print(f"[完成] VTT→SRT，已写入 {args.out_srt}（{len(srt.splitlines())} 行）")
        return

    # en2zh
    if not args.out_md:
        stem = os.path.splitext(os.path.basename(args.input))[0]
        args.out_md = os.path.join(os.path.dirname(args.input) or ".", stem + ".zh.md")
    res = _convert.translate_file_to_chinese(
        args.input,
        output_dir=os.path.dirname(args.out_md) or ".",
        translator_model=model,
        glossary_path=glossary_path,
        srt_out=args.out_srt or None,
        md_out=args.out_md or None,
        temperature=tcfg.get("temperature", 0.1),
        base_url=tcfg.get("ollama_base_url", "http://localhost:11434"),
        workers=tcfg.get("workers", 4),
        cache_dir=os.path.join(HERE, "work"),
    )
    print(f"[完成] 已翻译 {res['segments']} 段（{res['kind']}），输出：{res['wrote']}")


if __name__ == "__main__":
    main()
