"""QA 独立补充边界用例（严过关/Edward，不破坏现有 47 用例）。

聚焦易错点：
  * died 误填（在世/无 Died 行 → None，绝不填空串/当前日期）
  * jersey 去重（单号不丢、无 uni_holder → None）
  * honors 容错（无 #bling → []；非数字年份格式 → year=None 不报错）
  * 区间年取末年
"""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

from common import player_bio_ext as bx


# ── died 误填防护 ──────────────────────────────────────────────────────────
def test_died_no_died_line_returns_none():
    # 在世球员页（仅有 Born，无 Died 行）→ 必须 None，严禁误填
    html = '<div id="info"><div id="meta"><p><strong>Born:</strong> August 23, 1978</p></div></div>'
    assert bx.extract_died(html) is None


def test_died_empty_string_html_returns_none():
    assert bx.extract_died("") is None
    assert bx.extract_died(None) is None


# ── jersey 去重边界 ─────────────────────────────────────────────────────────
def test_jersey_single_number_not_dropped():
    # 单号球员：去重后仍是单元素列表，不能被误清空
    html = '<div id="info"><div class="uni_holder bbr"><svg class="jersey"><text x="9" y="39">32</text></svg></div></div>'
    assert bx.extract_jersey_numbers(html) == ["32"]


def test_jersey_no_uni_holder_returns_none():
    html = '<div id="info"><div id="meta"></div></div>'
    assert bx.extract_jersey_numbers(html) is None


def test_jersey_mixed_text_tokens_ignored():
    # uni_holder 内非纯数字 token（如球队名）应被忽略，只收数字
    html = (
        '<div id="info"><div class="uni_holder bbr">'
        '<svg><text>32</text></svg>'
        '<svg><text>PHI</text></svg>'
        '<svg><text>6</text></svg>'
        "</div></div>"
    )
    assert bx.extract_jersey_numbers(html) == ["32", "6"]


# ── honors 容错 ─────────────────────────────────────────────────────────────
def test_honors_no_bling_returns_empty():
    html = '<div id="info"><div id="meta"></div></div>'
    assert bx.extract_honors(html) == []


def test_honor_line_nonnumeric_year_tolerated():
    # 无 4 位年份 → year None，不抛异常
    assert bx.parse_honor_line("Hall of Fame")["honor_year"] is None
    assert bx.parse_honor_line("16x All Star")["honor_year"] is None


def test_honor_line_range_year_takes_end_year():
    # 赛季区间：取末年（NBA 命名惯例）
    assert bx.parse_honor_line("1971-72 All-Rookie")["honor_year"] == 1972
    assert bx.parse_honor_line("2008-09 All-Rookie")["honor_year"] == 2009


def test_honor_line_decade_suffix_not_misparsed():
    # "1980s" 不应被误判为年份 1980
    assert bx.parse_honor_line("1990s Scoring Leader")["honor_year"] is None


# ── extract_all：在世球员核心字段不误填 ───────────────────────────────────────
def test_extract_all_alive_no_died():
    html = (
        '<div id="info">'
        '<div id="meta">'
        '<p><strong>Born:</strong> August 23, 1978</p>'
        "</div>"
        '<div class="uni_holder bbr"><svg><text>8</text></svg></div>'
        "</div>"
    )
    d = bx.PlayerBioExtExtractor.extract_all(html)
    assert d["died"] is None
    assert d["aba_debut"] is None
    assert d["hof_inducted_year"] is None
    assert d["is_hall_of_famer"] is False
    assert d["jersey_numbers"] == ["8"]
    assert d["honors"] == []
    assert d["career_honors_text"] is None
