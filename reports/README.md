# reports — 产物治理

> 本目录是产物治理入口，**只登记、不移动、不删除**任何既有产物。

## 用途

`R/reports/` 集中存放产物治理文件：本说明、`INDEX.md`（人类可读清单）、
`manifest.json`（结构化清单，文件大小从磁盘实读）、以及可复现清单的 `build_manifest.py`。
既有 HTML / SVG / PNG 产物仍留在它们原来的位置（R 根级、W、P），本目录不复制、不搬运。

仓外批量产物 P 通过只读软链 `R/reports/nba-analysis -> /Volumes/12T/NBA/nba_analysis` 收敛，
在清单中以 `reports/nba-analysis/...` 形式的逻辑路径登记。

## 权威版本判定规则

`manifest.json` 每条带 `status`，取值与判定如下：

| status | 含义 | 判定规则 |
| --- | --- | --- |
| `authoritative` | 当前权威版本 | 由现存生成器可重新生成的最新版本；`analysis_*.html` 经剥离内联 plotly bundle 瘦身后为权威；`star_rings_2026/<TEAM>_2026.html` 每队各一份为该队权威；`team_shot_radial.html` 为当前主版本 |
| `variant` | 变体 | 同一内容的不同呈现，如 `star_ring_*_logo.html`（内嵌 base64 队标 / 头像，体积为普通版 2–4 倍），不覆盖权威版 |
| `snapshot` | 历史快照 | 带数字 / 时间戳 / 备份后缀的一次性导出，如 `team_shot_radial_215504.html`；**非权威，勿删除**，仅作历史追溯 |
| `orphan` | 孤儿产物 | 全库范围内找不到生成脚本，来源不可追溯；**只登记不删除** |
| `document` | 文档类产物 | 说明 / 评审类 HTML，非数据报告，孤儿但可接受 |

判定顺序：先按「是否有现存生成器」区分 `authoritative` 与 `orphan`；
再按「是否带时间戳 / 备份后缀」降级为 `snapshot`；
再按「是否同一内容的呈现变体」标为 `variant`；说明 / 评审类单独标 `document`。

## 孤儿产物处理原则

**只登记不删除。** 孤儿产物（生成脚本已丢失或从未纳入仓库）仍可能承载唯一的历史结论，
在找到可复现的生成器或明确确认无价值之前：

1. 在 `INDEX.md` 与 `manifest.json` 中登记路径、真实字节数、`status=orphan` 与 `generator=null`；
2. 不移动、不重命名、不删除、不覆盖；
3. 文档类孤儿产物标 `status=document` 并注明「文档类可接受」。

## 生成脚本 → 产物

配对表见 `INDEX.md`。长期方向是**优先维护生成器**，不要用字符串补丁去修一次性历史产物
（见 `W/patch_reports.py`、`W/reskin_pace_white.py` 的严格化改造）。

## 复现清单

```bash
cd R
python reports/build_manifest.py       # 从磁盘实读字节数，重写 manifest.json
```
