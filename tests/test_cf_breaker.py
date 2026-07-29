"""CFBreaker 类单元测试（不启动浏览器 / 不连库）。

验证「连续撞墙 → 熔断冷却 → 自恢复」核心状态机：
  * on_success 重置连续计数
  * on_breach 未达上限返回 "retry"（含 backoff sleep）
  * on_breach 达上限返回 "cooldown"（sleep cooldown + 重置计数 + 计数冷却轮次）
  * 冷却轮次超 max_cooldowns 返回 "giveup"
  * cooldown 默认 0 = 无限自恢复（永不给 up）

这是 nba-br-crawler §0a 防撞机制的权威测试。
"""
import time

import pytest

from common.cf_breaker import CFBreaker


def test_success_resets_consecutive():
    b = CFBreaker(breach_limit=3, backoff=0, cooldown=0)
    b.on_breach()
    b.on_breach()
    assert b.consecutive == 2
    b.on_success()
    assert b.consecutive == 0


def test_breach_below_limit_returns_retry():
    b = CFBreaker(breach_limit=3, backoff=0, cooldown=0)
    assert b.on_breach() == "retry"
    assert b.consecutive == 1
    assert b.cooldown_count == 0


def test_breach_at_limit_trigers_cooldown_and_resets():
    b = CFBreaker(breach_limit=3, backoff=0, cooldown=0)
    assert b.on_breach() == "retry"
    assert b.on_breach() == "retry"
    dec = b.on_breach()  # 第 3 次 = 达上限
    assert dec == "cooldown"
    assert b.consecutive == 0   # 冷却结束：重置
    assert b.cooldown_count == 1


def test_cooldown_sleeps_about_cooldown_seconds():
    # breach_limit=1：每次撞墙即达上限 → cooldown（sleep cooldown）
    b = CFBreaker(breach_limit=1, backoff=0, cooldown=1, max_cooldowns=0)
    t0 = time.time()
    assert b.on_breach() == "cooldown"
    dt = time.time() - t0
    assert dt >= 0.9, f"应 sleep ~1s，实际 {dt:.2f}s"
    assert b.consecutive == 0


def test_giveup_after_max_cooldowns():
    # breach_limit=1：每次撞墙即达上限 → cooldown；max_cooldowns=1 → 第 2 次放弃
    b = CFBreaker(breach_limit=1, backoff=0, cooldown=0, max_cooldowns=1)
    assert b.on_breach() == "cooldown"   # 冷却 #1（count=1，未超上限）
    assert b.consecutive == 0
    # 第 2 次达上限：count=2 > max(1) → giveup
    assert b.on_breach() == "giveup"
    assert b.consecutive == 0  # giveup 前已重置，避免再误触发


def test_infinite_self_recover_never_giveup():
    # breach_limit=1：每次撞墙即达上限 → cooldown；max_cooldowns=0 永不给 up
    b = CFBreaker(breach_limit=1, backoff=0, cooldown=0, max_cooldowns=0)
    for _ in range(20):
        dec = b.on_breach()
        assert dec == "cooldown", f"max_cooldowns=0 应永远 cooldown，得 {dec}"
        assert b.consecutive == 0
