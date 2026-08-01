"""NBACore v8 §2 Layer 1 (Data Layer) — Data-coverage timeline loader.

This module is the SOLE place where the ``/coverage`` router's data is read
from PostgreSQL + the raw-archive filesystem. It follows the v8 §2 / §6 hard
rules:

    - SELECT-only. Every DB read goes through ``backend.core.db.batch_query``
      (which validates the SQL string). All table names used here are trusted
      module constants (never user input), so there is no dynamic identifier to
      bind with ``psycopg2.sql.Identifier`` — ``batch_query`` is sufficient.
    - The big tables (play_by_play ~18M, player_gamelog ~2M) live on an external
      USB drive. Per the performance contract they must NOT be fully scanned on
      every poll:
          * play_by_play   -> the filesystem proxy
            ``raw_archive/br/{season}/*.html`` is the PRIMARY source (fast, and
            it IS the PBP source). When that archive is empty we transparently
            fall back to the cheap ``dim_games.pbp_imported`` per-season proxy
            (a small 70k-row table), flagged ``approx``.
          * player_gamelog -> has no season index; a per-season GROUP BY times
            out (>30s, observed). We only run a fast total ``COUNT(*)`` and flag
            the dataset ``approx`` (no per-season breakdown).
    - Filesystem roots come from ``common.bridge_constants.ARCHIVE_ROOT`` and
      ``common.player_page_cache.CACHE_ROOT`` (which honor the NBA_ARCHIVE_ROOT
      env var) — never hardcoded ``/Volumes/12T/NBA``. A safe fallback mirrors
      the exact same env logic if ``common`` is not importable.

The router (``backend.api.routers.coverage``) only calls :func:`get_coverage`
and never touches the DB or filesystem itself.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, date
from pathlib import Path
from typing import Any

from backend.core.db import batch_query

logger = logging.getLogger("nbacore.data_layer.coverage_loader")

# ---------------------------------------------------------------------------
# Filesystem root resolution (honor NBA_ARCHIVE_ROOT; never hardcode the drive)
# ---------------------------------------------------------------------------
def _resolve_paths() -> tuple[Path, Path]:
    """Return ``(archive_root, cache_root)``.

    Prefer the project ``common`` constants (single source of truth). If those
    are not importable we replicate their exact env logic as a safe fallback so
    the loader still works on any machine.
    """
    try:  # pragma: no cover - depends on runtime environment
        from common.bridge_constants import ARCHIVE_ROOT  # type: ignore
        from common.player_page_cache import CACHE_ROOT  # type: ignore
        return Path(ARCHIVE_ROOT), Path(CACHE_ROOT)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("common constants unavailable (%s); using env fallback", exc)
        root = os.environ.get("NBA_ARCHIVE_ROOT", "/Volumes/12T/NBA/raw_archive")
        return Path(root), Path(root) / "br_players"


_ARCHIVE_ROOT, _CACHE_ROOT = _resolve_paths()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _fmt_season(s_int: int) -> str:
    """Render a season-ending year (e.g. 2026) as ``2025-26``.

    ``dim_games.season`` stores the ENDING calendar year of the NBA season
    (verified: ``MAX(game_date).year == season`` for every season), so the
    label is derived from ``s_int - 1``.
    """
    return f"{s_int - 1}-{str(s_int)[2:]}"


def _safe_query(sql: str, params: tuple = ()) -> list[dict]:
    """Run a SELECT via batch_query, returning ``[]`` on any failure.

    A single failing query must never break the whole coverage report — we
    degrade gracefully and let the caller show a gap for that dataset.
    """
    try:
        return batch_query(sql, params)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("coverage query failed | %s | %s", sql[:80], exc)
        return []


def _count_br_pbp_by_season(ref_ints: list[int]) -> dict[int, int]:
    """Count ``*.html`` files under ``ARCHIVE_ROOT/br/{season}`` per season.

    PRIMARY source for play_by_play coverage. Only scans season dirs that exist
    in the reference; missing dirs → 0. Cheap even if the archive is large.
    """
    out: dict[int, int] = {s: 0 for s in ref_ints}
    br_dir = _ARCHIVE_ROOT / "br"
    if not br_dir.is_dir():
        return out
    try:
        for s in ref_ints:
            d = br_dir / str(s)
            if not d.is_dir():
                continue
            n = 0
            try:
                for f in os.scandir(d):
                    if f.is_file() and f.name.lower().endswith(".html"):
                        n += 1
            except OSError:
                n = 0
            out[s] = n
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("br PBP filesystem scan failed: %s", exc)
    return out


def _count_espn_archive_by_season() -> dict[int, int]:
    """Count files under ``ARCHIVE_ROOT/espn/{YYYY-MM-DD}`` grouped by season.

    Date dirs map to a season via month >= July => start year = year, else
    year - 1 (matches ``dim_games.season`` semantics). Fast: only ~774 dirs.
    """
    out: dict[int, int] = {}
    espn_dir = _ARCHIVE_ROOT / "espn"
    if not espn_dir.is_dir():
        return out
    try:
        for entry in os.scandir(espn_dir):
            if not entry.is_dir():
                continue
            parts = entry.name.split("-")
            if len(parts) != 3:
                continue
            try:
                y, m = int(parts[0]), int(parts[1])
            except ValueError:
                continue
            s_start = y if m >= 7 else y - 1
            n = 0
            try:
                n = sum(1 for f in os.scandir(entry.path) if f.is_file())
            except OSError:
                n = 0
            out[s_start] = out.get(s_start, 0) + n
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("espn archive filesystem scan failed: %s", exc)
    return out


def _count_br_players() -> int:
    """Total cached BR player pages (``*.html``) under CACHE_ROOT."""
    if not _CACHE_ROOT.is_dir():
        return 0
    try:
        return sum(1 for _ in _CACHE_ROOT.rglob("*.html"))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("br_players filesystem scan failed: %s", exc)
        return 0


def _build_season_coverage(
    count_by_int: dict[int, int],
    ref: list[dict],
    future_labels: set[str] = set(),
) -> dict[str, dict]:
    """Build ``{season_label: {count, expected, pct, future}}`` from per-int counts."""
    cov: dict[str, dict] = {}
    for x in ref:
        cnt = int(count_by_int.get(x["s_int"], 0))
        exp = x["expected"]
        pct = round(cnt / exp, 4) if exp else 0.0
        cov[x["label"]] = {
            "count": cnt,
            "expected": exp,
            "pct": pct,
            "future": x["label"] in future_labels,
        }
    return cov


def _span(count_by_int: dict[int, int], ref: list[dict]) -> dict[str, Any]:
    """First/last season (label) that has any coverage; else nulls."""
    present = [x["label"] for x in ref if count_by_int.get(x["s_int"], 0) > 0]
    if present:
        return {"first": present[0], "last": present[-1]}
    return {"first": None, "last": None}


def _season_dataset(
    key: str,
    label: str,
    source: str,
    count_by_int: dict[int, int],
    ref: list[dict],
    *,
    approx: bool = False,
    note: str = "",
    future_labels: set[str] = set(),
) -> dict:
    """Assemble a season-based dataset entry."""
    return {
        "key": key,
        "label": label,
        "by": "season",
        "coverage": _build_season_coverage(count_by_int, ref, future_labels),
        "span": _span(count_by_int, ref),
        "source": source,
        "approx": approx,
        "note": note,
        "future_labels": sorted(future_labels),
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def get_coverage() -> dict:
    """Compute the full data-coverage timeline.

    Returns a JSON-serializable dict with:

        generated_at          ISO timestamp
        fetch_duration_seconds wall-clock seconds for this computation
        seasons               ordered list of season labels (reference axis)
        reference             {"dim_games": {season: expected_count}}
        datasets              list of dataset coverage entries

    Every DB read is a small-table GROUP BY or a fast COUNT(*); the heavy
    tables are handled via filesystem proxies / approx totals only, so this
    returns in a few seconds even with the DB on an external drive.
    """
    t0 = time.time()

    # 1) Reference axis: dim_games grouped by season (expected games/season).
    ref_rows = _safe_query(
        "SELECT season, COUNT(*) AS n FROM dim_games "
        "WHERE season IS NOT NULL GROUP BY season ORDER BY season"
    )
    ref: list[dict] = []
    for r in ref_rows:
        s_int = int(r["season"])
        ref.append({"s_int": s_int, "label": _fmt_season(s_int), "expected": int(r["n"])})
    seasons = [x["label"] for x in ref]
    expected_by_label = {x["label"]: x["expected"] for x in ref}
    ref_ints = [x["s_int"] for x in ref]

    # Future-season guard: a season whose earliest game date is still in the
    # future has not started. Mark those labels so the dashboard greys them out
    # ("未开始") instead of flagging missing PBP/boxscore as gaps.
    mn_rows = _safe_query(
        "SELECT season, MIN(game_date) AS mn FROM dim_games "
        "WHERE season IS NOT NULL GROUP BY season"
    )
    min_date_by_int = {int(r["season"]): r.get("mn") for r in mn_rows}
    today = date.today()
    future_labels: set[str] = set()
    for x in ref:
        mn = min_date_by_int.get(x["s_int"])
        if mn is not None and mn > today:
            future_labels.add(x["label"])

    datasets: list[dict] = []

    # 2) dim_games itself — the reference (pct = 1.0 everywhere).
    datasets.append(_season_dataset(
        "dim_games", "比赛主表 dim_games", "dim_games (reference)",
        {x["s_int"]: x["expected"] for x in ref}, ref,
        note="比赛主表，作为各数据集覆盖率的基准分母（expected）。",
        future_labels=future_labels,
    ))

    # 3) play_by_play — filesystem proxy PRIMARY, dim_games.pbp_* fallback.
    fs_counts = _count_br_pbp_by_season(ref_ints)
    fs_total = sum(fs_counts.values())
    # Cheap per-season proxy from the small dim_games table.
    pbp_proxy_rows = _safe_query(
        "SELECT season, "
        "SUM(CASE WHEN pbp_imported THEN 1 ELSE 0 END) AS imp, "
        "SUM(CASE WHEN pbp_saved THEN 1 ELSE 0 END) AS saved "
        "FROM dim_games WHERE season IS NOT NULL GROUP BY season ORDER BY season"
    )
    proxy_by_int: dict[int, int] = {}
    proxy_total = 0
    for r in pbp_proxy_rows:
        s_int = int(r["season"])
        imp = int(r.get("imp") or 0)
        saved = int(r.get("saved") or 0)
        val = imp if imp > 0 else saved
        proxy_by_int[s_int] = val
        proxy_total += val

    if fs_total > 0:
        pbp_counts = fs_counts
        pbp_source = "raw_archive/br/{season}/*.html"
        pbp_approx = False
        pbp_note = "逐回合原始 HTML 归档（按赛季目录统计 .html 文件数）。"
    else:
        pbp_counts = proxy_by_int
        pbp_source = "dim_games.pbp_imported (raw_archive/br 归档为空，回退代理)"
        pbp_approx = True
        pbp_note = (
            "filesystem 归档 raw_archive/br 当前为空（0 文件），已回退到 "
            "dim_games.pbp_imported / pbp_saved 逐季代理（小表，快速；approx）。"
        )
    pbp_ds = _season_dataset(
        "play_by_play", "逐回合 PBP", pbp_source, pbp_counts, ref,
        approx=pbp_approx, note=pbp_note,
        future_labels=future_labels,
    )
    pbp_ds["filesystem_total"] = fs_total
    pbp_ds["db_proxy_total"] = proxy_total
    datasets.append(pbp_ds)

    # 4) game_id_map — DB GROUP BY season (5k rows, fast).
    gim_rows = _safe_query(
        "SELECT season, COUNT(*) AS n FROM game_id_map "
        "WHERE season IS NOT NULL GROUP BY season"
    )
    gim_by_int = {int(r["season"]): int(r["n"]) for r in gim_rows}
    datasets.append(_season_dataset(
        "game_id_map", "比赛ID映射 game_id_map", "game_id_map (GROUP BY season)",
        gim_by_int, ref,
        note="跨源比赛 ID 映射表，按 season 统计。",
        future_labels=future_labels,
    ))

    # 5) espn_boxscore — DB GROUP BY season (5k rows, fast).
    eb_rows = _safe_query(
        "SELECT season, COUNT(*) AS n FROM espn_boxscore "
        "WHERE season IS NOT NULL GROUP BY season"
    )
    eb_by_int = {int(r["season"]): int(r["n"]) for r in eb_rows}
    datasets.append(_season_dataset(
        "espn_boxscore", "ESPN 盒分 espn_boxscore", "espn_boxscore (GROUP BY season)",
        eb_by_int, ref,
        note="ESPN 盒分表，按 season 统计。",
        future_labels=future_labels,
    ))

    # 6) raw_archive/espn — filesystem count by season (date dirs -> season).
    espn_fs = _count_espn_archive_by_season()
    datasets.append(_season_dataset(
        "raw_archive_espn", "原始归档 espn/{date}", "raw_archive/espn/{date}/*",
        espn_fs, ref,
        note="按 YYYY-MM-DD 目录反推赛季，统计每个日期目录下的文件数。",
        future_labels=future_labels,
    ))

    # 7) player_gamelog — approx: fast total COUNT(*) only (no season index).
    pg_total = 0
    pg_rows = _safe_query("SELECT COUNT(*) AS n FROM player_gamelog")
    if pg_rows:
        pg_total = int(pg_rows[0]["n"])
    datasets.append({
        "key": "player_gamelog",
        "label": "球员比赛日志 player_gamelog",
        "by": "approx",
        "coverage": {},
        "span": {"first": None, "last": None, "approx": True},
        "source": "player_gamelog COUNT(*)",
        "approx": True,
        "total": pg_total,
        "note": (
            "约 207 万行、无 season 索引，逐季 GROUP BY 在外部盘上超 30s 被取消；"
            "仅返回总条数（approx），无逐季覆盖。前端以近似行单独展示。"
        ),
    })

    # 8) Attribute coverage: dim_players nickname / bio_ext + br_players cache.
    dp_total = 0
    dp_rows = _safe_query("SELECT COUNT(*) AS n FROM dim_players")
    if dp_rows:
        dp_total = int(dp_rows[0]["n"])
    nick_rows = _safe_query(
        "SELECT COUNT(*) AS n FROM dim_players WHERE nickname IS NOT NULL"
    )
    nick = int(nick_rows[0]["n"]) if nick_rows else 0
    bio_rows = _safe_query(
        "SELECT COUNT(*) AS n FROM dim_players WHERE bio_ext_scraped_at IS NOT NULL"
    )
    bio = int(bio_rows[0]["n"]) if bio_rows else 0

    player_attrs = [
        {
            "key": "nickname",
            "label": "绰号 nickname",
            "present": nick,
            "pct": round(nick / dp_total, 4) if dp_total else 0.0,
        },
        {
            "key": "bio_ext",
            "label": "球员简介 bio_ext",
            "present": bio,
            "pct": round(bio / dp_total, 4) if dp_total else 0.0,
        },
    ]
    datasets.append({
        "key": "dim_players_attrs",
        "label": "球员属性覆盖 dim_players",
        "by": "attribute",
        "total": dp_total,
        "attributes": player_attrs,
        "source": "dim_players",
        "approx": False,
        "note": (
            "球员级（非时间）属性覆盖率。bio_ext 以 bio_ext_scraped_at 非空代理"
            "（dim_players 无 bio_ext 文本列，仅有抓取时间戳）。"
        ),
    })

    br_players_total = _count_br_players()
    datasets.append({
        "key": "br_players",
        "label": "BR 球员主页缓存 br_players",
        "by": "attribute",
        "total": dp_total,
        "attributes": [
            {
                "key": "br_players",
                "label": "BR 球员主页缓存",
                "present": br_players_total,
                "pct": round(br_players_total / dp_total, 4) if dp_total else 0.0,
            }
        ],
        "source": "raw_archive/br_players/*",
        "approx": False,
        "note": "缓存命中数 / dim_players 总数（属性级覆盖率）。",
    })

    elapsed = round(time.time() - t0, 3)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "fetch_duration_seconds": elapsed,
        "seasons": seasons,
        "reference": {"dim_games": expected_by_label},
        "future_seasons": sorted(future_labels),
        "datasets": datasets,
    }
