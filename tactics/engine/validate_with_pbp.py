#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 play-by-play 校验视觉识别结果（用户 2026-09-23 提出）。

── 为什么要做这件事 ──────────────────────────────────────────
视觉层能给出「球在哪、谁拿着、朝哪走」，但在**语义层**（这是不是一个回合、
是不是一次出手、球权怎么转的）极度脆弱：本项目的球检测器 AUC=0.522 完全不可用，
「出手」判定至今未实现。PBP 恰好补上这块：它给的是
**事件类型 + 比赛时钟 + 球员 + 投篮坐标(x,y)/距离(dist) + 当时比分**。
颗粒度粗（无空间位置），但作为**外部独立参照**极有价值。

── 第一刀就砍出了一个真实错误 ─────────────────────────────────
片段一直被我们自己标为 `game_spurs_nyk_q3`。用画面左下角比分牌读出：
    TSN | 4th | 1:08 | 24      SA 108  (BONUS)
                               TOR 104
再用 PBP 反查：season 2026 只有一场 SAS@TOR 满足「终场 110-107」——`202602250TOR`
（2026-02-25，TOR 主），且 PBP 事件 482 在 1:24 把比分刷成 104-108，
与比分牌的 108-104 精确对上。**片段实为马刺客场 @ 猛龙第 4 节，不是尼克斯第 3 节。**

── 时钟映射（关键，别用标称帧率）──────────────────────────────
比分牌时钟与片段时间的实测关系（4 个锚点全中）：
    clock_sec ≈ 83.0 - 0.9837 * (t - 204.5)
**斜率 0.9837 而非 1.0** —— 片段比实时慢约 1.6%，43 秒累积 0.7 秒误差，
不做这个校正，片段两端的 PBP 事件就会对错一格。标称 fps 是 2.0，
但源片时间基与 `fps=2` 重采样的组合产生了系统性偏差。

── 本脚本做什么 ──────────────────────────────────────────────
1. 按 game_id + period 拉 PBP（psql 子进程，免额外依赖；密码从项目 .env 读）
2. 用 clock_sec(t) 线性模型把**每一帧**映射到比赛时钟
3. 为每帧找出「刚发生的事件」与「即将发生的事件」→ 生成逐帧上下文
4. 对给定的视觉主张（claims）做 PBP 对抗性核对，输出 verdict

用法：
  validate_with_pbp.py --game-id 202602250TOR --period 4 \
      --t0 204.5 --clock0 83.0 --rate 0.9837 --n-frames 87 --fps 2.0 \
      --claims claims.json --outdir <dir>

claims.json 形如：
  [{"t": 219.5, "claim": "球在 #30 Champagnie 手中，紧邻篮筐（疑似上篮）"}]
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import os
import subprocess
import sys

from common.nba_paths import repo_file

PSQL = "/opt/homebrew/opt/postgresql@18/bin/psql"
DEFAULT_ENV = str(repo_file(".env"))


def db_password(env_path: str) -> dict:
    """从 .env 读连接参数。不打印密码。"""
    cfg = {"DB_HOST": "localhost", "DB_PORT": "5433",
           "DB_NAME": "nba", "DB_USER": "postgres", "DB_PASSWORD": ""}
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() in cfg:
                    cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


def q(cfg: dict, sql: str) -> list[dict]:
    """跑一条 SQL，返回 list[dict]。用 csv 输出避免解析歧义。"""
    env = dict(os.environ)
    env["PGPASSWORD"] = cfg["DB_PASSWORD"]
    cmd = [PSQL, "-h", cfg["DB_HOST"], "-p", cfg["DB_PORT"],
           "-U", cfg["DB_USER"], "-d", cfg["DB_NAME"],
           "-X", "-q", "--csv", "-P", "footer=off", "-c", sql]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"psql 失败: {r.stderr.strip()[:400]}")
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    if not lines:
        return []
    import csv
    import io
    return list(csv.DictReader(io.StringIO("\n".join(lines))))


def fnum(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def load_pbp(cfg: dict, nba_api_id: str, period: int) -> list[dict]:
    """拉某节的 PBP，按 eventnum 聚合（同 eventnum 可能多行描述）。

    ⚠️ 连接键陷阱（已踩）：`play_by_play.gameid` 是 **varchar**，且它等价于
    `dim_games.nba_api_id`（bigint）—— 但**不能写 `p.gameid::bigint`**：
    表内存有 `199902190SAC` 这类 BR 格式 gameid（1997–2000 约 10–12%），
    强制转换会 `invalid input syntax for type bigint` 直接报错。
    正解 = 先取到 nba_api_id，再用**文本等值**比较。
    """
    sql = f"""
    SELECT p.eventnum, p.period, p.clock, p.clock_seconds, p.event_type,
           COALESCE(p.player,'') AS player,
           COALESCE(p.result,'') AS result,
           COALESCE(p.subtype,'') AS subtype,
           COALESCE(p.dist::text,'') AS dist,
           COALESCE(p.x::text,'') AS x, COALESCE(p.y::text,'') AS y,
           COALESCE(p.h_pts::text,'') AS h_pts,
           COALESCE(p.a_pts::text,'') AS a_pts,
           COALESCE(p.description,'') AS description
    FROM play_by_play p
    WHERE p.gameid = '{nba_api_id}' AND p.period = {period}
    ORDER BY p.eventnum, p.id;
    """
    rows = q(cfg, sql)
    agg: dict[int, dict] = {}
    for r in rows:
        ev = int(r["eventnum"])
        if ev not in agg:
            agg[ev] = {
                "eventnum": ev, "clock": r["clock"],
                "clock_sec": fnum(r["clock_seconds"]),
                "player": r["player"], "event_type": r["event_type"],
                "result": r["result"], "subtype": r["subtype"],
                "dist": fnum(r["dist"]), "x": fnum(r["x"]), "y": fnum(r["y"]),
                "h_pts": fnum(r["h_pts"]), "a_pts": fnum(r["a_pts"]),
                "descriptions": [r["description"]],
            }
        else:
            a = agg[ev]
            a["descriptions"].append(r["description"])
            # 用更"有信息"的行补全字段
            for k in ("player", "event_type", "result", "dist", "x", "y",
                      "h_pts", "a_pts"):
                if not a.get(k) and r[k]:
                    a[k] = fnum(r[k]) if k in ("dist", "x", "y", "h_pts", "a_pts") else r[k]
    out = sorted(agg.values(), key=lambda e: e["eventnum"])
    # 语义主行：优先含 "makes"/"misses"/"Rebound"/"turnover" 等
    for e in out:
        ds = [d for d in e["descriptions"] if d and d.strip()]
        main = ""
        for d in ds:
            dl = d.lower()
            if any(k in dl for k in ("makes", "misses", "rebound", "turnover",
                                     "steal", "block", "foul", "violation",
                                     "timeout", "end of", "sub:")):
                main = d
                break
        e["main"] = main or (ds[0] if ds else "")
        e["is_scoring"] = e["result"] in ("Made", "Missed")
    return out


def frame_clock(t: float, t0: float, clock0: float, rate: float) -> float:
    """片段时间 → 该节剩余秒数（线性模型）。"""
    return clock0 - rate * (t - t0)


def load_clock_table(path: str) -> dict[int, float]:
    """读逐帧时钟表（frame → 剩余秒）。首选方案，优于线性模型。

    ⚠️ 实测：**不要用速率模型**。同一片段内前半段隐含帧间距 0.4884 s/帧、
    后半段 0.4949 s/帧，标称 2.0 fps 的重采样有明显抖动，单一斜率拟合
    会在片段中段产生 ±0.3s 误差，足以把相邻的 PBP 事件对错一格。
    正解 = 逐帧读比分牌时钟（比分牌是固定位置的 overlay，读它没有额外难度）。
    """
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    return {int(r["frame"]): float(r["clock_sec"]) for r in d.get("frames", [])}


def context_for(clock_sec: float, events: list[dict], window: float = 6.0):
    """给一个比赛时钟，返回「刚发生」「即将发生」及窗口内事件。"""
    prev = [e for e in events
            if e["clock_sec"] is not None and e["clock_sec"] >= clock_sec]
    nxt = [e for e in events
           if e["clock_sec"] is not None and e["clock_sec"] < clock_sec]
    just = max(prev, key=lambda e: -e["clock_sec"]) if prev else None
    soon = max(nxt, key=lambda e: e["clock_sec"]) if nxt else None
    near = [e for e in events if e["clock_sec"] is not None
            and abs(e["clock_sec"] - clock_sec) <= window]
    return just, soon, near


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-id", required=True)
    ap.add_argument("--period", type=int, required=True)
    ap.add_argument("--t0", type=float, required=True, help="首帧片段时间")
    ap.add_argument("--clock0", type=float, required=True,
                    help="首帧(t0)对应的该节剩余秒数")
    ap.add_argument("--rate", type=float, default=1.0,
                    help="时钟相对片段时间的速率（仅在无 --clock-table 时用）")
    ap.add_argument("--clock-table", default=None,
                    help="逐帧时钟表 json（首选；见 load_clock_table 的说明）")
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--n-frames", type=int, default=87)
    ap.add_argument("--window", type=float, default=6.0)
    ap.add_argument("--claims", default=None, help="claims.json")
    ap.add_argument("--env-file", default=DEFAULT_ENV)
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()

    cfg = db_password(a.env_file)

    # 比赛基本信息（同时取出 PBP 连接用的 nba_api_id）
    gm = q(cfg, f"""SELECT game_id, game_date, season, season_type,
                           home_team_abbr, away_team_abbr, home_pts, away_pts,
                           nba_api_id::text AS nba_api_id
                    FROM dim_games WHERE game_id='{a.game_id}';""")
    if not gm:
        print(f"❌ dim_games 无此比赛: {a.game_id}")
        sys.exit(1)
    gm = gm[0]
    events = load_pbp(cfg, gm["nba_api_id"], a.period)
    if not events:
        print(f"❌ 无 PBP：{a.game_id} (nba_api_id={gm['nba_api_id']}) period={a.period}")
        sys.exit(1)

    print("=" * 78)
    print(f"比赛 {gm['game_id']}  {gm['game_date']}  {gm['season_type']}  "
          f"{gm['away_team_abbr']} @ {gm['home_team_abbr']}  "
          f"终场 {gm['away_team_abbr']} {gm['away_pts']} - {gm['home_pts']} {gm['home_team_abbr']}")
    print(f"第 {a.period} 节 PBP 事件 {len(events)} 条  |  "
          f"时钟模型 clock_sec = {a.clock0} - {a.rate}*(t - {a.t0})")
    print("=" * 78)

    clock_table = load_clock_table(a.clock_table)
    if clock_table:
        print(f"时钟来源: 逐帧表 {a.clock_table}（{len(clock_table)} 帧）")
    else:
        print(f"时钟来源: 线性模型 clock_sec = {a.clock0} - {a.rate}*(t - {a.t0})"
              f"  ⚠️ 建议改用 --clock-table（见 load_clock_table 注释）")
    print("=" * 78)

    # 逐帧映射
    frames = []
    for i in range(a.n_frames):
        fi = i + 1
        t = round(a.t0 + i / a.fps, 3)
        if fi in clock_table:
            cs = clock_table[fi]
            src = "clock_table"
        else:
            cs = frame_clock(t, a.t0, a.clock0, a.rate)
            src = "linear_model"
        just, soon, near = context_for(cs, events, a.window)
        frames.append({
            "frame": fi, "t": t, "clock_sec": cs, "clock_src": src,
            "clock_disp": (f"{int(cs // 60)}:{cs % 60:04.1f}" if cs < 60
                           else f"{int(cs // 60)}:{int(cs % 60):02d}"),
            "just": ({"eventnum": just["eventnum"], "clock_sec": just["clock_sec"],
                      "main": just["main"], "h_pts": just["h_pts"],
                      "a_pts": just["a_pts"]} if just else None),
            "soon": ({"eventnum": soon["eventnum"], "clock_sec": soon["clock_sec"],
                      "main": soon["main"], "h_pts": soon["h_pts"],
                      "a_pts": soon["a_pts"]} if soon else None),
            "n_near": len(near),
        })

    # ── 帧间距体检（替代此前那个"测自己舍入误差"的假检测器）──────────
    # 只能给"区段均值"，因为 MM:SS 区的显示分辨率是 1s，
    # 逐帧差值被量化吃掉，只有 <60s 区（0.1s 分辨率）才有意义。
    def spacing(lo, hi):
        v = [round(frames[i - 1]["clock_sec"] - frames[i]["clock_sec"], 3)
             for i in range(lo, hi) if i < len(frames)]
        if not v:
            return None
        m = sum(v) / len(v)
        var = sum((x - m) ** 2 for x in v) / len(v)
        return {"n": len(v), "mean": round(m, 4), "std": round(var ** 0.5, 4)}

    segments = []
    for lo, hi, label in ((1, 44, "≥60s 区（对秒显示，分辨率 1s）"),
                          (48, len(frames), "<60s 区（十分位，分辨率 0.1s）")):
        s = spacing(lo, hi)
        if s:
            s["range"] = [lo, hi]
            s["label"] = label
            segments.append(s)

    # 主张核对
    verdicts = []
    if a.claims and os.path.exists(a.claims):
        with open(a.claims, "r", encoding="utf-8") as f:
            claims = json.load(f)
        for c in claims:
            fi = int(round((c["t"] - a.t0) * a.fps)) + 1
            if fi in clock_table:
                cs = clock_table[fi]
            else:
                cs = frame_clock(c["t"], a.t0, a.clock0, a.rate)
            just, soon, near = context_for(cs, events, c.get("window", a.window))
            scoring_near = [e for e in near if e["is_scoring"]]
            verdicts.append({
                "t": c["t"], "claim": c["claim"],
                "clock_sec": round(cs, 1),
                "just": just, "soon": soon,
                "scoring_near": scoring_near,
            })
            print(f"\n── 主张核对  t={c['t']}s  (第{a.period}节 剩 {cs:.1f}s) ──")
            print(f"   视觉主张: {c['claim']}")
            if just:
                print(f"   刚发生  [{just['clock']} / {just['clock_sec']:.1f}s] "
                      f"{just['player']:<16} {just['event_type']:<12} "
                      f"{just['main'][:56]}")
            if soon:
                print(f"   即将发生 [{soon['clock']} / {soon['clock_sec']:.1f}s] "
                      f"{soon['player']:<16} {soon['event_type']:<12} "
                      f"{soon['main'][:56]}")
            if scoring_near:
                print("   窗口内投篮:")
                for e in scoring_near:
                    print(f"     {e['clock']:>11} {e['player']:<16} "
                          f"{e['result']:<7} dist={e['dist']}ft "
                          f"xy=({e['x']},{e['y']})  {e['main'][:48]}")

    # 累计比分轨迹（用于与画面比分牌对账）
    traj = []
    for e in events:
        if e["h_pts"] or e["a_pts"]:
            traj.append({"clock_sec": e["clock_sec"], "h": e["h_pts"],
                         "a": e["a_pts"], "main": e["main"][:60]})

    os.makedirs(a.outdir, exist_ok=True)
    out = {
        "game": gm, "period": a.period,
        "clock_source": ("clock_table" if clock_table else "linear_model"),
        "clock_model": {"t0": a.t0, "clock0": a.clock0, "rate": a.rate,
                        "fps": a.fps, "n_frames": a.n_frames},
        "n_events": len(events),
        "events": events,
        "frames": frames,
        "frame_spacing": segments,
        "verdicts": verdicts,
        "score_trajectory": traj,
    }
    p = os.path.join(a.outdir, "pbp_validation.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print("\n" + "=" * 78)
    print("逐帧时钟（抽样）")
    for fr in frames[::12]:
        j = fr["just"]
        print(f"  f{fr['frame']:03d}  t={fr['t']:>6.1f}  剩 {fr['clock_sec']:>5.1f}s "
              f"({fr['clock_disp']:>7})  刚发生: "
              f"{(j['main'][:52] if j else '-'):<54}")
    print("\n帧间距体检（隐含 s/帧）")
    for s in segments:
        print(f"  {s['label']:<26} {s['mean']:.4f} s/帧  std={s['std']:.4f}  n={s['n']}")
    if len(segments) == 2 and abs(segments[0]["mean"] - segments[1]["mean"]) > 0.003:
        print("  ⚠️ 两段间距不一致 → 标称 2.0fps 的重采样有抖动，"
              "**不要用线性速率模型**，以逐帧时钟表为准")
    print(f"[out] {p}")


if __name__ == "__main__":
    main()
