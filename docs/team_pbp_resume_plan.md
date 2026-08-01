# Team PBP 全量 Resume 方案（节流 + 断连保护）

> 状态：**准备稿**（2026-07-27）。启动需用户明确批准 + 确认 CF 已清。
> 范围仅 `team_pbp_raw`（Regular 缺口 + 全部 Playoffs）；球队级其它 PO 表空缺另议。

## 一、现状核对（2026-07-27，只读 DB）
- `team_pbp_raw`：仅 **Regular** 49,790 行 / 16 季 / 25 队；**Playoffs = 0 行**。
- 上一轮「Previous Season 按钮导航」bug → 2023/2021/2020/2018/2016/2014/2012/2011/2009/2008/2006 整季 0 行（按钮落空页，pbp_stats 未注入 DOM）。
- PO 解析逻辑**已离线验证正确**（`/tmp/verify_po.py` 对 SAS 2025-26 真实队页跑通，可见 `pbp_stats_po` 表可解析出多行）。0 行源于空页面，非解析 bug。

## 二、已落地的修正（未实跑）
- `common/br_team_page.py`：`_nav_button` 改为「点按钮仅用于解析邻季正确 URL（处理球队迁徙 OKC→SEA），随后强制 `driver.get(url)` 重新加载」，确保 `pbp_stats` / `pbp_stats_post` 注入 DOM。
- `_crawl_team`：首季 GET 载入，之后每季用按钮解析出的 URL 走 `driver.get`。

## 三、启动命令（节流 + 防休眠 + 断连重试 + resume）
```bash
# 前置检查：无 /tmp/br_cf_challenge.flag；Chrome CDP 9223 在线；5433 业务库已起
caffeinate -ims \
BROWSER_BACKEND=cdp CHROME_CDP_URL=http://127.0.0.1:9223 \
DB_PASSWORD='R!h0N-ctlg=xB01V_-1VJcFeCCuBjS6UCvV1' \
nohup .venv/bin/python external_crawler/crawler/crawl_br_team_pbp.py \
  --all-seasons --start-season 2000 --caffeinate \
  > /tmp/full_pbp_resume.log 2>&1 &
```
- `--resume` 默认开：已落库季（含 2000–2002）自动跳过，只补缺口 + 全部 Playoffs。
- 单队重试环（已内置）：连接异常 → `reset_driver()` + 重连 + 等 15s 重试。

## 四、节流设置（防触发访问限制 · 铁律 #0）
- 同会话内逐季导航（减少重复 GET / CF 触发）。
- 每季间建议 `time.sleep(1~2s)`（若基类 `_crawl_one` 未加，需补）。
- **严禁**无 `--resume` 整量重跑；**严禁**并发多进程打 BR。
- 任何实跑前先确认 CF 标记无、9223 在线、5433 起。

## 五、验证门禁
1. 启动后 ~5 分钟：查 log，确认「无 pbp_stats 表」消失、ATL/2025 等按钮季开始有数。
2. 跑一批后 DB 抽查：
   ```sql
   SELECT season, season_type, count(*)
   FROM team_pbp_raw GROUP BY season, season_type ORDER BY season DESC;
   ```
   应见每季 Regular +（打进季后赛的队）Playoffs 均有行。

## 六、Logo 管线（已建 `common/logo_store.py`）
- 队页抓取时顺带抽取 `<img class="teamlogo">` src，节流落盘到
  `/Volumes/12T/NBA/logo/{slug}-{year}.png`（保留 BR 原始命名，幂等跳过）。
- 已离线测试抽取逻辑（`/tmp/test_logo_extract.py`）；下载部分在实跑时随队页抓取触发。
- 启动前需在 `_crawl_one` 接入 `extract_team_logo_src` + `save_team_logo` 钩子。

## 七、不在本次范围
- `team_lineups` / `team_on_off` / `team_shooting` / `league_averages` 的 Playoffs 空缺
  （均为 0 行），以及 `playoff_player_advanced` / `playoff_player_per_100`（0 行）。
  这些需另起各自爬虫，单独评估。
