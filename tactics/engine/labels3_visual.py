#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实目视标注落盘：labels3_visual.json
标注来源：verifysheet_w{1-4}_t1.jpg 真实目视（2026-09-24，图像读取已恢复）。
覆盖 manifest2_t1.json 全部 60 样本。
口径：TP=框内确为篮球（含出界球/手中被部分遮挡但轮廓可辨）；
      FP=框内为观众席/球员躯干手部/设备等非球；
      unc=疑似球但分辨率不足两可（主分析按 FP 保守计，另报宽松口径）。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
from pathlib import Path

from common.nba_paths import tactics_data_file

M = Path(str(tactics_data_file("reports/milestone_05/measure")))

# (window, frame5, label, note)
ROWS = [
    # w1: TP 9 / FP 6
    ("w1", "00010", "TP", "紫木地板上清晰的球"),
    ("w1", "00030", "TP", "运球中球在手边"),
    ("w1", "00053", "TP", "运球中球"),
    ("w1", "00091", "FP", "球员手部，无球轮廓"),
    ("w1", "00118", "FP", "观众席衣物"),
    ("w1", "00140", "TP", "球飞向观众席（出界球，确为球）"),
    ("w1", "00153", "TP", "篮下球"),
    ("w1", "00179", "FP", "球员躯干/衣服暗色区"),
    ("w1", "00199", "TP", "地板上的球"),
    ("w1", "00209", "TP", "运球中球"),
    ("w1", "00245", "FP", "球员手部"),
    ("w1", "00290", "FP", "球员腿部/袜"),
    ("w1", "00356", "TP", "球员胸前球"),
    ("w1", "00381", "TP", "篮下投篮球"),
    ("w1", "00424", "FP", "球员腿间/鞋"),
    # w2: TP 9 / unc 1 / FP 5
    ("w2", "00012", "TP", "运球球"),
    ("w2", "00029", "TP", "球"),
    ("w2", "00043", "TP", "球"),
    ("w2", "00064", "FP", "观众席（浅蓝衣观众）"),
    ("w2", "00072", "unc", "观众席中暗橙圆形，疑似出界球但无法确认"),
    ("w2", "00093", "TP", "球在手边"),
    ("w2", "00121", "TP", "球"),
    ("w2", "00162", "FP", "球员手肘/躯干"),
    ("w2", "00179", "TP", "球在手边"),
    ("w2", "00188", "TP", "球在手边"),
    ("w2", "00218", "FP", "球员衣服/手"),
    ("w2", "00256", "TP", "球（2号球员上方）"),
    ("w2", "00269", "TP", "运球球"),
    ("w2", "00296", "FP", "球员腿部"),
    ("w2", "00321", "FP", "观众席衣物"),
    # w3: TP 7 / unc 1 / FP 7
    ("w3", "00010", "TP", "球"),
    ("w3", "00051", "FP", "观众席"),
    ("w3", "00109", "TP", "球"),
    ("w3", "00184", "FP", "观众席衣物（暗橙色调）"),
    ("w3", "00224", "TP", "球"),
    ("w3", "00258", "TP", "球（猛龙logo地板）"),
    ("w3", "00287", "TP", "球清晰"),
    ("w3", "00320", "TP", "运球球"),
    ("w3", "00444", "FP", "观众席"),
    ("w3", "00493", "TP", "球在腰/手边"),
    ("w3", "00534", "FP", "球员腰部衣服"),
    ("w3", "00626", "FP", "观众席"),
    ("w3", "00664", "unc", "边线低处暗橙圆形，疑似球"),
    ("w3", "00728", "FP", "观众席"),
    ("w3", "00754", "FP", "场边设备/球架底座"),
    # w4: TP 12 / FP 3
    ("w4", "00009", "TP", "球在手边"),
    ("w4", "00013", "TP", "球"),
    ("w4", "00022", "TP", "球"),
    ("w4", "00028", "TP", "球"),
    ("w4", "00038", "TP", "球"),
    ("w4", "00050", "TP", "球"),
    ("w4", "00062", "TP", "球"),
    ("w4", "00156", "TP", "远景篮下球（小但可辨）"),
    ("w4", "00160", "FP", "远景球员身体"),
    ("w4", "00171", "FP", "观众席"),
    ("w4", "00182", "FP", "远景交界/球员头"),
    ("w4", "00189", "TP", "地板上的球"),
    ("w4", "00204", "TP", "球在手边"),
    ("w4", "00207", "TP", "球在手边"),
    ("w4", "00243", "TP", "球在手边"),
]

out = [{"window": w, "frame": f"f{n}.jpg", "label": lb, "note": nt}
       for w, n, lb, nt in ROWS]
assert len(out) == 60, len(out)
strict_tp = sum(1 for r in out if r["label"] == "TP")
unc = sum(1 for r in out if r["label"] == "unc")
fp = sum(1 for r in out if r["label"] == "FP")
(M / "labels3_visual.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
print(f"labels3_visual.json 落盘：TP={strict_tp} unc={unc} FP={fp} 总={len(out)}")
print(f"严格口径（unc=FP）: {strict_tp}/60 = {strict_tp/60*100:.1f}%")
print(f"宽松口径（unc=TP）: {strict_tp+unc}/60 = {(strict_tp+unc)/60*100:.1f}%")
for w in ("w1", "w2", "w3", "w4"):
    rs = [r for r in out if r["window"] == w]
    t = sum(1 for r in rs if r["label"] == "TP")
    u = sum(1 for r in rs if r["label"] == "unc")
    print(f"  {w}: TP {t}/15 严格 {t/15*100:.0f}%  宽松 {(t+u)/15*100:.0f}%")
