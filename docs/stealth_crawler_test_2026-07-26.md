# 新爬虫（Scrapling Stealth）小批量测试报告（2026-07-26）

> 授权范围：用户批准「构建 + 小测」。本报告只覆盖 P2（安装）/ P3（写基类）/ P5（小批量试点）。
> **未做**：未跑完整爬取、未写 `player_lineups`、未改任何现有基类、未动正在跑的 lineup 爬虫。

## 1. 本次构建了什么

| 阶段 | 动作 | 结果 |
|---|---|---|
| P2 | `pip install -e research/Scrapling[fetchers]` 装入爬虫 `.venv` | ✅ 仅新增 `patchright`/`browserforge` 等；`playwright==1.61.0`、`curl_cffi==0.15.0` **版本不变（低风）**；patchright chromium-1228 就绪，chromium-1217（现有 crawl 用）未被删 |
| P3 | 新增 `common/br_player_page_stealth.py`（`BRPlayerPageCrawlerStealth`） | ✅ **仅覆写 `fetch_team_page`**，cache-first 落盘 / 断点续跑 / 404 隔离 / 本地重放 / 去重入库 **全部继承基类，一字未改** |
| P5 | 小批量试点 | ✅ 见 §2 |

## 2. 测试结果

- **目标**：10 个 `player_lineups` Regular 缺口 `(slug, season)` 对（DB 只读取，近期 2023-2026 优先）。
- **模式**：`StealthyFetcher` own-browser 隐身模式（patchright chromium-1228），**不走 CDP 接管**现有 Chrome；**不写库**。
- **URL**：`/players/{letter}/{slug}/lineups/{year}/`（按赛季分路径，正确带 `/{year}` 后缀）。

| # | slug | 结果 | HTML 字节 | 耗时 |
|---|---|---|---|---|
| 1 | iveyja01 | OK 200 | 474,628 | 33.9s |
| 2 | jacksan01 | OK 200 | 474,382 | 40.9s |
| 3 | jacksgg01 | OK 200 | 474,196 | 32.3s |
| 4 | martial01 | OK 200 | 471,998 | 42.5s |
| 5 | peavymi01 | OK 200 | 471,053 | 45.5s |
| 6 | sandfpa01 | OK 200 | 460,545 | 40.4s |
| 7 | santogu01 | OK 200 | 472,940 | 35.2s |
| 8 | sarafbe01 | OK 200 | 470,744 | 34.8s |
| 9 | saricda01 | OK 200 | 483,573 | 26.3s |
| 10 | sarral01 | OK 200 | 472,003 | 41.3s |

**汇总：成功 10 / 404 0 / CF 拦截 0 / 空 0 / 异常 0。**

## 3. 关键发现与警示

1. ⚠️ **CDP 接管现有 Chrome 失败**：`StealthyFetcher(cdp_url=ws://127.0.0.1:922x/...)` 连到被我方 Playwright **已接管**的 Chrome 时，patchright 的 Network 拦截（`Network.setCacheDisabled`）报 `session closed` 并 180s 超时挂死。→ 改用 own-browser 模式（或用一个**不被我方 driver 接管**的独立 CDP 浏览器）。
2. ⏱️ **速度偏慢**：own-browser 冷启动 ~30-45s/目标（含浏览器启动 + 导航 + `wait_selector=#content` + 1s 等待）。现有常驻 Chrome（9222）走 Playwright CDP 仅 ~秒级。优化方向（P4）：保持**单个 `StealthySession` 跨目标复用 context**，而非 `StealthyFetcher.fetch` 每次开/关浏览器。
3. ✅ **未触发真实 CF 挑战**（日志 `No Cloudflare challenge found`）—— BR 从全新隐身浏览器**直接放行**。故「绕过 CF」目前验证为「无 CF 拦截地干净抓取」，尚未在**真实 CF 挑战**下验证解算；侧面说明当前 IP/会话未被墙。
4. ✅ **零干扰**：正在跑的 lineup 爬虫（9222 / PID 33262）与 9223 **完全未受影响**；chromium-1217（crawl 用）仍在；9222/9223 仍 HTTP 200。

## 4. 结论与下一步

✅ **新爬虫抓取传输层工作正常**：Scrapling 隐身 fetcher 能稳定拿到可解析的 BR lineup 页，且完整继承现有基类机制（继承而非替换）。

待你授权后再推进：
- **P4**：把具体爬虫子类（`PlayerLineupCrawler` 等）改继承 `BRPlayerPageCrawlerStealth`（或加 `StealthMixin`），并实现「单 StealthySession 复用」提速 + 本地重放回归测试。
- **P6**：并入新赛季全量计划（见 `docs/new_season_2026_27_crawl_plan.md`），从季前赛起用新爬虫补 lineup 缺口。

## 5. 涉及文件
- `common/br_player_page_stealth.py`（新增，P3）
- `research/test_stealth_fetch.py`（测试脚本）
- `.venv`（P2 安装 scrapling[fetchers]，仅新增依赖）
