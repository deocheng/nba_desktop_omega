"""NBACore v8.2 — Season Type normalization.

The player fact table stores `season_type` as 'Regular' / 'Playoffs'
(and conceptually 'PlayIn'). The engine accepts many spellings and normalizes
them to the canonical capitalized form. The team fact table has only a
`playoffs` qualification flag (no season_type split), so team-level pace is
always regular-season pace — documented at the call sites that need it.
"""
from __future__ import annotations

SEASON_TYPES = ("Regular", "Playoffs", "PlayIn")

_ALIASES = {
    "regular": "Regular",
    "reg": "Regular",
    "rs": "Regular",
    "playoffs": "Playoffs",
    "postseason": "Playoffs",
    "post": "Playoffs",
    "po": "Playoffs",
    "play_in": "PlayIn",
    "playin": "PlayIn",
    "play-in": "PlayIn",
}


def normalize_season_type(value) -> str:
    """Map any accepted spelling to a canonical season_type string.

    Raises ValueError for anything unrecognized (v8 §2: fail loud, no silent
    fallback to wrong data).
    """
    if value is None:
        return "Regular"
    if isinstance(value, str) and value in SEASON_TYPES:
        return value
    key = str(value).strip().lower()
    if key in _ALIASES:
        return _ALIASES[key]
    raise ValueError(
        f"Unknown season_type {value!r}; expected one of {SEASON_TYPES} "
        f"(or aliases: regular/playoffs/play_in)"
    )


def validate_season_type(value) -> bool:
    """Raise if invalid, else return True. Convenience for callers."""
    normalize_season_type(value)
    return True
