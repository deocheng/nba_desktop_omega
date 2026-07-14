#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_draft_player_ids.py — BR draft-player-id verification crawler
===================================================================

Purpose
-------
Verify each candidate draft `player_id` against its live Basketball-Reference
(BR) player page and classify the result:

    exists_match : page exists AND the page name matches the expected player_name
                   -> correct_id = current player_id, confidence 0.95
    mismatch     : page exists BUT the page name is a different player
                   -> correct_id empty, confidence 0.9
    missing      : page does not exist (BR 404 / index page)
                   -> correct_id empty
    error        : genuine fetch failure (CF challenge not passed / network)
                   -> correct_id empty, logged for retry

Output CSV (appended) has the schema agreed with the data team:

    player_id,player_id_orig,player_name,status,page_name,
    correct_id,confidence,evidence,verified_at

Usage
-----
    # 10-row smoke test (do NOT overwrite the real output)
    python crawler/verify_draft_player_ids.py \
        --candidates docs/diagnostics/draft_376_audit.csv \
        --out /tmp/verify_smoke.csv --limit 10

    # Full idempotent run (the parent session launches this in the background;
    # already-verified ids recorded in --out are skipped automatically)
    python crawler/verify_draft_player_ids.py \
        --candidates docs/diagnostics/draft_376_audit.csv \
        --out docs/diagnostics/draft_corrections.csv --resume

    # Force a clean re-run from scratch (ignores any prior --out content)
    python crawler/verify_draft_player_ids.py \
        --candidates docs/diagnostics/draft_376_audit.csv \
        --out docs/diagnostics/draft_corrections.csv --overwrite

Design notes
------------
* Reuses ``nba_daily_crawler.BrowserManager`` — a SINGLE undetected-chromedriver
  session per run, CF-cookie reuse (persisted to
  ``C:\\autopick\\AutoPick\\nba_data\\.br_cf_cookies.pkl``), and ``atexit``
  cleanup so no orphaned Chrome tree is left behind.
* Idempotent / resumable: any ``player_id`` already present in ``--out`` is
  skipped, so an interrupted 376-row run can simply be re-launched.
* Rate limiting is governed by ``BrowserManager`` (~10–13s/request, well within
  the ≤15/min cap) — no extra artificial sleeps are added here.
* §6 compliance: this is a standalone, approved CLI crawler. It ONLY emits CSV.
  It never opens a database connection and contains NO SQL substrings. Writing
  the verified corrections into ``dim_draft_history`` is delegated to
  ``scripts/draft_a1_load_corrections.py`` (parameterized, single writer).
"""

from __future__ import annotations

import os
import sys
import re
import csv
import time
import logging
import argparse
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# ── §6: this crawler is CSV-only. No DB imports, no SQL. ──────────────────────

# ---------------------------------------------------------------------------
# Locate the shared NBA data root so we can reuse nba_daily_crawler.BrowserManager.
# Script lives at: <NBA_DATA>/crawler/verify_draft_player_ids.py
# Module lives at: <NBA_DATA>/nba_daily_crawler.py
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_NBA_DATA_ROOT = os.path.abspath(os.path.join(_THIS_DIR, ".."))
if _NBA_DATA_ROOT not in sys.path:
    sys.path.insert(0, _NBA_DATA_ROOT)

# BR base URL (matches nba_daily_crawler.Config.BASE_URL).
BR_BASE = "https://www.basketball-reference.com"

# Output schema — fixed column order.
OUTPUT_FIELDS: List[str] = [
    "player_id",
    "player_id_orig",
    "player_name",
    "status",
    "page_name",
    "correct_id",
    "confidence",
    "evidence",
    "verified_at",
]

logger = logging.getLogger("VerifyDraftIDs")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def configure_logging() -> None:
    """Configure a stdlib logger (stdout + file). BrowserManager only needs
    .info/.warning/.error/.debug, all provided by logging.Logger."""
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    try:
        log_dir = os.path.join(_NBA_DATA_ROOT, "logs")
        os.makedirs(log_dir, exist_ok=True)
        fh = logging.FileHandler(
            os.path.join(log_dir, "verify_draft_player_ids.log"),
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        # Logging to file is best-effort; stdout still works.
        pass


# ---------------------------------------------------------------------------
# Name normalization / comparison
# ---------------------------------------------------------------------------
def clean_name(raw: str) -> str:
    """Strip nicknames in parentheses and collapse whitespace."""
    if not raw:
        return ""
    s = re.sub(r"\s*\([^)]*\)\s*", " ", raw)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_name(raw: str) -> str:
    """Lowercase, strip punctuation/diacritics-ascii, collapse to comparable form."""
    s = clean_name(raw).lower()
    s = re.sub(r"[^a-z ]+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ---------------------------------------------------------------------------
# BR page parsing
# ---------------------------------------------------------------------------
def parse_player_page(html: str) -> Tuple[bool, str]:
    """Return (exists, page_name).

    ``exists`` is False when the page is a BR 404 / index page (no player).
    ``page_name`` is the cleaned player name from the page's <h1> (or og:title).
    """
    if not html or len(html) < 500:
        return (False, "")

    low = html.lower()
    # BR 404 / not-found indicators.
    if (
        "page not found" in low
        or "could not be found" in low
        or "file not found" in low
        or "404 error" in low
    ):
        return (False, "")

    try:
        from bs4 import BeautifulSoup
    except Exception:
        return (False, "")

    soup = BeautifulSoup(html, "lxml")

    # Preferred: the player name in <h1>.
    name = ""
    h1 = soup.find("h1")
    if h1:
        name = h1.get_text(" ", strip=True)

    # Fallback: OpenGraph title ("George Brown | Basketball-Reference.com").
    if not name:
        meta = soup.find("meta", attrs={"property": "og:title"})
        if meta and meta.get("content"):
            name = re.sub(
                r"\s*[-|]\s*Basketball-Reference\.com.*$",
                "",
                meta.get("content", ""),
                flags=re.IGNORECASE,
            ).strip()

    name = clean_name(name)
    if not name:
        return (False, "")
    return (True, name)


# ---------------------------------------------------------------------------
# Candidate / output IO
# ---------------------------------------------------------------------------
def read_candidates(path: str) -> List[Dict[str, str]]:
    """Read the audit CSV; return rows with player_id/player_name/player_id_orig."""
    rows: List[Dict[str, str]] = []
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            pid = (r.get("player_id") or "").strip()
            if not pid:
                continue
            rows.append(
                {
                    "player_id": pid,
                    "player_name": (r.get("player_name") or "").strip(),
                    "player_id_orig": (r.get("player_id_orig") or "").strip(),
                }
            )
    return rows


def load_existing_ids(out_path: str) -> set:
    """Load the set of player_id values already present in --out (idempotency)."""
    ids: set = set()
    if not os.path.exists(out_path):
        return ids
    try:
        with open(out_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pid = (row.get("player_id") or "").strip()
                if pid:
                    ids.add(pid)
    except Exception:
        pass
    return ids


# ---------------------------------------------------------------------------
# Core verification of a single candidate
# ---------------------------------------------------------------------------
def verify_one(browser, cand: Dict[str, str], cf_timeout: int) -> Dict[str, str]:
    """Fetch and classify one candidate; return an OUTPUT_FIELDS-shaped dict."""
    pid = cand["player_id"]
    pname = cand["player_name"]
    porig = cand.get("player_id_orig", "")
    letter = (pid[0].lower() if pid else "a")
    url = f"{BR_BASE}/players/{letter}/{pid}.html"
    verified_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    base = {
        "player_id": pid,
        "player_id_orig": porig,
        "player_name": pname,
        "page_name": "",
        "correct_id": "",
        "verified_at": verified_at,
    }

    html = browser.fetch_page(url, cf_timeout=cf_timeout)
    if html is None:
        base.update(
            {
                "status": "error",
                "confidence": "0.0",
                "evidence": "fetch failed (CF challenge not passed or network error)",
            }
        )
        return base

    exists, page_name = parse_player_page(html)
    if not exists:
        base.update(
            {
                "status": "missing",
                "confidence": "0.0",
                "evidence": "page not found (404 / BR index)",
            }
        )
        return base

    if normalize_name(page_name) == normalize_name(pname):
        base.update(
            {
                "status": "exists_match",
                "page_name": page_name,
                "correct_id": pid,
                "confidence": "0.95",
                "evidence": f"name matches ('{pname}')",
            }
        )
        return base

    base.update(
        {
            "status": "mismatch",
            "page_name": page_name,
            "confidence": "0.9",
            "evidence": f"page is for '{page_name}', expected '{pname}'",
        }
    )
    return base


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Verify BR draft player_ids via live player pages (CSV output)."
    )
    p.add_argument("--candidates", required=True,
                   help="Input audit CSV with player_id,player_name,player_id_orig")
    p.add_argument("--out", required=True,
                   help="Output CSV (appended; schema: "
                        "player_id,player_id_orig,player_name,status,page_name,"
                        "correct_id,confidence,evidence,verified_at)")
    p.add_argument("--limit", type=int, default=0,
                   help="Process only the first N candidates (smoke test). 0 = all")
    p.add_argument("--resume", action="store_true",
                   help="Resume: skip player_ids already present in --out (default "
                        "behavior is also idempotent; this flag is explicit)")
    p.add_argument("--overwrite", action="store_true",
                   help="Ignore existing --out content and reprocess everything")
    p.add_argument("--cf-timeout", type=int, default=40,
                   help="Seconds to poll for Cloudflare clearance per request")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    configure_logging()

    # §6: reuse BrowserManager only. Import lazily so --help works without deps.
    try:
        from nba_daily_crawler import BrowserManager  # noqa: F401
    except Exception as exc:  # pragma: no cover
        logger.error("Failed to import nba_daily_crawler.BrowserManager: %s", exc)
        return 2

    # Read candidates.
    try:
        candidates = read_candidates(args.candidates)
    except Exception as exc:
        logger.error("Cannot read candidates CSV %s: %s", args.candidates, exc)
        return 2
    logger.info("Loaded %d candidates from %s", len(candidates), args.candidates)

    # Idempotency / resume handling.
    if args.overwrite:
        existing_ids: set = set()
        open_mode = "w"
        logger.info("--overwrite set: ignoring prior --out and reprocessing all.")
    else:
        existing_ids = load_existing_ids(args.out)
        open_mode = "a"
        if args.resume or existing_ids:
            logger.info(
                "Idempotent/resume: %d player_id(s) already verified, will skip.",
                len(existing_ids),
            )

    # Apply --limit (smoke test).
    if args.limit and args.limit > 0:
        candidates = candidates[: args.limit]
        logger.info("--limit %d: processing first %d candidate(s).",
                    args.limit, len(candidates))

    if not candidates:
        logger.info("No candidates to process. Exiting.")
        return 0

    # Open output (write header only if file is new/empty).
    out_empty = not os.path.exists(args.out) or os.path.getsize(args.out) == 0
    fout = open(args.out, open_mode, newline="", encoding="utf-8")
    writer = csv.writer(fout)
    if open_mode == "w" or out_empty:
        writer.writerow(OUTPUT_FIELDS)
        fout.flush()

    # Single browser session (CF cookie reuse + atexit cleanup).
    browser = BrowserManager(logger)
    browser.start()

    processed = 0
    skipped = 0
    counts: Dict[str, int] = {}

    try:
        for cand in candidates:
            pid = cand["player_id"]
            if pid in existing_ids:
                skipped += 1
                continue
            row = verify_one(browser, cand, args.cf_timeout)
            writer.writerow([row[k] for k in OUTPUT_FIELDS])
            fout.flush()  # persist immediately so interruption is recoverable
            existing_ids.add(pid)
            processed += 1
            counts[row["status"]] = counts.get(row["status"], 0) + 1
            logger.info(
                "[%d/%d] %s -> %s (page_name=%r)",
                processed, len(candidates), pid, row["status"], row["page_name"],
            )
    finally:
        try:
            browser.quit()
        except Exception:
            pass
        fout.close()

    logger.info(
        "DONE. processed=%d skipped=%d counts=%s", processed, skipped, counts
    )
    logger.info("Output written to: %s", os.path.abspath(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
