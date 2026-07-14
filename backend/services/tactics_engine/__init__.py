"""NBACore v8 — Tactics Engine（Layer 2 计算层）。

球队战术板 + PBP 动态回放（v1）核心计算引擎。严格四层隔离：
    Frontend → API(编排) → Engine(本包) → Data(只读 batch_query)

本包负责：
    - 坐标映射 x/y → 半场 SVG 像素（coords）
    - 只读 PBP 数据接入（db）
    - 内置战术模板库（tactic_templates）
    - PBP 回放事件序列构建 + last-known 占位策略（replay_engine）
    - 线性插值 / 逐帧序列生成（animation）
    - AI 战术生成可插拔接口（ai_generator，P2 预留）
    - 门面（service）汇总能力供 API 编排

所有坐标映射 / 插值 / 帧生成均在 Engine 层完成，输出 deterministic 帧 JSON。
前端（Layer 4）仅消费帧序列并渲染 SVG，禁止任何坐标计算。
"""
from __future__ import annotations

from backend.services.tactics_engine import (
    ai_generator,
    animation,
    coords,
    db,
    replay_engine,
    schemas,
    tactic_templates,
)
from backend.services.tactics_engine.service import TacticsService

__all__ = [
    "TacticsService",
    "ai_generator",
    "animation",
    "coords",
    "db",
    "replay_engine",
    "schemas",
    "tactic_templates",
]
