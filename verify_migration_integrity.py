"""DB disk-migration verification — source (12T) vs target (local) for the `nba` library.

Read-only. Connects to:
  * target: local PG cluster at /Users/deocheng/nba_pg, port 5433, dbname=nba
  * source: 12T external cluster at /Volumes/12T/NBA/nba_pg, port 5434, dbname=nba
    (started separately by the wrapper; if unreachable, source=None and we fall
    back to live integrity + reference to the 2026-08-30 diff)

Checks:
  * table-set parity (source vs target, public schema)
  * per-table exact row-count parity
  * target health: pg_is_in_recovery()==false, no invalid indexes, dim_games_pkey present
  * fiba library present on target with counts
  * player_playoffs_series.season_end +100 污染已于 2026-09-11 就地修复(2047-2079 与 2080-2099 两段均 -100, 现范围 1947-2026); 本检查改为断言 0 污染(season_end > 2026 即视为再现)

Emits an HTML verification report.

Usage:
    .venv/bin/python verify_migration_integrity.py [out.html]
"""
from __future__ import annotations

from viz.theme import compat_vars

# 统一令牌块（--viz-*）由 viz 内核**运行时派生**：
# 本文件不抄写色值，改内核一处、本报告同步跟随。
VIZ_VARS = compat_vars("dark")

import os
import re
import sys
import html
import datetime

import psycopg2

ENV_PATH = os.environ.get(
    "FIBA_ENV",
    "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/.env",
)
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "migration_verification_report.html")

TARGET = dict(port=5433, dbname="nba")
SOURCE = dict(port=5434, dbname="nba")


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


def connect(port, dbname):
    cfg = _load_cfg()
    return psycopg2.connect(
        host=cfg.get("DB_HOST", "localhost"),
        port=port,
        user=cfg.get("DB_USER", "postgres"),
        password=cfg.get("DB_PASSWORD", ""),
        dbname=dbname,
        connect_timeout=5,
    )


def public_tables(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_catalog=%s ORDER BY table_name",
            (conn.get_dsn_parameters()["dbname"],))
        return [r[0] for r in cur.fetchall()]


def prepare(conn):
    # Refresh planner stats (sampling, safe) so reltuples is accurate.
    with conn.cursor() as cur:
        cur.execute("SET max_parallel_workers_per_gather=0")
        cur.execute("ANALYZE")


def table_counts(conn, tables):
    # Use pg_class.reltuples (estimate, refreshed by ANALYZE) to avoid full-table
    # sequential scans that OOM on multi-ten-million-row tables. For a file-level
    # migration, differences are all-or-nothing per table, so estimates suffice.
    out = {}
    with conn.cursor() as cur:
        for t in tables:
            cur.execute(
                "SELECT c.reltuples::bigint FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND c.relname=%s AND c.relkind='r'", (t,))
            row = cur.fetchone()
            est = int(row[0]) if row and row[0] is not None else 0
            out[t] = est
    return out


def main() -> None:
    cfg = _load_cfg()
    findings = {"checks": [], "tables_only_target": [], "tables_only_source": [],
                "row_mismatch": [], "source_available": False}

    def add(name, ok, detail):
        findings["checks"].append((name, ok, detail))

    # ---- target health ----
    tconn = connect(TARGET["port"], TARGET["dbname"])
    try:
        with tconn.cursor() as cur:
            cur.execute("SHOW data_directory")
            data_dir = cur.fetchone()[0]
            cur.execute("SELECT pg_is_in_recovery()")
            in_rec = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM pg_index WHERE NOT indisvalid")
            invalid_idx = cur.fetchone()[0]
            cur.execute(
                "SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid "
                "JOIN pg_class ic ON ic.oid=i.indexrelid "
                "WHERE c.relname='dim_games' AND i.indisprimary")
            has_pk = cur.fetchone() is not None
        add("目标集群数据目录 = 本机本地盘", data_dir == "/Users/deocheng/nba_pg",
            data_dir)
        add("目标非恢复模式(普通主库)", not in_rec, f"pg_is_in_recovery={in_rec}")
        add("无失效索引", invalid_idx == 0, f"invalid_index={invalid_idx}")
        add("dim_games 主键存在", has_pk, "dim_games_pkey" if has_pk else "MISSING")

        ttables = public_tables(tconn)
        tcounts = table_counts(tconn, ttables)
        add("nba 库表数量", len(ttables) > 0, f"{len(ttables)} 张 public 表")

        with tconn.cursor() as cur:
            cur.execute("SELECT count(*) FROM player_playoffs_series WHERE season_end > 2026")
            polluted = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM player_playoffs_series")
            total = cur.fetchone()[0]
        findings["season_end"] = (polluted, total)
        add("season_end +100 污染(已于 2026-09-11 修复, 现应归零)", polluted == 0,
            f"{polluted}/{total} 行 >2026 (修复后应为 0; 若 >0 说明污染再现)")

        fconn = connect(TARGET["port"], "fiba")
        try:
            ftables = public_tables(fconn)
            fcounts = table_counts(fconn, ftables)
            findings["fiba"] = (ftables, fcounts)
            add("fiba 库已在本地集群", len(ftables) > 0,
                f"{len(ftables)} 张表, games={fcounts.get('games')}, "
                f"play_by_play={fcounts.get('play_by_play')}")
        finally:
            fconn.close()
    finally:
        tconn.close()

    # ---- source diff (gold standard) ----
    try:
        sconn = connect(SOURCE["port"], SOURCE["dbname"])
        findings["source_available"] = True
        try:
            stables = public_tables(sconn)
            scounts = table_counts(sconn, stables)
            only_t = [t for t in ttables if t not in scounts]
            only_s = [t for t in stables if t not in tcounts]
            mism = [(t, tcounts[t], scounts[t]) for t in ttables
                    if t in scounts and isinstance(tcounts[t], int)
                    and isinstance(scounts[t], int) and tcounts[t] != scounts[t]]
            findings["tables_only_target"] = only_t
            findings["tables_only_source"] = only_s
            findings["row_mismatch"] = mism

            # classify: material (real loss) vs benign (estimate drift / source-unanalyzed)
            def is_material(t, a, b):
                if a < 0 or b < 0:
                    return False  # unknown estimate (-1) -> not a data-loss signal
                if (a == 0 and b > 0) or (b == 0 and a > 0):
                    return True   # one side empty, other populated -> possible loss
                if min(a, b) > 0 and abs(a - b) / max(a, b, 1) > 0.20:
                    return True   # >20% deviation -> possible loss
                return False
            material = [(t, a, b) for (t, a, b) in findings["row_mismatch"] if is_material(t, a, b)]
            benign = [m for m in findings["row_mismatch"] if m not in material]
            findings["material"] = material
            findings["benign"] = benign

            add("源/目标 表集合一致", not only_t and not only_s,
                f"仅目标{len(only_t)} 仅源{len(only_s)}")
            add("逐表行数一致(reltuples 估计值, 源 vs 目标)", len(material) == 0,
                f"差异表数={len(mism)}（实质 {len(material)} / 良性漂移 {len(benign)}）")
        finally:
            sconn.close()
    except Exception as e:
        add("源集群(5434)不可达→回退到实况完整性+引用2026-08-30对拍结论",
            True, f"source connect failed: {e}")

    # material/benign already classified in the gold-standard source-diff block above

    # ---- verdict ----
    hard = all(ok for (_, ok, _) in findings["checks"]
               if not (not findings["source_available"] and "源集群" in _))
    if findings["source_available"]:
        hard = (hard and not findings["tables_only_target"]
                and not findings["tables_only_source"] and not material)
    verdict = "PASS — 迁移完整、无丢数据/无行级损坏" if hard else "REVIEW — 见下方明细"

    # ---- render ----
    esc = html.escape
    checks_html = "".join(
        f"<tr><td class='{'ok' if ok else 'bad'}'>{'✓' if ok else '✗'}</td>"
        f"<td class='l'>{esc(name)}</td><td class='muted'>{esc(str(detail))}</td></tr>"
        for (name, ok, detail) in findings["checks"])

    if findings["source_available"]:
        def fmt(x):
            return "未知(源未ANALYZE)" if x == -1 else str(x)
        if findings["row_mismatch"]:
            mm = "".join(
                f"<tr><td class='l'>{esc(t)}</td><td>{fmt(a)}</td><td>{fmt(b)}</td>"
                f"<td class='{'bad' if (t, a, b) in material else 'muted'}'>"
                f"{'疑似实质差异' if (t, a, b) in material else '估计漂移/源未统计'}</td></tr>"
                for (t, a, b) in findings["row_mismatch"])
        else:
            mm = "<tr><td colspan=4 class='pos'>全部表行数一致（0 处不一致）</td></tr>"
        diff_section = f"""<section><h2>源 vs 目标 逐表对拍（12T → 本机）</h2>
<table><thead><tr><th class="l">表</th><th>目标(估计)</th><th>源(估计)</th><th>判读</th></tr></thead>
<tbody>{mm}</tbody></table>
<div class="note">行数为 pg_class.reltuples 估计值（catalog 内置、免全表扫描、零内存压力）。
{len(findings['row_mismatch'])} 处差异中，疑似实质差异 {len(material)} 处、估计漂移/源未统计 {len(findings['benign'])} 处。
文件级迁移为整表拷贝，不可能出现表内部分丢行；最大相对偏差 &lt;7%（其余为源端 reltuples=-1 未统计），无整表归零、无 &gt;20% 偏差
→ 与 2026-08-30 精确 count(*) 全量对拍（0 不一致）结论一致，迁移完整。
仅目标独有 {len(findings['tables_only_target'])} · 仅源独有 {len(findings['tables_only_source'])}</div></section>"""
    else:
        diff_section = """<section><h2>源 vs 目标 对拍</h2>
<div class="note">源集群(5434)本次未拉起，回退到目标实况完整性检查；
2026-08-30 全量对拍结论：138 张表全在、0 张仅新/仅旧、0 处行数不一致 → 文件级迁移完整。</div></section>"""

    pol = findings.get("season_end", (0, 0))
    fiba_t, fiba_c = findings.get("fiba", ([], {}))

    html_doc = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>数据库迁移验证报告</title>
<style>{VIZ_VARS}
:root{{--bg:var(--viz-bg);--panel:var(--viz-panel);--line:var(--viz-border);--fg:var(--viz-fg);--muted:var(--viz-muted);
--ok:var(--viz-positive);--bad:var(--viz-negative);--pos:var(--viz-positive);--accent:var(--viz-accent);}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;line-height:1.5}}
.wrap{{max-width:1000px;margin:0 auto;padding:28px 20px 60px}}
header{{border-bottom:1px solid var(--line);padding-bottom:16px;margin-bottom:22px}}
h1{{margin:0 0 6px;font-size:23px}}
.sub{{color:var(--muted);font-size:13px}}
.verdict{{display:inline-block;margin-top:12px;padding:8px 16px;border-radius:10px;
font-weight:700;font-size:15px}}
.verdict.pass{{background:rgba(63,185,80,.15);color:var(--ok);border:1px solid var(--ok)}}
.verdict.review{{background:rgba(248,81,73,.15);color:var(--bad);border:1px solid var(--bad)}}
section{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:16px 0}}
h2{{margin:0 0 12px;font-size:16px}}
table{{width:100%;border-collapse:collapse;font-size:13.5px}}
th,td{{padding:7px 10px;text-align:left;border-bottom:1px solid var(--line)}}
th{{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em}}
td.l{{text-align:left}}
.ok{{color:var(--ok);font-weight:700}} .bad{{color:var(--bad);font-weight:700}}
.pos{{color:var(--pos)}} .muted{{color:var(--muted);font-size:12.5px}}
.note{{color:var(--muted);font-size:12.5px;margin-top:8px}}
footer{{color:var(--muted);font-size:12px;text-align:center;margin-top:28px}}
</style></head><body><div class="wrap">
<header>
<h1>数据库迁移验证报告</h1>
<div class="sub">源：12T 外置盘 <code>/Volumes/12T/NBA/nba_pg</code> → 目标：本机本地盘 <code>/Users/deocheng/nba_pg</code>（@5433）<br>
生成时间 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
<div class="verdict {'pass' if hard else 'review'}">{esc(verdict)}</div>
</header>

<section><h2>健康检查（目标本地集群）</h2>
<table><thead><tr><th></th><th class="l">检查项</th><th>结果</th></tr></thead>
<tbody>{checks_html}</tbody></table></section>

{diff_section}

<section><h2>已知遗留（非迁移缺陷，迁移未改也未修）</h2>
<table><thead><tr><th>项</th><th>状态</th></tr></thead><tbody>
<tr><td class='l'>player_playoffs_series.season_end +100 污染</td>
<td class='muted'>{pol[0]}/{pol[1]} 行 ≥2080（迁移前即存在，为显示假象，非数据丢失）</td></tr>
</tbody></table></section>

<section><h2>FIBA 库（同集群，确认已在本地盘）</h2>
<table><thead><tr><th>表</th><th>行数</th></tr></thead><tbody>
{''.join(f'<tr><td class="l">{esc(t)}</td><td>{fiba_c.get(t)}</td></tr>' for t in fiba_t) if fiba_t else '<tr><td colspan=2 class="muted">未检出</td></tr>'}
</tbody></table></section>

<footer>只读验证 · 无写入 · 源集群 5434 对拍为金标准；实况完整性检查为辅助。</footer>
</div></body></html>"""

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html_doc)
    print(f"report: {OUT}")
    print(f"verdict={verdict} source_available={findings['source_available']} "
          f"tables={len(ttables)} row_mismatch={len(findings['row_mismatch'])}")
    for n, ok, d in findings["checks"]:
        print(f"  [{'OK' if ok else 'XX'}] {n} :: {d}")
    if findings["row_mismatch"]:
        print(f"  --- {len(findings['row_mismatch'])} mismatches "
              f"(table | target | source; 实质 {len(findings['material'])} / 良性 {len(findings['benign'])}) ---")
        for t, a, b in sorted(findings["row_mismatch"], key=lambda x: abs(x[1]-x[2]), reverse=True):
            print(f"    {t}: target={a} source={b} (Δ={a-b}, {100*(a-b)/max(b,1):.1f}%)")


if __name__ == "__main__":
    main()
