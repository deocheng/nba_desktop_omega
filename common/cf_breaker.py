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
  * 冷却时长**自适应递增**（``cooldown_max``/``cooldown_growth`` 控制）：
    持续撞墙时每轮冷却翻倍（600→1200→2400→封顶 3600），模拟「人手动
    停更久 CF 才过」的负反馈——爬虫自己越停越久，直到挑战自然解除。

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
        * ``"cooldown"``  — 触发了熔断冷却（已 sleep 本轮冷却秒数，
                           期间零线上请求），计数已重置，可继续。
        * ``"giveup"``   — 冷却次数已达 ``max_cooldowns`` 上限，
                           调用方应放弃退出（避免无限占用）。

    自适应冷却（核心设计，对齐「手动停更久 CF 才过」的负反馈观测）：
        第 N 轮冷却时长 = ``cooldown * cooldown_growth ** (N-1)``，
        并封顶 ``cooldown_max``。
        默认 600 * 2**(N-1) → 600 / 1200 / 2400 / 3600(封顶) 秒。
        含义：持续撞墙时，爬虫自己越停越久，直到 Cloudflare 风险评分
        衰减、挑战自然解除（等价于「人手动停一阵就过了」），无需人工介入。
        ``cooldown_count`` 在整个进程生命周期内单调递增（不在成功时重置），
        确保「反复撞墙→最长退避」的升级路径；``cooldown_max`` 兜底上限。

    时间触发（用户 2026-07-30 补充「连续 2 分钟没过墙就暂停」）：
        除计数阈值 ``breach_limit`` 外，再叠加**持续撞墙时长**触发——
        自首次连续撞墙起，若 ``now - streak_start >= cooldown_trigger_s``
        （默认 120s），**无论计数是否达 ``breach_limit``** 都立即熔断冷却。
        含义：刷了 2 分钟全是墙（一次都没过），爬虫就自己停下来，
        不必傻等计数阈值；``on_success()`` 会清零计时，过一次墙即打断连击。
        计数触发与时间触发「任一满足即熔断」，更贴合真实风控节奏。
    """

    def __init__(self, breach_limit: int = None, backoff: int = None,
                 cooldown: int = None, max_cooldowns: int = None,
                 cooldown_max: int = None,
                 cooldown_growth: float = None,
                 cooldown_trigger_s: int = None) -> None:
        import os as _os
        _e = _os.environ
        # 默认从 CF_* 环境变量读取（调度器可全局注入，控制撞墙后的退出速度）；
        # 显式传参优先（向后兼容 browser._BREAKER 与各爬虫 CLI 传值）。
        self.breach_limit = breach_limit if breach_limit is not None else int(_e.get("CF_BREACH_LIMIT", "5"))
        self.backoff = backoff if backoff is not None else int(_e.get("CF_BACKOFF", "30"))
        self.cooldown = cooldown if cooldown is not None else int(_e.get("CF_COOLDOWN", "600"))
        self.max_cooldowns = max_cooldowns if max_cooldowns is not None else int(_e.get("CF_MAX_COOLDOWNS", "0"))
        self.cooldown_max = cooldown_max if cooldown_max is not None else int(_e.get("CF_COOLDOWN_MAX", "3600"))
        self.cooldown_growth = cooldown_growth if cooldown_growth is not None else float(_e.get("CF_COOLDOWN_GROWTH", "2.0"))
        self.cooldown_trigger_s = cooldown_trigger_s if cooldown_trigger_s is not None else int(_e.get("CF_COOLDOWN_TRIGGER_S", "120"))
        self.consecutive = 0     # 连续撞墙计数（成功即重置）
        self.cooldown_count = 0   # 已发生冷却轮次（自恢复计数，单调升）
        self.streak_start = None  # 连续撞墙起点（用于"连续 N 秒没过墙"计时）

    def on_success(self) -> None:
        """一次成功抓取 → 重置连续撞墙计数与连击计时。"""
        if self.consecutive:
            logger.debug("CFBreaker: 连续撞墙 %d → 0（恢复）", self.consecutive)
        self.consecutive = 0
        self.streak_start = None  # 过一次墙即打断"连续没过墙"连击计时

    def on_breach(self) -> str:
        """记录一次撞墙，返回决策（见类 docstring）。

        调用方据此决定：继续(``retry``/``cooldown``) 还是放弃(``giveup``)。
        冷却的 sleep 在内部完成，调用方无需自己 sleep。
        """
        now = time.time()
        if self.consecutive == 0:
            self.streak_start = now  # 连击起点：首次撞墙开始计时
        self.consecutive += 1
        streak_s = (now - self.streak_start) if self.streak_start else 0
        # 双重触发：计数达 breach_limit，或持续撞墙时长达 cooldown_trigger_s
        if (self.consecutive < self.breach_limit
                and streak_s < self.cooldown_trigger_s):
            # 未达任一熔断阈值：单次退避，降低再次挑战概率
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
        # 自适应冷却：第 N 轮 = cooldown * growth**(N-1)，封顶 cooldown_max
        trigger = "count" if self.consecutive >= self.breach_limit else "time"
        actual_cooldown = int(min(
            self.cooldown * (self.cooldown_growth ** (self.cooldown_count - 1)),
            self.cooldown_max,
        ))
        logger.error(
            "CFBreaker: 连续撞墙 %d 次 / 持续 %.0fs（触发=%s） → 进入熔断冷却 %ds"
            "（断掉撞击，零线上请求；自适应第 %d 轮，"
            "基准 %ds ×增长 %.2f→封顶 %ds）— 自恢复",
            self.consecutive, streak_s, trigger, actual_cooldown,
            self.cooldown_count,
            self.cooldown, self.cooldown_growth, self.cooldown_max,
        )
        if actual_cooldown:
            time.sleep(actual_cooldown)
        self.consecutive = 0  # 冷却结束：重置，续跑剩余
        logger.info(
            "CFBreaker: 冷却结束（本轮 %ds），自动恢复抓取（第 %d 轮冷却）",
            actual_cooldown, self.cooldown_count,
        )
        return "cooldown"
