# Test Report — _backfill_2026_gap31.py（2026 RS 缺失 31 场补录）

## 验收结论：**通过（PASS）** ｜ 智能路由判定：**NoOne**（源码无 bug，测试已自修）

测试对象：`reconcile_2026-07-10/_backfill_2026_gap31.py`
测试脚本：`reconcile_2026-07-10/test_backfill_2026_gap31.py`（自包含 harness，可直接复跑）
环境：PG localhost:5433 db=nba；`.venv` 位于项目根；已 `env -u *proxy` 去代理。

## Summary
- 验收 6 大项：**6 / 6 PASS**，源码层面 **0 FAIL**。
- 单元测试/断言：全部 PASS（31 行逐行字段校验 × dim_games/games 双表，幂等 ×2，§6 ×9，回归 ×6）。
- 路由判定：**NoOne** —— 工程师交付的脚本行为正确，验收 1–6 均满足，无需回退给工程师。
- 遗留项（非脚本缺陷）：见下方「Known Issues / WARNING」。

## 逐项验收结果

### 验收1 · 复跑计数 = 1350 ✅
- `dim_games WHERE season=2026 AND season_type='Regular Season'` = **1350**
- `games` 同条件 = **1350**
- 与交付声明（落库后各 1350，++31）一致。

### 验收2 · 31 个 game_id 存在且字段规范 ✅
- `_GAP31` 清单 31 场，game_id 唯一。
- `dim_games` / `games` 两表 31 行全部存在（`WHERE game_id = ANY(ARRAY[...])` 抽查）。
- 逐行校验（dim_games + games 双表均通过）：
  - `game_date` 非空、`away_team_abbr`/`home_team_abbr` 非空；
  - `br_crawled_id` 非空且 == `game_id`（YYYYMMDD+home_abbr，BR 键）；
  - `source='BBRef'`、`nba_api_id IS NULL`；
  - **比分列 `home_pts`/`away_pts` 全 NULL**（其它统计列因未写入亦为默认 NULL）；
  - `season=2026`、`season_type='Regular Season'`。

### 验收3 · 幂等（再跑 0 插入）✅
- 子进程复跑 `--execute`：输出 `已存在跳过: 31 | 待补录: 0` → `无需补录`，落库前后计数均为 1350（dim_games/games 各不变）。
- 强幂等验证：绕过 Python 早退分支，直接对“已存在”的 31 行调用 `execute_values(... ON CONFLICT (game_id) DO NOTHING)`，前后计数差 = 0（dim_games 31→31、games 31→31），证明 `ON CONFLICT DO NOTHING` 机制生效。

### 验收4 · §6 合规（无动态 SQL 拼值）✅
- **无** `execute("..."+var+...)` 式值拼接（grep 正则零命中）。
- 所有 INSERT 经 `execute_values` + `%s` **参数化**；值无拼接。
- 表名/列名均为**代码字面常量**（`f"{tbl}"` 中 `tbl` 恒为 `'dim_games'`/`'games'`；`','.join(dim_cols)` 为常量列表），**无任何外部输入路径**（无 `input()`；`sys.argv` 仅作 `--execute` 开关；无 `open()` 读数据入 SQL）。
- 两条 INSERT 均带 `ON CONFLICT DO NOTHING`。

### 验收5 · 回归（无重复 / 前期不被影响）✅
- `dim_games` / `games` 内 `season=2026 RS` **无重复 game_id**（`GROUP BY game_id HAVING count(*)>1` = 0）。
- 前期 1319 行未被影响：NULL-source 行保持 **935**，BBRef 总数 **415** = 既有 384 + gap31 31；合计 1350。
- 31 个 gap31 行均已落库（BBRef，2026 RS），确为**增量追加**。

### 验收6 · 智能路由判定 ✅ → **NoOne**
- 源码行为正确，6 项验收全过；中途发现的失败均为**测试脚本自身 bug**（已自修 2 处：§6 正则误伤 `','.join()` 代码字面量拼接；abbr 校验表达式返回字符串而非 bool），非源码缺陷。判定 NoOne。

## Known Issues / WARNING（非 gap31 缺陷，供主理人裁定）
- **241 补录清单在本环境缺失**：验收文案称“既有 241 补录行未被影响”，但由 `missing_2026_rs.tsv`（241 行）推导的 241 个 game_id **仅 29 个存在于本库**（其余 212 场在本库完全不存在）。即该 241 补录（`_backfill_dim_games.py`）疑似**未在本环境执行/已漂移**。
- 此问题与 `_backfill_2026_gap31.py` 无关：gap31 仅 `INSERT`，不删不改既有行；实测前期 1319 行（935+384）完整保留、计数无异常。
- **建议**：主理人核查 `_backfill_dim_games.py` 是否已在当前 PG 实例运行；若 241 行确属预期缺失，则 gap31 验收不受影响，可判通过。

## 复跑方式
```bat
cd C:/autopick/AutoPick/nba_data/nba_desktop/nba_desktop_omega/reconcile_2026-07-10
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY ^
  C:/autopick/AutoPick/nba_data/nba_desktop/nba_desktop_omega/.venv/Scripts/python.exe ^
  test_backfill_2026_gap31.py
```
退出码 0 = 全部通过。
