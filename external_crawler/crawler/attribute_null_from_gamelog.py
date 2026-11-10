#!/usr/bin/env python3
"""用 player_gamelog（完整逐场来源）回填 player_salaries_historical 剩余 NULL team_abbr。

player_per_game 是聚合表，漏掉了只打几场/没出场的边缘与海外球员（Nene、Richard Hendrix 等），
故改用 player_gamelog（150万行，覆盖所有登场球员，自带 team/season/player_name）。

匹配：规范化名 token（去变音/连字符/中间缩写，土耳其语转写）后
  L1 精确 token 集 + exact season（老将正确）
  L2 ±1 赛季偏移（simple_csv 新秀首年按选秀年标）
  L3 token 子集（"Nene Hilario" ⊆ "Nene" / "Walter Herrmann Heinrich" ⊇ "Walter Herrmann"）
  L4 姓氏+首字母 最近季
可回滚：先整表快照。
"""
from __future__ import annotations
import psycopg2, datetime, re, unicodedata
from collections import Counter

DB = dict(host="127.0.0.1", port=5433, dbname="nba", user="postgres",
          password="R!h0N-ctlg=xB01V_-1VJcFeCCuBjS6UCvV1")
SUFFIX = {"ii", "iii", "iv", "jr", "sr"}
TRANSLIT = str.maketrans({"ı": "i", "İ": "i", "ğ": "g", "ş": "s", "ç": "c",
                           "ö": "o", "ü": "u", "æ": "a", "œ": "e", "ð": "d", "þ": "th", "ß": "ss"})

def strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.translate(TRANSLIT)
    s = s.replace("oe", "o").replace("ae", "a")   # 德语变体 oe=ö / ae=ä
    return s

def toks(name: str, ml: int = 2):
    t = [x for x in re.sub(r"[^a-z ]", " ", strip_accents(name.lower())).split() if len(x) >= ml and x not in SUFFIX]
    return t or [name.lower()]

def surname_of(tk):
    return tk[-1] if tk else ""

def main():
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()
    today = datetime.date.today().strftime("%Y%m%d")
    snap = f"player_salaries_historical_bak_{today}_gl"
    cur.execute(f"DROP TABLE IF EXISTS {snap}")
    cur.execute(f"CREATE TABLE {snap} AS SELECT * FROM player_salaries_historical")
    conn.commit()
    print(f"[snapshot] {snap}")

    # 建 gamelog 索引：赛季优先用 gamelog.season，否则用 game_id_full->dim_games 反推
    print("[index] 载入 player_gamelog(反推赛季) ...")
    cur.execute("""SELECT gl.player_name, gl.team, COALESCE(gl.season, dg.season) AS ssn
                   FROM player_gamelog gl
                   LEFT JOIN dim_games dg ON gl.game_id_full = dg.game_id
                   WHERE gl.team IS NOT NULL AND gl.team<>''
                     AND gl.player_name<>''
                     AND COALESCE(gl.season, dg.season) IS NOT NULL""")
    by_tokens = {}   # (season, frozenset(toks)) -> Counter(team)
    by_sur = {}      # (season, surname, init) -> Counter(team)
    n = 0
    for pname, team, season in cur.fetchall():
        n += 1
        tk = toks(pname, 2)
        fs = frozenset(tk)
        by_tokens.setdefault((season, fs), Counter())[team] += 1
        sn = surname_of(tk)
        init = tk[0][0] if tk[0] != sn else None
        by_sur.setdefault((season, sn, init), Counter())[team] += 1
        if init is not None:
            by_sur.setdefault((season, sn, None), Counter())[team] += 1
    print(f"[index] gamelog 行数={n}, token键={len(by_tokens)}, 姓键={len(by_sur)}")

    cur.execute("SELECT id, player_name, season FROM player_salaries_historical WHERE team_abbr IS NULL")
    nulls = cur.fetchall()
    print(f"[null rows] {len(nulls)}")

    def best(ctr):
        return ctr.most_common(1)[0][0] if ctr else None

    upd = {}
    method = {}
    # 显式兜底：gamelog 该季缺口但队属明确者（Dennis Schroder 2023 gamelog 反推缺，已知 HOU）
    EXPLICIT = {("Dennis Schroeder", 2023): "HOU"}
    for rid, pname, season in nulls:
        if (pname, season) in EXPLICIT:
            upd[rid] = EXPLICIT[(pname, season)]; method[rid] = "explicit"; continue
        tk = toks(pname, 2)
        fs = frozenset(tk)
        init = tk[0][0] if tk[0] != surname_of(tk) else None
        sn = surname_of(tk)
        cand = None
        win = (season, season + 1, season - 1, season + 2, season - 2, season + 3, season - 3)
        # L1 精确 token 集
        for s in win:
            if (s, fs) in by_tokens:
                cand = best(by_tokens[(s, fs)]); method[rid] = "exact"; break
        # L3 token 子集（gamelog 名 ⊆ salary 名，或反之）
        if cand is None:
            for s in win:
                for (gs, gfs), ctr in by_tokens.items():
                    if gs == s and (gfs <= fs or fs <= gfs):
                        cand = best(ctr); method[rid] = "subset"; break
                if cand:
                    break
        # L4 姓氏+首字母
        if cand is None:
            for s in win:
                for key in ((s, sn, init), (s, sn, None)):
                    if key in by_sur:
                        cand = best(by_sur[key]); method[rid] = "surname"; break
                if cand:
                    break
        if cand:
            upd[rid] = cand
    from collections import Counter as C
    print(f"[match] 可解析={len(upd)} 待核对={len(nulls)-len(upd)} 方法={dict(C(method.values()))}")

    for rid, team in upd.items():
        cur.execute("UPDATE player_salaries_historical SET team_abbr=%s WHERE id=%s", (team, rid))
    conn.commit()
    print(f"[update] 已写入 {len(upd)} 行")

    cur.execute("SELECT COUNT(*) FILTER (WHERE team_abbr IS NULL) FROM player_salaries_historical")
    print(f"[after] 全表 NULL = {cur.fetchone()[0]}")
    cur.execute("""SELECT season, COUNT(*) FILTER (WHERE team_abbr IS NULL) FROM player_salaries_historical
                   GROUP BY season ORDER BY season""")
    for r in cur.fetchall():
        if r[1]:
            print(f"  {r[0]}: {r[1]}")
    cur.execute("SELECT id,player_name,season,salary FROM player_salaries_historical WHERE team_abbr IS NULL LIMIT 40")
    rem = cur.fetchall()
    if rem:
        print(f"[sample remaining {len(rem)}]")
        for r in rem[:40]:
            print("  ", r)
    cur.close(); conn.close()
    print("DONE")

if __name__ == "__main__":
    main()
