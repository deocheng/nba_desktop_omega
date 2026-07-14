"""Requirement 7 (engine layer) — AI tactic generator pluggable interface (P2).

Verifies:
  - REGISTRY contains 'static' and 'llm'
  - StaticTemplateGenerator is obtainable and returns a valid TacticTemplate
  - StaticTemplateGenerator matches by prompt / template_id
  - LLMTacticGenerator raises NotImplementedError when called (reserved slot)
  - unknown provider falls back to static (zero-rewrite extensibility)
"""
from __future__ import annotations

import pytest

from backend.services.tactics_engine import ai_generator


def test_registry_has_static_and_llm():
    assert set(ai_generator.REGISTRY.keys()) >= {"static", "llm"}


def test_static_generator_obtainable_and_returns_template():
    gen = ai_generator.get_generator("static")
    assert isinstance(gen, ai_generator.StaticTemplateGenerator)
    tpl = gen.generate_from_natural_language("pick and roll", {})
    assert tpl.id == "pick_and_roll"


def test_static_generator_by_prompt_match():
    gen = ai_generator.get_generator("static")
    assert gen.generate_from_natural_language("horns", {}).id == "horns"


def test_static_extract_from_pbp_returns_template():
    gen = ai_generator.get_generator("static")
    tpl = gen.extract_from_pbp("22400740", {"period": 1})
    assert tpl is not None and tpl.id


def test_llm_generator_raises_not_implemented():
    gen = ai_generator.get_generator("llm")
    assert isinstance(gen, ai_generator.LLMTacticGenerator)
    with pytest.raises(NotImplementedError):
        gen.generate_from_natural_language("any prompt", {})
    with pytest.raises(NotImplementedError):
        gen.extract_from_pbp("22400740", {})


def test_unknown_provider_falls_back_to_static():
    gen = ai_generator.get_generator("unknown-provider")
    assert isinstance(gen, ai_generator.StaticTemplateGenerator)
