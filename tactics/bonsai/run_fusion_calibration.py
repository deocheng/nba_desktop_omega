#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全量标定：两半场 scan+refine → fuse_half → 对老程 6 张接触表(时间键)算一致率。

输出落项目目录 nbacup/_fusion/（非 /tmp，符合铁律）。
中间文件：shot_scale_h{1,2}.json / cands_h{1,2}.json / fusion_h{1,2}.json / calibration_report.md
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

ROOT = str(tactics_data_file("clips/tactics_notes_pick"))
SCRIPTS = os.path.join(ROOT, "scripts")
NBACUP = os.path.join(ROOT, "nbacup")
OUT = os.path.join(NBACUP, "_fusion")
SRC_DIR = str(data_file("比赛录像/2025-26/25-26常规赛/2025.12/2025.12.17 NBA杯决赛 马刺 vs 尼克斯"))
# 🔴 源路径必须与磁盘真实文件名一致（曾写"上半场.mp4"，实际带"NBA杯"字样→ffmpeg 抽流失败
#   → scan_half 的 if-exists:skip 复用旧缓存 → 下半场数据被上半场污染，见*_h2.POLLUTED.json）。
SRC_H1 = os.path.join(SRC_DIR, "2025.12.17 NBA杯 马刺 vs 尼克斯 上半场.mp4")
SRC_H2 = os.path.join(SRC_DIR, "2025.12.17 NBA杯 马刺 vs 尼克斯 下半场.mp4")
# 下半场源自身时长 3520s → 按自身时基 0~3520 扫（judge 在该 src 内按 clip 绝对时间 seek）
H1_SPAN = (0.0, 1440.0)
H2_SPAN = (0.0, 3520.0)
VENV_PY = str(Path.home() / ".workbuddy/binaries/python/envs/action05/bin/python")
YOLO_CFG = "/tmp/yolo_cfg"

# 老程 6 张接触表裁定（裁剪依据.md 第三部分，时间键=源窗口起点秒）
# KEEP=一次进攻/最完整标杆；EXCLUDE=吹停转场/入场仪式
LAOCHENG = {
    87.5: "EXCLUDE",    # cand87 入场仪式
    428.0: "KEEP",      # full_poss428 一次进攻
    444.5: "KEEP",      # possA_full 最完整标杆
    932.5: "KEEP",      # cand932 一次进攻(争议)
    1119.5: "KEEP",     # cand1119 一次进攻
    1244.5: "EXCLUDE",  # cand1244 裁判吹停转场
}


def run(cmd):
    print("+", cmd[:130])
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": "",
                            "YOLO_CONFIG_DIR": YOLO_CFG, "HF_HUB_OFFLINE": "1"})
    if r.returncode != 0:
        print("  STDERR:", r.stderr[-300:])
    return r


def scan_half(src, t0, t1, out_json):
    # 🔴 抽流有效性守卫：ffmpeg 抽流失败会留下 0 帧，但脚本仍写 JSON → 下游静默用坏数据。
    #   这里在 skip 缓存前先确认源可抽流（非 0 帧），杜绝再次污染。
    if os.path.exists(out_json):
        try:
            d = json.load(open(out_json))
            if len(d.get("hmax", [])) > 0:
                print(f"[skip] {out_json} (hmax={len(d['hmax'])})")
                return
            print(f"[warn] {out_json} 存在但 hmax 为空 → 重扫")
        except Exception:
            print(f"[warn] {out_json} 解析失败 → 重扫")
    s = os.path.join(SCRIPTS, "shot_scale_seq.py")
    run(f'"{VENV_PY}" "{s}" "{src}" {t0} {t1} "{out_json}" 1.0')


def refine(json_path, out_cands):
    if os.path.exists(out_cands):
        print(f"[skip] {out_cands}")
        return
    s = os.path.join(SCRIPTS, "refine_candidates.py")
    run(f'"{VENV_PY}" "{s}" "{json_path}" "{out_cands}"')


def fuse(cands_json, src, out_json):
    import fusion_judge
    kept, excl, rev = fusion_judge.fuse_half(cands_json, src, out=out_json)
    print(f"  {os.path.basename(cands_json)}: KEEP={len(kept)} "
          f"EXCLUDE={len(excl)} REVIEW={len(rev)}")
    return kept, excl, rev


def main():
    os.makedirs(OUT, exist_ok=True)
    src_h1, src_h2 = SRC_H1, SRC_H2

    # 1) 两半场扫描 + refine（下半场按自身时基 0~3520）
    scan_half(src_h1, *H1_SPAN, os.path.join(OUT, "shot_scale_h1.json"))
    refine(os.path.join(OUT, "shot_scale_h1.json"), os.path.join(OUT, "cands_h1.json"))
    scan_half(src_h2, *H2_SPAN, os.path.join(OUT, "shot_scale_h2.json"))
    refine(os.path.join(OUT, "shot_scale_h2.json"), os.path.join(OUT, "cands_h2.json"))

    # 1b) 🔴 防污染守卫：两半场 hmax/act 若逐点全等=下半场数据被上半场污染（静默坏数据）。
    #真实上下半场不可能帧对帧一致；若全等则中止，防止坏数据进入结论。
    def _pollution_check():
        try:
            a = json.load(open(os.path.join(OUT, "shot_scale_h1.json")))["hmax"]
            b = json.load(open(os.path.join(OUT, "shot_scale_h2.json")))["hmax"]
        except Exception:
            return
        n = min(len(a), len(b))
        if n and sum(1 for i in range(n) if a[i] == b[i]) == n:
            raise SystemExit("🔴 中止：H1/H2 hmax 逐点全等=下半场被上半场污染，拒绝出结论")
        eq = sum(1 for i in range(n) if a[i] == b[i]) if n else 0
        print(f"[guard] H1/H2 hmax 独立性 OK（比对前{n}点，全等{eq}点）")
    _pollution_check()

    # 2) 融合裁定（src=原半场 mp4，judge_candidate 内部按 close 段现算 sb_frac）
    k1, e1, r1 = fuse(os.path.join(OUT, "cands_h1.json"), src_h1,
                      os.path.join(OUT, "fusion_h1.json"))
    k2, e2, r2 = fuse(os.path.join(OUT, "cands_h2.json"), src_h2,
                      os.path.join(OUT, "fusion_h2.json"))

    all_c = k1 + e1 + r1 + k2 + e2 + r2
    print(f"\n全量候选={len(all_c)}  KEEP={len(k1)+len(k2)}  "
          f"EXCLUDE={len(e1)+len(e2)}  REVIEW={len(r1)+len(r2)}")

    # 3) 对老程 6 接触表（时间键）算一致率
    rep = ["# 融合判定全量标定报告\n"]
    rep.append(f"- 全量候选: {len(all_c)}（上半场 {len(k1)+len(e1)+len(r1)} / "
               f"下半场 {len(k2)+len(e2)+len(r2)}）\n")
    rep.append(f"- 自动 KEEP: {len(k1)+len(k2)} | 自动 EXCLUDE: {len(e1)+len(e2)} | "
               f"HUMAN_REVIEW: {len(r1)+len(r2)}\n")

    rep.append("\n## 对老程 6 张接触表（时间键匹配 clip[0]±4s）\n")
    rep.append("| 老程窗口 | 老程判 | 融合verdict | sb_frac | qwen_live | 一致 | 处置 |\n|---|---|---|---|---|---|---|")
    matched = 0
    kill = 0  # KEEP 被误杀为 EXCLUDE
    for t0, verdict_gt in sorted(LAOCHENG.items()):
        hit = None
        for c in all_c:
            cs = c.get("clip", [None, None])[0]
            if cs is not None and abs(cs - t0) <= 4.0:
                hit = c
                break
        if hit is None:
            rep.append(f"| {t0} | {verdict_gt} | (未匹配) | - | - | ? | 候选未过门控 |")
            continue
        matched += 1
        fv = hit["verdict"]
        sb = hit.get("sb_frac")
        ql = hit.get("qwen_live")
        # 一致定义：KEEP-KEEP / EXCLUDE-EXCLUDE 一致；REVIEW 视为"未误杀但不自动"
        if fv == verdict_gt:
            ok = "✅"
        elif verdict_gt == "KEEP" and fv == "EXCLUDE":
            ok = "❌误杀"; kill += 1
        elif verdict_gt == "EXCLUDE" and fv == "KEEP":
            ok = "❌漏排"
        else:  # REVIEW vs KEEP/EXCLUDE：未误杀，交老程
            ok = "⚠️交老程"
        action = ("自动KEEP" if fv == "KEEP" else
                  "自动EXCLUDE" if fv == "EXCLUDE" else "交老程")
        rep.append(f"| {t0} | {verdict_gt} | {fv} | {sb} | {ql} | {ok} | {action} |")

    rep.append(f"\n## 汇总\n- 匹配 {matched}/6 接触表；误杀(KEEP→EXCLUDE)={kill}；"
               f"漏排(EXCLUDE→KEEP)=见上表。")
    rep.append("\n> 说明：融合判定器当前设计=门控6 干净段(sb<0.5)自动 KEEP + 高 sb 交老程"
               "（真实全量 sb 数据显示高 sb 对 KEEP/EXCLUDE 无区分力，Qwen 把吹停错判 LIVE）。"
               "故自动 KEEP 召回有限、但零误杀；精确排除仍由老程视觉裁定。")
    rep.append("\n> 下半场候选无老程时间键金标（仅上半场 6 张接触表），故全量一致率仅覆盖上半场匹配项。")

    with open(os.path.join(OUT, "calibration_report.md"), "w") as f:
        f.write("\n".join(rep))
    print("\n".join(rep))
    print("\nwrote", os.path.join(OUT, "calibration_report.md"))


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
