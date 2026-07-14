# cba_aux — NBA CBA 薪资规则补充模块

> v8.3.2+ 引入。`backend.services.trade_engine` 的纯算法补充模块。

## 模块定位

`cba_aux.py` 是 `trade_engine` 的**补充模块**，与现有 `nba_rules.py` / `tax_engine.py`
**互补、不重叠**：

| 关注点 | 模块 | 说明 |
| --- | --- | --- |
| 交易 leg 校验（apron / cap / tax 规则引擎） | `nba_rules.py` (`NBARuleSet`) | 作用于 `PlayerAsset` / `LeagueSalaryRules` |
| Cap impact / tax bill 评估 | `tax_engine.py` (`CapImpact`) | |
| **Bird Rights cap hold** | **`cba_aux.py`** | 自由球员 cap hold 倍乘数（Full Bird 1.50x / Early Bird 1.25x / Non-Bird 1.20x），现有 `trade_engine` 未实现 |
| **Player max salary %** | **`cba_aux.py`** | 按 yos + All-NBA 决定顶薪比例（25% / 30% / 35%），现有 `trade_engine` 未实现 |
| **多队 League 模拟** | **`cba_aux.py`** | `LeagueSimulator` + JSON 持久化，现有 `trade_engine` 只管 trade leg |

本模块是**纯算法层**：

- 零 SQL、零 DB 写、零外部依赖（仅 Python stdlib: `json` / `dataclasses` / `typing` / `copy`）
- 不 import `backend.core.db`、不调用 `db.batch_query`、不写任何 SQL 子串
- 全部金额仍用 `int`（美元整数），与 `trade_engine` 整体一致

## 公共 API

```python
from backend.services.trade_engine.cba_aux import (
    SalaryCapRules,   # 2026-2027 赛季预估薪资规则（base_cap / luxury / apron / min_team_salary）
    Player,           # 球员基础信息 + Bird Rights 归属 + 顶薪档位判定
    Team,             # 球队：roster + cap_holds + repeat_payer 标记
    TradeSimulator,   # 两队交易模拟器（apron 校验 + 执行）
    LeagueSimulator,  # 多队赛季模拟器 + JSON 持久化
)
```

或通过包级导入：

```python
from backend.services.trade_engine import (
    cba_aux,
    SalaryCapRules,
    Player,
    Team,
    TradeSimulator,
    LeagueSimulator,
)
```

### 关键方法

- `SalaryCapRules(base_cap=168_000_000, ...)` — 缺省派生 `luxury_tax_line / first_apron / second_apron / min_team_salary`
- `Player.get_max_salary_pct()` — 返回 `0.25 / 0.30 / 0.35`
- `Team.get_cap_hold(player)` — 返回 `int(player.salary * {1.50, 1.25, 1.20})`
- `Team.add_player(player)` / `renounce_bird_rights(name)` / `to_dict()` / `from_dict()`
- `TradeSimulator.can_trade(team, rules, outgoing, incoming)` / `execute_trade(team_a, team_b, ...)`
- `LeagueSimulator.add_team(team)` / `season_summary()` / `save_league(path)` / `load_league(path)`

## 典型用法

### 1. 离线分析 CLI

```bash
python -m backend.services.trade_engine.cba_aux
```

输出示例（Warriors ↔ Lakers 交易模拟 + 联盟总结 + JSON 保存/加载）：

```
--- 交易模拟 ---
✅ 交易完成!Golden State Warriors ↔ Los Angeles Lakers

============================================================
🏀 2026-2027 NBA 赛季薪资总结
============================================================
Golden State Warriors   | 薪资 $ 79,000,000 | 健康
Los Angeles Lakers     | 薪资 $105,000,000 | 健康
💾 联盟数据已保存至 nba_league_2026.json
📂 已加载联盟存档 nba_league_2026.json
```

### 2. 程序化使用

```python
from backend.services.trade_engine.cba_aux import (
    LeagueSimulator, Team, Player, TradeSimulator, SalaryCapRules,
)

sim = LeagueSimulator()
gsw = Team("Golden State Warriors")
gsw.add_player(Player("Stephen Curry", 62_000_000, 17, True, 2))
sim.add_team(gsw)

# 顶薪档位
print(gsw.roster["Stephen Curry"].get_max_salary_pct())  # 0.35

# Bird cap hold
print(gsw.get_cap_hold(gsw.roster["Stephen Curry"]))  # 93000000

# 持久化
sim.save_league("out.json")
restored = LeagueSimulator.load_league("out.json")
```

## 与 `trade_engine` 现有模块的关系

- **不**修改 `nba_rules.py` / `tax_engine.py` / `match_engine.py` 等任何现有文件
- **不**引入新的 DB 写路径；本模块只做计算 + 内存对象 / 文件 JSON
- 通过 `trade_engine/__init__.py` 暴露 5 个公共类与 `cba_aux` 子模块名（保留全部既有导出，**未删除任何条目**）
- 测试位于 `backend/services/trade_engine/tests/test_cba_aux.py`，14 个用例覆盖默认值推导、顶薪档位、Bird cap hold、TradeSimulator 三分支、LeagueSimulator 往返

## 质量门槛

- `cba_aux.py` 全文 grep 无 SQL 子串（`SELECT ` / `INSERT ` / `UPDATE ` / `DELETE ` / `CREATE `）
- `cba_aux.py` 不 import 任何 DB 模块
- `pytest backend/services/trade_engine/tests/test_cba_aux.py` 14/14 通过
- `pytest backend/services/trade_engine/tests/` 全量回归无新增失败

## DB 接入（cba_aux_db.py）

`cba_aux` 原本只能手工构造示例对象；新增薄适配层 `cba_aux_db.py` 把它从**真实 DB**
构造出来。该层纯读取、零 SQL 子串、零写、不 import 任何 router（v8 §6 合规）。

> 注：所有 SELECT 只存在于 `trade_engine/db.py`（经 `core.db.batch_query` 参数化）。
> `cba_aux_db.py` 仅调用 `db.py` 的封装函数并做对象映射，本身不含任何 SQL。

### 5 个 load_* 函数与对应表

| 函数 | 返回 | 数据源（db.py 封装） | 关键映射 |
| --- | --- | --- | --- |
| `load_salary_rules(season='2025-26')` | `SalaryCapRules` | `db.load_rules` ← `league_salary_rules` | `base_cap=salary_cap`；**覆盖** luxury_tax_line/first_apron/second_apron/min_team_salary 为 DB 实测值（DB 权威，不用公式推） |
| `load_player(team_abbr, player_name, season)` | `Optional[Player]` | `db.get_team_player_rows` ← `player_contracts` | `salary=salary_{prefix}`（prefix=`season_to_prefix`）；`yos=max(0, age-19)`（入行约 19 岁，启发式）；`is_all_nba=False`（库无此字段，已知近似） |
| `load_team(team_abbr, season)` | `Team` | `db.get_team_player_rows` + `db.load_team_payrolls` ← `player_contracts` / `team_payroll` | 逐个 `add_player`；`team.payroll = total_{prefix}`（Team 无 payroll 属性，直接挂实例属性，未改 cba_aux） |
| `load_trades(team_abbr=None, season=None)` | `List[TradeRecord]` | `db.get_trades` ← `transactions`（`transaction_type='Traded'`） | `TradeRecord(date, team_abbr, description, counterparties)`；`counterparties` 由白名单（team_payroll 的 team_abbr/team_name）从 description 抽已知球队缩写（全名词边界 + 3 字母缩写兜底），**不做球员级 NLP** |
| `load_league(season='2025-26')` | `LeagueSimulator` | 遍历 `db.get_team_directory`（team_payroll 30 队） | 逐个 `load_team` 后 `sim.add_team` |

### 测试

`backend/services/trade_engine/tests/test_cba_aux_db.py`（真实 DB，7 用例）：
`load_salary_rules` 阈值核对、`load_team('GSW')` payroll 核对、`load_player('GSW','Stephen Curry')`
salary/yos 核对、`load_trades` 非空 + 多队抽取 + BOS 过滤、`load_league` 30 队、以及
§6 自检（cba_aux_db.py 与本测试文件均零 SQL 子串）。

### 已知近似 / 偏离

- `Player.yos` 用 `age-19` 启发式，非真实资历。
- `Player.is_all_nba`：DB 无此字段，统一 `False`。
- `counterparties` 仅白名单级抽取（description 多用全名，如 "Orlando Magic"）；未做球员级解析。
- `player_contracts_league`（联盟级，537 行）本次未接入，留作备用。`load_trades` 的 `season`
  参数保留仅为 API 对称（transactions 表无 season 列，不用于过滤）。
- `cba_aux.py` 未做任何改动（`Team.payroll` 通过附加实例属性实现，无需改原类）。
