#!/bin/bash
# 占有权分配收紧实验（held 模式）—— 球心须在球员框内才算持球
# 分别用 tile-raw 与 DP 两种球输入，喂入 poss_align 的 held 规则做池化检验。
export PYTHONPATH=""
V=/Users/deocheng/.workbuddy/binaries/python/envs/action05/bin/python
ENG=/Volumes/12T/NBA/action_analysis/engine
AW=/Volumes/12T/NBA/action_analysis/action_work
set -e
echo "===== START $(date) ====="

for w in w1 w2 w3 w4; do
  echo "=== $w poss_tile (tile-raw ball) ==="
  $V $ENG/ball_possession.py $AW/$w --out $AW/${w}_poss_tile \
     --ball-json $AW/${w}_rfdetr_tile.json --device mps --imgsz 1280 \
     --player-conf 0.3 --ball-conf 0.05 --max-gap 15 --poss-radius 0.04 --poss-hysteresis 1
done
for w in w1 w2 w3 w4; do
  echo "=== $w poss_dp (DP ball) ==="
  $V $ENG/ball_possession.py $AW/$w --out $AW/${w}_poss_dp \
     --ball-json $AW/${w}_poss_dp_ball.json --device mps --imgsz 1280 \
     --player-conf 0.3 --ball-conf 0.05 --max-gap 15 --poss-radius 0.04 --poss-hysteresis 1
done

echo "=== tile-raw near sweep (sanity) ==="
$V $ENG/poss_align.py --windows w1 w2 w3 w4 --assign near --poss-dir _poss_tile --sweep --out $AW/poss_align_tile_near.json
echo "=== tile-raw held sweep ==="
$V $ENG/poss_align.py --windows w1 w2 w3 w4 --assign held --poss-dir _poss_tile --sweep --out $AW/poss_align_tile_held.json
echo "=== dp held sweep ==="
$V $ENG/poss_align.py --windows w1 w2 w3 w4 --assign held --poss-dir _poss_dp --sweep --out $AW/poss_align_dp_held.json

echo "===== DONE $(date) ====="
