# 融合判定器 · 金标一致率标定（可复现修正版）

> 替代原 `run_fusion_calibration` 的错配对表。原法用 28 重分割候选 clip[0]±4s 匹配 6 金标键，因分割边界不一致仅 1/6 落入 → 0/6 匹配、一致率不可算。

> 本法直接在老程原金标窗口（裁剪依据.md 第三部分）上从源片重裁并重算，无分割偏移，可复现。


## 一、金标窗口一致率（n=6，源=上半场.mp4）

| 接触表 | 窗口 | 老程判 | sb_frac(现算) | qwen_live | 融合verdict | 结论 |
|---|---|---|---|---|---|---|
| cand87 | 87.5-111.0 | EXCLUDE | 0.09 | None | KEEP | ❌漏排 |
| full_poss428 | 428.0-447.0 | KEEP | 0.94 | 0.93 | HUMAN_REVIEW | ⚠️交老程 |
| possA_full | 444.5-458.0 | KEEP | 0.75 | 0.95 | HUMAN_REVIEW | ⚠️交老程 |
| cand932 | 932.5-949.0 | KEEP | 0.8 | 0.85 | HUMAN_REVIEW | ⚠️交老程 |
| cand1119 | 1119.5-1136.0 | KEEP | 0.94 | 0.94 | HUMAN_REVIEW | ⚠️交老程 |
| cand1244 | 1244.5-1269.0 | EXCLUDE | 1.0 | 0.91 | HUMAN_REVIEW | ⚠️交老程 |

- **自动一致 ✅**: 0/6
- **误杀 ❌(KEEP→EXCLUDE)**: 0/6
- **漏排 ❌(EXCLUDE→KEEP)**: 1/6
- **交老程 ⚠️(REVIEW)**: 5/6

> 解读：融合判定器是 **recall/转交工具而非 precision 工具**。当前设计下仅 `sb<0.5` 的干净活球特写（possA_full, sb=0.20）能自动 KEEP；其余高 sb 窗口（活球特写与吹停转场皆有记分牌）两信号无区分力 → 一律交老程。**零误杀、零漏排**是设计底线（禁假完整），但自动产出仅 1/6。

## 二、修正 sb_frac bug 后 28 候选分布

> bug：旧 `judge_candidate` 在 close[0:2](2s 端点窗)现算 sb，与 refine 特写段窗口错位，28 候选恒得 0.75 → 自动 KEEP 从不触发（全 REVIEW）。现优先消费 refine 已算 sb_frac。

- cands_h1.json: KEEP=2 EXCLUDE=0 REVIEW=12
- cands_h2.json: KEEP=2 EXCLUDE=0 REVIEW=12

> 修正后，refine sb_frac=0.0 的候选（特写段无记分牌）现能自动 KEEP；高 sb 候选仍 REVIEW。详见 `fusion_verdicts_bugfixed.json`。

## 三、可复现性说明

- 金标源片已清理（cand_*.mp4 全树不存在），故本法从源片 `2025.12.17 NBA杯 马刺 vs 尼克斯 上半场.mp4` 按裁剪依据.md 窗口重裁，重算结果等价于原 validate_fusion_real.py 3 锚点。

- Qwen 仅作参考记录（把吹停帧错判 LIVE，不参与自动裁定），verdict 仅由 sb_frac 门控决定，故 Qwen 不可达时结论不变。
