from __future__ import annotations

import ctypes
import re
import string
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from re import Pattern
from typing import Callable

from ._currency_data import (
    CURRENCY_CODES,
    CURRENCY_NATIONAL_SYMBOLS,
    CURRENCY_SYMBOLS,
)
from ._lib import address, bytes_address, lib


@dataclass
class Price:
    amount: Decimal | None
    currency: str | None
    amount_text: str | None = field(repr=False)

    @property
    def amount_float(self) -> float | None:
        if self.amount is not None:
            return float(self.amount)
        return None

    @classmethod
    def fromstring(
        cls,
        price: str | None,
        currency_hint: str | None = None,
        decimal_separator: str | None = None,
        digit_group_separator: str | None = None,
    ) -> Price:
        currency = extract_currency_symbol(price, currency_hint)
        if currency is not None:
            currency = currency.strip()
        if digit_group_separator is not None and price is not None:
            price = price.replace(digit_group_separator, "")
        amount_text = extract_price_text(price) if price is not None else None
        amount = (
            parse_number(amount_text, decimal_separator)
            if amount_text is not None
            else None
        )
        return cls(amount=amount, currency=currency, amount_text=amount_text)


parse_price = Price.fromstring


def or_regex(symbols: Sequence[str]) -> Pattern[str]:
    return re.compile("|".join(re.escape(symbol) for symbol in symbols))


SAFE_CURRENCY_SYMBOLS = [
    "Bds$", "CUC$", "MOP$", "AR$", "AU$", "BN$", "BZ$", "CA$", "CL$",
    "CO$", "CV$", "HK$", "MX$", "NT$", "NZ$", "TT$", "RD$", "WS$",
    "US$", "$U", "C$", "J$", "N$", "R$", "S$", "T$", "Z$", "A$",
    "SY£", "LB£", "CN¥", "GH₵", "$", "€", "£", "zł", "Zł", "Kč",
    "₽", "¥", "￥", "฿", "դր.", "դր", "₦", "₴", "₱", "৳", "₭",
    "₪", "﷼", "៛", "₩", "₫", "₡", "টকা", "ƒ", "₲", "؋", "₮",
    "नेरू", "₨", "₶", "₾", "֏", "ރ", "৲", "૱", "௹", "₠", "₢",
    "₣", "₤", "₧", "₯", "₰", "₳", "₷", "₸", "₹", "₺", "₼",
    "₾", "₿", "ℳ", "ر.ق.\u200f", "د.ك.\u200f", "د.ع.\u200f",
    "ر.ع.\u200f", "ر.ي.\u200f", "ر.س.\u200f", "د.ج.\u200f",
    "د.م.\u200f", "د.إ.\u200f", "د.ت.\u200f", "د.ل.\u200f",
    "ل.س.\u200f", "د.ب.\u200f", "د.أ.\u200f", "ج.م.\u200f",
    "ل.ل.\u200f", " تومان", "تومان", "درهم", "ريال", "جنيه", "EUR",
    "euro", "eur", "CHF", "DKK", "Rp", "lei", "руб.", "руб", "грн.",
    "грн", "дин.", "Dinara", "динар", "лв.", "лв", "р.", "тңг",
    "тңг.", "ман.",
]

DOLLAR_CODES = [code for code in CURRENCY_CODES if code.endswith("D")]
_DOLLAR_REGEX = re.compile(
    r"\b(?:{})(?=\$?(?:[\W\d]|$))".format(
        "|".join(re.escape(code) for code in DOLLAR_CODES)
    )
)
OTHER_CURRENCY_SYMBOLS = sorted(
    (
        set(CURRENCY_CODES)
        | set(CURRENCY_SYMBOLS)
        | set(CURRENCY_NATIONAL_SYMBOLS)
        | {"р", "Р"}
    )
    - set(SAFE_CURRENCY_SYMBOLS)
    - {"-", "XXX"}
    - set(string.ascii_uppercase),
    key=lambda symbol: (-len(symbol), symbol),
)

_search_dollar_code = _DOLLAR_REGEX.search
_search_safe_currency = or_regex(SAFE_CURRENCY_SYMBOLS).search
_search_unsafe_currency = or_regex(OTHER_CURRENCY_SYMBOLS).search


def extract_currency_symbol(
    price: str | None, currency_hint: str | None
) -> str | None:
    methods: list[
        tuple[Callable[[str], re.Match[str] | None], str | None]
    ] = [
        (_search_safe_currency, price),
        (_search_safe_currency, currency_hint),
        (_search_unsafe_currency, price),
        (_search_unsafe_currency, currency_hint),
    ]
    if currency_hint and "$" in currency_hint:
        methods.insert(0, (_search_dollar_code, currency_hint))
    if price and "$" in price:
        methods.insert(0, (_search_dollar_code, price))
    for search, value in methods:
        match = search(value) if value else None
        if match:
            return match.group(0)
    return None


_EURO_PRICE_RE = re.compile(
    r"""
    [\d\s.,']*?\d
    \s*?€(\s*?)?
    \d(?(1)\d|\d*?)
    (?:$|[^\d])
    """,
    re.VERBOSE,
)
_REGULAR_PRICE_RE = re.compile(
    r"""
    ([.]?\d[\d\s.,']*)
    \s*?
    (?:[^%\d]|$)
    """,
    re.VERBOSE,
)
_SEARCH_NONSTANDARD_WHITESPACE = re.compile(r"[^\S ]| {2}").search


def _normalize_whitespace(price: str) -> str:
    if _SEARCH_NONSTANDARD_WHITESPACE(price):
        return re.sub(r"\s+", " ", price)
    return price


def _clean_amount_text(value: str) -> str:
    value = value.rstrip(",.").replace("'", "")
    if value.count(".") == 1:
        return value.strip()
    return value.lstrip(",.").strip()


def _extract_regular_python(price: str) -> str | None:
    match = _REGULAR_PRICE_RE.search(price)
    return _clean_amount_text(match.group(1)) if match else None


def _extract_regular(price: str) -> str | None:
    if not price.isascii() and any(
        char.isdecimal() and not char.isascii() for char in price
    ):
        return _extract_regular_python(price)
    encoded = price.encode("utf-8")
    result = (ctypes.c_int64 * 2)(-1, -1)
    status = lib().mpp_extract_one(
        bytes_address(encoded), len(encoded), address(result)
    )
    if status != 0:
        raise RuntimeError(f"Mojo amount extraction failed with status {status}")
    start, end = result
    if start < 0:
        return None
    if not (0 <= start <= end <= len(encoded)):
        raise RuntimeError("Mojo amount extraction returned an invalid span")
    return _clean_amount_text(encoded[start:end].decode("utf-8"))


def extract_price_text(price: str) -> str | None:
    price = _normalize_whitespace(price)
    if price.count("€") == 1:
        match = _EURO_PRICE_RE.search(price)
        if match:
            return match.group(0).replace(" ", "")
    amount_text = _extract_regular(price)
    if amount_text is not None:
        return amount_text
    if "free" in price.lower():
        return "0"
    return None


def get_decimal_separator(price: str) -> str | None:
    if not price:
        return None
    separator_index = max(price.rfind("."), price.rfind(","), price.rfind("€"))
    if separator_index < 0:
        return None
    suffix = price[separator_index + 1 :]
    if suffix.isdecimal() and len(suffix) != 3:
        return price[separator_index]
    return None


def parse_number(
    num: str, decimal_separator: str | None = None
) -> Decimal | None:
    if not num:
        return None
    num = num.strip().replace(" ", "")
    decimal_separator = decimal_separator or get_decimal_separator(num)
    if decimal_separator is None:
        num = num.replace(".", "").replace(",", "")
    elif decimal_separator == ".":
        num = num.replace(",", "")
    elif decimal_separator == ",":
        num = num.replace(".", "").replace(",", ".")
    elif decimal_separator == "€":
        num = num.replace(".", "").replace(",", "").replace("€", ".")
    else:
        raise AssertionError(f"unsupported decimal separator: {decimal_separator!r}")
    try:
        return Decimal(num)
    except InvalidOperation:
        return None


def _expand_argument(
    value: str | None | Sequence[str | None], count: int, name: str
) -> list[str | None]:
    if value is None or isinstance(value, str):
        return [value] * count
    values = list(value)
    if len(values) != count:
        raise ValueError(f"{name} must have the same length as prices")
    return values


def _extract_many_amount_texts(
    values: Sequence[str | None], group_separators: Sequence[str | None]
) -> list[str | None]:
    count = len(values)
    prepared: list[str] = []
    special: list[str | None] = [None] * count
    use_python_result = [False] * count
    packed = bytearray()
    offsets = [0]
    for index, raw in enumerate(values):
        price = raw or ""
        if raw is not None and group_separators[index] is not None:
            price = price.replace(group_separators[index] or "", "")
        price = _normalize_whitespace(price)
        prepared.append(price)
        if price.count("€") == 1:
            match = _EURO_PRICE_RE.search(price)
            if match:
                special[index] = match.group(0).replace(" ", "")
                use_python_result[index] = True
        if (
            special[index] is None
            and not price.isascii()
            and any(char.isdecimal() and not char.isascii() for char in price)
        ):
            special[index] = _extract_regular_python(price)
            use_python_result[index] = True
        encoded = price.encode("utf-8")
        packed.extend(encoded)
        offsets.append(len(packed))

    if count == 0:
        return []
    data = (
        (ctypes.c_char * len(packed)).from_buffer(packed)
        if packed
        else (ctypes.c_char * 1)()
    )
    offset_data = (ctypes.c_int64 * (count + 1))(*offsets)
    starts = (ctypes.c_int64 * count)(*([-1] * count))
    ends = (ctypes.c_int64 * count)(*([-1] * count))
    status = lib().mpp_extract_many(
        address(data),
        len(packed),
        address(offset_data),
        count,
        address(starts),
        address(ends),
    )
    if status != 0:
        raise RuntimeError(f"Mojo batch extraction failed with status {status}")

    amount_texts: list[str | None] = []
    for index, price in enumerate(prepared):
        amount_text = special[index]
        if (
            amount_text is None
            and not use_python_result[index]
            and starts[index] >= 0
        ):
            absolute_start = offsets[index] + starts[index]
            absolute_end = offsets[index] + ends[index]
            if not (
                offsets[index]
                <= absolute_start
                <= absolute_end
                <= offsets[index + 1]
            ):
                raise RuntimeError(
                    f"Mojo amount extraction returned an invalid span at index {index}"
                )
            amount_text = _clean_amount_text(
                packed[absolute_start:absolute_end].decode("utf-8")
            )
        if amount_text is None and "free" in price.lower():
            amount_text = "0"
        amount_texts.append(amount_text)
    return amount_texts


def parse_amounts(
    prices: Iterable[str | None],
    decimal_separator: str | None | Sequence[str | None] = None,
    digit_group_separator: str | None | Sequence[str | None] = None,
) -> list[Decimal | None]:
    values = list(prices)
    count = len(values)
    decimal_separators = _expand_argument(
        decimal_separator, count, "decimal_separator"
    )
    group_separators = _expand_argument(
        digit_group_separator, count, "digit_group_separator"
    )
    amount_texts = _extract_many_amount_texts(values, group_separators)
    return [
        parse_number(amount_text, separator)
        if amount_text is not None
        else None
        for amount_text, separator in zip(
            amount_texts, decimal_separators, strict=True
        )
    ]


def parse_prices(
    prices: Iterable[str | None],
    currency_hint: str | None | Sequence[str | None] = None,
    decimal_separator: str | None | Sequence[str | None] = None,
    digit_group_separator: str | None | Sequence[str | None] = None,
) -> list[Price]:
    values = list(prices)
    count = len(values)
    hints = _expand_argument(currency_hint, count, "currency_hint")
    decimal_separators = _expand_argument(
        decimal_separator, count, "decimal_separator"
    )
    group_separators = _expand_argument(
        digit_group_separator, count, "digit_group_separator"
    )
    amount_texts = _extract_many_amount_texts(values, group_separators)
    parsed: list[Price] = []
    for index, raw in enumerate(values):
        currency = extract_currency_symbol(raw, hints[index])
        if currency is not None:
            currency = currency.strip()
        amount_text = amount_texts[index]
        amount = (
            parse_number(amount_text, decimal_separators[index])
            if amount_text is not None
            else None
        )
        parsed.append(Price(amount, currency, amount_text))
    return parsed
