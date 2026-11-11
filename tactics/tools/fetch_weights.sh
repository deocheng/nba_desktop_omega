#!/bin/bash
# 并行分片下载 RelateAnything 权重（curl 版）
# 必须绕代理：出站代理在 HF /resolve/ 上返 502/000；直连单连接 ~48KB/s，8 路并行 ~380KB/s
# HEAD 不可靠 -> 用 range 0-0 探总长，取最后一条 content-range（重试会产生多行）
set -u
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY

REPO="maelic/relsgg-vits16plus"
BASE="https://huggingface.co/$REPO/resolve/main"
DEST="/Users/deocheng/WorkBuddy/2026-07-13-10-47-43/action_work/models/relsgg-vits16plus"
TOOLS="/Volumes/12T/NBA/action_analysis/tools"
CHUNK=$((4*1024*1024))
PAR=8

mkdir -p "$DEST"

filesize() {
  curl -sL -r 0-0 -D - -o /dev/null --max-time 30 --retry 4 --retry-delay 2 "$1" \
    | tr -d '\r' | awk 'tolower($1)=="content-range:"{split($NF,a,"/"); n=a[2]} END{print n}'
}

for f in model.pth text_student.pt predicate_embeddings.npz tokenizer.json tokenizer_config.json calibration.json; do
  OUT="$DEST/$f"
  SZ=$(filesize "$BASE/$f")
  case "$SZ" in ''|*[!0-9]*) echo "[$f] 长度探测失败，跳过"; continue;; esac
  CUR=$(stat -f%z "$OUT" 2>/dev/null || echo 0)
  if [ "$CUR" = "$SZ" ]; then echo "[skip] $f 已完整 ($SZ bytes)"; continue; fi

  CD="$DEST/_chunks/$f"; rm -rf "$CD"; mkdir -p "$CD"
  N=$(( (SZ + CHUNK - 1) / CHUNK ))
  echo "[$f] $(( SZ/1024/1024 )) MB, $N 分片 x $PAR 并发"
  T0=$(date +%s)
  seq 0 $(( N - 1 )) | xargs -P $PAR -I{} bash "$TOOLS/_one_chunk.sh" {} "$BASE/$f" "$CD" "$SZ" "$CHUNK"
  cat "$CD"/part_* > "$OUT"
  rm -rf "$CD"
  NEW=$(stat -f%z "$OUT")
  DT=$(( $(date +%s) - T0 ))
  if [ "$NEW" = "$SZ" ]; then echo "[ok]   $f $(( NEW/1024/1024 )) MB in ${DT}s"
  else echo "[BAD]  $f 大小 $NEW != $SZ"; fi
done
echo "DONE"
