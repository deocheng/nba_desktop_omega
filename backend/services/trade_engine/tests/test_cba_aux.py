"""NBACore v8 — cba_aux 单元测试。

覆盖:
    - SalaryCapRules 默认值推导
    - Player.get_max_salary_pct 三档
    - Team.get_cap_hold 三档
    - TradeSimulator.execute_trade 三个分支（第二围裙 fail / 第一围裙 fail / 正常 success）
    - LeagueSimulator.save_league + load_league 往返一致
"""
from __future__ import annotations

import os
import tempfile

import pytest

from backend.services.trade_engine.cba_aux import (
    LeagueSimulator,
    Player,
    SalaryCapRules,
    Team,
    TradeSimulator,
)


# ── SalaryCapRules 默认值推导 ──
def test_salary_cap_rules_defaults():
    """base_cap=168M → luxury=204.12M → first_apron=210.12M → second_apron=221.62M → min=151.2M。"""
    rules = SalaryCapRules()
    assert rules.base_cap == 168_000_000
    assert rules.luxury_tax_line == 204_120_000  # 168M * 1.215
    assert rules.first_apron == 210_120_000      # 204.12M + 6M
    assert rules.second_apron == 221_620_000     # 204.12M + 17.5M
    assert rules.min_team_salary == 151_200_000  # 168M * 0.90


def test_salary_cap_rules_override():
    """显式覆盖字段应保持原值不重新派生。"""
    rules = SalaryCapRules(base_cap=100_000_000, luxury_tax_line=120_000_000)
    assert rules.base_cap == 100_000_000
    assert rules.luxury_tax_line == 120_000_000
    assert rules.first_apron == 126_000_000   # 120M + 6M
    assert rules.second_apron == 137_500_000  # 120M + 17.5M
    assert rules.min_team_salary == 90_000_000  # 100M * 0.90


# ── Player.get_max_salary_pct 三档 ──
def test_max_salary_pct_yos_under_10_no_all_nba():
    """yos < 10 且非 All-NBA → 0.25。"""
    assert Player("A", 1_000_000, yos=0).get_max_salary_pct() == 0.25
    assert Player("B", 1_000_000, yos=9, is_all_nba=False).get_max_salary_pct() == 0.25


def test_max_salary_pct_yos_under_10_all_nba():
    """yos < 10 且 All-NBA → 0.30。"""
    assert Player("A", 1_000_000, yos=5, is_all_nba=True).get_max_salary_pct() == 0.30
    assert Player("A", 1_000_000, yos=9, is_all_nba=True).get_max_salary_pct() == 0.30


def test_max_salary_pct_yos_10_plus_all_nba():
    """yos >= 10 且 All-NBA → 0.35。"""
    assert Player("A", 1_000_000, yos=10, is_all_nba=True).get_max_salary_pct() == 0.35
    assert Player("A", 1_000_000, yos=20, is_all_nba=True).get_max_salary_pct() == 0.35


def test_max_salary_pct_yos_10_plus_no_all_nba():
    """yos >= 10 但非 All-NBA → 0.25（yos>=10 单独不足以升档）。"""
    assert Player("A", 1_000_000, yos=12, is_all_nba=False).get_max_salary_pct() == 0.25


# ── Team.get_cap_hold 三档 ──
def test_cap_hold_full_bird():
    """yos >= 3 → 1.50x。"""
    t = Team("T")
    p = Player("Vet", 10_000_000, yos=3)
    assert t.get_cap_hold(p) == 15_000_000
    p2 = Player("Vet2", 10_000_000, yos=15)
    assert t.get_cap_hold(p2) == 15_000_000


def test_cap_hold_early_bird():
    """yos >= 2（且 < 3） → 1.25x。"""
    t = Team("T")
    p = Player("EB", 10_000_000, yos=2)
    assert t.get_cap_hold(p) == 12_500_000


def test_cap_hold_non_bird():
    """yos < 2 → 1.20x。"""
    t = Team("T")
    p = Player("Rookie", 10_000_000, yos=1)
    assert t.get_cap_hold(p) == 12_000_000
    p2 = Player("FR", 10_000_000, yos=0)
    assert t.get_cap_hold(p2) == 12_000_000


# ── TradeSimulator.execute_trade 三个分支 ──
def test_execute_trade_second_apron_fail():
    """球队薪资超第二围裙，且接收薪资更高 → 整体失败。"""
    rules = SalaryCapRules()
    over = Team("Celtics")
    # total > second_apron(221.62M)
    over.add_player(Player("Mega1", 250_000_000))  # total=250M
    over.add_player(Player("Cheap1", 1_000_000))
    under = Team("Nets")
    under.add_player(Player("Rich1", 100_000_000))

    # over 视角: total=251M > 221.62M, outgoing=1M, incoming=100M → fail
    ok = TradeSimulator.execute_trade(
        team_a=over,
        team_b=under,
        players_a_to_b=["Cheap1"],
        players_b_to_a=["Rich1"],
        rules=rules,
    )
    assert ok is False
    # roster 应未变化
    assert "Cheap1" in over.roster
    assert "Rich1" in under.roster


def test_execute_trade_first_apron_fail():
    """球队薪资在第一与第二围裙之间（> first_apron, <= second_apron），接收更高 → fail。"""
    rules = SalaryCapRules()
    # first_apron = 210.12M, second_apron = 221.62M
    mid = Team("Mid")
    # total 在 (210.12M, 221.62M] 区间
    mid.add_player(Player("Mid1", 215_000_000))  # total=215M

    counter = Team("Counter")
    counter.add_player(Player("C1", 10_000_000))
    counter.add_player(Player("C2", 5_000_000))  # total=15M

    # mid 不送出, 接收 C1+C2=15M: total=215M > first_apron, incoming(15M) > outgoing(0) → fail
    ok = TradeSimulator.execute_trade(
        team_a=mid,
        team_b=counter,
        players_a_to_b=[],
        players_b_to_a=["C1", "C2"],
        rules=rules,
    )
    assert ok is False
    assert "C1" in counter.roster
    assert "C2" in counter.roster


def test_execute_trade_success():
    """球队薪资在第一围裙之下，正常 trade → 成功。"""
    rules = SalaryCapRules()
    a = Team("A")
    a.add_player(Player("Astar", 30_000_000))
    a.add_player(Player("A1", 10_000_000))  # total=40M

    b = Team("B")
    b.add_player(Player("Bstar", 25_000_000))
    b.add_player(Player("B1", 8_000_000))  # total=33M

    # A 送出 A1(10M), 接收 B1(8M): total=40M < first_apron(210M), 无 apron 限制 → pass
    # B 送出 B1(8M), 接收 A1(10M): total=33M < first_apron, 无 apron 限制 → pass
    ok = TradeSimulator.execute_trade(
        team_a=a,
        team_b=b,
        players_a_to_b=["A1"],
        players_b_to_a=["B1"],
        rules=rules,
    )
    assert ok is True
    assert "A1" in b.roster
    assert "B1" in a.roster
    assert "A1" not in a.roster
    assert "B1" not in b.roster


# ── LeagueSimulator save/load 往返 ──
def test_league_save_load_roundtrip():
    """保存后 load 回的对象应保留规则/球队/球员/cap_holds/repeat_payer 全部信息。"""
    sim = LeagueSimulator()
    sim.rules = SalaryCapRules(base_cap=200_000_000)

    t1 = Team("Bulls")
    t1.add_player(Player("P1", 30_000_000, 5, True, 2))
    t1.add_player(Player("P2", 12_000_000, 2, False, 1))
    t1.cap_holds = {"P1": 45_000_000}
    t1.is_repeat_luxury_payer = True

    t2 = Team("Heat")
    t2.add_player(Player("P3", 20_000_000, 8, False, 3))
    t2.is_repeat_luxury_payer = False

    sim.add_team(t1)
    sim.add_team(t2)

    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "league.json")
        sim.save_league(path)

        # 确认文件存在
        assert os.path.exists(path)

        loaded = LeagueSimulator.load_league(path)

        # rules 保留
        assert loaded.rules.base_cap == 200_000_000
        assert loaded.rules.luxury_tax_line == int(200_000_000 * 1.215)
        assert loaded.rules.first_apron == loaded.rules.luxury_tax_line + 6_000_000

        # 球队保留
        assert set(loaded.teams.keys()) == {"Bulls", "Heat"}

        # roster 字段
        bulls = loaded.teams["Bulls"]
        assert "P1" in bulls.roster
        p1 = bulls.roster["P1"]
        assert p1.name == "P1"
        assert p1.salary == 30_000_000
        assert p1.yos == 5
        assert p1.is_all_nba is True
        assert p1.contract_years_left == 2
        # add_player 会更新 bird_rights_with_team
        assert p1.bird_rights_with_team == "Bulls"

        # cap_holds 保留
        assert bulls.cap_holds == {"P1": 45_000_000}

        # repeat_payer 保留
        assert bulls.is_repeat_luxury_payer is True
        assert loaded.teams["Heat"].is_repeat_luxury_payer is False

        # heat roster
        heat = loaded.teams["Heat"]
        assert "P3" in heat.roster
        assert heat.roster["P3"].salary == 20_000_000


def test_league_season_summary_runs(capsys):
    """season_summary 不抛异常并打印围裙/奢侈税状态。"""
    sim = LeagueSimulator()
    rich = Team("Rich")
    rich.add_player(Player("X", 230_000_000))  # > second_apron
    sim.add_team(rich)
    healthy = Team("Healthy")
    healthy.add_player(Player("Y", 50_000_000))  # < luxury_tax_line
    sim.add_team(healthy)

    sim.season_summary()
    out = capsys.readouterr().out
    assert "第二围裙违规" in out
    assert "健康" in out
    assert "Rich" in out
    assert "Healthy" in out
