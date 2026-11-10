# BR Crawler v2 — 重构版

> 新版 BR 爬虫。旧版 `external_crawler/crawler/`（含 `crawl_br_gamelog.py` / `br_fill_pbp.py` /
> `crawler_watchdog*.sh` / `nba_daily_crawler.py`）**零改动保留**。`crawler_v2/` 是新增同级目录，
> 全部成果隔离于此，**回滚 = 删除本目录**，绝不影响旧代码与已落库数据。

---

## 1. 为什么要做 v2（结合 MediaCrawler 借鉴）

评估过 GitHub `NanmiCoder/MediaCrawler` 的真实代码结构后，结论是：它的强在"抽象层干净 + 测试文化"，
而我们的强在"无人值守生产级健壮性"（DB 行数判卡死、CF 墙自动 PAUSE、§6 写库纪律、CDP 无头 stealth）。
两者是平级对话者，不是学徒关系。

v2 只借鉴它**真正比我们好、且杠杆最高**的部分，且严格守我们的栈纪律（stdlib 优先、psycopg2 §6 参数化、
无 python-dotenv、无 uv/playwright 重依赖）：

| MediaCrawler 借鉴点 | v2 落地 | 我们的铁律保护 |
|---|---|---|
| Parser/Extractor fixture 单测（录原始页→跑解析→断言） | `tests/test_br_*_parser.py` + `tests/fixtures/` | 直接覆盖 1999 hard-kill / CF 挂死类 bug，贴合严过关 pytest 体制 |
| `cache/abs_cache` + 工厂 + TTL | `core/cache.py` | 把 gamelog 缓存"修正缓冲→晋升 DB"建模成显式契约 |
| `proxy/base_proxy` 可插拔 Provider | `core/proxy.py` | cf_clearance 建模成带 TTL 的 Provider，过期自动换 |
| `store/*_store_impl` 分源存储 | `core/store.py` | DB 权威 sink 与 raw dump 分离，统一进 store 层 |
| `base/base_crawler` 模板方法 | `core/base_crawler.py` | fetch→parse→normalize→store，加 §6 写库门禁 |
| `tenacity` 请求级重试 | `core/retry.py`（stdlib 自研，免新增依赖） | — |

**不借的**：`.env` + dotenv（我们刻意不用）、`uv` + playwright/opencv/mongodb 重依赖（footprint 太大）、
广度铺 7 平台（我们只打 BR/NBA 深度）。

---

## 2. 目录结构

```
crawler_v2/
├── rollback_manifest.json      # 回滚契约：删本目录即回滚，旧版零影响
├── core/                       # 抽象层（借鉴 MediaCrawler base/store/cache/proxy）
│   ├── config.py               # DB 配置 / CDP URL / 出站点代理清除（复用旧约定）
│   ├── retry.py                # 请求级重试装饰器（stdlib，免 tenacity）
│   ├── cache.py                # AbsCache + LocalCache(TTL+持久化) + CacheFactory
│   ├── proxy.py                # ProxyProvider / StaticProxyProvider / CfClearanceProvider(TTL)
│   ├── store.py                # Store 抽象 + PGStore(§6 参数化) + CsvJsonDump + StoreFactory
│   └── base_crawler.py         # BaseCrawler 模板方法 + RateLimiter + SessionGone
├── adapters/                   # 数据源适配器（均子类化 BaseCrawler）
│   ├── br_pbp_adapter.py       # PBP 逐回合（复用 br_pbp_parse.parse_pbp + raw_archiver）
│   ├── br_gamelog_adapter.py   # 球员 gamelog（复用 crawl_br_gamelog 既有 parse/DB 函数）
│   ├── espn_adapter.py         # 接口脚手架（SCAFFOLD，待接入真实解析）
│   └── nba_api_adapter.py      # 接口脚手架（SCAFFOLD，待接入真实解析）
├── daemon/                     # 运维守护层（用 Python 重写旧 sh + nba_daily_crawler）
│   ├── watchdog.py             # 看门狗：DB 行数判卡死 / CF墙MAX_STALL→PAUSED / 单例锁 / status·stop
│   └── runner.py               # 编排器：赛季倒序 / STATE-BYPASSED-FAILURES / verify_gaps 门禁 / handoff
└── tests/                      # parser fixture 回归测试（离线、真页面）
    ├── fixtures/               # 真实归档 HTML 只读拷贝（3 PBP + 2 gamelog）
    ├── test_br_pbp_parser.py   # 5 passed
    └── test_br_gamelog_parser.py # 3 passed
```

---

## 3. 设计要点

### 3.1 复用而非重写（"严禁凭空猜"铁律）
- `br_gamelog_adapter.py` 单向 `import crawl_br_gamelog as leg`，复用其已验证函数：
  `parse_gamelog_html` / `build_insert` / `_fetch_html` / `canon_team` / `get_game_id_map` /
  `get_game_id_full_map` / `load_player_id_bridge` / `get_players` / `BRServerError` /
  `save/load/has_gamelog_html`。**解析与写库逻辑一字未重造**，只把"编排"搬进 v2 抽象层。

### 3.2 写库严守 §6
- 所有落库经 `PGStore.save(table, columns, key_columns, rows)`：仅 `psycopg2.sql.Identifier` +
  `%s` 参数化，表/列名走白名单；幂等 = 先 DELETE(key) 再 INSERT；写后由调用方计数校验。

### 3.3 数据四性：禁止静默丢弃
- `br_gamelog_adapter.normalize()` 对缺 `nba_api_id` 映射的比赛**计入 `_dropped_total` 并显式打印**，
  绝不静默跳过（直接灭掉"假完整"隐患）。

### 3.4 卡死 / CF 墙（v2 比旧脚本更稳）
- `watchdog.is_stalled()` 用 **DB 行数**判卡死（CF 墙时爬虫狂写 ERR 但行数不动，mtime 法漏判）。
- **v2 修复点**：DB 查询失败（"ERR"）与"行数不变"区分开，DB 抖动不会被累计成 CF 墙误杀。
- 连续 `MAX_STALL=3` 次卡死 → 写 PAUSED 退出，不空转烧 IP。

### 3.5 回滚即删目录
- 见 `rollback_manifest.json`。v2 与旧版物理隔离，删 `crawler_v2/` 即完全回滚。

---

## 4. 运行方式

### 4.1 单季 gamelog 回填（调旧 verify_gaps 作权威门禁）
```bash
cd external_crawler/crawler_v2
/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/.venv/bin/python \
  -m adapters.br_gamelog_adapter --season 2026 --cache-dir ../gamelog_cache
# 仅测试不写库：
/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/.venv/bin/python \
  -m adapters.br_gamelog_adapter --season 2026 --dry-run
```

### 4.2 PBP 逐回合
```bash
/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/.venv/bin/python \
  -m adapters.br_pbp_adapter --season 2026
```

### 4.3 完整编排（替代 recrawl_2004_2026_autofill.sh）
```bash
# 先确保 CDP Chrome(9223) 存活：bash launch_chrome_cdp.sh
/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/.venv/bin/python \
  -m daemon.runner --seasons-override 2026 2025   # 定向某几季
# 全量（2026→1980）：省略 --seasons-override
```

### 4.4 守护看门狗（替代 crawler_watchdog_v2.sh）
```bash
# 常驻（建议用 WorkBuddy Bash run_in_background 启动，避免被回收）
/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/.venv/bin/python \
  -m daemon.watchdog
# 状态 / 停止：
/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/.venv/bin/python -m daemon.watchdog status
/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/.venv/bin/python -m daemon.watchdog stop
```

### 4.5 回归测试
```bash
cd external_crawler/crawler_v2
/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/.venv/bin/python -m pytest tests/ -q
# 当前：test_br_pbp_parser 5 passed，test_br_gamelog_parser 3 passed
```

---

## 5. 已知范围与下一步

- **已忠实重构**：gamelog 适配器、PBP 适配器、watchdog、runner —— 均复用旧 parse/DB 函数，未重造。
- **脚手架（SCAFFOLD，未接真实解析）**：`espn_adapter.py` / `nba_api_adapter.py` 仅定义统一接口契约，
  待把既有跨源 bridge（坐标/对齐）逻辑接入后启用。
- **`br_team_adapter` 待补**：`runner.handoff_watcher` 切到的"球队数据"源尚未提供 adapter，
  当前缺失时降级跳过（不致命、不空转）。
- **`launch_chrome_cdp.sh` 沿用旧版**：watchdog 重启 CDP Chrome 仍 shell out 调用根目录旧脚本，未重写。

详见 `family_migration.md`（旧 50+ 文件 → v2 模块映射与迁移状态）。
