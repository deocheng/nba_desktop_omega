"""NBACore v8 — AI 交易语义解析：LLM Provider 抽象层（§6 合规，零新依赖）。

设计要点
--------
- 仅使用 Python 标准库 ``urllib.request`` + ``json`` 调用本地 Ollama
  ``/api/chat``，不引入 requests / openai SDK（满足 R3 / AC5）。
- 配置从 ``os.environ`` 读取（``backend.core.config`` 已在启动时把 .env 注入
  os.environ 并带默认值），本模块为 LLM 配置的单一真理源；**不修改
  backend.core.config.py**（最小变更原则）。
- Provider 可插拔：``LLMProvider`` ABC + ``OllamaProvider`` 默认实现；未来
  ``OpenAIProvider`` 等实现同一接口即可热切换（R1 / R10）。
- 任何网络 / 超时 / JSON 异常在 ``parse_trade`` 内 **不吞掉**，由上层
  ``parse_trade_semantics`` 统一 catch 并正则兜底（D3）。

§6 红线：本模块零 ``import psycopg2``、零 SQL 子串（纯 LLM 调用）。
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from backend.services.trade_engine import llm_prompts

logger = logging.getLogger("nbacore.llm_provider")

# parse_trade 返回 dict 的契约键（供上层 cba_aux_db 组装 TradeSemantics）
LLM_RESULT_KEYS = (
    "counterparties",
    "players_out",
    "players_in",
    "picks",
    "cash",
    "notes",
)


def get_llm_config() -> Dict[str, object]:
    """从 os.environ 读取 LLM 配置（带默认值）。

    配置集中在 env（由 ``backend.core.config`` 启动时注入 .env），本函数为
    LLM 配置的单一真理源，避免散落硬编码；不修改 backend.core.config。
    """
    return {
        "provider": os.getenv("LLM_PROVIDER", "ollama"),
        "ollama_base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        "ollama_model": os.getenv("OLLAMA_MODEL", "qwen3.5-16k"),
        "timeout": float(os.getenv("LLM_TIMEOUT", "30")),
        "temperature": float(os.getenv("LLM_TEMPERATURE", "0")),
        "throttle_sleep": float(os.getenv("LLM_THROTTLE_SLEEP", "0.15")),
        "max_retries": int(os.getenv("LLM_MAX_RETRIES", "1")),
    }


class LLMProvider(ABC):
    """LLM 语义解析 Provider 抽象基类（可插拔接口，R1）。

    实现类需提供 ``parse_trade(text, team_abbr) -> dict``，返回键见
    ``LLM_RESULT_KEYS``。任何实现层的网络 / JSON 异常都应向上抛出，
    由调用方决定兜底策略（不在此吞掉）。
    """

    provider_name: str = "base"

    @abstractmethod
    def parse_trade(self, text: str, team_abbr: Optional[str] = None) -> Dict[str, object]:
        """从自由文本交易描述抽取结构化语义。

        Args:
            text: 原始交易自由文本
            team_abbr: 可选关联球队缩写（作为 hint 传入 prompt）

        Returns:
            dict: {counterparties, players_out, players_in, picks, cash, notes}

        Raises:
            任何网络 / 超时 / JSON / 字段异常都向上抛（不吞掉）。
        """
        raise NotImplementedError


class OllamaProvider(LLMProvider):
    """默认 Provider：调用本地 Ollama ``/api/chat``（stdlib urllib，零新依赖）。"""

    provider_name = "ollama"

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        temperature: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> None:
        cfg = get_llm_config()
        self._base_url = (base_url or cfg["ollama_base_url"]).rstrip("/")
        self._model = model or cfg["ollama_model"]
        self._timeout = timeout if timeout is not None else cfg["timeout"]
        self._temperature = temperature if temperature is not None else cfg["temperature"]
        self._max_retries = max_retries if max_retries is not None else cfg["max_retries"]
        # 无代理 opener：Ollama 在 localhost，避免 http_proxy 干扰（实测环境有代理）。
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    # ── 公共接口 ──
    def parse_trade(self, text: str, team_abbr: Optional[str] = None) -> Dict[str, object]:
        """调用 Ollama 解析交易文本，返回稳健提取的 dict。异常向上抛。"""
        system, user = self._build_prompt(text, team_abbr)
        last_err: Optional[Exception] = None
        attempts = max(1, int(self._max_retries) + 1)
        for attempt in range(attempts):
            try:
                raw = self._post_chat(system, user)
                return self._extract_json(raw)
            except Exception as exc:  # 瞬时失败重试；最终失败上抛由上层兜底
                last_err = exc
                if attempt < attempts - 1:
                    logger.warning("Ollama parse attempt %d failed: %s", attempt + 1, exc)
                    continue
        assert last_err is not None
        raise last_err

    # ── 内部实现 ──
    def _build_prompt(self, text: str, team_abbr: Optional[str]) -> "tuple[str, str]":
        messages = llm_prompts.build_messages(text, team_abbr)
        system = ""
        user = ""
        for m in messages:
            role = m.get("role")
            if role == "system":
                system = m.get("content", "")
            elif role == "user":
                user = m.get("content", "")
        return system, user

    def _post_chat(self, system: str, user: str) -> str:
        """POST Ollama /api/chat，返回 message.content 字符串。异常向上抛。"""
        url = f"{self._base_url}/api/chat"
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": self._temperature},
        }
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self._opener.open(req, timeout=self._timeout) as resp:
            payload = resp.read().decode("utf-8")
        parsed = json.loads(payload)
        # Ollama 返回结构为 {"message": {"content": ...}}；兼容 OpenAI 风格 choices。
        content = self._extract_content(parsed)
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Ollama 响应缺少有效 content 字段")
        return content

    @staticmethod
    def _extract_content(parsed: dict) -> Optional[str]:
        if isinstance(parsed, dict):
            msg = parsed.get("message")
            if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                return msg["content"]
            choices = parsed.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, dict) and isinstance(first.get("message"), dict):
                    return first["message"].get("content")
        return None

    @staticmethod
    def _extract_json(content: str) -> Dict[str, object]:
        """从 LLM 输出稳健提取 JSON dict（D2：去围栏 + 截取首个{到末个}）。

        qwen 可能在 content 里带 ``<think>…</think>`` 思维链或尾随解释文本，
        本函数稳健截取 JSON 部分。失败抛 ``ValueError``（由上层兜底）。
        """
        if not isinstance(content, str) or not content.strip():
            raise ValueError("empty content, cannot extract JSON")
        # 1) 去除 ```json ... ``` 围栏
        cleaned = re.sub(r"```(?:json)?", "", content, flags=re.IGNORECASE)
        cleaned = cleaned.replace("```", "")
        # 2) 取首个 '{' 到末个 '}' 子串
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ValueError("no JSON object found in content")
        blob = cleaned[start : end + 1]
        try:
            obj = json.loads(blob)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid JSON in extracted blob: {exc}") from exc
        if not isinstance(obj, dict):
            raise ValueError("extracted JSON is not an object")
        # 字段清洗：确保全部契约键存在且类型合理
        out: Dict[str, object] = {}
        for key in LLM_RESULT_KEYS:
            out[key] = obj.get(key)
        for key in ("counterparties", "players_out", "players_in", "picks"):
            if not isinstance(out[key], list):
                out[key] = []
        if not isinstance(out.get("notes"), str):
            out["notes"] = "" if out.get("notes") is None else str(out["notes"])
        # cash 保持原值（float|int|None）；上层负责转 float
        return out

    def is_available(self) -> bool:
        """探测 Ollama 是否可达（用于测试 skip / 可用性判断）。"""
        try:
            url = f"{self._base_url}/api/tags"
            req = urllib.request.Request(url)
            with self._opener.open(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:  # noqa: BLE001
            return False


def get_provider() -> LLMProvider:
    """Provider 工厂（按 LLM_PROVIDER 选择；默认 ollama）。

    未来可扩展：``if name == "openai": return OpenAIProvider()``。
    """
    name = str(get_llm_config()["provider"]).lower()
    if name == "ollama":
        return OllamaProvider()
    logger.warning("未知 LLM_PROVIDER=%r，回退 ollama", name)
    return OllamaProvider()
