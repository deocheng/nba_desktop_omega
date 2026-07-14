"""Verification of current data state for A1/A2/A3 data-quality fixes.

Read-only (SELECT only) — safe to run any time.
Confirms:
  - dim_players weight coverage (lbs / kg)
  - the 37-tables-missing-weight inventory (excluding 2 bak + 1 bridge)
  - dim_draft_history 376 historical diff rows (player_id != player_id_orig)
  - weight_kg coverage in player_weight_history + dim_players
  - draft_picks is a VIEW fed by dim_draft_history

Run from project root with venv python + proxy unset:
    env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
        PYTHONPATH="<root>" .venv/Scripts/python.exe docs/diagnostics/draft_verify_state.py
"""
from __future__ import annotations

from backend.core.db import batch_query


def section(t: str) -> None:
    print("\n" + "=" * 70)
    print(t)
    print("=" * 70)


def show(rows, n: int = 10):
    if not rows:
        print("  (no rows)")
        return
    cols = list(rows[0].keys())
    print(f"  cols({len(cols)}): {cols}")
    for r in rows[:n]:
        print("  ", {k: r[k] for k in cols})


def main() -> None:
    # ── A2 inventory ──
    section("A2a. tables with a player key but NO weight column")
    col_rows = batch_query(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema='public'"
    )
    colmap: dict[str, list[str]] = {}
    for r in col_rows:
        colmap.setdefault(r["table_name"], []).append(r["column_name"])
    ttype = {
        r["table_name"]: r["table_type"]
        for r in batch_query(
            "SELECT table_name, table_type FROM information_schema.tables "
            "WHERE table_schema='public'"
        )
    }
    missing = []
    for t, c in colmap.items():
        has_key = any(k in c for k in ("player_id", "br_player_id"))
        has_w = any("weight" in k.lower() for k in c)
        if has_key and not has_w:
            missing.append(t)
    exclusions = [t for t in missing if ("bak" in t or "dup" in t or "backup" in t or t == "player_id_bridge")]
    actionable = [t for t in missing if t not in exclusions]
    print(f"  total missing-weight player tables: {len(missing)}")
    print(f"  exclusions (2 bak + 1 bridge): {exclusions}")
    print(f"  actionable (to be served via JOIN-at-read): {len(actionable)}")
    for t in sorted(actionable):
        c = colmap[t]
        key = "br_player_id" if "br_player_id" in c else "player_id"
        print(f"    - {t:30s} key={key:14s} kind={ttype.get(t, '?')}")

    # ── A3 weight coverage ──
    section("A3a. dim_players weight coverage")
    show(batch_query(
        "SELECT COUNT(*) AS total,"
        " COUNT(weight_lbs) AS with_lbs,"
        " COUNT(weight_kg) AS with_kg"
        " FROM dim_players"
    ))
    section("A3b. dim_players NULL-weight rows (the 3 to finish)")
    show(batch_query(
        "SELECT player_id, player_name FROM dim_players WHERE weight_lbs IS NULL"
    ), 10)
    section("A3c. player_weight_history weight_kg coverage")
    show(batch_query(
        "SELECT COUNT(*) AS rows,"
        " COUNT(weight_lbs) AS wt_lbs,"
        " COUNT(weight_kg) AS wt_kg"
        " FROM player_weight_history"
    ))

    # ── A1 draft history ──
    section("A1a. dim_draft_history total + 376 historical diff")
    show(batch_query("SELECT COUNT(*) AS total FROM dim_draft_history"))
    show(batch_query(
        "SELECT COUNT(*) AS diff_count FROM dim_draft_history"
        " WHERE player_id IS DISTINCT FROM player_id_orig"
    ))
    section("A1b. sample of 376 diff rows (dim_draft_history *)")
    show(batch_query(
        "SELECT * FROM dim_draft_history"
        " WHERE player_id IS DISTINCT FROM player_id_orig"
        " ORDER BY season LIMIT 10"
    ), 10)
    section("A1c. dim_draft_history columns (for audit CSV / snapshot)")
    show(batch_query(
        "SELECT column_name, data_type FROM information_schema.columns"
        " WHERE table_name='dim_draft_history' ORDER BY ordinal_position"
    ), 50)
    section("A1d. is draft_picks a VIEW? (information_schema)")
    show(batch_query(
        "SELECT table_name, table_type FROM information_schema.tables"
        " WHERE table_name IN ('draft_picks','dim_draft_history')"
    ))

    print("\nDONE.")


if __name__ == "__main__":
    main()
