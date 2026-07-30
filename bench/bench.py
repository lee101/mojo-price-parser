"""Benchmark Mojo-backed parsing against price-parser 0.5.1."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import gc
import math
import os
import platform
import sys
import time
from pathlib import Path

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "python"),
)

from price_parser import Price, parse_amounts, parse_prices  # noqa: E402


def load_upstream():
    package = Path(
        importlib.metadata.distribution("price-parser").locate_file("price_parser")
    )
    spec = importlib.util.spec_from_file_location(
        "bench_upstream_price_parser",
        package / "__init__.py",
        submodule_search_locations=[str(package)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load installed price-parser")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


UPSTREAM = load_upstream()
UPSTREAM_PARSER = sys.modules["bench_upstream_price_parser.parser"]


def timed(fn) -> float:
    gc.collect()
    gc.disable()
    try:
        start = time.process_time()
        result = fn()
        elapsed = time.process_time() - start
        if result is None:
            raise AssertionError("benchmark returned no result")
        return elapsed
    finally:
        gc.enable()


def paired_times(ours, theirs, repeat: int = 3) -> tuple[float, float]:
    ours_best = math.inf
    theirs_best = math.inf
    for index in range(repeat):
        if index % 2:
            theirs_best = min(theirs_best, timed(theirs))
            ours_best = min(ours_best, timed(ours))
        else:
            ours_best = min(ours_best, timed(ours))
            theirs_best = min(theirs_best, timed(theirs))
    return ours_best, theirs_best


TEMPLATES = [
    "Price: $1,234.56",
    "Běžná cena 75 990,00 Kč",
    "CHF 1'049,95",
    "Rp 1.550.000",
    "151,200 تومان",
    "Free",
    "35€ 99",
    "12,000원",
]


def dataset(size: int) -> list[str]:
    return [TEMPLATES[index % len(TEMPLATES)] for index in range(size)]


def tupled(values):
    return [(value.amount, value.currency, value.amount_text) for value in values]


def cpu_name() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def main() -> None:
    batch = dataset(100_000)
    numeric = [f"{index:,}.99" for index in range(100_000)]
    long_numeric = [
        f"product {'x' * 960} listed at {index:,}.99 each" for index in range(20_000)
    ]

    cases = [
        (
            "single parse, mixed (100k)",
            lambda: [Price.fromstring(value) for value in batch],
            lambda: [UPSTREAM.Price.fromstring(value) for value in batch],
        ),
        (
            "batch parse, mixed (100k)",
            lambda: parse_prices(batch),
            lambda: [UPSTREAM.Price.fromstring(value) for value in batch],
        ),
        (
            "batch parse, numeric-only (100k)",
            lambda: parse_prices(numeric),
            lambda: [UPSTREAM.Price.fromstring(value) for value in numeric],
        ),
        (
            "batch amounts, numeric-only (100k)",
            lambda: parse_amounts(numeric),
            lambda: [
                UPSTREAM_PARSER.parse_number(
                    UPSTREAM_PARSER.extract_price_text(value)
                )
                for value in numeric
            ],
        ),
        (
            "batch amounts, long text (20k x 1KB)",
            lambda: parse_amounts(long_numeric),
            lambda: [
                UPSTREAM_PARSER.parse_number(
                    UPSTREAM_PARSER.extract_price_text(value)
                )
                for value in long_numeric
            ],
        ),
    ]

    print(f"Machine: {cpu_name()}, {platform.python_implementation()} {platform.python_version()}")
    print()
    print("| case | mojo-price-parser | price-parser 0.5.1 | speedup |")
    print("|---|---:|---:|---:|")
    for name, ours, theirs in cases:
        ours_result = ours()
        theirs_result = theirs()
        if ours_result and isinstance(ours_result[0], UPSTREAM.Price):
            ours_comparable = tupled(ours_result)
            theirs_comparable = tupled(theirs_result)
        elif ours_result and isinstance(ours_result[0], Price):
            ours_comparable = tupled(ours_result)
            theirs_comparable = tupled(theirs_result)
        else:
            ours_comparable = ours_result
            theirs_comparable = theirs_result
        if ours_comparable != theirs_comparable:
            raise AssertionError(f"benchmark outputs differ for {name}")
        ours_time, theirs_time = paired_times(ours, theirs)
        print(
            f"| {name} | {ours_time * 1e3:.1f} ms | "
            f"{theirs_time * 1e3:.1f} ms | {theirs_time / ours_time:.2f}x |"
        )


if __name__ == "__main__":
    main()
