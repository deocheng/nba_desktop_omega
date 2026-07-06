"""Generate complete PROJECT_FULL_DOCUMENTATION.md with all source files."""
from pathlib import Path

ROOT = Path(__file__).parent
OUTPUT = ROOT / "docs" / "PROJECT_FULL_DOCUMENTATION.md"

def read_file(rel_path: str) -> str:
    """Read a file relative to project root."""
    p = ROOT / rel_path
    if not p.exists():
        return f"[FILE NOT FOUND: {rel_path}]"
    return p.read_text(encoding="utf-8")

def code_block(rel_path: str, lang: str) -> str:
    """Format a file as a markdown code block with path heading."""
    content = read_file(rel_path)
    return f"#### {rel_path}\n\n```{lang}\n{content}\n```\n\n"

def main():
    sections = []

    # ── Header & Overview ──
    sections.append(r"""# NBACore Studio v8 — 完整项目文档

> 版本: 8.0.0 | 更新日期: 2026-07-06
> 架构: 四层严格隔离 (Data Layer → Metric Engine → API Layer → Frontend)

---

## 1. 项目概述

### 1.1 项目简介

NBACore Studio v8 是一个**指标驱动的批量分析引擎**，专为 NBA 球员数据设计。系统采用严格的四层架构，确保各层职责单一、无跨层逻辑泄漏，所有计算均由 Metric Engine 统一完成。

### 1.2 四层架构

```
┌──────────────────────────────────────────────────────────┐
│  Layer 4: Frontend (纯渲染)                              │
│  - HTML/CSS/JavaScript + ECharts                        │
│  - 仅调用 API，无业务逻辑、无计算                        │
├──────────────────────────────────────────────────────────┤
│  Layer 3: API Layer (纯编排)                            │
│  - FastAPI routers + Pydantic schemas                   │
│  - 仅做请求整形 + 调用 Metric Engine                     │
│  - 无 SQL、无 pandas、无计算逻辑                         │
├──────────────────────────────────────────────────────────┤
│  Layer 2: Metric Engine (唯一计算层)                    │
│  - 向量化 pandas 计算                                    │
│  - 指标注册表 + 缓存 + 排名引擎                          │
│  - 所有指标计算在此完成                                  │
├──────────────────────────────────────────────────────────┤
│  Layer 1: Data Layer (只读数据访问)                     │
│  - 仅 SELECT，批量查询 (IN / 临时表)                    │
│  - Schema 注册 + 漂移检测                                │
│  - 唯一的数据库入口点                                    │
└──────────────────────────────────────────────────────────┘
```

### 1.3 核心特性

| 特性 | 说明 |
|------|------|
| **严格分层** | 四层架构，无跨层逻辑泄漏 |
| **向量化计算** | 所有指标使用 pandas 向量化操作，无 Python 循环 |
| **确定性输出** | 相同输入 = 相同输出，SHA256 缓存键 |
| **批量加载** | IN 子句或临时表，无 per-player 数据库循环 |
| **运行时自检** | startup 时自动检查架构合规性 |
| **磁盘缓存** | 24 小时 TTL，diskcache 持久化 |
| **可导出** | JSON/CSV 格式导出排名、VS、球员数据 |
| **上下文分析** | 相似球员、角色演变、趋势分析 |

---

## 2. 快速开始

### 2.1 环境要求

- Python 3.10+
- PostgreSQL 16 (数据库名: `nba`, 端口: `5433`)
- Windows / Linux / macOS

### 2.2 安装与运行

```bash
# 克隆项目
cd nba_desktop_omega

# 安装依赖
pip install -r requirements.txt

# 配置环境变量 (可选)
cp .env.example .env
# 编辑 .env 修改数据库连接参数

# 启动开发服务器
# Windows:
.\start.ps1 dev
# 或直接:
python main.py
```

服务启动后访问:
- 应用界面: http://127.0.0.1:5577/app/
- API 文档: http://127.0.0.1:5577/docs
- 健康检查: http://127.0.0.1:5577/health

### 2.3 Docker 部署

```bash
# 一键启动 (PostgreSQL + 应用)
docker compose up -d

# 查看日志
docker compose logs -f app

# 停止
docker compose down
```

### 2.4 打包 EXE (Windows)

```powershell
# 构建 EXE
.\build.ps1

# 清理并重新构建
.\build.ps1 -Clean
```

输出: `dist\NBACore.exe` (单文件，约 55MB)

### 2.5 运行测试

```bash
# 运行所有测试
pytest tests/ -v

# 仅运行 Phase 0 测试
pytest tests/test_phase0_health.py -v

# 仅运行 Phase 3 API 测试
pytest tests/test_phase3_api_layer.py -v
```

---

## 3. 项目结构

```
nba_desktop_omega/
├── backend/                          # 后端核心
│   ├── app.py                        # FastAPI 应用工厂
│   ├── core/                         # 核心基础设施
│   │   ├── config.py                 # 配置管理
│   │   ├── db.py                     # 数据库连接池 + SQL 校验
│   │   ├── logging.py                # 结构化日志
│   │   └── runtime_guard.py          # 启动时架构自检
│   ├── api/                          # Layer 3: API 层
│   │   ├── schemas.py                # Pydantic 数据模型
│   │   └── routers/                  # FastAPI 路由
│   │       ├── metrics.py            # /metrics 端点
│   │       ├── players.py            # /players 端点
│   │       ├── vs.py                 # /vs/compare 端点
│   │       ├── batch.py              # /batch 端点
│   │       ├── context.py            # /context 端点
│   │       ├── export.py             # /export 端点
│   │       └── monitor.py            # /monitor 端点
│   ├── data_layer/                   # Layer 1: 数据层
│   │   ├── schema.py                 # 表 Schema 注册表
│   │   ├── batch_loader.py           # 批量数据加载 (IN 子句)
│   │   ├── temp_loader.py            # 临时表加载 (大批次)
│   │   ├── joins.py                  # 表连接逻辑
│   │   └── schema_validator.py       # Schema 漂移检测
│   └── services/                     # Layer 2: 服务层
│       ├── metric_engine/            # Metric Engine (唯一计算层)
│       │   ├── registry.py           # 指标注册表
│       │   ├── executor.py           # 向量化执行器
│       │   ├── matrix_builder.py     # 矩阵构建器
│       │   ├── rank.py               # 排名引擎
│       │   ├── cache.py              # 磁盘缓存
│       │   ├── batch_loader.py       # 数据加载包装
│       │   └── metrics/              # 内置指标定义
│       │       ├── basic.py          # 基础指标 (PPG, RPG, etc.)
│       │       ├── advanced.py       # 高级指标 (TS%, eFG%, USG%)
│       │       └── composite.py      # 复合指标 (Fantasy, Efficiency)
│       ├── context_engine/           # Context Engine
│       │   ├── similar_players.py    # 相似球员 (余弦相似度)
│       │   ├── role_evolution.py     # 角色演变分析
│       │   └── trend_analysis.py     # 趋势分析 (线性回归)
│       └── export_service.py         # 导出服务 (JSON/CSV)
├── frontend/                         # Layer 4: 前端 (纯渲染)
│   ├── index.html                    # HTML 结构
│   ├── css/style.css                 # 样式
│   └── js/app.js                     # 前端逻辑 + ECharts
├── tests/                            # 测试套件
│   ├── conftest.py                   # Pytest fixtures
│   ├── test_phase0_health.py         # Phase 0: 健康检查 + 配置
│   └── test_phase3_api_layer.py      # Phase 3: API 层测试
├── NBAlogo/                          # 球队 Logo 素材
├── scripts/                          # 脚本工具
│   └── benchmark.py                  # 性能基准测试
├── docs/                             # 文档
│   └── PROJECT_FULL_DOCUMENTATION.md # 本文档
├── .github/workflows/                # CI/CD
│   └── ci.yml                        # GitHub Actions
├── main.py                           # EXE 入口点
├── Dockerfile                        # Docker 镜像构建
├── docker-compose.yml                # Docker Compose 编排
├── nbacore.spec                      # PyInstaller 配置
├── build.ps1                         # Windows 构建脚本
├── requirements.txt                  # 生产依赖 (固定版本)
├── pyproject.toml                    # 项目配置
├── .env.example                      # 环境变量示例
├── start.ps1                         # Windows 启动脚本
└── start.sh                          # Linux/Mac 启动脚本
```

---

## 4. 完整源代码

### 4.1 后端核心

""")

    # Backend core files
    sections.append(code_block("main.py", "python"))
    sections.append(code_block("backend/app.py", "python"))
    sections.append(code_block("backend/core/config.py", "python"))
    sections.append(code_block("backend/core/db.py", "python"))
    sections.append(code_block("backend/core/logging.py", "python"))
    sections.append(code_block("backend/core/runtime_guard.py", "python"))

    sections.append("### 4.2 API 层\n\n")
    sections.append(code_block("backend/api/schemas.py", "python"))
    sections.append(code_block("backend/api/routers/__init__.py", "python"))
    sections.append(code_block("backend/api/routers/metrics.py", "python"))
    sections.append(code_block("backend/api/routers/players.py", "python"))
    sections.append(code_block("backend/api/routers/vs.py", "python"))
    sections.append(code_block("backend/api/routers/batch.py", "python"))
    sections.append(code_block("backend/api/routers/context.py", "python"))
    sections.append(code_block("backend/api/routers/export.py", "python"))
    sections.append(code_block("backend/api/routers/monitor.py", "python"))

    sections.append("### 4.3 数据层\n\n")
    sections.append(code_block("backend/data_layer/__init__.py", "python"))
    sections.append(code_block("backend/data_layer/schema.py", "python"))
    sections.append(code_block("backend/data_layer/batch_loader.py", "python"))
    sections.append(code_block("backend/data_layer/temp_loader.py", "python"))
    sections.append(code_block("backend/data_layer/joins.py", "python"))
    sections.append(code_block("backend/data_layer/schema_validator.py", "python"))

    sections.append("### 4.4 服务层 — Metric Engine\n\n")
    sections.append(code_block("backend/services/metric_engine/__init__.py", "python"))
    sections.append(code_block("backend/services/metric_engine/registry.py", "python"))
    sections.append(code_block("backend/services/metric_engine/executor.py", "python"))
    sections.append(code_block("backend/services/metric_engine/matrix_builder.py", "python"))
    sections.append(code_block("backend/services/metric_engine/rank.py", "python"))
    sections.append(code_block("backend/services/metric_engine/cache.py", "python"))
    sections.append(code_block("backend/services/metric_engine/batch_loader.py", "python"))
    sections.append(code_block("backend/services/metric_engine/metrics/__init__.py", "python"))
    sections.append(code_block("backend/services/metric_engine/metrics/basic.py", "python"))
    sections.append(code_block("backend/services/metric_engine/metrics/advanced.py", "python"))
    sections.append(code_block("backend/services/metric_engine/metrics/composite.py", "python"))

    sections.append("### 4.5 服务层 — Context Engine\n\n")
    sections.append(code_block("backend/services/context_engine/__init__.py", "python"))
    sections.append(code_block("backend/services/context_engine/similar_players.py", "python"))
    sections.append(code_block("backend/services/context_engine/role_evolution.py", "python"))
    sections.append(code_block("backend/services/context_engine/trend_analysis.py", "python"))

    sections.append("### 4.6 服务层 — 导出服务\n\n")
    sections.append(code_block("backend/services/export_service.py", "python"))

    sections.append("### 4.7 前端\n\n")
    sections.append(code_block("frontend/index.html", "html"))
    sections.append(code_block("frontend/css/style.css", "css"))
    sections.append(code_block("frontend/js/app.js", "javascript"))

    sections.append("### 4.8 部署与构建\n\n")
    sections.append(code_block("Dockerfile", "dockerfile"))
    sections.append(code_block("docker-compose.yml", "yaml"))
    sections.append(code_block("nbacore.spec", "python"))
    sections.append(code_block("build.ps1", "powershell"))
    sections.append(code_block("requirements.txt", "text"))
    sections.append(code_block(".env.example", "text"))
    sections.append(code_block("pyproject.toml", "toml"))
    sections.append(code_block(".github/workflows/ci.yml", "yaml"))

    sections.append("### 4.9 测试\n\n")
    sections.append(code_block("tests/conftest.py", "python"))
    sections.append(code_block("tests/test_phase0_health.py", "python"))
    sections.append(code_block("tests/test_phase3_api_layer.py", "python"))

    # ── API Documentation ──
    sections.append(r"""---

## 5. API 接口说明

### 5.1 健康检查

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 + 运行时守卫状态 |
| GET | `/` | 项目信息 + 当前阶段 |

**GET /health 响应示例:**
```json
{
  "status": "ok",
  "version": "8.0.0",
  "database_connected": true,
  "runtime_guard": {
    "config_loaded": { "ok": true },
    "metric_engine_exists": { "ok": true },
    "no_forbidden_patterns": { "ok": true }
  }
}
```

### 5.2 指标 (Metrics)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/metrics` | 列出所有已注册指标 |
| GET | `/metrics/{name}` | 获取单个指标详情 |
| GET | `/metrics/evaluate/{name}` | 计算并排名 |

**GET /metrics 响应:**
```json
{
  "count": 11,
  "metrics": [
    {
      "name": "pts_per_game",
      "kind": "per_game",
      "source_table": "fact_player_season_stats",
      "required_cols": ["pts", "g"],
      "description": "Points per game = sum(pts) / sum(g)",
      "precision": 6
    }
  ]
}
```

**GET /metrics/evaluate/{name} 参数:**
- `season` (int, 必填): 赛季
- `limit` (int, 可选): 返回前 N 名，默认 100
- `ascending` (bool, 可选): 升序排列，默认 false
- `min_value` (float, 可选): 最小值过滤

### 5.3 球员 (Players)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/players` | 按姓名搜索球员 |
| GET | `/players/{id}` | 获取球员详情 + 赛季指标 |
| GET | `/players/seasons` | 获取可用赛季列表 |

**GET /players 参数:**
- `name` (str, 必填, min=2): 搜索关键字
- `limit` (int, 可选, 1-100): 返回数量限制，默认 20

### 5.4 VS 对比

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/vs/compare` | 两名球员多指标对比 |

**参数:**
- `p1` (str, 必填): 球员 1 ID
- `p2` (str, 必填): 球员 2 ID
- `season` (int, 必填): 赛季
- `metrics` (str, 可选): 逗号分隔的指标名列表，默认全部

**响应:**
```json
{
  "player_1": "gilgesh01",
  "player_2": "antetgi01",
  "season": 2025,
  "metrics": {
    "pts_per_game": {
      "gilgesh01": 32.5,
      "antetgi01": 30.4
    }
  }
}
```

### 5.5 批量操作 (Batch)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/batch` | 批量执行多个操作 |

**支持的操作类型:**
- `rank`: 排名计算
- `compute`: 单指标计算
- `compute_many`: 多指标计算

**请求示例:**
```json
{
  "operations": [
    {
      "type": "rank",
      "metric": "pts_per_game",
      "season": 2025,
      "limit": 10
    },
    {
      "type": "compute_many",
      "metrics": ["pts_per_game", "reb_per_game"],
      "season": 2025
    }
  ]
}
```

### 5.6 上下文分析 (Context)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/context/similar` | 相似球员分析 |
| GET | `/context/evolution` | 角色演变分析 |
| GET | `/context/trend` | 趋势分析 |

### 5.7 导出 (Export)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/export/rankings` | 导出排名 (JSON/CSV) |
| GET | `/export/vs` | 导出 VS 对比 (JSON/CSV) |
| GET | `/export/player` | 导出球员数据 (JSON) |
| GET | `/export/league` | 导出全联盟数据 (JSON) |

**参数:**
- `format`: `json` 或 `csv`
- 其他参数与对应 API 一致

### 5.8 监控 (Monitor)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/monitor/cache` | 缓存统计信息 |
| POST | `/monitor/cache/clear` | 清除缓存 |
| GET | `/monitor/schema` | Schema 漂移检测报告 |

---

## 6. 数据库 Schema

### 6.1 已注册表

| 表名 | 类型 | 赛季列 | 球员列 | 说明 |
|------|------|--------|--------|------|
| `fact_player_season_stats` | 事实表 | `season` | `player_id` | 球员赛季总数据 |
| `player_gamelog` | 事实表 | `season` | `br_player_id` | 球员比赛日志 |
| `dim_players` | 维度表 | — | `player_id` | 球员基本信息 |

### 6.2 fact_player_season_stats (球员赛季统计)

核心事实表，存储球员每个赛季的累计数据。Metric Engine 大部分指标基于此表计算。

**主要列:**
- `player_id` (text): BBR 球员 ID (如 'gilgesh01')
- `season` (int): 赛季年份
- `team` (text): 球队缩写
- `age` (int): 年龄
- `g` (int): 出场次数
- `gs` (int): 首发次数
- `mp` (float): 总出场时间
- `fg` (int): 命中数
- `fga` (int): 出手数
- `fg_pct` (float): 命中率
- `x3p` (int): 三分命中
- `x3pa` (int): 三分出手
- `x3p_pct` (float): 三分命中率
- `x2p` (int): 两分命中
- `x2pa` (int): 两分出手
- `x2p_pct` (float): 两分命中率
- `ft` (int): 罚球命中
- `fta` (int): 罚球出手
- `ft_pct` (float): 罚球命中率
- `orb` (int): 进攻篮板
- `drb` (int): 防守篮板
- `trb` (int): 总篮板
- `ast` (int): 助攻
- `stl` (int): 抢断
- `blk` (int): 盖帽
- `tov` (int): 失误
- `pf` (int): 犯规
- `pts` (int): 得分
- `usg_percent` (float): 使用率

### 6.3 dim_players (球员维度表)

球员基本信息表，用于搜索和展示。

**主要列:**
- `player_id` (text): BBR 球员 ID
- `player_name` (text): 球员姓名
- `full_name` (text): 全名
- `position` (text): 位置
- `height_cm` (int): 身高 (厘米)
- `weight_kg` (float): 体重 (公斤)
- `birth_date` (date): 出生日期
- `team` (text): 当前球队
- `team_abbr` (text): 球队缩写
- `college` (text): 大学
- `country` (text): 国家

### 6.4 player_gamelog (比赛日志)

逐场比赛数据，用于更细粒度的分析。

**主要列:**
- `br_player_id` (text): BBR 球员 ID
- `season` (int): 赛季
- `game_date` (date): 比赛日期
- `team` (text): 球队
- `opponent` (text): 对手
- `home_away` (text): 主客场
- `result` (text): 胜负
- `mp` (float): 出场时间
- `pts` (int): 得分
- `reb` (int): 篮板
- `ast` (int): 助攻
- `stl` (int): 抢断
- `blk` (int): 盖帽
- `tov` (int): 失误
- ... 其他技术统计列

---

> 文档生成时间: 2026-07-06
> 项目: NBACore Studio v8.0.0
""")

    # Write output
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("".join(sections), encoding="utf-8")
    print(f"Documentation written to: {OUTPUT}")
    print(f"Total sections: {len(sections)}")

if __name__ == "__main__":
    main()
