#!/usr/bin/env python3
"""
scrape_lebron.py  --  Harvest bball-index "Daily LEBRON" into a local JSONL.

Where the data actually lives
-----------------------------
bball-index.com only EMBEDS an iframe; the real dashboard is served by
fanspo.com at:

    https://fanspo.com/bbi-role-explorer/api/game-lebron

The endpoint is a plain JSON API (no auth / cookie / special header required).
Two view modes:
  * view_mode=games  -> player x game-day rows (26629 for 2025-26)
  * view_mode=players -> per-player season-aggregate rows (one row per
                         player-season, all seasons; ~83k rows total)

We use view_mode=players and KEEP rows whose Season == --season (default
2025-26). Each row already carries the season-to-date LEBRON decomposition.

Row columns (verified):
  PLAYER_ID, Name, Season, ThroughDate, Mins, daily_mins,
  LEBRON, OLEBRON, DLEBRON, boxLEBRON, LEBRON WAR, TotalLuck,
  OffPoss, DefPoss, cumulative_off_poss, cumulative_def_poss,
  Offensive Points Added, Defensive Points Saved

PLAYER_ID is the NBA nba_id (returned as float -> cast to int).

Output
------
  <out>.jsonl   one JSON object per player (Season == --season), resumable.

Design (standing automation pref: cache everything, errors non-blocking):
  * Outbound proxy stripped so requests leave directly.
  * Per-request try/except: failure -> None, log, continue.
  * Paginated; stops at last page (data length < limit) or empty data.
"""
import os
import sys
import json
import time
import argparse
import urllib.request
import urllib.error
from datetime import date

BASE = "https://fanspo.com/bbi-role-explorer/api/game-lebron"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

for _v in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
           "all_proxy", "ALL_PROXY"):
    os.environ.pop(_v, None)


def fetch_json(url, retries=4, timeout=30):
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if r.status != 200:
                    return None
                body = r.read().decode("utf-8", "replace")
            if not body:
                return None
            return json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
            time.sleep(1.5 * attempt)
        except Exception as e:  # noqa: BLE001 - error-tolerant by design
            last = e
            time.sleep(1.5 * attempt)
    sys.stderr.write(f"[warn] fetch failed {url}: {last}\n")
    return None


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _i(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__),
                                                   "lebron.jsonl"))
    ap.add_argument("--season", default="2025-26",
                    help="NBA season label to keep (default 2025-26)")
    ap.add_argument("--limit", type=int, default=500,
                    help="rows per page (max accepted by API)")
    ap.add_argument("--pace", type=float, default=0.15,
                    help="seconds between page requests")
    ap.add_argument("--max-pages", type=int, default=0,
                    help="safety cap on pages (0=until last page)")
    args = ap.parse_args()

    snap = date.today().isoformat()
    written = 0
    skipped_seasons = 0
    page = 1
    done_pages = 0
    consecutive_empty = 0
    seen = set()
    while True:
        if args.max_pages and page > args.max_pages:
            break
        url = (f"{BASE}?page={page}&limit={args.limit}&season={args.season}"
               f"&start_date=&end_date=&mode=table&view_mode=players")
        d = fetch_json(url)
        if not d or not isinstance(d.get("data"), list):
            sys.stderr.write(f"[warn] page {page}: no data, stopping\n")
            break
        rows = d["data"]
        if not rows:
            break
        kept_this_page = 0
        new_this_page = 0
        with open(args.out, "a") as fh:
            for r in rows:
                if str(r.get("Season")) != args.season:
                    skipped_seasons += 1
                    continue
                nid = _i(r.get("PLAYER_ID"))
                if nid is None:
                    continue
                # view_mode=players is actually DAILY (player x day), globally
                # sorted by ThroughDate DESC. Keep only the FIRST (latest) row
                # per player -> season-final LEBRON. Skip older daily rows.
                if nid in seen:
                    continue
                seen.add(nid)
                rec = {
                    "snapshot_date": snap,
                    "nba_id": nid,
                    "player_name": r.get("Name"),
                    "season": args.season,
                    "through_date": r.get("ThroughDate"),
                    "lebron": _f(r.get("LEBRON")),
                    "olebron": _f(r.get("OLEBRON")),
                    "dlebron": _f(r.get("DLEBRON")),
                    "boxlebron": _f(r.get("boxLEBRON")),
                    "lebron_war": _f(r.get("LEBRON WAR")),
                    "total_luck": _f(r.get("TotalLuck")),
                    "mins": _f(r.get("Mins")),
                    "off_poss": _f(r.get("OffPoss")),
                    "def_poss": _f(r.get("DefPoss")),
                    "cum_off_poss": _f(r.get("cumulative_off_poss")),
                    "cum_def_poss": _f(r.get("cumulative_def_poss")),
                    "off_points_added": _f(r.get("Offensive Points Added")),
                    "def_points_saved": _f(r.get("Defensive Points Saved")),
                }
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                written += 1
                kept_this_page += 1
                new_this_page += 1
        done_pages += 1
        print(f"[page {page}] players_written={written} new={new_this_page} "
              f"(skipped_other_seasons={skipped_seasons})")
        # Early-stop: data is ThroughDate-desc, so once a full page yields no
        # NEW player (every id already seen) we have all season-final rows.
        if new_this_page == 0:
            print(f"[early-stop] no new players on page {page}; all captured")
            break
        if len(rows) < args.limit:
            break
        page += 1
        if args.pace:
            time.sleep(args.pace)
    print(f"[done] pages={done_pages} players_written={written} "
          f"other_seasons_skipped={skipped_seasons}")


if __name__ == "__main__":
    main()
