#!/bin/bash
# Mage-VL 理解层全量干净段批量（2026-10-04，用 A/B 胜出配方 C1）
#
# 配方依据（A/B 矩阵 8 轮交叉验证）：
#   C1 = 短指令 + greedy + 不加 repetition_penalty
#   - C0 结构化编号模板：会复读（ep12_s1 4-gram 重复率 0.57）
#   - C2 加 rep1.2：模型转向"无法准确判断"拒答
#   - C3 叠加 ngram：出现幻觉（编造动作/跳到"另一场比赛"）
#
# 安全约束（老程要求"别死机"，已实测有效）：
#   - 每段独立进程（杜绝 MPS 缓存累积 → 换页）
#   - 严格串行
#   - 空闲率 < 45% 就等待回收
set -u
cd /Volumes/12T/NBA/action_analysis

PY=/Users/deocheng/.workbuddy/binaries/python/envs/mage_vl/bin/python
PROBE=engine/mage_vl_tactic_probe.py
SEGROOT=action_work/tactic_notes_batch_full/segments
ANN=action_work/asr_segment_annotation.json
OUT=action_work/mage_probe_clean14.json
FRAMES=24
SIZE=512x288
TOK=128

# ep10-20 的 22 段剔除 8 图版/讲解段后的 14 干净段
SEGS=(ep10_s0 ep11_s0 ep12_s0 ep12_s1 ep13_s1 ep15_s0 \
      ep16_s0 ep16_s1 ep17_s0 ep17_s1 ep18_s0 ep18_s1 ep19_s0 ep20_s0)

free_pct () { memory_pressure 2>/dev/null | grep -o 'System-wide memory free percentage: [0-9]*' | grep -o '[0-9]*$'; }

echo "干净段数=${#SEGS[@]}  配方=C1(短提示+greedy)  帧数=$FRAMES  尺寸=$SIZE  token=$TOK"
for seg in "${SEGS[@]}"; do
  echo "================================================================"
  echo "[$(date +%H:%M:%S)] seg=$seg"
  free=$(free_pct); echo "  空闲率(前)=${free}%"
  while [ "${free:-0}" -lt 45 ]; do
    echo "  ⚠ 空闲率 ${free}% 偏低，等待 20s 回收..."; sleep 20; free=$(free_pct)
  done
  PYTHONPATH="" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    $PY $PROBE --seg-dir "$SEGROOT/$seg" --do-magevl \
      --mage-frames $FRAMES --mage-frame-size $SIZE --mage-max-tokens $TOK \
      --mage-simple-prompt --out "$OUT" 2>&1 \
    | grep -E "^\[config\]|^  \[退化判定\]|^  Mage描述|^  ASR真值|Error|Traceback"
  echo "  空闲率(后)=$(free_pct)%"
  sleep 5
done

echo "================================================================"
echo "[done] 干净段全批量完成 -> $OUT"
