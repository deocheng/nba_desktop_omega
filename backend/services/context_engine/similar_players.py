"""Similar player finder — cosine similarity across a metric feature vector.

All data sourced from Metric Engine (layer 2). This module builds a per-player
metric vector and ranks by cosine similarity to the target player.

v8 §2 compliance:
- Input: metric names + season → calls compute_many
- Output: list of (player_id, similarity_score, top_metrics)
- No DB access, no SQL, no data_layer imports
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from backend.services.metric_engine import compute_many, get_player_bios


@dataclass
class SimilarPlayer:
    player_id: str
    similarity: float
    name: str
    team: str | None
    position: str | None
    # 增量：本地头像（来自 player_bio 视图，经 get_player_bios 返回）
    headshot_path: str | None = None
    headshot_status: str | None = None


def find_similar_players(
    player_id: str,
    season: int,
    metric_names: list[str],
    limit: int = 10,
    position_filter: bool = True,
) -> list[SimilarPlayer]:
    """Find players most similar to target player using cosine similarity.

    Args:
        player_id: target BBR player ID
        season: NBA season
        metric_names: list of metric names to use as feature vector
        limit: max number of similar players to return
        position_filter: if True, only compare to players sharing a position

    Returns:
        List of SimilarPlayer sorted by similarity descending.
        Target player is excluded from results.
    """
    if not metric_names:
        raise ValueError("metric_names must not be empty")

    # Step 1: get all player data for these metrics (entire league)
    df = compute_many(metric_names, season)

    if df.empty or player_id not in df.index:
        return []

    # Step 2: position filter (optional)
    if position_filter:
        target_bio_list = get_player_bios([player_id])
        target_bio = target_bio_list[0] if target_bio_list else None
        if target_bio and target_bio.get("position"):
            target_pos = target_bio["position"].split(",")[0].strip()
            all_ids = list(df.index)
            all_bios_list = get_player_bios(all_ids)
            all_bios = {b["player_id"]: b for b in all_bios_list}
            same_pos_ids = [
                pid for pid, bio in all_bios.items()
                if bio.get("position") and target_pos in bio["position"]
            ]
            if same_pos_ids:
                df = df.loc[df.index.isin(same_pos_ids)]

    if df.empty or player_id not in df.index:
        return []

    # Step 3: normalize (z-score) so all metrics have equal weight
    means = df.mean()
    stds = df.std()
    # Avoid division by zero for constant metrics
    stds = stds.replace(0, 1.0)
    df_norm = (df - means) / stds

    # Step 4: cosine similarity (vectorized)
    target_vec = df_norm.loc[player_id].values
    all_vecs = df_norm.values

    # Cosine sim = dot(A,B) / (||A|| * ||B||)
    dot_products = all_vecs @ target_vec
    target_norm = math.sqrt((target_vec ** 2).sum())
    all_norms = ((all_vecs ** 2).sum(axis=1)) ** 0.5

    # Avoid division by zero
    all_norms[all_norms == 0] = 1.0
    similarities = dot_products / (all_norms * target_norm)

    # Step 5: build results
    result_pairs = [
        (str(pid), float(sim))
        for pid, sim in zip(df.index, similarities)
        if pid != player_id and sim == sim  # exclude target + NaN
    ]
    result_pairs.sort(key=lambda x: x[1], reverse=True)

    top_pairs = result_pairs[:limit]
    if not top_pairs:
        return []

    # Step 6: attach bios
    top_ids = [pid for pid, _ in top_pairs]
    bios_list = get_player_bios(top_ids)
    bios = {b["player_id"]: b for b in bios_list}

    results: list[SimilarPlayer] = []
    for pid, sim in top_pairs:
        bio = bios.get(pid, {})
        results.append(SimilarPlayer(
            player_id=pid,
            similarity=round(sim, 4),
            name=bio.get("player_name") or bio.get("full_name") or pid,
            team=bio.get("team"),
            position=bio.get("position"),
            headshot_path=bio.get("headshot_path"),
            headshot_status=bio.get("headshot_status"),
        ))

    return results
