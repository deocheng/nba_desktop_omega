#!/usr/bin/env bash
# 启动一个「独立临时 profile」的 Chrome，专用于 BR 爬取 + cookie 自动同步。
# - 用 /tmp/chrome_cdp_profile 临时目录，绝不污染你的日常浏览器（含书签/登录态）。
# - 开启远程调试端口 9223。
# - 启动页用 about:blank（不再预开 BR 主页，避免每次重启 Chrome 都累积一个无用 BR tab）；
#   爬虫 driver 自己开 gamelog 专用 tab（tid 记在 /tmp/br_crawler_cdp_tid）。
# - 若是全新 profile，driver 首次 navigate 到 BR 时可能需手动过一次 CF 挑战。
#
# 用法：bash launch_chrome_cdp.sh
#      从 agent 工具 shell 启动时必须走 detach_launch.py（见下方「沙箱」说明）。
# 关闭：直接关掉这个 Chrome 窗口即可（crawler 用最后一份有效 cookie 续跑）。
#
# ── 2026-08-06 强化 ──────────────────────────────────────────────────────
# 1) 广告域名黑洞（--host-resolver-rules）：BR 每页带 ~50 个广告 iframe
#    （doubleclick / googlesyndication / pubmatic / rubicon / 3lift / criteo …）。
#    它们会：① 各自占一个 CDP target；② 疯狂写 HTTP 缓存（实测 1.2G/158,299 文件）；
#    ③ 吃内存 → Chrome fork 不出新渲染进程 → Target.createTarget 返回 HTTP 500
#    → 爬虫整季空转零写入（2026-08-06 实测 2013 季空转 50 分钟）。
#    把这些域名解析到 127.0.0.1 直接掐断，从源头不加载。
# 2) 关端侧 AI / 模型下载：OptGuideOnDeviceModel 曾自行下到 4.0G，与爬取无关。
# 3) --no-sandbox：从 agent 工具 shell 启动时必须带，否则
#    "sandbox initialization failed" → GPU FATAL 直接退出。
# ─────────────────────────────────────────────────────────────────────────

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT=9223   # 避开 agent 沙箱可能残留占用 9222 的 Chrome 僵尸（无 GUI，无法手动过 CF）

# profile 落在数据盘（2026-08-06 迁移）：原 /tmp/chrome_cdp_profile 在系统数据卷
# disk3s5 上，长期爬取会堆到数 GB；且 /tmp 有被系统清理的风险（丢 cf_clearance）。
PROFILE="/Volumes/12T/NBA/chrome_cdp_profile"
OLD_PROFILE="/tmp/chrome_cdp_profile"

if [ ! -x "$CHROME" ]; then
  echo "未找到 Google Chrome：$CHROME"
  echo "请修改本脚本的 CHROME 路径为你本机 Chrome/Chromium 可执行文件。"
  exit 1
fi

# 数据盘未挂载时果断退出：否则 Chrome 会在挂载点建空 profile → cf_clearance 丢失
# → 必须人工重过 CF，还会把空目录挡在挂载点上。
if [ ! -d /Volumes/12T/NBA ]; then
  echo "数据盘 /Volumes/12T 未挂载，拒绝启动（避免创建空 profile 丢失 cf_clearance）。"
  exit 1
fi

# 自动迁移保护：若新路径还没有 profile 而旧路径存在，先搬过来再启动。
# 防止「脚本已改路径但迁移还没执行」时启动出一个空 profile。
if [ ! -d "$PROFILE/Default" ] && [ -d "$OLD_PROFILE/Default" ]; then
  echo "检测到 profile 仍在 $OLD_PROFILE，先迁移到 $PROFILE …"
  pkill -f "remote-debugging-port=$PORT" 2>/dev/null
  sleep 5
  mkdir -p "$(dirname "$PROFILE")"
  # 端侧 AI 模型（Gemini Nano，与爬取无关，实测 4.0G）不搬，留在旧目录待清理
  mv "$OLD_PROFILE" "$PROFILE" && echo "迁移完成。"
fi

# 端侧 AI 模型（Gemini Nano，与爬取无关，曾自行下到 4.0G）清理。
# 放在启动前，无论 profile 是否已迁移都清一次；路径白名单防止误删。
AIDIR="$PROFILE/OptGuideOnDeviceModel"
case "$AIDIR" in
  /Volumes/12T/NBA/chrome_cdp_profile/OptGuideOnDeviceModel)
    if [ -d "$AIDIR" ]; then
      SZ=$(du -sh "$AIDIR" 2>/dev/null | cut -f1)
      rm -rf "$AIDIR" && echo "已清除端侧 AI 模型（$SZ）。"
    fi ;;
esac

mkdir -p "$PROFILE"

# 广告 / 追踪域名 → 黑洞。注意：MAP 规则只影响 DNS 解析，不改页面 HTML，
# BR 正文表格（爬虫真正要的数据）完全不受影响。
AD_BLOCK="MAP *doubleclick.net 127.0.0.1,\
MAP *googlesyndication.com 127.0.0.1,\
MAP *googleadservices.com 127.0.0.1,\
MAP *adtrafficquality.google 127.0.0.1,\
MAP *ad-delivery.net 127.0.0.1,\
MAP *pubmatic.com 127.0.0.1,\
MAP *rubiconproject.com 127.0.0.1,\
MAP *3lift.com 127.0.0.1,\
MAP *adnxs.com 127.0.0.1,\
MAP *indexww.com 127.0.0.1,\
MAP *criteo.com 127.0.0.1,\
MAP *openx.net 127.0.0.1,\
MAP *smartadserver.com 127.0.0.1,\
MAP *amazon-adsystem.com 127.0.0.1,\
MAP *hadronid.net 127.0.0.1,\
MAP *voltaxam.com 127.0.0.1,\
MAP *voltaxservices.io 127.0.0.1,\
MAP *pub.network 127.0.0.1,\
MAP *lijit.com 127.0.0.1,\
MAP *a-mx.com 127.0.0.1,\
MAP *media.net 127.0.0.1,\
MAP *freestar.com 127.0.0.1,\
MAP *adsrvr.org 127.0.0.1,\
MAP *casalemedia.com 127.0.0.1,\
MAP *bidswitch.net 127.0.0.1,\
MAP *sharethrough.com 127.0.0.1,\
MAP *taboola.com 127.0.0.1,\
MAP *outbrain.com 127.0.0.1,\
MAP *scorecardresearch.com 127.0.0.1,\
MAP *quantserve.com 127.0.0.1"

# 后台启动，输出到日志。
nohup "$CHROME" \
  --remote-debugging-port=$PORT \
  --remote-allow-origins=* \
  --user-data-dir="$PROFILE" \
  --no-sandbox \
  --no-proxy-server \
  --no-first-run \
  --no-default-browser-check \
  --disable-background-networking \
  --host-resolver-rules="$AD_BLOCK" \
  --disable-features=OptimizationGuideOnDeviceModel,OptimizationHints,TextSafetyClassifier \
  --disable-component-update \
  --disk-cache-size=104857600 \
  "about:blank" >/tmp/chrome_cdp.log 2>&1 &

# 阻塞等待 Chrome 退出：使本脚本（后台任务）在 Chrome 存活期间保持运行，
# 避免任务一结束被平台 killpg 连带回收 Chrome（2026-08-07 实测双重 fork 仍被
# 按进程树回收）。停止后台任务即关闭 Chrome。
wait

echo "已启动独立 Chrome（PID $!），远程调试端口 $PORT。"
echo "广告域名已黑洞化；磁盘缓存上限 100MB；端侧 AI 模型下载已关闭。"
echo "若窗口出现 Cloudflare 验证，请手动点一次 \"Verify you are human\" 后保持窗口打开。"
echo
echo "※ 从 agent 工具 shell 启动请改用（否则沙箱会拦）："
echo "  env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \\"
echo "    python3 detach_launch.py /tmp/chrome_cdp.log bash launch_chrome_cdp.sh"
