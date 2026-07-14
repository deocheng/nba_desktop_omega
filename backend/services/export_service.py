"""Export service — JSON/CSV export of metric data and VS results.

v8 §2 compliance:
- All data sourced from Metric Engine (layer 2)
- No DB access, no SQL
- Deterministic output (same input → same output)
- CSV/JSON are pure serialization (no transformation beyond formatting)
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import datetime

from backend.services.metric_engine import (
    compute_many_as_dict,
    list_metrics,
    player_metrics_dict,
    rank,
    vs_compare,
)


@dataclass
class ExportResult:
    content: str
    filename: str
    content_type: str
    sha256: str


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _timestamp() -> str:
    return datetime.utcnow().strftime("%Y%m%d")


def export_rankings_json(metric: str, season: int, limit: int = 100) -> ExportResult:
    """Export rankings as JSON (deterministic)."""
    rankings = rank(metric, season)[:limit]
    data = {
        "export_type": "rankings",
        "metric": metric,
        "season": season,
        "count": len(rankings),
        "generated_at": _timestamp(),
        "rankings": [
            {
                "rank": r.rank,
                "player_id": r.player_id,
                "value": r.value,
                "percentile": r.percentile,
            }
            for r in rankings
        ],
    }
    content = json.dumps(data, indent=2, sort_keys=True)
    return ExportResult(
        content=content,
        filename=f"rankings_{metric}_{season}_{_timestamp()}.json",
        content_type="application/json",
        sha256=_sha256(content),
    )


def export_rankings_csv(metric: str, season: int, limit: int = 100) -> ExportResult:
    """Export rankings as CSV (deterministic)."""
    rankings = rank(metric, season)[:limit]
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["rank", "player_id", "value", "percentile"])
    for r in rankings:
        writer.writerow([r.rank, r.player_id, r.value, round(r.percentile, 4)])
    content = buf.getvalue()
    return ExportResult(
        content=content,
        filename=f"rankings_{metric}_{season}_{_timestamp()}.csv",
        content_type="text/csv",
        sha256=_sha256(content),
    )


def export_vs_json(
    player_1: str,
    player_2: str,
    season: int,
    metric_names: list[str],
) -> ExportResult:
    """Export VS comparison as JSON (deterministic)."""
    result = vs_compare(metric_names, season, player_1, player_2)
    data = {
        "export_type": "vs_comparison",
        "player_1": player_1,
        "player_2": player_2,
        "season": season,
        "metrics": metric_names,
        "generated_at": _timestamp(),
        "results": result,
    }
    content = json.dumps(data, indent=2, sort_keys=True)
    return ExportResult(
        content=content,
        filename=f"vs_{player_1}_vs_{player_2}_{season}_{_timestamp()}.json",
        content_type="application/json",
        sha256=_sha256(content),
    )


def export_vs_csv(
    player_1: str,
    player_2: str,
    season: int,
    metric_names: list[str],
) -> ExportResult:
    """Export VS comparison as CSV (deterministic)."""
    result = vs_compare(metric_names, season, player_1, player_2)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["metric", player_1, player_2])
    for m in sorted(metric_names):
        vals = result.get(m, {})
        v1 = vals.get(player_1)
        v2 = vals.get(player_2)
        writer.writerow([m, v1 if v1 is not None else "", v2 if v2 is not None else ""])
    content = buf.getvalue()
    return ExportResult(
        content=content,
        filename=f"vs_{player_1}_vs_{player_2}_{season}_{_timestamp()}.csv",
        content_type="text/csv",
        sha256=_sha256(content),
    )


def export_player_json(
    player_id: str,
    season: int,
    metric_names: list[str] | None = None,
) -> ExportResult:
    """Export single-player metrics as JSON (deterministic)."""
    if metric_names is None:
        metric_names = list_metrics()
    metrics = player_metrics_dict(metric_names, season, player_id)
    data = {
        "export_type": "player_metrics",
        "player_id": player_id,
        "season": season,
        "metric_count": len(metrics),
        "generated_at": _timestamp(),
        "metrics": metrics,
    }
    content = json.dumps(data, indent=2, sort_keys=True)
    return ExportResult(
        content=content,
        filename=f"player_{player_id}_{season}_{_timestamp()}.json",
        content_type="application/json",
        sha256=_sha256(content),
    )


def export_league_json(
    season: int,
    metric_names: list[str] | None = None,
) -> ExportResult:
    """Export all players' metrics as JSON (deterministic, sorted by player_id)."""
    if metric_names is None:
        metric_names = list_metrics()
    data_dict = compute_many_as_dict(metric_names, season)
    data = {
        "export_type": "league_metrics",
        "season": season,
        "metric_count": len(metric_names),
        "player_count": len(data_dict),
        "generated_at": _timestamp(),
        "metrics": metric_names,
        "players": dict(sorted(data_dict.items())),
    }
    content = json.dumps(data, indent=2, sort_keys=True)
    return ExportResult(
        content=content,
        filename=f"league_{season}_{_timestamp()}.json",
        content_type="application/json",
        sha256=_sha256(content),
    )
