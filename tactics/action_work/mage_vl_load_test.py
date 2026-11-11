#!/usr/bin/env python
"""
Mage-VL BF16 本地可跑性 load test（M4 Mac / MPS）。

目标（老程 2026-10-03 裁定①=Q4，但需先拿 BF16 真实内存证据）：
1. 验证 transformers>=5.7 + 自定义 modeling_mage_vl.py 能在 M4 import；
2. 验证 `--video-backend frames` 路径不碰 neural_codec（CUDA 扩展）；
3. 实测 BF16 全模型峰值内存（MPS allocated + 进程 RSS），判断 16GB 是否装得下；
4. 跑一次 32 帧小生成，确认真实推理可用。

用法：
  mage_vl/bin/python mage_vl_load_test.py \
      --model <TACTICS_DATA_ROOT>/action_work/weights/Mage-VL \
      --video  <TACTICS_DATA_ROOT>/action_work/weights/Mage-VL/examples/soccer-broadcast.mp4 \
      --num-frames 32 --max-new-tokens 64
"""
import argparse
import json
import os
import resource
import time
import traceback


def rss_mb():
    # macOS ru_maxrss 单位为 bytes
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)


def sample_video(video: str, num_frames: int):
    import cv2
    import numpy as np
    from PIL import Image

    capture = cv2.VideoCapture(video)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if frame_count <= 0:
        capture.release()
        raise ValueError(f"Could not read video: {video}")
    indices = np.linspace(0, frame_count - 1, min(num_frames, frame_count), dtype=int)
    frames = []
    for index in indices:
        capture.set(cv2.CAP_PROP_POS_FRAMES, int(index))
        ok, frame = capture.read()
        if not ok:
            capture.release()
            raise ValueError(f"Could not decode frame {index}")
        frames.append(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
    capture.release()
    return frames


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--num-frames", type=int, default=32)
    ap.add_argument("--max-new-tokens", type=int, default=64)
    ap.add_argument("--dtype", default="bf16", choices=["bf16", "fp16", "auto"])
    args = ap.parse_args()

    rep = {"steps": [], "ok": False}
    t0 = time.time()

    def mark(name, **kw):
        rep["steps"].append({"step": name, "t": round(time.time() - t0, 1), "rss_mb": round(rss_mb(), 1), **kw})
        print(f"[{name}] t={rep['steps'][-1]['t']}s rss={rep['steps'][-1]['rss_mb']}MB {kw}")

    try:
        import torch
        from PIL import Image
        from transformers import AutoModelForCausalLM, AutoProcessor

        mark("import_ok", torch_version=torch.__version__,
             mps_available=torch.backends.mps.is_available(),
             transformers_ok=True)

        device = "mps" if torch.backends.mps.is_available() else "cpu"
        dtype = {"bf16": torch.bfloat16, "fp16": torch.float16, "auto": "auto"}[args.dtype]

        # 关键：trust_remote_code=True 加载自定义 Mage-ViT+Qwen3 架构
        processor = AutoProcessor.from_pretrained(args.model, trust_remote_code=True)
        mark("processor_loaded")

        model = AutoModelForCausalLM.from_pretrained(
            args.model, trust_remote_code=True, torch_dtype=dtype,
            low_cpu_mem_usage=True,
        )
        mark("model_loaded_cpu", param_dtype=str(dtype))

        model = model.to(device).eval()
        mark("model_to_device", device=device)
        if device == "mps":
            mark("mps_allocated_mb", mps_allocated_mb=round(torch.mps.current_allocated_memory() / 1024 / 1024, 1))

        # 构造 frames 后端输入（均匀抽帧，正是 40-50s 战术片段所需路径）
        frames = sample_video(args.video, args.num_frames)
        mark("frames_sampled", n=len(frames), size=frames[0].size)

        messages = [{"role": "user", "content": [
            {"type": "video"}, {"type": "text", "text": "Describe this video in one sentence."},
        ]}]
        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = processor(text=[text], videos=frames, return_tensors="pt", padding=True)
        inputs = {k: (v.to(device) if hasattr(v, "to") else v) for k, v in inputs.items()}
        if "pixel_values" in inputs:
            inputs["pixel_values"] = inputs["pixel_values"].to(model.dtype)
        mark("inputs_built", input_ids_shape=list(inputs["input_ids"].shape))

        with torch.inference_mode():
            out = model.generate(**inputs, max_new_tokens=args.max_new_tokens, do_sample=False)
        answer = processor.tokenizer.decode(out[0, inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        mark("generate_done", out_tokens=out.shape[1] - inputs["input_ids"].shape[1])
        rep["answer"] = answer.strip()
        if device == "mps":
            rep["mps_peak_mb"] = round(torch.mps.current_allocated_memory() / 1024 / 1024, 1)
        rep["rss_peak_mb"] = round(rss_mb(), 1)
        rep["ok"] = True
        print("\n=== ANSWER ===\n", answer.strip())
    except Exception as e:
        rep["error"] = repr(e)
        rep["traceback"] = traceback.format_exc()
        print("ERROR:", repr(e))
        traceback.print_exc()

    rep["total_s"] = round(time.time() - t0, 1)
    rep["rss_final_mb"] = round(rss_mb(), 1)
    out_json = "/tmp/mage_vl_load_test.json"
    with open(out_json, "w") as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    print(f"\n[report] -> {out_json}")
    print(json.dumps({k: rep[k] for k in ("ok", "rss_peak_mb", "mps_peak_mb", "total_s", "error") if k in rep}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
