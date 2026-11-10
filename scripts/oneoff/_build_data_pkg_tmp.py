"""Build the Mac migration DATA package: nba_csv/*.csv -> nba_csv_2026-07-13.zip"""
import glob
import os
import zipfile

#: 仓库根（脚本已收敛到 scripts/oneoff/，自身目录不再是仓库根）
#: 🔴 上溯**三层**：scripts/oneoff/x.py → oneoff → scripts → 仓库根
REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = REPO_DIR
CSV_DIR = os.path.join(ROOT, "nba_csv")
OUT = os.path.join(ROOT, "nba_csv_2026-07-13.zip")

files = sorted(glob.glob(os.path.join(CSV_DIR, "*.csv")))
print(f"Zipping {len(files)} CSVs from {CSV_DIR}", flush=True)
entries = 0
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for f in files:
        rel = "nba_csv/" + os.path.basename(f)
        z.write(f, rel)
        entries += 1
size = os.path.getsize(OUT)

print(f"DONE entries={entries} size={size/1e6:.1f} MB -> {OUT}", flush=True)
