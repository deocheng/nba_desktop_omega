"""NBACore v8 §2 Layer 2 — Metric Registry.

Sole source of truth for metric definitions. Every metric that the engine
can compute MUST be registered here (or in a sub-module at import time).

v8 §2 mandates:
    - All metrics must come from registry (no ad-hoc computation)
    - API/Frontend may not define metrics
    - compute() is a vectorized Callable, NOT a string expression
      (so we never need eval()/exec() — v8 §6 compliant)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

import pandas as pd

MetricFn = Callable[[pd.DataFrame], pd.Series]

MetricKind = Literal["per_game", "ratio", "weighted_sum", "expression"]


@dataclass(frozen=True)
class MetricSpec:
    """Declarative metric definition (immutable, introspectable)."""
    name: str                           # unique key, e.g. 'pts_per_game'
    kind: MetricKind                    # computation pattern
    source_table: str                   # registered data_layer table
    required_cols: tuple[str, ...]      # columns the compute fn reads
    compute: MetricFn                   # vectorized function: DataFrame -> Series
    description: str = ""
    min_denominator: float = 1.0        # guard against div-by-zero (ratio/per_game)
    precision: int = 6                  # decimal places for deterministic output


class MetricRegistry:
    """In-memory registry. Singleton-style via module-level _REGISTRY."""

    def __init__(self) -> None:
        self._specs: dict[str, MetricSpec] = {}

    def register(self, spec: MetricSpec) -> None:
        if not spec.name or not isinstance(spec.name, str):
            raise ValueError("metric name must be non-empty str")
        if spec.name in self._specs:
            raise ValueError(f"metric {spec.name!r} already registered")
        if not isinstance(spec.required_cols, tuple):
            raise TypeError("required_cols must be tuple (hashable)")
        self._specs[spec.name] = spec

    def get(self, name: str) -> MetricSpec:
        if name not in self._specs:
            raise KeyError(
                f"metric {name!r} not registered. "
                f"Available: {sorted(self._specs)}"
            )
        return self._specs[name]

    def list(self) -> list[str]:
        return sorted(self._specs)

    def has(self, name: str) -> bool:
        return name in self._specs

    def all_specs(self) -> list[MetricSpec]:
        return [self._specs[n] for n in self.list()]

    def __len__(self) -> int:
        return len(self._specs)


# Module-level singleton — the ONE registry used across the engine.
REGISTRY = MetricRegistry()


def get_registry() -> MetricRegistry:
    """Public accessor (used by executor + tests)."""
    return REGISTRY


def register(spec: MetricSpec) -> None:
    """Convenience wrapper around REGISTRY.register."""
    REGISTRY.register(spec)
