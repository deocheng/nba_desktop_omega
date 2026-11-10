# 来源清单（盘根未评估代码目录 + 工作区关系）

> 盘点口径：只读固定路径，**未做全盘递归遍历**；规模数据来自既有收敛盘点。
> 路径基准 `NBA_ROOT = /Volumes/12T/NBA/`，
> `R = NBA_ROOT/nba_desktop_omega_mac_migrate_2026-07-13`。

## 盘根下 5 个未评估代码目录

| 目录 | 路径 | 规模 | 性质 / 处置 |
| --- | --- | --- | --- |
| FRA_SRB_QS | `NBA_ROOT/FRA_SRB_QS` | 14 py / 1454 行 | 视频处理实验代码；保留原状，不纳入主仓库改造 |
| WeVisOne-VL | `NBA_ROOT/WeVisOne-VL` | 51 py / 7916 行 | **第三方开源项目，不改造**（不属本仓库代码治理范围） |
| nba_bot | `NBA_ROOT/nba_bot` | 26 py / 1437 行 | 机器人 / 抓取相关脚本；保留原状 |
| stream_download | `NBA_ROOT/stream_download` | 3 py / 1024 行 | 流下载脚本；保留原状 |
| nba_analysis | `NBA_ROOT/nba_analysis` | 3 py / 752 行 + 96 产物 | 批量历史报告产物目录，即 P；经 `R/reports/nba-analysis` 软链收敛 |

这 5 个目录全部位于**盘根而非 R 内**，因此不视为 R 的代码根组成部分；
其中仅 `nba_analysis` 同时是 P（仓外产物来源），其内部 3 个 py 为
`nba_report.py`、`batch_report.py`、`nba_metrics.py`。

## 受保护、不纳入遍历的资产

- 6TB 素材：`比赛录像/`、`球星/`、`电视节目/`、`篮球训练/`、`资料/`、`Images/` 等（mp4 / mp3 / jpg）
- `WeVisOne-VL`（第三方开源项目）、`.trash`、`raw_archive`、`*_cache`、`.venv`、`.git`

## W 与主仓库的关系

- `W = /Users/deocheng/WorkBuddy/2026-07-13-10-47-43` 是 WorkBuddy 会话工作区，
  存放历次任务产生的临时脚本（补丁脚本、诊断脚本）与一次性报告产物。
- W **不是**代码根，也不并入 R；R 通过 `R/workspace/workbuddy-scripts -> W` 软链
  提供只读可达入口。
- W 内的 `patch_reports.py`、`reskin_pace_white.py` 属「字符串补丁反模式」：
  本次已改为默认严格 / 补全报错，但长期方向是**优先修改生成器**。
- W 内的孤儿产物（`nba_game_results.html`、`crawler_code_review_20260816.html` 等）
  只在 `R/reports/` 登记，不移动、不删除。

## 收敛关系一览

- **R**：唯一代码根；新代码与治理文件都落在 R。
- **W**：经 `R/workspace/workbuddy-scripts` 软链可达。
- **P**（= `NBA_ROOT/nba_analysis`）：经 `R/reports/nba-analysis` 软链可达。
- 软链均为绝对路径、只新增、不覆盖已有同名文件；已验证目标存在且无循环。

详见 `R/workspace/README.md` 与 `R/workspace/entry.py`。
