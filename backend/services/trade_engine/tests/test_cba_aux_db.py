"""NBACore v8 — cba_aux_db 接入层测试（真实 DB）。

覆盖 load_salary_rules / load_team / load_player / load_trades / load_league，
并对 cba_aux_db.py 做 v8 §6 自检（零 SQL 子串）。

DB 不可用时整体跳过（conftest.skip_if_no_db）。
"""
from __future__ import annotations

import inspect
import os

import pytest

from backend.services.trade_engine import cba_aux_db
from backend.services.trade_engine.cba_aux_db import (
    TradeRecord,
    TradeSemantics,
    load_league,
    load_player,
    load_salary_rules,
    load_team,
    load_trades,
    parse_trade_semantics,
)
from backend.services.trade_engine.cba_aux import LeagueSimulator, Player, SalaryCapRules, Team
from backend.services.trade_engine.llm_provider import LLMProvider

from .conftest import skip_if_no_db


class FakeProvider(LLMProvider):
    """返回固定 dict 的假 provider（测试 LLM 优先路径用）。"""

    provider_name = "fake"

    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload or {
            "counterparties": ["GSW", "MIN"],
            "players_out": ["D'Angelo Russell"],
            "players_in": ["Andrew Wiggins"],
            "picks": [],
            "cash": None,
            "notes": "",
        }

    def parse_trade(self, text: str, team_abbr: str | None = None) -> dict:
        return dict(self.payload)


# 已知 DB 实测值（主理人核实，2025-26）
GSW_TOTAL_2025_26 = 204_744_987
CURRY_SALARY = 59_606_817
CURRY_YOS = 19  # max(0, 38 - 19)
SALARY_CAP = 154_647_000
LUXURY_TAX = 187_895_000
FIRST_APRON = 195_945_000
SECOND_APRON = 207_824_000
MIN_TEAM_SALARY = 139_182_000


@skip_if_no_db
def test_load_salary_rules():
    """返回 SalaryCapRules 且四个阈值等于 DB 实测值。"""
    rules = load_salary_rules("2025-26")
    assert isinstance(rules, SalaryCapRules)
    assert rules.base_cap == SALARY_CAP
    assert rules.luxury_tax_line == LUXURY_TAX
    assert rules.first_apron == FIRST_APRON
    assert rules.second_apron == SECOND_APRON
    assert rules.min_team_salary == MIN_TEAM_SALARY


@skip_if_no_db
def test_load_team_gsw():
    """Team('GSW') roster 非空，payroll == team_payroll.total_2025_26。"""
    team = load_team("GSW", "2025-26")
    assert isinstance(team, Team)
    assert team.name == "GSW"
    assert team.roster, "GSW roster 不应为空"
    assert getattr(team, "payroll", None) == GSW_TOTAL_2025_26


@skip_if_no_db
def test_load_player_curry():
    """Stephen Curry: salary==59606817, yos==19（age 38 - 19）。"""
    p = load_player("GSW", "Stephen Curry", "2025-26")
    assert isinstance(p, Player)
    assert p.name == "Stephen Curry"
    assert p.salary == CURRY_SALARY
    assert p.yos == CURRY_YOS
    assert p.is_all_nba is False


@skip_if_no_db
def test_load_trades_all():
    """全量交易非空；至少一条抽出 >=2 个对手方缩写。"""
    trades = load_trades()
    assert isinstance(trades, list) and trades
    assert all(isinstance(t, TradeRecord) for t in trades)
    multi = [t for t in trades if len(t.counterparties) >= 2]
    assert multi, "应至少有一条交易抽出 >=2 个对手方缩写"
    assert all(t.description for t in trades)


@skip_if_no_db
def test_load_trades_filter_bos():
    """按 team_abbr='BOS' 过滤：仅返回 BOS 相关，且非空。"""
    bos = load_trades(team_abbr="BOS")
    assert bos, "BOS 应有交易记录"
    assert all(t.team_abbr == "BOS" for t in bos)


@skip_if_no_db
def test_parse_trade_semantics_schema(monkeypatch):
    """parse_trade_semantics 返回 TradeSemantics；raw_text 保留；列表字段为 list（LLM 优先，确定性）。"""
    monkeypatch.setattr(cba_aux_db, "get_provider", lambda: FakeProvider())
    sample = (
        "The Golden State Warriors traded D'Angelo Russell to the "
        "Minnesota Timberwolves for Andrew Wiggins."
    )
    sem = parse_trade_semantics(sample, team_abbr="GSW")
    assert isinstance(sem, TradeSemantics)
    assert isinstance(sem.counterparties, list)
    assert isinstance(sem.players_out, list)
    assert isinstance(sem.players_in, list)
    assert isinstance(sem.picks, list)
    assert sem.raw_text == sample


@skip_if_no_db
def test_parse_trade_semantics_llm_first(monkeypatch):
    """LLM 优先：FakeProvider 填 players，parse 应返回 players 而非走正则空值。"""
    monkeypatch.setattr(cba_aux_db, "get_provider", lambda: FakeProvider())
    sample = (
        "The Golden State Warriors traded D'Angelo Russell to the "
        "Minnesota Timberwolves for Andrew Wiggins."
    )
    sem = parse_trade_semantics(sample, team_abbr="GSW")
    assert sem.players_out == ["D'Angelo Russell"]
    assert sem.players_in == ["Andrew Wiggins"]
    assert sem.counterparties == ["GSW", "MIN"]
    assert sem.raw_text == sample


@skip_if_no_db
def test_load_trades_include_semantics(monkeypatch):
    """include_semantics=True：GSW 记录均附 semantics，且 raw_text == description。

    注：LLM 优先后 load_trades(include_semantics=True) 会触发实时 parse；
    为避免依赖缓慢/不可达的 Ollama 使既有测试变慢或抖动，这里用 FakeProvider
    固定解析结果（验证“附 semantics + raw_text 保留”契约，行为与旧版一致）。
    """
    monkeypatch.setattr(cba_aux_db, "get_provider", lambda: FakeProvider())
    gsw = load_trades(team_abbr="GSW", include_semantics=True)
    assert gsw, "GSW 应有交易记录"
    assert all(t.semantics is not None for t in gsw)
    assert all(isinstance(t.semantics, TradeSemantics) for t in gsw)
    assert all(t.semantics.raw_text == t.description for t in gsw)
    # 默认 False 行为不变：旧调用不应带 semantics（显式复核）
    gsw_default = load_trades(team_abbr="GSW")
    assert all(t.semantics is None for t in gsw_default)


@skip_if_no_db
def test_load_league():
    """LeagueSimulator 球队数 == team_payroll 行数（30）。"""
    sim = load_league("2025-26")
    assert isinstance(sim, LeagueSimulator)
    assert len(sim.teams) == 30


@skip_if_no_db
def test_analyze_trade_semantics_persists(monkeypatch):
    """analyze 写 trade_semantics 落表；exists + get 正确；测试后清理。"""
    from backend.services.trade_engine import trade_semantics_db

    fake_rows = [
        {
            "id": 999001,
            "transaction_date": "2024-01-01",
            "team_abbr": "GSW",
            "description": (
                "Golden State Warriors traded James Wiseman to Detroit "
                "Pistons for a 2023 second-round pick"
            ),
        },
        {
            "id": 999002,
            "transaction_date": "2024-01-02",
            "team_abbr": "BOS",
            "description": (
                "Boston Celtics traded Marcus Smart to Memphis Grizzlies "
                "for Kristaps Porzingis"
            ),
        },
    ]
    # 用 FakeProvider 避免真实 Ollama；用假 2 行避免全量 904 条
    monkeypatch.setattr(cba_aux_db.db, "get_trades", lambda *a, **k: fake_rows)
    monkeypatch.setattr(cba_aux_db, "get_provider", lambda: FakeProvider())

    result = cba_aux_db.analyze_trade_semantics(force=True)
    assert result["total"] == 2
    assert result["parsed"] == 2
    assert result["failed"] == 0

    for r in fake_rows:
        ref = str(r["id"])
        assert trade_semantics_db.exists_source_ref(ref) is True
        rec = trade_semantics_db.get_trade_semantics(ref)
        assert rec is not None
        assert rec["source_ref"] == ref
        assert isinstance(rec["players_out"], list)
        assert rec["model"] == "FakeProvider"
    # 清理测试写入
    for r in fake_rows:
        trade_semantics_db.delete_trade_semantics(str(r["id"]))
    for r in fake_rows:
        assert trade_semantics_db.exists_source_ref(str(r["id"])) is False


# ── v8 §6 自检：cba_aux_db.py 与本测试文件均不得含 SQL 子串 ──
def _forbidden_substrings():
    # 用拼接避免本文件出现字面 SQL 子串（满足 §6 自检对“本文件”的要求）
    return [
        "SE" + "LECT ",
        "IN" + "SERT ",
        "UP" + "DATE ",
        "DE" + "LETE ",
        "CR" + "EATE ",
    ]


def test_section6_no_sql_substrings():
    """cba_aux_db.py 与当前测试文件均不得含 SELECT/INSERT/UPDATE/DELETE/CREATE，等 SQL 关键字子串。"""
    forbidden = _forbidden_substrings()
    here = os.path.dirname(os.path.abspath(__file__))
    targets = [
        os.path.join(here, "..", "cba_aux_db.py"),
        os.path.abspath(inspect.getfile(inspect.currentframe())),
    ]
    for path in targets:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        for sub in forbidden:
            assert sub not in text, f"{os.path.basename(path)} 含被禁子串 {sub!r}"
