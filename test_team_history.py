from fastapi.testclient import TestClient
from backend.app import create_app

app = create_app()
client = TestClient(app)

print("=== Testing Team History API ===")
response = client.get("/teams/LAL/history")
print(f"Status: {response.status_code}")
if response.status_code == 200:
    data = response.json()
    print(f"Team: {data['team_abbr']}, Seasons: {data['count']}")
    print(f"First 5 seasons:")
    for h in data['data'][:5]:
        print(f"  {h['season']}: {h.get('w', 0)}-{h.get('l', 0)} ({(h.get('win_pct', 0)*100):.1f}%), "
              f"PTS={h.get('pts_per_game', 0):.1f}, AST={h.get('ast_per_game', 0):.1f}, "
              f"REB={h.get('trb_per_game', 0):.1f}, Playoffs={h.get('made_playoffs')}")

print("\n=== Testing Team Legends API ===")
response = client.get("/teams/LAL/legends")
print(f"Status: {response.status_code}")
if response.status_code == 200:
    data = response.json()
    print(f"Team: {data['team_abbr']}, Legends: {data['count']}")
    print(f"Top 10 legends:")
    for i, p in enumerate(data['data'][:10], 1):
        print(f"  {i}. {p['player_name']} ({p['position']}), {p['seasons_played']} seasons, "
              f"PPG={p.get('ppg', 0)}, RPG={p.get('rpg', 0)}, APG={p.get('apg', 0)}, "
              f"All-Star={p.get('all_star_count', 0)}")
