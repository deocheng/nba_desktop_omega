# BR 爬虫套装 · 独立控制台 App

把 `crawler_v2` 的 v2 适配器打包成一个**带 GUI 控制面板的本地独立 App**（FastAPI 风格的本地 Web 面板，零第三方依赖，stdlib `http.server` 起的）。

## 功能
1. **数据项单独爬取**：BR Gamelog / BR PBP / ESPN / NBA_API 各自按钮，填赛季即可触发。
2. **融合数据**：跨源覆盖度汇总报告（`fusion_report.py`，只读，不写库）。
3. **赛季全量爬取**：走 `daemon.runner`（赛季倒序/定向，自带 STATE 续爬 + `verify_gaps` 门禁）。
4. **工作日志**：每个任务落盘 `worklog.json` + 独立 `logs/<job>.log`，面板实时刷新。
5. **根据日志续爬**：扫描工作日志，重派所有未成功（失败/中断）的任务；脚手架类任务自动跳过。

## 启动
```bash
bash start_app.sh
# 自动打开 http://127.0.0.1:5757
```
或手动：
```bash
source /Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/.env
/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/.venv/bin/python server.py
```

## 各适配器真实就绪状态（基于代码，非猜测）
| 数据项 | 状态 | 说明 |
|---|---|---|
| BR Gamelog | ✅ ready | cache-first 离线可跑（已验证 73 场 dry-run） |
| BR PBP | ⚠️ ready（需 Chrome/9223） | 复用 `br_fill_pbp`/`br_pbp_parse`/`raw_archiver`（位于 ROOT） |
| ESPN | ⛔ scaffold | 接口脚手架，`run` 抛 NotImplementedError，不编造解析 |
| NBA_API | ⛔ scaffold | 同上 |

> ESPN / NBA_API 按钮保留，运行会在工作日志里诚实标注 `scaffold`，待对应解析接入后即可真正爬取。

## 架构
- `server.py` — stdlib HTTP 服务，路由 API + 托管 `index.html`。
- `job_manager.py` — 每个爬取任务以**独立子进程**运行（不阻塞 server、可 stop、可续爬），写 `worklog.json`。
- `fusion_report.py` — 只读跨源覆盖度汇总。
- `index.html` — 原生 JS 深色控制面板，4s 轮询刷新。

## 铁律遵守
- 旧 `crawler/` **零修改**；本 App 全部为 `crawler_v2/app/` 增量。
- 写库仍走 v2 适配器既有 §6 参数化 + 幂等逻辑，不新增 SQL 拼接。
- `dry-run` 默认勾选：单数据项爬取的按钮在 UI 上默认 dry-run，取消勾选才真正写库（防误操作）。
