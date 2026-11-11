# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[4]))
import json
import statistics as st

from common.nba_paths import tactics_data_file

P = str(tactics_data_file("action_work/norm_calib/smooth_picks_merged_role.json"))
d = json.load(open(P))
rows = d["smooth"] + d["static"]
print(f"n_windows(声明)={d['n_windows']}  落盘条目={len(rows)}  "
      f"差={d['n_windows'] - len(rows)}  excluded_by_laocheng={d['excluded_by_laocheng']}")

print(f"\n{'clus':<5}{'seg':<10}{'win':<14}{'n_mv':<6}{'coord':<7}{'spd':<7}"
      f"{'straight':<9}{'stab':<7}{'score':<7}{'verdict':<10}role")
for r in sorted(rows, key=lambda x: -x.get("median_speed_px", 0)):
    print(f"{r.get('cluster'):<5}{r.get('seg',''):<10}"
          f"{str(r.get('win_start'))[:6]+'-'+str(r.get('win_end'))[:6]:<14}"
          f"{r.get('n_movers',0):<6}{r.get('coordination',0):<7}"
          f"{r.get('median_speed_px',0):<7}{r.get('straightness',0):<9}"
          f"{r.get('stability',0):<7}{r.get('smooth_score',0):<7}"
          f"{str(r.get('laocheng_verdict')):<10}{r.get('narrative_role')}")

print("\n=== 分布（仅落盘 17 条）===")
for name in ("median_speed_px", "coordination", "n_movers"):
    a = sorted(r.get(name, 0) for r in rows)
    print(f"{name:<18} min={a[0]:<7} p25={a[len(a)//4]:<7} med={st.median(a):<7} "
          f"p75={a[3*len(a)//4]:<7} max={a[-1]}")

print("\n=== transition 门 (n_mv>=3 & coord>=0.90 & spd>=6.0) 逐条 ===")
hit = 0
for r in rows:
    nmv, c, s = r.get("n_movers", 0), r.get("coordination", 0), r.get("median_speed_px", 0)
    c1, c2, c3 = nmv >= 3, c >= 0.90, s >= 6.0
    if c1 and c2 and c3:
        hit += 1
    if (c1 and c2) or (c1 and c3) or (c2 and c3):
        print(f"  clus{r.get('cluster'):<4} n_mv={nmv:<4}({int(c1)}) coord={c:<6}({int(c2)}) "
              f"spd={s:<7}({int(c3)})  role={r.get('narrative_role')}")
print(f"  三条全中 = {hit}")

print("\n=== result 门 (spd>=8.0) ===")
n8 = sum(1 for r in rows if r.get("median_speed_px", 0) >= 8.0)
print(f"  spd>=8.0 = {n8} 条")
print("  spd 排序前8:", [r.get("median_speed_px") for r in
                     sorted(rows, key=lambda x: -x.get("median_speed_px", 0))[:8]])

print("\n=== 各 role 的实际指标均值 ===")
by = {}
for r in rows:
    by.setdefault(r.get("narrative_role"), []).append(r)
for k, v in sorted(by.items()):
    print(f"  {k:<11} n={len(v):<3} "
          f"spd均={st.mean(x['median_speed_px'] for x in v):<7.2f} "
          f"coord均={st.mean(x['coordination'] for x in v):<7.3f} "
          f"n_mv均={st.mean(x['n_movers'] for x in v):<6.2f}")
