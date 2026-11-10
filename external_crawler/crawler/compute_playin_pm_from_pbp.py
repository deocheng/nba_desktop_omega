#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""compute_playin_pm_from_pbp.py — 从 PBP 原始流精确重建 Play-In 球员正负值。

动机（2026-08-17 仲裁链）：
  * pm 页 On 与 box 页全场 +/- 存在互斥离群（202105190LAL: pm -6 vs box -7）；
  * box 逐节表与 box 全场表自矛盾（202304120TOR Caruso: 逐节和 +8 vs 全场 +5=NBA.com +8）。
  → 两页都是 BR 的衍生展示，最原始数据是 PBP 流本身。

方法（离线，零网络，用 /tmp/playin_all4_cache 已缓存 PBP HTML）：
  1. PBP 描述中球员名带 <a href="/players/x/slugxx01"> 锚点 → 精确 slug，无姓名歧义；
  2. 替换事件 "X enters the game for Y" → 在场阵容迁移；
  3. 先发推导：roster 中「从未作为替补登场」者 = 先发（每队 5 人）；
  4. 相邻事件比分差 → 归因到当时在场 10 人（主队 +margin / 客队 -margin）；
  5. 按节聚合 + 全场合计。

输出：对比 box 页全场值（同意率）+ 可选落库（--write 覆盖 player_playin_plus_minus
的 q 列与 plus_minus_total，以 PBP 重建为权威；off/net 保留 pm 页值）。
"""
import sys, os, re, argparse, logging
from pathlib import Path
sys.path.insert(0, "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13")
sys.path.insert(0, "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/external_crawler/crawler")
from bs4 import BeautifulSoup
import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("pm_pbp")

from scrape_playin_all4 import (db_conn, load_games, cached_fetch, parse_box_pm,
                                BR_ABBR, NBA_ABBR)

SUB_RE = re.compile(r"enters the game for", re.I)
SCORE_RE = re.compile(r"(\d+)\s*-\s*(\d+)")

def parse_pbp_events(html, game):
    """从 PBP HTML 抽事件流：[(period, clock_s, score(h,a), side, desc_html, links)]。
    links = [(slug, text), ...] 按文档序。"""
    soup = BeautifulSoup(html, "lxml")
    tbl = soup.find("table", id="pbp")
    if tbl is None:
        return []
    away_br = BR_ABBR.get(game["away"], game["away"])
    home_br = BR_ABBR.get(game["home"], game["home"])
    period, events = 1, []
    tbody = tbl.find("tbody") or tbl
    for tr in tbody.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if tr.get("class") and "thead" in tr.get("class"):
            joined = " ".join(c.get_text(strip=True) for c in cells)
            from br_pbp_parse import detect_period
            p = detect_period(joined)
            if p: period = p
            continue
        if len(cells) < 6:
            continue
        time_str = cells[0].get_text(strip=True)
        m = re.match(r"(\d{1,2}):(\d{2})", time_str)
        if not m:
            continue
        clock_s = int(m.group(1)) * 60 + int(m.group(2))
        away_td, score_td, home_td = cells[1], cells[3], cells[5]
        sm = SCORE_RE.search(score_td.get_text(strip=True))
        score = (int(sm.group(2)), int(sm.group(1))) if sm else (None, None)  # (h, a)
        for td, side, abbr in ((away_td, "away", away_br), (home_td, "home", home_br)):
            desc = td.get_text(strip=True)
            if desc:
                links = [(a.get("href", "").split("/")[-1].removesuffix(".html"),
                          a.get_text(strip=True))
                         for a in td.find_all("a") if "/players/" in a.get("href", "")]
                events.append((period, clock_s, score, side, abbr, desc, links))
                break  # 每行只有一侧有事件
    return events

def _mp_seconds(s):
    m = re.match(r"(\d+):(\d{2})", s or "")
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None

def parse_box_quarter_mp(box_html, game):
    """从 box 页各节表抽 {team_nba: {period: {slug: mp_seconds, name}}}。"""
    from scrape_playin_all4 import parse_box_tables_meta
    return parse_box_tables_meta(box_html, game)

def reconstruct(game, html, box_html, roster):
    """混合锚定重建（v2 修正版，2026-08-17 诊断：旧版把「先发被换下后 re-enter」误判
    为节初不在场，锚定 0-2 人；改为按首次卷入换人事件的角色判定）：
    * 每节起始在场 = mp==整节时长(720s/300s) 者
      ∪ 首次卷入本节换人事件的角色是「被换下」(out) 者
      （先发被换下后 re-enter 的球员首次卷入是 out → 正确锚定；
        免疫 BR PBP 跨节换人漏记，如 202008150POR Morant Q2 案）；
    * 节内按替换事件迁移，比分差归因在场 10 人。
    roster: {team_nba: {slug: name}}"""
    events = parse_pbp_events(html, game)
    away_br = BR_ABBR.get(game["away"], game["away"])
    home_br = BR_ABBR.get(game["home"], game["home"])
    nba_of = {away_br: game["away"], home_br: game["home"]}
    qmp = parse_box_quarter_mp(box_html, game)  # {team: {period: {slug: mp}}}
    pm, team_of = {}, {}
    def ensure(slug, team):
        if slug not in pm:
            pm[slug] = [0] * 8
            team_of[slug] = team
    # 换人事件（带序号）
    subs = []
    for i, (period, clock, score, side, abbr, desc, links) in enumerate(events):
        if SUB_RE.search(desc) and len(links) >= 2:
            team = nba_of.get(abbr)
            if team:
                subs.append((i, links[0][0], links[1][0], team))
    sub_map = {i: (a, b, t) for i, a, b, t in subs}
    # 逐节处理
    last_score = (0, 0)
    cur_period = 0
    oncourt = {game["away"]: set(), game["home"]: set()}
    seen_periods = sorted({p for p, *_ in events} | {p for t in qmp for p in qmp[t]})
    for p in seen_periods:
        full = 300 if p >= 5 else 720
        pev = [(i, e) for i, e in enumerate(events) if e[0] == p]
        psubs = {i: (a, b, t) for i, a, b, t in subs if events[i][0] == p}
        for team in oncourt:
            mps = qmp.get(team, {}).get(p, {})
            psubs_team = [(a, b) for i, a, b, t in subs
                          if events[i][0] == p and t == team]
            # 每球员在本节首次卷入换人的角色：in=节初替补席 / out=节初在场
            first_role = {}
            for k, (a, b) in enumerate(psubs_team):
                if a not in first_role:
                    first_role[a] = "in"
                if b not in first_role:
                    first_role[b] = "out"
            anchored = set()
            for slug, mp in mps.items():
                if mp == full:
                    anchored.add(slug)
                elif first_role.get(slug) == "out":
                    anchored.add(slug)
            if len(anchored) != 5:
                log.warning("  %s P%d %s: 节初锚定 %d 人 %s",
                            game["br_url_id"], p, team, len(anchored),
                            sorted(anchored))
            oncourt[team] = anchored
            for s in anchored:
                ensure(s, team)
        for i, (period, clock, score, side, abbr, desc, links) in pev:
            if score != (None, None) and score != last_score:
                dh = score[0] - last_score[0]
                da = score[1] - last_score[1]
                if dh or da:
                    margin = dh - da
                    for team, sign in ((game["home"], margin), (game["away"], -margin)):
                        for s in oncourt.get(team, ()):
                            ensure(s, team)
                            pm[s][p - 1 if p <= 8 else 7] += sign
                last_score = score
            if i in sub_map:
                in_slug, out_slug, team = sub_map[i]
                oc = oncourt.get(team)
                if oc is not None:
                    oc.discard(out_slug)
                    oc.add(in_slug)
                    ensure(in_slug, team)
    return {"pm": pm, "team_of": team_of}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="以 PBP 重建值覆写 pppm 的 q 列与 total")
    args = ap.parse_args()
    conn = db_conn()
    games = load_games(conn)
    agree = disagree = 0
    all_results = {}
    for g in games:
        box_html = cached_fetch("box", g["br_url_id"])
        pbp_html = cached_fetch("pbp", g["br_url_id"])
        if not box_html or not pbp_html:
            log.warning("%s 缓存缺失，跳过", g["br_url_id"]); continue
        box_rows = parse_box_pm(box_html, g)
        roster = {}
        for r in box_rows:
            if r["br_player_id"]:
                roster.setdefault(r["team_abbr"], {})[r["br_player_id"]] = r["player_name"]
        rec = reconstruct(g, pbp_html, box_html, roster)
        # 对比
        diffs = []
        by_slug = {r["br_player_id"]: r for r in box_rows if r["br_player_id"]}
        for slug, qs in rec["pm"].items():
            total = sum(qs)
            bx = by_slug.get(slug)
            if bx is None:
                diffs.append((slug, total, "无box行")); continue
            if bx["plus_minus_total"] == total:
                agree += 1
            else:
                disagree += 1
                diffs.append((by_slug[slug]["player_name"], total, bx["plus_minus_total"]))
        all_results[g["game_id_full"]] = {"rec": rec, "by_slug": by_slug}
        if diffs:
            log.info("%s: 同意 %d / 分歧 %d %s", g["br_url_id"],
                     len(rec["pm"]) - len(diffs), len(diffs), diffs[:4])
        else:
            log.info("%s: 全部同意 (%d人)", g["br_url_id"], len(rec["pm"]))
    log.info("总同意 %d / 分歧 %d", agree, disagree)
    if args.write:
        cur = conn.cursor()
        n = 0
        for gf, res in all_results.items():
            for slug, qs in res["rec"]["pm"].items():
                bx = res["by_slug"].get(slug)
                name = bx["player_name"] if bx else slug
                cur.execute(
                    "UPDATE player_playin_plus_minus SET q1=%s,q2=%s,q3=%s,q4=%s,ot1=%s,"
                    "ot2=%s,ot3=%s,ot4=%s,plus_minus_total=%s,source='BR-PBP' "
                    "WHERE game_id_full=%s AND player_name=%s",
                    (qs[0], qs[1], qs[2], qs[3], qs[4], qs[5], qs[6], qs[7], sum(qs), gf, name))
                n += cur.rowcount
        conn.commit()
        log.info("已更新 %d 行（PBP 权威值）", n)

if __name__ == "__main__":
    main()
