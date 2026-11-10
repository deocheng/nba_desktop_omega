# reports/INDEX.md — 产物清单（人类可读）

> 基准：所有 `path` 相对 `R = /Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13`。
> W 产物经 `workspace/workbuddy-scripts` 软链、P 产物经 `reports/nba-analysis` 软链登记。
> 字节数从磁盘实读，结构化版本见 `manifest.json`（由 `build_manifest.py` 生成）。
> **只登记、不移动、不删除**任何既有产物。

## 1. analysis_*.html — 9 份（7 份已剥离内联 plotly bundle + 2 份轻量）

7 份原各约 4.9MB（内联 plotly bundle），**已由 impl-plotly-vendor 完成剥离**：
**瘦身后为权威版本，剥离前的 7 份原始备份在 `reports/_pre_strip_backup/`（合计 34,534,130 字节，完好）**。
下表「实测字节（瘦身后）」为剥离后磁盘真实值，与 `manifest.json` 一致
（`build_manifest.py` 可复现实读）；「剥离前字节」保留历史体积以便追溯。

| 产物 | 实测字节（瘦身后） | 剥离前字节 | generator | status |
| --- | --- | --- | --- | --- |
| `analysis_duo_density.html` | 35,789 | 4,886,917 | `build_duo_density.py` | authoritative |
| `analysis_duos_trios.html` | 32,895 | 4,884,023 | `build_duos_trios.py` | authoritative |
| `analysis_longterm_scatter.html` | 55,270 | 4,906,398 | `build_longterm_scatter.py` | authoritative |
| `analysis_player_coaches.html` | 56,345 | 4,907,473 | `build_player_coaches.py` | authoritative |
| `analysis_salary_share.html` | 43,266 | 4,894,394 | `build_salary_share.py` | authoritative |
| `analysis_trio_density.html` | 37,085 | 4,888,213 | `build_trio_density.py` | authoritative |
| `analysis_trio_scatter.html` | 315,584 | 5,166,712 | `build_trio_scatter.py` | authoritative |

另 2 份不含内联 plotly bundle，未参与剥离，同样为当前权威版本：

| 产物 | 实测字节 | generator | status |
| --- | --- | --- | --- |
| `analysis_allstar_scatter.html` | 26,891 | `build_allstar_scatter.py` | authoritative |
| `analysis_nicknames.html` | 946,215 | `build_nicknames.py` | authoritative |

## 2. star_rings_2026/ — 30 份队别星环图

`star_rings_2026/` 下每队一张（ATL BOS BRK CHI CHO CLE DAL DEN DET GSW HOU IND
LAC LAL MEM MIA MIL MIN NOP NYK OKC ORL PHI PHO POR SAC SAS TOR UTA WAS），
**视为该队权威版本**，`generator = team_shot_radial.py`
（`star_*.py` 为其等价包装，输出路径由 CLI 参数给定）。

- 实测 30 份，单份 14,682 – 131,459 字节；
  样例 `star_rings_2026/CLE_2026.html` 62,559、`star_rings_2026/DAL_2026.html` 131,459。

## 3. 根级 12 份 star_ring_*.html（6 权威 + 6 logo 变体）

| 产物 | 字节 | status | 说明 |
| --- | --- | --- | --- |
| `star_ring_CLE_2026.html` | 74,036 | authoritative | 普通版 |
| `star_ring_CLE_2026_logo.html` | 229,642 | variant | logo 版，约 3.1× |
| `star_ring_DET_2026.html` | 96,180 | authoritative | 普通版 |
| `star_ring_DET_2026_logo.html` | 385,414 | variant | 约 4.0× |
| `star_ring_HOU_2026.html` | 84,559 | authoritative | 普通版 |
| `star_ring_HOU_2026_logo.html` | 220,934 | variant | 约 2.6× |
| `star_ring_LAL_2026.html` | 100,080 | authoritative | 普通版 |
| `star_ring_LAL_2026_logo.html` | 348,682 | variant | 约 3.5× |
| `star_ring_OKC_2026.html` | 104,388 | authoritative | 普通版 |
| `star_ring_OKC_2026_logo.html` | 406,298 | variant | 约 3.9× |
| `star_ring_SAS_2026.html` | 92,201 | authoritative | 普通版 |
| `star_ring_SAS_2026_logo.html` | 249,311 | variant | 约 2.7× |

`*_logo.html` 因内嵌 **base64 头像 / 队标**，体积为对应普通版的 **2–4 倍**，
属**呈现变体**（`generator = star_logo.py`），不覆盖权威版。

## 4. team_shot_radial* — 9 份（1 主版本 + 8 历史快照）

| 产物 | 字节 | status |
| --- | --- | --- |
| `team_shot_radial.html` | 385,414 | authoritative（当前主版本） |
| `team_shot_radial_5.html` | 21,479 | snapshot |
| `team_shot_radial_6.html` | 24,565 | snapshot |
| `team_shot_radial_7.html` | 27,616 | snapshot |
| `team_shot_radial_215504.html` | 21,937 | snapshot |
| `team_shot_radial_215729.html` | 21,937 | snapshot |
| `team_shot_radial_222205.html` | 21,940 | snapshot |
| `team_shot_radial_223108.html` | 21,940 | snapshot |
| `team_shot_radial_223153.html` | 25,061 | snapshot |

数字 / 时间戳后缀（含 `team_shot_radial_215504` 等）为一次性导出：
**历史快照，非权威，勿删除**，仅作历史追溯。
`generator = team_shot_radial.py`（`screenshot_team_shot_radial.py` 负责截图导出）。

## 5. 孤儿产物（全库搜不到生成脚本）

| 产物 | 实测字节 | status | 说明 |
| --- | --- | --- | --- |
| `workspace/workbuddy-scripts/nba_game_results.html` | 5,282,656（≈5.28MB） | orphan | 找不到生成脚本 |
| `debug_sas_2026.html` | 1,605,358（≈1.6MB） | orphan | 诊断产物，找不到生成脚本 |
| `wemby_chart_composition.png` | 51,335 | orphan | 文班亚马图表 |
| `wemby_chart_efficiency.png` | 49,715 | orphan | 文班亚马图表 |
| `wemby_chart_trend.png` | 101,380 | orphan | 文班亚马图表 |
| `workspace/workbuddy-scripts/crawler_code_review_20260816.html` | 18,185 | document | 文档类代码评审，孤儿但可接受 |

处理原则：**只登记不删除**（见 `README.md`）。`generator = null`。

## 6. 生成脚本 → 产物配对表

| 生成脚本 | 产物 | 说明 |
| --- | --- | --- |
| `build_duo_density.py` / `build_duos_trios.py` / `build_longterm_scatter.py` / `build_player_coaches.py` / `build_salary_share.py` / `build_trio_density.py` / `build_trio_scatter.py` / `build_allstar_scatter.py` / `build_nicknames.py` | 同名 `analysis_*.html` | `OUT = os.path.join(BASE, "analysis_*.html")` 常量写死；写内联 plotly |
| `team_shot_radial.py` | `team_shot_radial.html`、`star_ring_*.html`、`star_rings_2026/*.html` | 核心生成器，输出路径由 CLI 参数给定 |
| `star_grid.py` / `star_heatmap.py` / `star_logo.py` / `star_portrait.py` | 同上（grid / heatmap / logo / portrait 四种模式） | `team_shot_radial.py` 的等价包装；`star_logo.py` 产出 `_logo.html` 变体 |
| `screenshot_team_shot_radial.py` | `team_shot_radial_*` 快照 / 截图 | 一次性截图导出 |
| `scan_videos.py` | `video_index.json` | 录像索引（不产出 HTML） |
| `workspace/workbuddy-scripts/nba_2026_report.py` | `workspace/workbuddy-scripts/nba_2026_season_report.html` | W 侧前瞻报告 |
| `workspace/workbuddy-scripts/nba_backtest_report.py` | `workspace/workbuddy-scripts/nba_backtest_report.html` | W 侧回测报告 |
| `workspace/workbuddy-scripts/nba_2027_round1_report.py` | `workspace/workbuddy-scripts/nba_2027_round1_report.html` | W 侧首轮报告 |
| `reports/nba-analysis/nba_report.py` / `batch_report.py` / `nba_metrics.py` | `reports/nba-analysis/season_report_*.html`、`champ_*.html/svg`、`pace_*` 等 | P 仓外批量产物（经软链） |

## 7. P 仓外产物（经 `reports/nba-analysis` 软链收敛）

`R/reports/nba-analysis -> /Volumes/12T/NBA/nba_analysis`（绝对路径软链，只新增）。
P 顶层实测 94 个文件：45 html / 22 svg / 12 png / 3 py / 2 json / 4 txt / 6 备份后缀
（`.darkbak` / `.bugbak_20260825` / `.badbak_20260827`），含 `bot_reports/` 子目录合计约 96 份。

- 正式产物：`season_report_1997.html` … `season_report_2026.html`、`champ_*.html/svg`、
  `pace_*.png/svg`、`style_overview_*.png/svg` 等 → `status=authoritative`。
- 备份类：`pace_five_eras_2026.html.darkbak`、
  `team_style_evolution_1979_2026.html.bugbak_20260825` 等 → `status=snapshot`，**非权威，勿删除**。
- 3 个 py（`nba_report.py`、`batch_report.py`、`nba_metrics.py`）为生成器，不是报告产物。
- `manifest.json` 登记代表性条目；P 全量逐文件清单不在本 manifest 逐条展开，
  均经软链原样保留、未移动未删除。

## 8. 结构化清单

`manifest.json` 每条含：`path`（相对 R 根的逻辑路径）、`generator`（无则 null）、
`status`（authoritative / variant / snapshot / orphan / document）、
`bytes`（磁盘实读）、`note`。
由 `python reports/build_manifest.py` 生成，可 `json.load` 校验。
