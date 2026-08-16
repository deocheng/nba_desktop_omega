#!/usr/bin/env python3
"""星环图 (Stellar-Ring Chart) — NBA team shot distribution.

New design (2026-08-03 spec):
- GLOBAL DYNAMIC ANGLE RATIO: the 300-degree data arc is split among top-N players
  strictly proportional to each player's total shot volume (no fixed slot).
- CROSS-PLAYER FAITHFULNESS: within each distance ring, a player's wedge arc is
  proportional to their real share of that zone (peer-relative to ring max).
- TEAM THEME COLORS: 30-team primary/secondary palette applied to the UI frame
  only; the 4-color data encoding stays constant for cross-team comparability.
- ADAPTIVE BACKGROUND LAYER (--bg):
    portrait : grayscale local player headshots masked per sector (default)
    logo     : local team logo masked per sector
    heatmap  : FG% heat colors (blue->yellow->red) per zone
    grid     : minimal radial grid in team secondary color
- 5/6/7-player adaptive layout; top 60-degree gap reserved for ring labels.
"""
from __future__ import annotations

import base64
import glob
import math
import os
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import psycopg2
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5433")),
    "dbname": os.getenv("DB_NAME", "nba"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
}

# ---- distance buckets (inner -> outer) -------------------------------------
DIST_BUCKETS = [
    ("0-8 ft (Rim)", 0, 8),
    ("8-16 ft (Mid)", 8, 16),
    ("16-24 ft (Long Mid)", 16, 24),
    ("24+ ft (3PT)", 24, 999),
]

# ---- data-state colors: derived PER-TEAM from primary/secondary (TEAM_THEMES).
# Four shot states keep distinct semantics:
#   made = solid team color, missed = lightened team color;
#   non-clutch = PRIMARY hue, clutch = SECONDARY hue.
# The uniform BLUE/CYAN/ORANGE/YELLOW below remain as the explicit fallback palette.
BLUE = "#2563eb"       # Non-clutch MADE   (uniform fallback)
CYAN = "#06b6d4"       # Non-clutch MISSED (uniform fallback)
ORANGE = "#f97316"     # Clutch MADE       (uniform fallback)
YELLOW = "#eab308"     # Clutch MISSED     (uniform fallback)
EMPTY_FILL = "#ffffff"

def _hex_to_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

def _rgb_to_hex(rgb):
    return "#" + "".join(f"{max(0, min(255, int(round(v)))):02x}" for v in rgb)

def lighten(hex_color: str, f: float) -> str:
    """Blend a hex color toward white by fraction f (0 = unchanged, 1 = white)."""
    r, g, b = _hex_to_rgb(hex_color)
    return _rgb_to_hex((r + (255 - r) * f, g + (255 - g) * f, b + (255 - b) * f))

BG_COLOR = "#ffffff"
CHART_NAME = "星环图"

HEADSHOT_DIR = "/Volumes/12T/NBA/headshots"
LOGO_DIR = "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/NBAlogo"

PORTRAIT_OPACITY = 0.55
LOGO_OPACITY = 0.60

# ---- team theme palette (primary / secondary) -----------------------------
TEAM_THEMES = {
    "ATL": {"primary": "#C8102E", "secondary": "#FDB927"},
    "BOS": {"primary": "#007A33", "secondary": "#BA9653"},
    "BKN": {"primary": "#000000", "secondary": "#FFFFFF"},
    "BRK": {"primary": "#000000", "secondary": "#FFFFFF"},
    "CHA": {"primary": "#1D1160", "secondary": "#008799"},
    "CHO": {"primary": "#1D1160", "secondary": "#008799"},
    "CHI": {"primary": "#CE1141", "secondary": "#000000"},
    "CLE": {"primary": "#860038", "secondary": "#FDBB30"},
    "DAL": {"primary": "#00538C", "secondary": "#B8C4CA"},
    "DEN": {"primary": "#0E2240", "secondary": "#FEC524"},
    "DET": {"primary": "#C8102E", "secondary": "#1D428A"},
    "GSW": {"primary": "#1D428A", "secondary": "#FFC72C"},
    "HOU": {"primary": "#CE1141", "secondary": "#000000"},
    "IND": {"primary": "#002D62", "secondary": "#FDBB30"},
    "LAC": {"primary": "#C8102E", "secondary": "#1D428A"},
    "LAL": {"primary": "#552583", "secondary": "#FDB927"},
    "MEM": {"primary": "#12173F", "secondary": "#5D76A5"},
    "MIA": {"primary": "#98002E", "secondary": "#F9A01B"},
    "MIL": {"primary": "#00471B", "secondary": "#EEE1C6"},
    "MIN": {"primary": "#0E2240", "secondary": "#78BE20"},
    "NOP": {"primary": "#0C2340", "secondary": "#C8102E"},
    "NYK": {"primary": "#006BB6", "secondary": "#F58426"},
    "OKC": {"primary": "#007AC1", "secondary": "#EF3B24"},
    "ORL": {"primary": "#0077C0", "secondary": "#C4CED4"},
    "PHI": {"primary": "#006BB6", "secondary": "#ED174C"},
    "PHX": {"primary": "#1D1160", "secondary": "#E56020"},
    "POR": {"primary": "#E03A3E", "secondary": "#000000"},
    "SAC": {"primary": "#5A2D81", "secondary": "#63727A"},
    "SAS": {"primary": "#C4CED4", "secondary": "#000000"},
    "TOR": {"primary": "#CE1141", "secondary": "#000000"},
    "UTA": {"primary": "#002B5C", "secondary": "#F9A01B"},
    "WAS": {"primary": "#002B5C", "secondary": "#E31837"},
}
# logo file uses lowercase 3-letter code
LOGO_FILE = {
    "BKN": "bkn", "BRK": "bkn", "CHA": "cha", "CHO": "cha",
}

TEAM_CN = {
    "ATL": "老鹰", "BOS": "凯尔特人", "BRK": "篮网", "CHI": "公牛", "CLE": "骑士",
    "DAL": "独行侠", "DEN": "掘金", "DET": "活塞", "GSW": "勇士", "HOU": "火箭",
    "IND": "步行者", "LAC": "快船", "LAL": "湖人", "MEM": "灰熊", "MIA": "热火",
    "MIL": "雄鹿", "MIN": "森林狼", "NOP": "鹈鹕", "NYK": "尼克斯", "OKC": "雷霆",
    "ORL": "魔术", "PHI": "76人", "PHX": "太阳", "POR": "开拓者", "SAC": "国王",
    "SAS": "马刺", "TOR": "猛龙", "UTA": "爵士", "WAS": "奇才", "CHO": "黄蜂",
}

# Team+slug overrides for ambiguous initial-based slugs.
# player_id_bridge maps "J. Williams" -> willija02 (Jason Williams, retired), but on
# modern OKC the slug "J. Williams" is Jalen Williams (willija06). Resolved per-team so
# historical Jason rows are not corrupted (data correctness / 数据四性).
SLUG_OVERRIDES = {
    ("OKC", "J. Williams"): "willija06",   # Jalen Williams, not Jason (willija02)
    ("CLE", "D. Mitchell"): "mitchdo01",   # Donovan Mitchell, not Dillon (mitchdi01)
}


@dataclass
class Segment:
    bucket: str
    attempts: int
    makes: int
    clutch_attempts: int
    clutch_makes: int


@dataclass
class PlayerSector:
    name: str
    player_slug: str
    br_id: str
    total: int
    segments: List[Segment]


# ---- geometry helpers -----------------------------------------------------
def polar_to_cartesian(cx: float, cy: float, r: float, angle: float) -> Tuple[float, float]:
    return cx + r * math.cos(angle), cy + r * math.sin(angle)


def ref_to_svg(theta: float) -> float:
    return theta - math.pi / 2


def annular_sector_path(cx: float, cy: float, r1: float, r2: float, start: float, end: float) -> str:
    x1, y1 = polar_to_cartesian(cx, cy, r1, start)
    x2, y2 = polar_to_cartesian(cx, cy, r2, start)
    x3, y3 = polar_to_cartesian(cx, cy, r2, end)
    x4, y4 = polar_to_cartesian(cx, cy, r1, end)
    span = (end - start) % (2 * math.pi)
    large_arc = 1 if span > math.pi else 0
    return (
        f"M {x1:.2f} {y1:.2f} "
        f"L {x2:.2f} {y2:.2f} "
        f"A {r2:.2f} {r2:.2f} 0 {large_arc} 1 {x3:.2f} {y3:.2f} "
        f"L {x4:.2f} {y4:.2f} "
        f"A {r1:.2f} {r1:.2f} 0 {large_arc} 0 {x1:.2f} {y1:.2f} Z"
    )


# ---- image helpers ---------------------------------------------------------
def _image_data_uri(path: Optional[str]) -> Optional[str]:
    if not path or not os.path.exists(path):
        return None
    ext = path.rsplit(".", 1)[-1].lower()
    mime = "image/png" if ext == "png" else "image/jpeg"
    with open(path, "rb") as f:
        b = f.read()
    return f"data:{mime};base64," + base64.b64encode(b).decode("ascii")


def ascii_name(name: str) -> str:
    """Strip diacritics so names render reliably in SVG/PNG (e.g. Dončić -> Doncic)."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", name)
        if not unicodedata.combining(c)
    )


def headshot_path(br_id: str) -> Optional[str]:
    if not br_id:
        return None
    hits = glob.glob(os.path.join(HEADSHOT_DIR, br_id + ".*"))
    for h in hits:
        if h.lower().endswith((".jpg", ".jpeg", ".png")):
            return h
    return None


def logo_path(team: str) -> Optional[str]:
    code = LOGO_FILE.get(team, team.lower())
    p = os.path.join(LOGO_DIR, code + ".png")
    return p if os.path.exists(p) else None


# ---- data fetch ------------------------------------------------------------
def fetch_team_data(season: int, team: str, top_n: int = 5):
    query = """
        SELECT p.player_slug,
               COALESCE(b.br_player_id, '') AS br_id,
               CASE
                   WHEN shot_distance < 8 THEN '0-8 ft (Rim)'
                   WHEN shot_distance < 16 THEN '8-16 ft (Mid)'
                   WHEN shot_distance < 24 THEN '16-24 ft (Long Mid)'
                   ELSE '24+ ft (3PT)'
               END AS bucket,
               COUNT(*) AS attempts,
               SUM(CASE WHEN is_make THEN 1 ELSE 0 END) AS makes,
               SUM(CASE WHEN is_clutch THEN 1 ELSE 0 END) AS clutch_attempts,
               SUM(CASE WHEN is_clutch AND is_make THEN 1 ELSE 0 END) AS clutch_makes
        FROM fct_pbp_shots p
        LEFT JOIN player_id_bridge b ON b.player_name = p.player_slug
        WHERE season = %s AND team = %s AND shot_distance IS NOT NULL
        GROUP BY p.player_slug, b.br_player_id, bucket
    """
    with psycopg2.connect(**DB_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (season, team))
            rows = cur.fetchall()

    raw: Dict[str, Dict[str, Dict[str, int]]] = {}
    br_of: Dict[str, str] = {}
    for player, br_id, bucket, att, mk, c_att, c_mk in rows:
        raw.setdefault(player, {})[bucket] = {
            "attempts": att, "makes": mk,
            "clutch_attempts": c_att, "clutch_makes": c_mk,
        }
        br_of[player] = br_id or ""

    player_totals = {
        p: sum(d["attempts"] for d in buckets.values())
        for p, buckets in raw.items()
    }
    sorted_players = sorted(player_totals.items(), key=lambda x: x[1], reverse=True)
    top_players = sorted_players[:top_n]
    team_total = sum(t for _, t in sorted_players)

    zone_totals = {name: 0 for name, _, _ in DIST_BUCKETS}
    for buckets in raw.values():
        for name, _, _ in DIST_BUCKETS:
            zone_totals[name] += buckets.get(name, {}).get("attempts", 0)

    sectors: List[PlayerSector] = []
    for player, total in top_players:
        segments = [
            Segment(
                bucket=name,
                attempts=raw[player].get(name, {}).get("attempts", 0),
                makes=raw[player].get(name, {}).get("makes", 0),
                clutch_attempts=raw[player].get(name, {}).get("clutch_attempts", 0),
                clutch_makes=raw[player].get(name, {}).get("clutch_makes", 0),
            )
            for name, _, _ in DIST_BUCKETS
        ]
        br_resolved = SLUG_OVERRIDES.get((team, player), br_of.get(player, ""))
        sectors.append(PlayerSector(ascii_name(player), player, br_resolved, total, segments))

    return sectors, zone_totals, team_total


# ---- color helpers ---------------------------------------------------------
def _hex_to_rgb(h: str) -> Tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r: Tuple[int, int, int]) -> str:
    return "#%02X%02X%02X" % (int(r[0]), int(r[1]), int(r[2]))


def _lerp(a: str, b: str, t: float) -> str:
    ca, cb = _hex_to_rgb(a), _hex_to_rgb(b)
    return _rgb_to_hex(tuple(ca[i] + (cb[i] - ca[i]) * t for i in range(3)))


def _luminance(hex_color: str) -> float:
    r, g, b = _hex_to_rgb(hex_color)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


def text_color(primary: str, secondary: str) -> str:
    """Return a readable text color; prefer primary, fall back to secondary or dark."""
    if _luminance(primary) < 0.55:
        return primary
    if _luminance(secondary) < 0.55:
        return secondary
    return "#1e293b"


def heat_color(fg: Optional[float]) -> str:
    """FG% -> blue(low) -> yellow(mid) -> red(high)."""
    if fg is None:
        return EMPTY_FILL
    fg = max(0.0, min(1.0, fg))
    if fg < 0.5:
        return _lerp("#2563eb", "#eab308", fg / 0.5)
    return _lerp("#eab308", "#ef4444", (fg - 0.5) / 0.5)


# ---- render ----------------------------------------------------------------
def render(season: int, team: str, top_n: int = 5, bg: str = "portrait") -> str:
    top_n = min(max(top_n, 5), 7)
    sectors, zone_totals, team_total = fetch_team_data(season, team, top_n)

    theme = TEAM_THEMES.get(team, {})
    PRIMARY = theme.get("primary", "#334155")
    SECONDARY = theme.get("secondary", "#94a3b8")
    TXT = text_color(PRIMARY, SECONDARY)

    # per-team data-state colors (derived from the 30-team theme palette)
    C_MADE = PRIMARY                     # non-clutch made   -> team primary (solid)
    C_MISS = lighten(PRIMARY, 0.5)      # non-clutch ...    -> primary lightened
    K_MADE = SECONDARY                  # clutch made       -> team secondary (solid)
    K_MISS = lighten(SECONDARY, 0.5)    # clutch missed     -> secondary lightened

    width, height = 1320, 1320
    cx, cy = width / 2, height / 2 + 20
    inner_radius, outer_radius = 160, 500

    # --- ring thicknesses (bi-proportional by zone volume) ---
    player_radial_span = outer_radius - inner_radius
    MIN_RING_TH = 4.0
    RING_GAP = 10.0
    zone_vals = [zone_totals.get(name, 0) for name, _, _ in DIST_BUCKETS]
    zone_sum = sum(zone_vals) or 1
    n_gaps = len(DIST_BUCKETS) - 1
    floor_total = MIN_RING_TH * len(DIST_BUCKETS)
    remaining = max(player_radial_span - floor_total - n_gaps * RING_GAP, 0.0)
    ring_thicknesses = [MIN_RING_TH + remaining * (z / zone_sum) for z in zone_vals]

    ring_inner: List[float] = []
    ring_outer: List[float] = []
    cur = inner_radius
    for idx, th in enumerate(ring_thicknesses):
        r0 = cur + (RING_GAP if idx > 0 else 0)
        r1 = r0 + th
        ring_inner.append(r0)
        ring_outer.append(r1)
        cur = r1

    # --- GLOBAL FIXED ANGLE ALLOCATION ---
    # Every player's sector is a FIXED 60deg regardless of shot volume. The wedge
    # area encoding INSIDE each sector is unchanged (angular span ∝ actual attempts),
    # so "数据面积" (relative shot-zone mix) is preserved. 5×60 = 300deg; with no
    # inter-player gap the remaining 60deg naturally lands at top (12 o'clock),
    # centered at start+330deg, mirroring the prior layout's upper-left gap.
    FIXED_SECTOR_DEG = 60.0
    INTER_GAP_DEG = 0.0

    start_angle_deg = 0.0  # #1 player's leading edge anchored at 12 o'clock
    gap_center_deg = start_angle_deg + 330.0
    theta_ranges: List[Tuple[float, float, PlayerSector]] = []
    for sec in sectors:
        sec_angle_deg = FIXED_SECTOR_DEG
        t_start = math.radians(start_angle_deg)
        t_end = math.radians(start_angle_deg + sec_angle_deg)
        theta_ranges.append((t_start, t_end, sec))
        start_angle_deg += sec_angle_deg + INTER_GAP_DEG

    parts: List[str] = [
        f'<svg id="stellarChart" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'style="background:{BG_COLOR};font-family:system-ui,-apple-system,sans-serif;">',
    ]
    parts.append('<defs>'
                 '<filter id="gray"><feColorMatrix type="saturate" values="0"/></filter>'
                 '</defs>')

    # Header
    cn = TEAM_CN.get(team, team)
    parts.append(f'<text x="{cx}" y="50" text-anchor="middle" fill="{TXT}" font-size="24" font-weight="800">{cn} · {CHART_NAME} ({top_n}人) — {season}</text>')
    # team-color accent bar under the title (PRIMARY from the 30-team palette)
    parts.append(f'<rect x="{cx-46:.1f}" y="60" width="92" height="4" rx="2" fill="{PRIMARY}"/>')


    label_specs: List[dict] = []
    clip_defs: List[str] = []
    bg_is_photo = bg in ("portrait", "logo")

    for p_idx, (theta_start, theta_end, sec) in enumerate(theta_ranges):
        theta_span = theta_end - theta_start
        theta_mid = (theta_start + theta_end) / 2
        start_svg = ref_to_svg(theta_start)
        end_svg = ref_to_svg(theta_end)
        mid_svg = ref_to_svg(theta_mid)

        clip_id = f"clip-{p_idx}"
        full_path = annular_sector_path(cx, cy, inner_radius, outer_radius, start_svg, end_svg)
        clip_defs.append(f'<clipPath id="{clip_id}"><path d="{full_path}"/></clipPath>')

        parts.append('<g class="sector-group">')

        # background layer (photo / logo / tint)
        if bg_is_photo:
            uri = None
            if bg == "logo":
                uri = _image_data_uri(logo_path(team))
            # background base: portrait uses neutral gray (matches grayscale headshot
            # backdrop + empty ring fill) for a unified monochrome field; logo keeps team tint
            if bg == "portrait":
                parts.append(f'<path d="{full_path}" fill="{BG_COLOR}" opacity="1.0"/>')
            else:
                parts.append(f'<path d="{full_path}" fill="{BG_COLOR}"/>')
            if uri:
                px, py = polar_to_cartesian(cx, cy, (inner_radius + outer_radius) / 2 - 30, mid_svg)
                # headshot height = sector radial radius (band thickness) so the full face
                # fits inside the annular sector after rotation (no overflow / clipping)
                img_size = (outer_radius - inner_radius)
                op = PORTRAIT_OPACITY if bg == "portrait" else LOGO_OPACITY
                filt = ' filter="url(#gray)"' if bg == "portrait" else ""
                # rotate the headshot so the face points radially outward along its sector
                rotate_deg = math.degrees(mid_svg) + 90.0
                parts.append(
                    f'<g clip-path="url(#{clip_id})">'
                    f'<image href="{uri}" x="{px - img_size/2:.1f}" y="{py - img_size/2:.1f}" '
                    f'width="{img_size:.1f}" height="{img_size:.1f}" preserveAspectRatio="xMidYMid meet"'
                    f' transform="rotate({rotate_deg:.1f} {px:.1f} {py:.1f})"'
                    f'{filt} opacity="{op}"/>'
                    f'</g>'
                )
        elif bg == "grid":
            # faint sector tint + concentric separators
            parts.append(f'<path d="{full_path}" fill="{BG_COLOR}"/>')
            for ri in ring_inner:
                parts.append(f'<circle cx="{cx}" cy="{cy}" r="{ri:.1f}" fill="none" stroke="{SECONDARY}" stroke-width="0.8" opacity="0.25"/>')

        # radial divider between players (inter-player gap is now 0, so draw an
        # explicit thin line so adjacent 60deg sectors stay visually distinct)
        div_svg = ref_to_svg(theta_start)
        dx0, dy0 = polar_to_cartesian(cx, cy, inner_radius, div_svg)
        dx1, dy1 = polar_to_cartesian(cx, cy, outer_radius, div_svg)
        parts.append(f'<line x1="{dx0:.1f}" y1="{dy0:.1f}" x2="{dx1:.1f}" y2="{dy1:.1f}" '
                     f'stroke="{SECONDARY}" stroke-width="1.2" opacity="0.45"/>')

        # data wedges — every distance ring anchors to the player's sector LEFT
        # edge (the 12 o'clock side), so the 4 layers read as one coherent radial
        # stack (unified left-edge alignment) instead of an L-R spiral. Wedge
        # angular span still ∝ actual attempts (area encoding kept).
        for i, seg in enumerate(sec.segments):
            r = ring_inner[i]
            r_next = ring_outer[i]
            thickness = r_next - r

            if bg == "heatmap":
                # fill full sector-width ring by FG%
                fg = (seg.makes / seg.attempts) if seg.attempts else None
                col = heat_color(fg)
                if seg.attempts == 0:
                    parts.append(f'<path d="{annular_sector_path(cx, cy, r, r_next, start_svg, end_svg)}" fill="{EMPTY_FILL}" opacity="0.5"/>')
                else:
                    parts.append(f'<path d="{annular_sector_path(cx, cy, r, r_next, start_svg, end_svg)}" fill="{col}"/>')
                    if seg.clutch_attempts > 0 and seg.clutch_makes > 0:
                        # inner bright arc marks clutch makes
                        cw = r + thickness * (seg.clutch_makes / seg.clutch_attempts)
                        parts.append(f'<path d="{annular_sector_path(cx, cy, r, cw, start_svg, end_svg)}" fill="#ffffff" opacity="0.55"/>')
                continue

            if seg.attempts == 0:
                # zero attempts -> occupy no angular space; advance nothing
                continue

            # Faithful area encoding: wedge angular span is proportional to the
            # segment's ACTUAL attempt count (seg.attempts / player_total). Since the
            # player's sector width theta_span is itself ~ player_total, this reduces
            # to draw_span ~ seg.attempts globally -- so within the SAME ring, wedge
            # AREA is directly comparable across players (fixes Joe 343 > SGA 279 inversion).
            raw_weight = seg.attempts / sec.total
            draw_span = theta_span * raw_weight
            # unified LEFT-edge alignment: all 4 distance rings start from the
            # sector's left edge, so the stacked layers share one common radial line.
            seg_start = theta_start
            seg_end = seg_start + draw_span
            draw_start_svg = ref_to_svg(seg_start)
            draw_end_svg = ref_to_svg(seg_end)

            svg_span = draw_end_svg - draw_start_svg
            if seg.clutch_attempts > 0 and seg.attempts > seg.clutch_attempts:
                cl_frac = seg.clutch_attempts / seg.attempts
                cl_start = draw_start_svg
                cl_end = draw_start_svg + svg_span * cl_frac
                nc_start, nc_end = cl_end, draw_end_svg
                has_clutch = True
            else:
                cl_start = cl_end = None
                nc_start, nc_end = draw_start_svg, draw_end_svg
                has_clutch = (seg.clutch_attempts > 0)

            # non-clutch block
            nc_att = seg.attempts - seg.clutch_attempts
            nc_mk = seg.makes - seg.clutch_makes
            if nc_att > 0:
                parts.append(f'<path d="{annular_sector_path(cx, cy, r, r_next, nc_start, nc_end)}" fill="{C_MISS}" opacity="0.5"/>')
                if nc_mk > 0:
                    nc_outer = r + thickness * (nc_mk / nc_att)
                    parts.append(f'<path d="{annular_sector_path(cx, cy, r, nc_outer, nc_start, nc_end)}" fill="{C_MADE}" opacity="0.55"/>')

            # clutch block
            if has_clutch:
                c_start = draw_start_svg if cl_start is None else cl_start
                c_end = draw_end_svg if cl_end is None else cl_end
                parts.append(f'<path d="{annular_sector_path(cx, cy, r, r_next, c_start, c_end)}" fill="{K_MISS}" opacity="0.5"/>')
                if seg.clutch_makes > 0:
                    cl_outer = r + thickness * (seg.clutch_makes / seg.clutch_attempts)
                    parts.append(f'<path d="{annular_sector_path(cx, cy, r, cl_outer, c_start, c_end)}" fill="{K_MADE}" opacity="0.55"/>')

            # number label (solid dark, legible on white base)
            draw_mid_svg = ref_to_svg(seg_start + draw_span / 2)
            mx, my = polar_to_cartesian(cx, cy, r + thickness / 2, draw_mid_svg)
            fs = 12 if thickness >= 26 else 11
            txt = f"{seg.makes}/{seg.attempts}"
            parts.append(f'<text x="{mx:.1f}" y="{my+3:.1f}" text-anchor="middle" fill="#0f172a" font-size="{fs}" font-weight="600">{txt}</text>')

        # external player label
        lx, ly = polar_to_cartesian(cx, cy, outer_radius + 22, mid_svg)
        label_specs.append({"x": lx, "y": ly, "name": sec.name, "total": sec.total,
                            "pct": (sec.total / team_total * 100) if team_total else 0.0})
        parts.append('</g>')

    # decorative band-divider rings in team SECONDARY (framework accent, all modes)
    # separates the 4 distance bands; drawn on top as thin separators (doc §3 grid accent)
    for ri in [inner_radius] + list(ring_outer[:3]):
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{ri:.1f}" fill="none" stroke="{SECONDARY}" stroke-width="0.8" opacity="0.35"/>')

    # inject clip defs
    parts.insert(2, '<defs>' + ''.join(clip_defs) + '</defs>')

    # player external labels
    for spec in label_specs:
        x, y = spec["x"], spec["y"]
        anchor = "end" if x < cx - 20 else ("start" if x > cx + 20 else "middle")
        tx = x - 10 if anchor == "end" else (x + 10 if anchor == "start" else x)
        parts.append(f'<text x="{tx:.1f}" y="{y:.1f}" text-anchor="{anchor}" fill="#0f172a" font-size="13" font-weight="800">{spec["name"]}</text>')
        parts.append(f'<text x="{tx:.1f}" y="{y+16:.1f}" text-anchor="{anchor}" fill="#64748b" font-size="11">{spec["total"]} 次 ({spec["pct"]:.1f}%)</text>')

    # top distance ring titles (pinned to 12 o'clock line, corresponding ring)
    gap_mid_svg = ref_to_svg(0.0)
    for k, (name, _, _) in enumerate(reversed(DIST_BUCKETS)):
        rr = ring_inner[3 - k] + (ring_outer[3 - k] - ring_inner[3 - k]) / 2
        lx, ly = polar_to_cartesian(cx, cy, rr, gap_mid_svg)
        parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="end" dominant-baseline="middle" fill="{TXT}" font-size="11" font-weight="700">{name}</text>')

    # center panel
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{inner_radius - 5:.1f}" fill="{BG_COLOR}" stroke="{TXT}" stroke-width="2"/>')
    # team-color medallion ring framing the center panel (SECONDARY from the 30-team palette)
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{inner_radius - 1:.1f}" fill="none" stroke="{SECONDARY}" stroke-width="1.5" opacity="0.85"/>')
    # team logo overlaid on top of the panel
    logo_uri = _image_data_uri(logo_path(team))
    if logo_uri:
        sz = 88.0
        parts.append(f'<image href="{logo_uri}" x="{cx - sz/2:.1f}" y="{cy - 144:.1f}" '
                     f'width="{sz:.1f}" height="{sz:.1f}" preserveAspectRatio="xMidYMid meet"/>')
    # panel text shifted down below the logo
    parts.append(f'<text x="{cx}" y="{cy - 28:.1f}" text-anchor="middle" fill="{TXT}" font-size="14" font-weight="800">星环战力榜 (Top {top_n})</text>')
    parts.append(f'<text x="{cx}" y="{cy - 8:.1f}" text-anchor="middle" fill="#64748b" font-size="10">球队总出手: {team_total} 次</text>')
    ry = cy + 14
    rlh = 15
    for i, sec in enumerate(sectors):
        tot_mk = sum(s.makes for s in sec.segments)
        tot_c_att = sum(s.clutch_attempts for s in sec.segments)
        tot_c_mk = sum(s.clutch_makes for s in sec.segments)
        fg = (tot_mk / sec.total * 100) if sec.total else 0.0
        parts.append(f'<text x="{cx:.1f}" y="{ry + i * rlh:.1f}" text-anchor="middle" fill="#334155" font-size="10.5" font-weight="600">{i+1}. {sec.name}: {sec.total}次 {fg:.0f}% · 关键{tot_c_mk}/{tot_c_att}</text>')

    # legend (swatch left, text right)
    legend = [
        (C_MISS, "非关键未中"), (C_MADE, "非关键命中"),
        (K_MISS, "关键未中"), (K_MADE, "关键命中"),
    ]
    legend_y = cy + outer_radius + 64
    total_w = sum(22 + len(t) * 12 + 20 for _, t in legend)
    x = cx - total_w / 2
    for color, text in legend:
        parts.append(f'<rect x="{x:.1f}" y="{legend_y - 11:.1f}" width="12" height="12" rx="3" fill="{color}"/>')
        parts.append(f'<text x="{x + 18:.1f}" y="{legend_y:.1f}" fill="#475569" font-size="12">{text}</text>')
        x += 22 + len(text) * 12 + 20

    parts.append("</svg>")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{team} {CHART_NAME} {season}</title>
<style>
body {{ margin: 0; background: #ffffff; display: flex; justify-content: center; min-height: 100vh; font-family: system-ui, sans-serif; }}
.chart {{ width: 98vw; max-width: 1340px; padding: 16px; }}
</style>
</head>
<body>
<div class="chart">{''.join(parts)}</div>
</body>
</html>"""


def main():
    season = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    team = sys.argv[2].upper() if len(sys.argv) > 2 else "OKC"
    top_n = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    bg = "portrait"  # standalone template: portrait (grayscale headshot) mode
    out_path = sys.argv[4] if len(sys.argv) > 4 else str(Path(__file__).with_suffix(".html"))

    html = render(season, team, top_n, bg)
    Path(out_path).write_text(html, encoding="utf-8")
    print(f"Wrote {out_path} for {team} {season} (top {top_n}, bg={bg})")


if __name__ == "__main__":
    main()
