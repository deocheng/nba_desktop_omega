"""fill_player_cache 防撞熔断 + 自恢复逻辑测试（不启动真实浏览器 / 不连库）。

三个场景：
  A. 全程 CF 挑战页 + 冷却上限=1 → 第 1 次冷却后自恢复，第 2 次超上限放弃退出
     （验证：断掉撞击后自动续跑，而非永久空转；且可受控放弃）
  B. 前 4 次 CF、第 5 次起正常 → 不触发熔断，跑完 10 个，连续计数被重置
  C. 全程 CF + 冷却上限=0(无限自恢复) + cooldown=0 → 持续自恢复，跑完全部不退出

通过 monkeypatch common.browser._build_driver 注入 fake driver，
并 stub DB 连接 / is_cached / save_html，纯函数级验证熔断+自恢复分支。
"""
import logging
import os
import sys
import types

# 让 `import fill_player_cache` 可解析（它在 external_crawler/crawler/ 下）
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "external_crawler", "crawler",
    ),
)

import pytest

import fill_player_cache as fpc


class _FakeDriver:
    """page_source 随 get() 调用次数在 CF 挑战页 / 正常页间切换。"""

    def __init__(self, cf_until: int = 10 ** 9):
        self._cf_until = cf_until   # get 调用次数 <= cf_until 时返回 CF 挑战页
        self._n = 0

    def get(self, url: str) -> None:
        self._n += 1

    @property
    def page_source(self) -> str:
        if self._n <= self._cf_until:
            return "<html><body>Just a moment</body></html>"
        return "<html><body>LeBron James</body></html>"


@pytest.fixture
def stubbed(monkeypatch):
    """Stub 掉 DB / 缓存查询 / driver builder，返回受控 fake。"""
    import common.browser as cb

    built = []

    def set_builder(cf_until: int):
        def _build():
            d = _FakeDriver(cf_until=cf_until)
            built.append(d)
            return d
        monkeypatch.setattr(cb, "_build_driver", staticmethod(_build))

    monkeypatch.setattr(
        fpc, "psycopg2",
        types.SimpleNamespace(
            connect=lambda *a, **k: types.SimpleNamespace(close=lambda: None)
        ),
    )
    monkeypatch.setattr(
        fpc, "_load_player_ids",
        lambda conn, season: [f"p{i:03d}" for i in range(10)],
    )
    monkeypatch.setattr(fpc, "is_cached", lambda pid: False)
    saved = {"n": 0}
    monkeypatch.setattr(
        fpc, "save_html",
        lambda pid, html: (saved.__setitem__("n", saved["n"] + 1) or True),
    )

    cb.reset_driver()          # 清掉上一测试遗留的进程级 driver 单例
    set_builder(10 ** 9)  # 默认：始终 CF
    yield {"set_builder": set_builder, "built": built, "saved": saved}


def test_cf_breach_then_self_recover_then_giveup(stubbed, caplog):
    """全程 CF + 冷却上限=1 → 冷却一次自恢复，第二次超上限放弃退出。"""
    caplog.set_level(logging.INFO)
    # cooldown=0 让测试不真睡；max_cooldowns=1 → 第 2 次冷却即放弃
    fpc.main(limit=10, cf_breach_limit=5, cf_backoff=0,
             cf_cooldown=0, cf_max_cooldowns=1)
    drv = stubbed["built"][-1]
    # 第 1 批 5 次 CF → 冷却#1 → 第 2 批 5 次 CF → 冷却#2 超上限 break
    # 总共 get 了 10 次（不是无限空转，也不是只 5 次就永久退场）
    assert drv._n == 10, f"应 get 10 次(5+5), 实际 {drv._n}"
    assert stubbed["saved"]["n"] == 0
    # 自恢复信号出现（冷却#1 结束后打印）
    assert any("自动恢复抓取" in r.message for r in caplog.records)
    # 超上限放弃信号出现
    assert any("放弃退出" in r.message for r in caplog.records)


def test_recovery_mid_run_does_not_break(stubbed, caplog):
    """前 4 次 CF、第 5 次起正常 → 不熔断，跑完 10 个，计数被重置。"""
    import common.browser as cb
    caplog.set_level(logging.INFO)
    cb.reset_driver()            # 清掉测试 A 遗留的进程级 driver 单例
    stubbed["set_builder"](4)  # 只前 4 次返回 CF
    fpc.main(limit=10, cf_breach_limit=5, cf_backoff=0,
             cf_cooldown=0, cf_max_cooldowns=0)
    drv = stubbed["built"][-1]
    assert drv._n == 10, f"应跑完 10 个, 实际 {drv._n}"
    # 第 5~10 次是正常页 → save_html 被调用 6 次
    assert stubbed["saved"]["n"] == 6, f"应落盘 6 次, 实际 {stubbed['saved']['n']}"
    # 不应触发熔断冷却
    assert not any("自恢复" in r.message for r in caplog.records)
    assert not any("放弃退出" in r.message for r in caplog.records)


def test_infinite_self_recover_runs_to_completion(stubbed, caplog):
    """全程 CF + 冷却上限=0(无限自恢复) + cooldown=0 → 持续自恢复跑完不退出。"""
    caplog.set_level(logging.INFO)
    fpc.main(limit=10, cf_breach_limit=5, cf_backoff=0,
             cf_cooldown=0, cf_max_cooldowns=0)
    drv = stubbed["built"][-1]
    # 10 个全是 CF，但无限自恢复：5→冷却→5→冷却→(重置后继续, 但已无剩余) 跑完
    # 关键：没有死循环，函数正常返回；get 次数 = 10
    assert drv._n == 10, f"应 get 10 次并正常返回, 实际 {drv._n}"
    # 至少发生了一次自恢复（冷却后继续）
    assert any("自动恢复抓取" in r.message for r in caplog.records)
    # 未触发放弃退出（上限=0 永不放弃）
    assert not any("放弃退出" in r.message for r in caplog.records)
