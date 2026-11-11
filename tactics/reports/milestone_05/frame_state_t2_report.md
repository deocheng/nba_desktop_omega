# T2 验收报告 — sas_det 逐帧状态表（比赛钟 × PBP 对齐）

日期：2026-09-26 · 产出：`action_work/validate/sas_det_frame_states.json`（400 帧）
代码：`engine/frame_state_table.py`（DB 只读，零写）

## 0. 结论

**T2 验收通过**。400 帧逐帧状态 `{display_clock, remaining_est, live_state, possession,
pending_events, last_confirmed, score_confirmed}` 落盘；7/7 窗口内 PBP 事件与解码钟显示
窗口对齐；活/死球由「PBP 状态机 + 钟显示窗口宽度」双证据链判定；4 处关键落点视觉抽查
全部一致。

## 1. 帧 → 比赛时间映射

- `t(f) = 60.04 + (f−1)/10`（f00001=视频 60.04s，DELTA=1 铁律）。
- `remaining(f) = C − t(f)`，**C=761.49s**（多数派区间 [761.44, 761.54)，37 变点中 35 支持；
  即 Q1 开球在视频 t≈41.49s，与 f1=11:41 一致）。
- 🔴 **显示端 1-tick 抖动（实测沉淀）**：f127(→28)、f217(→19) 两个变点晚 1 帧——台标
  图形引擎偶发更新延迟，特征是「该窗 11 帧 + 相邻窗 9 帧」（走表速率守恒）。逐帧级
  est-vs-解码不一致 27/400 帧 = 走表期抖动 2 帧（f126/f216）+ 死球冻结段 25 帧
  （f376-400，公式不适用=物理预期，非错误）。

## 2. 活/死球判定（双证据链）

1. **PBP 状态机**：哨响事件（Foul/Violation/Timeout/Instant Replay）开死球，至下一活球
   动作（Made/Missed Shot/Rebound/Turnover/Jump Ball）恢复。⚠️ v1 简化：Jump Ball 视为
   活球开始（tip 后立即活——实证 f1-f5 比赛进行中）。
2. **窗口宽度物理证据**（独立于 PBP）：同一 display 值连续帧数正常 ~10 帧（1s@10fps）；
   **frozen ⟺ excess=w−10 > 相邻窗亏损 (10−prev)+(10−next)**。该判据天然区分：
   - 抖动窗（11:29 窗 11 帧、11:20 窗 11 帧，邻窗 9 帧互补）→ 不误报；
   - 真死球窗（11:04 窗 **35 帧**，excess 25 > deficit 0）→ dead。
3. **秒内歧义如实分列**：NBA PBP 1s 粒度，事件 cs=v ↔ 发生在显示秒 v 的 10 帧内。
   confirmed（cs≥display+1，确定已发生）/ pending（cs==display，秒内歧义）分开。

## 3. 验收结果

| 关 | 项 | 结果 |
|---|---|---|
| A | 事件↔显示窗口对齐 | **7/7 OK**（turnover+Fox steal@700→帧窗 6-15；SAS 三分不中@678→226-235；Duren 篮板@675→256-265；Vassell 犯规+Harris 2FT@664→366-400） |
| B | 关键落点视觉抽查 | **4/4 一致**：f8 快攻转换（抢断后）✓；f232 SAS 跳投出手瞬间 ✓；f262 DET 转换推进 ✓；f390 **罚球列队已站好但台标比分仍 0-0** ✓ |
| C | 比分自洽 | 确认口径全程 0-0；Harris 两罚（→DET 2-0）在 pending——**f390 画面比分 0-0 直接佐证** PBP 把 FT 记在钟停秒而实际执行更晚 |
| — | 活/死球 | live 365 帧（f1-f365）/ dead 35 帧（f366-f400，双证据：钟冻结 + Foul） |

## 4. 对 T3a 的输入

- **死球段**：f366-f400 → 死球否决（球位语义=罚球线/底线，无战术含义）。
- **遮挡帧归属**：f00025/91/103（老程标注的球被挡帧）落在 Fox 抢断快攻活球段
  （SAS possession, f6-f235）——T3a 可给「活球遮挡」语义标记。
- **FP 簇**：人脸特写簇 00225-00253 落在三分不中→篮板段（转播切近景）——与 A4.26
  逐帧印证一致；T3a 可用「近景特写=无战术球位」规则。
- shot clock 读取器未做（T2 规格未要求）；后续需按新几何重定标（shot 盒 ~x895 起，
  红盒/透明底两形态）。

## 5. 产物

- `action_work/validate/sas_det_frame_states.json` — 400 帧状态表 + meta（C 拟合/抖动清单）+ acceptance
- `action_work/validate/sas_det_t2_spotcheck.png` — 4 处关键落点视觉抽查拼图
- `engine/frame_state_table.py` — 生成器（DB 只读）
