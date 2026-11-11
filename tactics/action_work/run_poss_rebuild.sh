#!/bin/bash
# 重建占有权 + 重跑 Phase 1.5 池化检验（里程碑 05 · Phase 1.5b 补测）
# Exp A: tile-raw 检测直接喂 ball_possession
# Exp B: DP 选定轨迹喂 ball_possession（canonical）
export PYTHONPATH=""
V=/Users/deocheng/.workbuddy/binaries/python/envs/action05/bin/python
ENG=/Volumes/12T/NBA/action_analysis/engine
AW=/Volumes/12T/NBA/action_analysis/action_work

set -e
echo "===== START $(date) ====="

for w in w1 w2 w3 w4; do
  echo "=== $w tile-raw ==="
  $V $ENG/ball_possession.py $AW/$w --out $AW/${w}_poss \
     --ball-json $AW/${w}_rfdetr_tile.json --device mps --imgsz 1280 \
     --player-conf 0.3 --ball-conf 0.05 --max-gap 15 --poss-radius 0.04 --poss-hysteresis 3
done
echo "=== tile poss_align (sweep) ==="
$V $ENG/poss_align.py --windows w1 w2 w3 w4 --hyst 3 --sweep --out $AW/poss_align_tile.json

for w in w1 w2 w3 w4; do
  echo "=== $w dp ==="
  $V $ENG/ball_possession.py $AW/$w --out $AW/${w}_poss \
     --ball-json $AW/${w}_poss_dp_ball.json --device mps --imgsz 1280 \
     --player-conf 0.3 --ball-conf 0.05 --max-gap 15 --poss-radius 0.04 --poss-hysteresis 3
done
echo "=== dp poss_align (sweep) ==="
$V $ENG/poss_align.py --windows w1 w2 w3 w4 --hyst 3 --sweep --out $AW/poss_align_dp.json

echo "===== DONE $(date) ====="
