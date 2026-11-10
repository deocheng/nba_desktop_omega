#!/usr/bin/env python3
"""
tests/test_br_pbp_parser.py — PBP 解析器 fixture 回归测试（离线，不启 Chrome/不连 DB）。

设计目的（对应 MediaCrawler 的 test_*_extractor / test_*_raw_response_errors 思路）：
  把真实归档 HTML 当 fixture，跑既有 parse_pbp，断言输出非空且结构稳定。
  —— 这样 1999 赛季 hard-kill / driver-CF 挂死这类"只有 live 才暴露"的解析回归，
     能在本地秒级隔离，不必靠爬虫跑崩才发现（旧版 1999 bug 的根因 class）。

fixture 来源（只读拷贝，不改动旧数据）：
  - tests/fixtures/*.html 来自 pbp_raw/ 与 raw_archive/br/（真实 BR 比赛页）
运行：
  cd external_crawler/crawler_v2 && python -m pytest tests/test_br_pbp_parser.py -q
"""
import os
import sys
import glob
import pytest
from bs4 import BeautifulSoup

ROOT = "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13"
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
# 只吃 PBP 页面（gamelog_* 是球员页，没有 pbp 表，归 gamelog 测试）
PBP_FIXTURES = sorted(
    g for g in glob.glob(os.path.join(FIXTURE_DIR, "*.html"))
    if "gamelog_" not in os.path.basename(g)
)

# 轻量 import：parse_pbp 是纯函数（仅依赖 bs4），无副作用
try:
    from br_pbp_parse import parse_pbp  # type: ignore
except Exception as e:  # noqa: BLE001
    pytest.skip(f"br_pbp_parse 不可导入（环境缺失）: {e}", allow_module_level=True)


def _load_soup(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        html = f.read()
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def _fname_gid(path):
    return os.path.splitext(os.path.basename(path))[0]


@pytest.mark.parametrize("path", PBP_FIXTURES, ids=[os.path.basename(p) for p in PBP_FIXTURES])
def test_parse_pbp_nonempty_and_structured(path):
    """真实页面 → parse_pbp 必须产出非空、结构合法的逐回合行。"""
    soup = _load_soup(path)
    gid = _fname_gid(path)
    rows = parse_pbp(soup, "", "", gid)
    assert isinstance(rows, list), "parse_pbp 应返回 list"
    assert len(rows) > 0, f"{os.path.basename(path)} 解析为空（疑似解析回归）"

    r0 = rows[0]
    assert isinstance(r0, dict)
    # 关键字段必存在（与 br_fill_pbp.INSERT_SQL 列对齐）
    for col in ("eventnum", "period", "clock", "team", "player"):
        assert col in r0, f"缺少字段 {col}"


def test_parse_pbp_deterministic():
    """同页面两次解析行数一致（确定性，防止随机漏解析）。"""
    if not PBP_FIXTURES:
        pytest.skip("无 fixture")
    soup = _load_soup(PBP_FIXTURES[0])
    gid = _fname_gid(PBP_FIXTURES[0])
    a = parse_pbp(soup, "", "", gid)
    b = parse_pbp(soup, "", "", gid)
    assert len(a) == len(b), "两次解析行数不一致（非确定性解析）"


def test_all_fixtures_parse():
    """完整性：所有 fixture 都能解析且非空（回归总闸）。"""
    assert PBP_FIXTURES, "fixtures 目录无 HTML"
    for p in PBP_FIXTURES:
        rows = parse_pbp(_load_soup(p), "", "", _fname_gid(p))
        assert len(rows) > 0, f"{os.path.basename(p)} 解析为空"
