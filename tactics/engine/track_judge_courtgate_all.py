#!/usr/bin/env python3
"""A5.8b 对裁定工作台**全部 38 条**（5 个段）跑场上脚点门。

目的：检验 ep24_s1 的「8/8 完美分离」是真规律还是**单段过拟合**（A4.60 栽过的坑）。
输出 on_frac 分布；若呈双峰且谷区远离 0.5 ⇒ 门稳定；若中段密集 ⇒ 门不可靠。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import re
import sys
from collections import Counter
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
sys.path.insert(0, str(ROOT / "engine"))
import court_filter as cf
import cv2

JD = ROOT / "action_work" / "track_judge"
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"


def load_items():
    h = (JD / "index.html").read_text(encoding="utf-8")
    return json.loads(re.search(r"\[\{.*\}\]", h.split("\n")[31], re.S).group(0))


def main():
    items = load_items()
    srcs = {}
    rows = []
    for it in items:
        seg, tid = it["seg"], it["tid"]
        src_name = "tracks_b.json" if it["key"].startswith("B:") else "tracks.json"
        k = (seg, src_name)
        if k not in srcs:
            srcs[k] = json.load(open(SEGD / seg / src_name))
            files = sorted((SEGD / seg / "frames").glob("f*.jpg"))
            srcs[k + ("_files",)] = files
        files = srcs[k + ("_files",)]
        tr = srcs[k]
        tot = inside = 0
        modes = Counter()
        for fr in tr["frames"]:
            hit = [p for p in fr.get("players", []) if p["id"] == tid]
            if not hit:
                continue
            if fr["idx"] >= len(files):
                continue
            img = cv2.imread(str(files[fr["idx"]]))
            if img is None:
                continue
            r = cf.court_mask(img)
            for p in hit:
                fx, fy = cf._foot(p["box"])
                tot += 1
                if r is None or r[0] is None:   # 掩膜不可靠 → 本帧不参与判据
                    modes["n/a"] += 1
                    continue
                m, mode = r
                modes[mode] += 1
                H, W = m.shape
                if 0 <= fx < W and 0 <= fy < H and \
                        m[min(int(fy), H - 1), min(int(fx), W - 1)] > 0:
                    inside += 1
        frac = inside / tot if tot else 0.0
        rows.append({"key": it["key"], "seg": seg, "tid": tid, "src": src_name,
                     "n": it["n"], "span": it["span"], "auto": it["auto"],
                     "on_frac": round(frac, 3), "tot": tot,
                     "mask_mode": modes.most_common(1)[0][0] if modes else "n/a"})

    rows.sort(key=lambda r: r["on_frac"])
    print(f"{'key':<16}{'n':>4} {'span':<10}{'on_frac':>8}  {'掩膜':<8} auto")
    for r in rows:
        print(f"{r['key']:<16}{r['n']:>4} {r['span']:<10}{r['on_frac']:>8}  "
              f"{r['mask_mode']:<8} {r['auto']}")

    fr = sorted(r["on_frac"] for r in rows)
    bins = Counter(int(v * 10) for v in fr)
    print("\non_frac 直方图（每 0.1 一档）:")
    for b in sorted(bins):
        bar = "#" * bins[b]
        print(f"  {b/10:.1f}-{(b+1)/10:.1f}  {bins[b]:>2}  {bar}")
    lo = [v for v in fr if v < 0.5]
    hi = [v for v in fr if v >= 0.5]
    print(f"\n判为「场外」(<0.5): {len(lo)} 条，最大 {max(lo) if lo else '-'}")
    print(f"判为「场上」(≥0.5): {len(hi)} 条，最小 {min(hi) if hi else '-'}")
    gap = (min(hi) - max(lo)) if (lo and hi) else None
    print(f"分离带 gap = {gap:.3f}" if gap is not None else "分离带: 无法计算")
    print(f"中位 {fr[len(fr)//2]:.2f}  p25 {fr[len(fr)//4]:.2f}  p75 {fr[3*len(fr)//4]:.2f}")

    for seg in sorted({r["seg"] for r in rows}):
        s = [r["on_frac"] for r in rows if r["seg"] == seg]
        print(f"  {seg}: n={len(s)} frac={[round(v,2) for v in sorted(s)]}")

    out = JD / "courtgate_all38.json"
    json.dump(rows, open(out, "w"), ensure_ascii=False, indent=1)
    print("\n->", out)


if __name__ == "__main__":
    main()
