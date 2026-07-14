"""NBACore v8 — Fusion Clutch Replay service (Layer 2 aggregation facade).

Orchestrates three engine capabilities and shapes the ``ClutchReplayResult``:

    1. TacticsService.replay(req)            → frames[] + meta   (PBP frame sequence)
    2. clutch_service.fetch_clutch_events()  → clutch event rows (br_crawler only)
    3. clutch_service.get_clutch_players_for_game() → per-player sidebar stats
    4. mapper                                 → eventnum→index map + frame segments

Strict four-layer isolation (v8 §6): this module contains NO SQL and NO
coordinate / interpolation / clutch-window math. All DB access is delegated to
the engine layers (which themselves use ``core.db.batch_query``).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.services.clutch_engine import clutch_service
from backend.services.clutch_replay_engine import mapper, schemas
from backend.services.clutch_replay_engine.mapper import (
    build_eventnum_to_index_map,
    build_segments,
)
from backend.services.tactics_engine import service as tactics_service


class ClutchReplayService:
    """Fuse clutch-engine stats with a tactics replay timeline."""

    def __init__(self) -> None:
        self._tactics = tactics_service.TacticsService()
        self._clutch = clutch_service

    # ───────────────────────── public API ─────────────────────────
    def clutch_replay(self, req: schemas.ClutchReplayRequest) -> schemas.ClutchReplayResult:
        """Build a fused clutch-replay timeline for ``req.game_id``."""
        # (1) PBP replay frames — the single source of truth for frame indices.
        try:
            replay = self._tactics.replay(tactics_service.schemas.ReplayRequest(
                game_id=req.game_id,
                season=req.season,
                frame_rate=req.frame_rate,
            ))
        except LookupError as exc:
            raise schemas.ClutchReplayError(
                40002,
                f"该赛季无 br_crawler xy 回放数据: game {req.game_id} season {req.season} ({exc})",
            )

        frames: List[dict] = replay.get("frames") or []
        meta: Dict[str, Any] = dict(replay.get("meta") or {})
        if not frames:
            raise schemas.ClutchReplayError(
                40002,
                f"该赛季无 br_crawler xy 回放数据: game {req.game_id} season {req.season}",
            )

        # (2) clutch event-level rows (br_crawler only).
        clutch_events = self._clutch.fetch_clutch_events(
            req.game_id, req.season, req.period, req.clock_max, req.margin_max
        )

        # (3) per-game clutch player stats for the sidebar.
        player_rows = self._clutch.get_clutch_players_for_game(
            req.game_id, req.season, req.period, req.clock_max, req.margin_max
        )
        clutch_players = [self._to_player_stat(r) for r in player_rows]

        # (4) map eventnum → event_index, resolve clutch segments, enrich.
        eventnum_map = build_eventnum_to_index_map(req.game_id, req.season)
        event_indices = [
            eventnum_map[e["eventnum"]]
            for e in clutch_events
            if e["eventnum"] in eventnum_map
        ]
        segments = build_segments(event_indices, frames, req.pad_events)
        segments = self._enrich_segments(segments, clutch_events, eventnum_map)

        meta["clutch_segment_count"] = len(segments)
        return schemas.ClutchReplayResult(
            game_id=req.game_id,
            season=req.season,
            frames=frames,
            meta=meta,
            clutch_segments=segments,
            clutch_players=clutch_players,
        )

    # ───────────────────────── internal helpers ─────────────────────────
    @staticmethod
    def _enrich_segments(
        segments: List[schemas.ClutchSegment],
        clutch_events: List[dict],
        eventnum_map: Dict[int, int],
    ) -> List[schemas.ClutchSegment]:
        """Tag each resolved segment window with its clutch-event details.

        For every segment, gather the clutch events whose ``event_index`` falls
        inside ``[start_event_index, end_event_index]`` and derive period,
        clock span, involved players, and a representative margin.
        """
        by_index: Dict[int, dict] = {}
        for ev in clutch_events:
            ei = eventnum_map.get(ev["eventnum"])
            if ei is not None:
                by_index[ei] = ev

        for seg in segments:
            in_range = [
                by_index[ei]
                for ei in range(seg.start_event_index, seg.end_event_index + 1)
                if ei in by_index
            ]
            if not in_range:
                continue
            seg.period = int(in_range[0].get("period") or 0)
            clocks = [float(ev.get("clock_seconds", 0.0)) for ev in in_range]
            seg.clock_start = max(clocks)
            seg.clock_end = min(clocks)
            seg.margin = max((abs(int(ev.get("margin", 0))) for ev in in_range), default=0)

            seen = set()
            players: List[schemas.ClutchSegmentPlayer] = []
            for ev in in_range:
                pid = ev.get("playerid")
                pname = ev.get("player") or ""
                team = ev.get("team")
                key = (pid, pname)
                if key in seen:
                    continue
                seen.add(key)
                players.append(schemas.ClutchSegmentPlayer(
                    playerid=pid, player=pname, team=team
                ))
            seg.players = players
        return segments

    @staticmethod
    def _to_player_stat(row: dict) -> schemas.ClutchPlayerStat:
        """Convert a ``_post_process`` dict into the public ``ClutchPlayerStat``."""
        return schemas.ClutchPlayerStat(
            player_id=row.get("player_id"),
            player_name=row.get("player_name") or "",
            team=row.get("team"),
            poss=int(row.get("poss") or 0),
            fg_pct=row.get("fg_pct"),
            fg2_pct=row.get("fg2_pct"),
            fg3_pct=row.get("fg3_pct"),
            oreb=int(row.get("oreb") or 0),
            dreb=int(row.get("dreb") or 0),
            ast=int(row.get("ast") or 0),
            stl=int(row.get("stl") or 0),
            tov=int(row.get("tov") or 0),
            pf=int(row.get("pf") or 0),
            pts=int(row.get("pts") or 0),
            catch_shots=row.get("catch_shots"),
            dribble_shots=row.get("dribble_shots"),
            dribble_coverage=row.get("dribble_coverage"),
        )
