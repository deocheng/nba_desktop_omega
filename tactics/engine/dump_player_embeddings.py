#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dump_player_embeddings —— 给 stabilize 产物 ball_tracks.json 每帧每球员生成 DINOv2-small
CLS 384d 嵌入，落盘为 id_identity_audit.py 需要的 emb_dump.json。

用法:
  python3 dump_player_embeddings.py --tracks <seg>/ball_tracks.json \
      --frames-dir <seg>/frames --out <seg>/emb_dump.json
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

# 离线 + 清 broker（A0 铁律）
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ["PYTHONPATH"] = ""
os.environ["YOLO_CONFIG_DIR"] = "/tmp/yolo_cfg"

ROOT = Path(str(tactics_data_file("")))
sys.path.insert(0, str(ROOT / "engine"))
import stabilize_tracks_v2 as S  # 复用 embed_crops


def crop_box(img, b, margin=0.1):
    h, w = img.shape[:2]
    x1, y1, x2, y2 = b
    bw, bh = x2 - x1, y2 - y1
    x1 = max(0, int(x1 - margin * bw)); y1 = max(0, int(y1 - margin * bh))
    x2 = min(w, int(x2 + margin * bw)); y2 = min(h, int(y2 + margin * bh))
    return img[y1:y2, x1:x2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracks", required=True)
    ap.add_argument("--frames-dir", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    d = json.loads(Path(a.tracks).read_text(encoding="utf-8"))
    fdir = Path(a.frames_dir)
    out = []
    for rec in d:
        players = rec.get("players") or []
        fname = rec.get("file") or f"f{int(rec.get('frame', 0)) + 1:05d}.jpg"
        ip = fdir / fname
        if not ip.exists():
            out.append({"embs": []}); continue
        img = cv2.imread(str(ip))
        if img is None:
            out.append({"embs": []}); continue
        crops = []
        for p in players:
            b = p.get("bbox")
            if not b or len(b) != 4:
                crops.append(None); continue
            crops.append(crop_box(img, b))
        embs = S.embed_crops([c for c in crops if c is not None])
        # 对齐 players 顺序（None 处填零向量）
        ei = 0; row = []
        for c in crops:
            if c is None:
                row.append([0.0] * 384)
            else:
                row.append(embs[ei].tolist()); ei += 1
        out.append({"embs": row})
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    n_emb = sum(len(r["embs"]) for r in out)
    print(f"[emb] {Path(a.tracks).parent.name}: {len(out)} 帧, {n_emb} 嵌入 -> {a.out}", flush=True)


if __name__ == "__main__":
    main()
