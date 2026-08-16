#!/usr/bin/env python3
"""
verify_gaps.py — 严格逐人完整性校验（替代临场手写 SQL，杜绝误判）

判定口径（已核验）：
  - 真相源：player_per_game（BR 每场聚合表），只取 player_id 非空且非空的 slug 行。
  - 比对侧：player_gamelog，按 br_player_id（同 slug）聚合。
  - 连接键：player_per_game.player_id = player_gamelog.br_player_id
    （两列都是 BR slug；player_per_game.season=bigint / player_gamelog.season=smallint，
     与 dim_games.season=integer 均为数字型，跨类型比较安全）
  - 缺口 = 某球员在 player_per_game 的场次 > 在 player_gamelog 的场次。

同时输出：
  - 每季「比赛覆盖」：player_gamelog distinct gameid vs dim_games(Regular Season) 场次数。
  - 孤儿/多余告警（信息性，不计入缺口）：br_player_id 为 NULL 的行、gamelog 有但
    player_per_game 无对应 slug 的行。

用法：
  python3 verify_gaps.py 2025          # 单季
  python3 verify_gaps.py --all         # 2004-2026 逐季
  python3 verify_gaps.py 2024 2025     # 多季

退出码：0 = 所有指定季无缺口；1 = 存在缺口（便于当 CI/门禁）。
"""
import os
import sys
import subprocess

ROOT = "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13"
PSQL = "/opt/homebrew/opt/postgresql@18/bin/psql"


def get_pw():
    try:
        with open(os.path.join(ROOT, ".env")) as f:
            for line in f:
                if line.startswith("DB_PASSWORD="):
                    return line.strip().split("=", 1)[1]
    except Exception:
        pass
    return os.environ.get("PGPASSWORD", "")


PW = os.environ.get("PGPASSWORD") or get_pw()
os.environ["PGPASSWORD"] = PW


def psql(query: str) -> str:
    p = subprocess.run(
        [PSQL, "-h", "localhost", "-p", "5433", "-U", "postgres", "-d", "nba",
         "-t", "-A", "-F", "|", "-c", query],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        sys.stderr.write(f"PSQL ERROR (rc={p.returncode}):\n{p.stderr}\nQUERY:\n{query}\n")
        sys.exit(2)
    return p.stdout


def check_season(S: int, quiet: bool = False):
    # ① 逐人缺口（核心）
    # 关键：player_per_game 是「每球员每季聚合表」，每球员仅 1 行，真实出场场次在 `g` 列。
    #   绝不能用 COUNT(*) 当场次（那样每球员恒为 1，会误报 0 缺口）。
    #   期望场次 = player_per_game.g；实际场次 = player_gamelog 按 br_player_id 计数。
    #   连接键 = player_per_game.player_id(=BR slug) = player_gamelog.br_player_id。
    q_gap = f"""
    WITH exp AS (
      SELECT player_id, MAX(g) AS n
      FROM player_per_game
      WHERE season={S} AND player_id IS NOT NULL AND player_id <> ''
      GROUP BY player_id
    ),
    act AS (
      SELECT br_player_id, COUNT(*) AS n
      FROM player_gamelog
      WHERE season={S} AND br_player_id IS NOT NULL AND br_player_id <> ''
      GROUP BY br_player_id
    ),
    nm AS (
      SELECT DISTINCT player_id, player FROM player_per_game
      WHERE season={S} AND player_id IS NOT NULL AND player_id <> ''
    )
    SELECT e.player_id, COALESCE(nm.player, e.player_id),
           e.n, COALESCE(a.n, 0), e.n - COALESCE(a.n, 0)
    FROM exp e
    LEFT JOIN act a ON a.br_player_id = e.player_id
    LEFT JOIN nm ON nm.player_id = e.player_id
    WHERE e.n > COALESCE(a.n, 0)
    ORDER BY (e.n - COALESCE(a.n, 0)) DESC, nm.player;
    """
    gap_rows = [r for r in psql(q_gap).strip().split("\n") if r]

    # ② 比赛覆盖（Regular Season 场次，用 EXISTS 精确算缺失，避免 distinct 把非 Reg 场混入）
    #   gameid 是 varchar，dim_games.nba_api_id 是 bigint，必须 ::bigint 转换；
    #   且必须用 EXISTS（NOT IN 遇 NULL 子元素会整体变 NULL → 假阴性）。
    q_cov = f"""
    SELECT
      (SELECT count(*) FROM dim_games WHERE season={S} AND season_type='Regular Season'),
      (SELECT count(*) FROM dim_games d
         WHERE d.season={S} AND d.season_type='Regular Season'
           AND EXISTS (SELECT 1 FROM player_gamelog g
                         WHERE g.season={S} AND g.gameid IS NOT NULL
                           AND g.gameid::bigint = d.nba_api_id));
    """
    cov = psql(q_cov).strip().split("|")
    exp_g = int(cov[0]) if cov and cov[0] else 0
    cov_g = int(cov[1]) if len(cov) > 1 and cov[1] else 0

    # ③ 孤儿/多余告警（信息性）
    q_warn = f"""
    SELECT
      (SELECT count(*) FROM player_gamelog WHERE season={S} AND br_player_id IS NULL),
      (SELECT count(DISTINCT br_player_id) FROM player_gamelog
         WHERE season={S} AND br_player_id IS NOT NULL AND br_player_id <> ''
           AND br_player_id NOT IN (SELECT player_id FROM player_per_game
               WHERE season={S} AND player_id IS NOT NULL AND player_id <> ''));
    """
    warn = psql(q_warn).strip().split("|")
    null_rows = int(warn[0]) if warn and warn[0] else 0
    extra_players = int(warn[1]) if len(warn) > 1 and warn[1] else 0

    cov_ok = (exp_g > 0 and cov_g >= exp_g)
    gap_pids = [r.split("|")[0] for r in gap_rows]
    if not quiet:
        print(f"\n===== season {S} =====")
        if exp_g:
            miss = exp_g - cov_g
            print(f"  比赛覆盖(RS): player_gamelog 覆盖 {cov_g} / dim_games(Reg) {exp_g}"
                  + ("  OK" if cov_ok else f"  !! 覆盖不足（缺 {miss} 场）"))
        else:
            print(f"  比赛覆盖(RS): dim_games 无该季 Regular Season 记录，跳过覆盖校验")
        if null_rows:
            print(f"  [告警] br_player_id 为 NULL 的孤儿行: {null_rows}（不影响逐人缺口，待去重）")
        if extra_players:
            print(f"  [告警] gamelog 有但 player_per_game 无 slug 匹配的球员: {extra_players}（身份/来源差异，需人工核）")
        if not gap_rows:
            print(f"  [逐人完整性] OK: 0 缺失球员（按 player_per_game.g 比对，全部 slug 球员场次齐全）")
        else:
            total_gap = 0
            print(f"  [逐人完整性] !! {len(gap_rows)} 个球员缺失场次:")
            for r in gap_rows:
                parts = r.split("|")
                pid, pname, expn, actn, gap = parts[0], parts[1], parts[2], parts[3], int(parts[4])
                total_gap += gap
                print(f"     {pname} ({pid}): 应有 {expn} 场, 现有 {actn} 场, 缺 {gap} 场")
            print(f"  [逐人完整性] 合计缺失场次: {total_gap}（跨 {len(gap_rows)} 人）")
    if gap_rows or not cov_ok:
        return 1, gap_pids
    return 0, gap_pids


def main():
    args = sys.argv[1:]
    missing_ids = "--missing-ids" in args
    args = [a for a in args if a != "--missing-ids"]
    seasons = []
    for a in args:
        if a in ("--all", "-a"):
            seasons = list(range(2004, 2027))
            break
        try:
            seasons.append(int(a))
        except ValueError:
            print(f"忽略无法解析的参数: {a}", file=sys.stderr)
    if not seasons:
        seasons = [2025]
    rc = 0
    all_pids = []
    for S in seasons:
        s_rc, gap_pids = check_season(S, quiet=missing_ids)
        if missing_ids:
            all_pids.extend(gap_pids)
        if s_rc:
            rc = 1
    if missing_ids:
        for pid in all_pids:
            print(pid)
        sys.exit(0)
    if rc:
        print(f"\n>>> 存在缺口（rc=1）")
    else:
        print(f"\n>>> 全部指定季通过逐人完整性校验（rc=0）")
    sys.exit(rc)


if __name__ == "__main__":
    main()
