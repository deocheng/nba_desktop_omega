#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地 Decisions 等价客户端 (stdlib-only): 用本地 llama-server 上的 VLM 复刻 OpenAI Decisions 机制

为什么本地能做:
  - Qwen2.5-VL 等本地 VLM 原生支持**多图输入**(一张请求喂 N 帧) -> 破"单帧歧义"(Decisions 的 128 图同理)。
  - llama.cpp server 的 /v1/chat/completions 支持 `logprobs`+`top_logprobs` -> 拿到首词 LIVE/DEAD 的
    **真实概率分布**, 即本地的"confidence", 等价于 Decisions choice 的 probabilities + confidence。
  - 全程离线、无 key、无云端, 机制与云端 Decisions API 一致: 高置信自动决、低置信转人工。

机制 (对标 Decisions choice):
  1) 把候选窗口的 N 帧(<=若干)作为一条 user message 的多个 image_url 部分发出;
  2) prompt 强制"只答一个词 LIVE 或 DEAD";
  3) 取首生成 token 的 top_logprobs, 找 LIVE/DEAD 两词概率 -> conf = max(P), verdict = argmax;
  4) conf < --confidence-threshold(默认 0.90) 或两词都不在 top_logprobs -> 判 HUMAN_REVIEW。

依赖: 仅 Python 标准库。目标 server = 本地 llama-server (OpenAI 兼容), 如:
  bin/mac/llama-server -m models/qwen25vl-3b/Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf \
      --mmproj models/qwen25vl-3b/mmproj-model-f16.gguf --port 8077
"""
import argparse
import base64
import json
import math
import os
import sys
import urllib.request

DEFAULT_SERVER = "http://127.0.0.1:8077"

DEFAULT_PROMPT = (
    "These frames are sampled in chronological order from one NBA broadcast clip. "
    "Decide if it shows a LIVE-ball offensive possession or a DEAD-ball stoppage "
    "(whistle/timeout/free-throw/break graphic). Use motion across frames, not a single "
    "static pose. Answer with EXACTLY ONE WORD: LIVE or DEAD."
)


def b64encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def build_request(frames, prompt, top_logprobs=10, max_tokens=4):
    content = [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64encode_image(fp)}"}}
               for fp in frames]
    content.append({"type": "text", "text": prompt})
    return {
        "model": "local",
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "logprobs": True,
        "top_logprobs": top_logprobs,
    }


def _prob_of(entry):
    """logprobs.content[i].top_logprobs[j] 可能含 logprob 或已转 prob; 统一成概率。"""
    if "prob" in entry and entry["prob"] is not None:
        return float(entry["prob"])
    if "logprob" in entry and entry["logprob"] is not None:
        return math.exp(float(entry["logprob"]))
    return 0.0


def parse_verdict(body) -> dict:
    """从 chat completions 响应提取 LIVE/DEAD 概率 + confidence。

    兼容两种响应: 标准 logprob(需 exp) 与 server 开 post_sampling_probs 后的 prob。
    """
    try:
        choice = body["choices"][0]
    except (KeyError, IndexError):
        return {"type": "missing", "reason": "no choices"}
    raw = (choice.get("message", {}).get("content") or "").strip()
    lp = choice.get("logprobs")
    if not lp or not lp.get("content"):
        # 退化: 无 logprobs -> 用文本 regex, confidence 置 None(必转人工)
        import re
        toks = re.findall(r"\b(LIVE|DEAD)\b", raw.upper())
        v = toks[-1] if toks else "UNKNOWN"
        return {"type": "text_fallback", "verdict": v, "confidence": None, "raw": raw}
    # 取首个生成 token 的 top_logprobs
    # 注意: Qwen 把 LIVE 切成 "L"+"IVE" / DEAD 切成 "DE"+"AD" -> 必须用前缀匹配聚合,
    # 否则会丢弃 "L"/"DE" 这些主导概率质量, 严重低估置信度(实测 0.74 vs 真实 ~0.97)。
    first = lp["content"][0]
    tops = first.get("top_logprobs", [])
    scores = {}
    for t in tops:
        tok = (t.get("token") or "").strip().upper()
        if not tok:
            continue  # 空 token(EOS)不计入
        if tok.startswith("LIVE") or "LIVE".startswith(tok):
            scores["LIVE"] = scores.get("LIVE", 0.0) + _prob_of(t)
        elif tok.startswith("DEAD") or "DEAD".startswith(tok):
            scores["DEAD"] = scores.get("DEAD", 0.0) + _prob_of(t)
    if not scores:
        return {"type": "no_token", "verdict": "UNKNOWN", "confidence": None, "raw": raw}
    total = sum(scores.values()) or 1.0
    probs = {k: v / total for k, v in scores.items()}
    verdict = "LIVE" if probs.get("LIVE", 0) >= probs.get("DEAD", 0) else "DEAD"
    conf = max(probs.get("LIVE", 0.0), probs.get("DEAD", 0.0))
    return {"type": "logprobs", "verdict": verdict, "confidence": conf,
            "p_live": probs.get("LIVE", 0.0), "p_dead": probs.get("DEAD", 0.0), "raw": raw}


def decide(parsed, conf_thr) -> tuple:
    if parsed.get("type") in ("missing", "no_token", "text_fallback"):
        return "HUMAN_REVIEW", parsed.get("type")
    if parsed.get("confidence") is None or parsed["confidence"] < conf_thr:
        return "HUMAN_REVIEW", f"conf {parsed.get('confidence')} < {conf_thr}"
    return parsed["verdict"], f"conf {parsed['confidence']:.2f} (LIVE {parsed.get('p_live',0):.2f}/DEAD {parsed.get('p_dead',0):.2f})"


def call_local(server, payload, timeout=120, print_raw=False):
    req = urllib.request.Request(
        f"{server.rstrip('/')}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.load(resp)
    if print_raw:
        sys.stderr.write("RAW RESPONSE:\n" + json.dumps(body, indent=2) + "\n")
    return body


def main() -> int:
    ap = argparse.ArgumentParser(description="本地 VLM LIVE/DEAD 判定(多帧+logprobs 置信度)")
    ap.add_argument("--server", default=DEFAULT_SERVER)
    ap.add_argument("--confidence-threshold", type=float, default=0.90)
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--top-logprobs", type=int, default=10)
    ap.add_argument("--max-tokens", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--print-raw", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--expect", default="", help="逗号分隔 GT(LIVE/DEAD), 与 clips 同序")
    ap.add_argument("--per-image", action="store_true", help="每张 --images 作独立单帧请求(对表用)")
    ap.add_argument("--batch", default="", help="jsonl: {name,frames:[...],expected?}")
    ap.add_argument("images", nargs="*")
    args = ap.parse_args()

    expects = [e.strip().upper() for e in args.expect.split(",") if e.strip()] if args.expect else []

    if args.batch:
        clips = [json.loads(l) for l in open(args.batch, encoding="utf-8") if l.strip()]
    elif args.images:
        if args.per_image:
            clips = [{"frames": [f], "expected": (expects[i] if i < len(expects) else None)}
                     for i, f in enumerate(args.images)]
        else:
            clips = [{"frames": args.images, "expected": (expects[0] if expects else None)}]
    else:
        print("ERROR: 需提供 --images 或 --batch", file=sys.stderr)
        return 2

    results = []
    for i, clip in enumerate(clips):
        payload = build_request(clip["frames"], args.prompt, args.top_logprobs, args.max_tokens)
        try:
            body = call_local(args.server, payload, args.timeout, args.print_raw)
            parsed = parse_verdict(body)
            verdict, reason = decide(parsed, args.confidence_threshold)
        except Exception as e:  # noqa: BLE001
            parsed = {"type": "error", "msg": f"{type(e).__name__}: {e}"}
            verdict, reason = "ERROR", str(e)
        expect = clip.get("expected") or (expects[i] if i < len(expects) else None)
        ok = (expect is not None and verdict == expect)
        rec = {"frames": clip["frames"], "verdict": verdict, "expected": expect,
               "correct": ok, "reason": reason, "parsed": parsed}
        results.append(rec)
        tag = "OK " if ok else ("XX " if expect else "   ")
        print(f"{tag} {clip.get('name', os.path.basename(clip['frames'][0])):24s} -> {verdict:12s}"
              f"{(' (expect '+expect+')') if expect else ''} | {reason}")

    n_expect = sum(1 for x in results if x.get("expected"))
    if n_expect:
        hit = sum(1 for x in results if x.get("correct"))
        print(f"\n证伪准确率: {hit}/{n_expect}  ({100.0*hit/n_expect:.0f}%)  [仅 {n_expect} clip, 非统计结论]")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
