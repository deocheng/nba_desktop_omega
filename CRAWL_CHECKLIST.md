# NBA 爬虫爬取清单 (Crawl Checklist)

> 生成时间：2026-08-09 ｜ 数据均来自实时 DB 审计（非凭记忆）
> 主爬取管线：`player_gamelog`（看门狗 + driver，逐季 `verify_gaps` 自检补齐）
> 图例：✅ 完整(verify_gaps rc=0) ｜ 🟡 比赛100%覆盖但个别 BR-500 球员缺口(PBP回填) ｜ 🔴 缺失(爬取中/待爬) ｜ ⬜ 未爬(表空/脚本未跑) ｜ 🚫 无独立表

---

## 1. player game log — `player_gamelog`（看门狗编排，1980–2026 共 47 季）

| 状态 | 赛季 |
|------|------|
| ✅ 完整 | 2026 2025 2024 2023 2022 |
| 🟡 PBP回填 | 2021 2020 2019 2018 2017 2016 2015 2014 |
| 🔴 爬取中→待爬 | 2013 2012 2011 2010 2009 2008 2007 2006 2005 2004 2003 2002 2001 2000 1999 1998 1997 1996 1995 1994 1993 1992 1991 1990 1989 1988 1987 1986 1985 1984 1983 1982 1981 1980 |

- **看门狗当前目标**：2013 → 1980（34 季，倒序，每季自检补齐）
- **已注释/跳过（STATE + FAILURES，不重爬）**：
  ```
  # STATE (完整): 2022 2023 2024 2025 2026
  # FAILURES (BR-500缺口, 走PBP回填): 2014 2015 2016 2017 2018 2019 2020 2021
  ```
- 1947–1979：不在看门狗范围（老数据零散在库，未纳入本轮）

启动命令：
```bash
cd /Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/external_crawler/crawler
bash start_watchdog_detached.sh          # 常驻续爬（run_in_background 包裹）
bash crawler_watchdog.sh status          # 查状态
bash crawler_watchdog.sh stop            # 停止（下轮退出）
```

---

## 2. player lineup — `player_lineups`
- 🟡 在库 1997–2026（30 季），未逐季校验
- 启动：`python3 crawl_br_player_lineup.py`

## 3. team lineup — `team_lineups`
- 🟡 在库 1997–2026（30 季）
- 启动：`python3 crawl_br_team_lineups.py`

## 4. starting lineups — `starting_lineups`
- ⬜ 仅 2025、2026；其余季缺失
- 启动：`python3 crawl_br_team_lineups.py --starting`（待确认参数）

## 5. player shooting — `player_shooting`
- 🟡 在库 1997–2026（30 季）
- 启动：`python3 crawl_br_player_shooting.py`

## 6. team shooting — `team_shooting`
- ⬜ **0 行，从未爬取**
- 启动：`python3 crawl_br_team_shooting.py`（需先确认脚本/源站可用性）

## 7. player shot chart — `player_shot_chart`
- 🟡 在库 1997–2026（30 季，约 6M 行）
- 启动：`python3 crawl_br_player_shot_chart.py`

## 8. player on/off — `player_onoff`
- 🟡 在库 1997–2026（30 季）
- 启动：`python3 crawl_br_player_onoff.py`

## 9. team on/off — `team_on_off`
- 🟡 在库 1997–2026（30 季）
- 启动：`python3 crawl_br_team_onoff.py`

## 10. player splits — `player_season_splits`
- 🟡 在库 2001–2026（26 季）
- 启动：`python3 crawl_br_player_page_extras.py`

## 11. team splits — `team_game_splits`
- ⬜ 仅 2020、2021、2026
- 启动：`python3 crawl_br_team_page_extras.py`

---

## 未实现的 2 个域（原 8 域清单中的 "team game log" 与 "+/-"）
- 🚫 **team game log**：无独立表；可由 `team_pbp_raw` 派生
- 🚫 **+/-**：无 `plus_minus` 表；为派生指标（由 PBP / on-off 计算）

---

## 待办（非看门狗自动范围，需手动触发）
1. 🟡→✅ **PBP 回填** 2014–2021 的 BR-500 缺口球员（`play_by_play` 覆盖 1997–2026）
2. ⬜ **team_shooting / starting_lineups / team_game_splits** 单独跑脚本补齐
3. 看门狗撞 CF 墙熔断时：刷新 `cf_clearance` 后重跑 `start_watchdog_detached.sh`
