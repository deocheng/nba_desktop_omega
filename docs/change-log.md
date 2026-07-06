# NBACore Studio v8 — Change Log

All changes to LOCKED phases must be recorded here (v8 §1 Change Request mechanism).

## Phase 10 — Feature Enhancements (2026-07-06)

### 2026-07-06 — Player Growth + Context VS + Team Logos

**Status**: ✅ Implemented

**Added**:

1. **球员成长路线 (Player Growth)**
   - 新增 `backend/data_layer/growth_loader.py` — 生涯数据加载器
   - 新增 `backend/services/growth_report.py` — 成长报告生成服务
   - 新增 API: `GET /players/{player_id}/growth` — 返回球员成长报告
   - 新增前端页面: Player Growth（侧边栏导航）
   - 功能特性:
     - 球员生涯逐年数据（身高、体重、年龄、得分、篮板、助攻等）
     - 位置占比分析（出场时间占比、得分占比）
     - 得分占比计算（球员得分 / 球队赛季总得分）
     - 生涯里程碑时间轴
     - ECharts 可视化：折线图、面积图、饼图、雷达图
     - 赛季数据详情表格

2. **Player Context 页面增强**
   - 相似球员列表增强：
     - 点击球员姓名 → 跳转到该球员的 Player Context 页面
     - 📈 按钮 → 跳转到该球员的 Player Growth 页面
     - ⚔️ 按钮 → 将球员添加到 VS 对比
   - Context VS 整合 (Tab 切换模式):
     - 新增 "Context" 和 "VS Compare" 两个 Tab
     - Player 1 自动绑定当前 Context 球员
     - Player 2 可搜索选择任意球员
     - 支持指标选择、数据对比表格、雷达图、柱状图
     - 相似球员一键对比（自动切换到 VS Compare Tab）

3. **球队 Logo 可视化**
   - 球队列表页新增 Logo 列
   - 球队详情页头部显示大尺寸 Logo + 队名
   - 后端静态文件挂载: `/assets/logos/`
   - 30 支 NBA 球队 SVG Logo

**Modified**:
- `frontend/index.html` — 新增 Player Growth 导航、Context Tab 结构、球队 Logo 相关 HTML
- `frontend/js/app.js` — 新增成长报告页面逻辑、Context VS 逻辑、球队 Logo 渲染逻辑
- `frontend/css/style.css` — 新增 `.pos-badge`、`.btn-ghost`、`.ctx-tabs`、`.team-logo-sm`、`.team-detail-header` 等样式
- `backend/api/routers/players.py` — 新增 `/players/{player_id}/growth` 接口和 `GrowthReportResponse` 模型

---

## Phase 9 — Standalone EXE Build (LOCKED 2026-07-06)

### 2026-07-06 — Phase 9 BUILD + VERIFY
**Status**: ✅ LOCKED

**VERIFY results**:
- EXE builds successfully: 54.6 MB one-file executable
- Core API verified: /health, /metrics, /players/seasons, /metrics/evaluate all return 200
- Frontend loads: /app/, /app/css/style.css, /app/js/app.js all return 200
- DB connection works: PostgreSQL pool initialized on port 5433
- 160/160 unit tests pass (no regressions)

**Known issues (minor)**:
- Team logo 404 in EXE mode (StaticFiles path issue, cosmetic only)
- runtime_guard AST scan warning (db.py not a real file in PyInstaller archive, non-critical)

**Added**:
- `main.py` — EXE entry point (uvicorn + auto-open browser)
- `nbacore.spec` — PyInstaller spec (onefile, console mode, backend+frontend+logos bundled)
- `build.ps1` — One-click build script (auto-installs PyInstaller, builds, verifies)
- `requirements.txt` — 11 pinned production dependencies

**Modified**:
- `backend/app.py` — Static file paths adapted for PyInstaller (_MEIPASS-aware)
- `.env.example` — Added Docker + WORKERS notes
- `.gitignore` — Added build/, dist/, PyInstaller artifacts

**How to build**:
```powershell
.\build.ps1           # Build EXE
.\build.ps1 -Clean    # Clean rebuild
```

**Output**: `dist\NBACore.exe`

**How to run**:
1. Ensure PostgreSQL running on localhost:5433 (database: nba)
2. Double-click NBACore.exe
3. Browser opens automatically to http://127.0.0.1:5577/app/
4. Ctrl+C in console window to stop

---

## Phase 8 — Deployment Preparation (LOCKED 2026-07-06)

### 2026-07-06 — Phase 8 BUILD + VERIFY
**Status**: ✅ LOCKED

**VERIFY results**:
- 160/160 tests passed (0 regressions)
- All 8 deployment files validated (YAML syntax, file integrity)
- Dockerfile: multi-stage build, non-root user, health check
- docker-compose: PostgreSQL 16 + app, health checks, volumes

**Added**:
- `Dockerfile` — multi-stage build (builder + runtime), gunicorn + uvicorn workers, health check, non-root user
- `docker-compose.yml` — PostgreSQL 16-alpine + app service, volumes for pgdata + cache
- `.dockerignore` — build context exclusions
- `requirements.txt` — 11 pinned production dependencies
- `.github/workflows/ci.yml` — GitHub Actions CI (test + docker-build)
- `start.sh` — Unix dev/prod start script
- `start.ps1` — Windows dev/prod start script

**Modified**:
- `.env.example` — added Docker notes + WORKERS config
- `.gitignore` — added Docker artifacts

**Deployment architecture**:
- **Dev**: `uvicorn --reload` (start.sh dev / start.ps1 dev)
- **Prod (Docker)**: `gunicorn --workers 4 --worker-class uvicorn.workers.UvicornWorker`
- **CI**: GitHub Actions → test → docker build → health check
- **DB**: PostgreSQL 16-alpine, port 5433 (v7 compat), health check via pg_isready
- **Cache**: diskcache volume mounted at /app/.cache/metric_engine

**Security**:
- Non-root user (nbacore) in Docker container
- No secrets in images (env vars only)
- Health check on /health endpoint

---

## Phase 7 — Testing & Monitoring (LOCKED 2026-07-06)

### 2026-07-06 — Phase 7 BUILD + VERIFY
**Status**: ✅ LOCKED (auto-advance, low priority)

**VERIFY results**:
- 160/160 tests passed (0 regressions)
- Benchmark suite runs successfully (7 benchmarks)
- /monitor/stats endpoint returns correct structure
- Context + Export + Monitor all covered by tests

**Performance baseline (2025 season, warm cache)**:
- Single metric compute: 0.26ms (warm), 15.38ms (cold)
- compute_many (5 metrics): 0.53ms (warm)
- Rank top 100: 2.87ms
- Similar players: 18.77ms
- Role evolution (5 seasons): 1.37ms (warm)
- Trend analysis: 0.85ms (warm)

**Added**:
- `scripts/benchmark.py` — 7 benchmarks across all layers
- `backend/api/routers/monitor.py` — /monitor/stats endpoint
- `tests/test_phase7_monitoring.py` — 21 tests (context + export + monitor + benchmark)

**Modified**:
- `backend/app.py` — registered monitor router, phase = "7-testing-monitoring"
- `backend/api/routers/context.py` — fixed dataclass→dict conversion for Pydantic response
- `tests/test_phase0_health.py` — updated phase assertion

**Bug fixes**:
- Context router: dataclass objects not compatible with Pydantic response_model → vars() conversion
- Stale cache with old data format → cleared .cache/metric_engine

---

## Phase 6 — Export & Offline System (LOCKED 2026-07-06)

### 2026-07-06 — Phase 6 BUILD + VERIFY + VALIDATE
**Status**: ✅ LOCKED (auto-advance, low priority)

**VERIFY results**:
- 139/139 tests passed (0 regressions)
- Determinism: 4/4 checks passed (JSON + CSV for rankings + VS)
- SHA256 consistency verified across repeated calls
- Layer isolation: export_service uses only metric_engine (no direct DB access)

**VALIDATE results**:
- ✅ Rankings JSON export: 5.9KB, correct structure
- ✅ Rankings CSV export: 1.5KB, correct structure
- ✅ VS JSON export: correct structure with both players
- ✅ VS CSV export: correct structure with metric rows
- ✅ X-Export-SHA256 header present on all responses
- ✅ Content-Disposition attachment header correct

**Added**:
- `backend/services/export_service.py` — 6 export functions + ExportResult dataclass
- `backend/api/routers/export.py` — 3 endpoints: /rankings, /vs, /player
- Frontend: Export buttons (JSON + CSV) on Rankings and VS pages

**Modified**:
- `backend/app.py` — registered export router, phase = "6-export-offline"
- `frontend/index.html` — JSON/CSV export buttons on Rankings + VS
- `frontend/js/app.js` — exportRankings(), exportVS() functions
- `tests/test_phase0_health.py` — updated phase assertion

**Export formats supported**:
- Rankings: JSON, CSV
- VS Comparison: JSON, CSV
- Player metrics: JSON

**Determinism guarantees**:
- JSON: sort_keys=True + indent=2
- CSV: sorted metric names, consistent row order (rank order)
- SHA256 hash in X-Export-SHA256 header
- Filename includes metric/players + season + date

---

## Phase 5 — Context System (LOCKED 2026-07-06)

### 2026-07-06 — Phase 5 BUILD + VERIFY + VALIDATE
**Status**: ✅ LOCKED (auto-advance, low priority)

**VERIFY results**:
- 139/139 tests passed (0 regressions)
- Layer isolation: context_engine has NO data_layer / psycopg2 / SQL imports
- All data flows through Metric Engine (compute_many + get_player_bios)
- API router (context.py) is pure orchestration — no pandas, no computation

**VALIDATE results**:
- ✅ /context/similar — 10 similar players returned for LeBron (cosine sim, z-score normalized)
- ✅ /context/evolution — 5-season role evolution with 10 metrics, overall shift magnitude
- ✅ /context/trend — linear regression (slope, intercept, r², momentum, prediction)
- ✅ Frontend Context page — all 3 sections render with data

**Added**:
- `backend/services/context_engine/__init__.py` — public API
- `backend/services/context_engine/similar_players.py` — cosine similarity + z-score normalization
- `backend/services/context_engine/role_evolution.py` — multi-season metric change + OLS slope
- `backend/services/context_engine/trend_analysis.py` — linear trend + momentum + prediction
- `backend/api/routers/context.py` — 3 endpoints: /similar, /evolution, /trend
- Pydantic schemas: SimilarPlayersResponse, RoleEvolutionResponse, TrendResponse
- Frontend: Context page (sidebar nav + similar players + evolution grid + trend chart)
- CSS: .stat-chip, .metric-tile components

**Modified**:
- `backend/app.py` — registered context router, phase = "5-context-system"
- `frontend/index.html` — Context System title + Player Context nav + page
- `frontend/js/app.js` — context page logic (search + similar + evolution + trend)
- `frontend/css/style.css` — stat-chip + metric-tile styles
- `tests/test_phase0_health.py` — updated phase assertion

**Decisions**:
- Context Engine is Layer 2.5 — sits between Metric Engine and API layer
- Cosine similarity with z-score normalization (all metrics equal weight)
- OLS linear regression (hand-rolled, no scipy/numpy dep beyond pandas)
- Position filter optional (default on) — restricts similarity to same-position players
- Default metric set: 10 core metrics (per-game + advanced + composite)
- Evolution uses 5-season window (current + 4 prior)
- Trend includes momentum (last 3 seasons slope vs overall slope ratio)

---

## Phase 4 — Frontend VS System (LOCKED 2026-07-06)

### 2026-07-06 — Phase 4 VERIFY + VALIDATE
**Status**: ✅ LOCKED (confirmed by user)

**VERIFY results**: Layer isolation check passed
- Violations: 0
- Warnings: 3 (all display-only — `filter(Boolean)` for string join, `Math.max` for axis scaling)
- Static mount: ✅ FastAPI StaticFiles with html=True
- Files scanned: 1 JS file (frontend/js/app.js)

**VALIDATE**: End-to-end browser test (E2E)
- ✅ Page loads correctly at http://127.0.0.1:5577/app/
- ✅ Season selector populated (10+ seasons from fact_player_season_stats)
- ✅ Player search works (LeBron James → jamesle01)
- ✅ Player card renders with initials + name + team/position
- ✅ Metric grid renders with 11 metrics (auto-selects first 5)
- ✅ VS Compare button enables when both players + metrics selected
- ✅ VS Results: 5 metric rows rendered in table
- ✅ Radar chart: ECharts canvas rendered with both players
- ✅ Bar chart: ECharts canvas rendered with both players
- ✅ Rankings page: 50 player rows loaded (ast_per_game default)
- ✅ Console: 0 frontend errors (only TRAE preload errors, not our code)

**v8 §2 Layer 4 Compliance**:
- ✅ Pure render — no business computation
- ✅ All data from API (no hardcoded metrics)
- ✅ Uses mature chart library (ECharts 5.5.0 via CDN)
- ✅ No eval()/new Function()
- ✅ No client-side data filtering/sorting/aggregation
- ✅ Team logo assets mounted at /assets/logos (NBAlogo SVGs)

### 2026-07-06 — Phase 4 BUILD
**Added**:
- `frontend/index.html` — VS System main page (sidebar + 2 pages: VS Compare + Rankings)
- `frontend/css/style.css` — Dark theme,延续 v7 design system
- `frontend/js/app.js` — Pure render logic (API calls + DOM rendering + ECharts)

**Modified**:
- `backend/app.py` — mounted /app (frontend) and /assets/logos (NBAlogo) via StaticFiles
- `backend/app.py` — updated phase field to "4-frontend-vs"
- `backend/api/routers/players.py` — added GET /players/seasons endpoint
- `backend/services/metric_engine/batch_loader.py` — added get_available_seasons() wrapper
- `backend/services/metric_engine/__init__.py` — exported get_available_seasons
- `tests/test_phase0_health.py` — updated root phase assertion

**Phase 3 Change Request**: /players/seasons endpoint (additive, non-breaking)
- Added new endpoint to support season selector in frontend
- Goes through metric_engine → data_layer (layer isolation maintained)
- Uses existing load_seasons_available() function
- Regression: 139/139 tests pass

**Frontend Features**:
1. **VS Compare Page**:
   - Dual player search (debounced 300ms, dropdown with name + team/position)
   - Player cards with initials avatar + name + team/position
   - Dynamic metric selector (11 metrics from API, select all / clear)
   - Compare button (disabled until both players + metrics selected)
   - Results table with win highlighting (higher = better, colored per player)
   - Radar chart (ECharts) with normalized axes
   - Bar chart comparison (ECharts)
2. **Rankings Page**:
   - Metric selector (all registered metrics)
   - Season selector
   - Top 50 players table with rank, value, percentile
   - Medal colors for top 3
3. **System**:
   - Server status indicator (sidebar footer)
   - Toast notifications
   - Responsive layout (mobile-friendly)
   - Dark theme (NBACore brand colors: #00d9a3 accent)

**Decisions**:
- Vanilla HTML/CSS/JS — no framework (keeps Layer 4 simple and auditable)
- ECharts 5.5.0 via CDN — mature chart library (v8 §2.4 approved)
- Frontend served via FastAPI StaticFiles — single server deployment
- Logo assets at /assets/logos — mounted from NBAlogo directory
- No frontend computation — all metrics from /vs/compare API
- Win highlighting uses API values directly (no client-side calculation)

---

## Phase 3 — API Layer (LOCKED 2026-07-06)

### 2026-07-06 — Phase 3 VERIFY + VALIDATE + FIX
**Status**: All verification passed, awaiting user LOCK confirmation

**VERIFY results**: 139/139 tests passed in 12.10s
- Phase 0: 32 + Phase 0.5: 20 + Phase 1: 16 + Phase 2: 42 + Phase 3: 29
- TestSchemas: 4/4 (MetricInfo serialization, PlayerBio.from_row date handling, null date, VS None handling)
- TestMetricsEndpoints: 5/5 (list all, detail, 404, season validation, evaluate rankings)
- TestPlayersEndpoints: 4/4 (search validation, search results, 404, detail with metrics)
- TestVSEndpoint: 4/4 (same player 400, unknown metric 404, season required, real comparison)
- TestBatchEndpoint: 3/3 (empty 400, invalid type 400, rank+compute)
- TestLayerIsolation: 5/5 (no pandas, no psycopg2, no SQL, no eval/exec, routers concise)
- TestRealEndpoints2025: 4/4 (PPG top 10, VS compare stars, player detail, batch compute_many)

**VALIDATE**: real 2025 season endpoint integration verified
- GET /metrics → 11 metrics listed (5 per_game + 4 ratio + 2 composite)
- GET /metrics/evaluate/pts_per_game?season=2025&limit=10 → PPG top 10:
  #1 gilgesh01 (SGA) 32.68, #2 antetgi01 (Giannis) 30.39, #3 jokicni01 (Jokic) 29.59, #4 doncilu01 (Luka) 28.16, #5 edwaran01 (Ant) 27.56 — matches NBA reality
- GET /vs/compare?p1=gilgesh01&p2=antetgi01&season=2025 → 10 metrics side-by-side:
  SGA wins PPG (32.68 vs 30.39), Giannis wins REB (11.91 vs 4.99)
- GET /players/gilgesh01?season=2025 → bio + 5 default metrics (PPG 32.68, RPG 4.99, APG 6.40, TS% 0.637, Fantasy 4271.8)
- POST /batch → rank (Fantasy top 5: LaVine 5616, Luka 5603, Fox 5393, AD 5339, Jokic 4639) + compute_many (569 players, 3 metrics each)
- Layer Isolation: PASS — no pandas/psycopg2/SQL/eval in backend/api/

**FIX**: 3 issues found and fixed
1. **Duplicate player_id rows in fact_player_season_stats** (Change Request on Phase 2):
   - Root cause: 5 traded players had multiple rows per season (e.g., `anderky01` with 3 team stints). `execute_many`/`execute_spec` produced DataFrames with duplicate indices, causing `df.loc[pid]` to return a DataFrame instead of Series, triggering "truth value of a Series is ambiguous" error.
   - Fix: Added `if matrix.index.has_duplicates: matrix = matrix.groupby(matrix.index).sum(numeric_only=True)` in both `execute_spec` and `execute_many` (executor.py). This aggregates traded players' team stints into season totals before computing metrics.
   - Regression: all 42 Phase 2 tests still pass.

2. **Empty player data causing 500 errors** (Change Request on Phase 2):
   - Root cause: `compute()`/`compute_many()` called `execute_spec()` even when `load_metric_input()` returned 0 rows (player has no 2025 data). `build_matrix()` then raised ValueError → 500.
   - Fix: Added `if not rows: return pd.Series(dtype=float)` / `return pd.DataFrame(columns=metric_names)` guards in `compute()` and `compute_many()` (__init__.py). Players with no data now get empty metrics dict instead of 500.
   - Regression: all Phase 2 tests still pass.

3. **VSCompareResponse schema rejecting None values**:
   - Root cause: `vs_compare()` converts NaN to None for missing player data, but `VSCompareResponse.metrics` was typed as `dict[str, dict[str, float]]` (no None). Pydantic validation would fail.
   - Fix: Changed type to `dict[str, dict[str, float | None]]` in schemas.py.

**Phase 2 Change Request** (v8 §1 controlled exception):
- Modified files: `backend/services/metric_engine/executor.py`, `backend/services/metric_engine/__init__.py`
- Changes: duplicate row aggregation + empty data guards (described above)
- Regression test: 42/42 Phase 2 tests pass + 6/6 TestRealCompute2025 pass
- Architecture review: no API change, no new computation, purely data-handling robustness

### 2026-07-06 — Phase 3 BUILD
**Added**:
- `backend/api/__init__.py` — Layer 3 package (pure orchestration docstring)
- `backend/api/schemas.py` — 10 Pydantic models (MetricInfo, RankingItem, PlayerBio, VSCompareResponse, BatchOperation, etc.)
- `backend/api/routers/__init__.py` — exports 4 routers
- `backend/api/routers/metrics.py` — GET /metrics, GET /metrics/{name}, GET /metrics/evaluate/{name}
- `backend/api/routers/players.py` — GET /players?name=, GET /players/{id}?season=
- `backend/api/routers/vs.py` — GET /vs/compare?p1=&p2=&season=
- `backend/api/routers/batch.py` — POST /batch (rank/compute/compute_many)
- `tests/test_phase3_api_layer.py` — 29 tests across 7 classes

**Modified**:
- `backend/app.py` — registered 4 routers via `app.include_router()`, updated phase to "3-api-layer"
- `backend/data_layer/batch_loader.py` — added `search_players()` (additive, non-breaking)
- `backend/data_layer/__init__.py` — added `search_players` to exports
- `backend/services/metric_engine/__init__.py` — added `player_metrics_dict()`, `vs_compare()`, `compute_as_dict()`, `compute_many_as_dict()` (dict-returning helpers to prevent pandas leaking to API)
- `backend/services/metric_engine/batch_loader.py` — added `get_player_bios()`, `search_players_by_name()` wrappers
- `tests/test_phase0_health.py` — updated root endpoint phase assertion to "3-api-layer"

**Decisions**:
- API layer returns plain dicts (no pandas objects) via dict-returning helpers in metric_engine
- Player search uses ILIKE on player_name + full_name (case-insensitive)
- Default player metrics: pts_per_game, reb_per_game, ast_per_game, true_shooting_pct, fantasy_points
- Default VS metrics: all 10 built-in metrics (5 per_game + 4 ratio + efficiency_rating)
- Batch endpoint validates metric names against registry before dispatch
- VSCompareResponse allows `float | None` for missing player data
- Test player IDs fetched dynamically from /metrics/evaluate (avoids diacritic search issues)

**v8 Compliance Checks**:
- ✅ API layer has NO pandas/numpy imports (AST scan in TestLayerIsolation)
- ✅ API layer has NO psycopg2 imports (AST scan)
- ✅ API layer has NO SQL strings (keyword scan)
- ✅ API layer has NO eval/exec (AST scan)
- ✅ API layer has NO computation logic (routers < 200 lines each, pure orchestration)
- ✅ All computation delegated to metric_engine (sole compute layer)
- ✅ No mock for Metric Engine (real endpoints against real DB)
- ✅ Deterministic outputs (same season → same rankings)

---

## Phase 2 — Metric Engine Core (LOCKED 2026-07-06)

### 2026-07-06 — Phase 2 VERIFY + VALIDATE + FIX
**Status**: All verification passed, awaiting user LOCK confirmation

**VERIFY results**: 110/110 tests passed in 10.10s
- Phase 0: 32 + Phase 0.5: 20 + Phase 1: 16 + Phase 2: 42
- TestRegistry: 7/7 (register, list, dup, unknown, frozen, tuple-only, builtins)
- TestMatrixBuilder: 7/7 (player_index, missing cols, missing player_col, empty, keep-only, **drops null player_id**, all-null raises)
- TestExecutor: 6/6 (per_game, ratio, weighted_sum, expression, precision, execute_many)
- TestCache: 4/4 (deterministic key, params differ, hit/miss, byte-stable)
- TestRankEngine: 6/6 (desc, asc, ties, percentile, min_value, empty)
- TestDeterminism: 3/3 (same input → byte-identical, float precision, stable tie-break)
- TestLayerIsolation: 3/3 (no psycopg2, no eval/exec via AST, no dynamic SQL)
- TestRealCompute2025: 6/6 (PPG sane, TS% in range, fantasy positive, rank sorted, cache hit, compute_many)

**VALIDATE**: real 2025 season integration verified
- PPG top 5: gilgesh01 (SGA) 32.68, antetgi01 (Giannis) 30.39, jokicni01 (Jokic) 29.59, doncilu01 (Luka) 28.16, edwaran01 (Ant) 27.56 — matches 2024-25 NBA season
- Fantasy top 5: lavinza01 5616, doncilu01 5603, foxde01 5393, davisan02 5339, jokicni01 4639
- Cache: 0.069s compute → 0.000s cache hit, byte-identical: True
- Determinism: same input across runs → byte-identical pickle: True
- 11 metrics registered: pts_per_game, reb_per_game, ast_per_game, stl_per_game, blk_per_game, true_shooting_pct, effective_fg_pct, ft_rate, usage_percent, fantasy_points, efficiency_rating

**FIX**: 1 critical bug found and fixed
1. **NULL player_id aggregation bug**: `fact_player_season_stats` has rows with `player_id IS NULL` (likely league-aggregate or TOT rows). `build_matrix` was coercing NaN → string "None", which then aggregated all null-player rows into a single bogus #1 ranking (36858 fantasy points). Fix: drop `notna()` rows + empty strings before `astype(str)`; raise `ValueError` if all rows are null. Added 2 regression tests.

**v8 §2 Layer 2 Architecture**:
- `registry.py` — MetricSpec (frozen dataclass) + MetricRegistry (singleton)
- `matrix_builder.py` — list[dict] → player-indexed DataFrame (drops null IDs)
- `executor.py` — vectorized compute, precision rounding, execute_many
- `cache.py` — diskcache + SHA256 key (sorted player_ids, sort_keys=True)
- `batch_loader.py` — wraps Layer 1 (no direct SQL in metric_engine)
- `rank.py` — Ranking dataclass + stable tie-break (player_id asc)
- `metrics/basic.py` — 5 per-game metrics (PPG/RPG/APG/SPG/BPG)
- `metrics/advanced.py` — 4 ratio metrics (TS%/eFG%/FT Rate/USG%)
- `metrics/composite.py` — 2 weighted-sum metrics (Fantasy/Efficiency)

### 2026-07-06 — Phase 2 BUILD
**Added**:
- `backend/services/metric_engine/registry.py` — MetricSpec + MetricRegistry
- `backend/services/metric_engine/matrix_builder.py` — build_matrix + coerce_numeric
- `backend/services/metric_engine/executor.py` — execute_metric / execute_spec / execute_many
- `backend/services/metric_engine/cache.py` — CacheEngine + make_cache_key + get_engine
- `backend/services/metric_engine/batch_loader.py` — load_metric_input (wraps data_layer)
- `backend/services/metric_engine/rank.py` — rank_players + Ranking + to_dataframe
- `backend/services/metric_engine/metrics/__init__.py` — auto-registration side-effect
- `backend/services/metric_engine/metrics/basic.py` — 5 per-game metrics
- `backend/services/metric_engine/metrics/advanced.py` — 4 ratio metrics
- `backend/services/metric_engine/metrics/composite.py` — 2 composite metrics
- `backend/services/metric_engine/__init__.py` — public API + compute/compute_many/rank
- `tests/test_phase2_metric_engine.py` — 42 tests across 8 classes
- `pyproject.toml` — moved numpy/pandas from optional `compute` to required deps

**Decisions**:
- Vectorization backend: pandas (mature, deterministic, handles NaN gracefully)
- Metric declaration: frozen dataclass + explicit compute Callable (no decorator magic)
- Cache key: SHA256(metric_name | season | sorted(player_ids) | params_json sort_keys=True)
- Cache serialization: pickle protocol=5 (fixed for byte-stable)
- Rank tie-break: player_id ascending (lexicographic on str)
- Determinism: round to 6 decimals + mergesort (stable) + sorted cache key
- `compute()` / `compute_many()` / `rank()` are the high-level public API for Phase 3

**v8 Compliance Checks**:
- ✅ No eval()/exec() (AST scan in TestLayerIsolation)
- ✅ No dynamic SQL (no psycopg2 import in metric_engine)
- ✅ No per-player DB loop (compute fns are vectorized pandas groupby)
- ✅ No cross-layer leakage (metric_engine only imports pandas + data_layer)
- ✅ No mock for Metric Engine core (real compute against real DB)
- ✅ Determinism verified (byte-identical pickle across runs)

---

## Phase 1 — Data Layer Validation (LOCKED 2026-07-06)

### 2026-07-06 — Phase 1 VERIFY + VALIDATE + FIX
**Status**: All verification passed, awaiting user LOCK confirmation

**VERIFY results**: 68/68 tests passed in 8.95s (Phase 0: 32 + Phase 0.5: 20 + Phase 1: 16)
- TestTempTableLoader: 3/3 (empty ids rejected, id_type validation, select_sql must reference temp table)
- TestSchemaValidator: 4/4 (registry healthy, drift summary, per-table validate, missing column detection)
- TestJoinLoaders: 2/2 (gamelog+game_context, season_stats+bio — single query, no N+1)
- TestTempTableRealQuery: 2/2 (gamelog temp load vs IN-clause deterministic match, players temp load)
- TestRuntimeGuardPhase1: 5/5 (no per-player loop via AST, no dynamic SQL, no eval/exec, layer isolation, SQL trace)

**VALIDATE**: real DB integration verified
- Temp table batch (`batch_query_with_temp_ids`): identical output to IN-clause for same ID set → deterministic
- Schema drift detection caught real issue: `player_season_splits` has no `player_id` column (only `player_name`)
- Join loaders return enriched rows: gamelog + game_context, season_stats + bio (single query each)
- AST-based loop detection confirmed: no `for player in players: batch_query(...)` pattern in any data_layer module

**FIX**: 1 issue found and fixed
1. Schema drift: `player_season_splits.player_col` changed from `"player_id"` to `None` (table only has `player_name`, no stable player_id) — schema_validator correctly flagged this before runtime failure

**v8 §2 Controlled Exception**: temp table pattern (`_nbacore_batch_ids`) approved for batches >500 IDs
- Hardcoded DDL constant (NOT dynamic SQL)
- `ON COMMIT DROP` for auto-cleanup
- Only the final SELECT is validated via `validate_batch_sql`
- Threshold: `TEMP_TABLE_THRESHOLD = 500` in `temp_loader.py`

### 2026-07-06 — Phase 1 BUILD
**Added**:
- `backend/core/db.py` — extended with `batch_query_with_temp_ids()` + `temp_table_name()` (v8 §2 controlled exception)
- `backend/data_layer/temp_loader.py` — temp table batch loaders (gamelog, players) + `should_use_temp_table()` threshold
- `backend/data_layer/schema_validator.py` — `DriftReport` dataclass + `validate_table()` + `validate_registry()` + `registry_healthy()` + `drift_summary()`
- `backend/data_layer/joins.py` — cross-table join batch loaders (gamelog+game_context, season_stats+bio)
- `backend/data_layer/__init__.py` — updated exports (6 IN-clause + 4 temp + 2 join + 3 schema validators)
- `tests/test_phase1_data_layer.py` — 16 tests across 5 classes

**Decisions**:
- Temp table name is a hardcoded constant `_nbacore_batch_ids` (not dynamic SQL, v8 §6 compliant)
- Temp table threshold = 500 IDs (above this, IN-clause becomes impractical)
- Schema validator runs at startup and on-demand (catches column renames/drops before runtime)
- Join loaders use LEFT JOIN to preserve all base rows even when dimension has gaps
- AST-based loop detection (`ast.walk` for `ast.For` nodes) replaces fragile line heuristics

---

## Phase 0.5 — Data Ingestion & Schema (LOCKED 2026-07-06)

### 2026-07-06 — Phase 0.5 VERIFY + VALIDATE + FIX
**Status**: All verification passed, awaiting user LOCK confirmation

**Schema introspection** (38 tables + 35 views in `nba` DB):
- play_by_play: 18.07M rows
- player_gamelog: 1.91M rows (54 cols, br_player_id is BBR key, 96% coverage)
- fact_player_season_stats: 45K rows (74 cols, player_id is BBR string)
- dim_games: 99K rows (99 cols)
- dim_players: 5.5K rows
- Seasons available: 2017–2026

**Key data finding**: player_gamelog has TWO mutually-exclusive ID columns:
- `player_id` = NBA.com numeric ID (47% coverage)
- `br_player_id` = BBR string ID (96% coverage, matches fact_player_season_stats)
- Schema registry uses `br_player_id` as the canonical key for player_gamelog

**VERIFY results**: 20/20 Phase 0.5 tests passed + 32/32 Phase 0 regression still green (52 total)
- TestSchemaRegistry: 6/6 (key tables, season cols, frozen dataclass)
- TestSeasonEnforcement: 4/4 (rejects invalid, accepts valid, dims exempt)
- TestInClause: 3/3 (single/multi/empty)
- TestNoPerPlayerLoop: 1/1 (AST-based detection, no false positives)
- TestRealBatchQuery: 6/6 (real DB: seasons, stats, gamelog, IN-filter, games, players)

**VALIDATE**: real batch queries executed against live PostgreSQL:
- load_player_season_stats(2025) → ~600 player rows
- load_player_gamelog(2025) → 93,307 game log rows
- load_player_gamelog(2025, player_ids=[3 BBR IDs]) → IN-clause filter verified
- load_games(2025) → game dimension rows
- load_players([3 IDs]) → dimension batch load

**FIX**: 2 issues found and fixed
1. Schema: player_gamelog.player_col changed from `player_id` (47% coverage) to `br_player_id` (96% coverage)
2. Test: loop detection switched from line heuristic (false positive on docstring) to AST-based check

### 2026-07-06 — Phase 0.5 BUILD
**Added**:
- `backend/data_layer/__init__.py` — Layer 1 package, exports 6 loaders
- `backend/data_layer/schema.py` — TableSchema dataclass + REGISTRY (8 tables)
- `backend/data_layer/batch_loader.py` — 6 batch loaders with season filter enforcement
- `tests/test_phase05_data_layer.py` — 20 tests across 5 test classes

**Decisions**:
- season filter enforced at function signature (required param, no default)
- IN-clause batch via parameterized `%s` placeholders (no dynamic SQL)
- AST-based loop detection in tests (no per-player DB round-trips)
- Dimension tables (dim_players, dim_teams) exempt from season filter

---

## Phase 0 — Environment Bootstrap (LOCKED 2026-07-06)

### 2026-07-06 — Phase 0 VERIFY + VALIDATE
**Status**: All verification passed, awaiting user LOCK confirmation

**VERIFY results**: 32/32 tests passed (0.27s)
- TestConfig: 5/5 (port 5433, db=nba, version 8.0.0, season, dsn)
- TestSqlValidation: 10/10 (SELECT allowed, 8 DML/DDL rejected, empty rejected)
- TestLayerIsolation: 2/2 (app.py no psycopg2, no SQL keyword)
- TestRuntimeGuard: 4/4 (all 3 checks registered + pass)
- TestLoggingTraceability: 3/3 (query_id unique/bound, setup idempotent)
- TestHealthEndpoint: 6/6 (200, fields, status, version, bool, root)
- TestDbConnectivity: 2/2 (live PostgreSQL ping + batch_query SELECT 1)

**VALIDATE results**: uvicorn server started on 127.0.0.1:5577
- GET /health → 200, status="ok", database_connected=true, 3 guards ok
- GET / → 200, version 8.0.0, phase 0-bootstrap

**FIX**: no issues found, skipped

### 2026-07-06 — Phase 0 BUILD
**Status**: BUILD complete

**Added**:
- `pyproject.toml` — project config, deps lock, pytest config
- `.env.example` — environment template (DB port 5433 inherited from v7)
- `.gitignore`
- `backend/__init__.py` — four-layer architecture docstring
- `backend/core/__init__.py`
- `backend/core/config.py` — config layer (manual .env loader, no extra deps)
- `backend/core/logging.py` — structured logging with query_id/request_id (contextvars)
- `backend/core/db.py` — Layer 1 DB pool + batch_query + SQL validation (SELECT only)
- `backend/core/runtime_guard.py` — §5.5 startup checks (config/metric_engine/no_forbidden)
- `backend/app.py` — FastAPI app factory + lifespan + /health + / root
- `backend/services/__init__.py`
- `backend/services/metric_engine/__init__.py` — placeholder (Phase 2 fills in)
- `tests/__init__.py`
- `tests/conftest.py` — TestClient fixture, DB availability skip
- `tests/test_phase0_health.py` — 20+ tests covering config/SQL/guard/logging/health

**Decisions**:
- Web framework: FastAPI (async-first, auto OpenAPI)
- DB driver: psycopg2-binary (sync, matches v7, batch-friendly)
- Cache: diskcache (Phase 2 will consume)
- DB port: 5433 (inherited from v7, NOT default 5432)
- Server port: 5577 (inherited from v7)
- No python-dotenv (manual loader, v8 §6 minimal deps)
- No structlog (stdlib logging + contextvars, sufficient for traceability)

**v8 Compliance Checks**:
- ✅ No eval()/exec() in core modules
- ✅ No dynamic SQL (parameterized queries only via batch_query)
- ✅ No per-player DB loop (Phase 1 will enforce at data_layer)
- ✅ No frontend computation (frontend not yet built)
- ✅ No cross-layer leakage (runtime_guard checks metric_engine import)
- ✅ No mock for Metric Engine (placeholder only, real logic in Phase 2)
