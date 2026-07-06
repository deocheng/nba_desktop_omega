"""NBACore v8 §2 Layer 3 — /batch router (pure orchestration).

Executes multiple metric operations in one request. Each operation is
dispatched to metric_engine — no computation happens in this router.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from backend.api.schemas import BatchRequest, BatchResponse
from backend.services.metric_engine import (
    compute_as_dict,
    compute_many_as_dict,
    list_metrics,
    rank,
)

logger = logging.getLogger("nbacore.api.batch")

router = APIRouter(prefix="/batch", tags=["batch"])

_VALID_TYPES = {"rank", "compute", "compute_many"}


@router.post("", response_model=BatchResponse)
def execute_batch(request: BatchRequest) -> BatchResponse:
    """Execute multiple metric operations in one request.

    Each operation in `request.operations` is dispatched based on `type`:
        - "rank":         rank(metric, season, ascending, min_value)
        - "compute":      compute_as_dict(metric, season, player_ids)
        - "compute_many": compute_many_as_dict(metrics, season, player_ids)
    """
    if not request.operations:
        raise HTTPException(status_code=400, detail="operations list is empty")

    available = set(list_metrics())
    results: list[dict] = []

    for i, op in enumerate(request.operations):
        if op.type not in _VALID_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"operation {i}: invalid type {op.type!r} "
                       f"(must be one of {sorted(_VALID_TYPES)})",
            )

        try:
            if op.type == "rank":
                if not op.metric:
                    raise ValueError("rank operation requires 'metric'")
                if op.metric not in available:
                    raise ValueError(f"unknown metric {op.metric!r}")
                rankings = rank(
                    op.metric,
                    op.season,
                    ascending=op.ascending,
                    min_value=op.min_value,
                    use_cache=True,
                )
                if op.limit is not None:
                    rankings = rankings[:op.limit]
                results.append({
                    "type": "rank",
                    "metric": op.metric,
                    "season": op.season,
                    "rankings": [
                        {
                            "rank": r.rank,
                            "player_id": r.player_id,
                            "value": r.value,
                            "percentile": r.percentile,
                            "sample_size": r.sample_size,
                        }
                        for r in rankings
                    ],
                    "total": len(rankings),
                })

            elif op.type == "compute":
                if not op.metric:
                    raise ValueError("compute operation requires 'metric'")
                if op.metric not in available:
                    raise ValueError(f"unknown metric {op.metric!r}")
                values = compute_as_dict(
                    op.metric,
                    op.season,
                    player_ids=op.player_ids,
                    use_cache=True,
                )
                results.append({
                    "type": "compute",
                    "metric": op.metric,
                    "season": op.season,
                    "values": values,
                    "count": len(values),
                })

            elif op.type == "compute_many":
                if not op.metrics:
                    raise ValueError("compute_many operation requires 'metrics'")
                invalid = [m for m in op.metrics if m not in available]
                if invalid:
                    raise ValueError(f"unknown metrics: {invalid}")
                values = compute_many_as_dict(
                    op.metrics,
                    op.season,
                    player_ids=op.player_ids,
                    use_cache=True,
                )
                results.append({
                    "type": "compute_many",
                    "metrics": op.metrics,
                    "season": op.season,
                    "values": values,
                    "count": len(values),
                })

        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"operation {i} ({op.type}): {exc}",
            )
        except Exception as exc:
            logger.exception("batch operation %d failed", i)
            raise HTTPException(
                status_code=500,
                detail=f"operation {i} ({op.type}) failed: {exc}",
            )

    return BatchResponse(results=results, count=len(results))
