#!/usr/bin/env python3
"""检测层目视核对：把 YOLO 框画到帧上，输出叠加图 + 尺寸分布。

用途：给「球场区域裁人」定阈值。转播画面里观众/替补/裁判全会被检成 person，
需要看清它们的框有多大、在哪，才能设计过滤规则（身高带 / 静态剔除 / 多边形）。
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import os
import sys
import time

from common.nba_paths import workspace_file

os.environ.setdefault("YOLO_CONFIG_DIR", "/tmp/yolo_cfg")

from PIL import Image, ImageDraw  # noqa: E402
from ultralytics import YOLO  # noqa: E402

W = str(workspace_file("action_work/weights/yolo11n.pt"))
PALETTE = [(255, 64, 64), (64, 200, 255), (255, 210, 60), (120, 255, 120),
           (255, 120, 255), (255, 160, 60), (140, 140, 255), (60, 255, 210)]


def run(img_path: str, out_path: str, imgsz: int, conf: float) -> None:
    model = YOLO(W)
    t0 = time.perf_counter()
    r = model.predict(img_path, imgsz=imgsz, conf=conf, verbose=False, device="cpu")[0]
    ms = (time.perf_counter() - t0) * 1000

    img = Image.open(img_path).convert("RGB")
    d = ImageDraw.Draw(img)
    iw, ih = img.size

    rows = []
    for i, b in enumerate(sorted(r.boxes, key=lambda z: -float(z.xyxy[0][3] - z.xyxy[0][1]))):
        cls = int(b.cls[0])
        cf = float(b.conf[0])
        x1, y1, x2, y2 = [float(v) for v in b.xyxy[0].tolist()]
        h = y2 - y1
        w = x2 - x1
        col = (255, 40, 40) if cls == 32 else PALETTE[i % len(PALETTE)]
        d.rectangle([x1, y1, x2, y2], outline=col, width=3)
        tag = "BALL" if cls == 32 else str(i)
        d.text((x1 + 3, max(0, y1 - 14)), f"{tag} {cf:.2f} h{h:.0f}",
               fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))
        rows.append((cls, cf, h, w, y2 / ih, x1 / iw))

    img.save(out_path, quality=92)
    print(f"[{os.path.basename(img_path)}] imgsz={imgsz} conf={conf} "
          f"-> {len(r.boxes)} 框 | {ms:.0f}ms | {iw}x{ih}")
    print(f"{'cls':>4} {'conf':>6} {'h_px':>6} {'w_px':>6} {'h/img':>6} {'x/img':>6}")
    for cls, cf, h, w, hy, xr in rows[:30]:
        print(f"{cls:>4} {cf:>6.2f} {h:>6.0f} {w:>6.0f} {hy:>6.3f} {xr:>6.3f}")
    hs = sorted(row[2] for row in rows)
    if hs:
        print(f"[尺寸分布] n={len(hs)} min={hs[0]:.0f} p25={hs[len(hs)//4]:.0f} "
              f"中位={hs[len(hs)//2]:.0f} p75={hs[3*len(hs)//4]:.0f} max={hs[-1]:.0f}")


def main() -> int:
    if len(sys.argv) < 3:
        print("用法: probe_detect_overlay.py <img...> <outdir> [imgsz] [conf]")
        return 2
    *imgs, outdir = sys.argv[1:]
    imgsz = 1280
    conf = 0.25
    if os.path.isdir(outdir) is False:
        os.makedirs(outdir, exist_ok=True)
    for p in imgs:
        stem = os.path.splitext(os.path.basename(p))[0]
        run(p, os.path.join(outdir, f"ov_{stem}.jpg"), imgsz, conf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
