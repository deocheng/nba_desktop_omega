# 家族迁移清单 — 旧 crawler/ → crawler_v2/

> 本文件逐类映射旧版 `external_crawler/crawler/`（~130 文件）+ 迁移包根 `*.py`（~100 文件）到 v2 模块，
> 并**诚实标注每项状态**。v2 不是对 200+ 文件的 1:1 重写（那会违反"严禁凭空猜"铁律——未读文件不能瞎编），
> 而是先夯**架构骨架 + core 抽象层 + 两个核心爬虫忠实重构 + 守护层 + parser fixture 测试**这组家族核心，
> 其余卫星爬虫按统一路径机械接入。

---

## A. 已完成（已在 v2 实现，复用旧 parse/DB 函数，未重造）

| 旧文件（旧版零改动） | v2 落地 | 迁移状态 |
|---|---|---|
| `crawler/crawl_br_gamelog.py` (1306行) | `adapters/br_gamelog_adapter.py` | ✅ 忠实重构（lazy import 复用 `parse_gamelog_html`/`build_insert`/`_fetch_html`/`canon_team`/`get_game_id_map`/`get_game_id_full_map`/`load_player_id_bridge`/`get_players`/`BRServerError`/`save/load/has_gamelog_html`） |
| `br_fill_pbp.py` + `br_pbp_parse.py` | `adapters/br_pbp_adapter.py` | ✅ 忠实重构（复用 `parse_pbp` + `raw_archiver.save_br_html`） |
| `crawler/crawler_watchdog.sh` + `crawler_watchdog_v2.sh` + `nba_daily_crawler.BrowserManager` | `daemon/watchdog.py` | ✅ Python 重写（DB 行数判卡死；DB 失败≠卡死 v2 修复点；CF墙 MAX_STALL→PAUSED；单例锁/stop/heartbeat；status·stop 子命令） |
| `crawler/recrawl_2004_2026_autofill.sh` / `recrawl_2004_2026.sh` / `recrawl_2004_2022.sh` | `daemon/runner.py` | ✅ Python 重写（赛季倒序 2026→1980；STATE/BYPASSED/FAILURES/STOP_AFTER；verify_gaps 门禁 subprocess 复用；handoff_watcher 降级；pre_delete_orphans） |
| `crawler/verify_gaps.py` | 沿用（runner 以 subprocess 调用） | ✅ 不迁移，v2 单向复用 |
| `raw_archiver.py` | `core/cache.py` 概念对应 | ✅ 缓存抽象建模（TTL + 持久化 + 工厂） |
| `nba_daily_crawler` 限流/CF 判定思路 | `core/retry.py` + `core/proxy.py:CfClearanceProvider` | ✅ cf_breaker 接口化为带 TTL 的 provider |
| 旧脚本里的 fetch→parse→normalize 串接 | `core/base_crawler.py:BaseCrawler` | ✅ 模板方法 + `RateLimiter` + `SessionGone` |

**核心抽象层**（全部新建，无旧对应、为 v2 新增）：
- `core/config.py` — DB 配置 / CDP URL / 出站点代理清除（沿用旧约定）
- `core/retry.py` — 请求级重试装饰器（stdlib 自研，免 tenacity 依赖）
- `core/cache.py` — `AbsCache` + `LocalCache(TTL)` + `CacheFactory`
- `core/proxy.py` — `ProxyProvider` / `StaticProxyProvider` / `CfClearanceProvider(TTL)`
- `core/store.py` — `Store` 抽象 + `PGStore`(§6 参数化) + `CsvJsonDump` + `StoreFactory`

**测试**：
- `tests/test_br_pbp_parser.py` — 5 passed（真实 PBP 归档 HTML）
- `tests/test_br_gamelog_parser.py` — 3 passed（真实 gamelog 归档 HTML）
- `tests/fixtures/` — 3 PBP + 2 gamelog 真实样本（只读拷贝）

---

## B. 脚手架（SCAFFOLD，仅定义统一接口契约，未接真实解析）

| v2 文件 | 状态 | 说明 |
|---|---|---|
| `adapters/espn_adapter.py` | 🟡 SCAFFOLD | 子类化 `BaseCrawler`，`fetch/parse/normalize` 抛 `NotImplementedError`，为 ESPN 跨源对齐预留契约 |
| `adapters/nba_api_adapter.py` | 🟡 SCAFFOLD | 同上，为 nba_api 跨源对齐预留契约 |
| `adapters/br_team_adapter.py`（runner.handoff 切到的"球队数据"源） | ⚪ 待补 | `runner.handoff_watcher` 已建模调用，缺失时降级跳过（不致命、不空转） |

---

## C. 沿用不迁移（旧脚本仍可直接用，v2 不重复实现）

| 旧文件 | 原因 |
|---|---|
| `launch_chrome_cdp.sh` | watchdog 重启 CDP Chrome 仍 shell out 调用本脚本，未重写 |
| `watch_apply_adblock.sh` / `watch_apply_adblock_v2.sh` | 浏览器去广告注入，独立于爬取核心 |
| `crawler_control.sh` / `crawler_dashboard.py` / `start_crawler_standalone.sh` / `start_watchdog_detached.sh` | 被 `daemon/watchdog` + `daemon/runner` 的 status·stop 子命令替代；旧版保留作应急 |
| `crawl_with_timeout.sh` | 被 `core/retry.py` + 适配器内 `threading.Timer` 思路替代 |

---

## D. 待迁移卫星爬虫（同源模式，需逐文件读后接入 BaseCrawler）

> 这些脚本各自有领域 parse 逻辑，**未读不能重写**。统一迁移路径（机械、低风险）：
> 1. 在 `adapters/` 新建 `br_<domain>_adapter.py`，子类化 `BaseCrawler`；
> 2. 用 `_legacy()` lazy import 复用旧脚本里**已验证的 parse/DB 函数**（同 gamelog 适配器做法）；
> 3. `normalize()` 用 `core/store.PGStore.save` 落库（§6 参数化）；
> 4. 补 `tests/test_br_<domain>_parser.py`（录真实页→跑旧 parse→断言）。
> 以下按类别列出代表性文件（非穷举，完整清单以 `crawler/` 实际目录为准）：

**D1. 球员级卫星**
- `crawl_br_player_shot_chart.py`（shot 坐标、home/away 逆转修复相关）、`crawl_br_player_shooting.py`
- `crawl_br_player_lineup.py`、`crawl_br_player_onoff.py`、`crawl_br_player_page_extras.py`
- `crawl_br_player_bio_ext.py`、`crawl_br_nicknames.py`、`crawl_br_headshots.py`

**D2. 球队级卫星**
- `crawl_br_team_pbp.py` / `crawl_br_team_pbp_v2.py`、`crawl_br_team_shooting.py`
- `crawl_br_team_lineups.py`、`crawl_br_team_onoff.py`、`crawl_br_team_page_extras.py`
- `crawl_br_team_depth.py`、`crawl_br_team_referees.py`、`crawl_br_team_logos.py`、`crawl_br_transactions.py`

**D3. EPM / 薪资 / 合同（多为 ESPN/nba_api/第三方源，将走 B 的跨源适配器）**
- `crawl_dunksandthrees_epm*.py`（多已在别处落地）、`scrape_historical_salaries.py`
- `scrape_player_weight.py`、`scrape_team_contracts.py`、`injuries_payroll_scraper.py`
- `attribute_*_salaries.py`（3 个）、`import_contracts.py`

**D4. Play-In / 季后赛 / 2026 专项**
- `playin_*.py`（fetch_sample/probe/all4/verify）、`import_playoff_gamelog*.py`
- `ingest_2026_playoffs.py`、`ingest_2026_pbp.py`、`refetch_playin_legacy_br.py`、`fix_playin_2024_mia.py`

**D5. 诊断 / 校验 / 回填辅助（多为一次性/临时脚本，通常不需迁入 v2 常驻架构）**
- `diag_*.py`（1980/abbrev/lookup/unresolved×2）、`check_*.py`（gamelog_cache/games_fields/pbp_*）
- `verify_*.py`、`analyze_data_gaps.py`、`archive_gamelog_cache.py`、`reingest_gamelog_from_cache.py`
- `backfill_*.py`（根）、`game_id_bridge.py`、`matcher.py`、`normalize_team_abbr.py`

---

## E. 回滚契约（铁律）

- **旧版零改动**：`crawler/`、`nba_daily_crawler.py`、根 `*.py` 在本次 v2 工作中未被任何写操作触及（已用 mtime 核验：近 3 天无 `.py` 改动）。
- **v2 物理隔离**：全部 v2 产物位于 `external_crawler/crawler_v2/`，与旧目录平级。
- **回滚动作**：`rm -rf /Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/external_crawler/crawler_v2`
  → 旧代码、已落库数据、`verify_gaps.py` 门禁全部原样保留，零影响。
- 详见 `rollback_manifest.json`（含 `verification` 字段：py_compile OK、12/12 import、pytest 8 passed、旧版未改动）。

---

## F. 下一步建议（按优先级）

1. **(高)** `adapters/br_team_adapter.py` 落位，使 `handoff_watcher` 切源闭环（当前降级跳过）。
2. **(高)** 把 D1 球员级卫星（尤其 shot_chart / shooting）按统一路径接入——这是用户历史投入最多的线，且 home/away 逆转修复已在旧脚本验证。
3. **(中)** `espn_adapter` / `nba_api_adapter` 接真实解析，启动跨源 bridge（坐标/对齐）落地。
4. **(低)** D5 诊断/校验脚本评估：一次性脚本原则上不迁入，保留旧版；仅把"有复用的 parse 校验"抽进 tests/。
