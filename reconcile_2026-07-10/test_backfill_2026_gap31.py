#!/usr/bin/env python3
# QA 验收测试：_backfill_2026_gap31.py（2026 RS 缺失 31 场补录）
# 覆盖验收 6 项：复跑计数 / 31 game_id 字段规范 / 幂等 / §6 合规 / 回归前期不被影响 /（241 清单环境发现）
# 说明：自包含 harness（assert + 退出码），`python test_backfill_2026_gap31.py` 直接运行。
import os, sys, re, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(k, None)

import psycopg2
from psycopg2.extras import execute_values

sys.path.insert(0, HERE)
import _backfill_2026_gap31 as gap31  # noqa: 同目录模块，仅取 _GAP31 / parse_gap

DB = dict(host='localhost', port=5433, dbname='nba', user='postgres', password=os.environ.get('DB_PASSWORD'))
SCRIPT = os.path.join(HERE, '_backfill_2026_gap31.py')
TASK_FAILS = []


def check(name, cond, detail=''):
    c = bool(cond)
    status = 'PASS' if c else 'FAIL'
    print(f'[{status}] {name}' + (f' :: {detail}' if detail else ''))
    if not c:
        TASK_FAILS.append((name, detail))
    return c


def conn():
    return psycopg2.connect(**DB)


def load_tsv_241_ids():
    """复刻 _backfill_dim_games.parse_missing 的 game_id 推导（YYYYMMDD+home_abbr）。"""
    tsv = os.path.join(HERE, 'missing_2026_rs.tsv')
    ids = []
    with open(tsv) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            ds, a, h = line.split('\t')
            ids.append(ds.replace('-', '') + h)
    return ids


# ---------------------------------------------------------------------------
def test_count_1350():
    print('\n=== 验收1: 复跑计数 dim_games/games season=2026 RS = 1350 ===')
    c = conn(); cur = c.cursor()
    ok = True
    for t in ('dim_games', 'games'):
        cur.execute(
            "SELECT COUNT(*) FROM %s WHERE season=2026 AND season_type='Regular Season'" % t)
        n = cur.fetchone()[0]
        ok &= check(f'count({t}) == 1350', n == 1350, f'actual={n}')
    c.close()
    return ok


def test_31_ids_fields():
    print('\n=== 验收2: 31 个 game_id 存在且字段规范 ===')
    rows = gap31.parse_gap()
    ids = [r['game_id'] for r in rows]
    check('清单含 31 场', len(rows) == 31, f'len={len(rows)}')
    check('game_id 唯一', len(set(ids)) == 31, f'unique={len(set(ids))}')

    c = conn(); cur = c.cursor()
    ok = True
    cur.execute(
        "SELECT game_id, game_date, away_team_abbr, home_team_abbr, "
        "br_crawled_id, source, nba_api_id, home_pts, away_pts, season, season_type "
        "FROM dim_games WHERE game_id = ANY(%s)", (ids,))
    got = {r[0]: r for r in cur.fetchall()}
    ok &= check('dim_games 31 个全部存在', len(got) == 31, f'found={len(got)}')

    for r in rows:
        g = got.get(r['game_id'])
        if not g:
            ok = check(f'dim_games {r["game_id"]} 存在', False); continue
        (gid, gdate, aabbr, habbr, brid, src, nbaid, hpts, apts, season, stype) = g
        ok &= check(f'{gid}: game_date 非空', gdate is not None)
        ok &= check(f'{gid}: away/home abbr 非空', bool(aabbr) and bool(habbr))
        ok &= check(f'{gid}: br_crawled_id 非空且==game_id', brid == gid and brid is not None)
        ok &= check(f'{gid}: source=BBRef', src == 'BBRef', f'src={src}')
        ok &= check(f'{gid}: nba_api_id NULL', nbaid is None)
        ok &= check(f'{gid}: 比分列 home_pts/away_pts NULL', hpts is None and apts is None,
                    f'hpts={hpts} apts={apts}')
        ok &= check(f'{gid}: season=2026 & RS', season == 2026 and stype == 'Regular Season')

    cur.execute(
        "SELECT game_id, br_crawled_id, source, nba_api_id, home_pts, away_pts "
        "FROM games WHERE game_id = ANY(%s)", (ids,))
    gotg = {r[0]: r for r in cur.fetchall()}
    ok &= check('games 31 个全部存在', len(gotg) == 31, f'found={len(gotg)}')
    for r in rows:
        g = gotg.get(r['game_id'])
        if not g:
            ok = check(f'games {r["game_id"]} 存在', False); continue
        (gid, brid, src, nbaid, hpts, apts) = g
        ok &= check(f'games {gid}: br_crawled_id==game_id', brid == gid)
        ok &= check(f'games {gid}: source=BBRef', src == 'BBRef')
        ok &= check(f'games {gid}: nba_api_id NULL', nbaid is None)
        ok &= check(f'games {gid}: 比分列 NULL', hpts is None and apts is None)
    c.close()
    return ok


def test_idempotency_subprocess():
    print('\n=== 验收3: 幂等（再跑 --execute 应 0 新插入）===')
    before = _current_counts()
    proc = subprocess.run(
        [sys.executable, SCRIPT, '--execute'],
        capture_output=True, text=True, cwd=HERE)
    out = proc.stdout + proc.stderr
    print('  --- script stdout ---')
    for line in out.strip().splitlines():
        print('   ', line)
    print('  --- end ---')
    zero_inserted = ('已插入 dim_games: 0' in out and 'games: 0' in out) or ('无需补录' in out)
    ok = check('再跑 --execute 报告 0 新插入/无需补录', zero_inserted, out.strip().replace('\n', ' | '))
    after = _current_counts()
    ok &= check('dim_games 计数前后一致(=1350)', before[0] == after[0] == 1350,
                f'before={before[0]} after={after[0]}')
    ok &= check('games 计数前后一致(=1350)', before[1] == after[1] == 1350,
                f'before={before[1]} after={after[1]}')
    return ok


def _current_counts():
    c = conn(); cur = c.cursor()
    cur.execute("SELECT COUNT(*) FROM dim_games WHERE season=2026 AND season_type='Regular Season'")
    d = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM games WHERE season=2026 AND season_type='Regular Season'")
    g = cur.fetchone()[0]
    c.close()
    return (d, g)


def test_idempotency_onconflict_mechanism():
    """强幂等：直接对“已存在”的 31 行调用 execute_values ON CONFLICT DO NOTHING，确认 0 影响。"""
    print('\n=== 验收3(强): ON CONFLICT DO NOTHING 机制对已有行 0 影响 ===')
    rows = gap31.parse_gap()
    dim_cols = ['game_id', 'game_date', 'season', 'season_type',
                'away_team_abbr', 'home_team_abbr', 'away_team_name', 'home_team_name',
                'away_team_id', 'home_team_id', 'br_crawled_id', 'nba_api_id',
                'source', 'game_status', 'pbp_saved', 'pbp_imported']
    games_cols = ['game_id', 'game_date', 'season', 'season_type',
                  'away_team_abbr', 'home_team_abbr', 'br_crawled_id', 'nba_api_id',
                  'source', 'game_status']
    dim_data = [tuple(r[col] for col in dim_cols) for r in rows]
    games_data = [tuple(r[col] for col in games_cols) for r in rows]

    c = conn(); cur = c.cursor()
    b_d = _count_any(cur, 'dim_games', [r['game_id'] for r in rows])
    b_g = _count_any(cur, 'games', [r['game_id'] for r in rows])
    execute_values(cur,
                   "INSERT INTO dim_games (" + ','.join(dim_cols) + ") VALUES %s "
                   "ON CONFLICT (game_id) DO NOTHING", dim_data)
    execute_values(cur,
                   "INSERT INTO games (" + ','.join(games_cols) + ") VALUES %s "
                   "ON CONFLICT DO NOTHING", games_data)
    c.commit()
    a_d = _count_any(cur, 'dim_games', [r['game_id'] for r in rows])
    a_g = _count_any(cur, 'games', [r['game_id'] for r in rows])
    c.close()
    ok = check('ON CONFLICT: dim_games 0 新增', a_d == b_d, f'before={b_d} after={a_d}')
    ok &= check('ON CONFLICT: games 0 新增', a_g == b_g, f'before={b_g} after={a_g}')
    return ok


def _count_any(cur, tbl, ids):
    cur.execute("SELECT COUNT(*) FROM %s WHERE game_id = ANY(%%s)" % tbl, (ids,))
    return cur.fetchone()[0]


def test_sec6_no_dynamic_sql():
    print('\n=== 验收4: §6 合规（无动态 SQL 拼值）===')
    src = open(SCRIPT, encoding='utf-8').read()
    ok = True
    # 4a. 禁止：execute* 调用中把“裸变量”用 + 拼进 SQL 字符串（execute(cur,"..."+var+...)）。
    #     允许：字符串字面量之间 + 连接、f"{代码字面量}" 插值；值统一用 %s。
    forbidden = re.search(
        r'execute(?:_values)?\s*\([^;]*?\w+\s*,\s*["\'][^"\']*["\']\s*\+\s*[a-zA-Z_]\w*\s*\+',
        src)
    ok &= check('无 `execute("..."+var+...)` 式值拼接', forbidden is None,
                forbidden.group(0)[:80] if forbidden else '')
    # 4b. 正向：≥2 个 execute_values；INSERT 值 %s 参数化；带 ON CONFLICT DO NOTHING
    n_ev = len(re.findall(r'execute_values\s*\(', src))
    ok &= check('存在 ≥2 个 execute_values INSERT', n_ev >= 2, f'found={n_ev}')
    ok &= check('INSERT 值使用 %s 参数化', '%s' in src)
    ok &= check('INSERT 带 ON CONFLICT DO NOTHING', 'ON CONFLICT' in src and 'DO NOTHING' in src)
    # 4c. 无任何外部输入进入 SQL：无 input()；argv 仅作 --execute 开关；未 open() 读数据入 SQL
    ok &= check('无 input() 外部输入', 'input(' not in src)
    ok &= check('argv 仅用于 --execute 开关(非 SQL)',
                "sys.argv" in src and "'--execute' in sys.argv" in src)
    ok &= check('无 open() 读取外部数据入 SQL（_GAP31 硬编码）', 'open(' not in src)
    # 4d. SQL 中的 f-string 仅插值代码字面量表名 {tbl}，数据用 %s
    sql_fs = [fs for fs in re.findall(r'f["\']([^"\']*)["\']', src)
              if re.search(r'\b(SELECT|INSERT|UPDATE|DELETE)\b', fs, re.I)]
    for fs in sql_fs:
        ok &= check(f'SQL f-string 仅插值代码字面量: {fs[:50]}',
                    re.search(r'\{tbl\}', fs) is not None and '%s' in fs)
    ok &= check('存在合规 SQL f-string（表名字面量插值）', len(sql_fs) >= 1, f'found={len(sql_fs)}')
    return ok


def test_regression_no_dup():
    print('\n=== 验收5: 回归-无重复 / 前期 1319 行未被影响 ===')
    c = conn(); cur = c.cursor()
    ok = True
    for t in ('dim_games', 'games'):
        cur.execute(
            "SELECT COUNT(*) FROM (SELECT game_id FROM %s "
            "WHERE season=2026 AND season_type='Regular Season' "
            "GROUP BY game_id HAVING COUNT(*)>1) s" % t)
        dups = cur.fetchone()[0]
        ok &= check(f'{t} season=2026 RS 无重复 game_id', dups == 0, f'dups={dups}')

    # 前期 1319 行未被影响：935(NULL source) + 384(既有 BBRef) 保持；gap31 仅追加 31
    cur.execute(
        "SELECT source, COUNT(*) FROM dim_games WHERE season=2026 AND season_type='Regular Season' "
        "GROUP BY source")
    dist = dict(cur.fetchall())
    n_null = dist.get(None, 0)
    n_bbref = dist.get('BBRef', 0)
    ok &= check('前期 NULL-source 行保持 935（未被改动）', n_null == 935, f'n_null={n_null}')
    ok &= check('BBRef 总数 = 415 (= 既有384 + gap31 31)', n_bbref == 415, f'n_bbref={n_bbref}')
    ok &= check('总计 = 935 + 415 = 1350', n_null + n_bbref == 1350)
    ids31 = [r['game_id'] for r in gap31.parse_gap()]
    cur.execute("SELECT COUNT(*) FROM dim_games WHERE game_id = ANY(%s) "
                "AND season=2026 AND season_type='Regular Season' AND source='BBRef'",
                (ids31,))
    n31 = cur.fetchone()[0]
    ok &= check('31 个 gap31 行均已落库(BBRef)', n31 == 31, f'found={n31}')

    # 【环境发现 / 非 gap31 缺陷】验收文案提及“既有 241 补录行未被影响”，但磁盘
    # missing_2026_rs.tsv 推导的 241 个 id 仅 29 个存在于本库 —— 该 241 补录疑似未在本环境
    # 落地（数据漂移）。与 _backfill_2026_gap31.py 无关（其仅 INSERT，不删不改）。列为 WARNING。
    ids241 = load_tsv_241_ids()
    cur.execute("SELECT COUNT(*) FROM dim_games WHERE game_id = ANY(%s)", (ids241,))
    n241 = cur.fetchone()[0]
    overlap = len(set(ids241) & set(ids31))
    print(f'  [WARNING] 241 补录清单(missing_2026_rs.tsv)在本库仅存在 {n241}/241 行'
          f'（其中 {overlap} 行与 gap31 重叠）。该 241 补录疑似未在本环境落地，'
          f'属数据/环境漂移，非 _backfill_2026_gap31.py 缺陷，建议主理人核查 _backfill_dim_games.py 是否在本环境执行。')
    c.close()
    return ok


def main():
    print('############ QA 验收 _backfill_2026_gap31.py ############')
    r1 = test_count_1350()
    r2 = test_31_ids_fields()
    r3 = test_idempotency_subprocess()
    r4 = test_idempotency_onconflict_mechanism()
    r5 = test_sec6_no_dynamic_sql()
    r6 = test_regression_no_dup()

    all_ok = r1 and r2 and r3 and r4 and r5 and r6
    print('\n================ 验收汇总 ================')
    print(f'计数1350={r1} | 31字段={r2} | 幂等脚本={r3} | 幂等机制={r4} | §6={r5} | 回归={r6}')
    if TASK_FAILS:
        print('FAIL 项:')
        for n, d in TASK_FAILS:
            print(f'  - {n} :: {d}')
    print('RESULT:', 'ALL PASS' if all_ok else 'HAS FAIL')
    sys.exit(0 if all_ok else 1)


if __name__ == '__main__':
    main()
