#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sweep_identity_pilot —— A5.32b 步骤B 试点：以 replace+twin 率为目标扫 stabilize 参数。

做法：
  ① 从 norm_g3 的纯净子集里挑「球没动换ID事件」最多的前 N 段（率要有统计意义）；
  ② 对每组 stabilize 参数变体，把这 N 段重新稳定化到临时 outroot（绝不覆盖 norm_g3）；
  ③ 在每组上跑 ball_switch_classify，算 replace+twin 率；
  ④ 与 G3 基线（同 N 段）对比，看目标函数是否随参数响应。

用法：
  python3 sweep_identity_pilot.py            # 默认 N=12，4 个变体
  python3 sweep_identity_pilot.py --n 8 --variant all
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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
ACT = ROOT / "action_work"
SEGBASE = ACT / "tactic_notes_batch_full" / "segments"
PY = str(Path.home() / ".workbuddy/binaries/python/envs/action05/bin/python")
CLEAN_JSON = ACT / "norm_calib" / "switch_classify_clean_g3.json"
NORM_G3 = ACT / "norm_g3"
SWEEP_ROOT = ACT / "sweep_pilot"

G3_BASE = {"track_buffer": 300, "zombie_buffer": 600, "gate": 0.30,
           "app_thresh": 0.10, "w_app": 0.5, "fps": 2.0,
           "conf_min": 0.40, "h_min": 0, "topn": 12}

VARIANTS = {
    "G3_base":        dict(G3_BASE),
    "long_persist":   {**G3_BASE, "track_buffer": 900, "zombie_buffer": 1800},
    "loose_gate":     {**G3_BASE, "gate": 0.50},
    "long_loose":     {**G3_BASE, "track_buffer": 900, "zombie_buffer": 1800, "gate": 0.50},
    "tight_gate":     {**G3_BASE, "gate": 0.20},
}


def classify_rate(root, segs):
    import importlib.util
    spec = importlib.util.spec_from_file_location("ball_switch_classify",
                                                  ROOT / "engine" / "ball_switch_classify.py")
    C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)
    rep = tw = tot = 0
    per = {}
    for s in segs:
        d = json.loads((root / s / "ball_tracks.json").read_text(encoding="utf-8"))
        c = C.classify_seg(d)
        per[s] = c
        rep += c["replace"]; tw += c["twin"]; tot += sum(c.values())
    return {"n_seg": len(segs), "replace": rep, "twin": tw, "two_real": tot - rep - tw,
            "total": tot, "err_rate": (rep + tw) / max(1, tot), "per": per}


def pick_segs(n):
    data = json.loads(CLEAN_JSON.read_text())
    clean = data["clean_segs"]
    # 用 norm_g3 算每段 total，挑事件最多的前 n
    import importlib.util
    spec = importlib.util.spec_from_file_location("ball_switch_classify",
                                                  ROOT / "engine" / "ball_switch_classify.py")
    C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)
    scored = []
    for s in clean:
        d = json.loads((NORM_G3 / s / "ball_tracks.json").read_text())
        c = C.classify_seg(d); tot = sum(c.values())
        if tot >= 5:
            scored.append((tot, s))
    scored.sort(reverse=True)
    return [s for _, s in scored[:n]]


def _offline_env():
    import os
    e = dict(os.environ)
    e["HF_HUB_OFFLINE"] = "1"
    e["TRANSFORMERS_OFFLINE"] = "1"
    e["PYTHONPATH"] = ""  # 清掉 broker shim，避免 open() 审批超时（A0 铁律）
    e["YOLO_CONFIG_DIR"] = "/tmp/yolo_cfg"
    return e


def stabilize_one(seg, params, outroot):
    src = SEGBASE / seg / "ball_tracks.json"
    img = None
    for c in (SEGBASE / seg / "frames", ACT / seg / "frames", ACT / seg):
        if c.exists() and any(c.glob("*.jpg")):
            img = c; break
    if src is None or img is None:
        return seg, "SKIP", 0
    out = outroot / seg; out.mkdir(parents=True, exist_ok=True)
    cmd = [PY, str(ROOT / "engine" / "stabilize_tracks_v2.py"), str(src), str(img),
           "--out", str(out)]
    for k, v in params.items():
        cmd += [f"--{k.replace('_', '-')}", str(v)]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, env=_offline_env())
    el = time.time() - t0
    if p.returncode != 0 or not (out / "ball_tracks.json").exists():
        (out / "run_error.log").write_text((p.stdout or "") + "\nSTDERR:\n" + (p.stderr or "")[-1500:],
                                           encoding="utf-8")
        return seg, "FAIL", el
    return seg, "OK", el


def run_variant(name, params, segs, workers=4):
    outroot = SWEEP_ROOT / name
    # 重稳定化（断点：已有同参数产物则跳过——这里简化，每次清了重跑试点）
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(stabilize_one, s, params, outroot): s for s in segs}
        for i, f in enumerate(futs, 1):
            seg, st, el = f.result()
            if st != "OK":
                print(f"   [{name}] {seg}: {st}", flush=True)
    print(f"   [{name}] 稳定化 {len(segs)} 段 耗时 {(time.time()-t0)/60:.1f}min", flush=True)
    return classify_rate(outroot, segs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--variant", default="all", help="all / G3_base / long_persist / loose_gate / long_loose / tight_gate")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    segs = pick_segs(a.n)
    print(f"试点段 (top-{a.n} by 事件数): {segs}")
    if not segs:
        print("无可用段"); return

    variants = VARIANTS if a.variant == "all" else {a.variant: VARIANTS[a.variant]}
    results = {}
    for name, params in variants.items():
        print(f"\n=== 变体 {name} ===")
        print("   params:", {k: params[k] for k in ("track_buffer", "zombie_buffer", "gate", "app_thresh", "w_app")})
        r = run_variant(name, params, segs, a.workers)
        results[name] = r
        print(f"   纯净子集: n_seg={r['n_seg']} total={r['total']} "
              f"replace={r['replace']} twin={r['twin']} two_real={r['two_real']} "
              f"=> 真错误率 {r['err_rate']*100:.1f}%")

    print("\n=== 汇总（同 N 段横向对比）===")
    print(f"  {'variant':<14}{'total':>6}{'replace':>9}{'twin':>6}{'err%':>7}")
    for name, r in results.items():
        print(f"  {name:<14}{r['total']:>6}{r['replace']:>9}{r['twin']:>6}{r['err_rate']*100:>6.1f}%")
    (SWEEP_ROOT / "pilot_results.json").write_text(
        json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "per"} for k, v in results.items()},
                  indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nwrote", SWEEP_ROOT / "pilot_results.json")


if __name__ == "__main__":
    sys.exit(main())
