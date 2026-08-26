# mojo-price-parser

`mojo-price-parser` is a Mojo-accelerated port of
[`price-parser`](https://github.com/scrapinghub/price-parser) for extracting
prices and currencies from messy text. It preserves the upstream Python API for
the covered surface and adds batch entry points that amortize the Python-to-Mojo
call cost.

The implementation targets upstream `price-parser` 0.5.1.

## Compatibility

Covered and tested against upstream:

- `Price`, including `amount`, `currency`, `amount_text`, and `amount_float`
- `Price.fromstring(price, currency_hint=None, decimal_separator=None,
  digit_group_separator=None)`
- the public `parse_price` alias
- amount extraction and parsing behavior exercised by the parity suite:
  separator guessing, explicit decimal and grouping separators, rejected
  percentages, `Free`, euro-as-decimal notation, Unicode whitespace, and
  Unicode decimal digits
- every vendored upstream currency code and symbol, plus currency hints and
  dollar-code priority

Extensions:

- `parse_prices` for full batch parsing and `parse_amounts` for amount-only
  batches

Not covered:

- compatibility for private upstream module contents, including the private
  `CURRENCIES` metadata dictionary; only parsing data and the public API above
  are supported
- a native Mojo `Decimal` or currency engine; Python still constructs
  `decimal.Decimal` results and runs the currency-pattern priority rules
- prebuilt libraries or platforms outside the repository's current Pixi Linux
  target

## Install

Install [Pixi](https://pixi.sh), clone this repository, and run:

```bash
pixi install
pixi run build
```

The build produces `dist/libmojo-price-parser.so`. All development commands run
inside the pinned environment:

```bash
pixi run test
pixi run bench
```

## Usage

```python
from price_parser import Price, parse_amounts, parse_prices

price = Price.fromstring("Běžná cena 75 990,00 Kč")
assert str(price.amount) == "75990.00"
assert price.currency == "Kč"
assert price.amount_text == "75 990,00"

prices = parse_prices(["Price: $1,234.56", "22,90 €", "Free"])
assert [str(item.amount) for item in prices] == ["1234.56", "22.90", "0"]

amounts = parse_amounts(["1,234.56", "9.990,00"])
assert [str(amount) for amount in amounts] == ["1234.56", "9990.00"]
```

Run the example after `pixi run build` with `pixi run python`.

## Benchmarks

Measured by `pixi run bench` on this machine, an Intel Xeon E5-2697 v4 at
2.30 GHz using CPython 3.13.14. Each figure is the best of three interleaved
process-CPU-time runs. The benchmark compares outputs before timing.

| case | mojo-price-parser | price-parser 0.5.1 | speedup |
|---|---:|---:|---:|
| single parse, mixed (100k) | 629.5 ms | 859.7 ms | 1.37x |
| batch parse, mixed (100k) | 596.5 ms | 833.5 ms | 1.40x |
| batch parse, numeric-only (100k) | 432.6 ms | 553.7 ms | 1.28x |
| batch amounts, numeric-only (100k) | 333.3 ms | 381.6 ms | 1.14x |
| batch amounts, long text (20k x 1KB) | 718.1 ms | 1116.8 ms | 1.56x |

Short single-item inputs stay in CPython's compiled regex because a ctypes call
costs more than their scan. Longer inputs use the Mojo scanner, and batch APIs
amortize the boundary cost. Long nonnumeric spans are skipped with unaligned-safe
`UInt8` SIMD loads and a scalar remainder loop. A thresholded CPU-parallel path
was measured and rejected: it increased process CPU time for the 20 MiB case
from 717.0 ms to 1137.0 ms. No GPU path is provided because this branch-heavy
byte scan performs well below two arithmetic operations per byte moved; transfer
and launch overhead would dominate.

## How it works

Short single prices use the compiled Python regex; longer prices are encoded as
UTF-8 and cross the C ABI directly from immutable bytes storage. A batch uses one
contiguous `bytearray` plus full-width offset and result arrays. Python owns all
memory, and live ctypes views pin the buffers for the duration of each call.
Buffer addresses cross the ABI as pointer-sized values, and the exported Mojo
functions reconstruct `UnsafePointer[..., AnyOrigin[mut=True]]` values inside
the shared library. Mojo writes amount start/end byte offsets into caller-owned
arrays, so there is no cross-language allocation or string ownership.

The ABI validates null pointers, signed lengths, monotonic offsets, and buffer
bounds before scanning. It returns a status code; Python raises on failure and
also validates every returned span before slicing.

The Mojo scanner implements the amount-extraction hot path, including the
upstream regex's percent rejection and punctuation backtracking. Rare
Unicode-decimal inputs use an exact Python regex fallback. Python then applies
the upstream currency priority tables and creates exact `Decimal` values.
`parse_prices` and `parse_amounts` pass all strings in one FFI call, which is why
they are the intended high-throughput interfaces.

Currency tables are generated from BSD-licensed upstream data; see
`THIRD_PARTY_NOTICES.md`.
