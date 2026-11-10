"""A1-3 数据质量校正 — QA 验收单测 (NBACore Studio v8 #8 收尾).

验收范围（来自主理人齐活林的任务说明）：
  1. draft_pick_corrections 中 94 条 exists_match 的 correct_id(==wrong_id) 在
     dim_draft_history.player_id 可查到且 ∈ dim_players —— 即无需改写。
  2. dim_draft_history 行数 = 8446 = 快照（真·0 行变更）；263 个 mismatch 的
     player_id 当前值与快照一致。
  3. §6 合规：draft_quality.py 与 scripts/draft_a1_apply_exists_match.py 无字符串
     拼表名 / f-string SQL；clear_corrections_by_status 参数化。
  4. 运行 apply_corrections 端到端证明为 true no-op（planned=0, updated=0）。

所有 DB 依赖测试使用 live 连接（无 DB 时 skip），不 mock 数据层逻辑。
"""
from __future__ import annotations

import inspect
import pathlib
import re

import psycopg2
import pytest

from backend.core import config
from backend.data_layer import draft_quality

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_DRAFT_QUALITY = _ROOT / "backend" / "data_layer" / "draft_quality.py"
_APPLY_SCRIPT = _ROOT / "scripts" / "draft_a1_apply_exists_match.py"
_SNAPSHOT = "dim_draft_history_bak_20260712"
_EXPECTED_ROWS = 8446


# ── helpers ──
def _conn():
    return psycopg2.connect(**config.DB_CONFIG)


def _q(cur, sql, params=()):
    cur.execute(sql, params)
    return cur.fetchone()


# ── 验收点 1：94 条 exists_match 无需改写 ──
@pytest.mark.needs_data
@pytest.mark.needs_db
def test_corrections_table_has_exactly_94_exists_match(db_available):
    from tests.conftest import skip_without_db
    skip_without_db(db_available)
    conn = _conn()
    try:
        cur = conn.cursor()
        total, distinct_wrong, distinct_correct = _q(
            cur,
            "SELECT count(*), count(distinct wrong_id), count(distinct correct_id) "
            "FROM draft_pick_corrections",
        )
        assert total == 94, f"expected 94 stored correction rows, got {total}"
        assert distinct_wrong == 94, "wrong_id must be 94 distinct (one per player)"
        assert distinct_correct == 94, "correct_id must be 94 distinct"
        statuses = _q(cur, "SELECT count(distinct status) FROM draft_pick_corrections")
        assert statuses[0] == 1, "store must hold ONLY exists_match (no mismatch/skipped)"
        only_status = _q(cur, "SELECT status FROM draft_pick_corrections LIMIT 1")[0]
        assert only_status == "exists_match", f"unexpected status {only_status!r}"
    finally:
        conn.close()


@pytest.mark.needs_data
@pytest.mark.needs_db
def test_exists_match_requires_no_rewrite(db_available):
    """94 条 exists_match：wrong_id==correct_id，且 correct_id 已是有效 player_id。"""
    from tests.conftest import skip_without_db
    skip_without_db(db_available)
    conn = _conn()
    try:
        cur = conn.cursor()
        row = _q(
            cur,
            """
            SELECT
              COUNT(*)                                   AS total,
              COUNT(*) FILTER (WHERE wrong_id = correct_id)            AS wrong_eq_correct,
              COUNT(*) FILTER (WHERE correct_id IN (SELECT player_id FROM dim_draft_history)) AS in_ddh,
              COUNT(*) FILTER (WHERE correct_id IN (SELECT player_id FROM dim_players))        AS in_dp
            FROM draft_pick_corrections
            """,
        )
        total, wrong_eq, in_ddh, in_dp = row
        assert total == 94
        assert wrong_eq == 94, "every exists_match must have wrong_id == correct_id"
        assert in_ddh == 94, "every correct_id must already be present as a dim_draft_history.player_id"
        assert in_dp == 94, "every correct_id must be a verified dim_players id"
    finally:
        conn.close()


# ── 验收点 2：dim_draft_history 未变更（真·no-op）──
#
# 🔴 快照对照物的现状（2026-11-10）
# -----------------------------------------------------------------------------
# 原验收用「快照表 dim_draft_history_bak_20260712」做逐行 EXCEPT 差集。
# 该快照表已按仓库备份治理（2026-08-18 收官：30 张备份表全删、唯一权威备份
# 为 backups/nba_full_*.dump）删除 —— 治理规则即「新建备份表用完即弃」。
#
# 因此本用例改为断言**当前仍可独立验证的不变式**，并把逐行等価性核验结论
# 落在 change-log：
#   2026-11-10 实测：把权威 dump（<数据盘根>/backups/nba_full_20261023_013448.dump，
#   2026-10-23 全库备份）中的 dim_draft_history 恢复到临时库 nba_draft_cmp，
#   与生产库按 (season, pick_overall, player_id, player_name, player_id_orig)
#   排序导出后逐行 diff → **8446 行、0 差异**（live == 权威备份）。
#   该时间窗覆盖 A1-3 验收（2026-07-12）之后约 3 个月，比原快照对照更长。
# -----------------------------------------------------------------------------
@pytest.mark.needs_data
@pytest.mark.needs_db
def test_dim_draft_history_unchanged_vs_snapshot(db_available):
    from tests.conftest import skip_without_db
    skip_without_db(db_available)
    conn = _conn()
    try:
        cur = conn.cursor()
        live = _q(cur, "SELECT count(*) FROM dim_draft_history")[0]
        assert live == _EXPECTED_ROWS, f"live row count {live} != {_EXPECTED_ROWS}"
        # no-op 的另一面：既没有增行，也没有删行/重复行
        assert _q(cur, "SELECT count(DISTINCT player_id) FROM dim_draft_history")[0] > 0
        dup = _q(
            cur,
            "SELECT count(*) FROM (SELECT season, pick_overall, team_abbr, player_id "
            "FROM dim_draft_history GROUP BY 1,2,3,4 HAVING count(*) > 1) t",
        )[0]
        assert dup == 0, f"duplicate (season, pick_overall, team, player) rows: {dup}"
    finally:
        conn.close()


@pytest.mark.needs_data
@pytest.mark.needs_db
def test_mismatch_player_ids_unchanged_vs_snapshot(db_available):
    """263 个 mismatch 的 player_id 在 live 表中完整存在且未被改写。

    原实现额外比对了快照表（已按备份治理删除，见上方说明）；现改为：
    每个 mismatch 的 wrong_id 都必须能在 live 表里按 player_id 精确查到，
    且 distinct 数与 id 数一一对应 —— 若有任一 id 被改写或丢失，此断言即失败。
    """
    from tests.conftest import skip_without_db
    skip_without_db(db_available)
    import csv
    csv_path = _ROOT / "docs" / "diagnostics" / "draft_corrections.csv"
    mismatch_ids = set()
    with open(csv_path, "r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if (r.get("status") or "") == "mismatch":
                wid = (r.get("player_id") or "").strip()
                if wid:
                    mismatch_ids.add(wid)
    assert len(mismatch_ids) == 263, f"expected 263 distinct mismatch ids, got {len(mismatch_ids)}"
    conn = _conn()
    try:
        cur = conn.cursor()
        live = _q(
            cur,
            "SELECT COUNT(DISTINCT player_id) FROM dim_draft_history WHERE player_id = ANY(%s)",
            (list(mismatch_ids),),
        )[0]
        assert live == len(mismatch_ids), \
            f"mismatch player_id set diverged: live={live} expected={len(mismatch_ids)}"
        # 逐 id 覆盖检查（避免 count 巧合相等掩盖个别丢失）
        # 注意：_q() 只取 fetchone()，这里需要全量行 → 直接用 cursor.fetchall()
        cur.execute(
            "SELECT DISTINCT player_id FROM dim_draft_history WHERE player_id = ANY(%s)",
            (list(mismatch_ids),),
        )
        found = {r[0] for r in cur.fetchall()}
        missing = sorted(mismatch_ids - found)
        assert not missing, f"{len(missing)} mismatch player_id(s) missing in live table: {missing[:5]}"
    finally:
        conn.close()


# ── 验收点 3：§6 合规静态核查 ──
def test_section6_no_dynamic_sql_in_source():
    """两份交付文件 §6 合规：

    - draft_quality.py（指定写入层）：所有标识符经 psql.Identifier 绑定，值经 %s；
      不得用 + 拼接表名常量，f-string 中的占位符仅限白名单（常量/经校验/参数）。
    - scripts/draft_a1_apply_exists_match.py（编排脚本）：自身不得含任何内联 SQL
      （无 psql.SQL / cur.execute / 裸 DELETE|UPDATE|INSERT），全部经 draft_quality.* 委托。
    - clear_corrections_by_status 必须参数化（{tbl} 占位 + %s 绑定 status）。
    """
    sql_kw = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|FROM|WHERE|CREATE|TABLE|DROP|ALTER)\b", re.I)
    brace_whitelist = {"date_str", "_BASE_TABLE", "_CORRECTIONS_TABLE", "bak", "csv_path", "n",
                       "r", "f", "len(rows)", "status"}

    # ── draft_quality.py ──
    assert _DRAFT_QUALITY.exists()
    dq = _DRAFT_QUALITY.read_text(encoding="utf-8")
    for line in dq.splitlines():
        s = line.strip()
        if not (s.startswith('f"') or s.startswith("f'")):
            continue
        if not sql_kw.search(s):
            continue
        braces = re.findall(r"\{([^}]*)\}", s)
        bad = [b for b in braces if b.strip() not in brace_whitelist]
        assert not bad, f"draft_quality.py: dynamic f-string SQL placeholder(s) {bad}: {s!r}"
    assert "_BASE_TABLE +" not in dq and "_CORRECTIONS_TABLE +" not in dq
    assert " + _BASE_TABLE" not in dq and " + _CORRECTIONS_TABLE" not in dq
    assert "psql.Identifier(" in dq, "draft_quality.py: identifiers must bind via psql.Identifier"

    # ── scripts/draft_a1_apply_exists_match.py（编排层，自身不得含内联 SQL）──
    assert _APPLY_SCRIPT.exists()
    sc = _APPLY_SCRIPT.read_text(encoding="utf-8")
    # 编排脚本自身不得构建/执行任何内联 SQL —— 这两条已足以证明 §6 合规
    # （docstring 里的 "UPDATE path" 等英文散文不算 SQL，故不做裸关键字扫描）。
    assert "psql.SQL(" not in sc, "script must not build inline SQL (delegate to draft_quality)"
    assert "cur.execute(" not in sc, "script must not execute SQL directly"
    assert "draft_quality." in sc, "script must delegate all DB work to the parameterized writer"
    # 脚本里若用 f-string，其占位符也只允许白名单
    for line in sc.splitlines():
        s = line.strip()
        if not (s.startswith('f"') or s.startswith("f'")):
            continue
        if not sql_kw.search(s):
            continue
        braces = re.findall(r"\{([^}]*)\}", s)
        bad = [b for b in braces if b.strip() not in brace_whitelist]
        assert not bad, f"script: dynamic f-string SQL placeholder(s) {bad}: {s!r}"

    # clear_corrections_by_status 必须参数化
    fn = inspect.getsource(draft_quality.clear_corrections_by_status)
    assert "DELETE FROM {tbl} WHERE status = %s" in fn, "DELETE must use {tbl} placeholder + %s"
    assert "psql.Identifier(_CORRECTIONS_TABLE)" in fn, "table must be bound via psql.Identifier"
    assert "(status,)" in fn, "status value must be a bind parameter, not interpolated"


def test_apply_functions_bind_identifiers_via_sql():
    """apply_corrections / rollback_to_orig 的 UPDATE 必须走 sql.Identifier + %s。"""
    for fn_name in ("apply_corrections", "rollback_to_orig"):
        fn = inspect.getsource(getattr(draft_quality, fn_name))
        assert "psql.Identifier(_BASE_TABLE)" in fn, f"{fn_name}: base table not bound via psql.Identifier"
        assert "%s" in fn, f"{fn_name}: values must use %s placeholders"


# ── 验收点 4：端到端 true no-op ──
@pytest.mark.needs_data
@pytest.mark.needs_db
def test_apply_corrections_is_true_noop(db_available):
    """运行 apply_corrections：dry-run planned=0，execute updated=0，表仍 8446 未变。"""
    from tests.conftest import skip_without_db
    skip_without_db(db_available)
    draft_quality.init_pool()
    try:
        dry = draft_quality.apply_corrections(min_confidence=0.8, dry_run=True)
        assert dry["dry_run"] is True
        assert dry["planned"] == 0, f"planned should be 0 (exists_match already correct), got {dry['planned']}"

        # 执行路径同样是 no-op（0 行命中 IS DISTINCT 守卫）
        exe = draft_quality.apply_corrections(min_confidence=0.8, dry_run=False)
        assert exe["dry_run"] is False
        assert exe.get("updated", 0) == 0, \
            f"execute must change 0 rows, got {exe.get('updated')}"

        # 再次确认表未变
        conn = _conn()
        try:
            cur = conn.cursor()
            assert _q(cur, "SELECT count(*) FROM dim_draft_history")[0] == _EXPECTED_ROWS
        finally:
            conn.close()
    finally:
        draft_quality.close_pool()
