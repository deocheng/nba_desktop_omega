#!/usr/bin/env python3
"""Mock-data smoke test for team_shot_radial.py layout validation."""
from pathlib import Path

import team_shot_radial as tsr


def mock_fetch_team_data(season: int, team: str, top_n: int = 5):
    """Return synthetic data that resembles the reference image."""
    players = [
        ("Player 1", [600, 250, 50, 600]),   # total 1500
        ("Player 2", [300, 200, 200, 500]),  # total 1200
        ("Player 3", [150, 100, 150, 500]),  # total 900
        ("Player 4", [300, 150, 50, 200]),   # total 700
        ("Player 5", [100, 80, 120, 200]),   # total 500
    ]
    sectors = []
    for name, attempts in players:
        segments = []
        for bucket, att in zip([b[0] for b in tsr.DIST_BUCKETS], attempts):
            segments.append(tsr.Segment(bucket, att, int(att * 0.45), int(att * 0.08), int(att * 0.08 * 0.35)))
        sectors.append(tsr.PlayerSector(name, sum(attempts), segments))

    zone_totals = {b[0]: sum(p[1][i] for p in players) for i, b in enumerate(tsr.DIST_BUCKETS)}
    team_total = sum(sum(p[1]) for p in players)
    return sectors, zone_totals, team_total


if __name__ == "__main__":
    # Patch the data fetcher so we don't need a running DB.
    tsr.fetch_team_data = mock_fetch_team_data

    html = tsr.render(2025, "BOS", top_n=5)
    out_path = Path(__file__).parent / "team_shot_radial.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path}")
