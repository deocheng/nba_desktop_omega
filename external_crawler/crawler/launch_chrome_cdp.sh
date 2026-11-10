#!/bin/bash
# 启动本机 Chrome CDP（端口 9223），供 BR 抓取走真实浏览器渲染（绕过 Cloudflare 挑战）。
# profile 位于数据盘，已含有效 cf_clearance，重启后仍然有效（绝不 clearBrowserCookies）。
# 注意：剥离代理环境变量，避免把 127.0.0.1 请求错发到代理。
set -u
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE="/Volumes/12T/NBA/chrome_cdp_profile"
PORT=9223

rm -f "$PROFILE/SingletonLock" 2>/dev/null

exec env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  "$CHROME" \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=$PORT \
  --remote-allow-origins='*' \
  --user-data-dir="$PROFILE" \
  --no-proxy-server \
  --no-sandbox \
  --disable-dev-shm-usage \
  --no-first-run \
  --no-default-browser-check \
  --disable-background-networking \
  --disable-features=Translate,OptimizationHints,MediaRouter \
  https://www.basketball-reference.com/
