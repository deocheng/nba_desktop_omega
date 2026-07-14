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
    """Load draft_picks rows with weight + in_dim_players flag.

    Args:
        limit: cap on returned rows (pagination safety). Default None = all.
        season: optional season filter (e.g. 2024).

    Returns:
        list[dict]: each row is a draft_picks row plus
            ``weight_lbs``, ``weight_kg``, ``in_dim_players`` (bool).
    """
    weight_join = join_player_weight("player_id", table_alias="dp")
    weight_cols = select_weight_cols("p_w")
    base = psql.SQL(
        """
        SELECT
            dp.*,
            {weight_cols},
            (p_w.player_id IS NOT NULL) AS in_dim_players
        FROM draft_picks dp
        {weight_join}
        """
    ).format(weight_cols=weight_cols, weight_join=weight_join)

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
    return rows
