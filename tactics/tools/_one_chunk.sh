#!/bin/bash
# 单个分片下载器，由 fetch_weights.sh 通过 xargs 调用
# 参数: <分片序号> <URL> <输出目录> <文件总长> <分片大小>
i=$1; URL=$2; OUT=$3; SIZE=$4; CHUNK=$5
S=$(( i * CHUNK ))
E=$(( S + CHUNK - 1 ))
[ "$E" -gt $(( SIZE - 1 )) ] && E=$(( SIZE - 1 ))
curl -sL -r "$S-$E" -o "$OUT/part_$(printf %06d "$i")" \
  --max-time 300 --retry 5 --retry-delay 2 --retry-all-errors "$URL"
