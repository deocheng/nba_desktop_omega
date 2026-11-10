"""字幕 / 文本文件转换工具（无需识别，直接处理已有字幕/文本文件）。

两个能力：
  1) VTT → SRT：纯格式转换，无需模型，秒出。
  2) 英文 / 法文字幕或文本 → 中文：调用本地大模型翻译（复用篮球术语表），
     有时戳的文件(SRT/VTT)保留时间轴生成中文 SRT，并附中文 Markdown 文稿。

段落统一结构：{"start": float|None, "end": float|None, "text": str}
"""
import os
import re

from src import subtitle as _sub
from src import translator as _tr


# ---------- 时间戳 ----------
def _ts_to_sec(ts: str) -> float:
    """解析 00:00:01.000 / 00:00:01,000 / 00:01.000 为秒（浮点）。"""
    ts = ts.strip().replace(",", ".")
    parts = [float(p) for p in ts.split(":") if p != ""]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    h, m, s = parts[-3], parts[-2], parts[-1]
    return h * 3600 + m * 60 + s


def _parse_timing(line: str):
    """从含 '-->' 的时间轴行解析 (start_sec, end_sec)。容错：忽略行尾的 cue 设置。"""
    m = re.match(r"^(.*?)\s*-->\s*(\S+)(.*)$", line.strip())
    if not m:
        return None, None
    return _ts_to_sec(m.group(1)), _ts_to_sec(m.group(2))


# ---------- 解析 ----------
def parse_vtt(text: str) -> list:
    """WebVTT → segments（按空行分块，取含 '-->' 的块）。"""
    segs = []
    for blk in re.split(r"\n\s*\n", text):
        lines = [ln.strip() for ln in blk.splitlines() if ln.strip()]
        arrow_idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if arrow_idx is None:
            continue
        start, end = _parse_timing(lines[arrow_idx])
        if start is None:
            continue
        txt = " ".join(lines[arrow_idx + 1:]).strip()
        if txt:
            segs.append({"start": start, "end": end, "text": txt})
    return segs


def parse_srt(text: str) -> list:
    segs = []
    for blk in re.split(r"\n\s*\n", text.strip()):
        lines = [ln.strip() for ln in blk.splitlines() if ln.strip()]
        arrow_idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if arrow_idx is None:
            continue
        start, end = _parse_timing(lines[arrow_idx])
        if start is None:
            continue
        txt = " ".join(lines[arrow_idx + 1:]).strip()
        if txt:
            segs.append({"start": start, "end": end, "text": txt})
    return segs


def parse_plain(text: str) -> list:
    """纯文本 / Markdown → 无时间戳分段（按段落，去掉标题/列表前缀）。"""
    segs = []
    for blk in re.split(r"\n\s*\n", text.strip()):
        blk = blk.strip()
        if not blk:
            continue
        cleaned = [re.sub(r"^\s*([#>\-*•]|\d+\.)\s*", "", ln).strip()
                   for ln in blk.splitlines()]
        txt = " ".join(cleaned).strip()
        if txt:
            segs.append({"start": None, "end": None, "text": txt})
    return segs


def file_to_segments(path: str):
    """返回 (segments, kind)，kind ∈ {vtt, srt, txt}。"""
    ext = os.path.splitext(path)[1].lower()
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    if ext == ".vtt":
        return parse_vtt(text), "vtt"
    if ext == ".srt":
        return parse_srt(text), "srt"
    return parse_plain(text), "txt"


# ---------- 能力 1：VTT → SRT ----------
def vtt_to_srt(path: str) -> str:
    """读取 VTT 文件，返回 SRT 文本（保留时间轴，按字数/时长自动断行）。"""
    segs, _ = file_to_segments(path)
    return _sub.segments_to_srt(segs)


# ---------- 能力 2：英文/法文 → 中文 ----------
def _build_zh_md(name: str, segs: list, zh: list, kind: str) -> str:
    lines = [f"# {name} · 中文译文", "",
             "> 由本地大模型翻译生成，篮球术语已做专业校对。", ""]
    if kind in ("srt", "vtt"):
        for s, z in zip(segs, zh):
            if z.strip():
                lines.append(f"- **{_sub.format_timestamp(s['start'])}** {z}")
    else:
        for z in zh:
            if z.strip():
                lines.append(z)
                lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def translate_file_to_chinese(input_path: str, translator_model: str,
                              glossary_path: str, output_dir: str,
                              srt_out: str = None, md_out: str = None,
                              temperature: float = 0.1,
                              base_url: str = "http://localhost:11434",
                              workers: int = 4, cache_dir: str = None) -> dict:
    """把已有字幕/文本翻译成中文，写盘后返回结果摘要。

    - 有时戳输入(SRT/VTT)：生成中文 SRT(srt_out) + 中文 MD(md_out)。
    - 纯文本输入(txt/md)：仅生成中文 MD(md_out)，srt_out 忽略。
    """
    segs, kind = file_to_segments(input_path)
    if not segs:
        return {"segments": 0, "kind": kind, "wrote": []}

    texts = [s["text"] for s in segs]
    glossary = _tr.load_glossary(glossary_path)
    name = os.path.splitext(os.path.basename(input_path))[0]
    cache = os.path.join(cache_dir or output_dir, name + ".trans.json")

    zh = _tr.translate_cached(texts, cache, glossary, model=translator_model,
                              workers=workers, temperature=temperature,
                              base_url=base_url)

    for s, z in zip(segs, zh):
        s["zh"] = z

    wrote = []
    if srt_out and kind in ("srt", "vtt"):
        with open(srt_out, "w", encoding="utf-8") as f:
            f.write(_sub.segments_to_srt(segs))
        wrote.append(srt_out)

    if md_out:
        with open(md_out, "w", encoding="utf-8") as f:
            f.write(_build_zh_md(name, segs, zh, kind))
        wrote.append(md_out)

    return {"segments": len(segs), "kind": kind, "wrote": wrote}
