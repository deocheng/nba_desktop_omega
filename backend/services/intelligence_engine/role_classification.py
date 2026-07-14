"""NBACore v8.2 §8 — Player Role Classification.

Assigns one of 9 archetypes from a player's advanced box percentages. The
classifier is a deterministic, documented rule tree (priority-ordered, first
match wins) — no ML, no randomness, fully testable.

Inputs (all columns of fact_player_season_stats):
    usg_percent, ast_percent, ts_percent, x3pa_rate (= x3pa / fga),
    orb_percent, drb_percent, stl_percent, blk_percent.

Role types (PRD §8):
    Primary Creator, Secondary Creator, Scoring Guard, 3&D Wing,
    Shot Creator, Rim Protector, Stretch Big, Two Way Star, Role Player.
"""
from __future__ import annotations

from typing import Mapping

ROLE_TYPES = (
    "Primary Creator",
    "Secondary Creator",
    "Scoring Guard",
    "3&D Wing",
    "Shot Creator",
    "Rim Protector",
    "Stretch Big",
    "Two Way Star",
    "Role Player",
)

# Thresholds (percentage points; x3pa_rate is a 0-1 fraction)
HIGH_USG = 25.0
HIGH_AST_PCT = 22.0
TWO_WAY_DEF = 3.0          # stl% + blk% >= this
THREE_RATE = 0.30
RIM_PROTECT_BLK = 4.0
STRETCH_BIG_BRD = 14.0     # orb% + drb% >= this
STRETCH_BIG_3R = 0.28


def _x3pa_rate(m: Mapping) -> float:
    x3pa = float(m.get("x3pa") or 0.0)
    fga = float(m.get("fga") or 0.0)
    return x3pa / fga if fga > 0 else 0.0


def classify_role(metrics: Mapping) -> str:
    """Classify a single player's archetype from its metric mapping.

    `metrics` must provide: usg_percent, ast_percent, ts_percent, x3pa, fga,
    orb_percent, drb_percent, stl_percent, blk_percent. Missing keys default
    to 0.0 so callers don't need to sanitize first.
    """
    usg = float(metrics.get("usg_percent") or 0.0)
    ast_pct = float(metrics.get("ast_percent") or 0.0)
    ts = float(metrics.get("ts_percent") or 0.0)
    x3r = _x3pa_rate(metrics)
    orb = float(metrics.get("orb_percent") or 0.0)
    drb = float(metrics.get("drb_percent") or 0.0)
    stl = float(metrics.get("stl_percent") or 0.0)
    blk = float(metrics.get("blk_percent") or 0.0)
    def_sum = stl + blk
    brd = orb + drb

    # Priority order — first match wins.
    if usg >= HIGH_USG and ast_pct >= HIGH_AST_PCT:
        return "Primary Creator"
    if ts >= 0.58 and def_sum >= TWO_WAY_DEF and usg >= 20.0:
        return "Two Way Star"
    if usg >= HIGH_USG and ast_pct < HIGH_AST_PCT and x3r >= 0.25:
        return "Scoring Guard"
    if usg >= HIGH_USG and ast_pct < HIGH_AST_PCT and x3r < 0.25:
        return "Shot Creator"
    if x3r >= 0.35 and ts >= 0.55 and def_sum >= 1.5 and usg < HIGH_USG:
        return "3&D Wing"
    if ast_pct >= HIGH_AST_PCT and usg < HIGH_USG:
        return "Secondary Creator"
    if blk >= RIM_PROTECT_BLK or (drb >= 18.0 and usg < 20.0):
        return "Rim Protector"
    if brd >= STRETCH_BIG_BRD and x3r >= STRETCH_BIG_3R and usg < 22.0:
        return "Stretch Big"
    return "Role Player"


def classify_role_batch(rows: list[dict]) -> dict[str, str]:
    """Classify many players at once. Returns {player_id: role}."""
    out: dict[str, str] = {}
    for r in rows:
        pid = r.get("player_id")
        if pid is not None:
            out[pid] = classify_role(r)
    return out
