#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_stabilize_batch —— 把验证过的 rescue-g3 参数铺到全部 177 段（净化门）。

背景：门①-A/①-B 已在 sas_det/hou/lal/nop 四段上跨段验证
  g3 = --track-buffer 300 --zombie-buffer 600 --gate 0.30 --app-thresh 0.10 --w-app 0.5
  ⇒ ①-A 4/4（中位寿命 14→32 … 56→188 帧）＋ ①-B 4/4（Δ10 0.21~0.28，win_rate 0.76~0.89）
本脚本负责把它铺到全部段，并**逐段留痕 + 逐段审计**。

断点续跑：已完成且 run_meta.json 里参数一致的段自动跳过；
          参数变了或产物缺失 ⇒ 重跑。任何时候中断都可重入。

用法:
  python3 run_stabilize_batch.py --workers 3                 # 全量
  python3 run_stabilize_batch.py --seg ep10_s0 --seg ep11_s1 # 指定段
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

# 已验证的双门配置（改动本字典 = 重做全部段，脚本会自动识别参数变化）
#
# 净化门前置过滤（engine/calibrate_detection_filter.py 全量 177 段标定）：
#   ep*_sX 的段内 ball_tracks.json 是**未过滤原始检测**（conf 中位 0.41、
#   33% 框高<60px 的远景/观众），直接喂给 stabilize ⇒ 每帧 25~27 框、并发 27
#   ⇒ 撞死「并发∈[8,16]」硬门。conf 0.40 / h 80 时：每帧人数中位 9.0、
#   <6 帧 10.4%、>14 帧 14.8%、逐段达标 122/177 —— 是网格里「压得住噪声」
#   与「不吞真实球员」之间最优的平衡点。
G3 = {
    "track_buffer": 300,
    "zombie_buffer": 600,
    "gate": 0.30,
    "app_thresh": 0.10,
    "w_app": 0.5,
    "fps": 2.0,
    "conf_min": 0.40,
    "h_min": 0,
    "topn": 12,
}


def segments():
    return sorted(d.name for d in SEGBASE.iterdir() if d.is_dir())


def src_of(seg):
    p = SEGBASE / seg / "ball_tracks.json"
    return p if p.exists() else None


def imgdir_of(seg):
    for c in (SEGBASE / seg / "frames", ACT / seg / "frames", ACT / seg):
        if c.exists() and any(c.glob("*.jpg")):
            return c
    return None


def already_done(seg, out):
    """已完成 且 run_meta.json 记录的参数与本脚本 G3 一致 ⇒ 跳过。"""
    bt = out / "ball_tracks.json"
    meta = out / "run_meta.json"
    if not bt.exists() or not meta.exists():
        return False
    try:
        m = json.loads(meta.read_text(encoding="utf-8"))
    except Exception:
        return False
    p = m.get("params", {})
    return all(p.get(k) == v for k, v in G3.items())


def run_one(seg, out):
    src = src_of(seg)
    img = imgdir_of(seg)
    if src is None or img is None:
        return seg, "SKIP_NO_SRC", 0
    out.mkdir(parents=True, exist_ok=True)
    cmd = [PY, str(ROOT / "engine" / "stabilize_tracks_v2.py"),
           str(src), str(img), "--out", str(out)]
    for k, v in G3.items():
        # argparse 只认连字符，下划线形式会被拒（踩过）
        cmd += [f"--{k.replace('_', '-')}", str(v)]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True)
    el = time.time() - t0
    if p.returncode != 0 or not (out / "ball_tracks.json").exists():
        (out / "run_error.log").write_text(
            (p.stdout or "") + "\n---stderr---\n" + (p.stderr or "")[-2000:], encoding="utf-8")
        return seg, "FAIL", el
    return seg, "OK", el


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--seg", action="append", default=[], nargs="+")
    ap.add_argument("--outroot", default=str(ACT / "norm_g3"))
    ap.add_argument("--limit", type=int, default=0)
    # 净化门前置过滤的 conf 门槛可覆盖，用来做 A/B 对照
    # （A5.31d 实测：被 conf>=0.40 滤掉的框框高 65~163px、conf 中位 0.31，
    #   视觉自证它们**落在真人身上** ⇒ 并发<8 的真因是 conf 门槛砍人，不是景别）。
    #   改写 G3 会让 already_done() 识别出参数变化 ⇒ 已跑的段自动重跑，不冲突。
    ap.add_argument("--conf-min", type=float, default=G3["conf_min"])
    # —— A5.32b 步骤B：以 replace+twin 率为目标函数扫 stabilize 参数 ——
    # 下列覆盖项让 G3 每个键都可从命令行改写；改写后 already_done() 会识别参数变化 ⇒ 自动重跑。
    ap.add_argument("--track-buffer", type=int, default=G3["track_buffer"])
    ap.add_argument("--zombie-buffer", type=int, default=G3["zombie_buffer"])
    ap.add_argument("--gate", type=float, default=G3["gate"])
    ap.add_argument("--app-thresh", type=float, default=G3["app_thresh"])
    ap.add_argument("--w-app", type=float, default=G3["w_app"])
    ap.add_argument("--fps", type=float, default=G3["fps"])
    ap.add_argument("--h-min", type=int, default=G3["h_min"])
    ap.add_argument("--topn", type=int, default=G3["topn"])
    a = ap.parse_args()
    G3["conf_min"] = a.conf_min
    G3["track_buffer"] = a.track_buffer
    G3["zombie_buffer"] = a.zombie_buffer
    G3["gate"] = a.gate
    G3["app_thresh"] = a.app_thresh
    G3["w_app"] = a.w_app
    G3["fps"] = a.fps
    G3["h_min"] = a.h_min
    G3["topn"] = a.topn

    segs = [s for grp in a.seg for s in grp] if a.seg else segments()
    if a.limit:
        segs = segs[: a.limit]
    print(f"[batch] 段数={len(segs)} workers={a.workers} outroot={a.outroot}")

    todo, skip = [], []
    for s in segs:
        (skip if already_done(s, Path(a.outroot) / s) else todo).append(s)
    print(f"[batch] 待跑={len(todo)} 跳过(已达标)={len(skip)}")

    done_at = {s: t for s, t in zip(skip, [0] * len(skip))}
    t_all = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(run_one, s, Path(a.outroot) / s): s for s in todo}
        for i, f in enumerate(futs, 1):
            seg, st, el = f.result()
            done_at[seg] = el
            print(f"[{i}/{len(todo)}] {seg}: {st} {el:.0f}s", flush=True)
            # 每 10 段落一次进度，方便中断后续跑
            if i % 10 == 0:
                Path(a.outroot, "_progress.json").write_text(
                    json.dump if False else json.dumps(
                        {"done": len(done_at), "total": len(segs),
                         "elapsed_s": round(time.time() - t_all, 1)}, indent=2),
                    encoding="utf-8")

    ok = sum(1 for v in done_at.values() if v)
    print(f"[batch] 完成 {ok}/{len(segs)}，总耗时 {(time.time()-t_all)/60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
