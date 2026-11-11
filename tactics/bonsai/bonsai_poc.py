#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bonsai-2-27B-VLM 死球/活球 二分类 PoC 客户端 (stdlib-only, 无第三方依赖)

目标: 用 PrismML 的 Ternary-Bonsai-2-27B-VLM 替代人工目测, 判别 NBA 广播帧是
      LIVE(活球进攻) 还是 DEAD(吹停/暂停/罚球/转场).

前置: 老程已在本机用 VPN 完成:
      1) cd bonsai && ./setup.sh            # 构建 PrismML llama.cpp fork + 下载 27B GGUF + mmproj
      2) ./scripts/start_llama_server.sh    # 起 OpenAI 兼容服务 :8080, 自动挂 mmproj
      本脚本只负责把代表帧发给服务并解析 LIVE/DEAD.

接口: llama-server 的 /v1/chat/completions (OpenAI 视觉格式, image_url + text)
依赖: 仅 Python 标准库 (urllib/json/base64) — 不要求任何 venv.
"""
import argparse
import base64
import json
import os
import re
import sys
import urllib.request

DEFAULT_PROMPT = (
    "In this NBA broadcast frame, is the on-court action a LIVE-ball offensive "
    "possession (players actively playing, ball in motion, no stoppage), or a "
    "DEAD-ball stoppage such as a referee whistle, timeout, free-throw, or a "
    "transition/break graphic? Answer with exactly one word: LIVE or DEAD."
)


def b64encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def judge(server: str, img_path: str, question: str, max_tokens: int = 1024) -> dict:
    data_url = f"data:image/jpeg;base64,{b64encode_image(img_path)}"
    payload = {
        "model": "bonsai",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": question},
                ],
            }
        ],
        "max_tokens": max_tokens,
        "temperature": 0.0,
    }
    req = urllib.request.Request(
        f"{server.rstrip('/')}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        body = json.load(resp)
    raw = body["choices"][0]["message"]["content"].strip()
    # Thinking VLM: reasoning comes first, the final LIVE/DEAD decision comes last.
    # Take the trailing standalone LIVE/DEAD token so reasoning text can't mis-lead.
    tokens = re.findall(r"\b(LIVE|DEAD)\b", raw.upper())
    verdict = tokens[-1] if tokens else "UNKNOWN"
    return {"verdict": verdict, "raw": raw}


def main() -> int:
    ap = argparse.ArgumentParser(description="Bonsai-2-27B-VLM LIVE/DEAD 二分类 PoC")
    ap.add_argument("--server", default="http://127.0.0.1:8080")
    ap.add_argument("--question", default=DEFAULT_PROMPT)
    ap.add_argument("--out", default="")
    ap.add_argument("--expect", default="",
                   help="逗号分隔的 ground-truth 标签(LIVE/DEAD), 与图片同序, 如 DEAD,LIVE,LIVE")
    ap.add_argument("--max-tokens", type=int, default=1024,
                   help="生成 token 上限; thinking VLM 可能把预算烧在推理上导致答案为空, 按需调大")
    ap.add_argument("images", nargs="+")
    args = ap.parse_args()

    expects = [e.strip().upper() for e in args.expect.split(",") if e.strip()] if args.expect else []
    results = []
    for i, img in enumerate(args.images):
        try:
            r = judge(args.server, img, args.question, max_tokens=args.max_tokens)
        except Exception as e:  # noqa: BLE001
            r = {"verdict": "ERROR", "raw": f"{type(e).__name__}: {e}"}
        expect = expects[i] if i < len(expects) else None
        ok = (expect is not None and r["verdict"] == expect)
        results.append({"image": img, "verdict": r["verdict"],
                        "expected": expect, "correct": ok, "raw": r["raw"]})
        tag = "OK " if ok else ("XX " if expect else "   ")
        print(f"{tag} {os.path.basename(img):28s} -> {r['verdict']:6s}"
              f"{(' (expect '+expect+')') if expect else ''} | {r['raw']}")

    if expects:
        n = len(expects)
        hit = sum(1 for x in results if x.get("correct"))
        print(f"\n证伪准确率: {hit}/{n}  ({100.0*hit/n:.0f}%)  [仅 {n} 张代表帧, 非统计结论]")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
