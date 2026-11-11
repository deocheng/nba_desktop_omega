#!/usr/bin/env bash
# 在 3 个独立高品质录像片段上复跑里程碑 05 球检测管线，验证「任务级事件可用性」门禁。
set -u
export PYTHONPATH=""
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_ENDPOINT=https://hf-mirror.com
PY=/Users/deocheng/.workbuddy/binaries/python/envs/action05/bin/python
ROOT=/Volumes/12T/NBA/action_analysis
cd "$ROOT"
for clip in sas_hou sas_nop sas_det; do
  echo "================================================================"
  echo ">>> validate_clips: $clip  $(date)"
  echo "================================================================"
  "$PY" engine/validate_clips.py --clip "$clip" \
      --frames-dir "action_work/$clip" --device mps --vconf -1
  echo "<<< done $clip  $(date)"
done
echo "ALL CLIPS DONE $(date)"
