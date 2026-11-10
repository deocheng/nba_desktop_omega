"""纯逻辑单测（不依赖模型）：时间戳、SRT 生成、文稿分组、术语表、识别归一化。
运行：python tests/test_logic.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from src import subtitle, transcript, translator
from src.transcriber import _normalize_segments


def test_format_timestamp():
    assert subtitle.format_timestamp(0) == "00:00:00,000"
    assert subtitle.format_timestamp(3661.5) == "01:01:01,500"
    assert subtitle.format_timestamp(125.0) == "00:02:05,000"
    print("✓ format_timestamp")


def test_srt_basic():
    segs = [{"start": 0.0, "end": 2.0, "zh": "欢迎观看本场比赛"}]
    srt = subtitle.segments_to_srt(segs)
    assert "1" in srt
    assert "00:00:00,000 --> 00:00:02,000" in srt
    assert "欢迎观看本场比赛" in srt
    print("✓ srt_basic")


def test_srt_long_line_split():
    long_text = "这是一句非常长的解说内容需要被合理地切分成多行以便观众阅读所以这里要超过默认字数限制来测试自动断行功能是否正常"
    segs = [{"start": 0.0, "end": 30.0, "zh": long_text}]
    srt = subtitle.segments_to_srt(segs, max_chars=22, max_lines=2, max_line_duration=7.0)
    # 时长 30s > 7s，应被拆成多条字幕
    count = srt.count("\n\n") + 1
    assert count >= 2, f"长时段未拆分：{count} 条"
    print(f"✓ srt_long_line_split（拆成 {count} 条）")


def test_markdown_grouping():
    segs = [
        {"start": 0.0, "end": 2.0, "zh": "第一节开始"},
        {"start": 2.5, "end": 4.0, "zh": "主队率先得分"},
        {"start": 12.0, "end": 14.0, "zh": "第二节换人"},  # 间隔>2s 应另起一段
    ]
    md = transcript.segments_to_markdown(segs, title="测试")
    assert "第一节开始" in md and "主队率先得分" in md
    assert "第二节换人" in md
    # 应有两个时间点标记
    assert md.count("**[") == 2, "分段未按停顿切分"
    print("✓ markdown_grouping")


def test_glossary():
    g = translator.load_glossary(os.path.join(ROOT, "glossary.json"))
    assert isinstance(g, list) and len(g) > 50
    txt = translator.glossary_to_text(g, limit=3)
    assert "控球后卫" in txt and "meneur" in txt   # 前 3 条含控卫/法文 meneur
    assert "挡拆" in translator.glossary_to_text(g)  # 全量含 pick and roll→挡拆
    print(f"✓ glossary（{len(g)} 条）")


def test_normalize_centiseconds():
    # whispercpp 后端：t0/t1 与 words 为厘秒
    raw = [{"text": "hello world", "t0": 100, "t1": 350,
            "words": [{"word": "hello", "start": 100, "end": 200},
                      {"word": "world", "start": 200, "end": 350}]}]
    segs = _normalize_segments(raw, backend="whispercpp")
    assert abs(segs[0]["start"] - 1.0) < 1e-6
    assert abs(segs[0]["end"] - 3.5) < 1e-6
    assert abs(segs[0]["words"][0]["start"] - 1.0) < 1e-6
    print("✓ normalize_centiseconds (whispercpp)")


def test_normalize_seconds():
    # faster-whisper 后端：直接为秒
    raw = [{"text": "pick and roll", "words": [
        {"word": "pick", "start": 1.2, "end": 1.6},
        {"word": "roll", "start": 1.6, "end": 2.0}]}]
    segs = _normalize_segments(raw, backend="fasterwhisper")
    assert abs(segs[0]["start"] - 1.2) < 1e-6
    assert abs(segs[0]["end"] - 2.0) < 1e-6
    print("✓ normalize_seconds (faster-whisper)")


if __name__ == "__main__":
    test_format_timestamp()
    test_srt_basic()
    test_srt_long_line_split()
    test_markdown_grouping()
    test_glossary()
    test_normalize_centiseconds()
    test_normalize_seconds()
    print("\n全部纯逻辑测试通过 ✅")
