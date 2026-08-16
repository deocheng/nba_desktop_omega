import os, subprocess

val = None
for line in open('/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/.env'):
    line = line.strip()
    if line.startswith('DB_PASSWORD'):
        val = line.split('=', 1)[1].strip().strip('"').strip("'")
        break
env = os.environ.copy(); env['PGPASSWORD'] = val

def q(sql):
    r = subprocess.run(
        ['/opt/homebrew/opt/postgresql@18/bin/psql', '-h', '127.0.0.1', '-p', '5433',
         '-U', 'postgres', '-d', 'nba', '-t', '-c', sql],
        env=env, capture_output=True, text=True)
    return r.stdout.strip() or r.stderr.strip()

print("===== (1) 2026 缺 player_id 且 br_player_id 非空的 distinct 球员(=bridge 缺其 NBA id,可补) =====")
print(q("""SELECT DISTINCT br_player_id, player_name
FROM player_gamelog
WHERE season=2026 AND player_id IS NULL AND br_player_id IS NOT NULL AND br_player_id<>''
ORDER BY br_player_id;"""))

print("\n===== (2) 这 25 人: 在 bridge 里是'不存在'还是'nba_player_id 为 NULL'? =====")
print(q("""SELECT
  count(*) FILTER (WHERE b.br_player_id IS NULL) AS not_in_bridge,
  count(*) FILTER (WHERE b.br_player_id IS NOT NULL AND b.nba_player_id IS NULL) AS in_bridge_but_null_nba
FROM (SELECT DISTINCT br_player_id, player_name FROM player_gamelog
      WHERE season=2026 AND player_id IS NULL AND br_player_id IS NOT NULL AND br_player_id<>'') g
LEFT JOIN player_id_bridge b ON b.br_player_id=g.br_player_id;"""))

print("\n===== (3) 关键: 这 25 人能否从【其他赛季】player_gamelog 借到数字 id(按 br_player_id 跨季)? =====")
print(q("""SELECT g.br_player_id,
  count(DISTINCT pg.player_id) FILTER (WHERE pg.player_id IS NOT NULL) AS distinct_nba_ids_in_other_seasons
FROM (SELECT DISTINCT br_player_id FROM player_gamelog
      WHERE season=2026 AND player_id IS NULL AND br_player_id IS NOT NULL AND br_player_id<>'') g
LEFT JOIN player_gamelog pg ON pg.br_player_id=g.br_player_id AND pg.season<>2026 AND pg.player_id IS NOT NULL
GROUP BY g.br_player_id
ORDER BY g.br_player_id;"""))

print("\n===== (4) 45 行 br_player_id NULL 孤儿(bridge 永远无法补,只能 DELETE) =====")
print(q("""SELECT count(*) AS orphan_rows FROM player_gamelog
WHERE season=2026 AND (br_player_id IS NULL OR br_player_id='');"""))
