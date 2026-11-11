#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenAI Decisions API (gpt-6-luna) 死球/活球 判定客户端骨架 — 待 key 即跑 (stdlib-only)

目的: 用 Decisions API 的 typed answer(predicate/choice) 替代本地单帧 VLM,
     破"单帧歧义"天花板 (Bonsai 宽景活球误判 DEAD / Qwen 死球误判 LIVE),
     向"无人工介入全自动"推进:
       - choice(LIVE/DEAD) + confidence -> 低 confidence 自动转人工(路由)
       - predicate(is_dead, 0..1) -> 阈值化
       - 单次请求可内联最多 128 张图 -> 喂多帧时序上下文破单帧歧义

官方 schema(developers.openai.com/api/reference/decisions, 2026-10-09 核实):
  POST /v1/decisions
  req = {"model":"gpt-6-luna", "input":<str | user messages w/ images>, "questions":[...]}
  ans = {"model", "answers":[{type,name, probability? | choice?, confidence?, probabilities? ...}],
         "usage":{input_tokens,...}}
  题型 predicate{name,probability} /
       choice{choice,confidence,probabilities:[{probability,value}]} /
       score{score,confidence,probabilities:[{label,probability,value}]} /
       refusal{name,type}
  图像: 内联 base64 data URL, 单次请求最多 128 张; 不支持外链/audio/function call.

诚实标注(未实测, 待真 key 首调校正):
  - question/answer 题型字段已对官方文档核实。
  - input 内"图像消息"的精确 content part 类型名(input_image/input_text)依官方
    "user messages containing text and images" 描述做最佳映射; 用 --image-content-type /
    --text-content-type 留可调口, 首调后用 --print-raw 比对官方契约校正。
  - 向官方端点发起请求前强制校验 OPENAI_API_KEY; 无 key 绝不扣费。

依赖: 仅 Python 标准库 (urllib/json/base64)。
"""
import argparse
import base64
import json
import os
import sys
import urllib.request

DEFAULT_BASE_URL = "https://api.openai.com/v1/decisions"

DEFAULT_INSTRUCTIONS = (
    "Decide whether this NBA broadcast clip shows a LIVE-ball offensive possession "
    "or a DEAD-ball stoppage. LIVE = players actively moving, ball in play, no "
    "whistle/timeout/free-throw/break graphic. DEAD = referee whistle, timeout, "
    "free-throw, or a transition/break graphic. When multiple frames are supplied "
    "they are in chronological order — use motion/continuity across them, not a "
    "single static pose."
)

DEAD_CHOICE_DESC = (
    "Dead-ball stoppage: referee whistle, timeout, free-throw, or transition/break graphic."
)
LIVE_CHOICE_DESC = (
    "Active live-ball offense: players moving, ball in play, no whistle/timeout/free-throw/break graphic."
)


def b64encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def build_question(mode: str, name: str, instructions: str) -> dict:
    if mode == "choice":
        return {
            "type": "choice",
            "name": name,
            "instructions": instructions,
            "choices": [
                {"value": "LIVE", "description": LIVE_CHOICE_DESC},
                {"value": "DEAD", "description": DEAD_CHOICE_DESC},
            ],
        }
    # predicate: 条件 = "是否死球" (概率近 1 = DEAD)
    return {
        "type": "predicate",
        "name": name,
        "instructions": "Is this clip a DEAD-ball stoppage (whistle/timeout/free-throw/break "
                        "graphic) rather than live offense? Probability near 1 means dead.",
    }


def build_request(mode, frames, instructions, name, img_ct, txt_ct) -> dict:
    content = []
    for fp in frames:
        content.append({"type": img_ct,
                        "image_url": {"url": f"data:image/jpeg;base64,{b64encode_image(fp)}"}})
    content.append({"type": txt_ct,
                    "text": f"These {len(frames)} frame(s) are sampled in chronological order "
                            f"from one NBA broadcast clip."})
    return {
        "model": "gpt-6-luna",
        "input": [{"role": "user", "content": content}],
        "questions": [build_question(mode, name, instructions)],
    }


def call_decisions(base_url, api_key, payload, timeout=120, print_raw=False):
    # 安全护栏: 仅当目标是官方端点且无 key 时才拒绝, 避免误扣费;
    # 指向本地 mock 服务(--base-url 127.0.0.1)时允许用占位 key 跑全链路自测。
    if base_url.rstrip("/") == DEFAULT_BASE_URL.rstrip("/") and not api_key:
        raise RuntimeError("OPENAI_API_KEY 未设置: 拒绝向官方端点发起真实扣费请求 "
                           "(用 --base-url 指向 mock 服务做自测, 或提供 key)")
    req = urllib.request.Request(
        base_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.load(resp)
    if print_raw:
        sys.stderr.write("RAW RESPONSE:\n" + json.dumps(body, indent=2) + "\n")
    return body


def parse_answer(ans) -> dict:
    if not ans:
        return {"type": "missing"}
    t = ans.get("type")
    if t == "choice":
        sel = ans.get("choice")
        conf = ans.get("confidence")
        probs = {p.get("value"): p.get("probability") for p in ans.get("probabilities", [])}
        return {"type": "choice", "choice": sel, "confidence": conf, "probabilities": probs}
    if t == "predicate":
        return {"type": "predicate", "probability": ans.get("probability")}
    if t == "refusal":
        return {"type": "refusal"}
    return {"type": t, "raw": ans}


def decide(parsed, mode, conf_thr, pred_thr) -> tuple:
    """返回 (verdict, reason). verdict ∈ {LIVE, DEAD, HUMAN_REVIEW, ERROR}."""
    if parsed.get("type") == "refusal":
        return "HUMAN_REVIEW", "model_refused"
    if parsed.get("type") == "error" or parsed.get("type") == "missing":
        return "HUMAN_REVIEW", parsed.get("type")
    if mode == "choice":
        sel = parsed.get("choice")
        conf = parsed.get("confidence")
        sel_prob = (parsed.get("probabilities") or {}).get(sel)
        if conf is not None and conf < conf_thr:
            return "HUMAN_REVIEW", f"conf {conf:.2f} < {conf_thr}"
        return sel, f"conf {conf:.2f} sel_prob {sel_prob}"
    # predicate: pred_thr = (dead_cut, gap). p>=cut -> DEAD; |p-cut|<gap -> 人工
    p = parsed.get("probability")
    cut, gap = pred_thr
    if p is None or (cut - gap) < p < (cut + gap):
        return "HUMAN_REVIEW", f"predicate {p} in review band [{cut-gap:.2f},{cut+gap:.2f}]"
    return ("DEAD" if p >= cut else "LIVE"), f"predicate {p:.2f}"


def main() -> int:
    ap = argparse.ArgumentParser(description="OpenAI Decisions API LIVE/DEAD 判定客户端")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY", ""))
    ap.add_argument("--mode", choices=["choice", "predicate"], default="choice")
    ap.add_argument("--name", default=None, help="question name (默认按 mode: live_dead/is_dead)")
    ap.add_argument("--confidence-threshold", type=float, default=0.90,
                   help="choice 模式: confidence 低于此值转 HUMAN_REVIEW")
    ap.add_argument("--pred-dead", type=float, default=0.50,
                   help="predicate 模式: 概率 >= 此值判 DEAD")
    ap.add_argument("--pred-review-gap", type=float, default=0.20,
                   help="predicate 模式: |p-cut|<gap 判 HUMAN_REVIEW")
    ap.add_argument("--instructions", default=DEFAULT_INSTRUCTIONS)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--print-raw", action="store_true", help="把原始响应打到 stderr(首调校正用)")
    ap.add_argument("--out", default="")
    ap.add_argument("--expect", default="",
                   help="逗号分隔 GT(LIVE/DEAD), 与 clips 同序, 如 DEAD,LIVE,LIVE")
    ap.add_argument("--per-image", action="store_true",
                   help="每张 --images 作独立单帧请求(与本地 VLM 三帧对表)")
    ap.add_argument("--batch", default="", help="jsonl: {name,frames:[...],expected?}")
    ap.add_argument("--image-content-type", default="input_image")
    ap.add_argument("--text-content-type", default="input_text")
    ap.add_argument("images", nargs="*")
    args = ap.parse_args()

    expects = [e.strip().upper() for e in args.expect.split(",") if e.strip()] if args.expect else []

    # 护栏(快失败): 指向官方端点但无 key -> 不发起任何请求, 非零退出防误扣费
    if args.base_url.rstrip("/") == DEFAULT_BASE_URL.rstrip("/") and not args.api_key:
        print("ERROR: OPENAI_API_KEY 未设置, 拒绝向官方端点发起真实扣费请求 "
              "(用 --base-url 指向 mock 服务做自测, 或提供 key)", file=sys.stderr)
        return 3

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

    name = args.name or ("live_dead" if args.mode == "choice" else "is_dead")
    pred_thr = (args.pred_dead, args.pred_review_gap)
    results = []
    for i, clip in enumerate(clips):
        frames = clip["frames"]
        payload = build_request(args.mode, frames, args.instructions, name,
                                args.image_content_type, args.text_content_type)
        try:
            body = call_decisions(args.base_url, args.api_key, payload, args.timeout, args.print_raw)
            ans = next((a for a in body.get("answers", []) if a.get("name") == name), None)
            parsed = parse_answer(ans)
            verdict, reason = decide(parsed, args.mode, args.confidence_threshold, pred_thr)
        except Exception as e:  # noqa: BLE001
            parsed = {"type": "error", "msg": f"{type(e).__name__}: {e}"}
            verdict, reason = "ERROR", str(e)
        expect = clip.get("expected") or (expects[i] if i < len(expects) else None)
        ok = (expect is not None and verdict == expect)
        rec = {"frames": frames, "verdict": verdict, "expected": expect,
               "correct": ok, "reason": reason, "parsed": parsed}
        results.append(rec)
        tag = "OK " if ok else ("XX " if expect else "   ")
        print(f"{tag} {clip.get('name', os.path.basename(frames[0])):24s} -> {verdict:12s}"
              f"{(' (expect '+expect+')') if expect else ''} | {reason}")

    n_expect = sum(1 for x in results if x.get("expected"))
    if n_expect:
        hit = sum(1 for x in results if x.get("correct"))
        print(f"\n证伪准确率: {hit}/{n_expect}  ({100.0*hit/n_expect:.0f}%)  "
              f"[仅 {n_expect} 个代表 clip, 非统计结论]")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
