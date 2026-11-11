#!/bin/bash
# Mage-VL 解码策略 A/B 矩阵（2026-10-04）
#
# 背景：证伪实验已确立——退化根因不是分辨率（640x360 提分辨率仍退化），
#       而是 greedy 解码 + §8 结构化编号模板诱导。
# 目的：找到能消除退化的最小解码/提示处方。
#
# 安全约束（老程要求"别死机"）：
#   - 每个 (段, 配置) **独立进程**（避免 MPS 缓存累积导致换页）
#   - **严格串行**， Magnetic 起多进程
#   - 每轮前后检查系统空闲率，低于 40% 就等待回收
set -u
cd /Volumes/12T/NBA/action_analysis

PY=/Users/deocheng/.workbuddy/binaries/python/envs/mage_vl/bin/python
PROBE=engine/mage_vl_tactic_probe.py
SEGROOT=action_work/tactic_notes_batch_full/segments
ANN=action_work/asr_segment_annotation.json
OUT=action_work/mage_probe_ab.json
FRAMES=24
SIZE=512x288
TOK=128

SEGS=(ep10_s0 ep12_s1)   # 两种不同退化症状的已知退化段

run_case () {
  local seg=$1 cfg=$2 shift_args=$3
  echo "================================================================"
  echo "[$(date +%H:%M:%S)] seg=$seg  cfg=$cfg  args=$shift_args"
  local free
  free=$(memory_pressure 2>/dev/null | grep -o 'System-wide memory free percentage: [0-9]*' | grep -o '[0-9]*$')
  echo "  内存空闲率(前)=${free}%"
  # 守卫：空闲率不足则等待回收，避免换页
  while [ "${free:-0}" -lt 40 ]; do
    echo "  ⚠ 空闲率 ${free}% 偏低，等待 20s 让系统回收..."
    sleep 20
    free=$(memory_pressure 2>/dev/null | grep -o 'System-wide memory free percentage: [0-9]*' | grep -o '[0-9]*$')
  done
  PYTHONPATH="" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    $PY $PROBE --seg-dir "$SEGROOT/$seg" --do-magevl \
      --mage-frames $FRAMES --mage-frame-size $SIZE --mage-max-tokens $TOK \
      $shift_args --out "$OUT" 2>&1 | grep -E "^\[config\]|^  Mage描述|^  \[退化判定\]|^  ASR真值|Error|Traceback"
  echo "  内存空闲率(后)=$(memory_pressure 2>/dev/null | grep -o 'System-wide memory free percentage: [0-9]*' | grep -o '[0-9]*$')%"
  sleep 5
}

for seg in "${SEGS[@]}"; do
  run_case "$seg" "C0_greedy_结构化提示(基线/已知退化)" ""
  run_case "$seg" "C1_短提示"                    "--mage-simple-prompt"
  run_case "$seg" "C2_rep1.2"                    "--mage-rep-penalty 1.2"
  run_case "$seg" "C3_短提示+rep1.2+ngram4"      "--mage-simple-prompt --mage-rep-penalty 1.2 --mage-no-repeat-ngram 4"
done

echo "================================================================"
echo "[done] A/B 矩阵跑完 -> $OUT"
