#!/bin/bash
# A4.42 短期: 持球者解出率对比（old vs new 池 × sas_lal/sas_det，th=0.8 球输入）
# 口径: --imgsz 1280 (1920x1080 硬要求) --poss-hysteresis 1 (sas_* 硬口径) --poss-radius 0.04
set -e
cd /Volumes/12T/NBA/action_analysis
export PYTHONPATH="" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
PY=/Users/deocheng/.workbuddy/binaries/python/envs/action05/bin/python
ENG=engine
AW=action_work

run() {
  local clip=$1 balljson=$2 out=$3
  echo "===== possession $out START $(date +%H:%M:%S) ====="
  $PY $ENG/ball_possession.py $AW/$clip \
      --out $AW/validate/$out \
      --ball-json $AW/validate/$balljson \
      --device mps --imgsz 1280 --player-conf 0.3 \
      --poss-radius 0.04 --poss-hysteresis 1 --max-gap 15
}

run sas_lal sas_lal_ball_old_th08.json sas_lal_poss_msold
run sas_lal sas_lal_ball_new_th08.json sas_lal_poss_msnew
run sas_det sas_det_ball_old_th08.json sas_det_poss_msold
run sas_det sas_det_ball_new_th08.json sas_det_poss_msnew
echo "===== ALL POSSESSION DONE $(date +%H:%M:%S) ====="
