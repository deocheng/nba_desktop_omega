#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""crawl_team_pages.py — 统一编排器（30 队 × 交易(倒序) + HOF + 高管）。

设计原则（docs/team_crawl_design.md §1.2 / 类图 / 时序图）：
  * 本文件**只组合调用** ``transactions_crawl`` / ``hof_exec`` 两包的公开函数，
    不重写抓取 / 解析 / 落库逻辑。任何 30 队泛化、拼接 bug 修复、孪生去重
    upsert 都在那两包内完成，本编排器一概不碰。
  * 离线 (``--offline-dir``) 与在线 (UC Chrome) 由 fetch 层决定；本编排器
    只负责 30 队循环、多年倒序、三类型调度、断点续爬 (幂等) 与进度统计。
  * 任何单队 / 单年 / 单类型的异常（404、FileNotFound、解析异常、落库异常）
    一律捕获并 SKIP，打印错误但不中断整轮 —— 靠 DB upsert 幂等 + 离线缓存
    实现续跑（docs/run_live_crawl.md）。

关键事实（务必遵守）：
  * 英文名来自 ``common.team_names.TEAM_FULL_NAME``（代码字典，英文）；
    **绝不**用 ``dim_teams.team_name``（中文）当英文名源。
  * BR slug 来自 ``common.team_names.get_br_slug``（BR_TEAM_SLUGS）。
  * DB 口令只来自 ``.env`` 的 ``DB_PASSWORD``（经 ``hof_exec.config.get_conn``），
    绝不硬编码。

断点续爬：
  * 进度写入 ``crawl_state.json``（PROJECT_ROOT 下）：记录已完成 abbr 清单
    及本次运行的签名 (kind:year_start-year_end)。
  * 参数（kind / 年份区间）不变时，二次运行自动跳过已完成队；参数变化则
    视为新任务，从零开始（旧 completed 清单作废）。
  * ``--force`` 强制重跑所有队（忽略 completed）；``--reset-state`` 运行前
    清空进度文件。

运行：
  .venv/bin/python -m crawl_team_pages --all-teams --year-start 2000 --year-end 2026
  .venv/bin/python -m crawl_team_pages --team DET
  .venv/bin/python -m crawl_team_pages --all-teams --offline-dir det2026_br
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

# 30-team canon abbrs — the single list we iterate as the outer loop.
from common.team_names import TEAM_ABBRS  # noqa: F401  (consumed by sub-packages too)

from transactions_crawl.fetch import (
    fetch_transactions_page,
    looks_like_404 as txn_looks_like_404,
)
from transactions_crawl.parse import parse_transactions
from transactions_crawl.load import upsert_transactions

from hof_exec.fetch import (
    fetch_team_page,
    looks_like_404 as he_looks_like_404,
)
from hof_exec.parse import parse_executives_table, parse_hof_div
from hof_exec.load import upsert_executives, upsert_hof

logger = logging.getLogger("crawl_team_pages")

_KIND_ALL = "all"
_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crawl_state.json")


def _wants(kind: str, target: str) -> bool:
    """Whether ``--kind`` includes ``target`` ('trans'|'hof'|'exec')."""
    return kind == _KIND_ALL or kind == target


def _state_signature(kind: str, year_start: int, year_end: int, offline: bool) -> str:
    # Include the offline/online mode: an offline replay (e.g. DET-only
    # fixtures) must NOT mark teams "completed" for a later live run, which
    # uses a different signature and therefore starts fresh.
    mode = "offline" if offline else "online"
    return f"{kind}:{year_start}-{year_end}:{mode}"


def _load_state() -> dict:
    """Load crawl_state.json, or return an empty skeleton if absent/unreadable."""
    if not os.path.exists(_STATE_FILE):
        return {"signature": None, "completed": []}
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        data.setdefault("signature", None)
        data.setdefault("completed", [])
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("crawl_state.json unreadable (%s); starting fresh", exc)
        return {"signature": None, "completed": []}


def _save_state(state: dict) -> None:
    try:
        with open(_STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, ensure_ascii=False)
    except OSError as exc:
        logger.warning("could not write crawl_state.json: %s", exc)


# ---------------------------------------------------------------------------
# Per-type workers — each isolates its own failure so a bad team/year never
# aborts the whole run. They return the number of rows upserted (0 on skip).
# ---------------------------------------------------------------------------

def run_transactions(
    abbr: str, year_start: int, year_end: int, offline_dir: "str | None"
) -> int:
    """Crawl + parse + upsert one team's transactions, years ``year_end``->``year_start`` (desc)."""
    total = 0
    for year in range(year_end, year_start - 1, -1):
        try:
            html = fetch_transactions_page(abbr, year, offline_dir)
        except FileNotFoundError as exc:
            logger.info("SKIP %s/%s: %s", abbr, year, exc)
            continue
        except Exception as exc:  # warm-up / driver / network
            logger.warning("SKIP %s/%s: fetch error: %s", abbr, year, exc)
            continue

        if txn_looks_like_404(html):
            logger.info("SKIP %s/%s: page looks like 404", abbr, year)
            continue

        try:
            entries = parse_transactions(html, abbr)
        except Exception as exc:
            logger.warning("SKIP %s/%s: parse error: %s", abbr, year, exc)
            continue

        try:
            n = upsert_transactions(entries)
        except Exception as exc:
            logger.warning("SKIP %s/%s: upsert error: %s", abbr, year, exc)
            continue

        logger.info("LOADED %s/%s: %d rows", abbr, year, n)
        total += n
    return total


def run_hof(abbr: str, offline_dir: "str | None") -> int:
    """Crawl + parse + upsert one team's Hall-of-Fame page."""
    try:
        html = fetch_team_page(abbr, "hof", offline_dir)
    except FileNotFoundError as exc:
        logger.info("SKIP %s/hof: %s", abbr, exc)
        return 0
    except Exception as exc:
        logger.warning("SKIP %s/hof: fetch error: %s", abbr, exc)
        return 0

    if he_looks_like_404(html):
        logger.info("SKIP %s/hof: page looks like 404", abbr)
        return 0

    try:
        rows = parse_hof_div(html, abbr)
    except Exception as exc:
        logger.warning("SKIP %s/hof: parse error: %s", abbr, exc)
        return 0

    try:
        n = upsert_hof(rows)
    except Exception as exc:
        logger.warning("SKIP %s/hof: upsert error: %s", abbr, exc)
        return 0

    logger.info("LOADED %s/hof: %d rows", abbr, n)
    return n


def run_executives(abbr: str, offline_dir: "str | None") -> int:
    """Crawl + parse + upsert one team's executives page."""
    try:
        html = fetch_team_page(abbr, "executives", offline_dir)
    except FileNotFoundError as exc:
        logger.info("SKIP %s/exec: %s", abbr, exc)
        return 0
    except Exception as exc:
        logger.warning("SKIP %s/exec: fetch error: %s", abbr, exc)
        return 0

    if he_looks_like_404(html):
        logger.info("SKIP %s/exec: page looks like 404", abbr)
        return 0

    try:
        rows = parse_executives_table(html, abbr)
    except Exception as exc:
        logger.warning("SKIP %s/exec: parse error: %s", abbr, exc)
        return 0

    try:
        n = upsert_executives(rows)
    except Exception as exc:
        logger.warning("SKIP %s/exec: upsert error: %s", abbr, exc)
        return 0

    logger.info("LOADED %s/exec: %d rows", abbr, n)
    return n


def run_team(
    abbr: str, kind: str, year_start: int, year_end: int, offline_dir: "str | None"
) -> "tuple[int, int, int]":
    """Run all requested kinds for a single team. Returns (txn, hof, exec) rows."""
    txn = hof_rows = exec_rows = 0
    if _wants(kind, "trans"):
        txn = run_transactions(abbr, year_start, year_end, offline_dir)
    if _wants(kind, "hof"):
        hof_rows = run_hof(abbr, offline_dir)
    if _wants(kind, "exec"):
        exec_rows = run_executives(abbr, offline_dir)
    return txn, hof_rows, exec_rows


def run_all(
    kind: str,
    year_start: int,
    year_end: int,
    offline_dir: "str | None",
    team: "str | None" = None,
    force: bool = False,
) -> "tuple[int, int, int]":
    """Iterate the 30 teams (or a single team) and accumulate totals.

    Honors ``crawl_state.json`` resume: teams already completed for this exact
    (kind, year range) signature are skipped unless ``force`` is set.
    """
    abbrs = [team] if team else list(TEAM_ABBRS)

    sig = _state_signature(kind, year_start, year_end, bool(offline_dir))
    state = _load_state()
    if state.get("signature") != sig:
        # Parameters changed since the last run -> fresh progress.
        state = {"signature": sig, "completed": []}
    completed = set(state.get("completed", []))

    totals = [0, 0, 0]
    for abbr in abbrs:
        if abbr in completed and not force:
            logger.info("RESUME skip %s (already completed for %s)", abbr, sig)
            continue
        try:
            t, h, e = run_team(abbr, kind, year_start, year_end, offline_dir)
        except Exception as exc:  # never let one team abort the run
            logger.error("SKIP team %s: unexpected error: %s", abbr, exc)
            continue
        totals[0] += t
        totals[1] += h
        totals[2] += e
        completed.add(abbr)
        state["completed"] = sorted(completed)
        _save_state(state)
        logger.info("PROGRESS %d/%d teams done (%s)", len(completed), len(abbrs), abbr)

    logger.info(
        "DONE totals: transactions=%d hof=%d exec=%d",
        totals[0],
        totals[1],
        totals[2],
    )
    return (totals[0], totals[1], totals[2])  # type: ignore[return-value]


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="crawl_team_pages",
        description="Unified 30-team BR page crawler (transactions + HOF + executives).",
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--all-teams",
        action="store_true",
        help="Crawl all 30 teams (from common.team_names.TEAM_ABBRS).",
    )
    mode.add_argument(
        "--team",
        metavar="ABBR",
        help="Crawl a single team by 3-letter abbreviation (e.g. DET).",
    )
    p.add_argument(
        "--year-start",
        type=int,
        default=2000,
        help="First season-start year (inclusive). Default 2000.",
    )
    p.add_argument(
        "--year-end",
        type=int,
        default=2026,
        help="Last season-start year (inclusive). Default 2026.",
    )
    p.add_argument(
        "--offline-dir",
        default=None,
        help="Read captured HTML from this dir instead of live fetch (e.g. det2026_br).",
    )
    p.add_argument(
        "--kind",
        choices=["all", "hof", "exec", "trans"],
        default="all",
        help="Which data kind(s) to crawl. Default all.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-run every team even if already marked completed in crawl_state.json.",
    )
    p.add_argument(
        "--reset-state",
        action="store_true",
        help="Delete crawl_state.json before starting (ignore prior progress).",
    )
    return p


def main(argv: "list[str] | None" = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    args = _build_parser().parse_args(argv)

    if args.team:
        args.team = args.team.upper()
    if args.year_start > args.year_end:
        logger.error(
            "year-start (%d) > year-end (%d); nothing to do",
            args.year_start,
            args.year_end,
        )
        return 0

    if args.reset_state and os.path.exists(_STATE_FILE):
        try:
            os.remove(_STATE_FILE)
            logger.info("reset crawl_state.json")
        except OSError as exc:
            logger.warning("could not remove crawl_state.json: %s", exc)

    run_all(
        kind=args.kind,
        year_start=args.year_start,
        year_end=args.year_end,
        offline_dir=args.offline_dir,
        team=args.team,
        force=args.force,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
