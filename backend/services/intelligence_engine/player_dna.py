"""NBACore v8.2 §9 — Player DNA.

A 7-dimension identity profile, each score on a 0-100 scale, derived
deterministically from a player's season metrics + availability. Scores are
transparent linear blends of real columns (documented below) — no opaque
model, so every value is explainable and testable.

Dimensions (PRD §9): scoring, playmaking, defense, rebounding, efficiency,
durability, leadership.

Formulas (all clipped to [0, 100]):
    scoring     = 0.7*(ppg/30*100) + 0.3*(ts%*100)
    playmaking  = 0.6*(apg/10*100) + 0.4*(ast%*2*100)   # ast% 50 -> 100
    defense     = (stl% + blk%) * 15
    rebounding  = (orb% + drb%) * 2.2
    efficiency  = ts% * 100
    durability  = availability_score * 100               # g / team_g
    leadership  = 0.5*(usg/35*100) + 0.5*(ast%*2*100)     # usage + playmaking proxy
                  (no direct leadership column exists; documented approximation)

`leadership` is the only proxy dimension — there is no leadership stat in the
source data, so it is approximated from usage + playmaking involvement.
"""
from __future__ import annotations

from typing import Mapping

DNA_DIMENSIONS = (
    "scoring",
    "playmaking",
    "defense",
    "rebounding",
    "efficiency",
    "durability",
    "leadership",
)

_MIN_G = 1.0  # guard against div-by-zero when computing per-game


def _clip(x: float) -> float:
    if x is None or (isinstance(x, float) and x != x):
        return 0.0
    return max(0.0, min(100.0, float(x)))


def compute_dna(metrics: Mapping, availability_score: float = 1.0) -> dict[str, float]:
    """Compute the 7 DNA scores for one player.

    Args:
        metrics: mapping with pts, g, ast, trb, ts_percent, usg_percent,
                 ast_percent, orb_percent, drb_percent, stl_percent, blk_percent.
        availability_score: g / team_g in [0, 1] (from availability module).
    """
    g = float(metrics.get("g") or 0.0)
    ppg = (float(metrics.get("pts") or 0.0) / g) if g >= _MIN_G else 0.0
    apg = (float(metrics.get("ast") or 0.0) / g) if g >= _MIN_G else 0.0

    ts = float(metrics.get("ts_percent") or 0.0)
    usg = float(metrics.get("usg_percent") or 0.0)
    ast_pct = float(metrics.get("ast_percent") or 0.0)
    orb = float(metrics.get("orb_percent") or 0.0)
    drb = float(metrics.get("drb_percent") or 0.0)
    stl = float(metrics.get("stl_percent") or 0.0)
    blk = float(metrics.get("blk_percent") or 0.0)

    scoring = 0.7 * (ppg / 30.0 * 100.0) + 0.3 * (ts * 100.0)
    playmaking = 0.6 * (apg / 10.0 * 100.0) + 0.4 * (ast_pct * 2.0 * 100.0)
    defense = (stl + blk) * 15.0
    rebounding = (orb + drb) * 2.2
    efficiency = ts * 100.0
    durability = (availability_score if availability_score is not None else 1.0) * 100.0
    leadership = 0.5 * (usg / 35.0 * 100.0) + 0.5 * (ast_pct * 2.0 * 100.0)

    return {
        "scoring": round(_clip(scoring), 1),
        "playmaking": round(_clip(playmaking), 1),
        "defense": round(_clip(defense), 1),
        "rebounding": round(_clip(rebounding), 1),
        "efficiency": round(_clip(efficiency), 1),
        "durability": round(_clip(durability), 1),
        "leadership": round(_clip(leadership), 1),
    }


def compute_dna_batch(
    rows: list[dict], availability_map: Mapping[str, float] | None = None
) -> dict[str, dict[str, float]]:
    """Compute DNA for many players. availability_map: {player_id: score}."""
    av_map = availability_map or {}
    out: dict[str, dict[str, float]] = {}
    for r in rows:
        pid = r.get("player_id")
        if pid is None:
            continue
        out[pid] = compute_dna(r, av_map.get(pid, 1.0))
    return out
