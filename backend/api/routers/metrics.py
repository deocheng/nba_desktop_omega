"""NBACore v8 §2 Layer 3 — /metrics router (pure orchestration).

All computation delegated to metric_engine. This router contains NO SQL,
NO pandas, NO aggregation logic — only request shaping + metric_engine calls.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.api.schemas import (
    EvaluateResponse,
    MetricInfo,
    MetricListResponse,
    RankingItem,
)
from backend.services.metric_engine import get_metric, get_player_bios, list_metrics, rank

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("", response_model=MetricListResponse)
def get_metrics() -> MetricListResponse:
    """List all registered metrics."""
    names = list_metrics()
    specs = [get_metric(n) for n in names]
    return MetricListResponse(
        metrics=[
            MetricInfo(
                name=s.name,
                kind=s.kind,
                source_table=s.source_table,
                required_cols=list(s.required_cols),
                description=s.description,
                min_denominator=s.min_denominator,
                precision=s.precision,
            )
            for s in specs
        ],
        count=len(specs),
    )


@router.get("/{metric_name}", response_model=MetricInfo)
def get_metric_detail(metric_name: str) -> MetricInfo:
    """Get details for a single metric."""
    try:
        s = get_metric(metric_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return MetricInfo(
        name=s.name,
        kind=s.kind,
        source_table=s.source_table,
        required_cols=list(s.required_cols),
        description=s.description,
        min_denominator=s.min_denominator,
        precision=s.precision,
    )


@router.get("/evaluate/{metric_name}", response_model=EvaluateResponse)
def evaluate_metric(
    metric_name: str,
    season: int = Query(..., ge=1900, le=2100, description="NBA season"),
    ascending: bool = Query(False, description="False=highest first"),
    min_value: float | None = Query(None, description="Exclude values below this"),
    limit: int | None = Query(None, ge=1, le=1000, description="Max rankings to return"),
) -> EvaluateResponse:
    """Evaluate a metric for a season and return ranked results."""
    try:
        rankings = rank(
            metric_name,
            season,
            ascending=ascending,
            min_value=min_value,
            use_cache=True,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if limit is not None:
        rankings = rankings[:limit]

    player_ids = [r.player_id for r in rankings]
    bios_list = get_player_bios(player_ids) if player_ids else []
    bios = {b["player_id"]: b for b in bios_list}

    return EvaluateResponse(
        metric=metric_name,
        season=season,
        ascending=ascending,
        min_value=min_value,
        rankings=[
            RankingItem(
                rank=r.rank,
                player_id=r.player_id,
                player_name=bios.get(r.player_id, {}).get("full_name")
                or bios.get(r.player_id, {}).get("player_name"),
                position=bios.get(r.player_id, {}).get("position"),
                value=r.value,
                percentile=r.percentile,
                sample_size=r.sample_size,
            )
            for r in rankings
        ],
        total=len(rankings),
    )
