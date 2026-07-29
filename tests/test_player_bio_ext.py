"""common/player_bio_ext.py 离线单元测试（不联网、不直接依赖 5433 PG 写操作）。

覆盖:
  * ``extract_relatives`` / ``extract_aba_debut`` / ``extract_died`` /
    ``extract_hof`` / ``extract_career_length`` / ``extract_jersey_numbers`` /
    ``extract_honors`` / ``parse_honor_line`` / ``extract_all``：
    对 tests/fixtures/ 三个真实 BR 球员页快照断言（选择器固化回归基线）。
    - br_julius_erving.html (ervinju01): 全维度 + 13 条荣誉 + 号码 32/6
    - br_kobebry01.html (bryanko01): 已故（died=2020-01-26）+ 荣誉 + 号码
    - br_erninca01.html (grunfer01): 极简（无 #bling、无号码块、无 HOF）
  * ``upsert_player_bio_ext``：用 mock 连接验证「同事务 UPDATE + DELETE/INSERT」。
  * DDL 007 幂等：连跑两次不报错（DB 可用时实测；否则静态断言 IF NOT EXISTS）。

所有网络均不发生；DB 仅在 DDL 幂等测试（可跳过）中做只读式幂等执行。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

from common import player_bio_ext as bx

FIX = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


JULIUS = _load("br_julius_erving.html")
KOBE = _load("br_kobebry01.html")
ERNIE = _load("br_erninca01.html")


# ── extract_relatives ──────────────────────────────────────────────────────
def test_relatives_julius():
    assert bx.extract_relatives(JULIUS) == "Cousin Jeff Halliburton"


def test_relatives_kobe_has_multiple():
    # Kobe: 分号分隔的多亲属
    assert bx.extract_relatives(KOBE) == "Father Joe Bryant ; Uncle Chubby Cox"


def test_relatives_ernie_none():
    assert bx.extract_relatives(ERNIE) is None


def test_relatives_empty_html():
    assert bx.extract_relatives("") is None
    assert bx.extract_relatives(None) is None


# ── extract_aba_debut ──────────────────────────────────────────────────────
def test_aba_debut_julius():
    # Julius 与 NBA Debut 同处一行 "NBA Debut: ... ▪ ABA Debut: October 15, 1971"
    assert bx.extract_aba_debut(JULIUS) == date(1971, 10, 15)


def test_aba_debut_no_aba_returns_none():
    assert bx.extract_aba_debut(KOBE) is None
    assert bx.extract_aba_debut(ERNIE) is None


# ── extract_died（仅已故球员）────────────────────────────────────────────────
def test_died_kobe():
    assert bx.extract_died(KOBE) == date(2020, 1, 26)


def test_died_alive_returns_none():
    # Julius 在世 → None（切勿误填）
    assert bx.extract_died(JULIUS) is None
    assert bx.extract_died(ERNIE) is None


# ── extract_hof ────────────────────────────────────────────────────────────
def test_hof_julius():
    assert bx.extract_hof(JULIUS) == (1993, "Player")


def test_hof_kobe():
    assert bx.extract_hof(KOBE) == (2020, "Player")


def test_hof_not_hof_returns_none():
    assert bx.extract_hof(ERNIE) == (None, None)


# ── extract_career_length ──────────────────────────────────────────────────
def test_career_length():
    assert bx.extract_career_length(JULIUS) == 16
    assert bx.extract_career_length(KOBE) == 20
    assert bx.extract_career_length(ERNIE) == 9


# ── extract_jersey_numbers ─────────────────────────────────────────────────
def test_jersey_julius_deduped():
    # 实测 uni_holder svg texts = ['32','32','6','6'] → 去重
    assert bx.extract_jersey_numbers(JULIUS) == ["32", "6"]


def test_jersey_kobe_deduped():
    assert bx.extract_jersey_numbers(KOBE) == ["24", "33", "8", "10"]


def test_jersey_ernie_deduped():
    assert bx.extract_jersey_numbers(ERNIE) == ["20", "18"]


# ── parse_honor_line（纯函数）────────────────────────────────────────────────
def test_parse_honor_hall_of_fame_no_year():
    h = bx.parse_honor_line("Hall of Fame")
    assert h["honor_type"] == "hall_of_fame"
    assert h["honor_year"] is None
    assert h["honor_count"] is None


def test_parse_honor_hall_of_fame_with_year():
    h = bx.parse_honor_line("Hall of Fame", hof_year=1993)
    assert h["honor_type"] == "hall_of_fame"
    assert h["honor_year"] == 1993


def test_parse_honor_all_star_count():
    h = bx.parse_honor_line("16x All Star")
    assert h == {
        "honor_raw": "16x All Star",
        "honor_type": "all_star",
        "honor_count": 16,
        "honor_year": None,
        "honor_detail": None,
    }


def test_parse_honor_nba_champ_year():
    h = bx.parse_honor_line("1983 NBA Champ")
    assert h["honor_type"] == "nba_champ"
    assert h["honor_year"] == 1983
    assert h["honor_count"] is None


def test_parse_honor_aba_champ_count():
    h = bx.parse_honor_line("2x ABA Champ")
    assert h["honor_type"] == "aba_champ"
    assert h["honor_count"] == 2


def test_parse_honor_all_rookie_year():
    h = bx.parse_honor_line("1971-72 All-Rookie")
    assert h["honor_type"] == "all_rookie"
    assert h["honor_year"] == 1972


def test_parse_honor_as_mvp_and_finals_mvp():
    assert bx.parse_honor_line("2x AS MVP")["honor_type"] == "as_mvp"
    fm = bx.parse_honor_line("2x Finals MVP")
    assert fm["honor_type"] == "mvp"
    assert fm["honor_count"] == 2


def test_parse_honor_teams_and_poy():
    assert bx.parse_honor_line("ABA All-Time Team")["honor_type"] == "aba_all_time_team"
    n75 = bx.parse_honor_line("NBA 75th Anniv. Team")
    assert n75["honor_type"] == "nba_75_team"
    assert n75["honor_detail"] == "Team"
    assert bx.parse_honor_line("2x MBWA ABA POY")["honor_type"] == "mbwa_aba_poy"


def test_parse_honor_falls_to_other():
    # 无对应枚举 → other（如 Scoring Champ / Oscar）
    assert bx.parse_honor_line("2x Scoring Champ")["honor_type"] == "other"
    assert bx.parse_honor_line("2018 Oscar")["honor_type"] == "other"


# ── extract_honors（#bling 整块）─────────────────────────────────────────────
def test_honors_julius_full():
    honors = bx.extract_honors(JULIUS, hof_year=1993)
    by_raw = {h["honor_raw"]: h for h in honors}
    assert len(honors) == 13
    assert by_raw["Hall of Fame"]["honor_type"] == "hall_of_fame"
    assert by_raw["Hall of Fame"]["honor_year"] == 1993  # 由 hof_year 注入
    assert by_raw["16x All Star"] == {
        "honor_raw": "16x All Star",
        "honor_type": "all_star",
        "honor_count": 16,
        "honor_year": None,
        "honor_detail": None,
    }
    assert by_raw["1983 NBA Champ"]["honor_year"] == 1983
    assert by_raw["2x ABA Champ"]["honor_type"] == "aba_champ"
    assert by_raw["7x All-NBA"]["honor_count"] == 7
    assert by_raw["5x All-ABA"]["honor_type"] == "all_aba"
    assert by_raw["1971-72 All-Rookie"]["honor_year"] == 1972
    assert by_raw["4x MVP"]["honor_type"] == "mvp"
    assert by_raw["1975-76 All-Defensive"]["honor_type"] == "all_defensive"
    assert by_raw["2x AS MVP"]["honor_type"] == "as_mvp"
    assert by_raw["ABA All-Time Team"]["honor_type"] == "aba_all_time_team"
    assert by_raw["NBA 75th Anniv. Team"]["honor_type"] == "nba_75_team"
    assert by_raw["2x MBWA ABA POY"]["honor_type"] == "mbwa_aba_poy"


def test_honors_ernie_empty():
    # Ernie 无 #bling → 空列表
    assert bx.extract_honors(ERNIE) == []


# ── extract_all（汇总）───────────────────────────────────────────────────────
def test_extract_all_julius():
    d = bx.PlayerBioExtExtractor.extract_all(JULIUS)
    assert d["aba_debut"] == date(1971, 10, 15)
    assert d["died"] is None
    assert d["hof_inducted_year"] == 1993
    assert d["hof_as"] == "Player"
    assert d["is_hall_of_famer"] is True
    assert d["career_length_years"] == 16
    assert d["relatives"] == "Cousin Jeff Halliburton"
    assert d["jersey_numbers"] == ["32", "6"]
    assert isinstance(d["career_honors_text"], list)
    assert "Hall of Fame" in d["career_honors_text"]
    assert len(d["honors"]) == 13
    # career_honors_text 是 honors 的 honor_raw 去重镜像
    assert d["career_honors_text"] == [h["honor_raw"] for h in d["honors"]]


def test_extract_all_kobe_died_and_hof():
    d = bx.PlayerBioExtExtractor.extract_all(KOBE)
    assert d["died"] == date(2020, 1, 26)
    assert d["hof_inducted_year"] == 2020
    assert d["is_hall_of_famer"] is True
    assert d["jersey_numbers"] == ["24", "33", "8", "10"]
    assert len(d["honors"]) > 0


def test_extract_all_ernie_minimal():
    d = bx.PlayerBioExtExtractor.extract_all(ERNIE)
    assert d["aba_debut"] is None
    assert d["died"] is None
    assert d["hof_inducted_year"] is None
    assert d["is_hall_of_famer"] is False
    assert d["relatives"] is None
    assert d["jersey_numbers"] == ["20", "18"]
    assert d["honors"] == []
    assert d["career_honors_text"] is None


# ── upsert_player_bio_ext（mock 连接）────────────────────────────────────────
def _fake_conn():
    conn = mock.MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    return conn, cur


def test_upsert_writes_dim_and_honors_in_one_txn():
    data = {
        "aba_debut": date(1971, 10, 15),
        "died": None,
        "hof_inducted_year": 1993,
        "hof_as": "Player",
        "is_hall_of_famer": True,
        "career_length_years": 16,
        "relatives": "Cousin Jeff Halliburton",
        "jersey_numbers": ["32", "6"],
        "career_honors_text": ["Hall of Fame", "16x All Star"],
        "honors": [
            {"honor_raw": "Hall of Fame", "honor_type": "hall_of_fame",
             "honor_count": None, "honor_year": 1993, "honor_detail": None},
            {"honor_raw": "16x All Star", "honor_type": "all_star",
             "honor_count": 16, "honor_year": None, "honor_detail": None},
        ],
    }
    conn, cur = _fake_conn()
    bx.upsert_player_bio_ext(conn, "ervinju01", data, source_url="http://x")

    # 1) UPDATE dim_players 被调用，且参数正确
    upd = [c for c in cur.execute.call_args_list if "UPDATE public.dim_players" in c.args[0]]
    assert upd, "UPDATE dim_players 必须被调用"
    params = upd[0].args[1]
    assert params["jersey_numbers"] == ["32", "6"]
    assert params["career_honors_text"] == ["Hall of Fame", "16x All Star"]
    assert params["is_hall_of_famer"] is True
    assert params["player_id"] == "ervinju01"

    # 2) DELETE player_career_honors 被调用
    dele = [c for c in cur.execute.call_args_list if "DELETE FROM public.player_career_honors" in c.args[0]]
    assert dele, "DELETE 必须先于 INSERT"

    # 3) 每条荣誉一次 INSERT
    ins = [c for c in cur.execute.call_args_list if "INSERT INTO public.player_career_honors" in c.args[0]]
    assert len(ins) == 2
    assert ins[0].args[1] == ("ervinju01", "Hall of Fame", "hall_of_fame", None, 1993, None, "http://x")
    assert ins[1].args[1] == ("ervinju01", "16x All Star", "all_star", 16, None, None, "http://x")

    # 4) 提交一次（自治事务）
    conn.commit.assert_called_once()


def test_upsert_rollback_on_error():
    data = {"honors": []}
    conn, cur = _fake_conn()
    cur.execute.side_effect = Exception("boom")
    with pytest.raises(Exception):
        bx.upsert_player_bio_ext(conn, "x01", data)
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


# ── DDL 007 幂等 ─────────────────────────────────────────────────────────────
def _db_conn_or_skip():
    from backend.core.db import is_port_open, ping
    if not (is_port_open() and ping()):
        pytest.skip("PostgreSQL not available — set DB_PORT and start service")
    from backend.core import config
    import psycopg2
    return psycopg2.connect(config.db_dsn())


def test_migration_007_file_is_idempotent_markers():
    sql_path = ROOT / "sql" / "007_add_player_bio_ext.sql"
    content = sql_path.read_text(encoding="utf-8")
    # 静态断言：所有 DDL 均为幂等写法
    assert "ADD COLUMN IF NOT EXISTS" in content
    assert "CREATE TABLE IF NOT EXISTS" in content
    assert "CREATE INDEX IF NOT EXISTS" in content
    assert "DROP VIEW IF EXISTS" in content
    assert "COMMENT ON COLUMN" in content  # 正确拼写（非误写的 COMMENT）


def test_migration_007_runs_twice_idempotent():
    conn = _db_conn_or_skip()
    sql_path = ROOT / "sql" / "007_add_player_bio_ext.sql"
    content = sql_path.read_text(encoding="utf-8")
    try:
        cur = conn.cursor()
        cur.execute(content)
        conn.commit()
        # 第二次执行必须不报错（幂等）
        cur.execute(content)
        conn.commit()
        cur.close()
    finally:
        conn.close()
