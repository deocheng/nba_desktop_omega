#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
asr_probe.py  —  ASR 探针（单视频）
===================================
把战术笔记视频的人声讲解转写成带时间戳文字稿。
- ffmpeg 抽 16k 单声道 wav
- faster-whisper (small, zh, CPU int8) 转写，word_timestamps + VAD 过滤静音
- 输出 JSON: segments[{start,end,text,words[{start,end,word}]}]

纪律：只忠实转写人声，不解读/不猜测战术含义。
用法：python engine/asr_probe.py <video.mp4> [--model small|medium]
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

FFMPEG = "/opt/homebrew/bin/ffmpeg"
VENV = str(Path.home() / ".workbuddy/binaries/python/envs/action05/bin/python")


def extract_audio(video, wav):
    cmd = [FFMPEG, "-y", "-i", video, "-vn", "-ac", "1", "-ar", "16000",
           "-f", "wav", wav]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + r.stderr[-500:])
    return wav


def transcribe(wav, model_size):
    from faster_whisper import WhisperModel
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segs, info = model.transcribe(
        wav, language="zh", word_timestamps=True,
        vad_filter=True, vad_parameters=dict(min_silence_duration_ms=500),
        beam_size=5,
    )
    out = []
    for s in segs:
        words = [{"start": round(w.start, 2), "end": round(w.end, 2), "word": w.word}
                 for w in (s.words or [])]
        out.append({
            "start": round(s.start, 2), "end": round(s.end, 2),
            "text": s.text.strip(), "words": words,
        })
    return out, {"language": info.language, "probability": round(info.language_probability, 3),
                 "duration": round(info.duration, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--model", default="small")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    base = os.path.splitext(os.path.basename(a.video))[0]
    tmp = tempfile.gettempdir()
    wav = os.path.join(tmp, base + ".wav")
    print(f"[1/3] extract audio: {a.video}")
    extract_audio(a.video, wav)
    print(f"[2/3] transcribe (model={a.model}) ...")
    segs, meta = transcribe(wav, a.model)
    out = {"video": a.video, "model": a.model, "meta": meta, "segments": segs}
    out_path = a.out or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", "action_work", "asr_probe", base + f"_asr_{a.model}.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[3/3] done: {len(segs)} segments, {meta}")
    print(f"  -> {out_path}")
    print("\n=== 中文转写抽样（前 8 段）===")
    for s in segs[:8]:
        print(f"  [{s['start']:.1f}-{s['end']:.1f}s] {s['text']}")


if __name__ == "__main__":
    main()
