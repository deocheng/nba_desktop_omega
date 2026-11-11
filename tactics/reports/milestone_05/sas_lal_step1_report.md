# A4.32 — 四步计划第 1 步：新片段选段 sas_lal + 快速真值标注包

日期：2026-09-26　状态：✅ 标注包就绪，待老程标注
前置：A4.31（第 3 步收尾）、用户总指挥令（换比赛优先，泛化 > 本场深挖；close 硬负样本必须进真值）

## 1. 选段（六候选探针目视对比）

| 候选 | 宽景/动作 | 特写/广告 | 台标 | 判定 |
|---|---|---|---|---|
| **SAS@LAL 03.18** | 5/8 | 3 | 完整 | **选定**（跨场地/跨转播泛化价值最高） |
| SAS@TOR 03.24 | 6/8 | 2 | 完整 | 备选（与 TOR 宽景同场，违背换比赛） |
| NYK@SAS | 5/8 | 3 | 完整 | 落选（SAS 主场同风格） |
| OKC@SAS / SAS@MEM / CHA@SAS | — | 4-5 含演播室/广告 | — | 落选 |

**锁定**：`2025.03/马刺vs湖人/03.18 马刺vs湖人 第二节.mp4` t=940–980s（winD 三窗口预览最优：
前 ~85% 连续直播攻防；winA 撞场边专题、winB 撞腾讯演播室、winC 进罚球、winE 伤停特写）。
抽帧 400 帧 @10fps 1080p → `action_work/sas_lal/`（f%05d 1-based，口径同 sas_det）。

## 2. HUMAN 头零样本迁移基线（`ball_cand_scores_sas_lal_human.json`）

候选池 `sas_lal_cands.json`：400 帧 97.0% 有候选、1507 候选（validate_clips.py tile+256px 复验，
`--vconf -1` 完整池口径）。

| th | 覆盖 | 可跟踪 | 步长 | 轨迹 |
|---|---|---|---|---|
| 0.3 | 25.8% | **84.9%** | 38.1 | 17 |
| 0.5 | 20.8% | 86.8% | 38.4 | 15 |
| 0.8 | 12.5% | 84.6% | 40.2 | 11 |

→ 可跟踪率零样本即过 80% 线（轨迹一致性可），**覆盖 25.8% vs sas_det 53.0% = 跨转播泛化缺口，
正是第 2 步联合训练的靶子**。v2 头同池 6.2%（与 sas_det 旧基线同型，对照证据）。

## 3. shot_type_filter v1.3（老程提议落地，`engine/shot_type_filter.py`）

🔴 **定位红线**：只用于训练/标注池策展与语义富集，**禁止**用作检测后处理救门禁数字
（A6「后处理过滤全家」封口死路不复活）。

校准/修正史（三轮目视验收，全部有接触表证据）：
- v1 绝对阈值 → **证伪**：跨转播不可迁移（w1 med_h p50=145 vs sas_det 225，机距系统性不同）；
- v1.1 max_h 相对判据 → **证伪**：前排观众/替补席大框污染（w1 全宽景被误判 56.6% close），
  而真特写帧检测缺框落 none；
- v1.2 n_players 单判据 → w1/sas_det 97.9%/31.8% wide 分离成功，但换 RF-DETR 框源后失效
  （全帧 384² 漏宽景小目标，w1/sas_det n 分布同为 p50≈10——A2 根因在球员检测侧重现）；
- **v1.3 定稿**：close = n≤4（含 n=0，真特写+缺框帧，交人工复核）；wide = n≥12 且 med_h≤0.85·H0
  （RF-DETR 源下实际为空——诚实记录）；half = 其余。

**交付语义 = 二分类 close/half**：sas_lal 26 close（6.5%）/374 half；close 行目视验证全部为真特写。

## 4. 标注包（80 帧，待老程标注）

- `action_work/validate/sas_lal_sheets/`：80 张三面板 sheet（70 均匀 stride=5 + 10 close 硬负样本）+
  `manifest.json`（frame→[{idx,bbox,conf1,conf2}]）。
- **向导**：`action_work/validate/sas_lal_sheets/label_sas_lal.html`（浏览器打开，点 #i=球 / 无球 / 跳过，
  进度 localStorage 防丢，导出 human_labels.json）。
- 协议与 sas_det 完全同构（`build_human_labeler.py`/`make_sas_det_sheet.py` 已参数化 --clip）。
- ⚠️ 沿用 sas_det 已知 caveats：候选云漏检帧（约 10%）无法经此协议标注为「有球」，仍靠 reviewer_notes 补。

## 5. 产物清单

| 文件 | 内容 |
|---|---|
| `action_work/sas_lal/` | 400 帧 @10fps |
| `action_work/validate/sas_lal_cands.json` / `sas_lal_scores.json` | tile+复验候选池 / v2 头基线 |
| `action_work/validate/ball_cand_scores_sas_lal_human.json` | HUMAN 头打分（run_ball_events --scores 可直读） |
| `action_work/sas_lal_players.json` | RF-DETR 球员/裁判框（过滤器输入） |
| `action_work/validate/sas_lal_shot_types.json` | v1.3 逐帧镜头类型 |
| `action_work/validate/sas_lal_sheets/label_sas_lal.html` | **老程标注向导（待办入口）** |
| `engine/shot_type_filter.py` / `engine/detect_players_rfdetr.py` / `engine/rescore_clip_heads.py` | 新工具（均已参数化） |

## 6. 下一步

1. **老程标注 80 帧** → 导出 human_labels.json → `human_label_to_bank.py` 转 bank；
2. 第 2 步联合训练：sas_det 人工库 + sas_lal 真值合并 → 重训/增量 HUMAN 头 →
   验收双指标（sas_lal 覆盖 25.8%→? 与视觉精度）；
3. ID 稳定化仍是战术层唯一卡点（A4.30），本步不动。
