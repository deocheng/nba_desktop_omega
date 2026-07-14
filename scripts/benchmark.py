"""NBACore v8 — Performance Benchmark Suite.

Measures latency for core operations across all layers:
- Data Layer: raw query latency
- Metric Engine: single metric + compute_many
- API Layer: endpoint latency
- Context Engine: similarity + evolution + trend

Usage:
    python scripts/benchmark.py

Results are printed to stdout (no DB writes, no side effects).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from backend.services.context_engine import (
    find_similar_players,
    player_role_evolution,
    player_trend,
)
from backend.services.metric_engine import (
    compute,
    compute_many,
    list_metrics,
    rank,
)


@dataclass
class BenchmarkResult:
    name: str
    samples: int
    avg_ms: float
    min_ms: float
    max_ms: float
    p50_ms: float
    p95_ms: float
    extra: dict = field(default_factory=dict)


def _bench(fn, n=5) -> BenchmarkResult:
    """Run fn n times, measure latency, return stats."""
    times: list[float] = []
    for _ in range(n):
        start = time.perf_counter()
        result = fn()
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)

    times.sort()
    avg = sum(times) / len(times)
    p50 = times[len(times) // 2]
    p95_idx = int(len(times) * 0.95)
    p95 = times[min(p95_idx, len(times) - 1)]

    extra = {}
    if hasattr(result, "__len__"):
        extra["result_size"] = len(result)

    return BenchmarkResult(
        name=fn.__name__ if hasattr(fn, "__name__") else "bench",
        samples=len(times),
        avg_ms=round(avg, 2),
        min_ms=round(times[0], 2),
        max_ms=round(times[-1], 2),
        p50_ms=round(p50, 2),
        p95_ms=round(p95, 2),
        extra=extra,
    )


def run_all_benchmarks() -> list[BenchmarkResult]:
    season = 2025
    all_metrics = list_metrics()
    core_metrics = all_metrics[:5]

    results: list[BenchmarkResult] = []

    def bench_single_metric():
        return compute("pts_per_game", season)

    def bench_compute_many():
        return compute_many(core_metrics, season)

    def bench_rank_top100():
        return rank("pts_per_game", season)[:100]

    def bench_similar_players():
        return find_similar_players(
            "jamesle01", season, core_metrics,
            limit=10, position_filter=True,
        )

    def bench_role_evolution():
        return player_role_evolution(
            "jamesle01",
            [season - 4, season - 3, season - 2, season - 1, season],
            core_metrics,
        )

    def bench_trend():
        return player_trend(
            "jamesle01", "pts_per_game",
            [season - 4, season - 3, season - 2, season - 1, season],
        )

    benches = [
        ("Metric Engine: single metric (cold)", bench_single_metric),
        ("Metric Engine: single metric (warm)", bench_single_metric),
        ("Metric Engine: compute_many (5 metrics)", bench_compute_many),
        ("Metric Engine: rank top 100", bench_rank_top100),
        ("Context: similar players", bench_similar_players),
        ("Context: role evolution (5 seasons)", bench_role_evolution),
        ("Context: trend analysis", bench_trend),
    ]

    for name, fn in benches:
        fn.__name__ = name
        r = _bench(fn, n=3)
        results.append(r)

    return results


def print_benchmark_report(results: list[BenchmarkResult]) -> None:
    print("=" * 72)
    print("NBACore Studio v8 — Performance Benchmark Report")
    print("=" * 72)
    print(f"{'Benchmark':<45} {'Avg(ms)':>8} {'P50(ms)':>8} {'P95(ms)':>8}")
    print("-" * 72)
    for r in results:
        print(f"{r.name:<45} {r.avg_ms:>8.2f} {r.p50_ms:>8.2f} {r.p95_ms:>8.2f}")
    print("=" * 72)


def main():
    results = run_all_benchmarks()
    print_benchmark_report(results)


if __name__ == "__main__":
    main()
