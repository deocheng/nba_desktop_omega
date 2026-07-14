"""Convert NBA team SVG logos to PNG for Ardot upload."""
import cairosvg
import os

SIZE = 200  # output PNG size (square)
SRC_DIR = r"C:\autopick\AutoPick\nba_data\NBAlogo"
OUT_DIR = os.path.join(SRC_DIR, "png")
os.makedirs(OUT_DIR, exist_ok=True)

# Logos needed for the dashboard
logos = ["nba", "lal", "okc", "mil", "den", "bos", "cle", "hou", "min", "orl"]

for name in logos:
    svg_path = os.path.join(SRC_DIR, f"{name}.svg")
    png_path = os.path.join(OUT_DIR, f"{name}.png")
    
    if not os.path.exists(svg_path):
        print(f"SKIP (not found): {svg_path}")
        continue
    
    try:
        cairosvg.svg2png(
            url=svg_path,
            write_to=png_path,
            output_width=SIZE,
            output_height=SIZE,
        )
        size_kb = os.path.getsize(png_path) / 1024
        print(f"OK  {name}.svg → {name}.png ({size_kb:.1f} KB)")
    except Exception as e:
        print(f"ERR {name}.svg: {e}")

print(f"\nDone! Output: {OUT_DIR}")
