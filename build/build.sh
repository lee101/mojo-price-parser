#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$repo_dir/dist"
mojo build --emit shared-lib --optimization-level=3 \
    "$repo_dir/src/price_parser.mojo" \
    -o "$repo_dir/dist/libmojo-price-parser.so"
