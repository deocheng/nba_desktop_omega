# 里程碑 05 · 路径 C（时序跟踪器）+ 路径 B（标注工具）报告

> 日期：2026-09-25 深夜 ｜ 用户裁决：**C 先建 + 并行备 B**
> 前置：`pathA_gate_report.md`（宽景 scope 定稿）、`validate3_report.md`（路径 C 旧义=换检测器的阴性验证）

---

## 1. 为什么现在做 C：召回证据先行

动手前先跑了候选密度探针（不是拍脑袋建跟踪器）：

| 片段 | 总帧 | prob>0.85 帧 | prob>0.95 帧 | 中位 bbox 对角 |
|---|---|---|---|---|
| sas_nop | 400 | 20 (5%) | 18 | 30px |
| sas_det | 400 | 27 (7%) | 17 | 31px |

**诊断**：新域瓶颈不是尺度（候选本来 <60px），是**检测置信度整体塌**（域偏移）。
跟踪器只能「连」不能「造」——预期它救连贯、救不了召回。结果证实了这个预期，且更精确。

## 2. 路径 C 落地：`engine/track_ball.py`

恒速 Kalman（4 态 x,y,vx,vy）+ 贪心最近匹配（距离门限 120px）+ 预测续命（GAP_TOL=8 帧）。
**只消费真实检测（prob>th 且 bbox<60px），不把预测帧算进覆盖率/步长**——对门禁诚实。
踩坑修复：scores JSON 的 key 是 `f00001.jpg`（带扩展名），不是 `f00001`，重建 key 会全部 miss（首轮 0 检测 bug，已修）。

## 3. 7 域校准：tracker vs 朴素门禁（gate_tracked.json vs gate_calibrated.json）

| 域 | 朴素(greedy) | **跟踪器(tracker)** | 变化 |
|---|---|---|---|
| baseline w1–w4 | 4/4 PASS | **4/4 PASS**（w3: 31.8%/94.5%/217 步） | 持平略升 |
| sas_hou | PASS th=0.85（6.0%/90.9%/11 步） | **PASS** th=0.8（28.7%/80.6%/36 步） | 覆盖 6%→28.7%，步数 11→36 |
| **sas_det** | **FAIL**（trk 封顶 63.6%） | **✅ PASS** th=0.8（26.0%/83.3% [0.66,0.93]/30 步/74 轨迹） | **FAIL→PASS，本轮核心成果** |
| sas_nop | FAIL（3 步） | **FAIL**（trk 100% 但 **n_steps=9 < 10 下限**） | 仍 FAIL，但病因改判 |

**要点**：
- **C 真的救活了 sas_det**：跟踪器的跨帧关联把稀疏检测桥接成持续轨迹（n_steps 11→30），
  可跟踪率 63.6%→83.3%。这不是指标游戏——**只用了真实检测**，只是关联更聪明。
- **sas_nop 的病因改判了**：不是连贯（trk 已 100%），是**纯召回饥饿**——全片只有 9 步真实步进，
  低于 n_steps≥10 可测下限。跟踪器无法无中生有 ⇒ **sas_nop 只能靠 B（检测器域适应）救**。
- **目视自证**（sas_det 最长轨迹 帧 234–241）：f00239 里**球清晰可见被白球衣球员在罚球线附近运球**，
  跟踪区域命中；f00234 同一持球回合区域吻合 ⇒ PASS 不是 FP 堆出来的。

## 4. 路径 B 的钥匙：`engine/label_ball_app.py`（等你手标）

A4.12 已证 AI 自标不可靠（REJECT_SELF_AS_ANNOTATOR），B 的真值**必须你来标**。
已建浏览器标注工具（浏览器点球心，键鼠操作，存 JSON）：

```
python engine/label_ball_app.py --clip sas_nop --n 50   # 然后开 http://127.0.0.1:8766
python engine/label_ball_app.py --clip sas_det --n 50
```

- 采样 = 置信帧（prob>0.85）全取 + 其余随机补足 50 帧（sas_nop：20 置信 + 30 随机；sas_det：27 + 23）。
- 每帧预填检测器建议点，你**点附近即采纳/微调**，`n` 键标无球，方向键翻帧，「保存」写
  `action_work/validate/<clip>_ball_labels.json`。
- HTTP 层已端到端 smoke 测试（/data /frame /save 全通，测试伪标签已清）。
- **你标完两个片段各 ~50 帧 → 我拿它跑少样本域适应 + 过 A4.12 式门禁**（标注重测一致率须 ≥97% 才可信）。

## 5. 裁定

- **路径 C 已交付**：sas_det 被救活 ⇒ **常规转播域从 0/2 变 1/2 可用**。
- **路径 B 解锁条件 = 你的标注**。sas_nop 病因=召回饥饿，只有 B 能治。
- scope 更新：**宽景 4/4 + sas_hou + sas_det 全 PASS**；sas_nop 待 B。

## 6. 产物

- `engine/track_ball.py`（Kalman+匈牙利跟踪器 + 7 域校准）
- `action_work/validate/gate_tracked.json`（跟踪器版全表）
- `action_work/validate/sas_det_tracked.json`（sas_det 救活轨迹明细）
- `engine/label_ball_app.py`（B 标注工具，等你用）
- 本报告
