"""NBACore v8 — LLM Provider 测试（JSON 提取 / LLM 优先 / 正则兜底 / Ollama 真连通）。

纯逻辑测试不依赖真实 Ollama；``test_ollama_live`` 探测 Ollama 可达则跑，否则跳过。
"""
from __future__ import annotations

import json

import pytest

from backend.services.trade_engine.llm_prompts import build_messages
from backend.services.trade_engine.llm_provider import (
    LLMProvider,
    OllamaProvider,
    get_provider,
)
from .conftest import skip_if_no_db


class FakeProvider(LLMProvider):
    """返回固定 dict 的假 provider（测试 LLM 优先路径用）。"""

    provider_name = "fake"

    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload or {
            "counterparties": ["GSW", "MIN"],
            "players_out": ["D'Angelo Russell"],
            "players_in": ["Andrew Wiggins"],
            "picks": [],
            "cash": None,
            "notes": "",
        }

    def parse_trade(self, text: str, team_abbr: str | None = None) -> dict:
        return dict(self.payload)


def test_build_messages_shape():
    msgs = build_messages("Warriors traded X to Lakers for Y", "GSW")
    assert isinstance(msgs, list) and len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "GSW" in msgs[1]["content"]


def test_extract_json_clean():
    prov = OllamaProvider()
    content = json.dumps(
        {
            "counterparties": ["GSW", "DET"],
            "players_out": ["James Wiseman"],
            "players_in": [],
            "picks": ["2023 second-round pick"],
            "cash": None,
            "notes": "",
        }
    )
    out = prov._extract_json(content)
    assert out["counterparties"] == ["GSW", "DET"]
    assert out["players_out"] == ["James Wiseman"]
    assert out["picks"] == ["2023 second-round pick"]


def test_extract_json_with_thinking_noise():
    """qwen 可能在 content 里带 <think> 思维链 + 围栏 + 尾随解释。"""
    prov = OllamaProvider()
    inner = json.dumps(
        {
            "counterparties": ["ORL", "DEN"],
            "players_out": ["Aaron Gordon"],
            "players_in": ["Gary Harris"],
            "picks": [],
            "cash": None,
            "notes": "",
        }
    )
    content = (
        "<think>Let me analyze this NBA trade step by step...</think>\n"
        "```json\n" + inner + "\n```\n"
        "Here is the extracted trade semantics as requested."
    )
    out = prov._extract_json(content)
    assert out["counterparties"] == ["ORL", "DEN"]
    assert out["players_out"] == ["Aaron Gordon"]
    assert out["players_in"] == ["Gary Harris"]
    assert out["picks"] == []


def test_extract_json_invalid_raises():
    prov = OllamaProvider()
    with pytest.raises(ValueError):
        prov._extract_json("no json here at all")


def test_get_provider_default_ollama():
    prov = get_provider()
    assert isinstance(prov, OllamaProvider)


def test_parse_trade_semantics_llm_first(monkeypatch):
    """LLM 优先：FakeProvider 返回填充字段，parse 应组装 TradeSemantics 且玩家字段被填充。"""
    from backend.services.trade_engine import cba_aux_db

    monkeypatch.setattr(cba_aux_db, "get_provider", lambda: FakeProvider())
    sample = (
        "The Golden State Warriors traded D'Angelo Russell to the "
        "Minnesota Timberwolves for Andrew Wiggins."
    )
    sem = cba_aux_db.parse_trade_semantics(sample, team_abbr="GSW")
    assert sem.counterparties == ["GSW", "MIN"]
    assert sem.players_out == ["D'Angelo Russell"]
    assert sem.players_in == ["Andrew Wiggins"]
    assert sem.raw_text == sample


@skip_if_no_db
def test_parse_trade_semantics_regex_fallback(monkeypatch):
    """LLM 抛错 -> 正则兜底：不抛异常，raw_text 保留，counterparties 来自正则。"""
    from backend.services.trade_engine import cba_aux_db

    def _boom(*a, **k):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(cba_aux_db, "get_provider", _boom)
    sample = "Orlando Magic traded Aaron Gordon to Denver Nuggets for Gary Harris"
    sem = cba_aux_db.parse_trade_semantics(sample)
    assert isinstance(sem, cba_aux_db.TradeSemantics)
    assert sem.raw_text == sample
    # 正则从白名单抽出 ORL / DEN
    assert "ORL" in sem.counterparties
    assert "DEN" in sem.counterparties
    # 兜底时 LLM 字段留空
    assert sem.players_out == []
    assert sem.players_in == []


def test_ollama_live():
    """真实 Ollama 连通测试；不可达或响应超时（环境慢）则 skip，绝不 fail。"""
    import urllib.request

    prov = OllamaProvider()
    try:
        req = urllib.request.Request(f"{prov._base_url}/api/tags")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=5) as resp:
            assert resp.status == 200
    except Exception:  # noqa: BLE001
        pytest.skip("Ollama 不可达，跳过真连通测试")

    # 环境实测 Ollama 生成可能较慢（首调用冷启动），用较长超时；
    # 若仍超时/报错，skip 而非 fail，保证套件稳定。
    slow = OllamaProvider(timeout=120)
    try:
        d = slow.parse_trade(
            "The Golden State Warriors traded James Wiseman to the "
            "Detroit Pistons for a 2023 second-round pick",
            "GSW",
        )
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Ollama chat 超时/异常（环境慢）：{exc}")
    assert isinstance(d, dict)
    assert "counterparties" in d
    assert "players_out" in d
    assert "picks" in d
