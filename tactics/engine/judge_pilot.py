#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""judge_pilot.py —— 真值库重建的**协议试点**：先证明判读可靠，再动手建库。

为什么要有这一步
----------------
A4.11 审计证明：仓库里两份同日「目视标注」冲突 14/60 且全部单向（p=1.22e-04），
而判读者（本 AI）实测准确率仅 65–81%，且**系统性过度判球**（把光头判成球）。
⇒ 直接重标只会再制造一份不可信的真值。**必须先证明协议能把准确率抬到可用水位。**

本脚本实现试点渲染协议（三面板，**从左到右 = 判读顺序**）：
  面板1（左） 宽放大 200px→300px —— 提供中间尺度：人/球/鞋的整体形状关系
  面板2（中） 紧放大  60px→300px —— 提供纹理：**球缝黑弧/十字纹**是最强的客观判据
  面板3（右） 全帧（带框）       —— 提供上下文：框在球场上、观众席、还是场边设备区
判读顺序固定为：先看面板1判形状 → 再看面板2找球缝 → 最后用面板3否决（人群/设备）。

⚠️ 拼接顺序 = [w(200px), t(60px), f(全帧)]，与上面「左→中→右」一致。
   曾把标签行写成 ("FULL FRAME","ZOOM 60px","ZOOM 200px") ⇒ 与拼接**完全反序**、三列全错位；
   已修正。**改布局后必须目视复核一次标签行。**

评分：用「两套标注一致」的 46 个样本作为代理真值（见 --source agree），
渲染时**不显示标签**，判完再比对。

用法:
  # 试点表（盲）
  python engine/judge_pilot.py render --n 27 --seed 11 --source agree --tag p1
  # 换个种子/布局再渲染一轮（重测一致性）
  python engine/judge_pilot.py render --n 27 --seed 11 --source agree --tag p2 --order-seed 77
  # 评分（读 judge/pilot_<tag>_verdicts.json）
  python engine/judge_pilot.py score --tag p1
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
AW, MS = ROOT / "action_work", ROOT / "reports/milestone_05/measure"
JD = MS / "judge"
PW = 300          # 每面板边长/宽度
ROWS_PER_SHEET = 3


def crop_pad(img, box, half):
    h, w = img.shape[:2]
    cx, cy = (box[0]+box[2])/2.0, (box[1]+box[3])/2.0
    x0, y0 = int(round(cx-half)), int(round(cy-half))
    x1, y1 = x0+2*half, y0+2*half
    px0, py0 = max(0, -x0), max(0, -y0)
    px1, py1 = max(0, x1-w), max(0, y1-h)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
    p = img[y0:y1, x0:x1]
    if px0 or py0 or px1 or py1:
        p = cv2.copyMakeBorder(p, py0, py1, px0, px1, cv2.BORDER_REPLICATE)
    return p


def zoom_panel(img, box, half, boxcolor=(0, 220, 255)):
    p = cv2.resize(crop_pad(img, box, half), (PW, PW), interpolation=cv2.INTER_LANCZOS4)
    s = PW / (2.0*half)
    cx, cy = (box[0]+box[2])/2.0, (box[1]+box[3])/2.0
    ox, oy = cx-half, cy-half
    cv2.rectangle(p, (int((box[0]-ox)*s), int((box[1]-oy)*s)),
                  (int((box[2]-ox)*s), int((box[3]-oy)*s)), boxcolor, 2)
    return p


def frame_panel(img, box, boxcolor=(0, 220, 255)):
    H, W = img.shape[:2]
    sc = PW / W
    ctx = cv2.resize(img, (PW, int(round(H*sc))), interpolation=cv2.INTER_AREA)
    cv2.rectangle(ctx, (int(box[0]*sc), int(box[1]*sc)),
                  (int(box[2]*sc), int(box[3]*sc)), boxcolor, 2)
    out = np.full((PW, PW, 3), 18, np.uint8)
    out[:ctx.shape[0], :ctx.shape[1]] = ctx
    return out


def render_row(idx, win, frame, box, img, tag_hdr):
    f = frame_panel(img, box)
    t = zoom_panel(img, box, 30)     # 60px 窗 → 300 = 5× ：看球缝
    w = zoom_panel(img, box, 100)    # 200px 窗 → 300 = 1.5× ：看整体形状
    bar = np.full((26, PW*3, 3), 28, np.uint8)
    cv2.putText(bar, tag_hdr, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (0, 220, 255), 1, cv2.LINE_AA)
    # 🔴 标签顺序必须与面板拼接顺序一致：本函数返回 [w(200px), t(60px), f(全帧)]。
    #    曾把标签写成 ("FULL FRAME","ZOOM 60px","ZOOM 200px")，与拼接顺序错位 ⇒ 三列标签全对不上。
    pan_labels = ("ZOOM 200px (shape)", "ZOOM 60px (find seam)", "FULL FRAME")
    for i, lab in enumerate(pan_labels):
        cv2.putText(bar, lab, (PW*i+6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                    (170, 175, 190), 1, cv2.LINE_AA)
    return np.concatenate([bar, np.concatenate([w, t, f], axis=1)], axis=0)


def do_render(a):
    l3 = {(r["window"], r["frame"]): r["label"] for r in json.load(open(MS/"labels3_visual.json"))}
    b2 = {(r["window"], r["frame"]): r for r in json.load(open(MS/"labels_bank.json"))}
    # ⚠️ 比对必须取 b2[k]["label"]（字典），不能拿 l3[k] 直接和 b2[k] 比 —— 恒 False（实际踩过）
    agree = sorted([k for k in l3 if k in b2 and l3[k] == b2[k]["label"]
                    and l3[k] in ("TP", "FP")])
    # 自检：审计已算出「两套标注一致」= 46（A4.11）。不等于此值说明比对逻辑又错了。
    assert len(agree) == 46, f"agree 池应为 46，实得 {len(agree)} —— 比对逻辑有误"
    pool = sorted([k for k in b2 if b2[k]["label"] in ("TP", "FP")])
    src = agree if a.source == "agree" else pool
    # 🔴 留出设计：--exclude-tag 用于独立复现轮。第一轮评分输出会把其真值全部暴露给判读者
    #    （判对的格 ⇒ 真值=我的判读；判错的格 ⇒ 逐条列出），若第二轮抽到同一批样本，
    #    就是拿已泄露的真值自评 ⇒ 第二轮不可信。必须显式排除。
    if a.exclude_tag:
        prev = json.load(open(JD / f"pilot_{a.exclude_tag}_key.json"))
        drop = {(e["window"], e["frame"]) for e in prev["key"]}
        src = [k for k in src if k not in drop]
        print(f"  留出：排除 pilot_{a.exclude_tag} 已用 {len(drop)} 格 → 剩余源池 {len(src)}")
    rng = np.random.default_rng(a.seed)
    n = min(a.n, len(src))
    idxs = list(rng.choice(len(src), n, replace=False))
    sel = [src[i] for i in idxs]
    rng.shuffle(sel)
    if a.order_seed is not None:
        np.random.default_rng(a.order_seed).shuffle(sel)

    JD.mkdir(parents=True, exist_ok=True)
    rows, keys = [], []
    for i, k in enumerate(sel):
        r = b2[k]
        img = cv2.imread(str(AW / r["window"] / r["frame"]))
        if img is None:
            print(f"  ⚠️ 读图失败 {r['window']}/{r['frame']}")
            continue
        truth = l3.get(k, r["label"])
        # 🔴 盲性：格头**只印序号**，不印 window/frame。
        #    否则判读者可能（无意识地）回忆出早前打印过的标注字典 ⇒ 测量被污染（实际踩过）。
        hdr = f"#{i:02d}"
        rows.append(render_row(i, r["window"], r["frame"], r["bbox"], img, hdr))
        keys.append({"idx": i, "window": r["window"], "frame": r["frame"],
                     "bbox": r["bbox"], "truth": truth, "bank_label": r["label"]})
    sh = []
    for c in range(0, len(rows), ROWS_PER_SHEET):
        ch = rows[c:c+ROWS_PER_SHEET]
        while len(ch) < ROWS_PER_SHEET:
            ch.append(np.full_like(rows[0], 20))
        p = JD / f"pilot_{a.tag}_sheet{c//ROWS_PER_SHEET}.jpg"
        cv2.imwrite(str(p), np.concatenate(ch, axis=0), [cv2.IMWRITE_JPEG_QUALITY, 95])
        sh.append(str(p))
    json.dump({"source": a.source, "n": len(keys), "n_pool": len(src),
               "sheets": sh, "key": keys},
              open(JD / f"pilot_{a.tag}_key.json", "w"), ensure_ascii=False, indent=1)
    print(f"试点表 {len(keys)} 格 / {len(sh)} 张（源池 {a.source}={len(src)}）")
    for s in sh:
        print(" ", s)
    print("\n判读顺序：先看左（整体形状）→ 再看中（找球缝黑弧/十字纹）→ 最后看右（上下文否决）")
    print(f"写成 {{\"0\":\"BALL\",...}} 存到 {JD}/pilot_{a.tag}_verdicts.json")


def binom_le(k, n, p):
    """P(X <= k | Binomial(n, p)) —— 精确单侧检验用，不引 scipy 依赖。"""
    return sum(math.comb(n, i) * p**i * (1-p)**(n-i) for i in range(0, k+1))


def do_score(a):
    key = json.load(open(JD / f"pilot_{a.tag}_key.json"))
    ver = json.load(open(JD / f"pilot_{a.tag}_verdicts.json"))
    lab = lambda v: "TP" if v == "BALL" else ("FP" if v == "NOT" else "unc")
    ok = bad = unc = 0
    over = under = 0
    errs = []
    for e in key["key"]:
        v = ver.get(str(e["idx"]))
        if v in (None, "UNC"):
            unc += 1
            continue
        m = lab(v)
        if m == e["truth"]:
            ok += 1
        else:
            bad += 1
            errs.append((e["idx"], e["window"], e["frame"], e["truth"], v))
            if v == "BALL":
                over += 1
            else:
                under += 1
    n = ok + bad
    print("=" * 70)
    print(f"试点评分 tag={a.tag}  源={key['source']}  共 {len(key['key'])} 格")
    print(f"  判对 {ok} / 判错 {bad} / 弃权 {unc}")
    if n:
        print(f"  ⇒ 准确率 {ok}/{n} = {ok/n*100:.1f}%   （弃权率 {unc/len(key['key'])*100:.1f}%）")
        lo = ok/n - 1.96*math.sqrt((ok/n)*(1-ok/n)/n)
        hi = ok/n + 1.96*math.sqrt((ok/n)*(1-ok/n)/n)
        print(f"     95%CI [{max(0,lo)*100:.1f}%, {min(1,hi)*100:.1f}%]")
        print(f"  偏差方向：过度判球 {over} 例 / 漏判 {under} 例")
    print("  错误明细：")
    for e in errs:
        print(f"    #{e[0]:02d} {e[1]} {e[2][1:6]}  真值={e[3]} 我判={e[4]}")
    # 精确单侧二项检验：H0 = 「判读者准确率 >= target」；p 小 ⇒ 证伪 H0
    pv = binom_le(ok, n, a.target) if n else 1.0
    if n:
        print(f"  单侧精确二项 H0: acc >= {a.target:.2f}  →  p = {pv:.4f}"
              f"   ({'❌ 拒绝 H0：准确率显著低于目标' if pv < 0.05 else '⚠️ 未拒绝 H0（样本不足或达标）'})")
    print("=" * 70)
    p = ok/n*100 if n else 0
    print(f"裁决：{'✅ 达到建库水位（≥90%）' if p >= 90 else '❌ 未达建库水位（需 ≥90%）'}"
          f"  —— 目标 90%，实测 {p:.1f}%")
    json.dump({"tag": a.tag, "source": key["source"], "n": len(key["key"]),
               "ok": ok, "bad": bad, "unc": unc,
               "acc": ok/n if n else None, "over": over, "under": under,
               "target": a.target, "binom_p_le": pv, "errs": errs},
              open(JD / f"pilot_{a.tag}_score.json", "w"), ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["render", "score"])
    ap.add_argument("--n", type=int, default=27)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--order-seed", type=int, default=None)
    ap.add_argument("--source", default="agree", choices=["agree", "pool"])
    ap.add_argument("--tag", default="p1")
    ap.add_argument("--target", type=float, default=0.90,
                    help="建库水位（精确二项检验的 H0 阈值）")
    ap.add_argument("--exclude-tag", default=None,
                    help="留出轮：排除此前某轮已用过的样本（防真值锚定）")
    a = ap.parse_args()
    (do_render if a.mode == "render" else do_score)(a)


if __name__ == "__main__":
    main()
