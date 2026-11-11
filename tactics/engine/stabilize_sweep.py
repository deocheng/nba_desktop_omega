#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stabilize_sweep —— 带**参数留痕**的 stabilize_tracks_v2 跨段扫描。

存在理由（实证）：现有 sas_det_poss_tile_stab / _stab2 / _stab3 三个产物目录里
只有 ball_tracks.json，**没有参数留痕**，日志亦未记录 ⇒ 其中最好的
「85 ID / 中位寿命 35 帧」当前**无法复现**，因此不能当作"ID 稳定化已解决"的证据。
（铁律：数字全从磁盘现读、禁假完整。）

本脚本：跑参数网格 → 每个配置落盘 (参数 + 审计指标) 到 <out>/sweep_result.json，
使任何一条成绩都可被第三方复现与跨段迁移验证。

用法:
  python3 stabilize_sweep.py --seg sas_det --src sas_det_poss_tile \
      --out action_work/stab_sweep_sas_det --grid default
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
ACT = ROOT / "action_work"
PY = str(Path.home() / ".workbuddy/binaries/python/envs/action05/bin/python")

# 参数网格：全部显式写出，不依赖任何"上次跑的那套"
GRIDS = {
    "default": [{}],
    "app": [
        {"app-thresh": "0.15", "w-app": "1.0"},
        {"app-thresh": "0.25", "w-app": "1.0"},
        {"app-thresh": "0.35", "w-app": "1.0"},
        {"app-thresh": "0.25", "w-app": "1.5"},
    ],
    "buf": [
        {"track-buffer": "60", "zombie-buffer": "120"},
        {"track-buffer": "90", "zombie-buffer": "180"},
        {"track-buffer": "150", "zombie-buffer": "300"},
    ],
    "gate": [
        {"gate": "0.10"}, {"gate": "0.14"}, {"gate": "0.20"}, {"gate": "0.28"},
    ],
    # rescue：专治「检测器漏检型」段（每帧框数偏低、track 出生帧右偏）。
    # 思路：track_buffer 拉到 300 几乎不丢 track + 放宽脚点/尺寸门，让漏检恢复后能续接。
    "rescue": [
        {"track-buffer": "300", "zombie-buffer": "600"},
        {"track-buffer": "300", "zombie-buffer": "600", "gate": "0.30"},
        {"track-buffer": "300", "zombie-buffer": "600", "gate": "0.30", "app-thresh": "0.10"},
        {"track-buffer": "300", "zombie-buffer": "600", "gate": "0.30",
         "app-thresh": "0.10", "w-app": "0.5"},
        {"track-buffer": "300", "zombie-buffer": "600", "size-gate": "1.40"},
        {"track-buffer": "300", "zombie-buffer": "600", "gate": "0.30", "new-conf": "0.10"},
    ],
}


def frames_dir(seg):
    cands = [ACT / "tactic_notes_batch_full" / "segments" / seg / "frames",
             ACT / seg / "frames", ACT / seg]
    for c in cands:
        if c.exists() and any(c.glob("*.jpg")):
            return c
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", required=True)
    ap.add_argument("--src", required=True, help="源产物目录名(含 ball_tracks.json)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--grid", default="default", choices=list(GRIDS))
    ap.add_argument("--extra", default="", help="附加参数字符串，如 '--pose-masked'")
    a = ap.parse_args()

    src = ACT / a.src / "ball_tracks.json"
    if not src.exists():
        print("ERR 源不存在:", src)
        return 1
    imgdir = frames_dir(a.seg)
    if imgdir is None:
        print("ERR 找不到帧目录 for seg:", a.seg)
        return 1

    outroot = Path(a.out)
    if not outroot.exists():
        outroot.mkdir(parents=True)

    rows = []
    for i, cfg in enumerate(GRIDS[a.grid]):
        tag = f"g{i}_" + "_".join(f"{k}{v}" for k, v in cfg.items()) if cfg else f"g{i}_default"
        od = outroot / tag
        cmd = [PY, str(ROOT / "engine" / "stabilize_tracks_v2.py"),
               str(src), str(imgdir), "--out", str(od)]
        for k, v in cfg.items():
            cmd += [f"--{k}", v]
        if a.extra:
            cmd += a.extra.split()
        t0 = time.time()
        p = subprocess.run(cmd, capture_output=True, text=True)
        el = time.time() - t0
        bt = od / "ball_tracks.json"
        rec = {"tag": tag, "params": cfg, "extra": a.extra,
               "elapsed_s": round(el, 1), "rc": p.returncode, "ok": bt.exists()}
        if bt.exists():
            aq = subprocess.run([PY, str(ROOT / "engine" / "track_stability_audit.py"),
                                 str(bt)], capture_output=True, text=True)
            line = [l for l in aq.stdout.splitlines() if "ball_tracks" in l or str(bt) in l]
            # 直接调 audit 函数拿结构化结果
            sys.path.insert(0, str(ROOT / "engine"))
            import track_stability_audit as TA
            m = TA.audit(str(bt))
            rec.update({k: m[k] for k in ("n_ids", "med_life", "p90_life", "max_life",
                                          "ppl_per_frame", "concurrency_med",
                                          "new_ids_per_fr", "long_ratio", "VERDICT")})
        else:
            rec["stderr_tail"] = p.stderr[-400:]
        rows.append(rec)
        print(f"[{tag}] rc={rec['rc']} {el:.0f}s "
              f"ids={rec.get('n_ids')} med={rec.get('med_life')} "
              f"conc={rec.get('concurrency_med')} -> {rec.get('VERDICT')}")

    (outroot / "sweep_result.json").write_text(
        json.dumps({"seg": a.seg, "src": a.src, "grid": a.grid,
                    "grid_def": GRIDS[a.grid], "rows": rows},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", outroot / "sweep_result.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
