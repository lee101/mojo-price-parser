from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


def load_currency_module(source: Path):
    spec = importlib.util.spec_from_file_location("_vendor_currencies", source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def format_tuple(name: str, values: list[str]) -> str:
    lines = [f"{name} = ("]
    current = "    "
    for value in values:
        item = repr(value) + ", "
        if len(current) + len(item) > 88:
            lines.append(current.rstrip())
            current = "    "
        current += item
    if current.strip():
        lines.append(current.rstrip())
    lines.append(")")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    module = load_currency_module(args.source)
    sections = [
        "# Generated from price-parser 0.5.1 currency data (BSD-3-Clause).",
        format_tuple("CURRENCY_CODES", list(module.CURRENCY_CODES)),
        format_tuple("CURRENCY_SYMBOLS", sorted(module.CURRENCY_SYMBOLS)),
        format_tuple(
            "CURRENCY_NATIONAL_SYMBOLS",
            sorted(module.CURRENCY_NATIONAL_SYMBOLS),
        ),
    ]
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    args.destination.write_text("\n\n".join(sections) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
