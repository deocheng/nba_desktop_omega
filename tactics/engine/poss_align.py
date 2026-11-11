#!/usr/bin/env python3
"""Phase 1.5 —— 球权段切换点 vs PBP 事件：跨窗口池化置换检验。

假设（物理）
-----------
NBA 的「一次球权」以 失误/抢断/篮板/投篮命中 结束。若检测器给出的球权段是真实的，
那么**球权段切换点**在时间上应富集于 PBP 的这几类事件附近。

方法（沿用里程碑 04 已验证的池化框架，避免重复踩坑）
--------------------------------------------------
1. **切换点取段间中点**：段 A 结束于 e、段 B 起始于 s，物理换手发生在 (e, s] 之间；
   取 (e+s)/2 是无偏折中，不偏向任何一方。
2. **池化而非倒进一个池子**：每个窗口**内部**循环平移（保留该窗口切换点数量与间隔
   结构），统计量 = 各窗口之和。窗口间的时钟映射误差互不污染。
3. **两个统计量**：
   - `hits`  = |Δt| ≤ half_win 的事件数（阈值型，与 04 同口径，便于对比）；
   - `mean_dist` = 各事件到最近切换点的平均 |Δt|（**无阈值、信息量更大，主统计量**）。
4. **必须报稀释基线**：04 的教训是「动作密度稀释特异性」——本脚本显式输出
   `exp_random_hits = Σ_events (n_changes·2·hw / W)`，没有它就无法判断命中数是否真的高。

事件时刻**全部来自 pose_motion.json**（由 clock_table 读秒插值推导，零手写常量）。

用法: poss_align.py --windows w1 w2 w3 w4 [--radius 0.035] [--hyst 10]
                    [--half-win 1.5] [--n-perm 5000] [--sweep] [--out poss_align.json]
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import random
import statistics
from pathlib import Path

from common.nba_paths import tactics_data_file

AW = Path(str(tactics_data_file("action_work")))
DT_DEFAULT = 0.1  # 窗口统一 10fps；仍由 series 端点实测推导，非硬编码依赖


def pt_to_rect(bx, by, box):
    x1, y1, x2, y2 = box
    dx = max(x1 - bx, 0.0, bx - x2)
    dy = max(y1 - by, 0.0, by - y2)
    return (dx * dx + dy * dy) ** 0.5


def assign(ball_box, players, radius_frac, diag, box_pad=0.1):
    """near 模式：点到球员框矩形距离 <= radius_frac*diag 即占有权（原规则，过度分割根源）。"""
    bx = (ball_box[0] + ball_box[2]) / 2.0
    by = (ball_box[1] + ball_box[3]) / 2.0
    best, bd = None, 1e18
    for p in players:
        d = pt_to_rect(bx, by, p["bbox"])
        if d < bd:
            bd, best = d, p
    return best["track_id"] if (best is not None and bd <= radius_frac * diag) else None


def assign_held(ball_box, players, radius_frac, diag, box_pad=0.1):
    """held 模式：球心须落在（按 box_pad 扩张后的）球员框内才算「持球」。
    物理依据：球权只在球员真正持/运/护球时成立；传球/出手/松球时球在框外→None。
    副作用：25% 错检球（落在广告牌/观众/篮筐）自然不落在任何人框内→被滤除（自纠错）。"""
    if not players:
        return None
    bx = (ball_box[0] + ball_box[2]) / 2.0
    by = (ball_box[1] + ball_box[3]) / 2.0
    best, bd = None, 1e18
    for p in players:
        x1, y1, x2, y2 = p["bbox"]
        w, h = x2 - x1, y2 - y1
        x1 -= box_pad * w; x2 += box_pad * w
        y1 -= box_pad * h; y2 += box_pad * h
        if x1 <= bx <= x2 and y1 <= by <= y2:
            cx = (p["bbox"][0] + p["bbox"][2]) / 2.0
            cy = (p["bbox"][1] + p["bbox"][3]) / 2.0
            d = (cx - bx) ** 2 + (cy - by) ** 2
            if d < bd:
                bd, best = d, p
    return best["track_id"] if best is not None else None


def hysteresis(raw, k):
    if k <= 0:
        return list(raw)
    out = list(raw)
    cur, pend, pc = None, None, 0
    for i, p in enumerate(raw):
        if p == cur:
            pend, pc = None, 0
        else:
            if p == pend:
                pc += 1
            else:
                pend, pc = p, 1
            if pc >= k:
                cur, pend, pc = p, None, 0
        out[i] = cur
    return out


def rle(seq):
    segs = []
    for i, v in enumerate(seq):
        if v is None:
            continue
        if segs and segs[-1]["track_id"] == v and segs[-1]["end"] == i - 1:
            segs[-1]["end"] = i
            segs[-1]["n"] += 1
        else:
            segs.append({"track_id": int(v), "start": i, "end": i, "n": 1})
    return segs


def load_window(name, radius, hyst, diag, mode="near", box_pad=0.1, poss_dir="_poss"):
    tracks = json.loads((AW / f"{name}{poss_dir}" / "ball_tracks.json").read_text())
    pm = json.loads((AW / name / "pose_motion.json").read_text())
    series = pm["series"]
    t0 = min(s["t"] for s in series if s["t"] is not None)
    t1 = max(s["t"] for s in series if s["t"] is not None)
    n = len(tracks)
    dt = (t1 - t0) / (n - 1) if n > 1 else DT_DEFAULT

    fn = assign_held if mode == "held" else assign
    raw = []
    for fr in tracks:
        b = fr.get("ball")
        raw.append(fn(b["bbox"], fr.get("players", []), radius, diag, box_pad)
                   if (b and "bbox" in b) else None)
    sm = hysteresis(raw, hyst)
    segs = rle(sm)

    # 切换点 = 相邻两段的中点
    changes = []
    for a, b in zip(segs, segs[1:]):
        mid = (a["end"] + b["start"]) / 2.0
        changes.append(t0 + mid * dt)
    cov = sum(1 for v in sm if v is not None) / len(sm)
    return {
        "name": name, "t0": t0, "t1": t1, "W": t1 - t0, "n_frames": n,
        "events": sorted(pm["events"], key=lambda e: e["t"]),
        "segments": segs, "changes": changes,
        "coverage": cov,
    }


def nearest(changes, t):
    return min((abs(c - t) for c in changes), default=float("inf"))


def pooled(wins, hw, n_perm, seed=20260924):
    obs_hits = sum(1 for w in wins for e in w["events"]
                   if nearest(w["changes"], e["t"]) <= hw)
    ds = [nearest(w["changes"], e["t"]) for w in wins for e in w["events"]]
    obs_md = statistics.fmean(ds) if ds else float("inf")
    # 稀释基线：每次事件被随机切换点命中的期望
    exp_rand = sum(len(w["changes"]) * 2 * hw / w["W"] for w in wins
                   for _ in w["events"])
    rnd = random.Random(seed)
    null_h, null_d = [], []
    n_ev = sum(len(w["events"]) for w in wins)
    for _ in range(n_perm):
        th = td = 0.0
        for w in wins:
            W = w["W"]
            d = rnd.uniform(-W / 2, W / 2)
            cs = [(c - w["t0"] + d) % W + w["t0"] for c in w["changes"]]
            for e in w["events"]:
                dd = nearest(cs, e["t"])
                th += 1 if dd <= hw else 0
                td += dd
        null_h.append(th)
        null_d.append(td / n_ev)
    p_h = (sum(1 for x in null_h if x >= obs_hits) + 1) / (n_perm + 1)
    p_d = (sum(1 for x in null_d if x <= obs_md) + 1) / (n_perm + 1)
    return {
        "half_win": hw,
        "obs_hits": obs_hits, "n_events": n_ev,
        "n_changes": sum(len(w["changes"]) for w in wins),
        "exp_random_hits": round(exp_rand, 2),
        "null_hits_mean": round(statistics.fmean(null_h), 3),
        "null_hits_p95": round(sorted(null_h)[int(0.95 * len(null_h))], 2),
        "p_hits": round(p_h, 4),
        "obs_mean_dist": round(obs_md, 3),
        "null_mean_dist": round(statistics.fmean(null_d), 3),
        "null_dist_p05": round(sorted(null_d)[int(0.05 * len(null_d))], 3),
        "p_dist": round(p_d, 4),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", nargs="+", default=["w1", "w2", "w3", "w4"])
    ap.add_argument("--radius", type=float, default=0.035)
    ap.add_argument("--assign", choices=["near", "held"], default="near",
                    help="near=最近球员+半径(原); held=球心须在球员框内(收紧)")
    ap.add_argument("--box-pad", type=float, default=0.1,
                    help="held 模式：球员框扩张比例（容忍指尖持球）")
    ap.add_argument("--poss-dir", default="_poss",
                    help="占有权目录后缀：w{name}{poss-dir}/ball_tracks.json")
    ap.add_argument("--hyst", type=int, default=10)
    ap.add_argument("--half-win", type=float, default=1.5)
    ap.add_argument("--n-perm", type=int, default=5000)
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    diag = (1920 ** 2 + 1080 ** 2) ** 0.5
    wins = [load_window(n, a.radius, a.hyst, diag, a.assign, a.box_pad, a.poss_dir)
            for n in a.windows]
    print(f"[载入] {len(wins)} 窗口  assign={a.assign} box_pad={a.box_pad} "
          f"poss_dir={a.poss_dir}  radius={a.radius}  hyst={a.hyst}帧 "
          f"({a.hyst*0.1:.1f}s)  diag={diag:.0f}px")
    tot_sec = 0.0
    for w in wins:
        tot_sec += w["W"]
        print(f"  {w['name']:<3} t {w['t0']:.1f}–{w['t1']:.1f}s ({w['W']:.1f}s)  "
              f"球权段 {len(w['segments']):>2}  切换点 {len(w['changes']):>2}  "
              f"覆盖 {w['coverage']*100:.1f}%  PBP {len(w['events'])}")
    print(f"  合计运行时间 {tot_sec:.1f}s → NBA 真实球权量级 ≈ "
          f"{tot_sec/24:.0f}–{tot_sec/14:.0f} 次；实测球权段 "
          f"{sum(len(w['segments']) for w in wins)} 段")

    print(f"\n===== 主检验（half-win ±{a.half_win}s, hyst={a.hyst}）=====")
    res = pooled(wins, a.half_win, a.n_perm)
    for k, v in res.items():
        print(f"  {k:<18} {v}")
    v1 = "✅ 显著" if res["p_hits"] < 0.05 else "⚠️ 不显著"
    v2 = "✅ 显著" if res["p_dist"] < 0.05 else "⚠️ 不显著"
    print(f"  → 命中数 p={res['p_hits']:.4f} {v1}   "
          f"平均距离 p={res['p_dist']:.4f} {v2}")

    detail = []
    print("\n===== 逐事件明细 =====")
    for w in wins:
        print(f"-- {w['name']} --")
        for e in w["events"]:
            d = nearest(w["changes"], e["t"])
            mark = "✅" if d <= a.half_win else ("🟡" if d <= 2 * a.half_win else "·")
            print(f"  {mark} t={e['t']:>6.1f} clock={e['clock']:>6.1f} "
                  f"{e['player']:<16} {e['kind']:<12} 最近换手 {d:.2f}s")
            detail.append({"window": w["name"], "n": e["n"], "t": e["t"],
                           "clock": e["clock"], "player": e["player"],
                           "kind": e["kind"], "nearest_change_sec": round(d, 2)})

    out = {"radius": a.radius, "assign": a.assign, "box_pad": a.box_pad,
           "poss_dir": a.poss_dir, "hyst": a.hyst, "diag": round(diag, 1),
           "n_perm": a.n_perm, "windows": a.windows,
           "total_run_sec": round(tot_sec, 1),
           "n_segments": sum(len(w["segments"]) for w in wins),
           "main": res, "detail": detail, "sweep": []}

    if a.sweep:
        print("\n===== 参数扫描（box_pad × half-win × hyst）=====")
        print(f"{'pad':>5} {'hw':>5} {'hyst':>5} {'段数':>5} {'切换':>5} "
              f"{'命中':>5} {'随机基线':>8} {'p_hits':>8} {'obs_d':>7} "
              f"{'null_d':>7} {'p_dist':>8}")
        for bp in (0.0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5):
            for hw in (1.0, 1.5, 2.0, 3.0):
                for h in (3, 6, 10):
                    ws = [load_window(n, a.radius, h, diag, a.assign, bp, a.poss_dir)
                          for n in a.windows]
                    r = pooled(ws, hw, a.n_perm)
                    out["sweep"].append({"box_pad": bp, "half_win": hw, "hyst": h,
                                         "n_segments": sum(len(x["segments"]) for x in ws),
                                         **r})
                    print(f"{bp:>5} {hw:>5} {h:>5} "
                          f"{sum(len(x['segments']) for x in ws):>5} "
                          f"{r['n_changes']:>5} {r['obs_hits']:>5} "
                          f"{r['exp_random_hits']:>8} {r['p_hits']:>8} "
                          f"{r['obs_mean_dist']:>7} {r['null_mean_dist']:>7} "
                          f"{r['p_dist']:>8}")

    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False))
        print(f"\n[写] {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
