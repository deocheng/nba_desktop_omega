import requests

r = requests.get('http://127.0.0.1:5577/players/jamesle01/growth')
data = r.json()

print("=== Bio totals ===")
bio = data.get('bio', {})
print(f"Total Games: {bio.get('total_games')}")
print(f"Total Points: {bio.get('total_points')}")
print(f"Total Offensive Rebounds: {bio.get('total_offensive_rebounds')}")
print(f"Total Defensive Rebounds: {bio.get('total_defensive_rebounds')}")
print(f"Total Assists: {bio.get('total_assists')}")
print(f"Total Steals: {bio.get('total_steals')}")
print(f"Total Blocks: {bio.get('total_blocks')}")
print(f"Total Fouls: {bio.get('total_fouls')}")

print("\n=== Scoring Share per season ===")
seasons = data.get('seasons', [])
for s in seasons[:5]:
    print(f"  {s['season']}: team={s['team']}, pts={s['pts']}, team_pts={s.get('team_pts')}, scoring_share={s.get('scoring_share')}")

print(f"\nTotal seasons with scoring_share: {sum(1 for s in seasons if s.get('scoring_share') is not None)} / {len(seasons)}")
