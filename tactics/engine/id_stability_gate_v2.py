#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""id_stability_gate_v2 —— 门 ①-A 的**相对化/窗口化**重判（承 A5.31c）。

前版（id_stability_corpus_summary.py）暴露两个口径缺陷，都是实测逼出来的，不是调线调过：
  缺陷1 绝对并发带 [8,16] = 「半场中近景」假设下的数。
         全语料 7 段未过里 6 段**场上本来就 5~7 人**（真·特写，保真率 1.00）。
  缺陷2 中位寿命 ≥30 帧是**绝对帧数**门槛，对 60 帧短段天然苛刻
         （段比门槛还短，不可能有 30 帧寿命的轨）。

本脚本用三个可证伪的物理量重判，**全部从磁盘现读，不复用任何记忆数字**：

  A. 景别代理  med_box_h = 输入框中位框高(px)。用来**独立证明**「6 段未过是真的特写」，
     而不是我嘴上说特写。若近景框高天然大 ⇒ 场上人少是正常的转播取景。
  B. 相对保真率 fidelity = 稳定化并发中位 / 输入框中位。1.000 = 每帧每个可见人恰好一 ID
     （既无碎片也无关并）。这是**稳定化自己的指标**，与景别无关。
  C. 相对寿命  life_ratio = 中位寿命 / 段长(帧)。短段不应被绝对帧数门槛卡死。
  D. 镜头窗口：**必须用像素切镜（shot_cut_detect.py），不能用 id 集切**。
     已取证：track_buffer=300 让 id 跨切镜延续（ep24_s1 f90 与 f96 的 12 个 id 里
     10 个相同），且跨切镜框高几乎不跳（111→119→116）。
     ⇒ 任何「id 重合率骤降⇒切镜」的判据都只会得到噪声
       （A5.31c 那版「68/177 段含切镜」就是这么来的，已作废）。
     窗口内**寿命只在同一窗口内计数**，否则跨切镜的 id 延续会把寿命撑长。

三套判据一起出数，不挑好看的报：
  甲 绝对(老)：           并发∈[8,16] 且 中位寿命≥30
  乙 保真(相对)：         保真率∈[0.80,1.25] 且 中位寿命≥30
  丙 窗口(全相对)：       每个帧数≥MIN_WIN 的镜头窗口，
                          窗口保真率∈[0.80,1.25] 且 窗口寿命/窗口长 ≥ LIFE_RATIO

用法:
  python3 id_stability_gate_v2.py --root action_work/norm_g3 [--json out.json] [--top 20]
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import statistics
from pathlib import Path

from common.nba_paths import tactics_data_file

SEGDIR = Path(str(tactics_data_file("action_work/tactic_notes_batch_full/segments")))
CONF_MIN = 0.40
TOPN = 12

# —— 判据常数（集中在此，避免散落；勿手写常量进别处）——
BAND_LO, BAND_HI = 8, 16          # 甲：绝对并发带（半场中近景假设）
LIFE_THR = 30                     # 甲/乙：绝对寿命门槛(帧)
FID_LO, FID_HI = 0.80, 1.25       # 乙/丙：保真率带
LIFE_RATIO = 0.25                 # 丙：寿命/段长（相对寿命）
MIN_WIN = 20                      # 丙：窗口太短不参与判定（噪声）
_CONF_DEFAULT = CONF_MIN          # argparse 的 default 要早于 main() 内的 reassignment
SHOT_THR = 0.50                   # 切镜：当前帧与前一窗 id 并集 的重合率上限
SHOT_MIN = 10                     # 切镜：最短窗口(帧)，比这更短的是噪声
SHOT_PERSIST = 5                  # 切镜：低重合需持续多少帧才算真的切了镜头


# ---------------------------------------------------------------- 输入侧
def input_frames(seg):
    """原始 ball_tracks.json，按 stabilize 口径(conf>=0.40, 每帧取框最高的 topn 个)过滤。

    返回 lists: cnt[帧] = 框数, hs[帧] = 该帧保留框的框高中位数。
    ⚠️ topn 是**景别无关**的过滤（按框高排序取前 N），
       h_min（绝对像素高度）已弃用：会把宽景里的真球员砍光（A5.31c 实测）。
    """
    p = SEGDIR / seg / "ball_tracks.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    cnt, hs = [], []
    for r in d:
        ps = [pp for pp in (r.get("players") or []) if (pp.get("conf") or 0.0) >= CONF_MIN]
        if TOPN and len(ps) > TOPN:
            ps = sorted(ps, key=lambda pp: -(pp["bbox"][3] - pp["bbox"][1]))[:TOPN]
        cnt.append(len(ps))
        hs.append(statistics.median([x["bbox"][3] - x["bbox"][1] for x in ps]) if ps else 0.0)
    return cnt, hs


def input_frames_win(cnt, lo, hi):
    return cnt[lo:hi + 1]


# ---------------------------------------------------------------- 输出侧
def out_frames(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(d, dict):
        for k in ("tracks", "records", "frames"):
            if k in d:
                d = d[k]
                break
    return d


def shots(frames, thr=SHOT_THR, min_win=SHOT_MIN, persist=SHOT_PERSIST):
    """镜头窗口切分。

    🔴 三道防呆（全部来自实测踩坑，不是拍脑袋加的）：
     1. 判据比**当前帧 id 集 与 前一窗口 id 并集**的重合率，不能只比相邻两帧：
        单帧漏检会让相邻重合率暴跌（A5.31c 已踩，首版把一段切成 8~22 个假窗口）。
     2. **持续确认 persist 帧**：真切镜后新镜头的 id 不会马上又切回去；
        冷启动段（开头几帧几乎没人）单帧判据必然误报 —— 实测 ep28_s0 被切成
        [(0,3),(4,7),(8,8),(9,10),(11,219)]，就是冷启动 + 无持续确认造成的。
     3. **最短窗 min_win**：比 min_win 还短的窗口是噪声。
    """
    idsets = []
    for r in frames:
        idsets.append({p.get("track_id") for p in (r.get("players") or [])
                       if p.get("track_id") is not None})

    def ratio(i, lo):
        """第 i 帧与 [lo, i-1] 帧 id 并集 的重合率"""
        cur = idsets[i]
        if not cur:
            return 1.0
        prev = set()
        for j in range(lo, i):
            prev |= idsets[j]
        if not prev:
            return 1.0
        return len(cur & prev) / len(cur)

    bounds = [0]
    lo = 0                       # 当前窗口起点
    run = 0                      # 连续满足"低重合"的帧数
    for i in range(1, len(idsets)):
        if not idsets[i]:
            run = 0              # 空帧不推进（漏检）
            continue
        ok = ratio(i, lo) < thr
        run = run + 1 if ok else 0
        if ok and run >= persist and (i - lo) >= min_win:
            bounds.append(i - run + 1)   # 从第一个低重合帧起算新窗口
            lo = i - run + 1
            run = 0
    bounds.append(len(frames))
    out = [(bounds[k], bounds[k + 1] - 1) for k in range(len(bounds) - 1)]
    return [w for w in out if w[1] >= w[0]]


def conc_life(frames, lo=0, hi=None):
    """(并发数列, {id: 寿命})"""
    hi = len(frames) - 1 if hi is None else hi
    conc, life = [], {}
    for r in frames[lo:hi + 1]:
        ids = {p.get("track_id") for p in (r.get("players") or [])
               if p.get("track_id") is not None}
        conc.append(len(ids))
        for t in ids:
            life[t] = life.get(t, 0) + 1
    return conc, life


def med(xs):
    return statistics.median(xs) if xs else 0.0


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="action_work/norm_g3")
    ap.add_argument("--json", default="")
    ap.add_argument("--top", type=int, default=25, help="打印未通过清单条数")
    ap.add_argument("--why", nargs="*", default=[], metavar="SEG",
                    help="对指定段做「输入为什么这么少」的三级计数诊断")
    ap.add_argument("--cuts", default="action_work/norm_calib/shotcuts.json",
                    help="shot_cut_detect.py 产出的像素切镜表")
    # 🔴 输入侧口径必须与产物口径一致。踩坑：输入侧 CONF_MIN 原本写死 0.40，
    #   拿它去评估 --conf-min 0.30 的产物 ⇒ 输入/输出错配，乙 174→151、丙 174→118
    #   全是**假数字**（保真率被人为抬高成 1.33/1.5）。A/B 必须两边都传。
    ap.add_argument("--conf-min", type=float, default=_CONF_DEFAULT)
    a = ap.parse_args()
    root = Path(a.root)

    # 🔴 必须 global：main() 里直接 `CONF_MIN = ...` 只是**局部变量**，
    #    input_frames() 是模块级函数，读的仍是全局 0.40 ⇒ A/B 口径错配。
    #    这次差点把「conf0.30 让保真率退到 85%」当成真结论发出去。
    global CONF_MIN
    CONF_MIN = a.conf_min
    cutinfo = {}
    cp = Path(a.cuts)
    if cp.exists():
        cutinfo = json.loads(cp.read_text(encoding="utf-8"))
    else:
        print(f"⚠️ 未找到切镜表 {cp}，窗口化判定将按单窗口算（=退化成段级）")

    segs = sorted(d.name for d in root.iterdir()
                  if d.is_dir() and (d / "ball_tracks.json").exists())
    rows = []
    for s in segs:
        cnt, hs = input_frames(s)
        fr = out_frames(root / s / "ball_tracks.json")
        nf = len(fr)
        conc, life = conc_life(fr)
        inp = med(cnt) if cnt else 0.0
        c = med(conc)
        ml = med(list(life.values())) if life else 0.0
        fid = c / inp if inp else 0.0

        # —— 镜头窗口：像素切镜（id 集切镜已证伪，见文件头 D）——
        cf = [c["frame"] for c in cutinfo.get(s, {}).get("cuts", [])]
        bounds = [0] + cf + [nf]
        wins = []
        for k in range(len(bounds) - 1):
            wi = bounds[k]
            wh = bounds[k + 1] - 1
            if wh >= wi:
                wins.append((wi, wh))
        # 对照：id 集切镜给出什么（只作反证输出，不参与判定）
        idwin = shots(fr)
        win_rows = []
        for lo, hi in wins:
            if hi - lo + 1 < MIN_WIN:
                continue
            wc, wl = conc_life(fr, lo, hi)
            wcnt = input_frames_win(cnt, lo, hi)
            w_inp = med(wcnt)
            w_c = med(wc)
            w_fid = w_c / w_inp if w_inp else 0.0
            _, w_life = conc_life(fr, lo, hi)
            w_ml = med(list(w_life.values())) if w_life else 0.0
            win_rows.append({"lo": lo, "hi": hi, "len": hi - lo + 1,
                             "inp": w_inp, "conc": w_c, "fid": round(w_fid, 3),
                             "life": w_ml, "lr": round(w_ml / (hi - lo + 1), 3)})

        rows.append({
            "seg": s, "n_frames": nf, "input": inp, "conc": c, "fidelity": round(fid, 3),
            "delta": round(c - inp, 1), "med_life": ml,
            "med_box_h": round(med([h for h in hs if h > 0]), 1) if any(h > 0 for h in hs) else 0.0,
            "n_win": len(wins), "win_checked": len(win_rows),
            "n_cut": len(cf), "id_win": len(idwin),
            "win_min_fid": round(min((w["fid"] for w in win_rows), default=1.0), 3),
            "win_min_lr": round(min((w["lr"] for w in win_rows), default=1.0), 3),
            "gate_abs": BAND_LO <= c <= BAND_HI and ml >= LIFE_THR,
            "gate_fid": FID_LO <= fid <= FID_HI and ml >= LIFE_THR,
            # 🔴 窗口全短 ⇒ 「不适用」而不是 FAIL。踩坑：初版写成
            #    bool(win_rows) and all(...)，导致没有可用窗口的段被判 FAIL
            #    （ep78_s1 显示保真1.00/寿命比1.0 却 FAIL，就是空窗口被当成失败）。
            "gate_win": (all(FID_LO <= w["fid"] <= FID_HI and w["lr"] >= LIFE_RATIO
                             for w in win_rows) if win_rows else None),
        })

    n = len(rows)
    ka = sum(r["gate_abs"] for r in rows)
    kb = sum(r["gate_fid"] for r in rows)
    kc = sum(1 for r in rows if r["gate_win"] is True)          # None=不适用，不计入通过
    kna = sum(1 for r in rows if r["gate_win"] is None)         # 无可用窗口的段单列
    print(f"  丙 中「无可用窗口(全窗<{MIN_WIN}帧)」不适用 {kna} 段")

    # 未过清单（按最严格的丙排序，先看最脏的）
    bad = [r for r in rows if not (r["gate_abs"] and r["gate_fid"] and r["gate_win"])]
    bad.sort(key=lambda r: (min(r["win_min_fid"], r["fidelity"]), r["med_life"]))

    hdr = (f"{'段':<11}{'帧':>5}{'输入':>6}{'并发':>6}{'保真':>6}{'寿命':>6}"
           f"{'寿命比':>7}{'框高':>7}{'镜':>3}{'窗':>3}{'最小保真':>9}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows[: a.top]:
        print(f"{r['seg']:<11}{r['n_frames']:>5}{r['input']:>6.0f}{r['conc']:>6.1f}"
              f"{r['fidelity']:>6.2f}{r['med_life']:>6.0f}"
              f"{(r['med_life'] / max(1, r['n_frames'])):>7.2f}{r['med_box_h']:>7.0f}"
              f"{r['n_win']:>3}{r['win_checked']:>3}{r['win_min_fid']:>9.2f}")

    print(f"\n段数 {n}")
    print(f"  甲 绝对并发[8,16]+寿命≥30      PASS {ka}/{n}  ({ka/max(1,n)*100:.0f}%)")
    print(f"  乙 保真率[0.80,1.25]+寿命≥30   PASS {kb}/{n}  ({kb/max(1,n)*100:.0f}%)")
    print(f"  丙 窗口级(每窗保真∈带 且 寿命比≥{LIFE_RATIO})  PASS {kc}/{n}  ({kc/max(1,n)*100:.0f}%)")
    print(f"  三口径全过 "
          f"{sum(1 for r in rows if r['gate_abs'] and r['gate_fid'] and r['gate_win'] is True)}/{n}")
    print(f"  保真率中位 {med([r['fidelity'] for r in rows]):.3f}"
          f"  Δ(并发-输入)中位 {med([r['delta'] for r in rows]):+.2f}"
          f"  寿命比中位 {med([r['med_life'] / max(1, r['n_frames']) for r in rows]):.2f}")
    nshot = sum(1 for r in rows if r["n_cut"] > 0)
    print(f"  含切镜(像素)的段数 {nshot}/{n}   —— id 集切镜给出 {sum(1 for r in rows if r['id_win'] > 1)} 段，"
          f"后者已证伪，仅作对照")
    import collections
    print("  切镜数分布(段数):", dict(sorted(
        collections.Counter(r["n_cut"] for r in rows).items())))
    print(f"\n未过清单（共 {len(bad)} 段，最严格的丙口径优先）：")
    print(f"{'段':<11}{'丙':>5}{'乙':>5}{'甲':>5}{'保真':>7}{'寿命比':>7}{'框高':>7}"
          f"{'镜':>3}  原因")
    for r in bad:
        why = []
        if r["med_life"] < LIFE_THR:
            why.append(f"寿命{r['med_life']:.0f}<{LIFE_THR}")
        if r["gate_win"] is False:
            # 注意：不显示 min(x,1.0) 封顶值 —— 会把 <0.25 的窗口寿命比显示成 1.00（误导）
            why.append(f"窗口保真{r['win_min_fid']}/寿命比{r['win_min_lr']}")
        if not r["gate_fid"]:
            why.append(f"保真{r['fidelity']}")
        c = r["conc"]
        if not (BAND_LO <= c <= BAND_HI):
            why.append(f"并发{c}∉[{BAND_LO},{BAND_HI}]")
        gw = ("N/A" if r["gate_win"] is None else ("P" if r["gate_win"] else "F"))
        print(f"{r['seg']:<11}{gw:>5}"
              f"{'P' if r['gate_fid'] else 'F':>5}{'P' if r['gate_abs'] else 'F':>5}"
              f"{r['fidelity']:>7.2f}{(r['med_life'] / max(1, r['n_frames'])):>7.2f}"
              f"{r['med_box_h']:>7.0f}{r['n_win']:>3}  " + "; ".join(why))

    # —— 景别代理的语料分布：用**独立物理量**证明"未过的 6 段是特写"，不是我嘴上说 ——
    hs = sorted(r["med_box_h"] for r in rows if r["med_box_h"] > 0)
    if hs:
        q = lambda p: hs[int(p * (len(hs) - 1))]
        print(f"\n景别代理(输入框中位框高px) 语料分位: "
              f"p5={q(0.05):.0f} p25={q(0.25):.0f} 中位={q(0.50):.0f} "
              f"p75={q(0.75):.0f} p95={q(0.95):.0f} max={hs[-1]:.0f}")
        hi_set = [r["seg"] for r in rows if r["med_box_h"] > 0 and r["med_box_h"] >= q(0.95)]
        print(f"  框高 ≥p95 的段({len(hi_set)}): {', '.join(hi_set)}")

    # —— 逐个段解释「输入框为什么这么少」——
    # 关键分歧：并发<8 到底是 (a) 镜头里本来就这几个人(特写/取景)，
    # 还是 (b) conf>=0.40 把远处小球员滤掉了(检测召回)？
    # 判定方法：对比 三级计数 —— raw(不滤conf不topn) / conf过滤 / topn12，
    # 并看**被滤掉的那些框**的 conf 与框高。
    if a.why:
        print("\n【为何输入这么少】raw=不滤conf不topn  conf=只滤conf  topn=再取框最高N"
              "   drop=被滤掉的框(conf/框高)")
        print(f"{'段':<11}{'raw':>6}{'conf':>6}{'topn':>6}{'被滤框conf中位':>13}"
              f"{'被滤框高中位':>13}{'定性':>10}")
        for s in a.why:
            p = SEGDIR / s / "ball_tracks.json"
            if not p.exists():
                print(f"{s}: 无源")
                continue
            d = json.loads(p.read_text(encoding="utf-8"))
            n_raw, n_conf, n_top, dc, dh = [], [], [], [], []
            for r in d:
                ps = r.get("players") or []
                n_raw.append(len(ps))
                keep = [x for x in ps if (x.get("conf") or 0.0) >= CONF_MIN]
                n_conf.append(len(keep))
                if TOPN and len(keep) > TOPN:
                    keep = sorted(keep, key=lambda x: -(x["bbox"][3] - x["bbox"][1]))[:TOPN]
                n_top.append(len(keep))
                for x in ps:
                    if (x.get("conf") or 0.0) >= CONF_MIN:
                        continue
                    dc.append(x.get("conf") or 0.0)
                    dh.append(x["bbox"][3] - x["bbox"][1])
            q = lambda v: med(v)
            if q(n_raw) - q(n_top) <= 0.5:
                tag = "真·人就少"
            elif q(dc) >= CONF_MIN:
                tag = "?"
            else:
                tag = "召回(低conf)"
            print(f"{s:<11}{q(n_raw):>6.0f}{q(n_conf):>6.0f}{q(n_top):>6.0f}"
                  f"{(q(dc) if dc else 0):>13.2f}{(q(dh) if dh else 0):>13.0f}{tag:>12}")

    if a.json:
        Path(a.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print("wrote", a.json)


if __name__ == "__main__":
    main()
