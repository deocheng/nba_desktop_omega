"""tests/test_br_gapfill.py — br_gapfill 离线单测（不连库、不联网）。

覆盖：
  1. 五个域解析层「全列覆盖」：构造含 BR 真实 data-stat 列的最小 HTML，断言
     解析结果包含 DDL 全部字段、无遗漏、关键值正确。
  2. 缓存 MERGE 语义：旧缓存不被 OVERWRITE；损坏/半截 JSON 容错；同队同季重抓覆盖。
  3. 球员桥接 / slug 归一：以 mock 连接验证 HAVING COUNT(DISTINCT)=1 歧义处理。
  4. build_rows：注入 team/season 维度与球员键，列对齐 DDL。

运行: pytest tests/test_br_gapfill.py -q
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.br_team_page import BRTeamPageCrawler, extract_player_links

# team_shooting 爬虫已于 2026-10-22 归档（队页无 team_shooting 表，实跑 0 行）。
# 解析器本体保留在归档区，这里继续覆盖其纯函数（无 DB/网络），以便未来复活时
# 有回归基线；见 external_crawler/_archived/README.md。
from external_crawler._archived.crawl_br_team_shooting import (
    DISTANCE_LABELS,
    SHOOTING_ZONES,
    TeamShootingCrawler,
    parse_team_shooting_html,
)
from external_crawler.crawler.crawl_br_team_depth import (
    DepthCrawler,
    parse_team_depth_html,
)
from external_crawler.crawler.crawl_br_team_lineups import (
    LineupsCrawler,
    parse_team_lineups_html,
)
from external_crawler.crawler.crawl_br_team_onoff import (
    OnOffCrawler,
    parse_team_onoff_html,
)
from external_crawler.crawler.crawl_br_team_referees import (
    RefereesCrawler,
    parse_team_referees_html,
)


# ───────────────────────── 最小 HTML fixtures ─────────────────────────
def _shooting_html() -> str:
    zones = ["Restricted Area", "In The Paint (Non-RA)", "Mid-Range",
             "Left Corner 3", "Right Corner 3", "Above the Break 3"]
    body = ""
    # "Team" 汇总行（应被跳过）
    body += ('<tr><th data-stat="team">Boston Celtics</th>'
             '<td data-stat="gp">82</td><td data-stat="fg">3000</td></tr>')
    for i, z in enumerate(zones, start=1):
        fg, fga = 100 * i, 200 * i
        fg2, fga2 = 80 * i, 150 * i
        fg3, fga3 = 20 * i, 50 * i
        body += (
            f'<tr><th data-stat="team">{z}</th>'
            f'<td data-stat="mp">2000</td><td data-stat="g">82</td>'
            f'<td data-stat="fg">{fg}</td><td data-stat="fga">{fga}</td>'
            f'<td data-stat="fg_pct">.500</td>'
            f'<td data-stat="fg2">{fg2}</td><td data-stat="fga2">{fga2}</td>'
            f'<td data-stat="fg2_pct">.533</td>'
            f'<td data-stat="fg3">{fg3}</td><td data-stat="fga3">{fga3}</td>'
            f'<td data-stat="fg3_pct">.400</td>'
            f'<td data-stat="pct_of_fga">.{(i*5)%100}</td>'
            f'<td data-stat="avg_shot_dist">{i*2}.5</td></tr>'
        )
    return (
        '<table id="team_shooting"><thead><tr></tr></thead><tbody>' + body + '</tbody></table>'
        '<table id="opponent_shooting"><thead><tr></tr></thead><tbody>' + body + '</tbody></table>'
    )


def _lineups_html() -> str:
    """BR 按阵容人数拆表：id=lineups_{n}-man_（常规赛）/ lineups_{n}-man__p（季后赛）。

    解析器（parse_team_lineups_html）遍历 2/3/4/5 四档表，不再只取 5-man，
    故 fixture 必须按新表 id 结构构造，否则解析出 0 行。
    """
    names = [("a", "aaabr01", "A. Aaa"), ("b", "bbbbr01", "B. Bbb"),
             ("c", "cccbr01", "C. Ccc"), ("d", "dddbr01", "D. Ddd"),
             ("e", "eeebr01", "E. Eee")]
    # BR lineups 页是**净差值(Net)表**：真实列为 diff_pts/diff_fg/.../diff_pf，
    # **没有** gp/won/lost/pts/opp_pts/off_rtg/def_rtg/net_rtg
    # （见 crawl_br_team_lineups.py 模块 docstring 的 2026-07-28 实测记录）。
    cells = ('<td data-stat="mp">480:00</td>'
             '<td data-stat="diff_pts">52</td><td data-stat="diff_fg">21</td>'
             '<td data-stat="diff_fga">48</td><td data-stat="diff_fg_pct">.438</td>'
             '<td data-stat="diff_fg3">7</td><td data-stat="diff_fg3a">18</td>'
             '<td data-stat="diff_fg3_pct">.389</td><td data-stat="diff_efg_pct">.512</td>'
             '<td data-stat="diff_ft">4</td><td data-stat="diff_fta">5</td>'
             '<td data-stat="diff_ft_pct">.800</td>'
             '<td data-stat="diff_orb">9</td><td data-stat="diff_orb_pct">.130</td>'
             '<td data-stat="diff_drb">31</td><td data-stat="diff_drb_pct">.450</td>'
             '<td data-stat="diff_trb">40</td><td data-stat="diff_trb_pct">.580</td>'
             '<td data-stat="diff_ast">24</td><td data-stat="diff_stl">8</td>'
             '<td data-stat="diff_blk">5</td><td data-stat="diff_tov">12</td>'
             '<td data-stat="diff_pf">18</td>')
    out = []
    for n in (2, 3, 4, 5):
        lineup = "/".join(
            f"<a href='/players/{d}/{slug}.html'>{nm}</a>" for d, slug, nm in names[:n]
        )
        row = f'<tr><td data-stat="lineup">{lineup}</td>{cells}</tr>'
        out.append(
            f'<table id="lineups_{n}-man_"><thead><tr></tr></thead><tbody>{row}</tbody></table>'
        )
    return "".join(out)


def _onoff_html() -> str:
    # 真实 BR on/off 表（#on_off）结构：On Court / Off Court / Difference 三组，
    # 每组 11 列。On Court 组 data-stat 无前缀；Off Court 组带 opp_ 前缀；
    # Difference 组带 diff_ 前缀。无 gp / def_rtg / net_rtg。
    row = (
        '<tr>'
        "<th data-stat=\"player\"><a href='/players/a/aaabr01.html'>A. Aaa</a></th>"
        # —— On Court 组（无前缀 data-stat）——
        '<td data-stat="mp">1500</td>'
        '<td data-stat="off_rtg">118.0</td>'
        '<td data-stat="pace">99.5</td>'
        '<td data-stat="efg_pct">.550</td>'
        '<td data-stat="tov_pct">12.5</td>'
        '<td data-stat="orb_pct">25.0</td>'
        '<td data-stat="drb_pct">73.0</td>'
        '<td data-stat="trb_pct">50.0</td>'
        '<td data-stat="stl_pct">8.0</td>'
        '<td data-stat="blk_pct">5.0</td>'
        '<td data-stat="ast_pct">60.0</td>'
        # —— Off Court 组（opp_ 前缀 data-stat）——
        '<td data-stat="opp_mp">500</td>'
        '<td data-stat="opp_off_rtg">105.0</td>'
        '<td data-stat="opp_pace">100.2</td>'
        '<td data-stat="opp_efg_pct">.500</td>'
        '<td data-stat="opp_tov_pct">13.5</td>'
        '<td data-stat="opp_orb_pct">22.0</td>'
        '<td data-stat="opp_drb_pct">76.0</td>'
        '<td data-stat="opp_trb_pct">49.0</td>'
        '<td data-stat="opp_stl_pct">7.5</td>'
        '<td data-stat="opp_blk_pct">4.5</td>'
        '<td data-stat="opp_ast_pct">58.0</td>'
        # —— Difference 组（diff_ 前缀 data-stat）——
        '<td data-stat="diff_mp">1000</td>'
        '<td data-stat="diff_off_rtg">13.0</td>'
        '<td data-stat="diff_pace">-0.7</td>'
        '<td data-stat="diff_efg_pct">.050</td>'
        '<td data-stat="diff_tov_pct">-1.0</td>'
        '<td data-stat="diff_orb_pct">3.0</td>'
        '<td data-stat="diff_drb_pct">-3.0</td>'
        '<td data-stat="diff_trb_pct">1.0</td>'
        '<td data-stat="diff_stl_pct">0.5</td>'
        '<td data-stat="diff_blk_pct">0.5</td>'
        '<td data-stat="diff_ast_pct">2.0</td>'
        '</tr>'
    )
    return '<table id="on_off"><thead><tr></tr></thead><tbody>' + row + '</tbody></table>'


def _depth_html() -> str:
    def slot(name, slug):
        return f'<td><a href="/players/{slug[0]}/{slug}.html">{name}</a></td>'
    rows = ""
    for pos, players in [("PG", [("A. Aaa", "aaabr01"), ("B. Bbb", "bbbbr01")]),
                        ("SG", [("C. Ccc", "cccbr01"), ("D. Ddd", "dddbr01")])]:
        cells = "".join(slot(n, s) for n, s in players)
        rows += f'<tr><th data-stat="pos">{pos}</th>{cells}</tr>'
    return ('<table id="depth_charts"><thead><tr></tr></thead><tbody>'
            + rows + '</tbody></table>')


def _referees_html() -> str:
    """BR referees 页的真实结构（2026-07-28 SAS/2026 实抓）：

    - 表 id = ``refs-summary``，粒度是 **team×season×referee 赛季汇总**
      （每裁判一行），**不是**逐场裁判名单；
    - 数值列 data-stat 与 DB 同名：rank/g/wins/losses/win_pct/pace +
      team_/opp_/diff_ 的 pts/fta/pf/sfoul/ofoul。
    """
    # (slug, name, rank, g, wins, losses, win_pct, pace,
    #  team_pts, team_fta, team_pf, team_sfoul, team_ofoul,
    #  opp_pts, opp_fta, opp_pf, opp_sfoul, opp_ofoul,
    #  diff_pts, diff_fta, diff_pf, diff_sfoul, diff_ofoul)
    refs = [
        ("johndoe01", "John Doe", 1, 62, 36, 26, ".581", "99.4",
         112.3, 24.1, 21.9, 18.2, 17.1,
         108.7, 22.8, 20.4, 17.6, 16.4,
         3.6, 1.3, 1.5, 0.6, 0.7),
        ("janesmi02", "Jane Smith", 2, 55, 30, 25, ".545", "98.8",
         110.1, 23.5, 21.2, 17.8, 16.9,
         109.4, 23.1, 20.7, 18.0, 16.8,
         0.7, 0.4, 0.5, -0.2, 0.1),
        ("boblee03", "Bob Lee", 3, 41, 21, 20, ".512", "100.2",
         108.9, 22.6, 20.1, 17.4, 16.2,
         110.2, 22.9, 20.6, 17.9, 16.7,
         -1.3, -0.3, -0.5, -0.5, -0.5),
    ]
    rows = []
    for (slug, name, rank, g, w, l, wp, pace, tpts, tfta, tpf, tsf, tof,
         opts, ofta, opf, osf, oof, dpts, dfta, dpf, dsf, dof) in refs:
        rows.append(
            '<tr>'
            f'<th data-stat="referee"><a href="/referees/{slug}.html">{name}</a></th>'
            f'<td data-stat="rank">{rank}</td>'
            f'<td data-stat="g">{g}</td>'
            f'<td data-stat="wins">{w}</td>'
            f'<td data-stat="losses">{l}</td>'
            f'<td data-stat="win_pct">{wp}</td>'
            f'<td data-stat="pace">{pace}</td>'
            f'<td data-stat="team_pts">{tpts}</td><td data-stat="team_fta">{tfta}</td>'
            f'<td data-stat="team_pf">{tpf}</td><td data-stat="team_sfoul">{tsf}</td>'
            f'<td data-stat="team_ofoul">{tof}</td>'
            f'<td data-stat="opp_pts">{opts}</td><td data-stat="opp_fta">{ofta}</td>'
            f'<td data-stat="opp_pf">{opf}</td><td data-stat="opp_sfoul">{osf}</td>'
            f'<td data-stat="opp_ofoul">{oof}</td>'
            f'<td data-stat="diff_pts">{dpts}</td><td data-stat="diff_fta">{dfta}</td>'
            f'<td data-stat="diff_pf">{dpf}</td><td data-stat="diff_sfoul">{dsf}</td>'
            f'<td data-stat="diff_ofoul">{dof}</td>'
            '</tr>'
        )
    return ('<table id="refs-summary"><thead><tr></tr></thead><tbody>'
            + "".join(rows) + '</tbody></table>')


# ───────────────────────── 1. 解析层全列覆盖 ─────────────────────────
def test_shooting_parse_columns():
    recs = parse_team_shooting_html(_shooting_html(), "Regular", "BOS")
    # 6 self + 6 opp = 12；"Team" 汇总行被跳过
    assert len(recs) == 12, recs
    expected_keys = {"vs_type", "zone", "mp", "g", "fg", "fga", "fg_percent",
                     "fg2", "fga2", "fg2_pct", "fg3", "fga3", "fg3_pct",
                     "pct_of_fga", "avg_shot_dist"}
    for r in recs:
        assert expected_keys <= set(r.keys()), f"缺列: {expected_keys - set(r.keys())}"
    self_rows = [r for r in recs if r["vs_type"] == "self"]
    opp_rows = [r for r in recs if r["vs_type"] == "opp"]
    assert len(self_rows) == 6 and len(opp_rows) == 6
    # 关键值解析正确（含 INFERRED 补全的 fg2_pct / fg3_pct；真实页 mp 列）
    r0 = self_rows[0]
    assert r0["zone"] == "Restricted Area"
    assert r0["fg"] == 100 and r0["fga"] == 200
    assert r0["mp"] == 2000                        # 真实 BR 页 mp 列解析
    assert r0["fg_percent"] == 0.500
    assert r0["fg2_pct"] == 0.533 and r0["fg3_pct"] == 0.400
    assert r0["avg_shot_dist"] == 2.5


def test_lineups_parse_columns():
    """BR 按人数拆表 → 解析器遍历 2/3/4/5 四档，各得一行（不再是"只取 5-man"）。"""
    recs = parse_team_lineups_html(_lineups_html(), "Regular", "BOS")
    assert len(recs) == 4, f"应解析出 2/3/4/5 四档共 4 行，实得 {len(recs)}"
    # group_size 标记该行来自哪一档，人数与档位自洽
    assert sorted(r["group_size"] for r in recs) == [2, 3, 4, 5]
    for r in recs:
        assert len(r["players"]) == r["group_size"], "行内人数应与档位自洽"
    # 真实 BR 列是净差值 diff_*（无 gp/won/lost/pts）
    r5 = next(r for r in recs if r["group_size"] == 5)
    for k in ("diff_pts", "diff_fg", "diff_fga", "diff_fg_pct", "diff_efg_pct",
              "diff_trb", "diff_trb_pct", "diff_ast", "diff_stl", "diff_blk",
              "diff_tov", "diff_pf"):
        assert k in r5, f"缺列 {k}"
        assert r5[k] is not None, f"列 {k} 解析为 None（落库会成 NULL）"
    assert r5["diff_pts"] == 52 and r5["diff_fg"] == 21
    assert r5["diff_fg_pct"] == 0.438 and r5["diff_efg_pct"] == 0.512
    assert r5["diff_trb"] == 40 and r5["diff_ast"] == 24


def test_onoff_parse_columns():
    recs = parse_team_onoff_html(_onoff_html(), "Regular", "BOS")
    assert len(recs) == 1
    r = recs[0]
    # 真实 BR on/off 三组 × 11 列 + player 维度；无幻影列。
    expected = {
        "player_name", "player_slug",
        "on_mp", "on_off_rtg", "on_pace", "on_efg_pct", "on_tov_pct",
        "on_orb_pct", "on_drb_pct", "on_trb_pct", "on_stl_pct", "on_blk_pct", "on_ast_pct",
        "off_mp", "off_off_rtg", "off_pace", "off_efg_pct", "off_tov_pct",
        "off_orb_pct", "off_drb_pct", "off_trb_pct", "off_stl_pct", "off_blk_pct", "off_ast_pct",
        "diff_mp", "diff_off_rtg", "diff_pace", "diff_efg_pct", "diff_tov_pct",
        "diff_orb_pct", "diff_drb_pct", "diff_trb_pct", "diff_stl_pct", "diff_blk_pct", "diff_ast_pct",
    }
    assert expected <= set(r.keys()), f"缺列: {expected - set(r.keys())}"
    # 三组关键数值均非 NULL（修复前假绿：全部 .get() 返回 None 仍过断言）
    for k in ["on_mp", "on_off_rtg", "on_pace", "on_efg_pct", "on_tov_pct",
              "on_orb_pct", "on_drb_pct", "on_trb_pct", "on_stl_pct", "on_blk_pct", "on_ast_pct",
              "off_mp", "off_off_rtg", "off_pace", "off_efg_pct", "off_tov_pct",
              "off_orb_pct", "off_drb_pct", "off_trb_pct", "off_stl_pct", "off_blk_pct", "off_ast_pct",
              "diff_mp", "diff_off_rtg", "diff_pace", "diff_efg_pct", "diff_tov_pct",
              "diff_orb_pct", "diff_drb_pct", "diff_trb_pct", "diff_stl_pct", "diff_blk_pct", "diff_ast_pct"]:
        assert r[k] is not None, f"列 {k} 解析为 None（落库会成 NULL）"
    # 关键值正确性
    assert r["on_mp"] == 1500 and r["off_mp"] == 500 and r["diff_mp"] == 1000
    assert r["on_off_rtg"] == 118.0 and r["off_off_rtg"] == 105.0 and r["diff_off_rtg"] == 13.0
    assert r["on_efg_pct"] == 0.550 and r["off_efg_pct"] == 0.500 and r["diff_efg_pct"] == 0.050


def test_depth_parse_columns():
    recs = parse_team_depth_html(_depth_html(), "Regular", "BOS")
    assert len(recs) == 4  # 2 位置 × 2 槽位
    for r in recs:
        assert {"position", "depth_rank", "player_name"} <= set(r.keys())
    assert recs[0]["position"] == "PG" and recs[0]["depth_rank"] == 1
    assert recs[1]["depth_rank"] == 2


def test_referees_parse_columns():
    """refs-summary 表 = 每裁判一行的赛季汇总（非逐场名单）。

    真实契约（crawl_br_team_referees.py 模块 docstring / 2026-07-28 实抓）：
    记录含 referee_slug / referee_name + rank/g/wins/losses/win_pct/pace
    + team_/opp_/diff_ 的 pts/fta/pf/sfoul/ofoul。
    """
    recs = parse_team_referees_html(_referees_html(), "Regular", "BOS")
    assert len(recs) == 3, f"3 名裁判应得 3 行，实得 {len(recs)}"
    for r in recs:
        assert {"referee_slug", "referee_name", "rank", "g", "wins", "losses",
                "win_pct", "pace", "team_pts", "opp_pts", "diff_pts",
                "team_pf", "opp_pf", "diff_pf"} <= set(r.keys()), \
            f"缺列: 缺 { {'referee_slug','referee_name','rank','g','wins','losses','win_pct','pace','team_pts','opp_pts','diff_pts'} - set(r.keys()) }"
        # 数值列不得解析为 None（落库会成 NULL）
        for k in ("rank", "g", "wins", "losses", "win_pct", "pace",
                  "team_pts", "opp_pts", "diff_pts"):
            assert r[k] is not None, f"列 {k} 解析为 None（落库会成 NULL）"
    assert [r["referee_name"] for r in recs] == ["John Doe", "Jane Smith", "Bob Lee"]
    assert recs[0]["referee_slug"] == "johndoe01"
    assert recs[0]["rank"] == 1 and recs[0]["g"] == 62
    assert recs[0]["wins"] == 36 and recs[0]["losses"] == 26
    assert recs[0]["win_pct"] == 0.581 and recs[0]["pace"] == 99.4
    assert recs[0]["team_pts"] == 112.3 and recs[0]["opp_pts"] == 108.7
    assert recs[0]["diff_pts"] == 3.6


def test_referees_slug_from_referee_link():
    """裁判 slug 来自 /referees/{slug}.html 链接；无链接时退回 name 小写下划线。"""
    html = ('<table id="refs-summary"><tbody>'
            '<tr><th data-stat="referee"><a href="/referees/doejo01.html">John Doe</a></th>'
            '<td data-stat="rank">1</td><td data-stat="g">10</td></tr>'
            '<tr><th data-stat="referee">Zed Zylo</th>'
            '<td data-stat="rank">2</td><td data-stat="g">8</td></tr>'
            '</tbody></table>')
    recs = parse_team_referees_html(html, "Regular", "BOS")
    assert len(recs) == 2
    assert recs[0]["referee_slug"] == "doejo01"
    assert recs[0]["referee_name"] == "John Doe"
    # 无链接 → slug 退回 name 小写下划线
    assert recs[1]["referee_slug"] == "zed_zylo"
    assert recs[1]["referee_name"] == "Zed Zylo"


# ───────────────────────── 2. 缓存 MERGE 语义 ─────────────────────────
def _make_crawler(tmp):
    c = TeamShootingCrawler(cache_dir=tmp)
    return c


def test_merge_cache_preserves_other_teams():
    with tempfile.TemporaryDirectory() as tmp:
        c = _make_crawler(tmp)
        season = 2026
        old_A = [{"vs_type": "self", "zone": "Restricted Area", "fg": 1}]
        # 先写 A（模拟旧缓存）
        c.merge_cache(season, "BOS", "Regular", old_A)
        # 再写 B：A 必须保留
        new_B = [{"vs_type": "self", "zone": "Mid-Range", "fg": 2}]
        c.merge_cache(season, "LAL", "Regular", new_B)
        path = os.path.join(tmp, f"shooting_{season}.json")
        with open(path) as f:
            data = json.load(f)
        teams = data["teams"]
        assert "BOS" in teams and "LAL" in teams
        assert teams["BOS"]["Regular"] == old_A  # A 未被覆盖/清除
        assert teams["LAL"]["Regular"] == new_B


def test_merge_cache_overwrites_same_team_season():
    with tempfile.TemporaryDirectory() as tmp:
        c = _make_crawler(tmp)
        season = 2026
        c.merge_cache(season, "BOS", "Regular",
                      [{"vs_type": "self", "zone": "Restricted Area", "fg": 1}])
        # 同队同季重抓：应覆盖该项（而非追加）
        c.merge_cache(season, "BOS", "Regular",
                      [{"vs_type": "self", "zone": "Restricted Area", "fg": 999}])
        path = os.path.join(tmp, f"shooting_{season}.json")
        with open(path) as f:
            data = json.load(f)
        recs = data["teams"]["BOS"]["Regular"]
        assert len(recs) == 1
        assert recs[0]["fg"] == 999


def test_merge_cache_handles_corrupt_json():
    with tempfile.TemporaryDirectory() as tmp:
        c = _make_crawler(tmp)
        season = 2026
        path = os.path.join(tmp, f"shooting_{season}.json")
        # 写入半截/损坏 JSON
        with open(path, "w") as f:
            f.write('{"teams": {"BOS": {"Regular": [')
        # 损坏情况下 merge 不应崩溃，且新数据能正常写入
        c.merge_cache(season, "LAL", "Regular",
                      [{"vs_type": "self", "zone": "Mid-Range", "fg": 5}])
        with open(path) as f:
            data = json.load(f)
        assert data["teams"]["LAL"]["Regular"][0]["fg"] == 5


# ───────────────────────── 3. 球员桥接 / slug 归一 ─────────────────────────
def _mock_conn_for_resolve(rows):
    cur = MagicMock()
    cur.fetchall.return_value = rows
    cur.__enter__ = lambda s: s
    cur.__exit__ = lambda s, *a: None
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn


def test_resolve_player_unique():
    # 同名仅 1 个 nba_player_id → 取之
    conn = _mock_conn_for_resolve([("aaabr01", 123)])
    c = TeamShootingCrawler()
    br, nba = c.resolve_player(conn, "A. Aaa")
    assert br == "aaabr01" and nba == 123


def test_resolve_player_ambiguous():
    # 同名歧义（2 个不同 nba_player_id）→ player_id 留 NULL，br 取唯一 slug
    conn = _mock_conn_for_resolve([("aaabr01", 123), ("aaabr01", 456)])
    c = TeamShootingCrawler()
    br, nba = c.resolve_player(conn, "A. Aaa")
    assert br == "aaabr01" and nba is None


def test_resolve_player_none():
    conn = _mock_conn_for_resolve([])
    c = TeamShootingCrawler()
    assert c.resolve_player(conn, "Unknown") == (None, None)


def test_br_slug_mapping():
    # team_mapping: WSB→WAS；缩写在映射中→归一为 current_code
    conn = _mock_conn_for_resolve([("WSB", "WAS"), ("BOS", "BOS")])
    c = TeamShootingCrawler()
    assert c._br_slug(conn, "WSB") == "WAS"
    assert c._br_slug(conn, "BOS") == "BOS"
    # 未命中映射 → 原样返回
    assert c._br_slug(conn, "ZZZ") == "ZZZ"


# ───────────────────────── 4. build_rows 维度注入 + 列对齐 ─────────────────────────
def test_lineups_build_rows_keys():
    conn = _mock_conn_for_resolve([])  # resolve 返回 (None,None)
    c = LineupsCrawler()
    parsed = parse_team_lineups_html(_lineups_html(), "Regular", "BOS")
    # 取 5 人档（build_rows 的球员键按 br_player_id1..N 生成，与人数无关）
    rec5 = next(r for r in parsed if r["group_size"] == 5)
    row = c.build_rows(conn, "BOS", 2026, "Regular", rec5)
    expected = {"team_abbr", "season", "season_type", "lineup_key", "group_size", "mp",
                "br_player_id1", "player_id1", "player_name1",
                "br_player_id5", "player_id5", "player_name5",
                "diff_pts", "diff_fg", "diff_fga", "diff_fg_pct", "diff_efg_pct",
                "diff_trb", "diff_trb_pct", "diff_ast", "diff_stl", "diff_blk",
                "diff_tov", "diff_pf"}
    assert expected <= set(row.keys()), f"缺列: {expected - set(row.keys())}"
    assert row["team_abbr"] == "BOS" and row["season"] == 2026
    # 落库 season_type 经 canon_season_type 归一 → dim_games 权威值
    assert row["season_type"] == "Regular Season"
    assert row["group_size"] == 5
    # lineup_key 为 5 个 slug 排序后连接（无序去重）
    assert row["lineup_key"] == "|".join(
        sorted(["aaabr01", "bbbbr01", "cccbr01", "dddbr01", "eeebr01"]))
    assert row["br_player_id1"] == "aaabr01"
    assert row["player_id1"] is None  # 缺桥留 NULL


def test_onoff_build_rows_keys():
    conn = _mock_conn_for_resolve([])
    c = OnOffCrawler()
    parsed = parse_team_onoff_html(_onoff_html(), "Regular", "BOS")
    row = c.build_rows(conn, "BOS", 2026, "Regular", parsed[0])
    assert row["team_abbr"] == "BOS" and row["season"] == 2026
    assert row["player_name"] == "A. Aaa"
    assert row["on_off_rtg"] == 118.0 and row["off_off_rtg"] == 105.0
    assert row["br_player_id"] == "aaabr01"
    # 列与 DDL 严格对应：33 数值列 + 维度列
    assert "on_efg_pct" in row and "off_ast_pct" in row and "diff_ast_pct" in row
    assert row["on_mp"] == 1500 and row["diff_off_rtg"] == 13.0
    # 老幻影列已彻底移除（不再落库 NULL 污染）
    for phantom in ("gp", "minutes", "off_minutes", "on_ortg", "on_drtg", "on_nrtg",
                    "off_ortg", "off_drtg", "off_nrtg", "net_pts_diff"):
        assert phantom not in row, f"幻影列未移除: {phantom}"


def test_depth_build_rows_keys():
    conn = _mock_conn_for_resolve([])
    c = DepthCrawler()
    parsed = parse_team_depth_html(_depth_html(), "Regular", "BOS")
    row = c.build_rows(conn, "BOS", 2026, "Regular", parsed[0])
    assert {"team_abbr", "season", "position", "depth_rank",
            "player_name", "player_id"} <= set(row.keys())
    assert row["position"] == "PG" and row["depth_rank"] == 1
    assert row["player_id"] is None  # 缺桥留 NULL


def test_referees_build_rows_keys():
    conn = _mock_conn_for_resolve([])
    c = RefereesCrawler()
    parsed = parse_team_referees_html(_referees_html(), "Regular", "BOS")
    row = c.build_rows(conn, "BOS", 2026, "Regular", parsed[0])
    # build_rows 注入 team/season 维度 + 原样透传裁判与数值列
    assert {"team_abbr", "season", "referee_slug", "referee_name",
            "rank", "g", "wins", "losses", "win_pct", "pace",
            "team_pts", "opp_pts", "diff_pts"} <= set(row.keys())
    assert row["team_abbr"] == "BOS" and row["season"] == 2026
    assert row["referee_name"] == "John Doe" and row["referee_slug"] == "johndoe01"
    assert row["rank"] == 1 and row["g"] == 62
    assert row["diff_pts"] == 3.6


def test_min_season_guard():
    # 远低于 MIN_SEASON 的赛季应被 run_pipeline 直接跳过（不碰 DB/浏览器）
    c = TeamShootingCrawler()
    # 用 mock 验证不进入枚举/抓取：直接调用 _already_done 之外，检查方法短路
    # run_pipeline 在 season<MIN_SEASON 时返回 0 且不建立连接
    conn = MagicMock()
    # 直接断言：season 远低于阈值时不应调用 enumerate_team_seasons
    # （通过子类钩子未被触发来验证；此处仅校验常量）
    assert c.MIN_SEASON == 1997
    # 实际跳过逻辑在 run_pipeline 内联判断，无法离线触发 DB；此处仅确认常量正确
    assert True
