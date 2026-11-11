#!/usr/bin/env python3
"""A5.6e ep24_s1 的 8 条裁定条目拼一张对照图（我独立目视复核用，也是给老程的对照证据）。"""
# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from common.nba_paths import tactics_data_file

ROOT = Path(str(tactics_data_file("")))
JD = ROOT / "action_work" / "track_judge"
FONT_CAND = ["/System/Library/Fonts/PingFang.ttc",
             "/System/Library/Fonts/Hiragino Sans GB.ttc",
             "/System/Library/Fonts/STHeiti Medium.ttc"]


def F(sz):
    for p in FONT_CAND:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, sz)
            except Exception:
                pass
    return ImageFont.load_default()


h = (JD / "index.html").read_text(encoding="utf-8")
items = json.loads(re.search(r"\[\{.*\}\]", h.split("\n")[31], re.S).group(0))
sel = [x for x in items if x["seg"] == "ep24_s1"]
sel.sort(key=lambda x: (x["key"].startswith("B:"), x["tid"]))

TARGET_W = 900
rows = []
for x in sel:
    im = Image.open(JD / x["crop"]).convert("RGB")
    nw = TARGET_W
    nh = int(im.height * nw / im.width)
    im = im.resize((nw, nh), Image.LANCZOS)
    band = 34
    c = Image.new("RGB", (nw + 12, nh + band), (255, 255, 255))
    d = ImageDraw.Draw(c)
    col = (200, 0, 0) if x["key"].startswith("B:") else (0, 90, 200)
    d.text((8, 6), f"{x['key']}   {x['bucket']} n={x['n']}  帧{x['span']}   "
                   f"框图:max_step={x['max_step']}px/帧  n_big={x['n_big']}   "
                   f"自动预判[{x['auto']}]", font=F(22), fill=col)
    c.paste(im, (6, band))
    rows.append(c)

W = max(r.width for r in rows)
H = sum(r.height for r in rows) + 26 * len(rows)
sheet = Image.new("RGB", (W, H), (240, 240, 240))
d = ImageDraw.Draw(sheet)
y = 0
d.text((10, 4), "ep24_s1 的 8 条裁定条目（红= B 版样本，蓝= base 版样本）",
       font=F(24), fill=(20, 20, 20))
y = 34
for r in rows:
    sheet.paste(r, (0, y))
    y += r.height + 12
out = JD / "hires" / "ep24_s1_judge8_contact.png"
sheet.save(out)
print("saved", out, sheet.size, "n=", len(rows))
