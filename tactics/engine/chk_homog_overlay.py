"""A5.14-b 决定性自证图：把「模型说罚球圈应在哪」(品红) 与「画面里真实的白色罚球弧」(青)
叠在同一张放大图上，另叠检测到的油漆区掩膜(绿) 与拟合四边形(红)。

判据：品红与青若重合 ⇒ 单应标定成立；若分离 ⇒ 不成立。
用法: chk_homog_overlay.py --seg ep24_s1 --idx 70
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
SEGD = ROOT / "action_work" / "tactic_notes_batch_full" / "segments"
OUT = ROOT / "action_work" / "track_judge" / "num"
sys.path.insert(0, str(ROOT / "engine"))
from court_homography_recover import COURT_W, KEY_D, assign_world, fit_quad, paint_mask  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    a = ap.parse_args()
    if not OUT.exists():
        OUT.mkdir(parents=True)
    files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    pm = paint_mask(img)
    q = np.asarray(fit_quad(pm), float)
    world, imgp, _ = assign_world(q)
    H = cv2.getPerspectiveTransform(world.astype(np.float32), imgp.astype(np.float32))

    # 真实白线（限制在油漆区内部，避免木地板与球衣）
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    white = (((hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 165)).astype(np.uint8)) * 255
    w = cv2.bitwise_and(white, cv2.erode(pm, np.ones((9, 9), np.uint8)))
    w = cv2.morphologyEx(w, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    cnts, _ = cv2.findContours(w, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cnts = [c for c in cnts if cv2.arcLength(c, True) > 60]

    vis = img.copy()
    vis[pm > 0] = (0.55 * vis[pm > 0] + 0.45 * np.array([0, 210, 0])).astype(np.uint8)
    cv2.polylines(vis, [np.int32(imgp)], True, (0, 0, 255), 2)
    t = np.linspace(0, np.pi, 181)
    circ = np.stack([KEY_D + 1.8288 * np.cos(t), COURT_W / 2 + 1.8288 * np.sin(t)], 1)
    P = cv2.perspectiveTransform(np.asarray([circ], np.float32), H)[0]
    cv2.polylines(vis, [P.astype(np.int32)], False, (255, 0, 255), 3)
    for c in cnts:
        cv2.drawContours(vis, [c], -1, (255, 255, 0), 2)   # 青=BGR(255,255,0)
    txt = "green=detected paint mask  red=fitted quad  MAGENTA=model says FT circle  CYAN=real white arc"
    cv2.putText(vis, txt, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 4)
    cv2.putText(vis, txt, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)

    x0, x1 = max(int(imgp[:, 0].min()) - 60, 0), min(int(imgp[:, 0].max()) + 60, img.shape[1])
    y0, y1 = max(int(imgp[:, 1].min()) - 60, 0), min(int(imgp[:, 1].max()) + 60, img.shape[0])
    c = vis[y0:y1, x0:x1]
    c = cv2.resize(c, None, fx=1.8, fy=1.8, interpolation=cv2.INTER_CUBIC)
    op = OUT / f"_dbg_{a.seg}_f{a.idx}_selfcheck.png"
    cv2.imwrite(str(op), c)
    print(f"-> {op}   ({c.shape[1]}x{c.shape[0]})")
    print(f"候选真实白弧 {len(cnts)} 条: " +
          ", ".join(f"{len(x)}pts" for x in cnts))


if __name__ == "__main__":
    main()
