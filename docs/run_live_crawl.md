# 统一 30 队 BR 球队页爬取 — 运行手册 (Runbook)

本手册定稿 **统一编排器 `crawl_team_pages.py`** 的用法：一个入口对全部 30 队
依次爬 **交易(多年倒序) + 名人堂(HOF) + 高管(executives)**，复用
`transactions_crawl` / `hof_exec` 两包已验证的 fetch / parse / load，统一断点续爬
与进度统计。**不改任何表结构**（零 DDL；唯一约束 `(tx_date,abbr,desc)` /
`(tx_abbr,season,player)` / `(tx_abbr,rk)` 直接复用，孪生去重 upsert 自然修复
旧拼接 bug）。

> ⚠️ **在线爬取必须在本机 Mac 跑，不在沙箱。**
> 沙箱被 Cloudflare 挡（`CF 403` / JS challenge）且无 Chrome 配置；离线
> `DET` 回放（`--offline-dir`）是唯一可在 CI/沙箱跑的部分。

## 范围边界
仅 **transactions + HOF + executives** 三类。coaches / draft / retired_numbers /
players / all_star / leaders 等其它 BR 分区属独立管线，**OUT OF SCOPE**。

## 前置条件（Mac 本机）
- Python 3.11+，项目 `.venv` 已激活。
- `undetected_chromedriver` + 可用的 Chrome（驱动真实 UC Chrome，复用
  `.uc_br_profile` 会话 cookie 策略过 CF）。
- 项目根 `.env` 含 `DB_PASSWORD`（loader `hof_exec.config.get_conn` 读取，
  **绝不硬编码**）。
- Postgres 可达：`localhost:5433`（dbname `nba`，user `postgres`）。
- `bs4` 已装于 `.venv`（未在 `requirements.txt` 中声明，但本机已可用）。

```bash
cd /path/to/nba_desktop_omega_mac_migrate
source .venv/bin/activate
```

## 三阶段「年份分阶段滚动」
在线连跑 30 队 × 多年必遇 CF 限速，故按年份分段、确认前一阶段稳了再放下一阶段。
三个阶段只是同一编排器的不同 `--year-start/--year-end` 参数：

```bash
# 阶段①（现在，推荐首轮）：2000 → 2026
.venv/bin/python -m crawl_team_pages --all-teams --year-start 2000 --year-end 2026

# 阶段②：1980 → 2000（确认①稳了再放）
.venv/bin/python -m crawl_team_pages --all-teams --year-start 1980 --year-end 2000

# 阶段③（剩余历史）：1947 → 1979
.venv/bin/python -m crawl_team_pages --all-teams --year-start 1947 --year-end 1979
```

便捷脚本 `run_br_team_pages.sh` 封装了上述三阶段（自动加载 `.env` 与 `PYTHONPATH`）：

```bash
bash run_br_team_pages.sh            # 阶段①（默认）
bash run_br_team_pages.sh stage2    # 1980→2000
bash run_br_team_pages.sh stage3    # 1947→1979
bash run_br_team_pages.sh all       # ①②③ 连续
```

## 单队 / 单类型
```bash
# 单队
.venv/bin/python -m crawl_team_pages --team DET

# 只爬交易 / HOF / 高管
.venv/bin/python -m crawl_team_pages --all-teams --kind trans
.venv/bin/python -m crawl_team_pages --all-teams --kind hof
.venv/bin/python -m crawl_team_pages --all-teams --kind exec
```

## 断点续爬 / CF 命中策略
- **CF 挑战 / 404 命中即 SKIP 继续**（记日志，不中断整轮）；在线抓取会把 raw HTML
  缓存到 `det2026_br/`，二次运行自动跳过已完成项。
- **续跑靠双重保险 + 显式进度文件**：① 落库 `upsert` 幂等（`ON CONFLICT` / 孪生
  `UPDATE`）；② raw HTML 离线缓存；  ③ 编排器写 `crawl_state.json`（仓库根）记录
  已完成 abbr 清单，按签名 `kind:year_start-year_end` 划分。参数不变时二次运行
  自动跳过已完成队（日志 `RESUME skip`）；`--force` 强制重跑所有队；`--reset-state`
  清空进度文件后重跑。字段格式见 `crawl_state.example.json`：
  ```json
  { "signature": "all:2000-2026:online", "completed": ["ATL", "BOS"] }
  ```
- 日志盯 `SKIP`（应只来自 CF/404/缺页）、`PROGRESS n/30 teams done` 与
  `LOADED <abbr>/<year>: N rows`；收尾打印 `DONE totals: transactions=N hof=M exec=K`。

## 限速建议
BR/CF 会限流激进请求。建议分批而非一次梭哈：按分区（东/西）或单队循环，
队间 `sleep 5`。示例单队循环：

```bash
for t in BOS BKN NYK PHI TOR CHI CLE DET IND MIL ATL CHA MIA ORL WAS \
         DEN MIN OKC POR UTA GSW LAC LAL PHX SAC DAL HOU MEM NOP SAS; do
  echo "=== $t ==="
  .venv/bin/python -m crawl_team_pages --team "$t"
  sleep 5
done
```

## 离线 DET 回放（沙箱安全，已验证）
无 DB、无网络，用 `det2026_br/` 下捕获的 DET 离线文件回放三类解析并校验：

```bash
# 解析层单测（含拼接 bug 守卫、多集合相等）
.venv/bin/python -m pytest tests/test_team_pages_offline.py -v

# 编排器离线回放（会真实 upsert 到本机 DB；DET 三类 LOADED，其余 29 队因无
# 离线文件被 SKIP，EXIT=0 不崩）
.venv/bin/python -m crawl_team_pages --all-teams --year-start 2000 --year-end 2026 --offline-dir det2026_br
```

## 运行后核验（SQL）
```sql
SELECT team_abbr, count(*) FROM transactions      GROUP BY team_abbr ORDER BY team_abbr;
SELECT team_abbr, count(*) FROM team_hof         GROUP BY team_abbr ORDER BY team_abbr;
SELECT team_abbr, count(*) FROM team_executives GROUP BY team_abbr ORDER BY team_abbr;
```

## 历史 fallback：仅 HOF / executives（旧管线，仍可用）
若只需 HOF + executives（不含交易），可直接用 `hof_exec` 包（早于统一编排器存在）：

```bash
.venv/bin/python -m hof_exec --all-teams --kind both
.venv/bin/python -m hof_exec --offline-dir det2026_br --team DET --kind both
```
