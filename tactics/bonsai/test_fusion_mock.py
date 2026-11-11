#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fusion_judge 逻辑单测（mock IO，无需 Qwen server / cv2 / ffmpeg）。

锚点来源（磁盘实证 + 老程裁定，修正后逻辑）：
  真实全量 sb 数据：cand1244=1.0(EXCLUDE) / cand932=1.0(KEEP) / cand1119=1.0(KEEP) /
  full_poss428=0.75(KEEP) / possA=0.20(KEEP)。
  ⇒ 高 sb(≥0.5) 对 KEEP/EXCLUDE 无区分力 → 一律 HUMAN_REVIEW（交老程）；
  sb<0.5 门控6 干净 → KEEP（possA 实证）；Qwen 把吹停错判 LIVE，仅记录参考。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import sys
import types

from common.nba_paths import tactics_data_file

sys.path.insert(0, str(tactics_data_file("bonsai")))
import fusion_judge as fj


# ---- 把 cv2/numpy/server 全部 mock 掉，只测纯逻辑 ----
def fake_compute_sb_frac(src, t0, t1, step=1.0, tmp=None):
    # 由测试注入的全局表驱动
    return fake_compute_sb_frac.VALUE


def fake_call_qwen_live(frames, qwen_url=fj.QWEN_URL, temperature=0.0):
    return fake_call_qwen_live.VALUE


fj.compute_sb_frac = fake_compute_sb_frac
fj.call_qwen_live = fake_call_qwen_live
fj.extract_frames = lambda *a, **k: ["fake1.jpg", "fake2.jpg"]


def mk_cand(close=(450.0, 458.0), far=(446.0, 448.0, 300), mid=(448.0, 450.0),
            shape_ok=True, sb_frac_field=None):
    c = {"far": list(far), "mid": list(mid),
         "close": list(close) + [700], "dur": 12.0, "act_rise": 20.0,
         "shape_ok": shape_ok, "sb_frac": sb_frac_field,
         "clip": [close[0] - 1.5, close[1] + 3.0]}
    return c


PASS = 0
FAIL = 0


def check(name, got, exp):
    global PASS, FAIL
    ok = got == exp
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: got={got} exp={exp}")
    PASS += ok
    FAIL += (not ok)


# ============ 1) 纯逻辑 fuse_verdict ============
print("== fuse_verdict 纯逻辑（修正后：高sb无区分力→REVIEW）==")
v, c, r = fj.fuse_verdict(1.0, 0.99)
check("cand1244 高sb→REVIEW(交老程,即便Qwen说LIVE)", v, "HUMAN_REVIEW")
v, c, r = fj.fuse_verdict(0.70, 0.98)
check("cand932 高sb→REVIEW(交老程,即便Qwen高置信)", v, "HUMAN_REVIEW")
v, c, r = fj.fuse_verdict(0.30, None)
check("possA 特写无记分牌→KEEP", v, "KEEP")
v, c, r = fj.fuse_verdict(-1.0, None)
check("无sb数据→REVIEW", v, "HUMAN_REVIEW")
v, c, r = fj.fuse_verdict(0.70, None)
check("高sb+Qwen不可达→REVIEW", v, "HUMAN_REVIEW")
v, c, r = fj.fuse_verdict(0.70, 0.60)
check("高sb+Qwen低置信→REVIEW", v, "HUMAN_REVIEW")

# ============ 2) 编排 judge_candidate（mock IO）============
print("\n== judge_candidate 编排（mock IO）==")
fake_compute_sb_frac.VALUE = 1.0
fake_call_qwen_live.VALUE = 0.99
r = fj.judge_candidate(mk_cand(), "fake.mp4")
check("cand1244 verdict(高sb→REVIEW)", r["verdict"], "HUMAN_REVIEW")

fake_compute_sb_frac.VALUE = 0.70
fake_call_qwen_live.VALUE = 0.98
r = fj.judge_candidate(mk_cand(), "fake.mp4")
check("cand932 verdict(高sb→REVIEW)", r["verdict"], "HUMAN_REVIEW")
check("cand932 qwen_live 仍记录", r.get("qwen_live"), 0.98)

fake_compute_sb_frac.VALUE = 0.30
fake_call_qwen_live.VALUE = None  # 模糊档以下不应调 Qwen
r = fj.judge_candidate(mk_cand(), "fake.mp4")
check("possA verdict(不调Qwen)", r["verdict"], "KEEP")

# 模糊档但 Qwen 不可达 → REVIEW
fake_compute_sb_frac.VALUE = 0.70
fake_call_qwen_live.VALUE = None
r = fj.judge_candidate(mk_cand(), "fake.mp4")
check("模糊档Qwen不可达→REVIEW", r["verdict"], "HUMAN_REVIEW")

print(f"\n==== 结果: {PASS} passed, {FAIL} failed ====")
sys.exit(1 if FAIL else 0)
