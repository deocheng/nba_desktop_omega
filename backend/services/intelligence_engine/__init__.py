"""NBACore v8.2 — Intelligence Engine (Layer 2½, above Metric Engine).

The Intelligence Engine is a SEPARATE calculation layer from the Metric
Engine (v8 §2 / v8.2 §3). It consumes raw season rows (via its own Layer-1
loader) and produces context-aware intelligence outputs: pace adjustment,
availability, historical percentile. It does NOT register these as MetricSpec
metrics — those live in the Metric Engine; this engine sits above it.

v8 §6 compliance:
    - no eval() / exec()
    - no SQL / psycopg2 in this package (all DB via intel_loader → batch_query)
    - no per-player DB loops (loaders use IN-clause batches; compute is vectorized)

Public API:
    - normalize_season_type(value) -> str
    - compute_team_paces(season) -> dict[str, float]
    - compute_league_pace(season) -> float
    - pace_adjust_player_stats(season, player_ids, season_type) -> dict
    - availability_score(pg, tg) / minutes_share(pm, tm)  (pure)
    - compute_availability(season, player_ids, season_type) -> dict
    - percentile_rank(value, dist)  (pure)
    - historical_percentile(season, metric, player_ids, season_type) -> dict
"""
from __future__ import annotations

from backend.services.intelligence_engine.availability import (
    availability_score,
    compute_availability,
    minutes_share,
)
from backend.services.intelligence_engine.historical_percentile import (
    historical_percentile,
    percentile_rank,
)
from backend.services.intelligence_engine.loader import (
    load_player_intel,
    load_player_shooting,
    load_team_intel,
)
from backend.services.intelligence_engine.pace_adjustment import (
    compute_league_pace,
    compute_team_paces,
    league_pace,
    pace_adjust,
    pace_adjust_player_stats,
    team_pace,
    team_possessions,
)
from backend.services.intelligence_engine.player_dna import (
    DNA_DIMENSIONS,
    compute_dna,
    compute_dna_batch,
)
from backend.services.intelligence_engine.role_classification import (
    ROLE_TYPES,
    classify_role,
    classify_role_batch,
)
from backend.services.intelligence_engine.scoring_profile import scoring_profile
from backend.services.intelligence_engine.season_type import (
    SEASON_TYPES,
    normalize_season_type,
    validate_season_type,
)

__phase_status__ = "phase82-core"
__all__ = [
    # season type
    "SEASON_TYPES",
    "normalize_season_type",
    "validate_season_type",
    # loaders (Layer 1 access)
    "load_player_intel",
    "load_player_shooting",
    "load_team_intel",
    # pace
    "team_possessions",
    "team_pace",
    "league_pace",
    "pace_adjust",
    "compute_team_paces",
    "compute_league_pace",
    "pace_adjust_player_stats",
    # availability
    "availability_score",
    "minutes_share",
    "compute_availability",
    # historical percentile
    "percentile_rank",
    "historical_percentile",
    # role classification
    "ROLE_TYPES",
    "classify_role",
    "classify_role_batch",
    # player dna
    "DNA_DIMENSIONS",
    "compute_dna",
    "compute_dna_batch",
    # scoring profile
    "scoring_profile",
]
