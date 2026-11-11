#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_identity_audit_sweep —— 对 G3_base / loose_gate 两组 stabilize 产物跑 门①-B 外观审计。

判定：loose_gate 降低可见 replace 率是否「真改进」还是「假完整」(track 保 ID 但跟错人)。
若 loose_gate 的 delta10 / P1 明显劣于 G3_base ⇒ 假完整（ID 串人）；若持平或更好 ⇒ 真改进。

用法:
  python3 run_identity_audit_sweep.py
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
SWEEP = ROOT / "action_work" / "sweep_pilot"
SEGBASE = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
PY = str(Path.home() / ".workbuddy/binaries/python/envs/action05/bin/python")
DUMP = ROOT / "engine" / "dump_player_embeddings.py"
AUDIT = ROOT / "engine" / "id_identity_audit.py"
VARIANTS = ["G3_base", "loose_gate"]


def load_audit():
    spec = importlib.util.spec_from_file_location("id_identity_audit", AUDIT)
    return spec, importlib.util.module_from_spec(spec)


def main():
    segs = sorted(p.name for p in (SWEEP / "G3_base").iterdir()
                  if p.is_dir() and (p / "ball_tracks.json").exists())
    agg = {v: {"n": 0, "pass": 0, "d10": [], "w10": [], "btw": [], "adjbrk": [], "cohen": []}
           for v in VARIANTS}
    per = {v: {} for v in VARIANTS}

    for v in VARIANTS:
        for s in segs:
            bt = SWEEP / v / s / "ball_tracks.json"
            emb = SWEEP / v / s / "emb_dump.json"
            fr = SEGBASE / s / "frames"
            if not bt.exists() or not fr.exists():
                continue
            # 1) dump embeddings (幂等: 已有则跳过)
            if not emb.exists():
                r = subprocess.run([PY, str(DUMP), "--tracks", str(bt),
                                    "--frames-dir", str(fr), "--out", str(emb)],
                                   capture_output=True, text=True,
                                   env={**__import__("os").environ,
                                        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                                        "PYTHONPATH": "", "YOLO_CONFIG_DIR": "/tmp/yolo_cfg"})
                if r.returncode != 0:
                    print(f"  [{v}/{s}] DUMP FAIL: {r.stderr[-500:]}", flush=True)
                    continue
            # 2) 跑外观审计
            spec = importlib.util.spec_from_file_location("id_identity_audit", AUDIT)
            M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
            try:
                res = M.audit(str(bt), str(emb))
            except Exception as e:
                print(f"  [{v}/{s}] AUDIT ERR: {e}", flush=True)
                continue
            per[v][s] = res
            a = agg[v]
            a["n"] += 1
            if res["VERDICT"] == "PASS":
                a["pass"] += 1
            for k in ("delta10", "within@10", "between_mean", "adj_break_ratio(<0.5)", "cohen_d_@10"):
                val = res.get(k)
                if val is not None:
                    a[{"delta10": "d10", "within@10": "w10", "between_mean": "btw",
                       "adj_break_ratio(<0.5)": "adjbrk", "cohen_d_@10": "cohen"}[k]].append(val)

    import numpy as np
    print("\n=== 门①-B 外观审计：G3_base vs loose_gate（同 12 段）===")
    print(f"{'variant':<12}{'n':>4}{'PASS':>6}{'Δ10':>8}{'within@10':>11}{'between':>9}{'adj_brk':>9}{'cohen_d':>9}")
    for v in VARIANTS:
        a = agg[v]
        if not a["n"]:
            continue
        d10 = np.mean(a["d10"]) if a["d10"] else float("nan")
        w10 = np.mean(a["w10"]) if a["w10"] else float("nan")
        btw = np.mean(a["btw"]) if a["btw"] else float("nan")
        adj = np.mean(a["adjbrk"]) if a["adjbrk"] else float("nan")
        co = np.mean(a["cohen"]) if a["cohen"] else float("nan")
        print(f"{v:<12}{a['n']:>4}{a['pass']:>6}{d10:>8.3f}{w10:>11.3f}{btw:>9.3f}{adj:>9.3f}{co:>9.2f}")
    out = {"per": per, "agg": {k: {kk: (vv if not isinstance(vv, list) else round(float(np.mean(vv)), 4))
                                   for kk, vv in v.items()} for k, v in agg.items()}}
    (SWEEP / "identity_audit_sweep.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nwrote", SWEEP / "identity_audit_sweep.json")


if __name__ == "__main__":
    main()
