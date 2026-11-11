#!/usr/bin/env python3
"""A-1 探针：ASR word 级转写能否定位「人声讲解战术/动作」的时间窗？

背景（A4.64 / 路线 A）：
    自动识别掩护已被彻底证伪（A4.61/A4.63，specificity 不可解）。
    新路线 = 战术语义来自**人声**，工具只负责定位 + 可视化，标签由老程人工裁定。
    本探针回答一个前置问题：ASR 转写（whisper small）的错字率有多高，
    能否用「关键词命中 + word 时间戳」可靠定位讲解窗口？

方法：
    1. 关键词**不手写**：英文名/别名全部取自 tactic_library.json（实测来源）。
    2. 每段视频与其归属战术配对（tactic.source_clips 文件名 ↔ transcript.video）。
    3. 在该视频内做 sliding-window 匹配，取最小命中窗 -> 时间 = word 时间戳。
    4. 同时算 difflib 最佳模糊比 + **打印命中的真实原文片段**（自证，不靠猜）。
    输出 action_work/asr_locate_probe.json + 摘要打印。
"""
import difflib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AW = ROOT / "action_work"
LIB = AW / "tactic_library.json"
TR = AW / "asr_transcripts"
OUT = AW / "asr_locate_probe.json"

PUNCT = re.compile(r"[^\w一-鿿]+", re.UNICODE)
MAXW = 6  # 滑窗最大词数（覆盖多词英文名如 zipper backdoor）


def norm(s):
    """归一化：小写 + 去标点空白（便于跨中英匹配）。"""
    return PUNCT.sub("", (s or "").lower())


def build_words(segs):
    """把 whisper word 级 tokens 还原成词（含时间戳）。

    whisper word token 若以空格开头 = 新词起点；否则是上一个词的续字母。
    返回 [(start, end, text), ...]
    """
    words, cur = [], None
    for seg in segs:
        for w in seg.get("words") or []:
            t, s, e = w.get("word", ""), w.get("start"), w.get("end")
            if s is None or e is None:
                continue
            if t.startswith(" "):
                if cur:
                    words.append(tuple(cur))
                cur = [float(s), float(e), t.strip()]
            else:
                if cur:
                    cur[1] = float(e)
                    cur[2] += t
                else:
                    cur = [float(s), float(e), t]
        if cur:
            words.append(tuple(cur))
            cur = None
    if cur:
        words.append(tuple(cur))
    return words


def find_hit(words, kw):
    """在词流里找关键词最小命中窗。命中返回 (t0, t1, 原文片段) else None。

    同时返回该窗口内关键词的近似位置信息不足时退化为整窗时间。
    """
    k = norm(kw)
    if not k:
        return None
    n = len(words)
    for i in range(n):
        for W in range(1, min(MAXW, n - i) + 1):
            txt = "".join(words[j][2] for j in range(i, i + W))
            if k in norm(txt):
                return (words[i][0], words[i + W - 1][1], txt.strip())
    return None


def best_fuzzy(words, kw):
    """返回该视频内对关键词的最佳模糊匹配 (score, t0, t1, 片段)。"""
    k = norm(kw)
    if not k or not words:
        return None
    # 只在合适长度的词窗上比：窗口长度取关键词长度的 0.6~2.0 倍
    lo, hi = max(1, int(len(k) * 0.6)), max(int(len(k) * 2.0) + 2, 12)
    best = (0.0, None, None, "")
    n = len(words)
    for i in range(n):
        for W in (1, 2, 3):
            if i + W > n:
                continue
            txt = norm("".join(words[j][2] for j in range(i, i + W)))
            if not txt or not (lo <= len(txt) <= hi):
                continue
            r = difflib.SequenceMatcher(None, k, txt).ratio()
            if r > best[0]:
                best = (r, words[i][0], words[i + W - 1][1],
                        "".join(words[j][2] for j in range(i, i + W)).strip())
    return best


def main():
    lib = json.load(open(LIB, encoding="utf-8"))
    tactics = lib.get("tactics", {})
    files = sorted(p for p in TR.glob("*_asr_small.json"))
    print(f"[A-1] 转写 {len(files)} 份 ｜ 战术库 {len(tactics)} 条")

    # video 名 -> transcript 路径
    by_base = {}
    for p in files:
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        v = d.get("video") or ""
        by_base[os.path.basename(v)] = p

    rows = []
    n_pair = n_exact = 0
    ratios = []
    for name, t in tactics.items():
        keys = [name] + list(t.get("aliases") or [])
        for clip in t.get("source_clips") or []:
            p = by_base.get(os.path.basename(clip))
            if not p:
                continue  # 该战术的视频无转写（未覆盖）
            d = json.load(open(p, encoding="utf-8"))
            words = build_words(d.get("segments") or [])
            if not words:
                continue
            n_pair += 1
            hit = None
            used = None
            for k in keys:
                hit = find_hit(words, k)
                if hit:
                    used = k
                    break
            if hit:
                n_exact += 1
                rows.append({"tactic": name, "clip": os.path.basename(clip),
                             "kw": used, "mode": "exact",
                             "t0": round(hit[0], 2), "t1": round(hit[1], 2),
                             "span": hit[2][:80], "score": 1.0})
            else:
                fz = None
                for k in keys:
                    b = best_fuzzy(words, k)
                    if b and (fz is None or b[0] > fz[0]):
                        fz = b
                        used = k
                ratios.append(fz[0] if fz else 0.0)
                rows.append({"tactic": name, "clip": os.path.basename(clip),
                             "kw": used, "mode": "fuzzy",
                             "t0": round(fz[1], 2) if fz and fz[1] is not None else None,
                             "t1": round(fz[2], 2) if fz and fz[2] is not None else None,
                             "span": (fz[3] if fz else "")[:80],
                             "score": round(fz[0], 3) if fz else 0.0})

    ratios.sort()
    med = ratios[len(ratios) // 2] if ratios else 0.0
    print("\n=== 战术名/别名 精确命中 ===")
    print(f"配对 {n_pair} 对（战术×视频）｜ 精确命中 {n_exact} "
          f"({100.0*n_exact/max(n_pair,1):.1f}%)")
    if ratios:
        print(f"未精确命中者的最佳模糊比: 中位 {med:.3f} ｜ "
              f"min {ratios[0]:.3f} ｜ max {ratios[-1]:.3f}")

    print("\n=== 未精确命中样例（看真实错字，自证）===")
    shown = 0
    for r in rows:
        if r["mode"] == "fuzzy" and shown < 12:
            print(f"  [{r['tactic']}] kw={r['kw']!r} score={r['score']:.2f} "
                  f"@{r['t0']}s  原文={r['span']!r}")
            shown += 1
    print("\n=== 精确命中样例 ===")
    shown = 0
    for r in rows:
        if r["mode"] == "exact" and shown < 8:
            print(f"  [{r['tactic']}] kw={r['kw']!r} @{r['t0']}-{r['t1']}s  "
                  f"原文={r['span']!r}")
            shown += 1

    json.dump({"n_transcripts": len(files), "n_tactics": len(tactics),
               "n_pair": n_pair, "n_exact": n_exact,
               "exact_rate": round(n_exact / max(n_pair, 1), 4),
               "fuzzy_median": round(med, 4), "rows": rows},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n-> {OUT}")


if __name__ == "__main__":
    main()
