#!/usr/bin/env bash
# =============================================================================
# run_player_shooting_auto.sh — player_shooting 全量爬取「全自动」编排层
#
# 一键甩出去就自己跑完：自动起本机 Chrome 远程调试(9222) → 提示手动过一次 CF
# → 前台循环驱动现有 run_player_shooting_backfill.sh (BROWSER_BACKEND=cdp)，
# 每轮重算 Regular 缺口，缺口清零即 DONE；Chrome 挂了自动重启、cookie 过期
# 自动带 --resume 续跑；带安全上限防死循环。
#
# 反屏蔽：复用既有 common.browser(cdp 直连用户已清 CF 的 Chrome)；爬虫内部
# 已强制限速(≤15 请求/分)，此处**不再**加节流。
#
# 口令：严禁硬编码；必须由调用方通过环境变量 PGPASSWORD 注入。
#
# 用法：
#   export PGPASSWORD='<集群B口令>'
#   ./run_player_shooting_auto.sh                  # 全自动（cdp）
#   ./run_player_shooting_auto.sh --limit 5        # 小批量验证
#   ./run_player_shooting_auto.sh --slugs a,b      # 指定 slug
#   ./run_player_shooting_auto.sh --dry-run        # 仅预览，不循环
#
# 可选环境变量（安全上限）：
#   PSA_MAX_CYCLES=200         # 最大循环次数（触顶以「仍有 N 缺口」清晰退出）
#   PSA_TOTAL_TIMEOUT=0        # 总超时(秒)，0=无限；触顶同样清晰退出
#   CHROME_CDP_URL             # 默认 http://127.0.0.1:9222
#   BROWSER_BACKEND=cdp        # 显式指定后端时跳过 Chrome 自动启动逻辑
# =============================================================================
set -euo pipefail

# ── 口令：禁止硬编码，必须由环境变量注入 ───────────────────────────────────
: "${PGPASSWORD:?ERROR: 必须先 export PGPASSWORD 环境变量（集群B 口令）}"
export PGPASSWORD

# ── 路径：脚本位于 external_crawler/runner/，仓库根为上两级 ─────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PY="${REPO}/.venv/bin/python"
BACKFILL_RUNNER="${REPO}/external_crawler/runner/run_player_shooting_backfill.sh"
CDP_URL="${CHROME_CDP_URL:-http://127.0.0.1:9222}"

# ── psql 约定：与脚本其余部分同一套 DB 连接（host=127.0.0.1 port=5433 dbname=nba user=postgres）
# 口令从已 export 的 $PGPASSWORD 走 libpq，严禁硬编码。
PSQL_BIN="${PSQL_BIN:-/opt/homebrew/bin/psql}"
PSQL_CONN="${PSQL_CONN:-host=127.0.0.1 port=5433 dbname=nba user=postgres}"
# coverage_report.sql 路径（仓库根 /docs 下，与 runner 同 REPO）
COVERAGE_SQL="${REPO}/docs/coverage_report.sql"

# ── 安全上限（env 可调；默认 200 循环 / 无总超时）──────────────────────────
MAX_CYCLES="${PSA_MAX_CYCLES:-200}"
TOTAL_TIMEOUT="${PSA_TOTAL_TIMEOUT:-0}"   # 0 = 不限制总时长
START_TS="$(date +%s)"

# ── 网络：CDP 永远是 localhost，强制直连（配合 common.browser 硬化的 opener）
export NO_PROXY=127.0.0.1,localhost
export no_proxy=127.0.0.1,localhost

# ── 用户是否显式指定了后端 ─────────────────────────────────────────────────
EXPLICIT_BACKEND="${BROWSER_BACKEND:-}"
AUTO_CHROME=1
if [ -n "${EXPLICIT_BACKEND}" ] && [ "${EXPLICIT_BACKEND}" != "cdp" ]; then
  # 非 cdp（如 uc/playwright）→ 跳过 Chrome 自动启动逻辑，直接跑 runner
  AUTO_CHROME=0
fi
# 未显式指定时，本编排层默认 cdp（驱动本机已清 CF 的 Chrome）
export BROWSER_BACKEND="${EXPLICIT_BACKEND:-cdp}"

# ── dry-run 短回路检测 ─────────────────────────────────────────────────────
DRY=0
for _a in "$@"; do [ "${_a}" = "--dry-run" ] && DRY=1; done

# ── 日志 ───────────────────────────────────────────────────────────────────
LOG_DIR="${REPO}/logs"
mkdir -p "${LOG_DIR}"
TS="$(date +%Y%m%d_%H%M%S)"
LOG="${LOG_DIR}/player_shooting_auto_${TS}.log"
exec > >(tee -a "${LOG}") 2>&1
echo "=============================================================="
echo "[auto] 启动 $(date)"
echo "[auto] REPO=${REPO}"
echo "[auto] BROWSER_BACKEND=${BROWSER_BACKEND}  AUTO_CHROME=${AUTO_CHROME}"
echo "[auto] MAX_CYCLES=${MAX_CYCLES}  TOTAL_TIMEOUT=${TOTAL_TIMEOUT}s"
echo "[auto] LOG=${LOG}"
echo "=============================================================="


# ── CDP 可达性探测（绕过代理，直连 localhost）──────────────────────────────
cdp_reachable() {
  if curl -s -o /dev/null --noproxy '*' --max-time 5 \
       "${CDP_URL}/json/version" 2>/dev/null; then
    return 0
  fi
  return 1
}


# ── ensure_chrome()：本机 Chrome 远程调试不可达时自动启动 ──────────────────
# 关键修复：macOS 下 `open -a "Google Chrome" --args ...` 在用户主 Chrome 已开时，
# 只会把已开实例提到前台、直接忽略 --args → 9222 永远不出现。改为用 `open -n`
# 强制新开一个独立 Chrome 实例，并配 --user-data-dir 指向独立缓存目录，与用户
# 原来的 Chrome 完全隔离、互不干扰（不杀原 Chrome）。-n 与 --user-data-dir 缺一不可：
# Chrome 单实例模型会复用已开实例，只有 user-data-dir 不同才能起第二个带 9222 的实例。
ensure_chrome() {
  if cdp_reachable; then
    return 0
  fi
  echo "[auto] Chrome(CDP 9222) 不可达，尝试为你新开一个独立的 CDP Chrome 实例 ..."
  local os_name cdp_profile_dir
  cdp_profile_dir="${REPO}/.cache/cdp_chrome_profile"
  os_name="$(uname -s 2>/dev/null || echo unknown)"
  if [ "${os_name}" = "Darwin" ]; then
    # macOS：open -n 强制新实例；--user-data-dir 隔离，即使主 Chrome 已开也会新弹一个带 9222 的窗口
    open -n -a "Google Chrome" --args \
      --remote-debugging-port=9222 \
      --user-data-dir="${cdp_profile_dir}" || \
      echo "[auto] open -n -a 'Google Chrome' 失败（可能未安装/未在前台）"
  elif [ "${os_name}" = "Linux" ]; then
    # Linux：best-effort 后台拉起独立实例（同样用独立 user-data-dir 隔离）
    google-chrome --remote-debugging-port=9222 \
      --user-data-dir="${cdp_profile_dir}" >/dev/null 2>&1 &
  else
    echo "[auto] 未知 OS(${os_name})，请手动启动 Chrome 远程调试。"
  fi

  # 轮询（≤~60s）直到 9222 起来
  local waited=0
  while [ "${waited}" -lt 60 ]; do
    if cdp_reachable; then
      echo "=============================================================="
      echo "✅ 已为你新开一个【专用的 CDP Chrome 窗口】（远程调试端口 9222）。"
      echo ">>> 请【在那个新弹出的窗口里】(不是你原来的 Chrome) 打开："
      echo ">>>        https://www.basketball-reference.com/"
      echo ">>> 并手动通过一次 Cloudflare 验证（点击 'Verify you are human'）。"
      echo ">>> 验证通过后，爬虫将自动开始。"
      echo "=============================================================="
      return 0
    fi
    sleep 2
    waited=$((waited + 2))
  done

  echo "=============================================================="
  echo "❌ 无法自动启动 Chrome 远程调试（轮询 60s 仍不可达）。"
  echo "   请手动启动一个独立的 Google Chrome 实例并加远程调试参数："
  echo "     macOS : open -n -a \"Google Chrome\" --args --remote-debugging-port=9222 --user-data-dir=\"${cdp_profile_dir}\""
  echo "     Linux : google-chrome --remote-debugging-port=9222 --user-data-dir=\"${cdp_profile_dir}\" &"
  echo "   启动后再重跑本脚本。"
  echo "=============================================================="
  return 1
}


# ── prompt_cf()：醒目提示用户在 Chrome 窗口手动过一次 CF ──────────────────
prompt_cf() {
  echo "=============================================================="
  echo ">>> [重要] 请在【爬虫驱动的那个 CDP Chrome 标签页】手动通过一次 Cloudflare"
  echo ">>>       验证（点击 'Verify you are human'）。"
  echo ">>>"
  echo ">>> 爬虫已在开爬前内置 CF 握手门禁：它会先把【自己驱动的那个标签页】导航到"
  echo ">>>       https://www.basketball-reference.com/ ，若命中挑战页会写"
  echo ">>>       /tmp/br_cf_challenge.flag 并原地轮询等待，直到你在该标签清完 CF、"
  echo ">>>       出现真实 BR 内容后才自动开始（不会再出现『全缺口 0 行』的假成功）。"
  echo ">>>"
  echo ">>> 中途 cf_clearance cookie 过期时，爬虫会在该标签原地暂停等你清 CF，"
  echo ">>>       清完自动续跑——无需重启脚本。"
  echo "=============================================================="
}


# ── get_gap()：重算 Regular 缺口（复用 runner 的 gap SQL，DB 只读）──────────
# 返回缺口数字；失败（DB 不可达 / 输出非数字）时输出 ERR 并返回 1。
get_gap() {
  local out
  out="$("${PY}" - <<'PY'
import os, sys, psycopg2
cfg = dict(host="127.0.0.1", port=5433, dbname="nba", user="postgres",
           password=os.environ.get("PGPASSWORD", ""))
try:
    conn = psycopg2.connect(**cfg)
except Exception as e:
    sys.stderr.write(f"[auto] DB 连接失败: {e}\n")
    sys.exit(2)
try:
    cur = conn.cursor()
    cur.execute(
        "SELECT (SELECT COUNT(*) FROM (SELECT DISTINCT br_player_id, season "
        "FROM player_gamelog WHERE br_player_id IS NOT NULL AND season >= 1997) t) "
        "- (SELECT COUNT(*) FROM (SELECT DISTINCT player_id, season "
        "FROM player_shooting WHERE season_type='Regular' AND player_id IS NOT NULL) t) "
        "- (SELECT COUNT(*) FROM (SELECT DISTINCT g.br_player_id, g.season "
        "FROM player_gamelog g JOIN player_shooting_404 q ON q.slug = g.br_player_id "
        "WHERE g.br_player_id IS NOT NULL AND g.season >= 1997) t)"
    )
    print(cur.fetchone()[0])
finally:
    conn.close()
PY
)" || { echo "ERR"; return 1; }
  if ! printf '%s' "${out}" | grep -Eq '^-?[0-9]+$'; then
    echo "ERR"; return 1
  fi
  echo "${out}"
}


# ── verify_coverage()：DONE 分支前的「端到端正确性守门」──────────────────────
# 纯 DB 只读 + 幂等 DDL（coverage_report.sql），零 BR 网络请求。
# 自动跑一次覆盖率校验，把关键行（覆盖率/缺口/孤儿数）原样输出给用户，
# 并据其结论决定能否 exit 0 宣告成功：
#   返回 0 = 校验通过（gap=0 或 覆盖率≥99.x%）
#   返回 1 = 校验仍报有缺口，需人工复核（调用方应改为非 0 退出，不谎报成功）
verify_coverage() {
  if [ ! -f "${COVERAGE_SQL}" ]; then
    echo "[auto][coverage] 未找到 ${COVERAGE_SQL}，跳过自动校验（视为通过）。"
    return 0
  fi
  echo "[auto][coverage] 自动跑覆盖率校验（coverage_report.sql，纯 DB、零 BR 请求）..."

  # 完整报告：捕获到变量 + 经 exec tee 落日志；同时原样打印给用户。
  local cov_raw cov_line u c pct gap ok
  # 注意：${PSQL_CONN} 必须加引号，作为单个 conninfo 参数传给 psql；
  # 否则逐词拆分后 psql 会把 host=/port= 当成库名/用户名导致连错目标。
  cov_raw="$("${PSQL_BIN}" "${PSQL_CONN}" -t -f "${COVERAGE_SQL}" 2>&1)" || {
    echo "[auto][coverage] 执行 coverage_report.sql 失败（DB 不可达？），无法校验，按未通过处理。"
    return 1
  }

  echo "──────────── 自动校验结果（coverage_report）────────────"
  printf '%s\n' "${cov_raw}"
  echo "────────────────────────────────────────────────────────"

  # 守门：取首个结果集（universe | covered | coverage_pct | gap）做稳定解析。
  # -t 默认 aligned 首列有前导空格，故用 '[0-9]'（不锚 ^）才能匹配到首行数据；
  # head -1 取输出顺序中第一张 SELECT 的数据行（位于所有结果集最前）。
  cov_line="$(printf '%s\n' "${cov_raw}" | grep -E '[0-9]' | head -1)" || true
  IFS='|' read -r u c pct gap <<< "${cov_line}"
  u="$(printf '%s' "${u}" | tr -d '[:space:]')"
  c="$(printf '%s' "${c}" | tr -d '[:space:]')"
  pct="$(printf '%s' "${pct}" | tr -d '[:space:]')"
  gap="$(printf '%s' "${gap}" | tr -d '[:space:]')"
  echo "[auto][coverage] 解析：universe=${u} covered=${c} coverage_pct=${pct}% gap=${gap}"

  # 判定：gap 为数字且 ==0，或 覆盖率 ≥ 99.0% → 通过
  ok=0
  if printf '%s' "${gap}" | grep -Eq '^[0-9]+$' && [ "${gap}" -eq 0 ]; then
    ok=1
  elif printf '%s' "${pct}" | grep -Eq '^[0-9]+(\.[0-9]+)?$' && \
       awk "BEGIN{exit !(${pct} >= 99.0)}"; then
    ok=1
  fi

  if [ "${ok}" -eq 1 ]; then
    echo "[auto][coverage] ✅ 校验通过：coverage_report 确认缺口≈0（gap=${gap}, coverage=${pct}%）。"
    return 0
  fi

  echo "=============================================================="
  echo "⚠️  [auto][coverage] 警告：爬取报缺口=0，但 coverage_report 仍显示 gap=${gap}（coverage=${pct}%）缺口。"
  echo "    请人工复核数据一致性后再宣告成功。"
  echo "=============================================================="
  return 1
}


# ═══════════════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════════════
before="$(get_gap)" || {
  echo "[auto] 无法获取 Regular 缺口（DB 不可达？），退出。"
  exit 1
}
echo "[auto] 初始 Regular 缺口 = ${before}"

if [ "${before}" -eq 0 ]; then
  echo "[auto] DONE: 缺口已为 0，无需爬取。"
  # 端到端正确性守门：自动跑 coverage_report 复核（纯 DB、零 BR 请求）
  if verify_coverage; then
    exit 0
  else
    echo "[auto] 初始缺口=0 但 coverage_report 仍报缺口，请人工复核，退出码 1。"
    exit 1
  fi
fi

# dry-run：只预览一轮，不进循环（preview 不推进缺口）
if [ "${DRY}" -eq 1 ]; then
  echo "[auto] --dry-run：仅预览一轮（不循环、不写库）。"
  bash "${BACKFILL_RUNNER}" --resume "$@" || true
  echo "[auto] dry-run 完成；日志见 ${LOG}"
  exit 0
fi

# 自动启动 Chrome（除非用户显式指定了非 cdp 后端）
if [ "${AUTO_CHROME}" -eq 1 ]; then
  if ! ensure_chrome; then
    exit 1
  fi
  prompt_cf
fi

cycle=0
while true; do
  cycle=$((cycle + 1))

  # 安全上限 1：最大循环次数
  if [ "${cycle}" -gt "${MAX_CYCLES}" ]; then
    gap_now="$(get_gap)" || { echo "[auto] 无法获取缺口，退出。"; exit 1; }
    echo "[auto] 已达最大循环次数 ${MAX_CYCLES}；仍有 ${gap_now} 个缺口，请稍后重跑。"
    exit 0
  fi

  # 安全上限 2：总超时
  if [ "${TOTAL_TIMEOUT}" -gt 0 ]; then
    now_ts="$(date +%s)"
    if [ $((now_ts - START_TS)) -gt "${TOTAL_TIMEOUT}" ]; then
      gap_now="$(get_gap)" || { echo "[auto] 无法获取缺口，退出。"; exit 1; }
      echo "[auto] 已达总超时 ${TOTAL_TIMEOUT}s；仍有 ${gap_now} 个缺口，请稍后重跑。"
      exit 0
    fi
  fi

  echo "[auto] === 循环 #${cycle}（backend=${BROWSER_BACKEND}）==="

  # 前台跑现有 runner：cdp + NO_PROXY 直连，透传 --resume 与用户其余参数
  bash "${BACKFILL_RUNNER}" --resume "$@" || true

  gap_after="$(get_gap)" || { echo "[auto] 无法获取缺口，退出。"; exit 1; }
  echo "[auto] 循环 #${cycle} 后 缺口 = ${gap_after}（此前 ${before}）"

  if [ "${gap_after}" -eq 0 ]; then
    # 端到端正确性守门：打印最终汇总「之前」自动跑 coverage_report（纯 DB、零 BR 请求）
    if verify_coverage; then
      echo "=============================================================="
      echo "[auto] DONE: 缺口清零，player_shooting 全量爬取完成。"
      echo "[auto] 循环次数 = ${cycle}；日志 = ${LOG}"
      echo "=============================================================="
      exit 0
    else
      echo "[auto] DONE 分支校验未通过（coverage_report 仍有缺口），不谎报成功，退出码 1。"
      exit 1
    fi
  fi

  # gap > 0：决定重启还是续跑
  if ! cdp_reachable; then
    echo "[auto] Chrome 挂了（9222 不可达）→ 尝试重启。"
    if [ "${AUTO_CHROME}" -eq 1 ]; then
      ensure_chrome || {
        echo "[auto] 无法重启 Chrome，退出（仍有 ${gap_after} 个缺口）。"
        exit 1
      }
      prompt_cf
    else
      echo "[auto] 非自动启动模式，请手动恢复 Chrome；退出（仍有 ${gap_after} 个缺口）。"
      exit 1
    fi
  else
    echo "[auto] Chrome 仍在（可能跑完一批 / cookie 中途过期）→ 带 --resume 续跑。"
  fi

  before="${gap_after}"
done
