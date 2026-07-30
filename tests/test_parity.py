from __future__ import annotations

import ctypes
import importlib.metadata
import importlib.util
import random
import sys
from decimal import Decimal
from pathlib import Path

import pytest

import price_parser
from price_parser import Price, parse_amounts, parse_price, parse_prices
from price_parser._currency_data import (
    CURRENCY_CODES,
    CURRENCY_NATIONAL_SYMBOLS,
    CURRENCY_SYMBOLS,
)
from price_parser import parser
from price_parser._lib import address, lib


def _load_upstream():
    package = Path(
        importlib.metadata.distribution("price-parser").locate_file("price_parser")
    )
    spec = importlib.util.spec_from_file_location(
        "upstream_price_parser",
        package / "__init__.py",
        submodule_search_locations=[str(package)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


UPSTREAM = _load_upstream()
UPSTREAM_PARSER = sys.modules["upstream_price_parser.parser"]


VECTORS = [
    (None, None, None, None),
    ("", None, None, None),
    ("Foo", None, None, None),
    ("Free", None, None, None),
    ("50% OFF", None, None, None),
    ("Price: $119.00", None, None, None),
    ("15 130 Р", None, None, None),
    ("151,200 تومان", None, None, None),
    ("Rp 1.550.000", None, None, None),
    ("Běžná cena 75 990,00 Kč", None, None, None),
    ("1,235€ 99", None, None, None),
    ("99 € 95 €", None, None, None),
    ("35€ 999", None, None, None),
    ("$1\xa0298,00", None, None, None),
    ("CHF 1'049,95", None, None, None),
    ("$.75", None, None, None),
    ("$..75", None, None, None),
    ("$.750.30", None, None, None),
    ("140.000", None, ".", None),
    ("140.000", None, ",", None),
    ("140,000€33", None, "€", None),
    ("34.99", "руб. (шт)", None, None),
    ("NZD $123", None, None, None),
    ("AU $59.95", None, None, None),
    ("CAD$1.23", None, None, None),
    ("AED 8000 (USD 2179)", None, None, None),
    ("205,68 € 205.68", None, None, None),
    ("3,439.00 درهم", None, None, None),
    ("106.61 ريال", None, None, None),
    ("1 2 3 4 5 6 7 8 9 10", "$", None, None),
    ("2.999,00 EUR (-10,00%)", None, None, None),
    ("123,456.789 OMR", None, ".", ","),
    (" \t423.923 KD\n", None, ".", None),
    ("₤1700.", None, None, None),
    ("12,000원", None, None, None),
    ("3,500円", None, None, None),
    ("१२.३४ ₹", None, None, None),
]


@pytest.mark.parametrize(
    ("raw", "hint", "decimal_separator", "group_separator"), VECTORS
)
def test_price_parity(raw, hint, decimal_separator, group_separator):
    ours = Price.fromstring(raw, hint, decimal_separator, group_separator)
    theirs = UPSTREAM.Price.fromstring(
        raw, hint, decimal_separator, group_separator
    )
    assert (ours.amount, ours.currency, ours.amount_text) == (
        theirs.amount,
        theirs.currency,
        theirs.amount_text,
    )


ALL_CURRENCIES = sorted(
    set(CURRENCY_CODES) | set(CURRENCY_SYMBOLS) | set(CURRENCY_NATIONAL_SYMBOLS)
)


@pytest.mark.parametrize("symbol", ALL_CURRENCIES)
def test_currency_table_parity(symbol):
    raw = f"1 {symbol}"
    assert parser.extract_currency_symbol(
        raw, None
    ) == UPSTREAM_PARSER.extract_currency_symbol(raw, None)


SEPARATORS = [",", ".", " ", "'", "\xa0"]
FORMATS = []
_rng = random.Random(7206)
for _ in range(250):
    whole = _rng.randint(0, 99_999_999)
    cents = _rng.randint(0, 99)
    group = _rng.choice(SEPARATORS)
    decimal = "," if group == "." else "."
    grouped = f"{whole:,}".replace(",", group)
    currency = _rng.choice(["$", "€", "GBP", "Kč", "руб.", ""])
    FORMATS.append(f"Now {currency}{grouped}{decimal}{cents:02d} each")


@pytest.mark.parametrize("raw", FORMATS)
def test_generated_price_parity(raw):
    ours = Price.fromstring(raw)
    theirs = UPSTREAM.Price.fromstring(raw)
    assert (ours.amount, ours.currency, ours.amount_text) == (
        theirs.amount,
        theirs.currency,
        theirs.amount_text,
    )


@pytest.mark.parametrize("raw", [vector[0] for vector in VECTORS if vector[0]])
def test_internal_amount_helpers_parity(raw):
    assert parser.extract_price_text(raw) == UPSTREAM_PARSER.extract_price_text(raw)
    amount_text = parser.extract_price_text(raw)
    if amount_text is not None:
        assert parser.get_decimal_separator(
            amount_text.replace(" ", "")
        ) == UPSTREAM_PARSER.get_decimal_separator(amount_text.replace(" ", ""))
        assert parser.parse_number(amount_text) == UPSTREAM_PARSER.parse_number(
            amount_text
        )


def test_batch_matches_individual_and_upstream():
    raw = [vector[0] for vector in VECTORS] + FORMATS
    hints = [vector[1] for vector in VECTORS] + [None] * len(FORMATS)
    ours = parse_prices(raw, currency_hint=hints)
    individual = [
        Price.fromstring(value, hint) for value, hint in zip(raw, hints, strict=True)
    ]
    theirs = [
        UPSTREAM.Price.fromstring(value, hint)
        for value, hint in zip(raw, hints, strict=True)
    ]
    as_tuples = lambda values: [
        (value.amount, value.currency, value.amount_text) for value in values
    ]
    assert as_tuples(ours) == as_tuples(individual) == as_tuples(theirs)
    assert parse_amounts(raw) == [item.amount for item in theirs]


@pytest.mark.parametrize("prefix_length", [0, 1, 15, 16, 31, 32, 33, 63, 64, 65])
def test_simd_scan_and_scalar_tail_parity(prefix_length):
    prefix = "x" * prefix_length
    raw = [
        f"{prefix} 12.34 each",
        f"{prefix}.75 USD",
        f"{prefix} 12.34,% off",
        f"{prefix} 12.34 % off 7.89",
        f"{prefix}1\t7% off 2",
        prefix,
    ]
    assert parse_amounts(raw) == [
        UPSTREAM_PARSER.parse_number(UPSTREAM_PARSER.extract_price_text(value))
        for value in raw
    ]


def test_parallel_byte_threshold_parity():
    count = 4096
    value = b"x" * 16_376 + b" 1.99"
    packed = bytearray(value * count)
    offsets = (ctypes.c_int64 * (count + 1))(
        *range(0, len(packed) + 1, len(value))
    )
    starts = (ctypes.c_int64 * count)()
    ends = (ctypes.c_int64 * count)()

    def extract():
        data = (ctypes.c_char * len(packed)).from_buffer(packed)
        lib().mpp_extract_many(
            address(data),
            len(packed),
            address(offsets),
            count,
            address(starts),
            address(ends),
        )

    extract()
    assert (starts[0], ends[0], starts[-1], ends[-1]) == (
        16_377,
        16_381,
        16_377,
        16_381,
    )

    packed.extend(b"x" * 32_768)
    offsets[-1] = len(packed)
    extract()
    assert (starts[0], ends[0], starts[-1], ends[-1]) == (
        16_377,
        16_381,
        16_377,
        16_381,
    )


def test_batch_arguments_and_empty_input():
    assert parse_prices([]) == []
    with pytest.raises(ValueError):
        parse_prices(["1", "2"], decimal_separator=["."])
    parsed = parse_prices(
        ["1.234", "1,234"],
        decimal_separator=[".", ","],
        digit_group_separator=[None, None],
    )
    assert [item.amount for item in parsed] == [Decimal("1.234"), Decimal("1.234")]


def test_public_api_and_repr():
    assert price_parser.__all__ == [
        "Price",
        "parse_price",
        "parse_prices",
        "parse_amounts",
    ]
    assert parse_price("22,90 €") == Price.fromstring("22,90 €")
    value = Price(Decimal("1.20"), "USD", "1.20")
    assert repr(value) == "Price(amount=Decimal('1.20'), currency='USD')"
    assert value.amount_float == 1.2
    assert Price(None, None, None).amount_float is None


def test_ffi_rejects_invalid_lengths_offsets_and_pointers():
    result = (ctypes.c_int64 * 2)(123, 456)
    assert lib().mpp_extract_one(None, -1, address(result)) == -1
    assert lib().mpp_extract_one(None, 1, address(result)) == -1
    assert lib().mpp_extract_one(None, 0, address(result)) == 0
    assert tuple(result) == (-1, -1)

    data = (ctypes.c_char * 3)(*b"123")
    starts = (ctypes.c_int64 * 2)()
    ends = (ctypes.c_int64 * 2)()
    for offsets in (
        (ctypes.c_int64 * 3)(1, 2, 3),
        (ctypes.c_int64 * 3)(0, 2, 1),
        (ctypes.c_int64 * 3)(0, 2, 4),
    ):
        assert (
            lib().mpp_extract_many(
                address(data),
                3,
                address(offsets),
                2,
                address(starts),
                address(ends),
            )
            == -2
        )
    valid_offsets = (ctypes.c_int64 * 3)(0, 1, 3)
    assert (
        lib().mpp_extract_many(
            address(data),
            3,
            address(valid_offsets),
            -1,
            address(starts),
            address(ends),
        )
        == -1
    )
