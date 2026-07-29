#!/usr/bin/env python3
"""
NBA Data Scraper — 基于 data.nba.com 移动 API + curl_cffi TLS 指纹模拟
========================================================================

绕过 Akamai 的策略：
  - stats.nba.com API 被 Akamai 锁死（多种浏览器/TLS 均返回 HTML 拦截页）
  - data.nba.com 是 NBA 移动端数据 API，使用 curl_cffi 模拟 Chrome TLS 指纹即可访问

已验证可用的端点:
  1. standings     — data/10s/v2015/json/mobile_teams/nba/{season}/00_standings.json
  2. scoreboard    — data/10s/v2015/json/mobile_teams/nba/{season}/scores/00_todays_scores.json
  3. game_detail   — data/10s/v2015/json/mobile_teams/nba/{season}/scores/gamedetail/{gid}_gamedetail.json

依赖:
  pip install curl_cffi

Author: Senior Developer
Date: 2026-06-18
"""

from __future__ import annotations

import json
import logging
import os
import time
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Any, Callable

from curl_cffi import requests as cffi_requests

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("NBADataScraper")


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                          CONFIGURATION                                      ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@dataclass
class ScraperConfig:
    """爬虫配置"""

    # API 基础 URL
    BASE_URL: str = "https://data.nba.com/data"
    API_VERSION: str = "10s/v2015/json/mobile_teams/nba"

    # 请求配置
    TIMEOUT: int = 30
    IMPERSONATE: str = "chrome124"  # curl_cffi TLS 指纹模拟

    # 限速 (每秒请求数)
    RATE_LIMIT_RPS: float = 2.0
    MIN_DELAY: float = 0.5
    MAX_DELAY: float = 5.0

    # 重试
    MAX_RETRIES: int = 3
    RETRY_DELAY_BASE: float = 2.0
    RETRY_BACKOFF: float = 2.0

    # 数据目录
    DATA_DIR: str = "data/nba_api"

    # 默认赛季
    DEFAULT_SEASON: str = "2025"

    # 请求头
    HEADERS: Dict[str, str] = field(default_factory=lambda: {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                      " (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://www.nba.com/",
    })


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                          SMART SCHEDULER                                    ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class SmartScheduler:
    """智能请求调度器 — 限速 + 重试 + 指数退避"""

    def __init__(self, config: ScraperConfig):
        self.config = config
        self._last_request: float = 0.0
        self._request_count: int = 0
        self._hourly_count: int = 0
        self._hour_start: float = time.time()

    def wait(self):
        """等待直到满足速率限制"""
        now = time.time()

        # 重置每小时计数
        if now - self._hour_start > 3600:
            self._hourly_count = 0
            self._hour_start = now

        # 速率限制间隔
        elapsed = now - self._last_request
        min_interval = 1.0 / self.config.RATE_LIMIT_RPS
        if elapsed < min_interval:
            sleep_time = min_interval - elapsed + random.uniform(0, 0.3)
            time.sleep(sleep_time)

        self._last_request = time.time()
        self._request_count += 1
        self._hourly_count += 1

    def retry_delay(self, attempt: int) -> float:
        """指数退避延迟"""
        return self.config.RETRY_DELAY_BASE * (self.config.RETRY_BACKOFF ** attempt) \
               + random.uniform(0, 1.0)

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "total_requests": self._request_count,
            "hourly_requests": self._hourly_count,
            "rate_limit": self.config.RATE_LIMIT_RPS,
        }


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                          NBA DATA API CLIENT                                ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class NBADataClient:
    """NBA data.nba.com 移动 API 客户端

    使用 curl_cffi 模拟 Chrome TLS 指纹绕过 Akamai 检测。
    data.nba.com 是 NBA 移动端数据源，防护级别低于 stats.nba.com。
    """

    def __init__(self, config: Optional[ScraperConfig] = None):
        self.config = config or ScraperConfig()
        self.scheduler = SmartScheduler(self.config)

        # 确保数据目录存在
        os.makedirs(self.config.DATA_DIR, exist_ok=True)

        logger.info(f"NBADataClient 初始化 | API: {self.config.BASE_URL} "
                     f"| TLS: {self.config.IMPERSONATE} "
                     f"| RPS: {self.config.RATE_LIMIT_RPS}")

    # ── 核心请求方法 ──────────────────────────────────────────────────────────

    def _get(self, path: str, params: Optional[Dict] = None,
             retries: Optional[int] = None) -> Optional[Dict]:
        """GET 请求到 data.nba.com，带重试和 TLS 模拟

        Args:
            path: API 路径（相对 BASE_URL）
            params: 查询参数
            retries: 重试次数（None = 使用配置默认值）

        Returns:
            解析后的 JSON 字典，失败返回 None
        """
        url = f"{self.config.BASE_URL}/{path}"
        retries = retries if retries is not None else self.config.MAX_RETRIES

        for attempt in range(retries + 1):
            try:
                self.scheduler.wait()

                resp = cffi_requests.get(
                    url,
                    params=params,
                    headers=self.config.HEADERS,
                    impersonate=self.config.IMPERSONATE,
                    timeout=self.config.TIMEOUT,
                )

                if resp.status_code == 200:
                    text = resp.text.strip()
                    if text.startswith("{"):
                        return resp.json()
                    else:
                        logger.warning(f"非 JSON 响应 (len={len(text)}): {text[:150]}")
                        if attempt < retries:
                            delay = self.scheduler.retry_delay(attempt)
                            time.sleep(delay)
                            continue
                        return None

                elif resp.status_code == 403:
                    logger.warning(f"403 Forbidden: {url[:80]} (可能频率过高)")
                    if attempt < retries:
                        delay = self.scheduler.retry_delay(attempt) * 2
                        logger.info(f"  等待 {delay:.1f}s 后重试...")
                        time.sleep(delay)
                        continue

                elif resp.status_code == 404:
                    logger.debug(f"404 Not Found: {path}")
                    return None

                else:
                    logger.warning(f"HTTP {resp.status_code}: {url[:80]}")
                    if attempt < retries:
                        delay = self.scheduler.retry_delay(attempt)
                        time.sleep(delay)
                        continue

            except Exception as e:
                logger.warning(f"请求异常 (attempt {attempt+1}/{retries+1}): {e}")
                if attempt < retries:
                    delay = self.scheduler.retry_delay(attempt)
                    time.sleep(delay)
                    continue

        logger.error(f"请求失败 (已重试 {retries} 次): {path}")
        return None

    # ── Standings ─────────────────────────────────────────────────────────────

    def get_standings(self, season: Optional[str] = None) -> Optional[Dict]:
        """获取联盟战绩排名

        Returns:
            {
                "sta": {
                    "gdte": "2025-04-13",
                    "co": [
                        {"val": "East", "di": [
                            {"val": "Atlantic", "t": [
                                {"tid": 1610612761, "tn": "Raptors", "ta": "TOR",
                                 "tc": "Toronto", "w": 30, "l": 52, ...}
                            ]}
                        ]}
                    ]
                }
            }
        """
        season = season or self.config.DEFAULT_SEASON
        path = f"{self.config.API_VERSION}/{season}/00_standings.json"

        logger.info(f"📊 获取战绩: season={season}")
        return self._get(path)

    # ── Scoreboard ────────────────────────────────────────────────────────────

    def get_scoreboard(self, season: Optional[str] = None) -> Optional[Dict]:
        """获取今日赛程/比分

        Returns:
            {
                "gs": {
                    "mid": ..., "gdte": "2025-10-14",
                    "g": [
                        {
                            "gid": "0012500057", "gcode": "20251014/DETCLE",
                            "p": 4, "st": 3, "stt": "Final",
                            "v": {"ta": "DET", "s": 100, "q1":31, ...},
                            "h": {"ta": "CLE", "s": 118, ...}
                        }
                    ]
                }
            }
        """
        season = season or self.config.DEFAULT_SEASON
        path = f"{self.config.API_VERSION}/{season}/scores/00_todays_scores.json"

        logger.info(f"📡 获取比分: season={season}")
        return self._get(path)

    # ── Game Detail ───────────────────────────────────────────────────────────

    def get_game_detail(self, game_id: str, season: Optional[str] = None) -> Optional[Dict]:
        """获取单场比赛详情

        Args:
            game_id: 10位比赛ID (如 "0022500001")
            season: 赛季 (如 "2025")

        Returns:
            {
                "g": {
                    "gid": "0022500001", "gcode": "20251021/HOUOKC",
                    "gdte": "2025-10-21", "st": 1, "stt": "7:30 pm ET",
                    "vls": {"tid": ..., "ta": "HOU", "tn": "Rockets", "s": "0"},
                    "hls": {"tid": ..., "ta": "OKC", "tn": "Thunder", "s": "0"},
                    "an": "Paycom Center", "ac": "Oklahoma City", ...
                }
            }
        """
        season = season or self.config.DEFAULT_SEASON
        path = f"{self.config.API_VERSION}/{season}/scores/gamedetail/{game_id}_gamedetail.json"

        logger.info(f"🎯 获取比赛详情: {game_id}")
        return self._get(path)

    # ── Batch Operations ──────────────────────────────────────────────────────

    def get_all_games_in_range(self, start_gid: str, end_gid: str,
                                season: Optional[str] = None,
                                callback: Optional[Callable] = None) -> List[Dict]:
        """批量获取比赛详情（顺序递增 game_id）

        Args:
            start_gid: 起始 game_id (如 "0022500001")
            end_gid: 结束 game_id (如 "0022500100")
            season: 赛季
            callback: 每场回调 (gid, data) -> None

        Returns:
            成功获取的比赛数据列表
        """
        season = season or self.config.DEFAULT_SEASON
        start = int(start_gid)
        end = int(end_gid)
        results = []

        logger.info(f"📚 批量获取比赛: {start_gid} → {end_gid} (共 {end - start + 1} 场)")

        for gid_num in range(start, end + 1):
            gid = str(gid_num).zfill(10)
            data = self.get_game_detail(gid, season)

            if data:
                results.append(data)
                if callback:
                    callback(gid, data)

            # 进度日志
            if (gid_num - start + 1) % 50 == 0:
                progress = (gid_num - start + 1) / (end - start + 1) * 100
                logger.info(f"  进度: {progress:.0f}% ({gid_num - start + 1}/{end - start + 1})")

        logger.info(f"✅ 批量获取完成: {len(results)}/{end - start + 1} 成功")
        return results

    def get_standings_all_seasons(self, seasons: List[str]) -> Dict[str, Dict]:
        """获取多个赛季的战绩

        Args:
            seasons: 赛季列表 (如 ["2023", "2024", "2025"])

        Returns:
            {season: standings_data}
        """
        results = {}
        for season in seasons:
            data = self.get_standings(season)
            if data:
                results[season] = data
            time.sleep(random.uniform(0.5, 1.5))
        return results

    # ── Data Export ───────────────────────────────────────────────────────────

    def save_json(self, data: Any, filename: str, subdir: str = ""):
        """保存数据为 JSON 文件"""
        dir_path = Path(self.config.DATA_DIR) / subdir
        dir_path.mkdir(parents=True, exist_ok=True)
        filepath = dir_path / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"💾 已保存: {filepath} ({len(json.dumps(data))} bytes)")

    def save_standings(self, season: Optional[str] = None):
        """获取并保存战绩"""
        data = self.get_standings(season)
        if data:
            season = season or self.config.DEFAULT_SEASON
            self.save_json(data, f"standings_{season}.json", f"season_{season}")

    def save_scoreboard(self, season: Optional[str] = None):
        """获取并保存今日比分"""
        data = self.get_scoreboard(season)
        if data:
            season = season or self.config.DEFAULT_SEASON
            date_str = data.get("gs", {}).get("gdte", datetime.now().strftime("%Y%m%d"))
            self.save_json(data, f"scoreboard_{date_str}.json", f"season_{season}")

    # ── Stats ─────────────────────────────────────────────────────────────────

    @property
    def stats(self) -> Dict[str, Any]:
        return self.scheduler.stats


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                          DATA PARSER                                        ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class NBADataParser:
    """NBA 数据解析器 — 将 API 原生格式转为结构化数据"""

    @staticmethod
    def parse_standings(data: Dict) -> List[Dict]:
        """解析战绩为扁平化列表

        Returns:
            [{tid, team_name, team_abbr, city, conference, division, wins, losses, ...}]
        """
        sta = data.get("sta", {})
        teams = []

        for conf in sta.get("co", []):
            conf_name = conf.get("val", "")
            for div in conf.get("di", []):
                div_name = div.get("val", "")
                for t in div.get("t", []):
                    teams.append({
                        "team_id": t.get("tid"),
                        "team_name": t.get("tn"),
                        "team_abbr": t.get("ta"),
                        "city": t.get("tc"),
                        "conference": conf_name,
                        "division": div_name,
                        "wins": t.get("w"),
                        "losses": t.get("l"),
                        "win_pct": round(t.get("w", 0) / max(t.get("w", 0) + t.get("l", 0), 1), 3),
                        "home_wins": t.get("hw"),
                        "home_losses": t.get("hl"),
                        "away_wins": t.get("aw"),
                        "away_losses": t.get("al"),
                        "conf_wins": t.get("cw"),
                        "conf_losses": t.get("cl"),
                        "div_wins": t.get("dw"),
                        "div_losses": t.get("dl"),
                        "last10_wins": t.get("l10w"),
                        "last10_losses": t.get("l10l"),
                        "streak": t.get("str"),
                        "points_for": t.get("pf"),
                        "points_against": t.get("pa"),
                        "diff": t.get("d"),
                    })
        return teams

    @staticmethod
    def parse_scoreboard(data: Dict) -> List[Dict]:
        """解析比分板为游戏列表

        Returns:
            [{game_id, date, status, away_team, home_team, away_score, home_score,
              quarters, is_playoffs, series_info}]
        """
        gs = data.get("gs", {})
        games = []

        for g in gs.get("g", []):
            v = g.get("v", {})
            h = g.get("h", {})
            lm = g.get("lm", {})

            games.append({
                "game_id": g.get("gid"),
                "game_code": g.get("gcode"),
                "date": gs.get("gdte", ""),
                "status": g.get("st"),  # 1=scheduled, 2=live, 3=final
                "status_text": g.get("stt"),
                "clock": g.get("cl"),
                "is_playoffs": g.get("p", 0) == 4,
                "period": g.get("p"),
                # Away team
                "away_team_id": v.get("tid"),
                "away_abbr": v.get("ta"),
                "away_name": v.get("tn"),
                "away_city": v.get("tc"),
                "away_score": v.get("s"),
                "away_q1": v.get("q1"),
                "away_q2": v.get("q2"),
                "away_q3": v.get("q3"),
                "away_q4": v.get("q4"),
                # Home team
                "home_team_id": h.get("tid"),
                "home_abbr": h.get("ta"),
                "home_name": h.get("tn"),
                "home_city": h.get("tc"),
                "home_score": h.get("s"),
                "home_q1": h.get("q1"),
                "home_q2": h.get("q2"),
                "home_q3": h.get("q3"),
                "home_q4": h.get("q4"),
                # Series info (playoffs)
                "series_summary": lm.get("seri", ""),
            })
        return games

    @staticmethod
    def parse_game_detail(data: Dict) -> Optional[Dict]:
        """解析比赛详情

        Returns:
            {game_id, date, status, home_team, away_team, arena, ...}
        """
        g = data.get("g", {})
        if not g:
            return None

        vls = g.get("vls", {})
        hls = g.get("hls", {})

        return {
            "game_id": g.get("gid"),
            "game_code": g.get("gcode"),
            "date": g.get("gdte"),
            "time_et": g.get("stt"),
            "time_utc": f"{g.get('gdtutc', '')}T{g.get('utctm', '')}",
            "status": g.get("st"),
            "status_text": g.get("stt"),
            # Away
            "away_team_id": vls.get("tid"),
            "away_abbr": vls.get("ta"),
            "away_name": vls.get("tn"),
            "away_city": vls.get("tc"),
            "away_score": vls.get("s"),
            "away_q1": vls.get("q1"),
            "away_q2": vls.get("q2"),
            "away_q3": vls.get("q3"),
            "away_q4": vls.get("q4"),
            # Home
            "home_team_id": hls.get("tid"),
            "home_abbr": hls.get("ta"),
            "home_name": hls.get("tn"),
            "home_city": hls.get("tc"),
            "home_score": hls.get("s"),
            "home_q1": hls.get("q1"),
            "home_q2": hls.get("q2"),
            "home_q3": hls.get("q3"),
            "home_q4": hls.get("q4"),
            # Arena
            "arena_name": g.get("an"),
            "arena_city": g.get("ac"),
            "arena_state": g.get("as"),
            "duration": g.get("dur"),
        }


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                          MAIN — 演示 / 测试                                 ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

if __name__ == "__main__":
    print("=" * 70)
    print("  NBA Data Scraper — data.nba.com 移动 API")
    print("=" * 70)

    client = NBADataClient()
    parser = NBADataParser()

    # ── Test 1: Standings ──
    print("\n" + "─" * 50)
    print("  [1/3] 获取战绩排名")
    print("─" * 50)

    standings = client.get_standings("2025")
    if standings:
        teams = parser.parse_standings(standings)
        print(f"  ✅ 获取到 {len(teams)} 支球队战绩")

        # 显示前5
        sorted_teams = sorted(teams, key=lambda t: t["win_pct"], reverse=True)
        for t in sorted_teams[:5]:
            print(f"     {t['team_name']:20s} {t['wins']:3d}-{t['losses']:<3d} "
                  f"({t['win_pct']:.3f}) [{t['conference']}]")

        client.save_json(teams, "standings_flat.json", "parsed")

    # ── Test 2: Scoreboard ──
    print("\n" + "─" * 50)
    print("  [2/3] 获取今日比分")
    print("─" * 50)

    scoreboard = client.get_scoreboard("2025")
    if scoreboard:
        games = parser.parse_scoreboard(scoreboard)
        status_text = scoreboard.get("gs", {}).get("gdte", "?")
        print(f"  ✅ 日期: {status_text}, {len(games)} 场比赛")

        for g in games:
            print(f"     {g['away_abbr']:4s} {g['away_score']:3d} @ "
                  f"{g['home_abbr']:4s} {g['home_score']:3d}  "
                  f"[{g['status_text']}]")

    # ── Test 3: Game Detail ──
    print("\n" + "─" * 50)
    print("  [3/3] 获取比赛详情")
    print("─" * 50)

    game = client.get_game_detail("0022500001", "2025")
    if game:
        detail = parser.parse_game_detail(game)
        print(f"  ✅ {detail['away_abbr']} @ {detail['home_abbr']}")
        print(f"     日期: {detail['date']} | 时间: {detail['time_et']}")
        print(f"     场馆: {detail['arena_name']}, {detail['arena_city']}")

    # ── Summary ──
    print("\n" + "=" * 70)
    print(f"  完成! 请求统计: {client.stats}")
    print("=" * 70)
