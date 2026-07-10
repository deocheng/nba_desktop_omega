"""NBACore v8 — AI 战术生成（P2 可插拔接口，v1 仅落契约 + 默认实现，T06）。

定义 TacticGenerator 抽象基类与注册表。v1 默认 StaticTemplateGenerator
（返回内置模板，保证接口可测、可运行）；LLMTacticGenerator 预留接口与
NotImplementedError 占位，不接真实 LLM（Ollama/LLM 插槽，Mac 版远期目标）。

零重构接入：未来新增 Provider 只需继承 TacticGenerator 并注册到 REGISTRY，
无需改动 Frontend/API/Engine 调用链。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Optional

from backend.services.tactics_engine.schemas import TacticTemplate
from backend.services.tactics_engine.tactic_templates import all_templates


class TacticGenerator(ABC):
    """战术生成器抽象接口（可插拔）。"""

    @abstractmethod
    def generate_from_natural_language(self, prompt: str, constraints: dict) -> TacticTemplate:
        """自然语言 → 战术模板。"""
        raise NotImplementedError

    @abstractmethod
    def extract_from_pbp(self, game_id: str, segment: dict) -> TacticTemplate:
        """从真实 PBP 片段提炼战术模板。"""
        raise NotImplementedError


class StaticTemplateGenerator(TacticGenerator):
    """v1 默认实现：返回内置模板（确定性、可测、可运行）。

    - generate_from_natural_language：按 constraints.template_id 或 prompt 匹配
      内置模板；未匹配则返回第一个内置模板（保证始终可返回有效模板）。
    - extract_from_pbp：返回默认内置模板（P2 真实提炼待 LLM 接入）。
    """

    def generate_from_natural_language(
        self, prompt: str, constraints: Optional[dict] = None
    ) -> TacticTemplate:
        constraints = constraints or {}
        wanted = constraints.get("template_id") or (prompt or "").strip().lower()
        templates = all_templates()
        if wanted:
            for t in templates:
                if t.id == wanted or t.name.lower() == wanted:
                    return t
            for t in templates:
                if wanted in t.name.lower():
                    return t
        return templates[0]

    def extract_from_pbp(
        self, game_id: str, segment: Optional[dict] = None
    ) -> TacticTemplate:
        # P2：真实提炼待 LLM；v1 返回默认内置模板（Pick-and-Roll）
        return all_templates()[0]


class LLMTacticGenerator(TacticGenerator):
    """P2 预留：对接 Ollama / 远程 LLM（Mac 版远期目标）。

    v1 不实现真实推理，调用即抛 NotImplementedError，供 QA 验证「接口已预留」。
    TODO(P2): 实现 OllamaProvider / RemoteLLMProvider，定义 prompt/response schema。
    """

    def __init__(self, endpoint: Optional[str] = None) -> None:
        self.endpoint = endpoint

    def generate_from_natural_language(
        self, prompt: str, constraints: Optional[dict] = None
    ) -> TacticTemplate:
        # TODO(P2-TB-14): 调用 Ollama/LLM 生成 TacticTemplate JSON。
        raise NotImplementedError("LLMTacticGenerator 尚未启用（P2 / Mac+Ollama 远期目标）")

    def extract_from_pbp(
        self, game_id: str, segment: Optional[dict] = None
    ) -> TacticTemplate:
        # TODO(P2-TB-15): 调用 LLM 从 PBP 事件序列归纳跑位模式。
        raise NotImplementedError("LLMTacticGenerator 尚未启用（P2 / Mac+Ollama 远期目标）")


# ── 注册表（Provider 可插拔）──
REGISTRY: Dict[str, type] = {
    "static": StaticTemplateGenerator,
    "llm": LLMTacticGenerator,
}


def get_generator(provider: str = "static") -> TacticGenerator:
    """按 provider 名获取生成器实例（默认 static）。"""
    cls = REGISTRY.get(provider, StaticTemplateGenerator)
    return cls()
