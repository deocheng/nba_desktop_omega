#!/usr/bin/env python3
"""A-2：给「画面实战片段」配上「人声在同一时间窗讲了什么」。

路线 A 的核心纪律：**战术语义来自人声，工具不猜**。
本脚本不做任何战术识别/打分/排序，只做一件事：
    对每个已经画面定位好的实战片段 (video, t0, t1)，
    把该时间窗内解说员说的原话（ASR，带时间戳）摘出来，
    并标出窗口内出现的领域术语锚点（含真实原文片段，供老程裁定）。

输入（均为既有产物，不重跑模型）：
    action_work/tactic_notes_batch_full/batch_results.json  画面片段 + 时间窗
    action_work/asr_transcripts/*_asr_small.json            人声转写(word 级时间戳)
    action_work/tactic_library.json                         术语来源(实测, 非手写)
输出：
    action_work/asr_segment_annotation.json                 逐段 {画面窗 + 人声原文 + 术语锚点}
    action_work/asr_segment_annotation.md                   人可读速览
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import difflib
import glob
import json
import os
import re
import sys
from pathlib import Path

from common.nba_paths import data_file

ROOT = Path(__file__).resolve().parent.parent
AW = ROOT / "action_work"
sys.path.insert(0, str(ROOT / "engine"))
from asr_locate_probe import build_words, norm  # 复用 A-1 的词流还原

FULL = AW / "tactic_notes_batch_full" / "batch_results.json"
LIB = AW / "tactic_library.json"
TR = AW / "asr_transcripts"
OUTJ = AW / "asr_segment_annotation.json"
OUTM = AW / "asr_segment_annotation.md"

CJK = re.compile(r"[\u4e00-\u9fff]")
VID_DIR = Path(str(data_file("NBA战术笔记")))


def load_lexicon():
    """领域术语来源全部取自实测数据（文件名 + 战术库），不手写。"""
    lib = json.load(open(LIB, encoding="utf-8"))
    tactics = lib.get("tactics", {})
    terms = set()
    for name, t in tactics.items():
        if len(norm(name)) >= 3:
            terms.add(name)
        for a in (t.get("aliases") or []):
            if len(norm(a)) >= 3:
                terms.add(a)
    # 文件名里的中文引号术语
    for p in list(VID_DIR.rglob("*.mp4")) + list(VID_DIR.rglob("*.mkv")):
        for m in re.findall(r"[\u201c\u201d\"\u300a]([^\u201d\"\u300b]{2,10})[\u201d\"\u300b]",
                            os.path.basename(p)):
            if CJK.search(m):
                terms.add(m.strip())
    return sorted(terms), tactics


def words_in_window(words, t0, t1):
    """取落在 [t0,t1] 内的词（词的中心点落窗内即算）。"""
    out = []
    for s, e, txt in words:
        if t1 >= s >= t0 or (s <= t0 <= e) or (e >= t1 >= s):
            out.append((s, e, txt))
    return out


def cues_in_span(span_words, terms):
    """在给定词片段内找术语锚点：先精确，再模糊(>=0.8)，均返回真实原文。"""
    if not span_words:
        return []
    joined = "".join(w[2] for w in span_words)
    nj = norm(joined)
    hits = []
    for t in terms:
        nt = norm(t)
        if not nt:
            continue
        if nt in nj:                      # 精确
            # 定位大致时刻：取该词片段起点
            hits.append({"term": t, "mode": "exact", "score": 1.0,
                         "t": round(span_words[0][0], 2)})
            continue
        # 模糊：先在整段 joined 上比一次，够高再局部滑窗找最佳
        if len(nt) >= 3:
            best = (0.0, None)
            n = len(span_words)
            for i in range(n):
                for W in (1, 2, 3):
                    if i + W > n:
                        continue
                    txt = norm("".join(w[2] for j, w in
                                       enumerate(span_words[i:i + W])))
                    if not txt:
                        continue
                    r = difflib.SequenceMatcher(None, nt, txt).ratio()
                    if r > best[0]:
                        best = (r, span_words[i][0])
            if best[0] >= 0.8:
                hits.append({"term": t, "mode": "fuzzy",
                             "score": round(best[0], 3),
                             "t": round(best[1], 2)})
    return hits


def main():
    terms, tactics = load_lexicon()
    full = json.load(open(FULL, encoding="utf-8"))
    rows = full.get("rows", []) if isinstance(full, dict) else full
    print(f"[A-2] 术语 {len(terms)} 条 ｜ 批次 {len(rows)} 行")

    # video basename -> transcript words
    tr_words, tr_raw = {}, {}
    for p in sorted(TR.glob("*_asr_small.json")):
        d = json.load(open(p, encoding="utf-8"))
        b = os.path.basename(d.get("video") or "")
        w = build_words(d.get("segments") or [])
        tr_words[b] = w
        tr_raw[b] = d

    out, n_seg = [], 0
    n_asr = n_text = n_cue = 0
    for r in rows:
        vid = os.path.basename(r.get("video") or "")
        ep = r.get("ep", "")
        gt = r.get("gt_models") or []
        for si, sd in enumerate(r.get("seg_detail") or []):
            n_seg += 1
            t0, t1 = sd.get("t0"), sd.get("t1")
            words = tr_words.get(vid)
            has = words is not None
            span = words_in_window(words, t0, t1) if has else []
            text = "".join(w[2] for w in span).strip()
            cues = cues_in_span(span, terms) if span else []
            if has:
                n_asr += 1
            if text:
                n_text += 1
            if cues:
                n_cue += 1
            out.append({
                "seg": f"{ep}_s{si}", "ep": ep, "video": vid,
                "t0": t0, "t1": t1, "episode_tactics": gt,
                "has_asr": has, "n_words": len(span),
                "narration": text, "cues": cues,
            })

    print("\n=== 画面 x 人声 联结结果（数字现读）===")
    print(f"画面片段总数        : {n_seg}")
    print(f"有 ASR 转写的片段  : {n_asr} ({100.0*n_asr/max(n_seg,1):.1f}%)")
    print(f"窗口内摘到人声原文 : {n_text} ({100.0*n_text/max(n_seg,1):.1f}%)")
    print(f"窗口内含领域术语   : {n_cue} ({100.0*n_cue/max(n_seg,1):.1f}%)")

    avg = sum(o["n_words"] for o in out) / max(n_seg, 1)
    print(f"平均每段人声词数   : {avg:.1f}")

    print("\n=== 样例自证（人声原文是否真在描述画面动作）===")
    shown = 0
    for o in out:
        if o["narration"] and shown < 5:
            print(f"\n[{o['seg']}] {o['video'][:38]}  {o['t0']}-{o['t1']}s")
            print(f"  人声: {o['narration'][:150]}")
            if o["cues"]:
                print("  锚点: " + ", ".join(
                    f"{c['term']}({c['mode']}{c['score']})@{c['t']}s"
                    for c in o["cues"][:6]))
            shown += 1

    json.dump({"n_seg": n_seg, "n_asr": n_asr, "n_text": n_text,
               "n_cue": n_cue, "segments": out},
              open(OUTJ, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 人可读 markdown
    with open(OUTM, "w", encoding="utf-8") as f:
        f.write("# ASR 人声 x 画面实战片段 联结表（路线 A）\n\n")
        f.write(f"- 画面片段 {n_seg} ｜ 有转写 {n_asr} ｜ 有人声原文 {n_text} "
                f"｜ 含术语 {n_cue}\n")
        f.write("- **战术标签必须由老程人工裁定，工具不猜。**\n\n")
        for o in out:
            f.write(f"## {o['seg']} （{o['t0']}–{o['t1']}s）\n")
            f.write(f"- 视频：{o['video']}\n")
            if o["episode_tactics"]:
                f.write(f"- 本期讲解：{', '.join(o['episode_tactics'])}\n")
            f.write(f"- 人声原文：{o['narration'][:300] or '（无）'}\n")
            if o["cues"]:
                f.write("- 术语锚点：" + ", ".join(
                    f"{c['term']}({c['mode']}{c['score']})@{c['t']}s"
                    for c in o["cues"]) + "\n")
            f.write("\n")
    print(f"\n-> {OUTJ}\n-> {OUTM}")


if __name__ == "__main__":
    main()
