#!/usr/bin/env bash
# backup_m05_pre_rebuild.sh —— 真值库重建前的快照
#
# 为什么备份（三条硬理由）
#   1. 本仓库**不是 git 仓库**（engine/ 下 138 个脚本无任何版本历史）。
#   2. 人工标注凭证不可再生：labels_bank.json / labels3_visual.json /
#      manifest2_t{1..4}.json / verifysheet_*.jpg / judge/ 判读记录。
#   3. 它们是「真值库审计」结论的证据链本身。重建会改写这些库，
#      若无「重建前」快照，p=1.22e-04 那条发现将永久不可复核。
#
# 产出
#   A 同卷全量 : $SRC/backups/m05_pre_rebuild_20260925/   （除 .venv 空壳外全量）
#   B 异地珍贵 : /Volumes/8T/backup_nba_action_analysis/m05_pre_rebuild_20260925/
#                仅不可再生子集（代码 + 标注 + 判读 + 指标 JSON + 报告）
#   两份各带 MANIFEST.md（清单）与 checksums.sha256（关键文件指纹）
#
# 幂等：可重复运行；已存在则增量补齐（rsync）。
# 安全：**只读源、只写新目录**，绝不删除源文件。
set -uo pipefail

SRC="/Volumes/12T/NBA/action_analysis"
STAMP="20260925"
A="${SRC}/backups/m05_pre_rebuild_${STAMP}"
B="/Volumes/8T/backup_nba_action_analysis/m05_pre_rebuild_${STAMP}"

echo "=== [1/6] 建目录 ==="
mkdir -p "$A" "$B"
echo "A = $A"
echo "B = $B"

echo "=== [2/6] A 全量快照（排除 .venv 空壳）==="
rsync -a --exclude '.venv' "$SRC/" "$A/" || { echo "❌ A 失败"; exit 1; }

echo "=== [3/6] B 异地珍贵子集 ==="
rsync -a "$SRC/engine/"                          "$B/engine/"
rsync -a "$SRC/tools/"                           "$B/tools/"
rsync -a "$SRC/vocab/"                           "$B/vocab/"
mkdir -p "$B/reports/milestone_05/measure/judge" "$B/reports/milestone_05/measure/_sheets" "$B/action_work"
rsync -a --include '*.html' --exclude '*' "$SRC/reports/milestone_05/" "$B/reports/milestone_05/"
rsync -a --include '*.json' --include '*/' --exclude '*' \
      "$SRC/reports/milestone_05/measure/" "$B/reports/milestone_05/measure/"
rsync -a --include '*.jpg' --include '*/' --exclude '*' \
      "$SRC/reports/milestone_05/measure/" "$B/reports/milestone_05/measure/"
rsync -a --include '*.jpg' --include '*/' --exclude '*' \
      "$SRC/reports/milestone_05/measure/judge/" "$B/reports/milestone_05/measure/judge/"
# 关键 .npy（特征缓存，重算昂贵）
for f in feats_all.npy feats_all_v2.npy verify_head_feats.npy; do
  [ -f "$SRC/reports/milestone_05/measure/$f" ] && cp -p "$SRC/reports/milestone_05/measure/$f" "$B/reports/milestone_05/measure/"
done
rsync -a --include '*.json' --exclude '*' "$SRC/action_work/" "$B/action_work/"
for f in "$SRC"/setup_env*.sh; do [ -f "$f" ] && cp -p "$f" "$B/"; done

echo "=== [4/6] 校验：文件计数 ==="
# ⚠️ 必须排除 backups/ 自身：否则源清单会把「刚建好的副本」也数进去，
#    得出「副本少了一半」的自引用假警报（2026-09-25 实际踩过一次）。
na=$(find "$A" -type f -not -path "$A/backups/*" | wc -l | tr -d ' ')
ns=$(find "$SRC" -type f -not -path '*/.venv/*' -not -path "$SRC/backups/*" | wc -l | tr -d ' ')
nb=$(find "$B" -type f | wc -l | tr -d ' ')
echo "源(除 .venv 与 backups 自身) = $ns ; A = $na ; B(珍贵子集) = $nb"
echo "  注：A 会比源多出 MANIFEST.md / checksums.sha256 两个自产文件 ⇒ 允许 $ns 与 $((ns+2)) 两个值"
if [ "$na" = "$ns" ] || [ "$na" = "$((ns+2))" ]; then
  echo "✅ A 计数一致"
else
  echo "⚠️ A 计数不一致（实差 $((ns-na))）—— 用下节逐文件比对定位"
fi

echo "=== [4.5/6] 校验：逐文件大小全量比对 ==="
python3 - "$SRC" "$A" <<'PY'
import os, sys
src, dst = sys.argv[1], sys.argv[2]
bad, n, tot = [], 0, 0
for root, dirs, files in os.walk(src):
    if "/.venv" in root or "/backups" in root:
        continue
    for f in files:
        p = os.path.join(root, f)
        rel = os.path.relpath(p, src)
        q = os.path.join(dst, rel)
        if not os.path.exists(q):
            bad.append(("MISSING", rel)); continue
        s1, s2 = os.path.getsize(p), os.path.getsize(q)
        n += 1; tot += s1
        if s1 != s2:
            bad.append(("SIZE", rel, s1, s2))
print(f"逐文件比对 {n} 个，累计 {tot/1e6:.1f} MB；不一致 {len(bad)}")
for b in bad[:10]:
    print("  ", b)
print("✅ 内容大小全一致" if not bad else "❌ 存在不一致")
PY

echo "=== [5/6] 校验：关键文件 sha256（源 vs A vs B）==="
KEY=(
  "engine/labels_bank_build.py"
  "engine/labels3_visual.py"
  "engine/ball_head_v2.py"
  "engine/ball_strict_eval.py"
  "engine/strict_power.py"
  "engine/judge_batch.py"
  "reports/milestone_05/measure/labels_bank.json"
  "reports/milestone_05/measure/labels3_visual.json"
  "reports/milestone_05/measure/manifest2_t1.json"
  "reports/milestone_05/measure/manifest2_t2.json"
  "reports/milestone_05/measure/manifest2_t3.json"
  "reports/milestone_05/measure/manifest2_t4.json"
  "reports/milestone_05/measure/strict_eval_v2.json"
  "reports/milestone_05/measure/operating_point.json"
  "reports/milestone_05/measure/allcand_ab.json"
  "reports/milestone_05/measure/judge/arb_result.json"
)
: > "$A/checksums.sha256"
ok=0; bad=0
for k in "${KEY[@]}"; do
  s="$SRC/$k"
  [ -f "$s" ] || { echo "  (源缺) $k"; continue; }
  h_s=$(shasum -a 256 "$s" | awk '{print $1}')
  h_a=$(shasum -a 256 "$A/$k" 2>/dev/null | awk '{print $1}')
  h_b=$(shasum -a 256 "$B/$k" 2>/dev/null | awk '{print $1}')
  printf "%s  %s\n" "$h_s" "$k" >> "$A/checksums.sha256"
  if [ "$h_s" = "$h_a" ] && [ "$h_s" = "$h_b" ]; then
    ok=$((ok+1)); printf "  ✅ %s\n" "$k"
  else
    bad=$((bad+1)); printf "  ❌ %s  (A=%s B=%s)\n" "$k" "${h_a:0:12}" "${h_b:0:12}"
  fi
done
echo "关键文件校验：通过 $ok / 失败 $bad"
cp -p "$A/checksums.sha256" "$B/checksums.sha256"
: > "$B/checksums.sha256.manifest"

echo "=== [6/6] 写 MANIFEST ==="
cat > "$A/MANIFEST.md" <<EOF
# 快照 m05_pre_rebuild_${STAMP}

- 源：\`$SRC\`
- 目的：真值库重建前快照（**只读源、只写新目录，未删除任何源文件**）
- 生成：$(date '+%Y-%m-%d %H:%M:%S %Z')

## 备份理由
1. **本仓库不是 git 仓库** —— \`engine/\` 下 $(ls "$SRC"/engine/*.py 2>/dev/null | wc -l | tr -d ' ') 个 .py 无版本历史。
2. 人工标注凭证不可再生（\`labels_bank.json\` 359 样本、\`labels3_visual.json\` 60 样本、
   \`manifest2_t{1..4}.json\`（帧号↔bbox 映射）、\`verifysheet_*.jpg\` 接触表 $(ls "$SRC"/reports/milestone_05/measure/verifysheet_*.jpg 2>/dev/null | wc -l | tr -d ' ') 张、
   \`judge/\` 盲判 key/verdicts）。
3. 这些是「真值库审计」结论的**证据链本身**：两份同日标注只一致 46/60、冲突 14/14 单向
   （精确二项 p=1.22e-04）。重建会改写库，无此快照则该发现永久不可复核。

## 内容
- 除 \`.venv\`（空壳，仅有 pip/mpmath，**勿用**）外全量镜像。
- 文件计数：源(除 .venv) = ${ns}，本快照 = ${na}。

## 关键文件指纹
见同目录 \`checksums.sha256\`（源与 A、B 三方一致才记入）。

## 还原方式（按需，勿整体覆盖回源）
\`\`\`bash
# 单个文件还原（推荐）
cp -p "$A/reports/milestone_05/measure/labels_bank.json" \\
      "$SRC/reports/milestone_05/measure/labels_bank.json"
# 整体还原前必须：① 另建一份当前状态快照；② 逐项确认影响范围
\`\`\`

## 异地副本
- \`$B\` —— 仅不可再生子集（代码 + 标注 + 判读 + 指标 JSON + 报告），
  用于防范 12T 卷损坏。
EOF
cp -p "$A/MANIFEST.md" "$B/MANIFEST.md"

echo "=== 体积 ==="
du -sh "$A" "$B"
echo "✅ 完成"
