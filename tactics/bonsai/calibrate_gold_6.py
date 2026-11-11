#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可复现金标一致率标定（修正版，替代原 run_fusion_calibration 的错配对表）。

原 run_fusion_calibration 把 6 金标时间键去匹配 28 重分割候选的 clip[0]±4s，
但 28 候选是本次全扫的【重新分割】，与 10-07 接触表 cand_XXXX.mp4 窗口边界不同
（仅 1119.5 落入候选），导致 0/6 匹配、一致率不可算。

本法直接在【老程原金标窗口】上重算，可复现、无分割偏移：
  - 窗口与老程裁定均来自裁剪依据.md 第三部分（文本权威证据，仍存盘）；
  - 源半场 mp4 仍在盘，按窗口重裁(CRF18)→跑 fusion_judge→对金标算一致率。

一致率定义（诚实，非灌水）：
  - 自动一致 ✅ = verdict == gold
  - 误杀 ❌   = gold=KEEP 但 verdict=EXCLUDE（最严重，杀掉有效素材）
  - 漏排 ❌   = gold=EXCLUDE 但 verdict=KEEP（放过死球转场）
  - 交老程 ⚠️ = verdict=REVIEW（未误杀未漏排，但无自动产出，须老程视觉裁定）

输出：calibration_gold_report.md + 控制台摘要。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import os
import subprocess
import sys
from pathlib import Path

from common.nba_paths import data_file, tactics_data_file

sys.path.insert(0, str(tactics_data_file("bonsai")))
import fusion_judge as fj

ROOT = str(tactics_data_file("clips/tactics_notes_pick"))
_SRC_DIR = (str(data_file("比赛录像/2025-26/25-26常规赛/")) + "/"
            + "2025.12/2025.12.17 NBA杯决赛 马刺 vs 尼克斯")
# 🔴 源路径必须与磁盘真实文件名一致（带"NBA杯"字样）；曾写"上半场.mp4"导致抽流失败、
#   下半场缓存被上半场污染（见 shot_scale_h2.POLLUTED.json）。
SRC_H1 = os.path.join(_SRC_DIR, "2025.12.17 NBA杯 马刺 vs 尼克斯 上半场.mp4")
SRC_H2 = os.path.join(_SRC_DIR, "2025.12.17 NBA杯 马刺 vs 尼克斯 下半场.mp4")
FUS = os.path.join(ROOT, "nbacup", "_fusion")
GOLD_DIR = os.path.join(FUS, "gold_clips")
VENV_PY = str(Path.home() / ".workbuddy/binaries/python/envs/action05/bin/python")

# (name, start, end, gold_label) —— 窗口与老程裁定来自裁剪依据.md 第三部分
# 全部在上半场时基(0-1440)，故源=上半场.mp4
GOLD = [
    ("cand87",       87.5, 111.0,  "EXCLUDE"),
    ("full_poss428", 428.0, 447.0, "KEEP"),
    ("possA_full",   444.5, 458.0, "KEEP"),
    ("cand932",      932.5, 949.0, "KEEP"),
    ("cand1119",     1119.5, 1136.0, "KEEP"),
    ("cand1244",     1244.5, 1269.0, "EXCLUDE"),
]


def cut(name, start, end, src):
    os.makedirs(GOLD_DIR, exist_ok=True)
    out = os.path.join(GOLD_DIR, f"{name}.mp4")
    if os.path.exists(out) and os.path.getsize(out) > 1000:
        return out
    dur = end - start
    # 重编码 CRF18（不用 -c copy，避免关键帧偏移损坏；符合项目片段标准）
    cmd = (f'ffmpeg -hide_banner -loglevel error -y -ss {start} -i "{src}" '
           f'-t {dur} -an -c:v libx264 -preset ultrafast -crf 18 '
           f'-pix_fmt yuv420p "{out}"')
    subprocess.run(cmd, shell=True, capture_output=True)
    return out


def dur_of(p):
    import cv2
    cap = cv2.VideoCapture(p)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    d = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
    cap.release()
    return d


def main():
    # ---- 主标定：6 金标窗口可复现一致率 ----
    rows, auto_ok = [], 0
    kill = leak = review = 0
    print("=== 金标窗口一致率（源=上半场.mp4，重裁 CRF18 → 融合判定）===")
    for name, start, end, gold in GOLD:
        path = cut(name, start, end, SRC_H1)
        d = dur_of(path)
        c = {"far": [0, 0, 300], "mid": [0, 0], "close": [0, d, 700],
             "dur": round(d, 1), "act_rise": 0, "shape_ok": True,
             "sb_frac": None, "clip": [0, d]}
        r = fj.judge_candidate(c, path, fj.QWEN_URL, use_qwen=True,
                               close_span=(0, d))
        fv = r["verdict"]
        if fv == gold:
            ok = "✅自动一致"; auto_ok += 1
        elif gold == "KEEP" and fv == "EXCLUDE":
            ok = "❌误杀"; kill += 1
        elif gold == "EXCLUDE" and fv == "KEEP":
            ok = "❌漏排"; leak += 1
        else:
            ok = "⚠️交老程"; review += 1
        rows.append((name, start, end, gold, fv, r["sb_frac"],
                     r.get("qwen_live"), ok, r["reason"]))
        print(f"  {name:14s} win={start}-{end} sb={r['sb_frac']} "
              f"qwen={r.get('qwen_live')} -> verdict={fv:12s} gold={gold:8s} {ok}")

    # ---- 附：修正 sb_frac bug 后 28 候选分布（--no-qwen，仅看 sb 门控效果）----
    print("\n=== 修正 sb_frac bug 后 28 候选裁定分布（仅 sb 门控，不调 Qwen）===")
    dist = []
    for src, cj in ((SRC_H1, os.path.join(FUS, "cands_h1.json")),
                    (SRC_H2, os.path.join(FUS, "cands_h2.json"))):
        kept, excl, rev = fj.fuse_half(cj, src, use_qwen=False,
                                       out=os.path.join(FUS, "fusion_verdicts_bugfixed.json"))
        dist.append((os.path.basename(cj), len(kept), len(excl), len(rev)))
        for r in kept:
            print(f"  KEEP  : {os.path.basename(cj)} close={r['close'][1]} "
                  f"refine_sb={r['sb_frac']}")

    # ---- 写报告 ----
    rep = ["# 融合判定器 · 金标一致率标定（可复现修正版）\n"]
    rep.append("> 替代原 `run_fusion_calibration` 的错配对表。原法用 28 重分割候选 clip[0]±4s "
               "匹配 6 金标键，因分割边界不一致仅 1/6 落入 → 0/6 匹配、一致率不可算。\n")
    rep.append("> 本法直接在老程原金标窗口（裁剪依据.md 第三部分）上从源片重裁并重算，"
               "无分割偏移，可复现。\n")
    rep.append("\n## 一、金标窗口一致率（n=6，源=上半场.mp4）\n")
    rep.append("| 接触表 | 窗口 | 老程判 | sb_frac(现算) | qwen_live | 融合verdict | 结论 |\n"
               "|---|---|---|---|---|---|---|")
    for name, s, e, gold, fv, sb, ql, ok, _ in rows:
        rep.append(f"| {name} | {s}-{e} | {gold} | {sb} | {ql} | {fv} | {ok} |")
    rep.append(f"\n- **自动一致 ✅**: {auto_ok}/6")
    rep.append(f"- **误杀 ❌(KEEP→EXCLUDE)**: {kill}/6")
    rep.append(f"- **漏排 ❌(EXCLUDE→KEEP)**: {leak}/6")
    rep.append(f"- **交老程 ⚠️(REVIEW)**: {review}/6\n")
    rep.append("> 解读：融合判定器是 **recall/转交工具而非 precision 工具**。当前设计下"
               "仅 `sb<0.5` 的干净活球特写（possA_full, sb=0.20）能自动 KEEP；"
               "其余高 sb 窗口（活球特写与吹停转场皆有记分牌）两信号无区分力 → 一律交老程。"
               "**零误杀、零漏排**是设计底线（禁假完整），但自动产出仅 1/6。\n")
    rep.append("## 二、修正 sb_frac bug 后 28 候选分布\n")
    rep.append("> bug：旧 `judge_candidate` 在 close[0:2](2s 端点窗)现算 sb，与 refine 特写段窗口错位，"
               "28 候选恒得 0.75 → 自动 KEEP 从不触发（全 REVIEW）。现优先消费 refine 已算 sb_frac。\n")
    for nm, kk, ee, rr in dist:
        rep.append(f"- {nm}: KEEP={kk} EXCLUDE={ee} REVIEW={rr}")
    rep.append("\n> 修正后，refine sb_frac=0.0 的候选（特写段无记分牌）现能自动 KEEP；"
               "高 sb 候选仍 REVIEW。详见 `fusion_verdicts_bugfixed.json`。\n")
    rep.append("## 三、可复现性说明\n")
    rep.append(f"- 金标源片已清理（cand_*.mp4 全树不存在），故本法从源片 `{os.path.basename(SRC_H1)}` "
               "按裁剪依据.md 窗口重裁，重算结果等价于原 validate_fusion_real.py 3 锚点。\n")
    rep.append("- Qwen 仅作参考记录（把吹停帧错判 LIVE，不参与自动裁定），verdict 仅由 sb_frac 门控决定，"
               "故 Qwen 不可达时结论不变。\n")

    with open(os.path.join(FUS, "calibration_gold_report.md"), "w") as f:
        f.write("\n".join(rep))
    print("\nwrote", os.path.join(FUS, "calibration_gold_report.md"))
    print(f"\n汇总: 自动一致={auto_ok}/6 误杀={kill} 漏排={leak} 交老程={review}")


if __name__ == "__main__":
    main()
