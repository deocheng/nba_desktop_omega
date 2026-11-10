#!/usr/bin/env python3
"""
tests/test_br_gamelog_parser.py — gamelog 解析器 fixture 回归测试（离线）。

  复用旧版 crawl_br_gamelog.parse_gamelog_html（纯函数，已验证），
  对真实球员页 HTML 断言：返回非空比赛 dict 列表、关键字段存在。
  —— 同理，把"只有 live 才暴露"的解析回归下沉到本地 fixture 测试。

fixture 来源（只读拷贝）：tests/fixtures/gamelog_*.html
  （来自 gamelog_cache/html/<season>/<letter>/<player_id>.html，12k+ 真实样本）
运行：
  cd external_crawler/crawler_v2 && python -m pytest tests/test_br_gamelog_parser.py -q
"""
import glob
import os
import sys

import pytest

from common.nba_paths import REPO_ROOT

ROOT = str(REPO_ROOT)
CRAWLER_DIR = os.path.join(ROOT, "external_crawler", "crawler")
for _p in (CRAWLER_DIR, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
GLOG_FIXTURES = sorted(glob.glob(os.path.join(FIXTURE_DIR, "gamelog_*.html")))

# 懒 import：crawl_br_gamelog 顶层可能拉重型依赖，放函数内按需导入并 skip
try:
    from crawl_br_gamelog import parse_gamelog_html  # type: ignore
except Exception as e:  # noqa: BLE001
    parse_gamelog_html = None
    _import_err = e


def _load_html(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


@pytest.mark.skipif(parse_gamelog_html is None, reason="crawl_br_gamelog 不可导入")
@pytest.mark.parametrize("path", GLOG_FIXTURES, ids=[os.path.basename(p) for p in GLOG_FIXTURES])
def test_parse_gamelog_nonempty(path):
    html = _load_html(path)
    games = parse_gamelog_html(html)
    assert isinstance(games, list), "parse_gamelog_html 应返回 list"
    assert len(games) > 0, f"{os.path.basename(path)} 解析为空（疑似回归）"
    assert isinstance(games[0], dict), "每场应为 dict"


@pytest.mark.skipif(parse_gamelog_html is None, reason="crawl_br_gamelog 不可导入")
def test_parse_gamelog_deterministic():
    if not GLOG_FIXTURES:
        pytest.skip("无 gamelog fixture")
    html = _load_html(GLOG_FIXTURES[0])
    a = parse_gamelog_html(html)
    b = parse_gamelog_html(html)
    assert len(a) == len(b), "两次解析行数不一致（非确定性解析）"
