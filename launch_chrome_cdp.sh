#!/usr/bin/env bash
# 启动一个「独立临时 profile」的 Chrome 专用于 BR cookie 自动同步。
# - 用 /tmp/chrome_cdp_profile 临时目录，绝不污染你的日常浏览器（含书签/登录态）。
# - 开启远程调试端口 9222（cookie_refresher.py 默认连这个）。
# - 打开 basketball-reference.com，手动过一次 CF 挑战后保持窗口打开即可。
#
# 用法：bash launch_chrome_cdp.sh
# 关闭：直接关掉这个 Chrome 窗口即可（cookie 同步会随之停止，crawler 用最后一份有效 cookie 续跑）。

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT=9223   # 避开 agent 沙箱可能残留占用 9222 的 Chrome 僵尸（无 GUI，无法手动过 CF）
PROFILE="/tmp/chrome_cdp_profile"

if [ ! -x "$CHROME" ]; then
  echo "未找到 Google Chrome：$CHROME"
  echo "请修改本脚本的 CHROME 路径为你本机 Chrome/Chromium 可执行文件。"
  exit 1
fi

mkdir -p "$PROFILE"

# 后台启动，输出到日志；用户在前台窗口手动过 CF。
nohup "$CHROME" \
  --remote-debugging-port=$PORT \
  --user-data-dir="$PROFILE" \
  --no-first-run \
  --no-default-browser-check \
  --disable-background-networking \
  "https://www.basketball-reference.com" >/tmp/chrome_cdp.log 2>&1 &

echo "已启动独立 Chrome（PID $!），远程调试端口 $PORT。"
echo "请在弹出的窗口里手动过一次 Cloudflare 验证，然后保持窗口打开。"
echo "cookie_refresher.py 会每 10 分钟（首刷后）自动同步 cookie（CDP 模式下主要作回退备份 + 过期告警）。"
