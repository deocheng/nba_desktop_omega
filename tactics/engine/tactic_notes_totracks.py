#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tactic_notes_totracks.py —— 把 segment_detect_track 的 tracks.json 转成
tactic_match_real.py 读取的 ball_tracks.json 契约。

契约(输出, list, 每帧一条):
  {"frame": idx, "file": "f00001.jpg",
   "ball": {"bbox":[x0,y0,x1,y1],"conf":c} | null,
   "players": [{"track_id": id, "bbox":[x0,y0,x1,y1], "conf": c, "team": null}, ...]}

用法:
  tactic_notes_totracks.py <tracks.json> <frames.json 或 frames 目录> <out.json>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def convert(tracks_json, frames_ref, out, team_of=None):
    """把 segment_detect_track 的 tracks.json 转成匹配契约(list)。返回输出路径。

    team_of: 可选 dict[(idx,tid)] -> 0/1（assign_team.compute_team_of 的逐帧队色）。
             传入时把 team 写入每帧每球员；不传保持 None（向后兼容）。
    """
    d = json.load(open(tracks_json, encoding="utf-8"))
    ref = Path(frames_ref)
    if ref.is_dir():
        files = sorted(p.name for p in ref.glob("f*.jpg"))
        idx2file = {i: n for i, n in enumerate(files)}
    else:
        recs = json.load(open(ref, encoding="utf-8"))
        idx2file = {r["idx"]: Path(r["path"]).name for r in recs}

    outl = []
    for fr in d["frames"]:
        idx = fr["idx"]
        pl = []
        for p in fr.get("players", []):
            tm = None
            if team_of is not None:
                tm = team_of.get((idx, int(p["id"])))
            pl.append({"track_id": int(p["id"]), "bbox": [round(v, 1) for v in p["box"]],
                       "conf": round(float(p["conf"]), 4), "team": tm})
        b = fr.get("ball") or {}
        bx = b.get("box")
        ball = {"bbox": [round(v, 1) for v in bx], "conf": round(float(b.get("conf", 0.0)), 4)} if bx else None
        outl.append({"frame": idx, "file": idx2file.get(idx), "ball": ball, "players": pl})

    Path(out).write_text(json.dumps(outl, ensure_ascii=False), encoding="utf-8")
    nb = sum(1 for r in outl if r["ball"])
    return out, len(outl), nb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tracks_json")
    ap.add_argument("frames_ref", help="frames.json 路径, 或 frames 目录")
    ap.add_argument("out")
    a = ap.parse_args()
    out, n, nb = convert(a.tracks_json, a.frames_ref, a.out)
    print(f"[totracks] {n} 帧 → {out}  (有球帧 {nb})")


if __name__ == "__main__":
    main()
