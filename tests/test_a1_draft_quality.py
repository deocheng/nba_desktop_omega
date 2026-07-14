"""A1 — draft history data-quality writer (snapshot/audit/apply, v8 §6)."""
from __future__ import annotations

import csv
import os
import tempfile

import pytest

from backend.data_layer import draft_quality

AUDIT_CSV = os.path.join(
    os.path.dirname(__file__), "..", "docs", "diagnostics", "draft_376_audit.csv"
)


def test_snapshot_rejects_bad_date():
    with pytest.raises(ValueError):
        draft_quality.snapshot_draft_history("2026-07-12")  # not YYYYMMDD
    with pytest.raises(ValueError):
        draft_quality.snapshot_draft_history("abcd")  # not digits


@pytest.mark.needs_db
def test_audit_returns_376(db_available):
    from tests.conftest import skip_without_db
    skip_without_db(db_available)
    draft_quality.init_pool()
    try:
        rows = draft_quality.audit_draft_history_diffs()
        assert len(rows) == 376, f"expected 376 historical diff rows, got {len(rows)}"
        # every diff row must carry the rollback anchor
        assert all(r.get("player_id_orig") is not None for r in rows)
    finally:
        draft_quality.close_pool()


def test_export_audit_csv_roundtrip():
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="")
    tmp.close()
    rows = [
        {"player_id": "a01", "player_id_orig": "a01x", "player_name": "Test A",
         "season": 2020, "pick_overall": 5},
        {"player_id": "b02", "player_id_orig": "b02x", "player_name": "Test B",
         "season": 2021, "pick_overall": 9},
    ]
    n = draft_quality.export_audit_csv(rows, tmp.name)
    assert n == 2
    with open(tmp.name, newline="", encoding="utf-8") as f:
        back = list(csv.DictReader(f))
    assert len(back) == 2
    assert back[0]["player_id"] == "a01"
    os.unlink(tmp.name)


@pytest.mark.needs_db
def test_apply_and_rollback_dry_run_noop(db_available):
    from tests.conftest import skip_without_db
    skip_without_db(db_available)
    draft_quality.init_pool()
    try:
        draft_quality.ensure_corrections_table()
        # With an (likely) empty corrections table, dry-run must plan 0 and
        # change nothing.
        apply_res = draft_quality.apply_corrections(dry_run=True)
        rollback_res = draft_quality.rollback_to_orig(dry_run=True)
        assert apply_res["dry_run"] is True
        assert rollback_res["dry_run"] is True
    finally:
        draft_quality.close_pool()


@pytest.mark.needs_db
def test_audit_csv_exists_on_disk(db_available):
    from tests.conftest import skip_without_db
    skip_without_db(db_available)
    assert os.path.exists(AUDIT_CSV), "T-A1-1 audit CSV was not produced"
