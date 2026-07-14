"""NBACore v8 §2 Layer 1 — Data Layer (immutable PostgreSQL access).

This package is the SOLE consumer of backend.core.db.batch_query().
Everything that reads from PostgreSQL goes through batch_loader.py.

Hard rules (v8 §2):
    - Only SELECT (enforced in backend.core.db.validate_batch_sql)
    - Batch query only (IN clause or temp table)
    - season / date range filter MANDATORY (enforced at function signature)
    - No per-player loop — all fetches are vectorized batches

Phase 0.5: schema registry + IN-clause loaders
Phase 1: temp table loaders + schema drift validation + join loaders
Phase 2: feature-complete loaders (teams, games, player charts, system, charts)
"""
from backend.data_layer.batch_loader import (
    load_player_gamelog,
    load_player_season_stats,
    load_player_team_share,
    load_players,
    load_games,
    load_team_season_stats,
    load_seasons_available,
    search_players,
)
from backend.data_layer.temp_loader import (
    load_player_gamelog_by_ids,
    load_players_by_ids,
    should_use_temp_table,
    TEMP_TABLE_THRESHOLD,
)
from backend.data_layer.joins import (
    load_player_gamelog_with_game_context,
    load_player_season_stats_with_bio,
    join_player_weight,
    select_weight_cols,
)
from backend.data_layer.entity_loader import (
    load_player_games_aggregated,
    load_player_seasons,
    load_team_games_aggregated,
    load_team_gamelog_with_game_context,
    load_team_seasons,
    season_label,
)
from backend.data_layer.schema_validator import (
    validate_registry,
    registry_healthy,
    drift_summary,
)
from backend.data_layer.team_loader import (
    list_all_teams,
    get_teams_board,
    get_team_splits,
    get_team_standings,
    get_team_stats_per_game,
    get_team_ratios,
    get_team_scoring_trend,
    get_team_radar,
    get_league_radar_avg,
    get_team_history,
    get_team_legend_players,
    get_team_season_roster,
)
from backend.data_layer.game_loader import (
    list_games,
    get_quarter_stats,
    get_game_detail,
    get_game_radar,
    get_play_by_play,
    get_game_player_performance,
)
from backend.data_layer.player_chart_loader import (
    compute_box_stats,
    get_scoring_distribution,
    get_player_advanced,
    get_player_shooting,
    get_player_ratios,
    get_player_per_game,
)
from backend.data_layer.system_loader import (
    list_tables,
    get_table_data,
    get_status_summary,
)
from backend.data_layer.charts_loader import (
    get_late_clock_team_stats,
    get_late_clock_player_stats,
)

__all__ = [
    # Phase 0.5 — IN-clause loaders
    "load_player_gamelog",
    "load_player_season_stats",
    "load_player_team_share",
    "load_players",
    "load_games",
    "load_team_season_stats",
    "load_seasons_available",
    # Phase 3 — player search (additive extension)
    "search_players",
    # Phase 1 — temp table loaders
    "load_player_gamelog_by_ids",
    "load_players_by_ids",
    "should_use_temp_table",
    "TEMP_TABLE_THRESHOLD",
    # Phase 1 — join loaders
    "load_player_gamelog_with_game_context",
    "load_player_season_stats_with_bio",
    # A2 — parameterized weight JOIN-at-read helper
    "join_player_weight",
    "select_weight_cols",
    # v8 Entity Detail — aggregation + season discovery
    "load_player_games_aggregated",
    "load_player_seasons",
    "load_team_games_aggregated",
    "load_team_gamelog_with_game_context",
    "load_team_seasons",
    "season_label",
    # Phase 1 — schema validation
    "validate_registry",
    "registry_healthy",
    "drift_summary",
    # Phase 2 — team loader
    "list_all_teams",
    "get_teams_board",
    "get_team_splits",
    "get_team_standings",
    "get_team_stats_per_game",
    "get_team_ratios",
    "get_team_scoring_trend",
    "get_team_radar",
    "get_league_radar_avg",
    "get_team_history",
    "get_team_legend_players",
    "get_team_season_roster",
    # Phase 2 — game loader
    "list_games",
    "get_quarter_stats",
    "get_game_detail",
    "get_game_radar",
    "get_play_by_play",
    "get_game_player_performance",
    # Phase 2 — player chart loader
    "compute_box_stats",
    "get_scoring_distribution",
    "get_player_advanced",
    "get_player_shooting",
    "get_player_ratios",
    "get_player_per_game",
    # Phase 2 — system loader
    "list_tables",
    "get_table_data",
    "get_status_summary",
    # Phase 2 — charts loader (Python-side computation)
    "get_late_clock_team_stats",
    "get_late_clock_player_stats",
]
