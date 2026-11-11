#!/bin/bash
# A4.42: scores -> ball_possession 外置球 json（th=0.8，old/new × 两片段）
set -e
cd /Volumes/12T/NBA/action_analysis
PY=/Users/deocheng/.workbuddy/binaries/python/envs/action05/bin/python
$PY engine/scores_to_balljson.py --scores action_work/validate/ball_cand_scores_final351_sas_lal_joint.json --clip sas_lal --th 0.8 --out action_work/validate/sas_lal_ball_old_th08.json
$PY engine/scores_to_balljson.py --scores action_work/validate/ball_cand_scores_multiscale_sas_lal_joint.json --clip sas_lal --th 0.8 --out action_work/validate/sas_lal_ball_new_th08.json
$PY engine/scores_to_balljson.py --scores action_work/validate/ball_cand_scores_final351_sas_det_joint.json --clip sas_det --th 0.8 --out action_work/validate/sas_det_ball_old_th08.json
$PY engine/scores_to_balljson.py --scores action_work/validate/ball_cand_scores_multiscale_sas_det_joint.json --clip sas_det --th 0.8 --out action_work/validate/sas_det_ball_new_th08.json
echo "=== 4 balljson DONE ==="
