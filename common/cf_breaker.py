"""common/cf_breaker.py — Cloudflare 防撞 + 自恢复熔断器（全爬虫共用）。

设计目标（对齐 nba-br-crawler §0a「本地留档优先 / 防撞」）：
  BR 的 Cloudflare 挑战页**成片波动**（上午无头能过、下午封死、晚点又松），
  绝非偶发。底层网络层对「单个」请求会空转若干轮才放弃；若全局封禁，
  **每个**请求都空转 → 整夜空转烧 CF 预算（已踩坑 3 小时卡死）。

  所以本模块提供唯一权威机制：
    * 连续撞墙达 ``breach_limit`` → 判定**全局封禁**，进入**熔断冷却**
      （冷却期间**零线上请求** = 真·断掉撞击）。
    * 冷却结束 → **自动重置计数、续跑剩余**（自恢复），无需手动重开。
    * ``max_cooldowns=0``（默认）→ **无限自恢复**，持续续跑直到跑完。

用法（两种）：
  1. 网络层直接内嵌（推荐，覆盖最广，零爬虫改动）：
       ``common/browser.get()`` 与 ``common/player_page_cache.fetch_player_page``
       各挂一个模块级 ``CFBreaker``，撞墙即熔断、冷却后自恢复。
       → 几十个爬虫（gamelog / fill / headshots / transactions / injuries /
          contracts / schedule / nicknames / bio_ext ...）自动获得保护。
  2. 爬虫主循环显式持有（需要可调 CLI / 清晰日志时）：
       br = CFBreaker(cf_breach_limit, cf_backoff, cf_cooldown, cf_max_cooldowns)
       try:
           html = fetch(...)
           br.on_success()
       except CFChallengeError:
           if br.on_breach() == "giveup":
               break   # 冷却次数超限，放弃退出
           # 否则已冷却/退避，继续下一轮（自恢复）
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


class CFBreaker:
    """连续撞墙熔断 + 冷却自恢复。

    ``on_breach()`` 返回值语义：
        * ``"retry"``    — 未达熔断阈值，仅做了单次退避（``backoff``）。
        * ``"cooldown"``  — 触发了熔断冷却（已 sleep ``cooldown`` 秒，
                           期间零线上请求），计数已重置，可继续。
        * ``"giveup"``   — 冷却次数已达 ``max_cooldowns`` 上限，
                           调用方应放弃退出（避免无限占用）。
    """

    def __init__(self, breach_limit: int = 5, backoff: int = 30,
                 cooldown: int = 600, max_cooldowns: int = 0) -> None:
        self.breach_limit = breach_limit
        self.backoff = backoff
        self.cooldown = cooldown
        self.max_cooldowns = max_cooldowns
        self.consecutive = 0     # 连续撞墙计数（成功即重置）
        self.cooldown_count = 0   # 已发生冷却轮次（自恢复计数）

    def on_success(self) -> None:
        """一次成功抓取 → 重置连续撞墙计数。"""
        if self.consecutive:
            logger.debug("CFBreaker: 连续撞墙 %d → 0（恢复）", self.consecutive)
        self.consecutive = 0

    def on_breach(self) -> str:
        """记录一次撞墙，返回决策（见类 docstring）。

        调用方据此决定：继续(``retry``/``cooldown``) 还是放弃(``giveup``)。
        冷却的 sleep 在内部完成，调用方无需自己 sleep。
        """
        self.consecutive += 1
        if self.consecutive < self.breach_limit:
            # 未达熔断阈值：单次退避，降低再次挑战概率
            if self.backoff:
                time.sleep(self.backoff)
            return "retry"
        # 触发熔断
        self.cooldown_count += 1
        if self.max_cooldowns and self.cooldown_count > self.max_cooldowns:
            logger.error(
                "CFBreaker: 连续撞墙 %d 次 × 冷却 %d 轮 → 放弃退出",
                self.breach_limit, self.cooldown_count - 1,
            )
            self.consecutive = 0  # 放弃前重置，状态一致
            return "giveup"
        logger.error(
            "CFBreaker: 连续撞墙 %d 次 → 进入熔断冷却 %ds"
            "（断掉撞击，零线上请求）— 自恢复 #%d",
            self.breach_limit, self.cooldown, self.cooldown_count,
        )
        if self.cooldown:
            time.sleep(self.cooldown)
        self.consecutive = 0  # 冷却结束：重置，续跑剩余
        logger.info(
            "CFBreaker: 冷却结束，自动恢复抓取（第 %d 轮冷却）",
            self.cooldown_count,
        )
        return "cooldown"
