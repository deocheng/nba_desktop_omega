"""A5.14-b 自证：单应标定是否正确 —— 用罚球圈(白弧)做独立校验。

判据（独立于标定所用的 4 个油漆区角点）：
  投影的罚球圈(半径 1.8288 m) 应压在画面里的白色罚球圆弧上。
用法: chk_homog_ft.py --seg ep24_s1 --idx 70 [--zoom 2.4]
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
from court_homography_recover import COURT_L, COURT_W, KEY_D, KEY_W, KEY_Y0, assign_world, fit_quad, paint_mask  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="ep24_s1")
    ap.add_argument("--idx", type=int, default=70)
    ap.add_argument("--zoom", type=float, default=2.4)
    a = ap.parse_args()

    if not OUT.exists():
        OUT.mkdir(parents=True)
    files = sorted((SEGD / a.seg / "frames").glob("f*.jpg"))
    img = cv2.imread(str(files[a.idx]))
    pm = paint_mask(img)
    if pm is None:
        print("油漆区掩膜为空")
        return
    q = fit_quad(pm)
    world, imgp, note = assign_world(q)
    Hm = cv2.getPerspectiveTransform(world.astype(np.float32), imgp.astype(np.float32))
    w4 = world.astype(np.float32).reshape(1, -1, 2)
    pp = cv2.perspectiveTransform(w4, Hm)[0]
    err = float(np.linalg.norm(np.asarray(imgp, float) - pp, axis=1).max())
    print(f"油漆区角点 {np.int32(imgp).tolist()}")
    print(f"单应重投影自检误差 = {err:.2e} px   ({note})")

    def proj(pts):
        return cv2.perspectiveTransform(np.asarray([pts], np.float32), Hm)[0]

    def arc(cx, cy, r, n=181, a0=0.0, a1=np.pi):
        t = np.linspace(a0, a1, n)
        return np.stack([cx + r * np.cos(t), cy + r * np.sin(t)], 1)

    FT_R = 1.8288
    fcirc = arc(KEY_D, COURT_W / 2, FT_R)                 # 罚球圈下半(画面上=场内一侧)
    fcirc_up = arc(KEY_D, COURT_W / 2, FT_R, 181, np.pi, 2 * np.pi)
    fline = np.array([[KEY_D, KEY_Y0], [KEY_D, KEY_Y0 + KEY_W]])   # 罚球线
    bline = np.array([[0.0, KEY_Y0], [0.0, KEY_Y0 + KEY_W]])       # 底线上油漆区后沿

    vis = img.copy()
    cv2.polylines(vis, [np.int32(imgp)], True, (0, 0, 255), 2)      # 检测到的油漆区(红)
    cv2.polylines(vis, [np.int32(proj(fcirc))], False, (255, 0, 255), 3)      # 投影罚球圈(品红)
    cv2.polylines(vis, [np.int32(proj(fcirc_up))], False, (255, 0, 255), 1)
    cv2.polylines(vis, [np.int32(proj(fline))], False, (0, 255, 255), 2)      # 投影罚球线(黄)
    cv2.polylines(vis, [np.int32(proj(bline))], False, (0, 255, 0), 2)        # 投影油漆区后沿(绿)

    # 裁到油漆区附近并放大
    x0 = max(int(imgp[:, 0].min()) - 90, 0)
    x1 = min(int(imgp[:, 0].max()) + 90, img.shape[1])
    y0 = max(int(imgp[:, 1].min()) - 90, 0)
    y1 = min(int(imgp[:, 1].max()) + 220, img.shape[0])
    c = vis[y0:y1, x0:x1]
    c = cv2.resize(c, None, fx=a.zoom, fy=a.zoom, interpolation=cv2.INTER_CUBIC)
    cv2.putText(c, "magenta=proj FT circle(1.83m)  yellow=proj FT line  green=proj back edge  red=detected key",
                (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 4)
    cv2.putText(c, "magenta=proj FT circle(1.83m)  yellow=proj FT line  green=proj back edge  red=detected key",
                (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    op = OUT / f"_dbg_{a.seg}_f{a.idx}_ftcheck.png"
    cv2.imwrite(str(op), c)
    print(f"-> {op}")


if __name__ == "__main__":
    main()
