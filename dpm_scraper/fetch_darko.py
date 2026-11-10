#!/usr/bin/env python3
"""
fetch_darko.py -- Fetch current DARKO DPM values by extracting the embedded
hydration payload from https://www.darko.app/ and write it as JSON.

WHY THIS EXISTS
---------------
DARKO publishes no stable JSON API (`/data/dpm.json` is 404). But the homepage
embeds the full current player table as a **JS object literal** inside a SvelteKit
hydration payload:

    data: [null,{type:"data",data:{players:[{nba_id:203999,player_name:"Nikola Jokic",
           team_name:"Denver Nuggets",...,dpm:6.76,o_dpm:4.79046,d_dpm:1.96954,...}, ...]}}]

It is NOT strict JSON: object keys are unquoted, and numbers may use a leading
dot (`.534094`). So we extract the array by bracket matching, then normalize it
into strict JSON before parsing.

OUTPUT CONTRACT
---------------
Writes the parsed list to `dpm_scraper/darko_players.json` (the file consumed by
`load_dpm.py`) and a dated archive copy under `dpm_scraper/raw_archive/`.
Raw HTML is cached to `raw_archive/darko_home_<date>.html` before parsing.

USAGE
-----
    .venv/bin/python dpm_scraper/fetch_darko.py [--dry-run] [--out PATH] [--date YYYY-MM-DD]
"""
import argparse
import io
import json
import os
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

for _k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
           "all_proxy", "ALL_PROXY"):
    os.environ.pop(_k, None)

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "darko_players.json"
ARCHIVE_DIR = HERE / "raw_archive"
URL = "https://www.darko.app/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")

# Guard against silently writing a truncated/garbage payload.
MIN_EXPECTED = 400
MAX_EXPECTED = 1200


class DarkoFetchError(RuntimeError):
    pass


def fetch_homepage(timeout=45, retries=3):
    """GET the darko.app homepage. Proxy env is stripped at import time."""
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                URL,
                headers={
                    "User-Agent": UA,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            text = raw.decode("utf-8", errors="replace")
            if "players:[" not in text:
                raise DarkoFetchError("homepage fetched but 'players:[' not present")
            return text
        except Exception as exc:  # noqa: BLE001 - non-blocking retry
            last = exc
            if attempt < retries:
                print(f"[fetch] attempt {attempt} failed ({exc}); retrying...")
    raise DarkoFetchError(f"failed to fetch {URL} after {retries} attempts: {last}")


def extract_players_array(html):
    """Return the raw `players:[...]` substring using bracket-depth matching.

    Bracket matching (rather than a naive regex) is required because player
    names / team names can contain brackets and commas inside strings.
    """
    marker = "players:["
    idx = html.find(marker)
    if idx < 0:
        raise DarkoFetchError("marker 'players:[' not found in homepage HTML")
    start = idx + len(marker) - 1  # index of the opening '['

    depth = 0
    in_str = False
    esc = False
    i = start
    n = len(html)
    while i < n:
        ch = html[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return html[start:i + 1]
        i += 1
    raise DarkoFetchError("unterminated 'players:[' array (no matching bracket)")


def js_literal_to_json(s):
    """Normalize a JS object/array literal into strict JSON.

    Three fixes, all applied ONLY outside string literals:
      1. quote unquoted object keys  ->  {nba_id:1}       becomes {"nba_id":1}
      2. repair leading-dot numbers  ->  x_fg_pct:.534    becomes "x_fg_pct":0.534
      3. JS-only literals            ->  undefined / NaN  become null

    NOTE ON ORDERING (this was a real bug): fixes 1 and 2 must be matched in a
    SINGLE regex. If the key regex consumes the trailing ':' and advances past
    it, a separate "if ch == ':'" branch can never see that colon again, so
    `x_fg_pct:.534094` stays broken. Hence `key_num_re` below captures the
    optional leading-dot number together with the key.
    """
    out = []
    i = 0
    n = len(s)
    in_str = False
    esc = False

    # key + (optional) leading-dot numeric value, matched as one unit
    key_num_re = re.compile(
        r'([{,])(\s*)([A-Za-z_$][A-Za-z0-9_$]*)(\s*):(\s*)(\.\d+)?'
    )
    # standalone leading-dot number after an already-quoted key, or as an array
    # element / after an arithmetic sign
    num_re = re.compile(r'\.\d+')
    # positions at which a number may legally start
    NUM_START = set("[,:+-*/%(=<>!&|?")
    lit_re = re.compile(r'(undefined|NaN|Infinity|-Infinity)(?![A-Za-z0-9_$])')

    def last_real_char(buf):
        """Last emitted char ignoring trailing whitespace (for lookback)."""
        k = len(buf) - 1
        while k >= 0 and buf[k] in " \t\r\n":
            k -= 1
        return buf[k] if k >= 0 else ""

    while i < n:
        ch = s[i]
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            i += 1
            continue

        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue

        if ch in "{,":
            m = key_num_re.match(s, i)
            if m:
                out.append(m.group(1))          # '{' or ','
                out.append(m.group(2))          # ws before key
                out.append('"')
                out.append(m.group(3))          # key
                out.append('"')
                out.append(m.group(4))          # ws before ':'
                out.append(":")
                out.append(m.group(5))          # ws after ':'
                if m.group(6):                  # leading-dot number
                    out.append("0")
                    out.append(m.group(6))
                i = m.end()
                continue

        if ch == ".":
            m = num_re.match(s, i)
            if m and last_real_char(out) in NUM_START:
                # e.g. "x":.534  |  [.5,.3]  |  -.534
                out.append("0")
                out.append(m.group(0))
                i = m.end()
                continue

        if ch in "uN":
            m = lit_re.match(s, i)
            if m:
                out.append("null")
                i = m.end()
                continue

        out.append(ch)
        i += 1

    return "".join(out)


def parse_players(html):
    raw_array = extract_players_array(html)
    normalized = js_literal_to_json(raw_array)
    try:
        players = json.loads(normalized)
    except json.JSONDecodeError as exc:
        snippet = normalized[max(0, exc.pos - 120): exc.pos + 120]
        raise DarkoFetchError(
            f"could not parse players array as JSON: {exc}\nnear: ...{snippet}..."
        ) from exc

    if not isinstance(players, list):
        raise DarkoFetchError(f"expected a list of players, got {type(players).__name__}")
    if not (MIN_EXPECTED <= len(players) <= MAX_EXPECTED):
        raise DarkoFetchError(
            f"parsed {len(players)} players, outside sane range "
            f"[{MIN_EXPECTED}, {MAX_EXPECTED}] -- refusing to write partial data"
        )
    return players


def main():
    ap = argparse.ArgumentParser(description="Fetch DARKO DPM from darko.app homepage")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="output JSON path")
    ap.add_argument("--date", default=None, help="snapshot date YYYY-MM-DD (default today)")
    ap.add_argument("--dry-run", action="store_true", help="fetch+parse but write nothing")
    ap.add_argument("--html", default=None, help="parse a cached HTML file instead of fetching")
    args = ap.parse_args()

    snap = args.date or date.today().isoformat()

    if args.html:
        print(f"[fetch] using cached HTML: {args.html}")
        html = Path(args.html).read_text(encoding="utf-8", errors="replace")
    else:
        print(f"[fetch] GET {URL}")
        html = fetch_homepage()

    # Cache raw HTML before parsing (standing preference: cache everything).
    # Done even in --dry-run so a parse failure can be re-debugged offline.
    if not args.html:
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        (ARCHIVE_DIR / f"darko_home_{snap}.html").write_text(html, encoding="utf-8")
        print(f"[cache] raw HTML -> {ARCHIVE_DIR / f'darko_home_{snap}.html'}")

    players = parse_players(html)
    print(f"[parse] players parsed: {len(players)}")

    top = sorted(players, key=lambda p: (p.get("dpm") is not None, p.get("dpm") or 0),
                 reverse=True)[:5]
    print("[parse] top 5 by dpm:")
    for p in top:
        print(f"          {p.get('player_name')}: dpm={p.get('dpm')}")

    if args.dry_run:
        print("[dry-run] no files written")
        return 0

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with io.open(out_path, "w", encoding="utf-8") as fh:
        json.dump(players, fh, ensure_ascii=False)
    print(f"[write] {out_path} ({out_path.stat().st_size} bytes, {len(players)} players)")

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    arc = ARCHIVE_DIR / f"darko_players_{snap}.json"
    with io.open(arc, "w", encoding="utf-8") as fh:
        json.dump(players, fh, ensure_ascii=False)
    print(f"[write] archive -> {arc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
