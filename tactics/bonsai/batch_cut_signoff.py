#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量剪「自动 KEEP 待签核片段」+ 生成接触表，供老程视觉判读。

来源：干净两半场 refine→sb门控 的自动 KEEP（fusionverdicts_{h1,h2}_noqwen.json）。
规则：同一远景起点有多条候选 → 取最长窗口（去重，避免重复剪同一进攻）。
抗性：断点续跑（mp4/sheet 已存在则跳过）。

🔴 时基警告：H1 时间=上半场文件时基；H2 时间=下半场文件时基（各自 0 起）。
   H2 的 1119.5s ≠ 金标 cand1119（那是上半场 1119.5s），二者不是同一片段。
   清单逐条标注半场，避免混淆。

产出：nbacup/_signoff/ 下 mp4 + sheet_*.jpg + 签核清单 md。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

from common.nba_paths import data_file, tactics_data_file

ROOT = str(tactics_data_file("clips/tactics_notes_pick"))
NBACUP = os.path.join(ROOT, "nbacup")
FUS = os.path.join(NBACUP, "_fusion")
OUT = os.path.join(NBACUP, "_signoff")
SRC_DIR = (str(data_file("比赛录像/2025-26/25-26常规赛/")) + "/"
           + "2025.12/2025.12.17 NBA杯决赛 马刺 vs 尼克斯")
# 🔴 源路径=磁盘真实文件名（带"NBA杯"）；写错会静默抽流失败→陈旧 ss.mp4 污染
SRC = {
    "h1": os.path.join(SRC_DIR, "2025.12.17 NBA杯 马刺 vs 尼克斯 上半场.mp4"),
    "h2": os.path.join(SRC_DIR, "2025.12.17 NBA杯 马刺 vs 尼克斯 下半场.mp4"),
}
VENV_PY = str(Path.home() / ".workbuddy/binaries/python/envs/action05/bin/python")
CONTACT_SHEET = (str(tactics_data_file("clips/")) + "/"
                 + "sas_scrimmage_pick/scripts/contact_sheet.py")

# 老程已有金标（裁剪依据.md 第三部分）→ 仅上半场时基
GOLD_H1 = {
    87.5: ("EXCLUDE", "入场仪式(cand87)"),
    444.5: ("KEEP", "possA_full 最完整标杆"),
}


def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        print("  ERR:", r.stderr[-200:])
    return r


def collect():
    """返回独立片段列表 [(half, start, end, sb, n_entries), ...]"""
    rows = []
    for h in ("h1", "h2"):
        p = os.path.join(FUS, f"fusionverdicts_{h}_noqwen.json")
        d = json.load(open(p))
        for r in d["kept"]:
            rows.append((h, r["clip"][0], r["clip"][1], r["sb_frac"]))
    uniq = {}
    for h, s, e, sb in rows:
        uniq.setdefault((h, round(s, 1)), []).append((e, sb))
    segs = []
    for (h, s), lst in uniq.items():
        e = max(x[0] for x in lst)
        segs.append((h, s, e, lst[0][1], len(lst)))
    return sorted(segs, key=lambda x: (x[0], x[1]))


def main():
    os.makedirs(OUT, exist_ok=True)
    segs = collect()
    print(f"独立片段 {len(segs)} 个（去重前条目更多）")

    made = []
    for h, s, e, sb, n in segs:
        dur = round(e - s, 1)
        if dur <= 0.2:
            print(f"  [skip] {h} {s} 窗口过短 {dur}s")
            continue
        name = f"{h}_{s:.1f}-{e:.1f}"
        mp4 = os.path.join(OUT, name + ".mp4")
        sheet = os.path.join(OUT, "sheet_" + name + ".jpg")
        # 1) 剪片段（CRF18 重编码，不用 -c copy 避免关键帧偏移）
        if not (os.path.exists(mp4) and os.path.getsize(mp4) > 10000):
            run(f'ffmpeg -hide_banner -loglevel error -y -ss {s} -i "{SRC[h]}" '
                f'-t {dur} -an -c:v libx264 -preset ultrafast -crf 18 '
                f'-pix_fmt yuv420p "{mp4}"')
        sz = os.path.getsize(mp4) / 1e6 if os.path.exists(mp4) else 0
        if sz < 0.5:
            print(f"  [fail] {name} mp4 生成失败({sz:.2f}MB)")
            continue
        # 2) 接触表（每 0.4s 一帧，标注源绝对时间）
        if not (os.path.exists(sheet) and os.path.getsize(sheet) > 1000):
            run(f'"{VENV_PY}" "{CONTACT_SHEET}" "{mp4}" 0.2 {dur - 0.2:.1f} '
                f'0.4 {s:.1f} "{sheet}"')
        made.append((h, s, e, sb, n, name, mp4, sheet))
        print(f"  ok {name}  dur={dur}s sb={sb} mp4={sz:.1f}MB "
              f"sheet={'Y' if os.path.exists(sheet) else 'N'}")

    # 3) 签核清单
    rep = ["# 自动 KEEP 待签核清单（含片段+接触表）\n",
           "> 22 个独立片段已剪片 + 生成接触表。**AI 不自行标定 KEEP/EXCLUDE**——"
           "门控6 与 Qwen 已被金标标定证伪，裁定权归老程。\n",
           "> ⚠️ 时基：h1=上半场文件时基，h2=下半场文件时基（各自 0 起）。"
           "**h2 的 1119.5s ≠ 金标 cand1119（上半场 1119.5s）**，不是同一片段。\n",
           "\n## 汇总\n",
           f"- 独立片段 {len(segs)} → 成功产出 {len(made)}\n",
           "- 已知金标 2 条（均在上半场）：87.5s=EXCLUDE(入场仪式)、444.5s=KEEP(possA标杆)\n",
           "- 其余待老程逐条判读接触表\n",
           "\n## 逐条（点开 sheet_*.jpg 判读）\n",
           "| # | 半场 | 窗口(源时基) | 时长 | refine_sb | 候选数 | 老程金标 | 片段 | 接触表 |\n",
           "|---|---|---|---|---|---|---|---|---|"]
    for i, (h, s, e, sb, n, name, mp4, sheet) in enumerate(made, 1):
        g = GOLD_H1.get(s) if h == "h1" else None
        gs = f"{g[0]}（{g[1]}）" if g else "待裁"
        rep.append(f"| {i} | {h} | {s:.1f}-{e:.1f}s | {e-s:.1f}s | {sb} | {n} | "
                   f"{gs} | {name}.mp4 | sheet_{name}.jpg |")
    rep.append("\n## 判读建议\n")
    rep.append("- 87.5s（h1）：老程已判入场仪式→**直接 EXCLUDE**（本清单保留仅作存档对照）。\n")
    rep.append("- 444.5s（h1）：老程已判 possA 最完整标杆→**KEEP**（可作完整配合模板）。\n")
    rep.append("- 其余：请看接触表判「完整配合/一次进攻/吹停转场/入场仪式/解说镜头」。\n")
    rep.append("- 接触表每格标注 `src=` 为该片段在对应半场文件中的绝对秒数。\n")
    p = os.path.join(OUT, "签核清单.md")
    open(p, "w").write("\n".join(rep))
    print("\nwrote", p)


if __name__ == "__main__":
    main()
