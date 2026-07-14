"""NBACore v8 — Clutch feature shared constants.

Centralizes the cross-source priority map used by the clutch engine.

Source priority (lower number = higher trust, kept first during dedup):
    br_crawler = 1  (primary; carries the dribble/catch signal)
    nba_api   = 2
    BBRef     = 3  (carries scoremargin + explicit 2-pt/3-pt subtype tags)
"""
from __future__ import annotations

# Cross-source dedup priority. Lower number = kept first.
SOURCE_PRIORITY: dict[str, int] = {
    "br_crawler": 1,
    "nba_api": 2,
    "BBRef": 3,
}

# Canonical source identifiers (exact casing as stored in play_by_play.source).
SOURCE_BR_CRAWLER = "br_crawler"
SOURCE_NBA_API = "nba_api"
SOURCE_BBREF = "BBRef"

# The only play-by-play table the clutch engine reads.
PBP_TABLE = "play_by_play"
# Curated seasons are sourced from the games table.
GAMES_TABLE = "games"
