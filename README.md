# NBACore Studio v8 — NBA 数据平台

篮球参考（Basketball-Reference / ESPN）双源爬虫 + 跨源 game_id 桥接 + 逐回合（PBP）数据平台，配套 FastAPI 分析后端与前端。

## 项目简介

- **双源爬虫**：Basketball-Reference（BR）逐回合 PBP 爬取 + ESPN 宽数据集（盒式/坐标）回补，无值守常驻。
- **跨源桥接**：BR / ESPN / nba_api 三套 game id 不一致，用 `(比赛日期, 主客队缩写, 比分)` 锚点对齐，生成 `game_id_map`，让下游按 BR gid 也能查到 ESPN / nba_api 数据。
- **PBP 动画还原**：`backend/services/tactics_engine` 基于 play_by_play 还原比赛动画（BR 无坐标时语义重建并标记 `pos_source='reconstructed'`，不冒充真实坐标）。
- **盯梢**：配套 WorkBuddy skill `nba-crawler-watch` 做双爬虫健康巡检（进程 / 归档增长 / 库进度 / 停滞判定）。

## 技术栈

- 后端：FastAPI + Uvicorn（入口 `backend.app:create_app --factory`，默认端口 `5577`）
- 数据库：PostgreSQL（默认 `5433` 端口，`dbname=nba`，`user=postgres`，口令走 `.env` 的 `DB_PASSWORD`）
- 运行时：Python 3.10+，虚拟环境 `.venv`
- 关键依赖：fastapi / uvicorn / psycopg2-binary / pydantic / pandas / numpy / httpx / curl_cffi（爬虫 TLS 指纹伪装，绕 Akamai / Cloudflare 限流）

## 目录结构

```
.
├── backend/                     # FastAPI 应用（api / services / core / data_layer）
├── common/                     # 桥接公共模块（bridge_constants 等）
├── db/                         # 建表 / 视图 SQL
│   ├── game_id_map.sql          # BR ↔ nba_api ↔ ESPN 三源 game id 映射
│   ├── espn_boxscore.sql       # ESPN 盒式（JSONB）
│   └── v_pbp_br_resolved.sql  # 只读视图：按 BR gid 解析桥接 PBP
├── br_crawler.py               # BR 综合爬虫（pbp / gamelog / espn_broad 向前增量）
├── espn_broad_crawler.py      # ESPN 宽爬（summary → 盒式 + 坐标 → 落盘 JSON）
├── game_id_bridge.py           # 桥接对账（幂等）
├── raw_archiver.py             # 原始数据原子落盘（sha256 去重）
├── matcher.py / verify_archive.py
├── run_br_crawler.sh           # BR 无值守编排（6h 一轮）
├── run_espn_full.sh            # ESPN 宽爬 + 坐标回填编排
├── start_mac.sh / start.sh / start.bat   # 一键启动后端
├── requirements.txt
└── .env.example               # 配置样例（真实 .env 不入库）
```

> 注：`raw_archive/`（BR HTML / ESPN JSON 原始落盘，约 1.8G）、`pbp_raw/`、`node_modules/`、`.env`、`*.log`、`*.csv` 等均已在 `.gitignore` 中排除，不入版本库。

## 环境准备

```bash
cd <项目根>
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 复制配置样例并填入数据库口令
cp .env.example .env
# 编辑 .env，至少设置：
#   DB_PASSWORD=<你的 PostgreSQL 口令>
#   （pg_hba 全 scram-sha-256，host 连接口令必填，无 trust 兜底）
```

## 数据库

- 需本地运行 PostgreSQL，监听 `5433`，建库 `nba`，所有者 `postgres`。
- 初始化表 / 视图：

```bash
psql -h localhost -p 5433 -U postgres -d nba -f db/game_id_map.sql
psql -h localhost -p 5433 -U postgres -d nba -f db/espn_boxscore.sql
psql -h localhost -p 5433 -U postgres -d nba -f db/v_pbp_br_resolved.sql
```

## 快速开始

**启动后端（macOS）**

```bash
./start_mac.sh
# 或手动：
.venv/bin/python -m uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 5577
```

- 前端页面：`http://127.0.0.1:5577/app/`
- API 文档：`http://127.0.0.1:5577/docs`

**跑双爬虫（无值守）**

```bash
# 脚本会自动探活并拉起本地 PostgreSQL 5433
nohup bash run_br_crawler.sh > br_crawler.out 2>&1 &    # BR，6h 一轮
nohup bash run_espn_full.sh > espn_full.out 2>&1 &     # ESPN 宽爬 + 坐标回填
```

- 桥接对账 `game_id_bridge.py` 每轮先跑，补全键空间；已覆盖的场自动跳过。
- 限速：BR ≤ 15 请求 / 分钟（4.5s 间隔）；ESPN 自带重试。

## 数据桥接说明

三源 game id 体系不同（BR `202510210LAL` / nba_api `22500866` / ESPN event id）。`game_id_bridge.py` 用比赛锚点对齐后写入 `game_id_map`（UNIQUE(br_gid)，无坐标列）。下游可通过 `v_pbp_br_resolved` 视图（只读）按 BR gid 查到桥接的 PBP，零侵入暴露历史数据。

**铁律**：BR 抓取永不加 `--force`；绝不碰 `play_by_play` 的 (x, y)；`game_id_map` 不含坐标；归档「存在且非空则跳过」。

## 盯梢（可选）

WorkBuddy 用户可装 `nba-crawler-watch` skill（位于 `~/.workbuddy/skills/nba-crawler-watch/`）做双爬虫健康巡检，输出进程存活 / 归档增长 / 库进度 / 停滞判定。本项目脚本 `run_*` 已自带 PG 探活与归档校验钩子。

## 测试

```bash
.venv/bin/python -m pytest tests/ -q
```

## 备注

- 本仓库为源码与文档，不含原始爬取数据（见上方 `.gitignore` 说明）。
- 前端为 Vite 构建产物，由 FastAPI 通过 `StaticFiles` 提供。
- 许可证：见仓库（如未单独声明，默认私有 / 自用）。
