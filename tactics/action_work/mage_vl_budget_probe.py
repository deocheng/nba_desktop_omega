#!/usr/bin/env python
"""
Mage-VL 帧数 × pixel预算 的 context 预算表扫描（只加载 processor，不加载 9GB 模型）。

背景（2026-10-03 实测）：本机 16GB M4 在 16 帧/(~8300ctx) 配置下换页抖动（swap 打满 17.5GB），
8 帧/(4170ctx) 才正常运行。根因是**运行时工作集**超限，而工作集主要由**总 patch 数**驱动
（视觉塔激活 + prefill 注意力），不是单纯的 context token 数。

解法思路（路线①）：把每帧分辨率降下来 ⇒ 同样总 patch 预算可以喂**更多帧**。
"多而粗"对战术理解更合适（要时序），"少而精"每 5-6 秒才一帧讲不清配合。

本脚本目标：在不加载模型的前提下，给出 (帧数, max_pixels) → (pixel_values 总 patch, input_ids 长度)，
据此挑出"总 patch 保持 8 帧安全水位 ≈16320"的最大可用帧数。

校验：默认配置 8 帧应复现已知基线 pixel_values=[16320,768]、input_ids≈4170（与 mage_vl_timing.py 一致）。

用法：
  mage_vl/bin/python mage_vl_budget_probe.py --frames-dir .../segments/ep10_s0/frames
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from common.nba_paths import tactics_data_file


def sample_frames(frames_dir: Path, n: int):
    files = sorted(frames_dir.glob("*.jpg"))
    if not files:
        raise SystemExit(f"no jpg frames in {frames_dir}")
    idx = np.linspace(0, len(files) - 1, min(n, len(files)), dtype=int)
    return [Image.open(files[int(i)]).convert("RGB") for i in idx]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=str(tactics_data_file("action_work/weights/Mage-VL")))
    ap.add_argument("--frames-dir", required=True)
    ap.add_argument("--out", default="/tmp/mage_vl_budget.json")
    a = ap.parse_args()

    from transformers import AutoProcessor
    proc = AutoProcessor.from_pretrained(a.model, trust_remote_code=True)

    frames_dir = Path(a.frames_dir)
    files = sorted(frames_dir.glob("*.jpg"))
    probe = Image.open(files[0])
    print(f"源 frames: {len(files)} 张, 单帧尺寸={probe.size}")

    # 与 mage_vl_timing.py 完全一致的构造（走 apply_chat_template 才能得到正确的 video 占位符）
    # 基线应复现：pixel_values=[16320,768]、input_ids≈4170
    messages = [{"role": "user", "content": [
        {"type": "video"},
        {"type": "text", "text": "Describe this video in one sentence."},
    ]}]
    text = proc.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

    # 注意：实测 max_pixels 对视频链路无效（传不同值 patches/frame 恒为 3520）。
    # 因为 video_preprocessor max_pixels=12845056 基本无上限、且 resize_frames=true
    # ⇒ 直接喂更小的 PIL 帧即可线性减少 patch（不依赖 max_pixels 生效）。
    sizes = [(1280, 720), (960, 540), (640, 360), (512, 288), (480, 270)]
    n_frames_list = [8, 16, 24, 32]
    rows = []
    for (w, h) in sizes:
        for n_frames in n_frames_list:
            frames = sample_frames(frames_dir, n_frames)
            frames = [f.resize((w, h), Image.BILINEAR) for f in frames]
            inputs = proc(text=[text], videos=frames, return_tensors="pt", padding=True)
            pv = inputs["pixel_values"]
            n_patch = int(pv.shape[0])
            n_ctx = int(inputs["input_ids"].shape[1])
            per_frame = n_patch // n_frames
            rows.append({
                "frame_size": f"{w}x{h}", "frames": n_frames,
                "total_patches": n_patch, "patches_per_frame": per_frame,
                "ctx_tokens": n_ctx, "patches_vs_safe": round(n_patch / 16320, 3),
            })
            flag = "OK" if n_patch <= 18000 else ("超" if n_patch > 30000 else "临界")
            print(f"  size={w}x{h:<4} frames={n_frames:<3} -> patch总={n_patch:<7} "
                  f"每帧={per_frame:<6} ctx={n_ctx:<6} 相对安全水位={n_patch/16320:>5.2f}x  {flag}")

    out = {"source_frames": len(files), "frame_size": probe.size, "rows": rows}
    json.dump(out, open(a.out, "w"), indent=2)
    print(f"\n[report] -> {a.out}")
    print("\n判读：选 patches_vs_base 最接近 1.0 的最大 frames —— 总 patch 守住安全水位，帧数最大化。")


if __name__ == "__main__":
    main()
