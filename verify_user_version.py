#!/usr/bin/env python3
"""Team shot distribution radial chart — fixed-angle sectors with centered symmetry.

Reference behavior (multilayer weighted polar chart):
- Polar zero at 12 o'clock, data runs clockwise.
- Each player occupies a FIXED angular sector (default 45 deg), separated by a
  small gap. The remaining angle becomes a large label gap at 12 o'clock.
- Distance zone labels are aligned vertically on the LEFT side of the 12 o'clock
  axis, with no boxes.
- Within a player sector, every distance ring has an EQUAL radial thickness, but
  its drawn angular span is proportional to that player's normalized weight for
  that bucket (centered on the sector mid-axis, mirrored left/right).
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

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

DIST_BUCKETS = [
    ("0-8 ft (Rim-Paint)", 0, 8),
    ("8-16ft (Mid)", 8, 16),
    ("16-24ft (Long Mid)", 16, 24),
    ("24+ft (3PT)", 24, 999),
]

# Blue gradient stops: low weight -> high weight
BASE_COLOR_STOPS = [(0.0, "#f8fafc"), (0.18, "#bfdbfe"), (0.45, "#60a5fa"), (0.72, "#2563eb"), (1.0, "#1e3a8a")]
CLUTCH_COLOR = "#0f172a"
GAP_COLOR = "#0f0f1a"
BG_COLOR = "#080e1a"

# Fixed angular layout parameters (in degrees)
PLAYER_SECTOR_DEG = 45.0      # each player sector angle
INTER_PLAYER_GAP_DEG = 5.0    # gap between player sectors


@dataclass
class Segment:
    bucket: str
    attempts: int
    makes: int
    clutch_attempts: int
    clutch_makes: int

    @property
    def fg_pct(self) -> float:
        return self.makes / self.attempts if self.attempts else 0.0


@dataclass
class PlayerSector:
    name: str
    total: int
    segments: List[Segment]


def polar_to_cartesian(cx: float, cy: float, r: float, angle: float) -> Tuple[float, float]:
    return cx + r * math.cos(angle), cy + r * math.sin(angle)


def ref_to_svg(theta: float) -> float:
    """Map reference polar angle (0 at 12 o'clock, clockwise positive) to SVG angle."""
    return theta - math.pi / 2


def normalize_angle(alpha: float) -> float:
    return alpha % (2 * math.pi)


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
        f"L {x4:.2f} {x4:.2f} "
        f"A {r1:.2f} {r1:.2f} 0 {large_arc} 0 {x1:.2f} {y1:.2f} Z"
    )


def interpolate_color(stops: List[Tuple[float, str]], t: float) -> str:
    """Linearly interpolate between color stops [ (pos, #hex), ... ]."""
    t = max(0.0, min(1.0, t))

    def hex_to_rgb(h: str) -> Tuple[int, int, int]:
        h = h.lstrip("#")
        return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))

    for i in range(len(stops) - 1):
        p0, c0 = stops[i]
        p1, c1 = stops[i + 1]
        if p0 <= t <= p1:
            if p1 == p0:
                return c0
            local = (t - p0) / (p1 - p0)
            r0, g0, b0 = hex_to_rgb(c0)
            r1, g1, b1 = hex_to_rgb(c1)
            r = int(r0 + (r1 - r0) * local)
            g = int(g0 + (g1 - g0) * local)
            b = int(b0 + (b1 - b0) * local)
            return f"#{r:02x}{g:02x}{b:02x}"
    return stops[-1][1]


def fetch_team_data(season: int, team: str, top_n: int = 5) -> Tuple[List[PlayerSector], Dict[str, int], int]:
    """与数据库交互，修复了聚合计算漏洞，并使用了上下文管理器保护连接"""
    query = """
        SELECT player_slug,
               CASE
                   WHEN shot_distance < 8 THEN '0-8 ft (Rim-Paint)'
                   WHEN shot_distance < 16 THEN '8-16ft (Mid)'
                   WHEN shot_distance < 24 THEN '16-24ft (Long Mid)'
                   ELSE '24+ft (3PT)'
               END AS bucket,
               COUNT(*) AS attempts,
               SUM(CASE WHEN is_make THEN 1 ELSE 0 END) AS makes,
               SUM(CASE WHEN is_clutch THEN 1 ELSE 0 END) AS clutch_attempts,
               SUM(CASE WHEN is_clutch AND is_make THEN 1 ELSE 0 END) AS clutch_makes
        FROM fct_pbp_shots
        WHERE season = %s AND team = %s
        GROUP BY player_slug, bucket
    """
    
    with psycopg2.connect(**DB_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (season, team))
            rows = cur.fetchall()

    raw: Dict[str, Dict[str, Dict[str, int]]] = {}
    zone_totals: Dict[str, int] = {name: 0 for name, _, _ in DIST_BUCKETS}

    for player, bucket, att, mk, c_att, c_mk in rows:
        raw.setdefault(player, {})[bucket] = {
            "attempts": att,
            "makes": mk,
            "clutch_attempts": c_att,
            "clutch_makes": c_mk,
        }
        zone_totals[bucket] += att

    # 计算玩家出手总数并排序
    player_totals = {
        player: sum(data["attempts"] for data in buckets.values())
        for player, buckets in raw.items()
    }

    sorted_players = sorted(player_totals.items(), key=lambda x: x[1], reverse=True)
    top_players = sorted_players[:top_n]
    others_total = sum(t for _, t in sorted_players[top_n:])
    team_total = sum(t for _, t in sorted_players)

    sectors: List[PlayerSector] = []
    for player, total in top_players:
        segments = []
        for name, _, _ in DIST_BUCKETS:
            seg_data = raw[player].get(name, {"attempts": 0, "makes": 0, "clutch_attempts": 0, "clutch_makes": 0})
            segments.append(Segment(
                bucket=name,
                attempts=seg_data["attempts"],
                makes=seg_data["makes"],
                clutch_attempts=seg_data["clutch_attempts"],
                clutch_makes=seg_data["clutch_makes"]
            ))
        sectors.append(PlayerSector(player, total, segments))

    if others_total > 0:
        sectors.append(PlayerSector("Bench / Others", others_total, [Segment(name, 0, 0, 0, 0) for name, _, _ in DIST_BUCKETS]))

    return sectors, zone_totals, team_total


def render(season: int, team: str, top_n: int = 5) -> str:
    sectors, zone_totals, team_total = fetch_team_data(season, team, top_n)

    width, height = 1300, 1200
    cx, cy = width / 2, height / 2 + 20
    inner_radius, outer_radius = 150, 480

    player_radial_span = outer_radius - inner_radius
    ring_thickness = player_radial_span / len(DIST_BUCKETS)

    top_sectors = [s for s in sectors if s.name != "Bench / Others"]
    bench_sector = next((s for s in sectors if s.name == "Bench / Others"), None)

    sector_angle = math.radians(PLAYER_SECTOR_DEG)
    inter_gap = math.radians(INTER_PLAYER_GAP_DEG)
    num_players = len(top_sectors)
    data_span = num_players * sector_angle + max(0, num_players - 1) * inter_gap
    gap_width = 2 * math.pi - data_span

    theta_ranges: List[Tuple[float, float, PlayerSector]] = []
    cur_theta = 0.0
    for sec in top_sectors:
        theta_ranges.append((cur_theta, cur_theta + sector_angle, sec))
        cur_theta += sector_angle + inter_gap

    parts: List[str] = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'style="background:{BG_COLOR};font-family:system-ui,-apple-system,sans-serif;">',
        '<defs>',
        f'<radialGradient id="bgGrad" cx="{cx}" cy="{cy}" r="{outer_radius}" gradientUnits="userSpaceOnUse">',
        '<stop offset="0%" stop-color="#0f172a"/><stop offset="70%" stop-color="#080e1a"/><stop offset="100%" stop-color="#020617"/>',
        '</radialGradient>',
        '</defs>'
    ]

    # Title & Header Info
    bench_total = bench_sector.total if bench_sector else 0
    bench_pct = (bench_total / team_total * 100) if team_total else 0
    parts.append(f'<text x="{cx}" y="55" text-anchor="middle" fill="#f1f5f9" font-size="22" font-weight="600">{team} Team Shot Distribution — {season}</text>')
    subtitle = f"Fixed {int(PLAYER_SECTOR_DEG)}° sectors  •  {int(math.degrees(gap_width))}° label gap"
    if bench_total:
        subtitle += f"  •  Bench/Others: {bench_total} ({bench_pct:.1f}%)"
    parts.append(f'<text x="{cx}" y="82" text-anchor="middle" fill="#94a3b8" font-size="13">{subtitle}</text>')

    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{outer_radius}" fill="url(#bgGrad)" stroke="#1e293b" stroke-width="2"/>')

    # Draw 12 o'clock gap
    gap_start_svg = normalize_angle(ref_to_svg(2 * math.pi))
    gap_end_svg = normalize_angle(ref_to_svg(2 * math.pi - gap_width))
    gap_path = annular_sector_path(cx, cy, inner_radius, outer_radius, gap_start_svg, gap_end_svg)
    parts.append(f'<path d="{gap_path}" fill="{GAP_COLOR}" stroke="none"/>')

    # Draw player sectors
    label_specs: List[dict] = []
    for theta_start, theta_end, sec in theta_ranges:
        theta_mid = (theta_start + theta_end) / 2
        sector_span = theta_end - theta_start
        max_bucket_attempts = max((seg.attempts for seg in sec.segments), default=1)

        start_svg, end_svg = ref_to_svg(theta_start), ref_to_svg(theta_end)
        mid_svg = ref_to_svg(theta_mid)

        r = inner_radius
        for seg in sec.segments:
            raw_weight = (seg.attempts / max_bucket_attempts) if max_bucket_attempts else 0
            weight = raw_weight ** 0.65
            base_color = interpolate_color(BASE_COLOR_STOPS, weight)

            draw_span = sector_span * weight
            theta_draw_start = theta_mid - draw_span / 2
            theta_draw_end = theta_mid + draw_span / 2

            draw_start_svg = ref_to_svg(theta_draw_start)
            draw_end_svg = ref_to_svg(theta_draw_end)

            # Missing/zero data
            if seg.attempts == 0:
                path = annular_sector_path(cx, cy, r, r + ring_thickness, start_svg, end_svg)
                parts.append(f'<path d="{path}" fill="{GAP_COLOR}" stroke="{BG_COLOR}" stroke-width="1"/>')
                r += ring_thickness
                continue

            # Active data wedge (centered mirror symmetry)
            clutch_ratio = seg.clutch_attempts / seg.attempts
            clutch_thickness = max(ring_thickness * clutch_ratio, 3 if seg.clutch_attempts else 0)
            base_thickness = ring_thickness - clutch_thickness

            if base_thickness > 0:
                path = annular_sector_path(cx, cy, r + clutch_thickness, r + ring_thickness, draw_start_svg, draw_end_svg)
                parts.append(f'<path d="{path}" fill="{base_color}" stroke="#ffffff" stroke-width="0.3" stroke-opacity="0.2"/>')

            if clutch_thickness > 0:
                path = annular_sector_path(cx, cy, r, r + clutch_thickness, draw_start_svg, draw_end_svg)
                parts.append(f'<path d="{path}" fill="{CLUTCH_COLOR}" stroke="#ffffff" stroke-width="0.3" stroke-opacity="0.2"/>')

            # Left & Right gaps
            if weight < 0.999:
                path_left = annular_sector_path(cx, cy, r, r + ring_thickness, start_svg, draw_start_svg)
                parts.append(f'<path d="{path_left}" fill="#ffffff" fill-opacity="0.03" stroke="none"/>')

                path_right = annular_sector_path(cx, cy, r, r + ring_thickness, draw_end_svg, end_svg)
                parts.append(f'<path d="{path_right}" fill="#ffffff" fill-opacity="0.03" stroke="none"/>')

            r += ring_thickness

        lx, ly = polar_to_cartesian(cx, cy, outer_radius + 24, mid_svg)
        label_specs.append({"x": lx, "y": ly, "line1": sec.name, "line2": f"{sec.total} shots"})

    # Player labels
    for spec in label_specs:
        x, y = spec["x"], spec["y"]
        anchor = "end" if x < cx - 20 else ("start" if x > cx + 20 else "middle")
        tx = x - 12 if anchor == "end" else (x + 12 if anchor == "start" else x)

        box_w = max(len(spec["line1"]) * 7.6, len(spec["line2"]) * 6.6) + 18
        box_h = 36
        box_x = tx - box_w + 12 if anchor == "end" else (tx - 12 if anchor == "start" else tx - box_w / 2)

        parts.append(f'<rect x="{box_x:.1f}" y="{y - 15:.1f}" width="{box_w:.1f}" height="{box_h:.1f}" rx="8" fill="#1e293b" stroke="#475569" stroke-width="1" fill-opacity="0.95"/>')
        parts.append(f'<text x="{tx:.1f}" y="{y + 1:.1f}" text-anchor="{anchor}" fill="#f8fafc" font-size="13" font-weight="600">{spec["line1"]}</text>')
        parts.append(f'<text x="{tx:.1f}" y="{y + 17:.1f}" text-anchor="{anchor}" fill="#cbd5e1" font-size="11">{spec["line2"]}</text>')

    # 12 o'clock vertical distance zone labels (Strictly left-aligned, no boxes)
    r_pos = outer_radius
    label_x = cx - 8
    for name, _, _ in reversed(DIST_BUCKETS):
        r_mid = r_pos - ring_thickness / 2
        y = cy - r_mid
        parts.append(f'<text x="{label_x:.1f}" y="{y:.1f}" text-anchor="end" dominant-baseline="middle" fill="#f1f5f9" font-size="12" font-weight="600">{name}</text>')
        r_pos -= ring_thickness

    # Center circle legend
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{inner_radius - 12}" fill="{BG_COLOR}"/>')
    parts.append(f'<text x="{cx}" y="{cy - 18}" text-anchor="middle" fill="#f1f5f9" font-size="15" font-weight="700">TEAM SHOT MAP</text>')
    parts.append(f'<line x1="{cx - 45}" y1="{cy - 6}" x2="{cx + 45}" y2="{cy - 6}" stroke="#475569" stroke-width="1"/>')
    parts.append(f'<text x="{cx}" y="{cy + 12}" text-anchor="middle" fill="#cbd5e1" font-size="11">■ High Weight (Dark)</text>')
    parts.append(f'<text x="{cx}" y="{cy + 27}" text-anchor="middle" fill="#cbd5e1" font-size="11">■ Low Weight (Light)</text>')

    parts.append("</svg>")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{team} Shot Distribution {season}</title>
<style>
body {{ margin: 0; background: {BG_COLOR}; color: #e2e8f0; display: flex; flex-direction: column; align-items: center; min-height: 100vh; font-family: system-ui, sans-serif; }}
.container {{ width: 98vw; max-width: 1300px; padding: 16px; }}
.controls {{ margin-bottom: 16px; display: flex; gap: 12px; align-items: center; justify-content: center; flex-wrap: wrap; }}
.controls label {{ font-size: 14px; color: #94a3b8; }}
.controls input, .controls select {{ background: #0f172a; color: #e2e8f0; border: 1px solid #334155; border-radius: 4px; padding: 6px 10px; }}
.controls button {{ background: #3b82f6; color: #fff; border: none; border-radius: 4px; padding: 7px 16px; cursor: pointer; font-weight: 600; }}
.chart {{ border-radius: 12px; overflow: hidden; box-shadow: 0 10px 40px rgba(0,0,0,0.5); }}
.note {{ margin-top: 16px; color: #64748b; font-size: 13px; text-align: center; max-width: 900px; }}
</style>
</head>
<body>
<div class="container">
  <div class="controls">
    <label>Season: <input type="number" id="season" value="{season}" min="1997" max="2026"></label>
    <label>Team:
      <select id="team">
        {''.join(f'<option value="{t}" {"selected" if team == t else ""}>{t}</option>' for t in ["BOS", "LAL", "GSW", "DEN", "OKC", "BRK", "PHX"])}
      </select>
    </label>
    <button onclick="reload()">Render</button>
  </div>
  <div class="chart">{''.join(parts)}</div>
  <p class="note">
    Each player occupies a fixed {int(PLAYER_SECTOR_DEG)}° sector. Ring angular span is centered on the sector mid-axis.
  </p>
</div>
<script>
function reload() {{
  const s = document.getElementById('season').value;
  const t = document.getElementById('team').value;
  window.location.search = `?season=${{s}}&team=${{t}}`;
}}
</script>
</body>
</html>"""


def main():
    import sys
    season = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
    team = sys.argv[2] if len(sys.argv) > 2 else "BOS"

    html = render(season, team)
    out_path = Path(__file__).with_suffix(".html")
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path} for {team} {season}")


if __name__ == "__main__":
    main()