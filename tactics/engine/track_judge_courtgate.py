#!/usr/bin/env python3
"""A5.8 对老程裁定的 8 条轨迹跑 A4.63 的「场上脚点门」，看能剔掉几条场外人。

判据：`court_filter.court_mask` 地板掩膜 + 脚点在掩膜内 ⇒ 场上。
输出每条的 on_frac（脚点在场上的帧占比）与「是否会被 min_frac=0.5 门剔掉」。
"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import sys
from pathlib import Path

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
sys.path.insert(0, str(ROOT / "engine"))
import court_filter as cf
import cv2

SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments" / "ep24_s1"

# (条目, src, tid, 老程定性, 老程裁定)
TARGETS = [
    ("ep24_s1#21", "tracks.json", 21, "观众", "换人"),
    ("ep24_s1#190", "tracks.json", 190, "替补席+观众", "换人"),
    ("ep24_s1#246", "tracks.json", 246, "替补席+观众", "换人"),
    ("ep24_s1#269", "tracks.json", 269, "场上球员", "同一人"),
    ("ep24_s1#309", "tracks.json", 309, "替补席教练", "换人"),
    ("ep24_s1#336", "tracks.json", 336, "观众", "换人"),
    ("B:ep24_s1#88", "tracks_b.json", 88, "观众", "换人"),
    ("B:ep24_s1#116", "tracks_b.json", 116, "观众", "换人"),
]


def main():
    files = sorted((SEGD / "frames").glob("f*.jpg"))
    srcs = {}
    for key, src, tid, subj, verd in TARGETS:
        if src not in srcs:
            srcs[src] = json.load(open(SEGD / src))
    # 逐帧掩膜缓存
    masks = {}
    all_frames = set()
    for src, tr in srcs.items():
        for fr in tr["frames"]:
            for p in fr.get("players", []):
                if p["id"] in {t[2] for t in TARGETS if t[1] == src}:
                    all_frames.add(fr["idx"])
    print(f"需要算掩膜的帧: {len(all_frames)}")
    for idx in sorted(all_frames):
        if idx >= len(files):
            continue
        img = cv2.imread(str(files[idx]))
        if img is None:
            continue
        r = cf.court_mask(img)
        masks[idx] = (None if r is None else r[0], None if r is None else r[1])

    print(f"\n{'key':<16}{'老程定性':<12}{'n':>4}{'on_frac':>9}  {'掩膜判据':<10} 判定")
    rows = []
    for key, src, tid, subj, verd in TARGETS:
        tr = srcs[src]
        tot = inside = 0
        modes = {}
        for fr in tr["frames"]:
            for p in fr.get("players", []):
                if p["id"] != tid:
                    continue
                fx, fy = cf._foot(p["box"])
                m, mode = masks.get(fr["idx"], (None, None))
                tot += 1
                if m is not None:
                    modes[mode] = modes.get(mode, 0) + 1
                    H, W = m.shape
                    if 0 <= fx < W and 0 <= fy < H and m[min(int(fy), H - 1), min(int(fx), W - 1)] > 0:
                        inside += 1
        frac = inside / tot if tot else 0
        keep = frac >= 0.5
        want_drop = "场上球员" not in subj
        ok = "✅剔掉" if (not keep and want_drop) else ("✅留下" if (keep and not want_drop) else "❌漏网/误删")
        mode = max(modes, key=modes.get) if modes else "n/a"
        print(f"{key:<16}{subj:<12}{tot:>4}{frac:>9.2f}  {mode:<10} {ok}")
        rows.append({"key": key, "tid": tid, "src": src, "subject": subj,
                     "verdict": verd, "n": tot, "on_frac": round(frac, 3),
                     "keep": keep, "mask_mode": mode})

    out = ROOT / "action_work" / "track_judge" / "courtgate_ep24_s1.json"
    json.dump(rows, open(out, "w"), ensure_ascii=False, indent=1)
    print("\n->", out)
    n_ok = sum(r["keep"] == ("场上球员" == r["subject"]) for r in rows)
    print(f"场上脚点门判定正确: {n_ok}/{len(rows)}")


if __name__ == "__main__":
    main()
