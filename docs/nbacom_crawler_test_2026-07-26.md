# nba.com 新爬虫 小テスト報告（2026-07-26）

> 用户授权范围：构建 curl_cffi(Fetcher) transport + 1997+ PBP 欠損 20-30 场小测。
> 全程 **只读 DB、零写库、不碰坐标、未触碰运行中的爬虫（9222/9223）**。

## 0. 结论速览（TL;DR）

| 项 | 结果 |
|---|---|
| **1997+ PBP 真实欠損** | **896 场**（此前"~35,331"是格式不一致造成的假缺口） |
| 896 欠損构成 | **≈99% 季前赛**；常规赛仅 3 场（2026 现役季） |
| RS/PO 的 PBP（1997+） | **实质已完整覆盖** |
| curl_cffi(Fetcher) 打 stats.nba.com | **被 Akamai WAF 拦截**（200→HTML拦截页 / 403），拿不到 JSON |
| 单次浏览器导航（StealthyFetcher/patchright） | 同样被 Akamai 拦截 |
| 探查约 40 次后 | IP 出现更硬的 **403 Access Denied** → **有被风控标记的风险** |

**核心判断：用户首选的 `Fetcher(curl_cffi)` 方式在 stats.nba.com 上不可行**——Akamai Bot Manager 需要浏览器执行 sensor JS 生成合法 `_abck` cookie，纯 HTTP（即使 TLS 偽装）无法通过。

---

## 1. PBP 欠損的真相（重要修正）

### 铁律复用：`play_by_play.gameid` 多形式，缺口判定必须联合两键

`play_by_play` 的 gameid 按 source 分两种形式：

| source | 场次 | gameid 形式 | 样本 |
|---|---:|---|---|
| br_crawler | 31,863 | nba_api 数字(去前导零) | `20000001` ~ `52500211` |
| nba_api | 5,882 | nba_api 数字 | `11300001` ~ `49800087` |
| BBRef | 732 | BR 日期格式 | `199611010DET` |
| ESPN | 513 | BR 日期格式 | `200204050SEA` |

`dim_games` 有两列 game id：
- `game_id`（text，BR 日期格式，如 `199611010LAL`）
- `nba_api_id`（bigint，如 `29600012`，与 pbp 数字键同形式）

**只用 `p.gameid = g.game_id` 结合 → 只命中 BBRef+ESPN 的 1,245 场，其余全部误判为"欠損"**（这就是此前 38,112 / ~35,331 的来源）。

正确判定：
```sql
NOT EXISTS(SELECT 1 FROM play_by_play p
           WHERE p.gameid = g.game_id
              OR p.gameid = g.nba_api_id::text)   -- 类型需 ::text
```

### 修正后结果（season >= 1997）

| 指标 | 值 |
|---|---:|
| 1997+ 总场次 | 39,357 |
| **PBP 真实欠損** | **896** |
| 其中有 nba_api_id | 893 |
| 其中无 nba_api_id | 3 |

欠損按赛季（Top）：全部集中在 **Pre Season**——2007:120 / 2011:119 / 2010:118 / 2013:116 / 2006:111 / 2009:110 / 2008:106 / 2012:30 …，常规赛仅 **2026 季 3 场**。

> 结论：**RS+PO 的 PBP 在 1997+ 已实质完整**。季前赛 PBP 价值低、且 nba.com 未必有 → "用 nba.com 补 PBP"这件事本身收益极小。
> `dim_games.nba_api_id` 覆盖 1997+ 达 38,825/39,357（98.6%）→ **GameID 桥接已就绪**（补零到 10 位即 stats.nba.com 用的 GameID）。

---

## 2. transport 实测：stats.nba.com 被 Akamai 拦

测试脚本：`research/test_nbacom_pbp_fetch.py`（curl_cffi 版，抽 30 场 gap 实打）。

### 2.1 curl_cffi（用户首选）

- 30/30 返回 **HTTP 200 但 content-type=text/html**，body 是 nba.com 的错误页（非 JSON）。
- 拦截页特征（= Akamai Bot Manager）：
  - `failover-waf.nba.com/akam/13/...` sensor 脚本
  - `bazadebezolkohpepadr` 变量（Akamai 签名）
  - `Reference Number: 18.3eff4817...`
- 尝试无效的规避：`impersonate` 5 种（chrome110/120/124/131、safari17）+ 先访问 www.nba.com 播种 cookie → **全部仍被拦**。

### 2.2 浏览器方式

| 方式 | 结果 |
|---|---|
| StealthyFetcher 单次 fetch | 200 → 同款 Akamai 拦截页（9.1s） |
| patchright 播种 nba.com/stats + 页内 fetch() | CORS `Failed to fetch`（自定义头触发预检失败），且未拿到 `_abck` |
| patchright 播种 nba.com 首页 + 直接导航 API URL | www.nba.com 返回 **0 cookie**；API **403 Access Denied**（更硬） |

### 2.3 风控信号（务必注意）

约 40 次探查后，从"软拦截页(200)"升级到 **403 Access Denied**，且首页拿不到任何 cookie ——
**本机出口 IP 很可能已被 Akamai 临时标记**。已 **立即停止** 对 nba.com 的一切 live 请求，避免进一步风控（符合项目"IP 保全 / 不越界"铁律）。

---

## 3. 为什么 curl_cffi 过不了

Akamai Bot Manager 的通过要件是合法的 `_abck` cookie，而它由页面内 sensor JS（`bmak.sensor_data`）在真实浏览器环境运行后生成并回传验证。curl_cffi 只做 TLS/HTTP 层偽装，**不执行 JS**，因此拿不到有效 `_abck` → 每次都吃拦截页。这不是 header 或 impersonate 调参能解决的。

---

## 4. nba.com 相对 BR 的独有数据域（后续价值所在）

PBP 已基本不缺；nba.com 的真正增量价值在 BR **完全没有** 的维度（均在同一 Akamai 墙后）：

| 数据域 | 起始季 | BR 有? | nba.com endpoint(示例) |
|---|---|---|---|
| Player Tracking(SportVU: 速度/距离/触球/驱动) | 2013-14 | ✗ | `leaguedashptstats`, `playerdashptshots` |
| Hustle Stats(拼抢/干扰投篮/护球) | 2015-16 | ✗ | `leaguehustlestatsplayer` |
| Shot Chart 坐标(x,y 逐投) | 1996-97 | 部分 | `shotchartdetail` |
| Play Types(Synergy) | 2015-16 | ✗ | `synergyplaytypes` |
| Matchups(对位) | 2017-18 | ✗ | `leagueseasonmatchups`, `boxscorematchupsv3` |
| Defense Dashboard | 2013-14 | ✗ | `leaguedashptdefend` |
| Clutch 细分 | 1996-97 | 部分 | `leaguedashplayerclutch` |

> 全部走 stats.nba.com → **要拿到这些，必须先解决 Akamai**。curl_cffi 方案对它们同样无效。

---

## 5. 建议的可行路径（待你拍板，本次未执行）

1. **A｜浏览器 cookie 收割 + curl_cffi 复用（推荐折中）**
   用一个"温好的"持久化 stealth 浏览器上下文访问真实 nba.com 页面，等 `_abck` 变为合法后，导出 cookie 注入 curl_cffi Session，在 cookie 有效期内高速批量取 JSON；失效则重新收割。兼顾"过墙"与"速度"。
2. **B｜纯浏览器逐页取**
   每个 endpoint 用 stealth 浏览器直接导航 JSON URL（慢，~10-40s/次），适合小批量高价值域。
3. **C｜非 Akamai 端点**
   `cdn.nba.com/static/json/liveData/...`（仅近期/当季）、`data.nba.com` 旧 feed（历史有限）——覆盖面窄，作为补充。
4. **前置｜换出口/降速/固定 UA-Profile**
   当前 IP 已疑似被标记，恢复前建议：暂停 live 请求一段时间、考虑住宅代理、严格限速（≥3-5s）、复用与既有 headed Chrome 一致的指纹。

> 重要：**不要** 复用正在跑 BR lineup 抓取的 9222 Chrome（PID 33262）来过 nba.com——违反"不碰运行中爬虫"铁律，也会污染 BR 抓取会话。若走浏览器路线，另起独立 stealth 上下文。

---

## 6. 产物清单（本次）

- `research/test_nbacom_pbp_fetch.py` — curl_cffi PBP 小测脚本（只读 DB / 零写库）
- 本报告
- 未新增任何 DB 数据；未改动既有爬虫；未安装新依赖（curl_cffi 0.15.0 / scrapling 0.4.11 / patchright 均已在 .venv）
