#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
asr_batch.py  —  批量 ASR 战术笔记视频 -> 语义术语库
==================================================
- 模型只加载一次（循环复用），大幅提速
- 断点续跑：已存在 *_asr_<model>.json 且含 segments 则跳过
- 逐文件容错：单文件失败记日志继续，不中断整批
- 走 HF_ENDPOINT 镜像（启动时 export HF_ENDPOINT=https://hf-mirror.com）
- 输出：action_work/asr_transcripts/<原名>_asr_<model>.json
- 纪律：只忠实转写人声，不解读战术含义

用法：
  export HF_ENDPOINT=https://hf-mirror.com
  python engine/asr_batch.py [--model small|medium] [--limit N] [--only-sas]
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import glob
import json
import os
import subprocess
import sys
import time

from faster_whisper import WhisperModel

from common.nba_paths import data_file, tactics_data_file

FFMPEG = "/opt/homebrew/bin/ffmpeg"
NOTES_DIR = str(data_file("NBA战术笔记"))
OUT_DIR = str(tactics_data_file("action_work/asr_transcripts"))
os.makedirs(OUT_DIR, exist_ok=True)

SAS_HINTS = ["马刺", "文班", "文班亚马", "Wembanyama", "波波维奇", "Spurs",
             "ZipperBackdoor", "crossscreen"]


def collect_videos(only_sas):
    vids = []
    for root, _, files in os.walk(NOTES_DIR):
        for f in files:
            if f.lower().endswith((".mp4", ".mkv", ".mov")):
                p = os.path.join(root, f)
                if only_sas and not any(h.lower() in f.lower() for h in SAS_HINTS):
                    continue
                vids.append(p)
    return sorted(vids)


def extract_audio(video, wav):
    subprocess.run([FFMPEG, "-y", "-i", video, "-vn", "-ac", "1", "-ar", "16000",
                    "-f", "wav", wav], capture_output=True, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="small")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only-sas", action="store_true")
    a = ap.parse_args()

    vids = collect_videos(a.only_sas)
    if a.limit:
        vids = vids[:a.limit]
    print(f"[init] model={a.model} videos={len(vids)} only_sas={a.only_sas}")

    model = WhisperModel(a.model, device="cpu", compute_type="int8")
    done = skip = fail = 0
    t0 = time.time()
    for i, v in enumerate(vids, 1):
        base = os.path.splitext(os.path.basename(v))[0]
        out = os.path.join(OUT_DIR, f"{base}_asr_{a.model}.json")
        if os.path.exists(out):
            try:
                if json.load(open(out, encoding="utf-8")).get("segments"):
                    skip += 1
                    print(f"[{i}/{len(vids)}] SKIP (exists) {base}")
                    continue
            except Exception:
                pass
        wav = os.path.join("/tmp", base + ".wav")
        try:
            extract_audio(v, wav)
            segs, info = model.transcribe(
                wav, language="zh", word_timestamps=True, vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500), beam_size=5)
            segs = [{"start": round(s.start, 2), "end": round(s.end, 2),
                     "text": s.text.strip(),
                     "words": [{"start": round(w.start, 2), "end": round(w.end, 2),
                                "word": w.word} for w in (s.words or [])]}
                    for s in segs]
            json.dump({"video": v, "model": a.model,
                       "meta": {"language": info.language,
                                "probability": round(info.language_probability, 3),
                                "duration": round(info.duration, 1)},
                       "segments": segs}, open(out, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
            done += 1
            print(f"[{i}/{len(vids)}] OK {base} ({len(segs)} segs, {info.duration:.0f}s)")
        except Exception as e:
            fail += 1
            print(f"[{i}/{len(vids)}] FAIL {base}: {repr(e)[:200]}")
        finally:
            if os.path.exists(wav):
                os.remove(wav)
    print(f"\n[done] {time.time()-t0:.0f}s | ok={done} skip={skip} fail={fail} / {len(vids)}")
    print(f"  -> {OUT_DIR}")


if __name__ == "__main__":
    main()
