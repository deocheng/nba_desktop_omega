"""NBACore v8 — Video Library service (Layer 2 aggregation facade).

Orchestrates four capabilities and shapes the ``PlaybackResponse``:

    1. VideoLibraryDB.get_video_source()     → video ref + offset
    2. ClutchReplayService.clutch_replay()   → frames + meta + clutch_segments + players
    3. tactics_engine.db.load_pbp_events()   → events[] (same-order PBP for offset calc)
    4. OffsetMapper                           → build_timeline + attach_video_time

Strict four-layer isolation (v8 §6): this module contains NO SQL and NO
coordinate / interpolation / clutch-window math. All DB access is delegated
to the ``db`` module (designated writer for writes, ``core.db.batch_query``
for reads) and the reused engine layers.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from backend.services.clutch_replay_engine import schemas as cr_schemas
from backend.services.clutch_replay_engine.service import ClutchReplayService
from backend.services.tactics_engine import db as tactics_db
from backend.services.video_library_engine import (
    analyzer,
    db,
    offset_mapper,
    schemas,
)

logger = logging.getLogger("nbacore.services.video_library_engine")


class VideoLibraryService:
    """Facade that fuses video source management with PBP replay + offset mapping."""

    def __init__(self) -> None:
        self._clutch_replay = ClutchReplayService()

    # ───────────────────────── public API ─────────────────────────

    def list_games(self, req: schemas.VideoLibraryListRequest) -> schemas.VideoLibraryListResult:
        """List games with has_video badges (dim_games LEFT JOIN game_videos)."""
        raw = db.list_games_with_flag(
            season=req.season,
            team=req.team,
            date=req.date,
        )
        games: List[schemas.VideoLibraryGameRow] = []
        for r in raw:
            teams: List[str] = []
            if r.get("home_team_abbr"):
                teams.append(str(r["home_team_abbr"]))
            if r.get("away_team_abbr"):
                teams.append(str(r["away_team_abbr"]))

            home_pts = r.get("home_pts")
            away_pts = r.get("away_pts")
            score = None
            if home_pts is not None and away_pts is not None:
                score = f"{int(home_pts)}-{int(away_pts)}"

            games.append(schemas.VideoLibraryGameRow(
                game_id=str(r["game_id"]),
                season=str(r["season"]),
                teams=teams,
                date=str(r["game_date"]) if r.get("game_date") else None,
                score=score,
                has_video=bool(r.get("video_id")),
                source=str(r["video_source"]) if r.get("video_source") else None,
            ))

        return schemas.VideoLibraryListResult(
            season=req.season,
            total=len(games),
            games=games,
        )

    def get_playback(
        self,
        gameid: str,
        season: str,
        perspective: str = "viewer",
    ) -> schemas.PlaybackResponse:
        """Build the full playback payload for one game.

        Raises :class:`VideoLibraryError` with code 40002 if no video source
        is registered for the game.
        """
        # (1) Get video source — raises 40002 if no source registered.
        src = db.get_video_source(gameid, season)
        if src is None:
            raise schemas.VideoLibraryError(
                40002,
                f"该场无录像来源: game {gameid} season {season}",
            )

        offset = float(src.get("video_offset_seconds", 0.0))
        source_type = str(src.get("source", "other"))

        # Determine video_ref and video_ref_type.
        if source_type == "local_file" and src.get("local_path"):
            video_ref = f"/video-library/media/{src['id']}"
            video_ref_type = "local"
        elif src.get("video_url"):
            video_ref = str(src["video_url"])
            video_ref_type = "url"
        elif src.get("local_path"):
            # Fallback: treat as local even if source label differs.
            video_ref = f"/video-library/media/{src['id']}"
            video_ref_type = "local"
        else:
            video_ref = ""
            video_ref_type = "url"

        # (2) Reuse ClutchReplayService to get frames + meta + clutch segments.
        try:
            cr_req = cr_schemas.ClutchReplayRequest(
                game_id=gameid,
                season=season,
            )
            cr_result = self._clutch_replay.clutch_replay(cr_req)
        except cr_schemas.ClutchReplayError as exc:
            # If no br_crawler replay data, still return the video ref with
            # empty frames (degraded: video can still play, no tactics overlay).
            logger.warning("clutch_replay returned error for %s/%s: %s", gameid, season, exc)
            return schemas.PlaybackResponse(
                game_id=gameid,
                season=str(season),
                video_ref=video_ref,
                video_ref_type=video_ref_type,
                video_offset_seconds=offset,
                frames=[],
                meta={},
                timeline=[],
                clutch_segments=[],
                clutch_players=[],
                perspective=perspective,
            )

        frames: List[dict] = cr_result.frames or []
        meta: Dict[str, Any] = dict(cr_result.meta or {})
        clutch_segments: List[dict] = [
            s.model_dump() for s in cr_result.clutch_segments
        ]
        clutch_players: List[dict] = [
            p.model_dump() for p in cr_result.clutch_players
        ]

        # (3) Load PBP events in the same order as tactics_engine (for offset).
        events = self._load_pbp_events_as_dicts(gameid, season)

        # (4) Build timeline + attach video_time to clutch segments.
        timeline = offset_mapper.build_timeline(events, frames, offset)
        clutch_segments = offset_mapper.attach_video_time(clutch_segments, timeline)

        return schemas.PlaybackResponse(
            game_id=gameid,
            season=str(season),
            video_ref=video_ref,
            video_ref_type=video_ref_type,
            video_offset_seconds=offset,
            frames=frames,
            meta=meta,
            timeline=timeline,
            clutch_segments=clutch_segments,
            clutch_players=clutch_players,
            perspective=perspective,
        )

    def upsert_video_source(self, req: schemas.UpsertVideoSourceRequest) -> schemas.VideoSourceRow:
        """Add or update a video source for one game (UPSERT)."""
        # Validate gameid exists in dim_games.
        if not self._game_exists(req.gameid, req.season):
            raise schemas.VideoLibraryError(
                40001,
                f"比赛不存在或 season 不匹配: gameid={req.gameid} season={req.season}",
            )
        row = db.upsert_video_source(
            gameid=req.gameid,
            season=req.season,
            source=req.source,
            video_url=req.video_url,
            local_path=req.local_path,
            video_offset_seconds=req.video_offset_seconds,
        )
        return self._row_to_source(row)

    def delete_video_source(self, gameid: str, season: str) -> int:
        """Delete the video source for one game. Returns deleted row count."""
        return db.delete_video_source(gameid, season)

    def bulk_import(self, req: schemas.BulkImportRequest) -> schemas.BulkImportResult:
        """Batch upsert video sources. Invalid gameids are rejected and reported."""
        items = [item.model_dump() for item in req.items]
        result = db.bulk_import(items)
        return schemas.BulkImportResult(
            inserted=result["inserted"],
            updated=result["updated"],
            rejected=result["rejected"],
        )

    def analyze(
        self,
        gameid: str,
        season: str,
        provider: str = "static",
    ) -> schemas.GameAnalysis:
        """Run AI game analysis (P2). v1: static returns placeholder, llm → 501."""
        # Get video_ref for the analyzer.
        src = db.get_video_source(gameid, season)
        video_ref = ""
        if src:
            if src.get("video_url"):
                video_ref = str(src["video_url"])
            elif src.get("local_path"):
                video_ref = f"/video-library/media/{src['id']}"

        analyzer_cls = analyzer.REGISTRY.get(provider)
        if analyzer_cls is None:
            raise schemas.VideoLibraryError(
                40001,
                f"unknown analyzer provider: '{provider}'",
            )
        instance = analyzer_cls()
        return instance.analyze(gameid, season, video_ref)

    # ───────────────────────── internal helpers ─────────────────────────

    @staticmethod
    def _load_pbp_events_as_dicts(gameid: str, season: str) -> List[dict]:
        """Load PBP events via tactics_engine.db.load_pbp_events and convert to dicts.

        The events are returned in the exact same ordering as the replay frames
        (``period ASC, clock_seconds DESC, id ASC``), so ``event_index`` is
        consistent between frames and the timeline.
        """
        pbp_events = tactics_db.load_pbp_events(gameid, season)
        return [
            {
                "event_index": ev.event_index,
                "period": ev.period,
                "clock_seconds": ev.clock_seconds,
            }
            for ev in pbp_events
        ]

    @staticmethod
    def _game_exists(gameid: str, season: str) -> bool:
        """Check if a game exists in dim_games."""
        from backend.core import db as core_db
        rows = core_db.batch_query(
            "SELECT 1 AS ok FROM dim_games WHERE game_id = %s AND season = %s::integer LIMIT 1",
            (str(gameid), int(season)),
        )
        return bool(rows)

    @staticmethod
    def _row_to_source(row: Dict[str, Any]) -> schemas.VideoSourceRow:
        """Convert a raw DB dict to a :class:`VideoSourceRow`."""
        return schemas.VideoSourceRow(
            id=row.get("id"),
            gameid=str(row.get("gameid", "")),
            season=str(row.get("season", "")),
            source=str(row.get("source", "other")),
            video_url=row.get("video_url"),
            local_path=row.get("local_path"),
            video_offset_seconds=float(row.get("video_offset_seconds", 0.0)),
            created_at=str(row["created_at"]) if row.get("created_at") else None,
        )
