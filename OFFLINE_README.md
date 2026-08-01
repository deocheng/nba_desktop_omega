# 离线安装包使用说明（nba_stat_crawler · offline）

本包为**离线整包**：已内置 `.venv/`（含 psycopg2-binary / fastapi / uvicorn / pytest 等全部运行时与测试依赖），**无需联网 `pip install`**。仅限 **macOS 同架构** 机器解包使用（venv 含编译型原生扩展，跨系统/跨架构不可用）。

## 三步跑起来

1. **填数据库口令**（占位 → 真实）
   ```bash
   cp .env.example .env
   # 编辑 .env，把 DB_PASSWORD 改成你的强口令
   ```
   > 后端 `backend/core/config.py` 与桥接 `common/bridge_constants.py` 均从 `DB_PASSWORD` 读口令，禁止硬编码。

2. **准备 PostgreSQL**
   - 确保本机 Postgres 在 `5433` 端口、存在 `nba` 库（默认库名/用户见 `.env.example`）。
   - 执行建表 SQL：`db/*.sql`（按文件内顺序）。

3. **用包内 venv 启动**（不要新建 venv）
   ```bash
   .venv/bin/python -m uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 5577
   ```
   - 前端是纯静态 SPA：用任意静态服务器 serve `frontend/`，并把 `/tactics`、`/clutch-replay`、`/video-library`、`/draft`、`/players` 等 API 反向代理到 `5577` 即可（同机可用一个简单的同源代理脚本）。

## 本包不包含（按需另行同步）
- 真实 `.env`（已用 `.env.example` 占位，口令请自行填，绝不随包分发）
- 爬虫原始落盘 `raw_archive/`、`pbp_raw/`（数据量大，不进包）
- `.git` 版本历史

## 目录速览
| 目录 | 内容 |
|------|------|
| `backend/` | FastAPI 后端服务（战术板/动态回放/视频库/选秀/球星情报等） |
| `frontend/` | 纯静态 SPA（HTML + JS + CSS，ECharts 走 CDN） |
| `common/` | 公共库（桥接/归档/匹配常量等） |
| `db/` | 建表与视图 SQL |
| `crawler/` | BR / ESPN 双爬虫 |
| `tests/` | 测试套件（含根 `tests/` 与 `backend/services/*/tests/`） |
| `requirements.txt` | 依赖清单（venv 已装好，离线无需再装） |

> 验证：后端起好后 `curl -s 127.0.0.1:5577/tactics/games?season=2025` 应返回 200。
