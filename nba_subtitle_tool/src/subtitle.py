"""字幕生成：把带时间戳的中文分段渲染为 SRT（支持按字数与时长自动断行/拆分）。"""


def format_timestamp(seconds: float) -> str:
    if seconds is None or seconds < 0:
        seconds = 0.0
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


_PUNCT = "，。、！？；,.!?; "


def _split_into_lines(text: str, max_chars: int) -> list:
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    lines, buf = [], ""
    for ch in text:
        buf += ch
        if len(buf) >= max_chars:
            cut = len(buf)
            # 尽量在标点处断开
            for i in range(len(buf) - 1, max(0, len(buf) - max_chars // 2), -1):
                if buf[i] in _PUNCT:
                    cut = i + 1
                    break
            lines.append(buf[:cut].strip())
            buf = buf[cut:]
    if buf.strip():
        lines.append(buf.strip())
    # 避免把单个标点甩到下一行（如「三分球！」被拆成「三分球」「！」）
    merged = []
    for i, ln in enumerate(lines):
        if merged and len(ln) <= 2 and ln[0] in "，。！？；、”’":
            merged[-1] += ln
        else:
            merged.append(ln)
    return [ln for ln in merged if ln]


def _split_text_into_n(text: str, n: int, max_chars: int) -> list:
    if n <= 1:
        return [text]
    k = max(max_chars, -(-len(text) // n))  # ceil
    chunks, buf = [], ""
    for ch in text:
        buf += ch
        if len(buf) >= k:
            cut = len(buf)
            for i in range(len(buf) - 1, max(0, len(buf) - k // 2), -1):
                if buf[i] in _PUNCT:
                    cut = i + 1
                    break
            chunks.append(buf[:cut].strip())
            buf = buf[cut:]
    if buf.strip():
        chunks.append(buf.strip())
    # 若块数不足 n（因标点聚集），直接等分补齐
    while len(chunks) < n:
        chunks.append("")
    return [c for c in chunks if c] or [text]


def _build_entries(seg: dict, max_chars: int, max_lines: int, max_line_duration: float) -> list:
    text = (seg.get("zh") or seg.get("text") or "").strip()
    if not text:
        return []
    start, end = seg["start"], seg["end"]
    dur = max(0.0, end - start)
    total_chars = len(text)
    by_content = max(1, -(-total_chars // (max_chars * max_lines)))
    by_duration = 1
    if max_line_duration and dur > max_line_duration:
        by_duration = max(1, -(-int(dur) // int(max_line_duration)))
    n = max(by_content, by_duration)
    chunks = _split_text_into_n(text, n, max_chars)
    entries = []
    step = dur / len(chunks) if chunks else dur
    for i, ch in enumerate(chunks):
        lines = _split_into_lines(ch, max_chars)[:max_lines] or [ch]
        s = start + i * step
        e = start + (i + 1) * step if i < len(chunks) - 1 else end
        entries.append({"start": s, "end": e, "lines": lines})
    return entries


def segments_to_srt(segments: list, max_chars: int = 22,
                    max_lines: int = 2, max_line_duration: float = 7.0) -> str:
    out = []
    idx = 1
    for seg in segments:
        for ent in _build_entries(seg, max_chars, max_lines, max_line_duration):
            out.append(str(idx))
            out.append(f"{format_timestamp(ent['start'])} --> {format_timestamp(ent['end'])}")
            out.extend(ent["lines"])
            out.append("")
            idx += 1
    return "\n".join(out).rstrip() + "\n"
