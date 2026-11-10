#!/usr/bin/env python3
"""
adapters/br_pbp_adapter.py — v2 的 Basketball-Reference 逐回合(PBP)适配器。

设计原则（严格遵守"严禁凭空猜"）：
  - 不重写解析逻辑。直接复用旧版已验证函数：
      * br_fill_pbp.build_driver / fetch_pbp_soup / to_br_gid / _br_team_code
      * br_pbp_parse.parse_pbp
      * raw_archiver.save_br_html（原始 HTML 落盘，离线重解析用）
      * br_fill_pbp.extract_semantics / collect_issues / SEMANTIC_SQL / ISSUES_SQL / INSERT_SQL
  - 只把"编排"搬进 v2 抽象层：BaseCrawler 的限流/缓存/Store，process 走 3 表幂等写入。
  - DB 写入严守 §6：经 PGStore（参数化、DELETE+INSERT 幂等、key=gameid）。

运行：
  python -m adapters.br_pbp_adapter --limit 3 --dry-run
  python -m adapters.br_pbp_adapter --seasons 2023 2024 2025 2026
"""
import argparse
import importlib.util
import logging
import os
import sys

# 把迁移包根目录加入 path，以便复用旧版已验证模块（单向复用，旧版不被修改）
ROOT = "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13"
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.base_crawler import BaseCrawler, SessionGone
from core.store import StoreFactory

log = logging.getLogger("br_crawler_v2.br_pbp")

# ---- 单向复用旧版已验证函数（不重造） ----
import raw_archiver  # type: ignore
from br_fill_pbp import (  # type: ignore
    INSERT_SQL,
    ISSUES_SQL,
    SEMANTIC_SQL,
    _br_team_code,
    build_driver,
    collect_issues,
    extract_semantics,
    fetch_pbp_soup,
    to_br_gid,
)
from br_pbp_parse import parse_pbp  # type: ignore

BASE = "https://www.basketball-reference.com/boxscores/pbp/{gid}.html"
RAW_DIR = os.path.join(ROOT, "external_crawler", "crawler", "pbp_raw")
UDC_DIR = os.path.join(ROOT, "external_crawler", "crawler", ".uc_pbp_profile")
MAX_PAGE_RETRY = 3

PBP_COLUMNS = [
    "gameid", "season", "eventnum", "period", "clock", "clock_seconds",
    "h_pts", "a_pts", "team", "playerid", "player",
    "event_type", "subtype", "action_verb", "result", "x", "y", "dist", "description", "current_team",
    "homedescription", "visitordescription", "neutraldescription",
    "scorehome", "scorevisitor", "scoremargin", "source",
]
SEMANTIC_COLUMNS = ["gameid", "eventnum", "actor", "actor_team", "action",
                    "action_detail", "outcome", "points", "raw_description"]
ISSUE_COLUMNS = ["gameid", "br_gid", "eventnum", "issue_type", "raw_text"]


class BrPbpAdapter(BaseCrawler):
    """BR 逐回合爬取适配器（v2 抽象层 + 旧版解析函数）。"""

    def __init__(self, store=None, cache_dir=None, rate_per_min=15, min_interval=4.5,
                 dry_run=False):
        super().__init__(store=store or StoreFactory.create("pg"),
                         cache_ttl=0, cache_dir=cache_dir,
                         rate_per_min=rate_per_min, min_interval=min_interval)
        self.dry_run = dry_run
        self.driver = None

    # ---- 复用旧版 fetch 语义（持有 driver + SessionGone 重建） ----
    def _ensure_driver(self):
        if self.driver is None:
            self.driver = build_driver()
        return self.driver

    def fetch(self, target):
        gid, gdate, season, a_abbr, h_abbr = target
        br_gid = to_br_gid(gid, gdate)
        url = BASE.format(gid=br_gid)
        driver = self._ensure_driver()
        soup, status = None, None
        for _ in range(1, MAX_PAGE_RETRY + 1):
            try:
                self.limiter.wait()
                soup, status = fetch_pbp_soup(driver, url, br_gid, season=season)
                if soup is not None or status == "404":
                    break
            except SessionGone:
                log.warning("driver 崩溃, 重建中... (%s)", gid)
                try:
                    self.driver.quit()
                except Exception:
                    pass
                self.driver = build_driver()
        if soup is None:
            return {"status": status, "br_gid": br_gid, "gid": gid}
        return {"status": "ok", "soup": soup, "br_gid": br_gid, "gid": gid,
                "season": season, "a_abbr": a_abbr, "h_abbr": h_abbr}

    def parse(self, raw, target):
        if not isinstance(raw, dict) or raw.get("status") != "ok":
            return raw  # 透传状态（404/cf_timeout/...）
        gid = raw["gid"]
        a_abbr, h_abbr = raw["a_abbr"], raw["h_abbr"]
        rows = parse_pbp(raw["soup"], a_abbr or "", h_abbr or "", gid)
        return {"status": "ok", "rows": rows, "br_gid": raw["br_gid"],
                "gid": gid, "season": raw["season"]}

    def normalize(self, parsed, target):
        if not isinstance(parsed, dict) or parsed.get("status") != "ok":
            return parsed
        rows = parsed["rows"]
        for r in rows:
            r["season"] = parsed["season"]
            r["source"] = r.get("source") or "BBRef"
        return parsed

    # ---- 覆盖 run：PBP 需写 3 张表 + 404 标脏 + 原始归档 ----
    def run(self, targets):
        ok = fail = total_events = 0
        fails = []
        try:
            for i, t in enumerate(targets, 1):
                fetched = self.fetch(t)
                if not isinstance(fetched, dict) or fetched.get("status") != "ok":
                    status = fetched.get("status") if isinstance(fetched, dict) else "fetch_fail"
                    log.warning("[%d/%d] %s FAIL(%s)", i, len(targets), t[0], status)
                    fail += 1
                    fails.append((t[0], status))
                    if status == "404" and not self.dry_run:
                        self._mark_no_data(t[0])
                    continue
                parsed = self.parse(fetched, t)
                if not isinstance(parsed, dict) or parsed.get("status") != "ok":
                    fail += 1
                    fails.append((t[0], "parse_fail"))
                    continue
                rows = parsed["rows"]
                if not rows:
                    log.warning("[%d/%d] %s FAIL(parsed_0_events)", i, len(targets), t[0])
                    fail += 1
                    fails.append((t[0], "parsed_0"))
                    continue
                semantics = extract_semantics(rows)
                issues = collect_issues(rows, parsed["gid"], parsed["br_gid"])
                log.info("[%d/%d] %s S%s %s@%s events=%d semantic=%d issues=%d",
                         i, len(targets), t[0], parsed["season"], t[3], t[4],
                         len(rows), len(semantics), len(issues))
                if not self.dry_run:
                    self.store.save("play_by_play", PBP_COLUMNS, ["gameid"], rows)
                    if semantics:
                        self.store.save("pbp_semantic", SEMANTIC_COLUMNS, ["gameid"], semantics)
                    if issues:
                        self.store.save("pbp_parse_issues", ISSUE_COLUMNS, ["gameid"], issues)
                    self._mark_imported(t[0])
                total_events += len(rows)
                ok += 1
        finally:
            if self.driver is not None:
                try:
                    self.driver.quit()
                except Exception:
                    pass
            try:
                self.store.close()
            except Exception:
                pass
        log.info("[done] 成功 %d 失败 %d 事件 %d", ok, fail, total_events)
        if fails:
            log.info("失败明细: %s", fails[:30])
        return {"ok": ok, "fail": fail, "rows": total_events}

    def _mark_no_data(self, gid):
        # 对称于旧版：404 => 标记 pbp_no_data=true（BR 权威源无此 PBP），永不再爬
        try:
            self.store.save.__self__  # no-op guard
        except Exception:
            pass
        # 直接走 store 连接做 UPDATE（§6：参数化）
        conn = self.store._connect()
        with conn.cursor() as cur:
            cur.execute("UPDATE dim_games SET pbp_no_data=true WHERE game_id=%s", (gid,))
        conn.commit()

    def _mark_imported(self, gid):
        conn = self.store._connect()
        with conn.cursor() as cur:
            cur.execute("UPDATE dim_games SET pbp_imported=true WHERE game_id=%s", (gid,))
        conn.commit()


def _get_targets(limit=0, since=None, seasons=None):
    """复用旧版缺口查询逻辑（SQL 同 br_fill_pbp.get_targets，避免重造）。"""
    import psycopg2
    from core.config import get_db_config
    conn = psycopg2.connect(**get_db_config())
    try:
        from br_fill_pbp import get_targets  # type: ignore
        return get_targets(conn, limit, since=since, seasons=seasons)
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rate-per-min", type=int, default=15)
    ap.add_argument("--min-interval", type=float, default=4.5)
    ap.add_argument("--since", type=str, default=None)
    ap.add_argument("--seasons", nargs="+", type=int, default=None)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    targets = _get_targets(limit=args.limit, since=args.since, seasons=args.seasons)
    log.info("待处理 PBP 缺口: %d (dry_run=%s)", len(targets), args.dry_run)
    if not targets:
        return
    adapter = BrPbpAdapter(rate_per_min=args.rate_per_min, min_interval=args.min_interval,
                           dry_run=args.dry_run)
    adapter.run(targets)


if __name__ == "__main__":
    main()
