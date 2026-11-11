#!/usr/bin/env python
"""
Mage-VL 生成速度 root-cause 分离计时（M4 Mac / MPS）。

把一次 generate 拆成三段，定位 ~14s/token 到底花在哪：
  1) vision   : model.get_image_features(pixel_values, image_grid_thw) 单独计时（Mage-ViT 编码）
  2) prefill  : model(**inputs, use_cache=True) 全 prompt 前向（含 vision + 第一次 LLM 注意力）
  3) decode   : model.generate 总时 - prefill，再 / N 个新 token → 每 token decode 耗时

判读：
  - 若 prefill 巨大、decode 很小 → 瓶颈在 prefill（vision 编码 / 首次长 context 注意力），
    减帧/降分辨率/换更快视觉塔可解；decode 本身可用。
  - 若 decode 每 token 巨大（数秒级）→ 瓶颈在 MPS 对长 context 的逐 token 注意力，
    需 flash-attn / int4 / CUDA 机。

用法：
  mage_vl/bin/python mage_vl_timing.py \
      --model .../Mage-VL --video .../examples/soccer-broadcast.mp4 \
      --num-frames 8 --max-new-tokens 16 --dtype fp16
"""
import argparse
import json
import resource
import time
import traceback


def rss_mb():
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
    ap.add_argument("--num-frames", type=int, default=8)
    ap.add_argument("--max-new-tokens", type=int, default=16)
    ap.add_argument("--dtype", default="fp16", choices=["bf16", "fp16", "auto"])
    args = ap.parse_args()

    rep = {"steps": [], "ok": False}
    t0 = time.time()

    def mark(name, **kw):
        rep["steps"].append({"step": name, "t": round(time.time() - t0, 1), **kw})
        print(f"[{name}] t={rep['steps'][-1]['t']}s {kw}")

    try:
        import torch
        from PIL import Image
        from transformers import AutoModelForCausalLM, AutoProcessor

        mark("import_ok", torch_version=torch.__version__,
             mps=torch.backends.mps.is_available())
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        dtype = {"bf16": torch.bfloat16, "fp16": torch.float16, "auto": "auto"}[args.dtype]

        processor = AutoProcessor.from_pretrained(args.model, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            args.model, trust_remote_code=True, torch_dtype=dtype, low_cpu_mem_usage=True
        ).to(device).eval()
        mark("model_ready", device=device, dtype=str(dtype))

        frames = sample_video(args.video, args.num_frames)
        messages = [{"role": "user", "content": [
            {"type": "video"}, {"type": "text", "text": "Describe this video in one sentence."},
        ]}]
        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = processor(text=[text], videos=frames, return_tensors="pt", padding=True)
        inputs = {k: (v.to(device) if hasattr(v, "to") else v) for k, v in inputs.items()}
        if "pixel_values" in inputs:
            inputs["pixel_values"] = inputs["pixel_values"].to(model.dtype)
        ctx = int(inputs["input_ids"].shape[1])
        mark("inputs_built", ctx_tokens=ctx, pv_shape=list(inputs["pixel_values"].shape) if "pixel_values" in inputs else None)

        # ---- 1) vision 编码单独计时 ----
        if "pixel_values" in inputs:
            pv = inputs["pixel_values"]
            igt = inputs.get("image_grid_thw")
            pp = inputs.get("patch_positions")
            # 与 model.generate 内部路径一致：generate 调的是 model.model.get_image_features
            # （带 patch_positions，用于 3D RoPE）；顶层 get_image_features 不接受该参数。
            t_v = time.time()
            with torch.inference_mode():
                feats = model.model.get_image_features(pv, igt, patch_positions=pp)
            if device == "mps":
                torch.mps.synchronize()
            t_vision = time.time() - t_v
            mark("vision_done", vision_s=round(t_vision, 2), n_patch_emb=len(feats) if isinstance(feats, list) else None)
        else:
            t_vision = None

        # ---- 2) prefill（含 vision + 首次 LLM 注意力）----
        t_p = time.time()
        with torch.inference_mode():
            prefill_out = model(**inputs, use_cache=True)
        if device == "mps":
            torch.mps.synchronize()
        t_prefill = time.time() - t_p
        mark("prefill_done", prefill_s=round(t_prefill, 2))

        # ---- 3) 完整 generate 计时 ----
        t_g = time.time()
        with torch.inference_mode():
            out = model.generate(**inputs, max_new_tokens=args.max_new_tokens, do_sample=False)
        if device == "mps":
            torch.mps.synchronize()
        t_gen = time.time() - t_g
        n_gen = int(out.shape[1]) - ctx
        decode_total = max(t_gen - t_prefill, 0.0)
        decode_per = decode_total / n_gen if n_gen else None
        answer = processor.tokenizer.decode(out[0, ctx:], skip_special_tokens=True)
        mark("generate_done", gen_total_s=round(t_gen, 2), n_gen=n_gen,
             decode_per_token_s=(round(decode_per, 3) if decode_per is not None else None))

        # ---- 汇总口径 ----
        llm_prefill = (t_prefill - t_vision) if (t_vision is not None) else None
        rep["timing"] = {
            "ctx_tokens": ctx,
            "vision_s": round(t_vision, 2) if t_vision is not None else None,
            "prefill_total_s": round(t_prefill, 2),
            "llm_prefill_s": round(llm_prefill, 2) if llm_prefill is not None else None,
            "generate_total_s": round(t_gen, 2),
            "decode_total_s": round(decode_total, 2),
            "decode_per_token_s": round(decode_per, 3) if decode_per is not None else None,
            "avg_per_new_token_s": round(t_gen / n_gen, 3) if n_gen else None,
        }
        rep["answer"] = answer.strip()
        if device == "mps":
            rep["mps_peak_mb"] = round(torch.mps.current_allocated_memory() / 1024 / 1024, 1)
        rep["ok"] = True
        print("\n=== ANSWER ===\n", answer.strip())
        print("\n=== TIMING ===\n", json.dumps(rep["timing"], indent=2))
    except Exception as e:
        rep["error"] = repr(e)
        rep["traceback"] = traceback.format_exc()
        print("ERROR:", repr(e))
        traceback.print_exc()

    rep["total_s"] = round(time.time() - t0, 1)
    out_json = "/tmp/mage_vl_timing.json"
    with open(out_json, "w") as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    print(f"\n[report] -> {out_json}")


if __name__ == "__main__":
    main()
