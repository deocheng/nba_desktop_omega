# 爬虫机制升级设计：Scrapling 取长补短 + 锁定现有基类 + 新机制继承

> 文档状态：v1 **设计稿**（仅方案，未执行任何代码改动 / 未启动爬取 / 未提交 git）
> 触发指令：拉取 `https://github.com/D4Vinci/Scrapling` → 验证我方现有爬虫逻辑 → 取长补短 → 锁定现有爬虫代码 → 新爬虫机制继承现有爬虫
> 项目根：`/Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13/`
> Scrapling 已克隆至：`research/Scrapling/`（v0.4.11，只读研究，未并入业务代码）

---

## 0. 执行边界声明（重要）

本文件只做 **调研 + 设计**。以下内容均为方案，落地（git 冻结、安装 scrapling、写新子类、跑爬取）需你逐项确认后才执行。尤其：

- 现有 `common/br_*.py` 基类**本轮回不改动**（这正是"锁定"的含义）。
- 不启动任何爬取、不改动 runner / auto-runner。

---

## 1. 验证：我方现有爬虫逻辑（已读源码确认）

### 1.1 继承树（精确，来自源码 Grep）

```
BRTeamPageCrawler                      common/br_team_page.py:135   [根] 球队页基类
 └─ BRPlayerPageCrawler              common/br_player_page.py:86    [球员页基类] 固化主流程
      ├─ BRPlayerLineupCrawlerBase   common/br_player_lineup.py:41  [阵容] 覆写 _upsert_rows(去重)
      │    └─ PlayerLineupCrawler    external_crawler/crawler/crawl_br_player_lineup.py:177
      └─ BRPlayerOnOffCrawlerBase   common/br_player_onoff.py:44   [on-off]
           └─ PlayerOnOffCrawler     external_crawler/crawler/crawl_br_player_onoff.py
```

> 注：活跃生效的 `_upsert_rows` 在 `common/br_player_page.py:352`（父类），lineup 基类**覆写**它做按冲突键去重（保留末次、幂等）。

### 1.2 基类固化主流程（契约，来自 `BRPlayerPageCrawler` 精读）

| 方法 | 位置 | 职责 | 是否冻结(继承不动) |
|---|---|---|---|
| `build_url(slug)` | :106 | 构造 BR 球员页 URL | ✅ 冻结 |
| `save_raw_html(slug, html)` | :112 | **cache-first 落盘** `raw_archive/br_players/{slug}/` | ✅ 冻结(核心优势) |
| `enumerate_players(conn, priority_gap)` | :121 | 待抓 slug 宇宙(gamelog.br_player_id ∪ dim_players) | ✅ 冻结 |
| `_player_done(conn, slug)` | :180 | **断点续跑**：已落库则跳过 | ✅ 冻结 |
| `_quarantine_slug(conn, slug, note)` | :191 | **404 隔离**进 `{table}_404`，缺口口径诚实 | ✅ 冻结(关键) |
| `_crawl_player(conn, driver, slug)` | :217 | **抓取落点**：`fetch_team_page` → 404 判定 → `save_raw_html` → `_consume_html` | 🔧 **唯一建议覆写点**(见 §4) |
| `_consume_html(conn, slug, html)` | :239 | **解析落点**：`parse` → `build_rows` → `upsert` | 🔧 可选增强点 |
| `run_players(...)` | :255 | 主循环(遍历 slug、续跑、dry_run) | ✅ 冻结 |
| `rework_from_archive(slug)` | :336 | **本地重放**：纯 `path.read_text()` + `_consume_html`，零联网 | ✅ 冻结(铁律②) |
| `_upsert_rows(conn, table, rows)` | br_player_page.py:352 | 入库(去重在子类覆写) | ✅ 冻结 |

**结论：现有逻辑核心机制健全、可继承** —— cache-first 落盘、断点续跑、404 隔离、本地重放、去重入库，这五点是项目数年沉淀的优势，必须原样保留。真正薄弱处在**抓取传输层**(手写 CDP/Playwright + 家生 `CFBreaker`)，这正是 Scrapling 可补强之处。

### 1.3 我方已有的反爬/驱动资产（避免重复造轮子）

- `common/cf_breaker.py:38 CFBreaker` —— **连续撞墙熔断 + 冷却自恢复**（backoff=30s、cooldown=600s、max_cooldowns 上限）。**重要发现：这比 Scrapling 的 `retries=3, retry_delay=1s` 固定延迟更成熟**（Scrapling 无指数退避、无熔断冷却）。→ 我们的 `CFBreaker` 应**保留并继续作为重试主控**，不换 Scrapling 的。
- `common/browser.py:191 _PWDriver` / `:480 _RawCDPDriver` —— 我们的 Playwright / 原生 CDP 驱动，已稳定驱动 9222/9223 双 Chrome。

---

## 2. Scrapling 架构（来自 Explore 深读，v0.4.11）

四层：`fetchers`(门面) → `engines`(curl_cffi / patchright) → `parser`(Selector/lxml) → `spiders`(调度/会话/缓存/检查点)。

| 能力 | 实现位置 | 说明 |
|---|---|---|
| **隐身/反爬** | `engines/_browsers/_stealth.py` | patchright(Playwright stealth 分支)；Cloudflare Turnstile/Interstitial **自动解算**(`_cloudflare_solver`)；canvas 加噪、WebRTC/DNS 防泄漏、browserforge 真实 header |
| **TLS 指纹** | `engines/static.py:73` | curl_cffi `impersonate="chrome"` 默认伪装最新 Chrome TLS；UA/指纹轮换 `ProxyRotator` |
| **多后端 Fetcher** | `fetchers/__init__.py:11` | `Fetcher`(HTTP/curl_cffi) / `DynamicFetcher`(Playwright) / `StealthyFetcher`(patchright 全隐身) |
| **CDP 接管** | `_stealth.py:82` / `chrome.py:33` | `connect_over_cdp(cdp_url)` —— **可接管我们自管 Chrome，而非取代** |
| **自适应解析** | `parser.py` | lxml `Selector`，selector 失效时按相似度(difflib)自动重定位元素(SQLite 持久化)，网站改版不崩 |
| **落盘重放缓存** | `spiders/cache.py:13` | `ResponseCacheManager` 首次落盘、后续原样重建 `Response` 重放(**但仅 development_mode，非生产级**) |
| **重试** | `engines/static.py:247` | 固定 `retries=3 / delay=1s`，**无指数退避/无熔断冷却**；spider 层按状态码(401/403/429/5xx)重新入队、摘代理 |
| **扩展点** | 继承为主 | 自定义 Fetcher 继承 `BaseFetcher`；自定义 Spider 继承 `Spider`(override `parse`/`is_blocked`/`configure_sessions`) |

> ⚠️ Scrapling 仅声明绕过 **Cloudflare**；**无 Akamai / PerimeterX 专用解算**。若 NBA 源走 Akamai 仍需自补（或用我方 CDP 通道兜底）。

---

## 3. 取长补短对照表

| 维度 | 我方现状 | Scrapling | 取长补短决策 |
|---|---|---|---|
| **抓取传输层** | 手写 `_PWDriver`/`_RawCDPDriver` + 家生 `CFBreaker` | patchright 隐身 + 自动 CF 解算 + TLS 伪装 | **借 Scrapling 的 Fetcher 作传输增强层**（接管我方 Chrome / 或硬 CF 走 StealthyFetcher） |
| **反爬重试** | `CFBreaker` 熔断+冷却(更优) | 固定 1s×3，无退避 | **保留我方 CFBreaker** 作重试主控，不换 |
| **CDP 驱动** | 已稳定驱动 9222/9223 | `connect_over_cdp` 可接管 | **复用**：新爬虫经 Scrapling 的 `connect_over_cdp` 连我方 Chrome（保留精细控制） |
| **缓存/重放** | cache-first 落盘 HTML + `rework_from_archive` 生产级 | 仅 development_mode 缓存 | **保留我方缓存体系**（更成熟），仅参考其 `Response` 重建机制 |
| **解析器** | BeautifulSoup 手写 | lxml `Selector` 自适应重定位 | **可选增强**：易被改版打挂的解析接 `Selector.adaptive`；其余保留 BS4 |
| **本地重放/增量** | gap 查询 `NOT EXISTS` 跳过已落库 | 无等价生产机制 | **保留我方**（铁律②核心） |
| **404 隔离/缺口诚实** | `_quarantine_slug` | 无等价 | **保留我方** |

**一句话定位**：Scrapling = **反爬/隐身与多后端抽象增强层（插件）**；我方 CDP 驱动 + 缓存/重放 + 断点续跑 + 去重 + 404 隔离 = **主链路（保留）**。新爬虫用 Scrapling 的 fetcher 替换"抓取传输"这一小段，其余全盘继承。

---

## 4. 锁定现有爬虫代码（冻结为继承锚点）

### 4.1 语义
"锁定" = 将 `common/` 下三个基类（`BRTeamPageCrawler`、`BRPlayerPageCrawler`、`BRPlayerLineupCrawlerBase`/`BRPlayerOnOffCrawlerBase`）及其 §1.2 契约方法，**确立为不可变继承基线**。后续所有演进（含 Scrapling 集成）一律走**新子类**，不再 patch 基类。这既能止血此前"lineup bug 改错文件"式的基类的意外改动，也满足你"新爬虫机制继承现有爬虫"的要求。

### 4.2 具体冻结做法（待你确认后执行，本回不执行）
1. **契约文档化（可逆、无破坏）**：把 §1.2 的基类 API 固化为 `docs/crawler_baseline_contract.md`，作为新爬虫必须 conform 的规格。→ 这一步不碰代码，我可直接做。
2. **git 冻结（需你批准）**：当前爬虫修复(lineup 去重覆写、PO 表 id 修复)是**未提交**的工作树改动，plain `git tag` 只指向旧 HEAD、不含这些修复。故"锁定"正确做法是：
   - 先 `git add` 仅 crawler 相关文件（`common/br_*.py`、`external_crawler/crawler/crawl_br_player_*.py`、`docs/`、`research/Scrapling` 作 subtree 或 submodule 引用），
   - 提交为 `crawler-baseline-v1`，再 `git tag crawler-baseline-v1`。
   - ⚠️ 仓库现有**无关未提交改动**（`Dockerfile`、`backend/api/routers/*`）需先 `git stash` 或排除，避免污染基线提交。

### 4.3 禁止项（冻结后）
- 不得再改 `common/br_team_page.py` / `br_player_page.py` / `br_player_lineup.py` / `br_player_onoff.py` 的基类方法。
- 新增能力只在新子类 / 新 mixin 中实现。

---

## 5. 新爬虫机制设计（继承现有，不替换）

### 5.1 新增基类（只覆写"抓取传输"一小段）

```python
# common/br_player_page_stealth.py  (新文件，不碰现有基类)
from common.br_player_page import BRPlayerPageCrawler
from scrapling import StealthyFetcher, Fetcher   # 安装自 research/Scrapling 或 pip

class BRPlayerPageCrawlerStealth(BRPlayerPageCrawler):
    """继承现有主流程(cache-first/续跑/404隔离/重放/去重全保留)，
    仅把『抓取传输』替换为 Scrapling Fetcher(隐身+CF解算)。"""

    def __init__(self, cdp_url="http://127.0.0.1:9222", use_stealth=False, **kw):
        super().__init__(**kw)
        # 默认接管我方自管 Chrome(connect_over_cdp)；硬 CF 才切 StealthyFetcher 自带浏览器
        if use_stealth:
            self._fetcher = StealthyFetcher(headless=True, cdp_url=cdp_url)
        else:
            self._fetcher = Fetcher(impersonate="chrome")  # curl_cffi TLS 伪装

    # —— 唯一覆写点：抓取传输(§1.2 🔧) ——
    def fetch_team_page(self, driver, url: str) -> str:
        resp = self._fetcher.get(url, wait="network_idle",
                                 wait_selector="#content, table", timeout=30_000)
        if resp and resp.status == 200 and resp.text:
            return resp.text
        self._last_fetch_404 = (getattr(resp, "status", None) == 404)
        return ""   # 交给基类 _crawl_player 的 404/CF 判定逻辑

    # —— 可选增强点：解析接自适应 Selector(§3 解析器行) ——
    # def _consume_html(self, conn, slug, html):
    #     ... 用 scrapling.Selector(adaptive=True) 替代 BS4 易碎解析 ...
```

> **关键**：`_crawl_player` / `save_raw_html` / `_quarantine_slug` / `rework_from_archive` / `_player_done` / `_upsert_rows` **全部继承、一字不改**。Scrapling 只作用于 `fetch_team_page` 这一行传输调用。这正符合"新爬虫机制继承现有爬虫"。

### 5.2 具体爬虫的继承链（扩展点）

```
BRPlayerPageCrawler                 [冻结基类]
 └─ BRPlayerPageCrawlerStealth     [新：仅换 fetch_team_page，继承一切]
      ├─ (可选) PlayerLineupCrawlerV2 继承 BRPlayerLineupCrawlerBase + mixin Stealth
      └─ (可选) PlayerOnOffCrawlerV2  同上
```

- 阵容/on-off 的**现有子类**(`PlayerLineupCrawler` 等)若想用隐身抓取，只需改其继承父类为 `BRPlayerPageCrawlerStealth`（或加一个 `StealthMixin`），**不重写任何解析/入库逻辑**。
- 去重(`_upsert_rows` 覆写)、PO 表 id 修复等既有正确逻辑**原样保留**。

### 5.3 与"新赛季计划"的衔接（见 `docs/new_season_2026_27_crawl_plan.md`）
- 新赛季(2026-27 / BR 标记 `2027`)的全量爬取，直接复用 `BRPlayerPageCrawlerStealth` 作为抓取底座。
- 新秀发现层(该计划 §3)产出的 slug 宇宙，灌入 `enumerate_players` 即可——基类契约不变。
- 从季前赛起(`--loop --since`)的增量节奏，由 `run_players(resume=)` + `CFBreaker` 主控，Scrapling 仅作传输。

---

## 6. 落地路线图（需逐项批准，本回不执行）

| 阶段 | 动作 | 风险 | 批准门槛 |
|---|---|---|---|
| P0 | 文档化基类契约 `docs/crawler_baseline_contract.md`(§4.2.1) | 无(只读产出) | 可直接做 |
| P1 | git 冻结 `crawler-baseline-v1`(§4.2.2，先 stash 无关改动) | 低/可逆 | **需你确认** |
| P2 | 安装 scrapling：`pip install -e research/Scrapling`(入 venv) 或 `pip install scrapling` | 低 | 需你确认 |
| P3 | 写 `common/br_player_page_stealth.py` 新基类(§5.1) | 低(新文件，不碰基类) | 需你确认 |
| P4 | 具体爬虫子类改继承 Stealth 基类 + 单测(含本地重放回归) | 中 | 需你确认 |
| P5 | 小批量试点(1~2 个曾被 CF 卡住的 slug)验证隐身抓取 | 低 | 需你确认 |
| P6 | 并入新赛季全量计划(§5.3) | — | 随新赛季计划走 |

---

## 7. 结论（一句话）

现有爬虫逻辑**核心健全、值得继承**；Scrapling 的最佳价值是**反爬/隐身 + 多后端 Fetcher 抽象**，应作为"抓取传输"增强层**插入 `_crawl_player` 的 `fetch_team_page` 落点**（经 `connect_over_cdp` 接管我方 Chrome），而 cache-first 落盘、断点续跑、404 隔离、本地重放、去重入库、以及我方 `CFBreaker` 重试主控**全部原样继承、冻结不动**。新爬虫 = 新增一个只覆写"抓取传输"的 `BRPlayerPageCrawlerStealth` 子类，全盘继承现有机制。

---

## 8. 执行记录（2026-07-26，用户授权「构建+小测」）

- **P2 完成**：`pip install -e research/Scrapling[fetchers]` 装入 `.venv`。仅新增 patchright/browserforge 等，`playwright==1.61.0` / `curl_cffi==0.15.0` 版本不变（低风）；patchright chromium-1228 就绪（chromium-1217=现有 crawl 用，未被删）。
- **P3 完成**：新增 `common/br_player_page_stealth.py`（`BRPlayerPageCrawlerStealth`），**仅覆写 `fetch_team_page`**，继承 cache-first/续跑/404隔离/重放/去重 全部基类逻辑，一字未改。
- **P5 完成（小测）**：10 个 lineup Regular 缺口 `(slug,season)` 目标，own-browser 隐身模式（patchright chromium-1228，不走 CDP 接管），**不写库**。结果 **10/10 → HTTP 200，真实 lineup HTML（均值 ~470KB），0 次 CF 拦截 / 0 个 404 / 0 异常**。详见 `docs/stealth_crawler_test_2026-07-26.md`。

### 关键发现 / 待办
1. ⚠️ **CDP 接管现有 Chrome 失败**：`StealthyFetcher(cdp_url=ws://…)` 连到被我方 Playwright 已接管的 Chrome 时，patchright 的 Network 拦截（`Network.setCacheDisabled`）报 `session closed` 并 180s 超时。→ 改用 own-browser 模式（或用一个不被我方 driver 接管的独立 CDP 浏览器）。
2. ⏱️ **速度**：own-browser 冷启动模式 ~30-45s/目标（含浏览器启动），比现有常驻 Chrome(~秒级)慢。优化方向（P4）：保持单个 `StealthySession` 跨目标复用 context，而非每调用开/关。
3. ✅ **未触发真实 CF 挑战**（日志 `No Cloudflare challenge found`）—— BR 从全新隐身浏览器直接放行；「绕过 CF」目前验证为「无 CF 拦截地干净抓取」，尚未在真实 CF 挑战下验证解算（侧面说明当前 IP/会话未被墙）。
4. ✅ 正在跑的 lineup 爬虫（9222 / PID 33262）与 9223 **零干扰**；chromium-1217 仍在。

### 下一步（待授权）
- **P4**：把具体爬虫子类（`PlayerLineupCrawler` 等）改继承 `BRPlayerPageCrawlerStealth`（或加 `StealthMixin`），并做「单 StealthySession 复用」优化 + 本地重放回归。
- **P6**：并入新赛季全量计划（见 `docs/new_season_2026_27_crawl_plan.md`）。
