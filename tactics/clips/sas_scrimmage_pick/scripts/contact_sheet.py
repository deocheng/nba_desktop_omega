import os
import sys

import cv2
import numpy as np

src = sys.argv[1] if len(sys.argv) > 1 else "poss_full_1958.2-1972.4.mp4"
t0 = float(sys.argv[2]) if len(sys.argv) > 2 else 0.2
t1 = float(sys.argv[3]) if len(sys.argv) > 3 else 5.21
step = float(sys.argv[4]) if len(sys.argv) > 4 else 0.4
src_off = float(sys.argv[5]) if len(sys.argv) > 5 else 1958.2
out = sys.argv[6] if len(sys.argv) > 6 else "verify_trans/poss_first5s.jpg"

cap = cv2.VideoCapture(src)
fps = cap.get(cv2.CAP_PROP_FPS)
n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
print("clip", src, "fps", fps, "frames", n, "dur", round(n / fps, 2))

SC = 0.5
want = [round(t, 2) for t in np.arange(t0, t1 + 1e-6, step)]
tiles = []
for t in want:
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * fps)))
    ok, fr = cap.read()
    if not ok:
        print("MISS", t)
        continue
    fr = cv2.resize(fr, (int(fr.shape[1] * SC), int(fr.shape[0] * SC)))
    cv2.rectangle(fr, (0, 0), (fr.shape[1], 22), (0, 0, 0), -1)
    cv2.putText(fr, f"clip t={t:.1f}s  src={src_off + t:.1f}s", (4, 16),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
    tiles.append(fr)
cap.release()
print("tiles", len(tiles))

W = max(t.shape[1] for t in tiles)
rows = []
for i in range(0, len(tiles), 2):
    grp = tiles[i:i + 2]
    rows.append(np.hstack([cv2.copyMakeBorder(t, 0, 0, 0, W - t.shape[1],
                                              cv2.BORDER_CONSTANT, value=(0, 0, 0))
                           for t in grp]))
maxw = max(r.shape[1] for r in rows)
rows = [cv2.copyMakeBorder(r, 0, 0, 0, maxw - r.shape[1],
                          cv2.BORDER_CONSTANT, value=(0, 0, 0)) for r in rows]
sheet = np.vstack(rows)
d = os.path.dirname(out)
if d and not os.path.isdir(d):
    os.makedirs(d)
cv2.imwrite(out, sheet, [cv2.IMWRITE_JPEG_QUALITY, 88])
print("wrote", out, sheet.shape)
