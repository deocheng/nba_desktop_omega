"""语音识别模块：支持两种本地后端，默认 faster-whisper（有 3.13 预编译 wheel，
Apple Silicon 上很快，时间戳直接为秒）；可选 whisper.cpp（whisper-cpp-python，
Metal 加速、速度最快，但需本机编译）。均支持逐段自动语言检测，处理英/法夹杂。

重依赖（faster_whisper / whispercpp）延迟导入，便于缺模型环境下仍可 import 与单测。
"""
import json
import os


def _normalize_segments(raw_segments, backend: str = "fasterwhisper", language_hint=None):
    """规整为统一格式：[{start, end, text, lang, words:[{start,end,word}]}]，单位秒。
    - faster-whisper：start/end/words 直接为秒。
    - whispercpp：t0/t1 与 words 为厘秒，需 /100。
    """
    if backend == "whispercpp":
        def cv(v):
            return v / 100.0 if v is not None else None
    else:
        def cv(v):
            return v

    out = []
    for seg in raw_segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        start = seg.get("start")
        end = seg.get("end")
        # whispercpp 段级时间可能在 t0/t1
        if start is None:
            start = cv(seg.get("t0"))
        if end is None:
            end = cv(seg.get("t1"))
        words = []
        for w in seg.get("words", []) or []:
            ws = cv(w.get("start"))
            we = cv(w.get("end"))
            wd = w.get("word", "").strip()
            if wd:
                words.append({"start": ws, "end": we, "word": wd})
        if words:
            if start is None:
                start = words[0]["start"]
            if end is None:
                end = words[-1]["end"]
        out.append({
            "start": start, "end": end, "text": text,
            "lang": language_hint or seg.get("language"), "words": words,
        })
    return out


def _transcribe_faster(wav_path, model, language, n_threads):
    from faster_whisper import WhisperModel
    model_obj = WhisperModel(
        model, device="cpu",
        cpu_threads=n_threads or 8, compute_type="int8",
    )
    segments, info = model_obj.transcribe(
        wav_path, language=language, word_timestamps=True,
        beam_size=5, vad_filter=True,
    )
    raw = []
    for s in segments:
        raw.append({
            "text": s.text, "start": s.start, "end": s.end,
            "words": [{"word": w.word, "start": w.start, "end": w.end}
                      for w in (s.words or [])],
            "language": getattr(info, "language", None),
        })
    return raw


def _transcribe_whispercpp(wav_path, model, language, n_threads):
    from whispercpp import Whisper
    w = Whisper(model_name=model, n_threads=n_threads or 8)
    return w.transcribe(wav_path, word_timestamps=True, language=language)


def transcribe_chunk(wav_path: str, model: str = "medium",
                    language=None, n_threads: int = 8,
                    backend: str = "fasterwhisper", verbose: bool = False) -> list:
    """识别单个音频块。language=None 启用自动语言检测（适合英/法夹杂）。"""
    if backend == "whispercpp":
        raw = _transcribe_whispercpp(wav_path, model, language, n_threads)
    else:
        raw = _transcribe_faster(wav_path, model, language, n_threads)
    return _normalize_segments(raw, backend=backend, language_hint=language)


def transcribe_chunk_cached(wav_path, cache_json, model="medium",
                            language=None, n_threads=8,
                            backend="fasterwhisper", resume=True):
    if resume and os.path.exists(cache_json):
        with open(cache_json, "r", encoding="utf-8") as f:
            return json.load(f)
    segs = transcribe_chunk(wav_path, model=model, language=language,
                           n_threads=n_threads, backend=backend)
    os.makedirs(os.path.dirname(cache_json), exist_ok=True)
    with open(cache_json, "w", encoding="utf-8") as f:
        json.dump(segs, f, ensure_ascii=False, indent=2)
    return segs
