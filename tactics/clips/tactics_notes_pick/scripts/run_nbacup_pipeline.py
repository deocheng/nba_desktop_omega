#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NBA杯 完整配合批量管线（上半场重扫+下半场扫+批量剪+接触表）。

门控：shot_scale_seq(6道,含记分牌ROI静态差) + refine_candidates(6道)。
两个半场均从各自文件头扫描（避开中段输入跳转在本文件产生的 h264 损坏）。
剪辑前先把各半场从 0 顺序干净重编码一次，再在干净文件上 seek 切片
（干净文件关键帧规整，避免中段跳转损坏）。

幂等：已存在的扫描JSON / 干净文件 / 片子 跳过。
用法：run_nbacup_pipeline.py
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[4]))
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

from common.nba_paths import data_file, tactics_data_file

ROOT = str(tactics_data_file("clips/tactics_notes_pick"))
SCRIPTS = os.path.join(ROOT, "scripts")
NBACUP = os.path.join(ROOT, "nbacup")
CLEAN = os.path.join(NBACUP, "_clean")
SRC_DIR = str(data_file("比赛录像/2025-26/25-26常规赛/2025.12/2025.12.17 NBA杯决赛 马刺 vs 尼克斯"))
VENV_PY = str(Path.home() / ".workbuddy/binaries/python/envs/action05/bin/python")
YOLO_CFG = "/tmp/yolo_cfg"
CONTACT_SHEET = str(tactics_data_file("clips/sas_scrimmage_pick/scripts/contact_sheet.py"))

# 已知误报（老程裁定，门控不能自动区分，须硬排除）
EXCLUDE_INTRO_FAR = (85.0, 90.0)   # cand87 入场仪式介绍球员
J_H1 = "/tmp/shot_scale_h1.json"
J_H2 = "/tmp/shot_scale_h2.json"
C_H1 = "/tmp/cands_h1.json"
C_H2 = "/tmp/cands_h2.json"


def find_src(suffix):
    for f in sorted(glob.glob(os.path.join(SRC_DIR, "*" + suffix))):
        return f
    raise FileNotFoundError("找不到 *" + suffix + " 于 " + SRC_DIR)


def run(cmd):
    print("+", cmd[:120])
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": "",
                            "YOLO_CONFIG_DIR": YOLO_CFG, "HF_HUB_OFFLINE": "1"})
    if r.returncode != 0:
        print("  STDERR:", r.stderr[-400:])
    return r


def get_h1_json():
    """上半场扫描JSON：优先 h1，回退早期全扫 full（含 sb 即可）。"""
    for p in (J_H1, "/tmp/shot_scale_full.json"):
        if os.path.exists(p):
            return p
    return None


def scan_half(src, t1, out_json):
    if os.path.exists(out_json):
        print(f"[skip] 已存在 {out_json}")
        return
    s = os.path.join(SCRIPTS, "shot_scale_seq.py")
    run(f'"{VENV_PY}" "{s}" "{src}" 0 {t1} "{out_json}" 1.0')


def refine(json_path, out_cands):
    s = os.path.join(SCRIPTS, "refine_candidates.py")
    run(f'"{VENV_PY}" "{s}" "{json_path}" "{out_cands}"')


def reencode_clean(src, out_clean):
    if os.path.exists(out_clean):
        print(f"[skip] 已存在 {out_clean}")
        return
    os.makedirs(os.path.dirname(out_clean), exist_ok=True)
    # 从 0 顺序重编码（无 -ss 跳转），关键帧规整，后续 seek 不损坏
    run(f'ffmpeg -hide_banner -loglevel error -y -i "{src}" -an '
        f'-c:v libx264 -crf 18 -preset veryfast -pix_fmt yuv420p "{out_clean}"')


def load_cands(path):
    return json.load(open(path))["cands"]


def is_excluded(c):
    far = c["far"][0]
    if EXCLUDE_INTRO_FAR[0] <= far <= EXCLUDE_INTRO_FAR[1]:
        return "intro"
    if c["far"][2] == 0:
        return "far_h0"
    return None


def cut_and_sheet(clean_src, c, tag, game_off):
    t0 = c["clip"][0]; t1 = c["clip"][1]; dur = round(t1 - t0, 1)
    name = f"{tag}_{c['far'][0]:.1f}-{c['close'][1]:.1f}"
    mp4 = os.path.join(NBACUP, name + ".mp4")
    if not os.path.exists(mp4):
        run(f'ffmpeg -hide_banner -loglevel error -y -ss {t0} -i "{clean_src}" '
            f'-t {dur} -an -c:v libx264 -crf 18 -pix_fmt yuv420p "{mp4}"')
    sheet = os.path.join(NBACUP, "sheet_" + name + ".jpg")
    if not os.path.exists(sheet):
        run(f'"{VENV_PY}" "{CONTACT_SHEET}" "{mp4}" 0.2 {dur-0.2:.1f} 0.4 '
            f'{t0+game_off:.1f} "{sheet}"')
    return name


def main():
    src_h1 = find_src("上半场.mp4")
    src_h2 = find_src("下半场.mp4")
    h1j = get_h1_json()
    if h1j is None:
        scan_half(src_h1, 1440, J_H1); h1j = J_H1
    else:
        print(f"[reuse] 上半场扫描 {h1j}")
    refine(h1j, C_H1)
    scan_half(src_h2, 1440, J_H2)
    refine(J_H2, C_H2)

    ch1 = load_cands(C_H1); ch2 = load_cands(C_H2)
    kept, excl = [], []
    for c in ch1:
        (excl if is_excluded(c) else kept).append((c, "cand", 0))
    for c in ch2:
        (excl if is_excluded(c) else kept).append((c, "h2", 1440))

    print(f"\n候选 h1={len(ch1)} h2={len(ch2)} 保留={len(kept)} 排除={len(excl)}")
    clean1 = os.path.join(CLEAN, "h1_clean.mp4")
    clean2 = os.path.join(CLEAN, "h2_clean.mp4")
    reencode_clean(src_h1, clean1)
    reencode_clean(src_h2, clean2)
    for c, tag, off in kept:
        nm = cut_and_sheet(clean1 if tag == "cand" else clean2, c, tag, off)
        print("  cut", nm)

    with open(os.path.join(ROOT, "pipeline_report.md"), "w") as f:
        f.write("# NBA杯管线报告\n\n")
        f.write(f"- 上半场候选: {len(ch1)}\n- 下半场候选: {len(ch2)}\n")
        f.write(f"- 保留(已剪+接触表): {len(kept)}\n- 排除: {len(excl)}\n\n")
        for c, tag, off in excl:
            f.write(f"- EXCLUDE {tag} far={c['far'][0]} close={c['close'][1]} "
                    f"reason={is_excluded(c)}\n")
    print("wrote pipeline_report.md")


if __name__ == "__main__":
    main()
