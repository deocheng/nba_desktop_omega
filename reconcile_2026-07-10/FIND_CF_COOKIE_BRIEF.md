# Agent Brief — 找回 / 生成 `.br_cf_cookies.pkl` 与 `br_2026_rs.tsv`（TASK A 输入）

> 目标：为 NBACore Studio v8 的 **TASK A（2026 缺失常规赛比赛清单）** 提供两个输入文件，
> 使 `reconcile_2026-07-10/_diff_2026_missing.py` 能产出 DB 与 Basketball-Reference 权威赛程的 diff。
> 本文件自包含，任何 agent（人或 AI）读完即可执行。

---

## 0. 一句话结论

- **`br_2026_rs.tsv` 不是现成文件**，是脚本 `_fetch_br_2026_schedule.py` 的**输出产物**，目前尚未生成。
- **`.br_cf_cookies.pkl` 本机不存在**（已在 `C:\autopick`、`C:\Users\Administrator` 搜 `*.pkl` / `*cf*cookies*` 全部落空）。
- 它必须由 `nba_daily_crawler.py` 的 `BrowserManager` 在**成功通过 Cloudflare 后**落盘，或从你**以前跑过 crawler 的其它机器/备份**找回。
- 没有这个 cookie，`_fetch_br_2026_schedule.py` 会被 CF 拦截、拿不到赛程表 → tsv 永远为空。

---

## 1. 两个产物的来龙去脉

### 产物 1：`br_2026_rs.tsv`（BR 2025-26 常规赛权威赛程）

| 项 | 值 |
|----|----|
| 性质 | **脚本输出**，非现成文件 |
| 生成脚本 | `C:\autopick\AutoPick\nba_data\nba_desktop\nba_desktop_omega\reconcile_2026-07-10\_fetch_br_2026_schedule.py` |
| 输出路径 | `…\reconcile_2026-07-10\br_2026_rs.tsv` |
| 格式 | TSV：`game_date \t away_abbr \t home_abbr`（按 10月–4月 6 个月份页抓取 BR `NBA_2026_games-<month>.html`，自动排除 Play-In 与 NBA Cup 决赛） |
| 前置依赖 | 必须能成功抓取 `basketball-reference.com`（即**必须绕过 Cloudflare**） |

### 产物 2：`.br_cf_cookies.pkl`（Cloudflare 绕过 cookie）

| 项 | 值 |
|----|----|
| 性质 | Python pickle，内容为 `driver.get_cookies()` 列表；关键是 `name=='cf_clearance'` 这条（域名 `basketball-reference.com`） |
| 期望路径 | `C:\autopick\AutoPick\nba_data\.br_cf_cookies.pkl`（⚠️ 在 `nba_data/` **根目录**，不在 `nba_desktop_omega/` 内。reconcile 脚本用 `os.path.join(here,'..','.br_cf_cookies.pkl')`，即回溯两级到 `nba_data/`） |
| 生产者 | `C:\autopick\AutoPick\nba_data\nba_daily_crawler.py` → `BrowserManager._save_cookies()`（line 415-422），**仅当成功通过 CF 挑战后**（`_try_get_real_page` 判定非 CF 页）落盘 |
| 消费者 | ① 真实 crawler 的 `_load_cookies()`（line 389，启动注入、跳过二次挑战）；② reconcile 脚本 line 30-39（`pickle.load` → `add_cookie`） |

---

## 2. 当前状态（已核实）

- `.br_cf_cookies.pkl` **本机不存在**（搜索 `C:\autopick\**\*.pkl`、`*cf*cookies*.pkl`、`C:\Users\Administrator\**\*cookies*.pkl` 均 0 结果）。
- `br_2026_rs.tsv` **尚未生成**（fetch 脚本因缺 cookie 被 CF 拦截，拿不到赛程表）。
- 环境就绪：系统 Python 3.10 有 `undetected_chromedriver 3.5.5` + `pandas 2.3.3` + `lxml`；Chrome 已装（`/c/Program Files/Google/Chrome/Application/chrome.exe`）。

---

## 3. 两条获取路径（任选其一）

### 路径 A — 从别处找回已有 cookie（最快，前提是你以前在别的机器/项目跑过 crawler）

1. 在**之前成功绕过 CF 的机器 / 项目目录 / 备份 / 云同步**里找隐藏文件 `.br_cf_cookies.pkl`。
   它也可能被改名：`cf_cookies.pkl`、`br_cookies.pkl`、`cookies.pkl` 等。
2. 内容特征搜法：任意 `.pkl`，pickle 反序列化后是 `list[dict]`，其中某 dict 满足
   `d['name'] == 'cf_clearance'` 且 `d['domain']` 含 `basketball-reference.com`。
3. 找到后**原样复制**到 `C:\autopick\AutoPick\nba_data\.br_cf_cookies.pkl`（保持隐藏文件名，含前导点）。
4. ⚠️ **`cf_clearance` 与生成它的 IP / 浏览器指纹部分绑定**。若来源机器 IP 与当前不同，cookie 可能失效 → 需走路径 B 重新生成。

### 路径 B — 本机重新生成（最稳，保证新鲜有效）

> ⚠️ **纠正**：`nba_daily_crawler.py --check` **不会**生成 cookie。
> `run_check()` 只读状态日志 + `information_schema` 表清单，**从不启动浏览器、从不导航到 BR**，
> 因此不会触发 `_save_cookies()`。下面两种才是能落盘 cookie 的方法。

**方法 B1（推荐，零副作用）— 用随附的 `gen_cf_cookie.py`：**

与本 brief 同目录已提供 `gen_cf_cookie.py`，它复用 `BrowserManager`，只抓一次 BR 首页就退出（不抓数据、不写库）：

```bash
cd /c/autopick/AutoPick/nba_data
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
  /c/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe \
  nba_desktop/nba_desktop_omega/reconcile_2026-07-10/gen_cf_cookie.py
```

- 脚本启动单会话浏览器 → 导航 BR 首页 → 过 CF 后 `BrowserManager._try_get_real_page` 自动 `_save_cookies()` 落盘 → 打印 `OK: cookie 已生成`。
- 若 CF 弹 **CAPTCHA**：headless 无法过，脚本会打印 `FAIL`。此时需在**可见浏览器**手动点过一次，或改用方法 B2。

**方法 B2（兜底）— 跑一次真实抓取模式（会真正爬数据，但首次抓到 BR 页即落盘 cookie）：**

```bash
cd /c/autopick/AutoPick/nba_data
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
  /c/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe \
  nba_daily_crawler.py --month-backfill 2025-10
```

- `run_month_backfill` / `run_daily` / `run_full_season` / `run_single_table` 都会 `browser.start()` 并导航到 BR，
  首次成功过 CF 即自动落盘 cookie（见 `BrowserManager._save_cookies`，line 415-422）。
- 此法会实际爬取 2025-10 的比赛数据（副作用），仅当 B1 因 CAPTCHA 卡住时使用。

**无论 B1 / B2，落盘后都确认：**

```bash
ls -la /c/autopick/AutoPick/nba_data/.br_cf_cookies.pkl
```

---

## 4. 生成 tsv（拿到 cookie 后）

```bash
cd /c/autopick/AutoPick/nba_data/nba_desktop/nba_desktop_omega/reconcile_2026-07-10
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
  /c/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe \
  _fetch_br_2026_schedule.py
```

- 脚本加载 cookie → 抓 6 个月赛程页 → 解析 Visitor/Home 列 → 去重 → 写 `br_2026_rs.tsv`。
- 正常输出：`TOTAL BR 2025-26 RS games: <N>`（N 应 ≈ 1230）。
- 若打印 `!! no schedule table found` 且 N=0 → cookie 失效，回到路径 B 重新生成。

---

## 5. 验证（最终交付）

```bash
cd /c/autopick/AutoPick/nba_data/nba_desktop/nba_desktop_omega/reconcile_2026-07-10
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
  /c/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe \
  _diff_2026_missing.py
```

- 连库（host=localhost, port=5433, dbname=nba, user=postgres, password=postgres）diff `dim_games`（2026 RS）与 tsv。
- 输出 `MISSING in DB`（BR 有、DB 缺 → 需补爬）、`EXTRA in DB`（DB 有、BR 无 → 待复核）、`null_broken`（abbr 为 NULL 的坏行计数）。

---

## 6. 红线 / 注意事项

- **不要改** `nba_daily_crawler.py` 的 cookie 路径契约（reconcile 脚本依赖 `nba_data/.br_cf_cookies.pkl`）。
- cookie 文件含敏感 session 凭证，**不要提交进 git / 不要外传**。
- `_fetch_br_2026_schedule.py` **只消费 cookie、不回存**；别指望它自己生成 cookie。
- `cf_clearance` 有 TTL（通常数小时～1 天）。生成后**尽快**跑第 4、5 步，过期则需重来。

---

## 7. 完成判据（checklist）

- [ ] `C:\autopick\AutoPick\nba_data\.br_cf_cookies.pkl` 存在且未过期
- [ ] `…\reconcile_2026-07-10\br_2026_rs.tsv` 已生成，行数 ≈ 1230，无 `no schedule table` 报错
- [ ] `_diff_2026_missing.py` 跑通，给出 MISSING / EXTRA / null_broken 清单
