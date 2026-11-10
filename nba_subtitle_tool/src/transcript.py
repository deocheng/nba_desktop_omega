"""中文文稿生成：把分段译文整理为带时间戳的 Markdown，按停顿自动分段。"""
from .subtitle import format_timestamp


def _fmt_ts(seconds: float) -> str:
    if seconds is None:
        return "00:00"
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m:02d}:{s:02d}"


def segments_to_markdown(segments: list, title: str = "视频文稿",
                         gap_threshold: float = 2.0,
                         with_timestamps: bool = True,
                         note: str = None) -> str:
    paras = []
    cur = []
    last_end = None
    for seg in segments:
        zh = seg.get("zh") or seg.get("text") or ""
        zh = zh.strip()
        if not zh:
            continue
        if last_end is not None and (seg["start"] - last_end) > gap_threshold and cur:
            paras.append((cur[0]["start"], cur))
            cur = []
        cur.append({"start": seg["start"], "text": zh})
        last_end = seg["end"]
    if cur:
        paras.append((cur[0]["start"], cur))

    note = note or "由本地语音识别生成，篮球术语已做专业校对。"
    lines = [f"# {title} · 中文文稿", "", f"> {note}", ""]
    for start, group in paras:
        if with_timestamps:
            lines.append(f"**[{_fmt_ts(start)}]**")
        lines.append(" ".join(g["text"] for g in group))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
