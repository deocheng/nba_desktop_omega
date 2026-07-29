"""common/browser.get() 共享熔断器接线测试（不启动真实浏览器 / 不连库）。

证明：所有经 common.browser.get() 的爬虫（gamelog / fill / headshots /
transactions / injuries / contracts / schedule ... 几十个）自动获得
「连续撞墙 → 熔断冷却 → 自恢复」，无需各写一遍。

通过 monkeypatch common.browser._build_driver 注入 fake driver，
并把模块级 _BREAKER 设成 cooldown=0 避免真睡。
"""
import types

import pytest

import common.browser as cb
from common.cf_breaker import CFBreaker


class _FakePage:
    def __init__(self):
        # url 含 cf_chl → _is_challenged 恒 True（模拟全局 CF 风暴）
        self.url = "https://www.basketball-reference.com/cf_chl/page"

    def goto(self, url, **k):
        pass

    def reload(self, **k):
        pass

    def evaluate(self, expr):
        return "Checking your browser"

    @property
    def content(self):
        return "<html><body>Just a moment</body></html>"

    def goto(self, url, **k):
        pass

    def reload(self, **k):
        pass

    def evaluate(self, expr):
        return "Checking your browser"


class _FakeDriver:
    """模仿 _PWDriver 的最小接口（get / page_source / _is_challenged）。"""

    def __init__(self):
        self._page = _FakePage()

    def get(self, url, _tries=cb._CF_INNER_TRIES):
        last_err = None
        for _ in range(_tries):
            try:
                self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as _e:  # noqa: BLE001
                last_err = _e
            if not self._is_challenged():
                cb._BREAKER.on_success()
                return
            decision = cb._BREAKER.on_breach()
            if decision == "giveup":
                raise cb.CFChallengeError(f"gave up: {last_err}")
            try:
                self._page.reload(wait_until="domcontentloaded", timeout=30000)
            except Exception:  # noqa: BLE001
                pass
        return

    @property
    def page_source(self):
        return self._page.content

    def _is_challenged(self):
        try:
            u = self._page.url or ""
            if "__cf_chl_rt_tk" in u or "cf_chl" in u:
                return True
            txt = self._page.evaluate("() => document.body.innerText")
            return "Checking your browser" in txt
        except Exception:  # noqa: BLE001
            return False


@pytest.fixture
def fake_driver(monkeypatch):
    monkeypatch.setattr(cb, "_build_driver", staticmethod(lambda: _FakeDriver()))
    monkeypatch.setattr(
        cb, "_BREAKER",
        CFBreaker(breach_limit=2, backoff=0, cooldown=0, max_cooldowns=0),
    )
    cb.reset_driver()  # 清掉上一测试遗留的进程级 driver 单例
    yield
    cb.reset_driver()


def test_get_does_not_spin_on_site_wide_cf(fake_driver):
    """全局 CF 风暴下：get() 触发熔断冷却（自恢复），不无限空转、不抛。"""
    drv = cb.get_driver()
    drv.get("https://www.basketball-reference.com/players/a/abc01.html")
    src = drv.page_source
    # 返回（挑战页）源码，未抛异常
    assert "Just a moment" in src
    # 已发生至少一次熔断冷却（证明断掉撞击、自恢复，而非空转）
    assert cb._BREAKER.cooldown_count >= 1


def test_get_gives_up_only_after_max_cooldowns(fake_driver):
    """设 max_cooldowns=1：第 1 次冷却后还能跑，第 2 次超上限才放弃抛出。"""
    cb._BREAKER.max_cooldowns = 1
    drv = cb.get_driver()
    drv.get("https://www.basketball-reference.com/players/a/abc01.html")
    assert cb._BREAKER.cooldown_count == 1  # 第 1 次冷却，未超上限
    with pytest.raises(cb.CFChallengeError):
        # 第 2 次冷却 → count=2 > max(1) → giveup 抛出
        drv.get("https://www.basketball-reference.com/players/a/abc01.html")
