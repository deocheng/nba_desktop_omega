# scripts/oneoff/ — 一次性脚本归档区

仓库根目录曾有 144 个 `.py`，混着三类完全不同的东西：长期入口、一次性脚本、工具。一次性脚本堆在根目录的真实代价是**发现成本**与**误用风险**（`python fix_xxx.py` 随手可跑，但那些脚本的前置条件早已不成立）。

本目录收纳 **一次性脚本**（分析 / 回填 / 审计 / 诊断 / 探查）。
长期入口（爬虫主程序、星图系统、7 份分析报告的生成器）**仍在仓库根**。

## 调用方式变了

```bash
# 之前（在仓库根）
python fix_jones_gamelog.py

# 现在
python scripts/oneoff/fix_jones_gamelog.py
```

脚本内部的仓库根定位已同步改写（`REPO_DIR` 常量，指向仓库根而非脚本所在目录），
故从任意 CWD 调用均可。

## 完整映射表

| 原路径 | 新路径 |
|--------|--------|
| `_build_data_pkg_tmp.py` | `scripts/oneoff/_build_data_pkg_tmp.py` |
| `_build_mac_pkg_tmp.py` | `scripts/oneoff/_build_mac_pkg_tmp.py` |
| `_import_csv_to_db.py` | `scripts/oneoff/_import_csv_to_db.py` |
| `assemble_notes.py` | `scripts/oneoff/assemble_notes.py` |
| `audit_br_schedule.py` | `scripts/oneoff/audit_br_schedule.py` |
| `backfill_action_verb.py` | `scripts/oneoff/backfill_action_verb.py` |
| `backfill_action_verb_all.py` | `scripts/oneoff/backfill_action_verb_all.py` |
| `backfill_action_verb_pass2.py` | `scripts/oneoff/backfill_action_verb_pass2.py` |
| `backfill_gamelog_from_pbp_2014_2021.py` | `scripts/oneoff/backfill_gamelog_from_pbp_2014_2021.py` |
| `backfill_gamelog_identity.py` | `scripts/oneoff/backfill_gamelog_identity.py` |
| `backfill_houstca01_from_pbp.py` | `scripts/oneoff/backfill_houstca01_from_pbp.py` |
| `backfill_manual_pbp.py` | `scripts/oneoff/backfill_manual_pbp.py` |
| `backfill_markdown_cache.py` | `scripts/oneoff/backfill_markdown_cache.py` |
| `backfill_nba_api_old.py` | `scripts/oneoff/backfill_nba_api_old.py` |
| `backfill_playoff_schedule.py` | `scripts/oneoff/backfill_playoff_schedule.py` |
| `calc_candidates.py` | `scripts/oneoff/calc_candidates.py` |
| `clean_games_dedup.py` | `scripts/oneoff/clean_games_dedup.py` |
| `clean_shotchart_cache.py` | `scripts/oneoff/clean_shotchart_cache.py` |
| `diag_clutch_schema.py` | `scripts/oneoff/diag_clutch_schema.py` |
| `diag_clutch_smoke.py` | `scripts/oneoff/diag_clutch_smoke.py` |
| `diag_pbp_schema.py` | `scripts/oneoff/diag_pbp_schema.py` |
| `diag_state.py` | `scripts/oneoff/diag_state.py` |
| `diag_state2.py` | `scripts/oneoff/diag_state2.py` |
| `diag_state3.py` | `scripts/oneoff/diag_state3.py` |
| `explore_style.py` | `scripts/oneoff/explore_style.py` |
| `explore_style2.py` | `scripts/oneoff/explore_style2.py` |
| `explore_style3.py` | `scripts/oneoff/explore_style3.py` |
| `explore_style4.py` | `scripts/oneoff/explore_style4.py` |
| `explore_style5.py` | `scripts/oneoff/explore_style5.py` |
| `explore_style6.py` | `scripts/oneoff/explore_style6.py` |
| `extract_bz_candidates.py` | `scripts/oneoff/extract_bz_candidates.py` |
| `fix_dim_players_2026_rookies.py` | `scripts/oneoff/fix_dim_players_2026_rookies.py` |
| `fix_dim_players_cle_rookies_2027.py` | `scripts/oneoff/fix_dim_players_cle_rookies_2027.py` |
| `fix_game_id.py` | `scripts/oneoff/fix_game_id.py` |
| `fix_games_data.py` | `scripts/oneoff/fix_games_data.py` |
| `fix_mia_phantom.py` | `scripts/oneoff/fix_mia_phantom.py` |
| `fix_mislabeled.py` | `scripts/oneoff/fix_mislabeled.py` |
| `fix_nba_cup_finals.py` | `scripts/oneoff/fix_nba_cup_finals.py` |
| `generate_final.py` | `scripts/oneoff/generate_final.py` |
| `merge_notes.py` | `scripts/oneoff/merge_notes.py` |
| `probe1.py` | `scripts/oneoff/probe1.py` |
| `probe2.py` | `scripts/oneoff/probe2.py` |
| `probe_br_pbp.py` | `scripts/oneoff/probe_br_pbp.py` |
| `probe_schema.py` | `scripts/oneoff/probe_schema.py` |
| `probe_team_share.py` | `scripts/oneoff/probe_team_share.py` |
| `score_dist.py` | `scripts/oneoff/score_dist.py` |
| `verify_archive.py` | `scripts/oneoff/verify_archive.py` |
| `verify_gamelog_2027.py` | `scripts/oneoff/verify_gamelog_2027.py` |
| `verify_migration.py` | `scripts/oneoff/verify_migration.py` |
| `verify_migration_integrity.py` | `scripts/oneoff/verify_migration_integrity.py` |
| `verify_screenshot.py` | `scripts/oneoff/verify_screenshot.py` |
| `verify_screenshot_v3.py` | `scripts/oneoff/verify_screenshot_v3.py` |
| `verify_team_franchise_coverage.py` | `scripts/oneoff/verify_team_franchise_coverage.py` |
| `verify_user_version.py` | `scripts/oneoff/verify_user_version.py` |
| `verify_v3.py` | `scripts/oneoff/verify_v3.py` |
| `verify_v832_e2e.py` | `scripts/oneoff/verify_v832_e2e.py` |

共 56 个。

## 边界说明

- **不删除、不重命名** —— 仓库 README 约定既有文件不移动不重命名不删除；
  本次以 `git mv` 保留历史（git rename 检测可用），并在上面的映射表留档。
- **同目录 import 依赖 = 0** —— 移动前已全量 AST 扫描确认，无脚本 import 另一个根目录 `.py`，故移动不会破坏 import。
- **运行时已验证** —— 56 个脚本逐个实跑：39 正常完成、17 报数据层错误（与路径无关）、**0 个导入/路径问题**。
