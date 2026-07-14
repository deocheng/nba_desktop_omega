# NBACore Studio v8 — Code Quality Review

**Date**: 2026-07-05  
**Reviewer**: Senior Developer  
**Scope**: Full codebase (Phase 0–10)  
**Overall Grade**: B− (Solid foundation, Phase 10 quality debt accumulating)

---

## Executive Summary

Phase 0–7 的代码质量很高：严格的四层隔离、AST 扫描验证、160 个测试全绿、确定性保证到位。Phase 8–9 的部署和打包也很完整。

**但 Phase 10（v7 feature migration）存在明显质量退化**：6 个新 router + 5 个新 data_layer 模块全部没有测试覆盖、没有 change-log 记录，且引入了若干架构违规和安全隐患。如果不及时清理，技术债会快速积累。

---

## Issue Summary

| Severity | Count | Description |
|----------|-------|-------------|
| P0 — Critical | 3 | 安全漏洞 + 架构违规 |
| P1 — Major | 6 | 合约违规 + 零测试 + 设计缺陷 |
| P2 — Minor | 8 | 代码质量 + 可维护性 |

---

## P0 — Critical Issues

### P0-1: XSS Vulnerability in Frontend

**File**: `frontend/js/app.js` (multiple locations)  
**Severity**: Critical

Frontend 大量使用 `innerHTML` 拼接来自 API 的数据（player names, team names, error messages），没有做 HTML 转义。虽然有一个 `escapeHtml()` 函数，但仅用于 crawler 日志。

**受影响的位置** (不完全列表):
- Line 156: `selectPlayer()` — `${p.full_name || p.player_name}` 直接拼入 HTML
- Line 210: `renderPlayerCard()` — `${name}` 从 bio 数据直接拼入
- Line 247: `renderMetricGrid()` — `${m.name}` 直接拼入
- Line 323-340: `renderVSResults()` — `${mname}` 直接拼入表格
- Line 548: `loadRankings()` — `${e.message}` error message 直接拼入
- Line 617-638: `renderStatRankings()` — `${name}`, `${team}` 等直接拼入
- Line 929-940: `loadTeamsPage()` — `${name}`, `${abbr}` 直接拼入

**Risk**: 如果数据库中 `player_name` 或 `full_name` 字段被注入 `<script>` 标签（例如通过 crawler 数据污染），将导致存储型 XSS。

**Fix**: 所有动态数据在拼入 HTML 前必须经过 `escapeHtml()` 处理。建议统一使用 textContent 或创建一个 `escapeAll()` 工具函数。

---

### P0-2: API Layer Subprocess Execution (Architecture Violation)

**File**: `backend/api/routers/crawler.py`  
**Severity**: Critical

`crawler.py` 在 API 层（Layer 3）使用 `subprocess.Popen` 启动外部进程，包含 threading、queue、进程管理逻辑。这违反了 v8 §2 "API 层是 pure orchestration — 只做请求转发和数据塑形" 的原则。

额外问题:
- Line 152, 240: 使用 `taskkill`（Windows 专有命令），Linux/Docker 环境下会失败
- Line 257-263: SSE stream `generate()` 是 `while True` 无限循环，客户端断开后 generator 可能不终止
- Line 29-33: `_crawl_running`, `_crawl_process` 等全局变量在多线程环境下无锁保护

**Fix**: 将 crawler 控制逻辑下沉到独立的 `backend/services/crawler_service.py`（Layer 2.5），API 层只调用 service 的方法。`taskkill` 替换为 `proc.terminate()` + `proc.kill()`（跨平台）。SSE stream 添加客户端断开检测。

---

### P0-3: Unsanitized Table Name in SQL (Defense-in-Depth Gap)

**File**: `backend/data_layer/system_loader.py`, Line 62  
**Severity**: Critical (defense-in-depth)

```python
cnt_sql = f"SELECT count(*) AS cnt FROM {tname}"
```

`tname` 来自 `information_schema.tables` 查询结果，不是直接用户输入。但这是 f-string SQL 拼接，不符合 v8 §6 "No dynamic SQL" 精神。如果 `information_schema` 被篡改或未来代码变更引入用户输入到这条路径，就会产生 SQL 注入。

**Note**: `get_table_data()` 中的 `table_name` 经过 `_ALLOWED_TABLES` 白名单验证，`sort_col` 经过 columns 列表验证 — 这些是安全的。但 `list_tables()` 中的 `tname` 没有白名单验证。

**Fix**: `list_tables()` 的 `tname` 应验证 against `_ALLOWED_TABLES` 或 `information_schema.tables` 的子集。

---

## P1 — Major Issues

### P1-1: Computation in API Layer (v8 §2 Violation)

**File**: `backend/api/routers/charts.py`, Lines 124-148  
**Severity**: Major

`_compute_box_stats()` 函数在 API 层做分位数计算（min/Q1/median/Q3/max），违反 v8 §2 "API 层无计算"原则。

```python
def _compute_box_stats(values: list[float]) -> dict:
    # ... percentile calculation in API layer
```

**Fix**: 将 box stats 计算下沉到 `data_layer/player_chart_loader.py` 或 `metric_engine`。

---

### P1-2: Python-Side Computation in Data Layer

**File**: `backend/data_layer/charts_loader.py`  
**Severity**: Major

`get_late_clock_team_stats()` 和 `get_late_clock_player_stats()` 从 `play_by_play` 表加载全量赛季事件数据到 Python 内存，然后逐行处理做 possession tracking。这在架构上应该是 Layer 2（Metric Engine）的职责，且对 18M 行的 play_by_play 表有严重性能隐患。

**Performance concern**: 一个赛季的 play_by_play 事件可能有数十万行，全部加载到 Python 做逐行处理会消耗大量内存和 CPU 时间。

**Fix**: 要么将 possession tracking 逻辑用 SQL 窗口函数实现（在数据库层完成），要么将其归入 metric_engine 作为专门的计算服务。

---

### P1-3: Zero Test Coverage for Phase 10

**Severity**: Major

新增的 6 个 router 和 5 个 data_layer 模块**没有任何测试**。现有 160 个测试只覆盖到 Phase 7。这意味着:
- 无层隔离验证（Phase 3 有 AST 扫描验证 API 层无 pandas/SQL/eval）
- 无 SQL 安全验证
- 无端点功能验证
- 无回归保护

**Fix**: 创建 `tests/test_phase10_v7_features.py`，至少包含:
- 每个新 router 的基本端点测试
- 层隔离 AST 扫描（验证新 router 无 pandas/psycopg2/SQL）
- data_layer 的白名单验证测试
- crawler 的安全配置测试（NBA_PYTHON 未设置时返回 503）

---

### P1-4: Phase 10 Not Tracked in Change-Log

**Severity**: Major (v8 §1 violation)

v8 合约 §1 要求所有变更记录在 `docs/change-log.md`。Phase 10 新增了 11 个文件、修改了 `app.py`/`__init__.py`/前端三件套，但 change-log 中没有任何 Phase 10 记录。

**Fix**: 在 change-log.md 中添加 Phase 10 的 BUILD 记录，列出所有 Added/Modified 文件和 Decisions。

---

### P1-5: Misleading API — `totals` Returns `per_game` Data

**File**: `backend/api/routers/leaderboard.py`, Line 62  
**Severity**: Major

```python
if stat_type in ("per_game", "totals"):
    # ... calls get_player_per_game()
```

API 声称支持 `totals` stat_type，但实际返回的是 per_game 数据。用户请求 `/leaderboard/totals` 会得到 per_game 结果，不知道数据是错的。

**Fix**: 要么实现真正的 totals 查询，要么在 `totals` 时返回 400 错误并说明 "not yet available"。

---

### P1-6: `exportVS()` Passes Object Instead of ID

**File**: `frontend/js/app.js`, Line 1614  
**Severity**: Major (functional bug)

```javascript
const url = '/export/vs?p1=' + encodeURIComponent(player1) + ...
```

`player1` 是一个 player bio 对象，`encodeURIComponent(player1)` 会将其转为 `%5Bobject%20Object%5D`，导致 export 请求失败。

**Fix**: 改为 `encodeURIComponent(player1.player_id)`。

---

## P2 — Minor Issues

### P2-1: CORS Configuration Too Permissive

**File**: `backend/app.py`, Line 60  
`allow_origins=["*"]` 允许所有来源。生产环境应限制为已知域名或 `http://127.0.0.1:5577`。

### P2-2: SQL Duplication in team_loader.py

**File**: `backend/data_layer/team_loader.py`, Lines 251-309  
`get_team_radar()` 有三个几乎相同的 SQL 查询（regular/playoffs/fallback），代码重复度高。应抽取为参数化模板。

### P2-3: N+1 Query Pattern in list_tables()

**File**: `backend/data_layer/system_loader.py`, Lines 56-70  
对每个表执行单独的 `SELECT count(*)`。对于 38+ 个表（含 play_by_play 18M 行），这会很慢。可考虑使用 `pg_class.reltuples` 估算或批量查询。

### P2-4: Duplicate Endpoints Between charts.py and teams.py

`charts.py` 和 `teams.py` 都有 team-radar、team-standings、team-ratios 等功能相似的端点，只是路径前缀不同。应合并或明确职责分工。

### P2-5: Outdated Docstrings

**File**: `backend/app.py`, Lines 1-14  
Docstring 仍写 "Phase 4 scope"，但实际已到 Phase 10。应更新。

### P2-6: `api/routers/__init__.py` Missing Exports

`__all__` 列表没有包含 `context`, `export`, `monitor`，虽然 `app.py` 直接导入它们不会出错，但 `__init__.py` 不一致。

### P2-7: `system_loader.py` Silent Exception Swallowing

`get_status_summary()` 中有 4 个 `try/except Exception: pass` 块（Lines 187-258），静默吞掉所有错误。应至少记录 warning 日志。

### P2-8: Frontend `initSeasonSelectors()` Repetitive DOM Updates

**File**: `frontend/js/app.js`, Lines 99-127  
7 个 season select 元素的 innerHTML 和 value 被逐个设置，代码重复。应循环处理。

---

## Architecture Compliance Summary

| Rule | Phase 0-7 | Phase 8-9 | Phase 10 |
|------|-----------|-----------|----------|
| §6 No eval()/exec() | ✅ | ✅ | ✅ |
| §6 No dynamic SQL | ✅ | ✅ | ⚠️ (f-string with whitelist) |
| §6 No per-player DB loop | ✅ | ✅ | ✅ |
| §6 No frontend computation | ✅ | ✅ | ✅ |
| §6 No cross-layer leakage | ✅ | ✅ | ❌ (crawler subprocess in API) |
| §2 API = pure orchestration | ✅ | ✅ | ❌ (charts.py computation) |
| §1 Change-log tracking | ✅ | ✅ | ❌ (Phase 10 missing) |
| Test coverage | ✅ 160 tests | ✅ | ❌ 0 new tests |

---

## Recommendations (Priority Order)

1. **Fix P0-1 (XSS)** — 前端所有 `innerHTML` 拼接处添加 `escapeHtml()`
2. **Fix P0-2 (crawler architecture)** — 下沉 subprocess 逻辑到 service 层
3. **Fix P1-6 (exportVS bug)** — 一行修复，立即上线
4. **Add Phase 10 tests** — 至少覆盖层隔离 + 端点冒烟测试
5. **Update change-log** — 补录 Phase 10 BUILD 记录
6. **Fix P1-1 (API computation)** — 下沉 `_compute_box_stats()`
7. **Fix P1-5 (totals fallback)** — 返回 400 或实现真正查询
8. **Fix P0-3 (table name validation)** — `list_tables()` 加白名单
9. **Fix P2 issues** — 按优先级逐步清理

---

## What's Working Well

- **Phase 0-7 架构执行严格**：AST 扫描、层隔离验证、确定性保证都到位
- **Metric Engine 设计优秀**：frozen dataclass + singleton registry + diskcache + 6位精度 + mergesort
- **Deployment 完整**：Dockerfile multi-stage + docker-compose + CI workflow + EXE build
- **SQL 安全实践**：`validate_batch_sql()` + 参数化查询 + 白名单验证（大部分）
- **错误处理**：大多数 router 有 ValueError → 400, Exception → 500 的统一模式
- **前端 UX**：响应式布局、loading spinner、toast 通知、debounced search
