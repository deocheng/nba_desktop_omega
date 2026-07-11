"""Pure parsing helpers for Basketball-Reference PBP pages.

No browser / DB imports here so this module is cheap to unit-test and can be
imported by both the ingest script and the local action_verb backfill.

Design decision (2026-07-09, per user feedback):
  BR omits the space between a player name and the following action verb
  (e.g. 'T. Easonenters the game for J. Smith').  We must NOT discard the verb
  when cleaning the name -- the verb IS data (it drives player-characteristic
  analysis).  So we keep three SEPARATE signals:
    * player      -> clean name only            ('T. Eason')
    * action_verb -> the action word            ('enters')
    * subtype     -> finer action detail        ('enters the game' / '2-pt jump shot')
"""
from __future__ import annotations

import re

SEASON = 2026

# --- low-level field parsers -------------------------------------------------
def detect_period(text: str):
    """Map a quarter/OT label row to a period number."""
    t = text.strip()
    m = re.match(r'^\s*(\d)\s*(st|nd|rd|th)?\s*(Q|OT)\b', t, re.I)
    if not m:
        return None
    if m.group(3).upper() == 'OT':
        return 4 + int(m.group(1))  # 1st OT -> 5
    return int(m.group(1))


def parse_clock(t: str):
    if not t:
        return None
    t = t.split('.')[0]
    m = re.match(r'(\d+):(\d+)', t)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    return None


def parse_score(s: str):
    if not s:
        return None, None
    m = re.match(r'(\d+)\s*-\s*(\d+)', s)
    if m:
        return int(m.group(1)), int(m.group(2))  # away, home
    return None, None


# Leading "X. Lastname" (optionally with suffix), tolerant of missing space
# between name and the following action verb (BR often writes "A. Smithmakes").
NAME_RE = re.compile(r"^([A-Z]\.\s*[A-Z][\w]+(?:\s+[A-Z][\w]+)*)", re.UNICODE)
BY_NAME_RE = re.compile(r'\sby\s*([A-Z]\.\s*[A-Z][\w]+(?:\s+[A-Z][\w]+)*)', re.UNICODE | re.IGNORECASE)
# When name runs into the verb with no space ("Easonenters"), trim the tail so
# the *name* column stays clean. The verb itself is preserved separately via
# extract_action_verb().
VERB_TAIL = re.compile(r'^(.+?)(enters|makes|misses|rebound|foul|turnover|substitution|violation)$', re.I)


def _trim_verb(name: str) -> str:
    words = name.split()
    if words:
        m = VERB_TAIL.match(words[-1])
        if m:
            words[-1] = m.group(1)
            return ' '.join(words)
    return name


def extract_player(desc: str):
    """Extract the primary player NAME (clean, verb removed) from a BR PBP desc."""
    if not desc:
        return ''
    base = desc.split('(')[0].strip()  # drop parenthetical (steal/block/foul details)
    if not base:
        return ''
    m = NAME_RE.match(base)
    if m:
        return _trim_verb(m.group(1).strip())
    m2 = BY_NAME_RE.search(base)
    if m2:
        return _trim_verb(m2.group(1).strip())
    return ''


# --- action verb + subtype (the data the user wants preserved ---------------
# Ordered specific-first so 'makes free throw' wins over 'makes', and the
# primary event verb (makes/misses/turnover/foul) wins over secondary tags
# that appear inside parentheses (block/steal/assist).
_VERB_PATTERNS = [
    ('makes free throw', 'makes'),
    ('misses free throw', 'misses'),
    ('makes', 'makes'),
    ('misses', 'misses'),
    ('rebound', 'rebound'),
    ('turnover', 'turnover'),
    ('violation', 'violation'),
    ('foul', 'foul'),
    ('enters', 'enters'),
    ('substitution', 'enters'),
    ('steal', 'steal'),
    ('block', 'block'),
    ('assist', 'assist'),
    ('timeout', 'timeout'),
    ('jump ball', 'jump ball'),
    ('instant replay', 'instant replay'),
    ('ejected', 'ejected'),
    ('end of', 'period'),
]


def extract_action_verb(desc: str):
    """Return the action VERB (makes/misses/rebound/enters/foul/...) or None.

    Searched across the whole description (glued or spaced) so it survives the
    missing-space BR quirk.  This is the signal the user wants kept as data.
    """
    if not desc:
        return None
    d = desc.lower()
    for token, verb in _VERB_PATTERNS:
        if token in d:
            return verb
    return None


_SHOT_RE = re.compile(r'(2-pt|3-pt)\s+(jump shot|layup|hook shot|tip shot|tip-in|dunk|putback|bank shot)', re.I)
_FT_RE = re.compile(r'free throw\s+\d+\s+of\s+\d+', re.I)
_FOUL_RE = re.compile(
    r'(shooting|personal|technical|def 3 sec tech|offensive|loose ball|inbound|'
    r'clear path|flagrant|away from play|double|pushing|holding|illegal screen|'
    r'hand check|non-unsportsmanlike|hoisting|tank|through the basket)\s+foul', re.I)
_VIOL_RE = re.compile(r'([a-z0-9 \-]+?violation)', re.I)


def extract_subtype(desc: str, verb: str):
    """Return finer action detail for the row (mirrors nba_api `subtype`).

    e.g. '2-pt jump shot', '3-pt jump shot', 'Offensive rebound',
    'bad pass', 'Shooting', 'enters the game', 'free throw 1 of 2'.
    """
    if not desc or not verb:
        return None
    if verb in ('makes', 'misses'):
        m = _SHOT_RE.search(desc)
        if m:
            return m.group(0).lower()
        m = _FT_RE.search(desc)
        if m:
            return m.group(0)
        return 'shot'
    if verb == 'rebound':
        dl = desc.lower()
        if 'offensive' in dl:
            return 'Offensive rebound'
        if 'defensive' in dl:
            return 'Defensive rebound'
        return 'rebound'
    if verb == 'turnover':
        m = re.search(r'\(([^;]+)', desc)  # reason inside first paren
        if m:
            return m.group(1).split(';')[0].strip().rstrip(')').title()
        return 'Turnover'
    if verb == 'foul':
        m = _FOUL_RE.search(desc)
        if m:
            return m.group(1).title()
        return 'Foul'
    if verb == 'enters':
        return 'enters the game'
    if verb == 'ejected':
        return 'ejected from game'
    if verb == 'violation':
        m = _VIOL_RE.search(desc)
        if m:
            return m.group(1).strip().title()
        return 'Violation'
    if verb == 'free throw':
        m = _FT_RE.search(desc)
        if m:
            return m.group(0)
    return verb.title() if verb else None


# --- event classification ----------------------------------------------------
def classify(desc: str):
    """Return (event_type, player) derived from a BR PBP description."""
    d = (desc or '').lower()
    player = extract_player(desc)
    if 'makes free throw' in d or ('free throw' in d and 'makes' in d):
        return 'Free Throw', player
    if 'misses free throw' in d:
        return 'Free Throw', player
    if 'makes' in d and any(k in d for k in ('shot', 'layup', 'dunk', 'tip', 'hook', 'jump', '3-pt', '2-pt')):
        return 'Made Shot', player
    if 'misses' in d and any(k in d for k in ('shot', 'layup', 'dunk', 'tip', 'hook', 'jump', '3-pt', '2-pt')):
        return 'Missed Shot', player
    if 'rebound' in d:
        return 'Rebound', player
    if 'turnover' in d:
        return 'Turnover', player
    if 'foul' in d:
        return 'Foul', player
    if 'violation' in d:
        return 'Violation', player
    if 'enters the game' in d or 'sub:' in d or 'substitution' in d or d.startswith('sub '):
        return 'Substitution', player
    if 'jump ball' in d:
        return 'Jump Ball', player
    if 'instant replay' in d:
        return 'Replay', player
    if 'timeout' in d:
        return 'Timeout', player
    if 'ejected' in d:
        return 'Ejection', player
    if 'end of' in d:
        return 'period', player
    return '', player


def parse_pbp(soup, away_abbr, home_abbr, br_game_id):
    """Parse a BR PBP page soup into play_by_play row dicts."""
    tbl = soup.find('table', id='pbp')
    if tbl is None:
        tbl = soup.find('table', id=lambda x: x and 'pbp' in x.lower())
    if tbl is None:
        return []
    period = 1
    out = []
    eventnum = 0
    tbody = tbl.find('tbody') or tbl
    for tr in tbody.find_all('tr'):
        cells = [td.get_text(strip=True) for td in tr.find_all(['th', 'td'])]
        joined = ' '.join(cells).strip()
        # period marker row
        if tr.get('class') and 'thead' in tr.get('class'):
            p = detect_period(joined)
            if p:
                period = p
            continue
        if not joined:
            continue
        if len(cells) < 4:
            continue
        time_str = cells[0]
        if not re.match(r'\d{1,2}:\d{2}', time_str):
            continue  # not an event row (e.g. stray label)
        away_desc = cells[1] if len(cells) > 1 else ''
        score = cells[3] if len(cells) > 3 else ''
        home_desc = cells[5] if len(cells) > 5 else (cells[-1] if len(cells) > 4 else '')
        desc = away_desc or home_desc
        if not desc and not score:
            continue
        team = away_abbr if away_desc else (home_abbr if home_desc else None)
        etype, player = classify(desc)
        verb = extract_action_verb(desc)
        subtype = extract_subtype(desc, verb)
        cs = parse_clock(time_str)
        a_pts, h_pts = parse_score(score)
        eventnum += 1
        out.append({
            'gameid': br_game_id,
            'season': SEASON,
            'eventnum': eventnum,
            'period': period,
            'clock': time_str.split('.')[0],
            'clock_seconds': cs,
            'h_pts': h_pts,
            'a_pts': a_pts,
            'team': team,
            'playerid': None,
            'player': player or None,
            'event_type': etype or None,
            'subtype': subtype,
            'action_verb': verb,
            'result': None,
            'x': None, 'y': None, 'dist': None,
            'description': desc,
            'current_team': team,
            'homedescription': home_desc or None,
            'visitordescription': away_desc or None,
            'neutraldescription': None,
            'scorehome': str(h_pts) if h_pts is not None else None,
            'scorevisitor': str(a_pts) if a_pts is not None else None,
            'scoremargin': (str(h_pts - a_pts) if (h_pts is not None and a_pts is not None) else None),
            'source': 'BBRef',
        })
    return out
