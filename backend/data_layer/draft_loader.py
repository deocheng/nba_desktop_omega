"""NBACore v8 — Draft picks read loader (A2 weight-at-read + A1-4 degrade flag).

Reads the ``draft_picks`` VIEW (which forwards ``dim_draft_history``) and
surfaces two things the UI needs without any physical schema change:

  * ``weight_lbs`` / ``weight_kg`` — JOINed from ``dim_players`` at read time
    (A2: JOIN-at-read, never a physical column on the 37 fact tables).
  * ``in_dim_players`` — a boolean telling the frontend whether the player's
    BBR id actually resolves to a master player (A1-4: render "无资料" instead
    of a dead BR link when False).

All SQL is SELECT-only and built from trusted constants + psycopg2.sql.Identifier
(v8 §6). No aggregation/coordinate math — that stays in the frontend/engine.
"""
from __future__ import annotations

from typing import Any

from psycopg2 import sql as psql

from backend.core.db import batch_query_composed
from backend.data_layer.joins import join_player_weight, select_weight_cols


def load_draft_picks_with_weight(
    limit: int | None = None,
    season: int | None = None,
) -> list[dict]:
    """Load draft_picks rows with weight + in_dim_players flag + wingspan.

    Args:
        limit: cap on returned rows (pagination safety). Default None = all.
        season: optional season filter (e.g. 2024).

    Returns:
        list[dict]: each row is a draft_picks row plus
            ``weight_lbs``, ``weight_kg``, ``in_dim_players`` (bool),
            and ``wingspan_cm`` (combine measurement; None when no match).
    """
    weight_join = join_player_weight("player_id", table_alias="dp")
    weight_cols = select_weight_cols("p_w")
    # C: surface wingspan_cm from draft_combine.
    # DEVIATION FROM BRIEF: the brief assumed a (player_id, season) key on
    # draft_combine, but that table has NO player_id column — its natural
    # (UNIQUE) key is (season, player_name). We therefore LEFT JOIN on those
    # two columns. Unmatched rows yield wingspan_cm = NULL -> frontend shows '—'.
    combine_join = psql.SQL(
        " LEFT JOIN draft_combine dc"
        " ON dp.season = dc.season AND dp.player_name = dc.player_name"
    )
    base = psql.SQL(
        """
        SELECT
            dp.*,
            {weight_cols},
            (p_w.player_id IS NOT NULL) AS in_dim_players,
            dc.wingspan_cm AS wingspan_cm
        FROM draft_picks dp
        {weight_join}
        {combine_join}
        """
    ).format(
        weight_cols=weight_cols,
        weight_join=weight_join,
        combine_join=combine_join,
    )

    params: list[Any] = []
    if season is not None:
        base = psql.SQL("{sql} WHERE dp.season = %s").format(sql=base)
        params.append(season)
    if limit is not None:
        base = psql.SQL("{sql} LIMIT %s").format(sql=base)
        params.append(int(limit))

    rows = batch_query_composed(base, tuple(params))
    for r in rows:
        r["in_dim_players"] = bool(r.get("in_dim_players"))
        # Ensure the wingspan key is always present (None when unmatched).
        r.setdefault("wingspan_cm", None)
    return rows
