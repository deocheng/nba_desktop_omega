#!/usr/bin/env python3
"""全量回填 player_salaries_historical 的 NULL team_abbr（覆盖 1997-2025 所有季）。

方法：
  1) 快照整表（可回滚）。
  2) 从 player_per_game(RS) 建索引：同季 (规范化名, 倒序名) -> 该球员当季出场最多(real team)。
     - 排除 2TM/3TM/TOT 聚合行，避免把"多队"标记当队属。
  3) 三级匹配回填 NULL 行：
     L1 精确：player_name 与 player 完全相同(去大小写/空格)。
     L2 规范化：去标点、小写、丢掉中间名缩写(单字母 token)、连字符归一，并尝试 名<->姓 倒序。
        （覆盖 Cedric E. Henderson / Ruben Boumtje-Boumtje / ZhiZhi Wang 等变体）
  4) 打印每季 before/after 与剩余样例，供逐行核对（L3 显式映射另行处理）。
"""
from __future__ import annotations

import datetime
import re
import sys
import unicodedata
from difflib import SequenceMatcher

import psycopg2

DB = dict(host="127.0.0.1", port=5433, dbname="nba", user="postgres",
          password="R!h0N-ctlg=xB01V_-1VJcFeCCuBjS6UCvV1")

SUFFIX = {"ii", "iii", "iv", "jr", "sr"}

# 土耳其语等特殊字符显式转写（NFKD 无法把 ı/İ 等变 ASCII）
TRANSLIT = str.maketrans({
    "ı": "i", "İ": "i", "ğ": "g", "ş": "s", "ç": "c", "ö": "o", "ü": "u",
    "æ": "a", "œ": "e", "ð": "d", "þ": "th", "ß": "ss",
})

def strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))  # 去掉组合变音符
    s = s.translate(TRANSLIT)                                   # 土耳其语等显式转写
    return s

def norm_core(name: str, minlen: int = 2):
    s = strip_accents(name.lower())
    s = re.sub(r"[^a-z ]", " ", s)          # 标点/连字符 -> 空格
    toks = [t for t in s.split() if t]
    core = [t for t in toks if len(t) >= minlen and t not in SUFFIX]
    if not core:
        core = [t for t in toks if t] or [""]
    return core

def keys_for(name: str):
    """返回 (strict_keys, loose_keys) 各自含 正序+倒序；loose 丢 len<=2 短 token。"""
    out = set()
    for minlen in (2, 3):
        core = norm_core(name, minlen)
        if not core or core == [""]:
            continue
        out.add(" ".join(core))
        if len(core) >= 2:
            out.add(" ".join(reversed(core)))
    return out

def surname_of(name: str):
    core = norm_core(name, 3)  # loose: 丢短 token，取末位为姓
    if not core or core == [""]:
        core = norm_core(name, 2)
    return core[-1] if core and core != [""] else ""

def main():
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()
    today = datetime.date.today().strftime("%Y%m%d")
    snap = f"player_salaries_historical_bak_{today}_allattr"
    cur.execute(f"DROP TABLE IF EXISTS {snap}")
    cur.execute(f"CREATE TABLE {snap} AS SELECT * FROM player_salaries_historical")
    conn.commit()
    print(f"[snapshot] {snap}")

    # 建 player_per_game 全局索引（任意季）：
    #   name_idx[norm_full] = [(season, team, g)]   精确名匹配（高优先，保老将 exact-S 正确）
    #   sur_idx[(surname, init)] = [(season, team, g)]  姓氏+首字母（取最近赛季队属）
    print("[index] 载入 player_per_game(RS) ...")
    cur.execute("""
        SELECT player, team, season, g FROM player_per_game
        WHERE season_type='Regular Season'
          AND player IS NOT NULL AND player<>''
          AND team IS NOT NULL AND team<>''
          AND team NOT LIKE '%TM' AND team<>'TOT'
    """)
    name_idx = {}
    sur_idx = {}
    nrows = 0
    for player, team, season, g in cur.fetchall():
        nrows += 1
        fwd = " ".join(norm_core(player, 2))
        name_idx.setdefault(fwd, []).append((season, team, g))
        tk = norm_core(player, 2)
        sn = tk[-1]
        init = tk[0][0] if tk[0] != sn else None
        sur_idx.setdefault((sn, init), []).append((season, team, g))
        if init is not None:
            sur_idx.setdefault((sn, None), []).append((season, team, g))  # 无首字母也兜底
    print(f"[index] player_per_game 行数={nrows}, 名索引={len(name_idx)}, 姓索引={len(sur_idx)}")

    def surname_options(name):
        tk = norm_core(name, 3)
        if not tk or tk == [""]:
            tk = norm_core(name, 2)
        opts = [tk[-1]]
        if len(tk) >= 3:
            opts.append(tk[-2])          # 中间名可能是真姓 (Walter Herrmann Heinrich)
        if len(tk) == 1:
            opts = [tk[0]]               # 单名 (Nene)
        return opts

    def pick_closest(cands, s):
        best = None
        for cs, cteam, cg in cands:
            d = abs(cs - s)
            key = (d, -cg)
            if best is None or key < best[0]:
                best = (key, cteam)
        return best[1] if best else None

    # 取全量 NULL 行
    cur.execute("SELECT id, player_name, season FROM player_salaries_historical WHERE team_abbr IS NULL")
    nulls = cur.fetchall()
    print(f"[null rows] 总数={len(nulls)}")

    upd = {}  # id -> team
    method = {}  # id -> 'exact'/'surname'/'difflib'
    for rid, pname, season in nulls:
        cand = None
        # L1 精确名（优先 exact-S，否则最近季）
        fwd = " ".join(norm_core(pname, 2))
        if fwd in name_idx:
            lst = name_idx[fwd]
            ex = [c for c in lst if c[0] == season]
            cand = pick_closest(ex, season) if ex else pick_closest(lst, season)
            if cand:
                method[rid] = "exact"
        # L2 姓氏+首字母，取最近赛季队属（±3 窗口隐含：sur_idx 含全部季，pick_closest 取最近）
        if cand is None:
            tk = norm_core(pname, 3)
            init = tk[0][0] if (tk and tk[0] != tk[-1]) else None
            for sn in surname_options(pname):
                for key in ((sn, init), (sn, None)):
                    if key in sur_idx:
                        cand = pick_closest(sur_idx[key], season)
                        if cand:
                            method[rid] = "surname"
                            break
                if cand:
                    break
        # L3 difflib 兜底（同姓、高相似）
        if cand is None:
            sal_norm = " ".join(norm_core(pname, 3))
            best, bestr = None, 0.0
            for sn in surname_options(pname):
                for (_, cinit), lst in sur_idx.items():
                    if _ != sn:
                        continue
                    for cs, cteam, cg in lst:
                        r = SequenceMatcher(None, sal_norm, " ".join(norm_core(f"{cinit or ''} {sn}", 2))).ratio()
                        if r > bestr:
                            bestr, best = r, cteam
            if best and bestr >= 0.8:
                cand, method[rid] = best, "difflib"
        if cand:
            upd[rid] = cand
    from collections import Counter
    mc = Counter(method.values())
    print(f"[match] 可解析={len(upd)}  待核对={len(nulls)-len(upd)}  方法分布={dict(mc)}")

    # 批量 UPDATE
    for rid, team in upd.items():
        cur.execute("UPDATE player_salaries_historical SET team_abbr=%s WHERE id=%s", (team, rid))
    conn.commit()
    print(f"[update] 已写入 {len(upd)} 行")

    # 报告
    cur.execute("SELECT COUNT(*) FROM player_salaries_historical WHERE team_abbr IS NULL")
    print(f"[after] 全表 NULL 行数={cur.fetchone()[0]}")
    cur.execute("""SELECT season, COUNT(*) FILTER (WHERE team_abbr IS NULL)
                   FROM player_salaries_historical GROUP BY season ORDER BY season""")
    print(f"{'season':<7}{'null':>7}")
    for r in cur.fetchall():
        if r[1]:
            print(f"{r[0]:<7}{r[1]:>7}")
    cur.execute("SELECT id, player_name, season, salary FROM player_salaries_historical WHERE team_abbr IS NULL LIMIT 40")
    rem = cur.fetchall()
    if rem:
        print(f"[sample remaining {len(rem)}]")
        for r in rem[:40]:
            print("  ", r)
    cur.close(); conn.close()
    print("DONE")

if __name__ == "__main__":
    main()
