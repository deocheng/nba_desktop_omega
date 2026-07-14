# A1-3 数据质量校正 — QA 验收报告

**任务**：NBACore Studio v8 #8 收尾 · 团队 software-dq-a13 · 验收工程师产出（IS_PASS: YES）
**验收人**：严过关（QA Engineer）
**日期**：2026-07-12
**环境**：PG localhost:5433 db=nba；`.venv/Scripts/python.exe`

---

## 验收结论：✅ 通过（PASS），无遗留问题

交付物（两份均为新文件，未提交）：
- `backend/data_layer/draft_quality.py`（含 `apply_corrections` 的 `IS DISTINCT FROM` 守卫 + 新增 `clear_corrections_by_status`）
- `scripts/draft_a1_apply_exists_match.py`（默认 dry-run，`--execute` 才写）

---

## 四项验收点结果

| # | 验收点 | 结果 | 证据 |
|---|---------|------|------|
| 1 | 94 条 exists_match 无需改写 | ✅ | `wrong_id==correct_id` 94/94；`correct_id ∈ dim_draft_history.player_id` 94/94；`correct_id ∈ dim_players` 94/94 |
| 2 | dim_draft_history 未变更（真·no-op） | ✅ | 行数 8446 = 快照 8446；**行级 EXCEPT 差异 = 0**；263 个 mismatch id 当前值与快照一致 |
| 3 | §6 合规（无动态 SQL） | ✅ | `draft_quality.py` 所有标识符经 `psql.Identifier` 绑定、值经 `%s`；`clear_corrections_by_status` 参数化（`DELETE FROM {tbl} WHERE status = %s`）；脚本自身**零内联 SQL**，全委托 `draft_quality.*` |
| 4 | 端到端 apply_corrections 为 true no-op | ✅ | dry-run `planned=0`；execute `updated=0`；表仍 8446 未变 |

---

## 测试执行

新增验收单测 `tests/test_a1_3_acceptance.py`（7 例）+ 原有 `tests/test_a1_draft_quality.py`（5 例）：

```
collected 12 items
test_a1_3_acceptance.py::test_corrections_table_has_exactly_94_exists_match PASSED
test_a1_3_acceptance.py::test_exists_match_requires_no_rewrite PASSED
test_a1_3_acceptance.py::test_dim_draft_history_unchanged_vs_snapshot PASSED
test_a1_3_acceptance.py::test_mismatch_player_ids_unchanged_vs_snapshot PASSED
test_a1_3_acceptance.py::test_section6_no_dynamic_sql_in_source PASSED
test_a1_3_acceptance.py::test_apply_functions_bind_identifiers_via_sql PASSED
test_a1_3_acceptance.py::test_apply_corrections_is_true_noop PASSED
test_a1_draft_quality.py::test_snapshot_rejects_bad_date PASSED
test_a1_draft_quality.py::test_audit_returns_376 PASSED
test_a1_draft_quality.py::test_export_audit_csv_roundtrip PASSED
test_a1_draft_quality.py::test_apply_and_rollback_dry_run_noop PASSED
test_a1_draft_quality.py::test_audit_csv_exists_on_disk PASSED

============================= 12 passed in 1.10s =============================
```

> 测试过程记录：前两次失败均为**测试代码本身的误报**（§6 静态检查对脚本要求了 `psql.Identifier(` 出现，而脚本作为编排层本就不含内联 SQL；以及把 docstring 散文 "UPDATE path" 误判为 SQL）。属测试代码 bug，已自行修复，非源码问题。修复后 12/12 全绿。

---

## 不变式核查明细（来自实时 DB）

- `draft_pick_corrections`：94 行，94 个 distinct `wrong_id`，94 个 distinct `correct_id`，状态**仅 `exists_match`**（不含 263 mismatch / 19 skipped，符合预期）。
- `dim_draft_history`：8446 行 = 快照 `dim_draft_history_bak_20260712`（8446 行）。
- 行级 diff（`EXCEPT` 双向并集）：**0 行** → 0 行实际变更，未越界。
- CSV 去重计数与摘要一致：exists_match=94、mismatch=263、skipped=0（19 skipped 不在 CSV，亦未进入 corrections 表，符合"仅存 94 exists_match"的范围约束）。

## §6 合规结论

- `draft_quality.py`：`bak = f"{_BASE_TABLE}_bak_{date_str}"` 中 `date_str` 经 `^\d{8}$` 正则校验，`bak` 随后经 `psql.Identifier(bak)` 绑定且仅作为 `%s` 参数值传入 `to_regclass`，**无注入面**。其余所有 SQL 标识符均 `psql.Identifier` 绑定，值全部 `%s`。
- `clear_corrections_by_status(status)`：参数化 `DELETE FROM {tbl} WHERE status = %s`，`tbl` 绑定、`status` 绑定。
- `scripts/draft_a1_apply_exists_match.py`：自身**无任何 `psql.SQL(` / `cur.execute(` / 裸 SQL**，全部经由 `draft_quality` 指定写入层，符合 v8 §6 Layer-1 隔离。

---

## 路由判定：NoOne（全部通过）

源码无 bug，测试代码 bug 已自行修复。无需工程师返工，可收尾。
