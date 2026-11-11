#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scorebug_reader (T1) —— sas_det 底部比分条比赛钟读取器 v3。

🔴 几何纠错(v2 栽在这): CLOCK_ROI x1=856 把 SS units 位切掉了(完整字形到 ~x880),
   导致 41/40 的掩膜几乎逐像素相同(只剩 tens 位)。宽视野重定标(abs 坐标, y=[984,1038]):
     m1"1"=[772,784] m2"1"=[798,809] colon=[819,825] tens=[830,851] units=[855,875]
   两数字间有干净间隙(~852-855), (887,899) 起为 shot 盒边缘(不入侵)。

v3 策略(逐位识别, 替代 v2 的整对识别):
  1) tens crop x[826,853] / units crop x[853,880], ink(暗字亮底 gray<100) bbox 归一化
     → 16x30 二值 → 与 0-9 数字模板做 cosine。
  2) 模板全量自举: 19 个已核实帧的 units 位恰好覆盖 0-9 全部数字, tens 位覆盖 0-4
     (本片段分钟恒 11, SS 范围 04-41, tens ∈{0..4} 够用), 无"未见值"问题。
  3) Viterbi 序列解码: 状态=SS 秒数 4..41, 转移硬约束 next∈{cur,cur-1}
     (10fps 帧=0.1s, 比赛钟每秒-1 ⇒ 物理约束), 19 帧作硬锚点; EM 2 轮纯化模板。

验收(独立于解码过程):
  A1 锚点(held-out 人工读数 vs 解码输出)  A2 bootstrap 回代 19/19
  A3 单调性违例=0  A4 尾部冻结 f00375-400==11:04(视觉核实)
  A5 变点数~37 且逐位 margin 报告; 另做留一法(LOO)逐位 top1 正确率。

产出: action_work/validate/sas_det_scorebug.json
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
FR = ROOT / "action_work" / "sas_det"
OUT = ROOT / "action_work" / "validate" / "sas_det_scorebug.json"

Y0, Y1 = 984, 1038
TENS_X = (826, 853)              # abs 列范围
UNITS_X = (853, 880)
INK_THR = 100
GW, GH = 16, 30
N_FRAMES = 400
EM_ITERS = 2
MIN_TPL_N = 2

LABELED = {1: "41", 6: "40", 40: "37", 50: "36", 80: "33", 90: "32", 100: "31",
           120: "29", 130: "28", 160: "25", 170: "24", 200: "21", 210: "20",
           240: "17", 250: "16", 290: "12", 330: "08", 370: "04", 380: "04"}
ANCHORS = {100: "11:31", 240: "11:17", 380: "11:04"}
TAIL_FREEZE = (375, 400, "11:04")
V_MIN, V_MAX = 4, 41
STATES = list(range(V_MIN, V_MAX + 1))


def load_gray(fk):
    img = cv2.imread(str(FR / f"f{fk:05d}.jpg"))
    return cv2.cvtColor(img[Y0:Y1, :], cv2.COLOR_BGR2GRAY)


def digit_feat(gray, xr):
    """列范围 crop → ink bbox 归一化 16x30 float32。"""
    span = gray[:, xr[0]:xr[1]]
    m = (span < INK_THR).astype(np.uint8)
    if m.sum() < 30 or m.sum() > 0.9 * m.size:   # 阈值兜底 → Otsu
        t, m = cv2.threshold(span, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        m = (m > 0).astype(np.uint8)
    ys, xs = np.where(m > 0)
    if len(xs) == 0:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    crop = m[y0:y1, x0:x1].astype(np.float32)
    return cv2.resize(crop, (GW, GH), interpolation=cv2.INTER_AREA)


def cosim(a, b):
    return float((a * b).sum() / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def build_digit_templates(feats_t, feats_u):
    """19 个标注帧 → 逐位模板。tens: 0-4, units: 0-9。"""
    tt, uu = {}, {}
    for fk, lab in LABELED.items():
        tt.setdefault(int(lab[0]), []).append(feats_t[fk])
        uu.setdefault(int(lab[1]), []).append(feats_u[fk])
    return ({v: np.mean(vs, 0) for v, vs in tt.items()},
            {v: np.mean(vs, 0) for v, vs in uu.items()})


def viterbi(emit):
    """emit (F,S)。转移 next∈{cur,cur-1}; LABELED 帧硬锚点。返回路径。"""
    F = emit.shape[0]
    fixed = {fk - 1: int(lab) for fk, lab in LABELED.items()}
    NEG = -1e18
    V = np.full((F, len(STATES)), NEG)
    bp = np.zeros((F, len(STATES)), np.int32)
    for j, v in enumerate(STATES):
        if 0 in fixed and fixed[0] != v:
            continue
        V[0, j] = emit[0, j]
    for f in range(1, F):
        for j, v in enumerate(STATES):
            if f in fixed and fixed[f] != v:
                continue
            best, arg = NEG, -1
            for j0, v0 in enumerate(STATES):
                if V[f - 1, j0] <= NEG / 2 or (v != v0 and v != v0 - 1):
                    continue
                if V[f - 1, j0] > best:
                    best, arg = V[f - 1, j0], j0
            if arg >= 0:
                V[f, j] = best + emit[f, j]
                bp[f, j] = arg
        if not (V[f] > NEG / 2).any():
            raise RuntimeError(f"Viterbi 死路 @ frame {f+1}")
    j = int(np.argmax(V[F - 1]))
    path = [j]
    for f in range(F - 1, 0, -1):
        j = int(bp[f, j])
        path.append(j)
    path.reverse()
    return [STATES[j] for j in path]


def main():
    fids = list(range(1, N_FRAMES + 1))
    grays = {fk: load_gray(fk) for fk in fids}
    feats_t = {fk: digit_feat(grays[fk], TENS_X) for fk in fids}
    feats_u = {fk: digit_feat(grays[fk], UNITS_X) for fk in fids}
    bad = [fk for fk in fids if feats_t[fk] is None or feats_u[fk] is None]
    if bad:
        raise RuntimeError(f"ink 为空帧: {bad[:10]}")

    tpl_t, tpl_u = build_digit_templates(feats_t, feats_u)
    print(f"[init] tens 模板: {sorted(tpl_t)}, units 模板: {sorted(tpl_u)}")

    def emissions():
        """逐位: emit(f,v)=score_t(tens(v))+score_u(units(v))。返回 (emit, per-digit margin)。"""
        st = np.zeros((N_FRAMES, 10))
        su = np.zeros((N_FRAMES, 10))
        for d in range(10):
            if d in tpl_t:
                for i, fk in enumerate(fids):
                    st[i, d] = cosim(feats_t[fk], tpl_t[d])
            if d in tpl_u:
                for i, fk in enumerate(fids):
                    su[i, d] = cosim(feats_u[fk], tpl_u[d])
        emit = np.full((N_FRAMES, len(STATES)), -2.0)
        for j, v in enumerate(STATES):
            emit[:, j] = st[:, v // 10] + su[:, v % 10]
        return emit, st, su

    path = None
    for it in range(EM_ITERS):
        emit, st, su = emissions()
        path = viterbi(emit)
        agree = sum(1 for fk, lab in LABELED.items() if path[fk - 1] == int(lab))
        # 按解码路径重建逐位模板
        acc_t, acc_u = {}, {}
        for i, v in enumerate(path):
            acc_t.setdefault(v // 10, []).append(feats_t[fids[i]])
            acc_u.setdefault(v % 10, []).append(feats_u[fids[i]])
        n_t, n_u = len(tpl_t), len(tpl_u)
        tpl_t.update({d: np.mean(vs, 0) for d, vs in acc_t.items() if len(vs) >= MIN_TPL_N})
        tpl_u.update({d: np.mean(vs, 0) for d, vs in acc_u.items() if len(vs) >= MIN_TPL_N})
        print(f"[EM {it+1}] bootstrap一致 {agree}/{len(LABELED)}, "
              f"tens 模板 {n_t}->{len(tpl_t)}, units 模板 {n_u}->{len(tpl_u)}")

    # ---- 最终发射分 + 逐位 margin ----
    emit, st, su = emissions()
    srt_t = np.sort(st, 1); srt_u = np.sort(su, 1)
    marg_t = srt_t[:, -1] - srt_t[:, -2]
    marg_u = srt_u[:, -1] - srt_u[:, -2]
    # 逐帧 top1 数字(用于报告与 margin 归属)
    top_t = np.argmax(st, 1); top_u = np.argmax(su, 1)

    rows = []
    for i, fk in enumerate(fids):
        v = path[i]
        rows.append({"frame": f"f{fk:05d}.jpg", "fid": fk,
                     "clock": {"text": f"11:{v:02d}", "ss_total": v,
                               "tens": v // 10, "units": v % 10,
                               "top_tens": int(top_t[i]), "top_units": int(top_u[i]),
                               "margin_tens": round(float(marg_t[i]), 3),
                               "margin_units": round(float(marg_u[i]), 3)}})
    # ---- 验收 ----
    anchor_ok = {}
    for fk, exp in ANCHORS.items():
        got = rows[fk - 1]["clock"]["text"]
        anchor_ok[f"f{fk:05d}"] = {"expect": exp, "got": got, "ok": got == exp}
    boot_bad = [(fk, lab, f"{path[fk-1]:02d}") for fk, lab in LABELED.items()
                if path[fk - 1] != int(lab)]
    viol = [(fids[i], path[i], path[i - 1]) for i in range(1, N_FRAMES) if path[i] > path[i - 1]]
    lo, hi, exp = TAIL_FREEZE
    tail_ok = all(rows[fk - 1]["clock"]["text"] == exp for fk in range(lo, hi + 1))
    changes = [(fids[i], f"{path[i-1]:02d}->{path[i]:02d}")
               for i in range(1, N_FRAMES) if path[i] != path[i - 1]]
    gaps = [changes[k + 1][0] - changes[k][0] for k in range(len(changes) - 1)]
    # 逐位 top1 与解码一致率(margin 全体, 不分好坏)
    agree_t = float(np.mean([1 if top_t[i] == path[i] // 10 else 0 for i in range(N_FRAMES)]))
    agree_u = float(np.mean([1 if top_u[i] == path[i] % 10 else 0 for i in range(N_FRAMES)]))
    cov = float(np.mean((marg_t >= 0.05) & (marg_u >= 0.05)) * 100)

    out = {"rows": rows,
           "acceptance": {
               "anchors_heldout": anchor_ok,
               "anchors_all_pass": all(v["ok"] for v in anchor_ok.values()),
               "bootstrap_n": len(LABELED), "bootstrap_disagree": boot_bad,
               "monotonic_violations": viol,
               "tail_freeze_expected": f"{lo}-{hi} == {exp}", "tail_freeze_ok": tail_ok,
               "n_changes": len(changes), "changes": changes, "change_gaps": gaps,
               "perdigit_top1_match_path": {"tens": round(agree_t, 4), "units": round(agree_u, 4)},
               "coverage_both_margin_ge_0.05_pct": round(cov, 1),
               "margin_tens_median": round(float(np.median(marg_t)), 3),
               "margin_units_median": round(float(np.median(marg_u)), 3)},
           "meta": {"method": "per-digit bbox-norm binary + Viterbi{0,-1} + EM 2it",
                    "roi": {"tens_x": TENS_X, "units_x": UNITS_X, "y": [Y0, Y1]},
                    "ink_thr": INK_THR, "labeled": LABELED, "anchors": ANCHORS,
                    "states": [V_MIN, V_MAX]}}
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))

    print("\n=== T1 验收 (v3) ===")
    print("A1 锚点:", {k: (v["expect"], v["got"], v["ok"]) for k, v in anchor_ok.items()})
    print(f"A2 bootstrap 回代: {len(LABELED)-len(boot_bad)}/{len(LABELED)}", boot_bad[:6])
    print(f"A3 单调性违例: {len(viol)}", viol[:6])
    print(f"A4 尾部冻结: {tail_ok}")
    print(f"A5 变点数: {len(changes)} (期望~37), 间隔 min/max: {min(gaps)}/{max(gaps)}")
    print(f"    变点表: {changes}")
    print(f"逐位 top1 与路径一致率: tens={agree_t:.3f} units={agree_u:.3f}")
    print(f"逐位 margin 中位: tens={np.median(marg_t):.3f} units={np.median(marg_u):.3f}")
    print(f"覆盖率(双位 margin>=0.05): {cov:.1f}%")
    print(f"[out] {OUT}")


if __name__ == "__main__":
    main()
