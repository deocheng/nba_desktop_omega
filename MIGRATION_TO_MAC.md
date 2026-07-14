# NBACore Studio v8 — 迁移到 macOS WorkBuddy 指南

> 生成日期: 2026-07-13 · 由交付总监(齐活林)整理
> 适用: 把当前 Windows 工作区整体迁到 Mac 版 WorkBuddy 继续开发/运行

---

## 1. TL;DR

把 **代码+配置+记忆+文档** 打包成 `nba_desktop_omega_mac_migrate_2026-07-13.zip`，
把 **数据库** 以 CSV 形式放在 `nba_csv/`（已导出，59 表/3.7GB），
另有一份 **仅结构 dump** `nba_schema_only.sql`（含 #105 的 `weight` 列）。
在 Mac 上: 建 venv → 起 Postgres(5433) → 灌结构 → 灌 CSV → 改 `.env` → `./start_mac.sh`。

---

## 2. 迁移包里有什么

| 内容 | 位置 | 说明 |
|------|------|------|
| 后端源码 | `backend/` | FastAPI + 4 层架构引擎 |
| 前端 | `frontend/` | 原生 JS + ECharts，后端 `/app/` 直接托管 |
| 脚本/SQL/测试 | `scripts/` `sql/` `tests/` 顶层 `*.py` | 爬取/回填/解析/测试 |
| 文档 | `docs/` + 顶层 `*.md` | PRD/设计/合同 `NBACore_Execution_Contract_v8.md` |
| 记忆文件 | `.workbuddy/memory/` | **含 MEMORY.md + 每日日志**(Git 不跟踪,迁移必带) |
| 结构 dump | `nba_schema_only.sql` | `pg_dump --schema-only`,59 表 + #105 weight |
| CSV 装载器 | `_import_csv_to_db.py` | Mac 端把 nba_csv 灌库 |
| Mac 启动脚本 | `start_mac.sh` | `start.bat` 等价物 |
| `.env` 模板 | `.env.example` | 填两个路径即可 |
| **仓库外爬虫** | `external_crawler/` | `nba_daily_crawler.py` + `crawler/` 包(见 §6) |

**不在包里**(需另处理): `nba_csv/` 数据目录(太大,见 §5)、`.venv/`(重装)、`.env`(重写)、
`dist/` `build/` `scratch_archive/`(已 gitignore,无需迁移)。

---

## 3. 前置依赖(macOS)

| 组件 | 版本/要求 | 安装 |
|------|----------|------|
| Python | 3.10+ | `brew install python@3.10` |
| PostgreSQL | 17(或 15/16) | `brew install postgresql` 或 Postgres.app |
| Node | 任意(前端为静态资源,可不装) | `brew install node` |
| Chrome | 爬 BR 用 | 普通 Chrome 即可 |
| psycopg2 | **用 `psycopg2-binary`**(见 requirements.txt) | venv 内 `pip install -r requirements.txt` |

> ✅ 好消息: 源码**零 `C:/` 硬编码路径**,全部走相对路径/`os.path`,Mac 直接可用。
> ✅ `psycopg2-binary` 是预编译 wheel,Mac 上**不需要 pg_config / libpq**。

---

## 4. 迁移步骤

### Step 1 — 传包 & 解压
把 `nba_desktop_omega_mac_migrate_2026-07-13.zip` 拷到 Mac,解压到如
`~/projects/nba_desktop_omega/`。再把 `nba_csv/` 整个目录拷到**同一项目根**(与 zip 解压同级)。

### Step 2 — Python venv + 依赖
```bash
cd ~/projects/nba_desktop_omega
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```
(约 1 分钟,psycopg2-binary/pandas/numpy/fastapi 等)

### Step 3 — PostgreSQL(关键: 端口是 5433,不是 5432)
```bash
brew install postgresql
brew services start postgresql         # 或 Postgres.app 图形启动
# 建用户/库 (项目硬编码: user=postgres password=postgres db=nba port=5433)
psql postgres -c "ALTER USER postgres WITH PASSWORD 'postgres';"
createdb -O postgres nba
# 改端口: 编辑 postgresql.conf 设 port = 5433, 重启
```
> ⚠️ 项目**全部代码用 5433**,用默认 5432 会连不上。务必改端口或改 `backend/core/config.py`。

### Step 4 — 灌表结构
```bash
psql -U postgres -d nba -f nba_schema_only.sql
```
确认 59 张表建好,且 `fact_player_season_stats` 等含 `weight` 列(#105 已落)。

### Step 5 — 灌数据(CSV)
```bash
.venv/bin/python _import_csv_to_db.py --csv-dir nba_csv
```
大表 `play_by_play`(1837 万行)约几分钟。完成后校验:
```bash
psql -U postgres -d nba -c "SELECT count(*) FROM play_by_play;"   -- 应 ≈ 18,370,598
```

> 💡 **备选(更保真)**: 若想连索引/约束/序列一起迁,Windows 端可改做
> `pg_dump -Fc -f nba_full.dump nba` 然后 Mac 端 `pg_restore -d nba nba_full.dump`。
> CSV 方案胜在可读、可增量;pg_dump 胜在结构完整。二选一即可。

### Step 6 — 写 `.env`(只改两个路径)
```bash
cp .env.example .env
# 编辑 .env:
#   NBA_PYTHON=/Users/you/projects/nba_desktop_omega/.venv/bin/python
#   CRAWLER_SCRIPT=/Users/you/projects/nba_desktop_omega/external_crawler/nba_daily_crawler.py
```
> DB 连接(host/port/db/user/pass)在 `backend/core/config.py` 硬编码,与 Windows 一致则**无需改**。

### Step 7 — 启动
```bash
chmod +x start_mac.sh
./start_mac.sh
```
打开 http://127.0.0.1:5577/app/ 。API 文档 http://127.0.0.1:5577/docs

---

## 5. 数据载体说明(nba_csv/)

CSV 由 Windows 端 `_export_tables_to_csv.py` 用 `COPY ... TO STDOUT` 导出,59 表全 OK。
体积(供评估传输方式):

| 表 | 大小 |
|----|------|
| play_by_play | 3436 MB |
| player_gamelog | 313 MB |
| player_season_splits | 144 MB |
| dim_games / fact_player_season_stats / player_* | 数 MB~18 MB 不等 |
| 其余小表 | < 1 MB |

**传输建议**: 3.7GB 用 U 盘/移动硬盘/rsync 比压缩再传更快。若坚持走压缩包,
另存了 `nba_csv_2026-07-13.zip`(后台生成)。注意 CSV 是文本,压缩比高但耗时。

---

## 6. ⚠️ 仓库外的爬虫依赖(易漏)

`nba_daily_crawler.py` 与 `crawler/` 工具箱**不在项目目录内**,原位于 Windows 的
`nba_data/`(项目上一级)。已随包复制到 `external_crawler/`。

- **`nba_daily_crawler.py`(必需)**: 被 `.env` 的 `CRAWLER_SCRIPT` 指向,后端 `/crawler/*`
  路由以子进程方式调用它。其抓取逻辑 `TableCrawler` 是**文件内联定义**的,自身可独立运行。
- **`crawler/` 工具箱(可选)**: 一堆**独立爬虫脚本**(bbref_scraper / nba_api_client /
  scrape_player_weight / 等),不被 daily crawler 也不被 backend `import`,是单独的采集工具集。
  复制进来备查,不强制与 daily crawler 同级;要单独跑某脚本时 `cd external_crawler/crawler && python xxx.py` 即可。

迁移到 Mac 后:
- `.env` 的 `CRAWLER_SCRIPT` 指向 Mac 上 `external_crawler/nba_daily_crawler.py` 的绝对路径
- 首次跑爬取前,Chrome 需可被执行;BR Cloudflare cookie 会重新生成(`.br_cf_cookies.pkl` 运行时产生,无需迁移)
- 注意: `nba_daily_crawler.py` 内有 `import winreg`(Windows 注册表, line 116)和
  `undetected_chromedriver`(Mac 需 `pip install undetected-chromedriver`)。winreg 在 try 块里,
  非 Windows 会被跳过,不影响主流程;若 Mac 上爬 BR 报错,检查 chromedriver 与 Chrome 版本匹配。

---

## 7. 架构速记(给接手的人)

4 层严格隔离(§6 红线):
```
前端(零业务计算) → API(仅编排) → 指标引擎(计算) → 数据层(SELECT-only, 参数化 SQL)
```
- DB: PostgreSQL,端口 **5433**,库 `nba`
- Server: FastAPI,入口 `main.py`,`backend.app:create_app`(factory)
- 默认技术栈: Vite + React + MUI + Tailwind(前端实际为原生 JS + ECharts,后端托管)
- 禁止: eval/exec · 动态 SQL · 逐球员 DB 循环 · 前端计算 · 跨层泄漏 · 引擎核心 mock

---

## 8. 当前数据状态 & 已知问题(迁移后同样适用)

- 2026 RS = 1560 场,球队对覆盖 870/870 = 100%
- PBP = 1837 万行(BBRef/br_crawler/nba_api 三源);BBRef 2026 的 playerid 已回填 14.2 万行(#114)
- #105: 12 张表已加 `weight` 列(本 dump 已含)
- **遗留**: #114 仍有 2 名重名球员(J.Butler/J.Jackson)playerid 为 NULL(预期,非缺陷)
- **挂起**: tAcntr(904 条 Traded 语义 LLM 预解析)依赖 Ollama,Windows 端 Ollama 离线未跑完;Mac 起 Ollama 后可补
- `scratch_archive/` 是清理时挪出的诊断脚本(未删,可恢复),按需处理

---

## 9. 迁移后自检清单

- [ ] `psql -p 5433 -d nba -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"` → 59
- [ ] `play_by_play` 行数 ≈ 18,370,598
- [ ] `.env` 两个路径指向 Mac 实际位置
- [ ] `./start_mac.sh` 起服务,`/docs` 可访问
- [ ] 跑一次 `pytest backend/services/clutch_engine/tests/ -q` 确认无回归
- [ ] `external_crawler/` 下 `nba_daily_crawler.py` 与 `crawler/` 同级
