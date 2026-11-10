import os, json
from dotenv import load_dotenv
import psycopg2

ENV_PATH = "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/.env"
load_dotenv(ENV_PATH)
pw = os.getenv("DB_PASSWORD")
conn = psycopg2.connect(host="localhost", port=5433, dbname="nba",
                        user="postgres", password=pw)
cur = conn.cursor()

def classify(pos):
    if pos is None or pos.strip() == '':
        return None
    # split into individual position tokens
    for sep in [' and ', '/', ',']:
        pos = pos.replace(sep, '|')
    toks = [t.strip() for t in pos.split('|') if t.strip()]
    primary = toks[0]
    gmap = {
        'Point Guard': 'Guard', 'Shooting Guard': 'Guard', 'Guard': 'Guard',
        'Small Forward': 'Wing', 'Forward': 'Wing',
        'Power Forward': 'Big', 'Center': 'Big',
    }
    return gmap.get(primary, None)

# season range
cur.execute("SELECT MIN(season), MAX(season) FROM player_per_game WHERE player_id IS NOT NULL AND player_id<>''")
print("season range:", cur.fetchone())

# Primary scorer per (team, season): max total pts = pts_per_game*g, g>=41, valid id, team not TOT
cur.execute("""
    WITH base AS (
        SELECT player_id, season, team, g, pts_per_game,
               (pts_per_game * g) AS total_pts
        FROM player_per_game
        WHERE player_id IS NOT NULL AND player_id <> ''
          AND g >= 41
          AND team IS NOT NULL AND team <> '' AND team <> 'TOT'
    ),
    ranked AS (
        SELECT b.*, dp.position,
               ROW_NUMBER() OVER (
                   PARTITION BY b.team, b.season
                   ORDER BY b.total_pts DESC, b.pts_per_game DESC
               ) AS rn
        FROM base b
        LEFT JOIN dim_players dp ON dp.player_id = b.player_id
    )
    SELECT team, season, player_id, total_pts, pts_per_game, g, position
    FROM ranked
    WHERE rn = 1
    ORDER BY season, team
""")
rows = cur.fetchall()
print("total primary-scorer team-seasons:", len(rows))

# classify & aggregate by era
def era_of(s):
    if 1980 <= s <= 1989: return '80s'
    if 1990 <= s <= 1999: return '90s'
    if 2000 <= s <= 2009: return '00s'
    if 2010 <= s <= 2019: return '10s'
    if 2020 <= s <= 2026: return '20s'
    return None

eras = ['80s','90s','00s','10s','20s']
agg = {e: {'n':0,'Guard':0,'Wing':0,'Big':0,'None':0} for e in eras}
classify_counts = {}
unclassified = []
for team, season, pid, total, ppg, g, pos in rows:
    e = era_of(season)
    if e is None: continue
    grp = classify(pos)
    agg[e]['n'] += 1
    if grp is None:
        agg[e]['None'] += 1
        unclassified.append((season, team, pid, pos))
    else:
        agg[e][grp] += 1
    classify_counts[pos] = classify_counts.get(pos,0)+1

print("\n=== ERA AGGREGATION ===")
for e in eras:
    a = agg[e]; n=a['n']
    if n==0: 
        print(e, "NO DATA"); continue
    print(f"{e}: n={n}  Guard={a['Guard']/n*100:.1f}%  Wing={a['Wing']/n*100:.1f}%  Big={a['Big']/n*100:.1f}%  None={a['None']}")

print("\nUnclassified positions (count):", len(unclassified))
from collections import Counter
uc = Counter(p for (_,_,_,p) in unclassified)
for k,v in uc.most_common():
    print("   ", repr(k), v)

# save raw primary scorers for sampling
primary = []
for team, season, pid, total, ppg, g, pos in rows:
    primary.append({'team':team,'season':int(season),'pid':pid,
                    'total':float(total),'ppg':float(ppg),'g':int(g),
                    'pos':pos,'grp':classify(pos)})

with open('/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/primary_scorers.json','w') as f:
    json.dump(primary, f)

# sample seasons 1985-86 and 2025-26
for target in (1986, 2026):
    sample = [p for p in primary if p['season']==target]
    sample.sort(key=lambda x: x['team'])
    print(f"\n=== SAMPLE {target}: {len(sample)} teams ===")
    for p in sample:
        print(f"  {p['team']:4} {p['pid']:12} grp={p['grp']:5} pos={p['pos']} pts={p['total']:.0f} (ppg={p['ppg']:.1f}, g={p['g']})")

conn.close()
print("\nSAVED primary_scorers.json")
