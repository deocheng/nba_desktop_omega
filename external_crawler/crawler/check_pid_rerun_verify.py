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

print("===== (1) 2026 孤儿/空值落点 =====")
print(q("""SELECT count(*) AS total_2026,
  count(*) FILTER (WHERE br_player_id IS NULL OR br_player_id='') AS br_null,
  count(*) FILTER (WHERE player_id IS NULL) AS pid_null,
  count(*) FILTER (WHERE br_player_id IS NULL AND player_id IS NULL) AS both_null
FROM player_gamelog WHERE season=2026;"""))

print("\n===== (2) 2026 行数 vs 去重球员(解释 29520 vs 28365 落差) =====")
print(q("""SELECT count(*) AS total_rows,
  count(DISTINCT player_id) AS distinct_pid,
  count(DISTINCT br_player_id) FILTER (WHERE br_player_id<>'') AS distinct_br
FROM player_gamelog WHERE season=2026;"""))

print("\n===== (3) verify_gaps 曾报的 45 行 br_player_id NULL 孤儿，现在还在吗 =====")
print(q("""SELECT count(*) AS br_null_rows
FROM player_gamelog WHERE season=2026 AND (br_player_id IS NULL OR br_player_id='');"""))

print("\n===== (4) 备份表仍在?(可作回滚点) =====")
print(q("SELECT to_regclass('player_gamelog_bak_pid_20260807');"))
