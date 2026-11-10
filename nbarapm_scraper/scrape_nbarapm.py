#!/usr/bin/env python3
"""
scrape_nbarapm.py  —  Harvest nbarapm.com advanced metrics into a local JSONL.

What it scrapes
---------------
nbarapm.com is a Flask app (nbarapm-flask.replit.app) that aggregates its OWN
"Six Factor RAPM" (time-decay) plus a headline total RAPM/VPM. It does NOT host
DARKO/LEBRON/RAPTOR values (those are only attribution credits on the site).

Two data sources:
  1. GET  /api/search-index   -> full player directory (2917 players).
        Each record: [name, id(nba_id), team, pos, rapm(total), rank, pop, aka]
        `rapm` is the headline total RAPM (float) for ~529 players with enough
        sample; the rest are null. This is the league-wide all-player metric.
  2. POST /api/player/{nba_id}/bundle  -> ~1.5MB per-player analytics package.
        Contains the 6-factor decomposition (oTS/oTOV/oSC/dTS/dTOV/dSC) in
        dashboard.stats[six_factor_timedecay], plus on/off net ratings and full
        season history. Cached to disk; missing players (404) simply keep the
        search-index total.

Output
------
  <out>.jsonl   one JSON object per valid player (resumable: skips nba_ids
                already present unless --force).
  raw_archive/{nba_id}.json   raw bundle payload (cache, enables re-extraction).

Design notes (per standing automation preference: cache everything, all errors
non-blocking, fully autonomous)
  * Outbound proxy is stripped so requests leave directly.
  * Per-request try/except: on failure returns None, logs, continues.
  * Adaptive pace (--pace sec between requests) + bounded retries w/ backoff.
  * Resumable: a player already in the JSONL (or whose raw cache exists when
    --use-cache) is skipped on restart, so the crawl can be killed/ resumed.
"""
import os
import sys
import json
import time
import argparse
import urllib.request
import urllib.error
from datetime import date

BASE = "https://www.nbarapm.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Strip any outbound proxy so requests leave directly (sandbox proxy breaks egress).
for _v in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
           "all_proxy", "ALL_PROXY"):
    os.environ.pop(_v, None)


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def fetch_json(url, method="GET", data=None, retries=3, timeout=30):
    """Error-tolerant JSON fetch. Returns parsed dict/list, or None on failure/404."""
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                url, data=data, method=method,
                headers={"User-Agent": UA, "Accept": "application/json",
                         "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode("utf-8", "replace")
            if not body:
                return None
            return json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
            time.sleep(2 * attempt)
        except Exception as e:  # noqa: BLE001 - error-tolerant by design
            last = e
            time.sleep(2 * attempt)
    sys.stderr.write(f"[warn] fetch failed {url}: {last}\n")
    return None


def parse_rapm_val(s):
    if s is None:
        return None
    s = str(s).replace("%", "").replace("+", "").strip()
    return _num(s)


def extract_6factor(bundle):
    """Pull oTS/oTOV/oSC/dTS/dTOV/dSC from dashboard.stats six_factor section."""
    stats = ((bundle or {}).get("dashboard") or {}).get("stats") or []
    out = {}
    for sec in stats:
        if sec.get("key") == "six_factor_timedecay":
            for st in (sec.get("stats") or []):
                lbl = st.get("label")
                if lbl in ("oTS", "oTOV", "oSC", "dTS", "dTOV", "dSC"):
                    out[lbl] = parse_rapm_val(st.get("value"))
    return out


def find_onoff(bundle):
    """Grab on/off net ratings from dashboard.stats.

    The bundle's dashboard.stats has three sibling sections -- 'NET RATING',
    'OFF RATING', 'DEF RATING' -- each containing stat items labelled 'OnCourt'
    and 'On-Off'. We map them to the canonical output keys.
    """
    result = {}
    # (section_title, stat_label) -> output_key
    m = {
        ("NET RATING", "OnCourt"): "on_court_net",
        ("NET RATING", "On-Off"): "on_off_net",
        ("OFF RATING", "OnCourt"): "off_rtg",
        ("DEF RATING", "OnCourt"): "def_rtg",
    }

    def scan(items, sec_title=""):
        for it in (items or []):
            if isinstance(it, dict):
                key = (sec_title, it.get("label"))
                if key in m and it.get("value") is not None:
                    result[m[key]] = parse_rapm_val(it.get("value"))
                scan(it.get("stats"), sec_title)
                scan(it.get("subsections"), sec_title)

    stats = ((bundle or {}).get("dashboard") or {}).get("stats") or []
    for sec in stats:
        t = sec.get("label") or sec.get("key") or ""
        scan(sec.get("stats"), t)
        scan(sec.get("subsections"), t)
    return result


def load_search_index(cache_dir):
    path = os.path.join(cache_dir, "search_index.json")
    if os.path.exists(path):
        si = json.load(open(path))
    else:
        si = fetch_json(f"{BASE}/api/search-index")
        if si is None:
            sys.stderr.write("[fatal] cannot fetch /api/search-index\n")
            sys.exit(2)
        os.makedirs(cache_dir, exist_ok=True)
        json.dump(si, open(path, "w"))
    f = si.get("fields", [])
    i = {name: k for k, name in enumerate(f)}
    players = si.get("players", [])
    valid = []
    for p in players:
        rapm = _num(p[i["rapm"]]) if "rapm" in i else None
        pop = _num(p[i["pop"]]) if "pop" in i else None
        if rapm is None or pop is None or pop <= 0:
            continue
        valid.append({
            "nba_id": int(p[i["id"]]),
            "player_name": p[i["name"]],
            "team_abbr": p[i["team"]],
            "position": p[i["pos"]],
            "rapm_total": rapm,
            "rapm_rank": int(p[i["rank"]]) if _num(p[i["rank"]]) is not None else None,
            "rapm_pop": int(pop),
        })
    valid.sort(key=lambda r: r["rapm_total"], reverse=True)
    return valid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__),
                                                   "nbarapm_rapm.jsonl"))
    ap.add_argument("--cache-dir", default=os.path.join(os.path.dirname(__file__),
                                                          "raw_archive"))
    ap.add_argument("--pace", type=float, default=0.4,
                    help="seconds between player bundle requests")
    ap.add_argument("--limit", type=int, default=0, help="max players to fetch (0=all)")
    ap.add_argument("--force", action="store_true",
                    help="re-fetch even if already in JSONL / cache")
    ap.add_argument("--use-cache", action="store_true",
                    help="use cached raw bundle if present (skip network)")
    args = ap.parse_args()

    os.makedirs(args.cache_dir, exist_ok=True)
    valid = load_search_index(args.cache_dir)
    print(f"[info] {len(valid)} players with valid RAPM from search-index")

    # Resume set
    done = set()
    if os.path.exists(args.out) and not args.force:
        with open(args.out) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    done.add(int(json.loads(line)["nba_id"]))
                except Exception:
                    pass
    print(f"[info] already harvested: {len(done)}")

    count = 0
    fetched = 0
    skipped = 0
    errors = 0
    snap = date.today().isoformat()
    fh = open(args.out, "a")
    targets = valid if args.limit <= 0 else valid[:args.limit]
    for rec in targets:
        nid = rec["nba_id"]
        if nid in done and not args.force:
            skipped += 1
            continue
        cache_path = os.path.join(args.cache_dir, f"{nid}.json")
        bundle = None
        if args.use_cache and os.path.exists(cache_path):
            try:
                bundle = json.load(open(cache_path))
            except Exception:
                bundle = None
        if bundle is None:
            payload = json.dumps({}).encode("utf-8")
            bundle = fetch_json(f"{BASE}/api/player/{nid}/bundle",
                                method="POST", data=payload)
            fetched += 1
            if bundle is not None:
                json.dump(bundle, open(cache_path, "w"))
            else:
                errors += 1
        six = extract_6factor(bundle) if bundle else {}
        oo = find_onoff(bundle) if bundle else {}
        comp = {k: six.get(k) for k in ("oTS", "oTOV", "oSC", "dTS", "dTOV", "dSC")}
        svals = [v for v in comp.values() if v is not None]
        rapm_sum = round(sum(svals), 3) if svals else None
        row = {
            "snapshot_date": snap,
            "nba_id": nid,
            "player_name": rec["player_name"],
            "team_abbr": rec["team_abbr"],
            "position": rec["position"],
            "rapm_total": rec["rapm_total"],
            "rapm_rank": rec["rapm_rank"],
            "rapm_pop": rec["rapm_pop"],
            "ots": comp.get("oTS"), "otov": comp.get("oTOV"),
            "osc": comp.get("oSC"), "dts": comp.get("dTS"),
            "dtov": comp.get("dTOV"), "dsc": comp.get("dSC"),
            "rapm_sum": rapm_sum,
            "on_off_net": _num(oo.get("on_off_net")),
            "on_court_net": _num(oo.get("on_court_net")),
            "off_rtg": _num(oo.get("off_rtg")),
            "def_rtg": _num(oo.get("def_rtg")),
            "has_bundle": bundle is not None,
        }
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
        count += 1
        done.add(nid)
        if args.pace and fetched and fetched % 1 == 0:
            time.sleep(args.pace)
    fh.close()
    print(f"[done] written={count} fetched={fetched} skipped={skipped} "
          f"bundle_errors={errors}")


if __name__ == "__main__":
    main()
