"""WC2027 European Qualifiers — read-only HTML report from the `fiba` DB.

No DB writes. Connects to the dedicated `fiba` database (port 5433, same cluster
as the NBA library) and renders a dark-themed standalone HTML report:
  * competition header
  * team standings (W-L, PF/PA, diff) from VALID games
  * top scorers (avg pts, min 2 games)
  * team efficiency (offense/defense per game)
  * notable games (highest total, biggest margin)
  * PBP coverage note

Usage:
    .venv/bin/python fiba_wc2027_report.py [competition_id=208943] [out.html]
"""
from __future__ import annotations

import html
import json
import os
import re
import sys

import psycopg2

ENV_PATH = os.environ.get(
    "FIBA_ENV",
    "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/.env",
)
COMPETITION_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 208943
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "reports", "wc2027_european_qualifiers.html")


def _load_cfg() -> dict:
    cfg = {}
    try:
        for line in open(ENV_PATH, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^([A-Z0-9_]+)\s*=\s*(.*)$", line)
            if m:
                cfg[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return cfg


def get_conn():
    cfg = _load_cfg()
    return psycopg2.connect(
        host=cfg.get("DB_HOST", "localhost"),
        port=int(cfg.get("DB_PORT", 5433)),
        user=cfg.get("DB_USER", "postgres"),
        password=cfg.get("DB_PASSWORD", ""),
        dbname="fiba",
    )


def q(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return cols, cur.fetchall()


def pname(r):
    fn, ln, sn = r.get("first_name"), r.get("last_name"), r.get("short_name")
    if fn and ln:
        return f"{fn} {ln}"
    return sn or f"id:{r.get('player_id')}"


def main() -> None:
    conn = get_conn()
    try:
        # ---- competition meta ----
        meta_cols, meta = q(
            conn,
            "SELECT competition_code, season, official_name, gender, zone, "
            "start_date, end_date FROM competitions WHERE competition_id=%s",
            (COMPETITION_ID,))
        meta = dict(zip(meta_cols, meta[0])) if meta else {}

        played_sql = """
            SELECT team_a_org AS org, team_a_score AS pf, team_b_score AS pa FROM games
            WHERE competition_id=%s AND status='VALID'
            UNION ALL
            SELECT team_b_org, team_b_score, team_a_score FROM games
            WHERE competition_id=%s AND status='VALID'
        """

        # ---- team standings ----
        stand_cols, stand = q(conn, f"""
            WITH played AS ({played_sql})
            SELECT t.org_id, t.code, t.official_name,
                   count(*) AS games,
                   sum(CASE WHEN p.pf > p.pa THEN 1 ELSE 0 END) AS wins,
                   sum(CASE WHEN p.pf < p.pa THEN 1 ELSE 0 END) AS losses,
                   sum(p.pf) AS pf, sum(p.pa) AS pa,
                   sum(p.pf) - sum(p.pa) AS diff
            FROM played p
            JOIN teams t ON t.org_id = p.org
            GROUP BY t.org_id, t.code, t.official_name
            ORDER BY wins DESC, diff DESC, pf DESC
        """, (COMPETITION_ID, COMPETITION_ID))

        # ---- top scorers ----
        sc_cols, scorers = q(conn, """
            SELECT p.player_id, pl.first_name, pl.last_name, pl.full_name,
                   count(*) AS g,
                   round(avg(p.pts)::numeric, 1) AS avg_pts,
                   sum(p.pts) AS tot_pts,
                   round(avg(p.reb)::numeric, 1) AS avg_reb,
                   round(avg(p.ast)::numeric, 1) AS avg_ast
            FROM game_player_stats p
            JOIN games g ON g.game_id = p.game_id
                 AND g.competition_id=%s AND g.status='VALID'
            LEFT JOIN players pl ON pl.player_id = p.player_id
            GROUP BY p.player_id, pl.first_name, pl.last_name, pl.full_name
            HAVING count(*) >= 2
            ORDER BY avg_pts DESC
            LIMIT 20
        """, (COMPETITION_ID,))

        # ---- team efficiency ----
        eff_cols, eff = q(conn, f"""
            WITH played AS ({played_sql})
            SELECT t.code, t.official_name,
                   round(avg(p.pf)::numeric, 1) AS off_ppg,
                   round(avg(p.pa)::numeric, 1) AS def_ppg,
                   round((avg(p.pf) - avg(p.pa))::numeric, 1) AS diff
            FROM played p
            JOIN teams t ON t.org_id = p.org
            GROUP BY t.code, t.official_name
            ORDER BY off_ppg DESC
        """, (COMPETITION_ID, COMPETITION_ID))

        # ---- notable games ----
        hi_cols, high = q(conn, """
            SELECT g.game_id, ta.code, tb.code, g.team_a_score, g.team_b_score,
                   g.team_a_score + g.team_b_score AS total
            FROM games g
            JOIN teams ta ON ta.org_id = g.team_a_org
            JOIN teams tb ON tb.org_id = g.team_b_org
            WHERE g.competition_id=%s AND g.status='VALID'
            ORDER BY total DESC LIMIT 5
        """, (COMPETITION_ID,))
        mg_cols, margin = q(conn, """
            SELECT g.game_id, ta.code, tb.code, g.team_a_score, g.team_b_score,
                   abs(g.team_a_score - g.team_b_score) AS margin
            FROM games g
            JOIN teams ta ON ta.org_id = g.team_a_org
            JOIN teams tb ON tb.org_id = g.team_b_org
            WHERE g.competition_id=%s AND g.status='VALID'
            ORDER BY margin DESC LIMIT 5
        """, (COMPETITION_ID,))

        # ---- counts ----
        _, cnt = q(conn, """
            SELECT
              (SELECT count(*) FROM games WHERE competition_id=%s) AS total,
              (SELECT count(*) FROM games WHERE competition_id=%s AND status='VALID') AS played,
              (SELECT count(*) FROM games WHERE competition_id=%s AND status='INIT') AS upcoming,
              (SELECT count(*) FROM games WHERE competition_id=%s AND pbp_loaded) AS pbp,
              (SELECT count(DISTINCT org_id) FROM (
                 SELECT team_a_org org_id FROM games WHERE competition_id=%s
                 UNION SELECT team_b_org FROM games WHERE competition_id=%s) t) AS teams
        """, (COMPETITION_ID, COMPETITION_ID, COMPETITION_ID, COMPETITION_ID,
              COMPETITION_ID, COMPETITION_ID))
        cnt = cnt[0]
    finally:
        conn.close()

    # ---------------- render ----------------
    esc = html.escape
    total_g, played_g, upcoming_g, pbp_g, teams_n = cnt

    def team_link(code, name):
        return f"{esc(code)} <span class='muted'>{esc(str(name))}</span>"

    # standings rows
    stand_rows = ""
    for i, r in enumerate(stand, 1):
        org, code, name, games, wins, losses, pf, pa, diff = r
        diff_s = f"+{diff}" if diff >= 0 else str(diff)
        stand_rows += (
            f"<tr><td>{i}</td><td class='l'>{team_link(code,name)}</td>"
            f"<td>{games}</td><td class='w'>{wins}</td><td class='l'>{losses}</td>"
            f"<td>{pf}</td><td>{pa}</td><td class='{'pos' if diff>=0 else 'neg'}'>{diff_s}</td></tr>"
        )

    # scorers rows + bar chart data
    scorer_rows = ""
    bars = []
    max_avg = max((float(r[5]) for r in scorers), default=1) or 1
    for i, r in enumerate(scorers, 1):
        pid, fn, ln, sn, g, avg_pts, tot, avg_reb, avg_ast = r
        name = (fn and ln and f"{fn} {ln}") or sn or f"id:{pid}"
        scorer_rows += (
            f"<tr><td>{i}</td><td class='l'>{esc(str(name))}</td><td>{g}</td>"
            f"<td class='hi'>{avg_pts}</td><td>{tot}</td><td>{avg_reb}</td><td>{avg_ast}</td></tr>"
        )
        bars.append((str(name), float(avg_pts), float(avg_pts) / max_avg))

    bar_svg = _bar_chart(bars)

    eff_rows = ""
    for i, r in enumerate(eff, 1):
        code, name, off, deff, diff = r
        diff_s = f"+{diff}" if diff >= 0 else str(diff)
        eff_rows += (
            f"<tr><td>{i}</td><td class='l'>{team_link(code,name)}</td>"
            f"<td class='hi'>{off}</td><td>{deff}</td>"
            f"<td class='{'pos' if diff>=0 else 'neg'}'>{diff_s}</td></tr>"
        )

    hi_rows = "".join(
        f"<tr><td>{esc(ta)}-{esc(tb)}</td><td>{sa}-{sb}</td><td class='hi'>{tot}</td></tr>"
        for (gid, ta, tb, sa, sb, tot) in high)
    mg_rows = "".join(
        f"<tr><td>{esc(ta)}-{esc(tb)}</td><td>{sa}-{sb}</td><td class='hi'>{margin}</td></tr>"
        for (gid, ta, tb, sa, sb, margin) in margin)

    title = meta.get("official_name", f"Competition {COMPETITION_ID}")
    sub = f"{esc(str(meta.get('gender','')))} · {esc(str(meta.get('zone','')))} · Season {meta.get('season','')}"

    html_doc = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} — Report</title>
<style>
:root{{--bg:#0f1216;--panel:#171b21;--panel2:#1d232b;--line:#2a323c;
--fg:#e6edf3;--muted:#8b97a6;--accent:#4ea1ff;--pos:#3fb950;--neg:#f85149;--hi:#ffcf5c;}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;
line-height:1.5}}
.wrap{{max-width:1080px;margin:0 auto;padding:28px 20px 60px}}
header{{border-bottom:1px solid var(--line);padding-bottom:18px;margin-bottom:24px}}
h1{{margin:0 0 4px;font-size:24px}}
.sub{{color:var(--muted);font-size:14px}}
.kpis{{display:flex;flex-wrap:wrap;gap:12px;margin:18px 0 6px}}
.kpi{{background:var(--panel);border:1px solid var(--line);border-radius:10px;
padding:12px 16px;min-width:110px}}
.kpi .n{{font-size:22px;font-weight:700;color:var(--accent)}}
.kpi .l{{font-size:12px;color:var(--muted)}}
section{{background:var(--panel);border:1px solid var(--line);border-radius:12px;
padding:18px 20px;margin:18px 0}}
h2{{margin:0 0 14px;font-size:17px;font-weight:650}}
table{{width:100%;border-collapse:collapse;font-size:13.5px}}
th,td{{padding:7px 10px;text-align:center;border-bottom:1px solid var(--line)}}
th{{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em}}
td.l,th.l{{text-align:left}}
td.w{{color:var(--pos)}} td.l{{color:var(--neg)}}
.pos{{color:var(--pos)}} .neg{{color:var(--neg)}} .hi{{color:var(--hi);font-weight:700}}
.muted{{color:var(--muted);font-size:12px}}
.note{{color:var(--muted);font-size:12.5px;margin-top:10px}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
@media(max-width:780px){{.grid2{{grid-template-columns:1fr}}}}
.bars{{display:flex;flex-direction:column;gap:5px;margin-top:4px}}
.bar{{display:flex;align-items:center;gap:8px;font-size:12.5px}}
.bar .nm{{width:150px;text-align:right;color:var(--fg);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.bar .track{{flex:1;background:var(--panel2);border-radius:4px;height:16px;position:relative}}
.bar .fill{{height:100%;background:linear-gradient(90deg,#2d6fb5,var(--accent));border-radius:4px}}
.bar .v{{width:42px;color:var(--hi);font-weight:700}}
footer{{color:var(--muted);font-size:12px;text-align:center;margin-top:30px}}
</style></head><body><div class="wrap">
<header>
<h1>{esc(title)}</h1>
<div class="sub">{sub}</div>
<div class="kpis">
<div class="kpi"><div class="n">{teams_n}</div><div class="l">球队 Teams</div></div>
<div class="kpi"><div class="n">{total_g}</div><div class="l">总场次 Games</div></div>
<div class="kpi"><div class="n">{played_g}</div><div class="l">已赛 Played</div></div>
<div class="kpi"><div class="n">{upcoming_g}</div><div class="l">待赛 Upcoming</div></div>
<div class="kpi"><div class="n">{pbp_g}</div><div class="l">有 PBP</div></div>
</div>
</header>

<section><h2>球队战绩榜 Standings</h2>
<table><thead><tr><th>#</th><th class="l">球队</th><th>场</th><th>胜</th><th>负</th>
<th>得</th><th>失</th><th>净</th></tr></thead><tbody>{stand_rows}</tbody></table>
<div class="note">依据 {played_g} 场已完赛（VALID）计算；{upcoming_g} 场 INIT 为未来赛程未计入。</div>
</section>

<section><h2>得分王 Top Scorers <span class="muted">(场均，最少 2 场)</span></h2>
<div class="grid2">
<table><thead><tr><th>#</th><th class="l">球员</th><th>场</th><th>均分</th><th>总</th><th>板</th><th>助</th></tr></thead>
<tbody>{scorer_rows}</tbody></table>
<div class="bars">{bar_svg}</div>
</div>
</section>

<section><h2>球队攻防效率 Team Efficiency <span class="muted">(场均得分/失分)</span></h2>
<table><thead><tr><th>#</th><th class="l">球队</th><th>进攻</th><th>防守</th><th>净</th></tr></thead>
<tbody>{eff_rows}</tbody></table>
</section>

<section><h2>焦点战 Notable Games</h2>
<div class="grid2">
<div><div class="muted" style="margin-bottom:6px">最高总分 Highest total</div>
<table><thead><tr><th>对阵</th><th>比分</th><th>总分</th></tr></thead><tbody>{hi_rows}</tbody></table></div>
<div><div class="muted" style="margin-bottom:6px">最大分差 Biggest margin</div>
<table><thead><tr><th>对阵</th><th>比分</th><th>分差</th></tr></thead><tbody>{mg_rows}</tbody></table></div>
</div>
</section>

<footer>数据源：本地 <code>fiba</code> 数据库（FIBA Basketball World Cup 2027 European Qualifiers, competition_id={COMPETITION_ID}）。
报告由 fiba_wc2027_report.py 只读生成 · 缓存优先 / 幂等。</footer>
</div></body></html>"""

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html_doc)
    print(f"report written: {OUT}")
    print(f"  teams={teams_n} games={total_g} played={played_g} pbp={pbp_g}")
    print(f"  standings={len(stand)} scorers={len(scorers)} eff={len(eff)}")


def _bar_chart(bars):
    """bars: list of (name, value, ratio 0..1). Returns HTML divs."""
    out = []
    for name, val, ratio in bars:
        ratio = max(0.02, min(1.0, ratio))
        out.append(
            f"<div class='bar'><div class='nm' title='{html.escape(name)}'>{html.escape(name)}</div>"
            f"<div class='track'><div class='fill' style='width:{ratio*100:.1f}%'></div></div>"
            f"<div class='v'>{val}</div></div>"
        )
    return "\n".join(out)


if __name__ == "__main__":
    main()
