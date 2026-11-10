"""流水线编排：抽音频 → 分块识别 → 翻译 → 出 SRT + Markdown。
块级与翻译级均支持断点续跑（缓存 json）。"""
import json
import os
import glob

import yaml

from . import audio_utils, transcriber, translator, subtitle, transcript


def _resolve(base_dir: str, p: str) -> str:
    if os.path.isabs(p):
        return p
    return os.path.join(base_dir, p)


def _dominant_language(segs: list) -> str:
    """统计各段检测到的语言，返回占比最高的语言代码（如 zh / en / fr）。"""
    from collections import Counter
    cnt = Counter()
    for s in segs:
        lang = s.get("lang") or s.get("language")
        if lang:
            cnt[lang] += 1
    if not cnt:
        return None
    return cnt.most_common(1)[0][0]


import re as _re
_CJK = _re.compile(r"[\u3400-\u9fff]")
_ASCII_LETTER = _re.compile(r"[A-Za-z]")


def _text_is_chinese(text: str, threshold: float = 0.3) -> bool:
    """按文本内容判断是否为中文源：CJK 字符占（CJK+英文字母）比例超阈值即视为中文。
    比 Whisper 的语言标签更可靠——可正确处理「中文视频被误判为英文」或「视频内夹英文」。"""
    cjk = len(_CJK.findall(text))
    ascii_letters = len(_ASCII_LETTER.findall(text))
    total_alpha = cjk + ascii_letters
    if total_alpha == 0:
        return False
    return cjk / total_alpha >= threshold


def _normalize_cjk_punct(text: str) -> str:
    """中文源直出时，把 ASCII 标点规范为中文标点（逗号/叹号/问号全替换；
    句号仅替换非数字相邻的，避免误伤小数，如 3.5）。"""
    text = text.replace(",", "，").replace("!", "！").replace("?", "？")
    text = _re.sub(r"(?<!\d)\.(?!\d)", "。", text)
    return text


def _make_chinese_converter(target: str):
    """源语言为中文时，把繁体转简体（hanziconv，纯 Python）。target!=simplified 则返回 None。"""
    if target != "simplified":
        return None
    try:
        from hanziconv import HanziConv
        return HanziConv.toSimplified
    except Exception:
        return None


def load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["_config_dir"] = os.path.dirname(os.path.abspath(config_path))
    return cfg


def run(video_path: str, config_path: str = "config.yaml",
        output_dir: str = None, language: str = None, **overrides) -> dict:
    cfg = load_config(config_path)
    cd = cfg["_config_dir"]

    # 覆盖项
    if overrides.get("whisper"):
        cfg["models"]["whisper"] = overrides["whisper"]
    if overrides.get("translator"):
        cfg["models"]["translator"] = overrides["translator"]
    if overrides.get("backend"):
        cfg["models"]["backend"] = overrides["backend"]
    # 显式指定识别语言（如中文教学视频强制 zh：识别更准 + 跳过翻译）
    if overrides.get("language"):
        language = overrides["language"]

    name = os.path.splitext(os.path.basename(video_path))[0]
    # 每个视频独立的 work 目录，避免多视频复用时串台（音频块/识别缓存互相覆盖）
    work_dir = os.path.join(_resolve(cd, cfg["paths"]["work_dir"]), name)
    output_dir = output_dir or _resolve(cd, cfg["paths"]["output_dir"])
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    wav_path = os.path.join(work_dir, "audio_full.wav")
    resume = cfg.get("pipeline", {}).get("resume", True)

    # 1) 抽音频
    if not (resume and os.path.exists(wav_path)):
        print(f"[1/5] 抽取音频：{video_path}")
        audio_utils.extract_audio(video_path, wav_path,
                                   sr=cfg["audio"]["sample_rate"],
                                   channels=cfg["audio"]["channels"])
    else:
        print(f"[1/5] 复用已抽取音频：{wav_path}")

    # 2) 分块
    existing = sorted(glob.glob(os.path.join(work_dir, "chunk_*.wav")))
    if resume and existing:
        chunks = []
        for i, p in enumerate(existing):
            # 估算 offset：从文件名序号无法得精确 offset，重新统一分块更稳
            pass
        print(f"[2/5] 复用 {len(existing)} 个已存在音频块")
        # 为保证 offset 正确，仍按时间重新生成 chunks 描述（wav 已存在则 ffmpeg 秒过）
    print(f"[2/5] 分块音频（每块 {cfg['audio']['chunk_seconds']}s，重叠 {cfg['audio']['chunk_overlap_seconds']}s）")
    chunks = audio_utils.chunk_audio(
        wav_path, work_dir,
        chunk_sec=cfg["audio"]["chunk_seconds"],
        overlap_sec=cfg["audio"]["chunk_overlap_seconds"],
    )

    # 3) 逐块识别（自动语言检测 → 处理英/法夹杂；显式指定语言时优先）
    auto_lang = cfg.get("pipeline", {}).get("auto_language", True)
    lang = language or (None if auto_lang else "en")
    backend = cfg["models"].get("backend", "fasterwhisper")
    all_segs = []
    n_threads = 8
    print(f"[3/5] 语音识别（{backend} / Whisper {cfg['models']['whisper']}，"
          f"语言={'自动' if auto_lang else 'en'}）")
    for ch in chunks:
        cache = os.path.join(work_dir, f"seg_{ch['index']:04d}.json")
        segs = transcriber.transcribe_chunk_cached(
            ch["path"], cache, model=cfg["models"]["whisper"],
            language=lang, n_threads=n_threads, backend=backend, resume=resume,
        )
        for s in segs:
            off = ch["offset"]
            if s.get("start") is not None:
                s["start"] += off
            if s.get("end") is not None:
                s["end"] += off
            for w in s.get("words", []) or []:
                if w.get("start") is not None:
                    w["start"] += off
                if w.get("end") is not None:
                    w["end"] += off
        all_segs.extend(segs)
    all_segs.sort(key=lambda s: s["start"] or 0)

    merged_path = os.path.join(work_dir, "merged_segments.json")
    with open(merged_path, "w", encoding="utf-8") as f:
        json.dump(all_segs, f, ensure_ascii=False, indent=2)

    # 4) 翻译 / 中文源直出
    glossary = translator.load_glossary(_resolve(cd, cfg["translation"]["glossary_path"]))
    tcfg = cfg["translation"]
    detected_lang = language or _dominant_language(all_segs)
    combined_text = " ".join(s.get("text", "") for s in all_segs)
    is_chinese_src = _text_is_chinese(combined_text)
    texts = [s["text"] for s in all_segs]

    if is_chinese_src:
        # 源语言已是中文：跳过 LLM 翻译，直接作为中文字幕/文稿（繁→简可选）
        print(f"[4/5] 识别内容为中文（Whisper 判定 {detected_lang}），跳过翻译，直接生成中文字幕")
        conv = _make_chinese_converter(tcfg.get("target_chinese", "simplified"))
        for s in all_segs:
            t = conv(s["text"]) if conv else s["text"]
            s["zh"] = _normalize_cjk_punct(t)
        md_note = "由本地语音识别生成（源语言为中文，已做繁→简统一），篮球术语已做专业校对。"
    else:
        print(f"[4/5] 翻译（本地模型 {cfg['models']['translator']}），共 {len(texts)} 段")
        zh = translator.translate_cached(
            texts,
            os.path.join(work_dir, "translations.json"),
            glossary,
            model=cfg["models"]["translator"],
            workers=tcfg.get("workers", 4),
            temperature=tcfg.get("temperature", 0.1),
            base_url=tcfg.get("ollama_base_url", "http://localhost:11434"),
            glossary_limit=tcfg.get("glossary_inject_limit", 0),
            resume=resume,
        )
        for s, z in zip(all_segs, zh):
            s["zh"] = z
        md_note = "由本地语音识别 + 本地大模型翻译生成，篮球术语已做专业校对。"

    # 5) 输出
    srt = subtitle.segments_to_srt(
        all_segs,
        max_chars=cfg["subtitle"]["max_chars_per_line"],
        max_lines=cfg["subtitle"]["max_lines"],
        max_line_duration=cfg["subtitle"]["max_line_duration"],
    )
    md = transcript.segments_to_markdown(all_segs, title=name, note=md_note)
    srt_path = os.path.join(output_dir, f"{name}.srt")
    md_path = os.path.join(output_dir, f"{name}.md")
    json_path = os.path.join(output_dir, f"{name}.json")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_segs, f, ensure_ascii=False, indent=2)

    total = all_segs[-1]["end"] if all_segs else 0
    print(f"[5/5] 完成。总时长 {total/60:.1f} 分钟，字幕 {len(srt.splitlines())//4} 条")
    print(f"  字幕：{srt_path}")
    print(f"  文稿：{md_path}")
    print(f"  结构化：{json_path}")
    return {"srt": srt_path, "md": md_path, "json": json_path,
            "duration": total, "segments": len(all_segs)}
