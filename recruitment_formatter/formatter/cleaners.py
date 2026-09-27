"""
Per-dtype value cleaning. Keeps garbage out of the CRM: normalizes phone
numbers, parses currency shorthand like "$419k" / "$1.18M", coerces
numeric strings, and strips junk from URLs.

Every cleaner is defensive: bad/unparseable input becomes "" (MISSING_VALUE)
rather than raising, since a single bad cell must never kill a whole file.
"""
from __future__ import annotations
import math
import re

_CURRENCY_RE = re.compile(r"[^\d.kKmM]")
_DIGITS_RE = re.compile(r"\D+")


def _is_blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def clean_str(value) -> str:
    if _is_blank(value):
        return ""
    return str(value).strip()


def clean_int(value):
    if _is_blank(value):
        return ""
    try:
        # handles "153", "153.0", 153.0
        return int(float(str(value).strip().replace(",", "")))
    except (ValueError, TypeError):
        digits = _DIGITS_RE.sub("", str(value))
        return int(digits) if digits else ""


def clean_float(value):
    if _is_blank(value):
        return ""
    try:
        return round(float(str(value).strip().replace(",", "")), 2)
    except (ValueError, TypeError):
        return ""


def clean_currency(value):
    """Parses '$419k', '$1.18M', '810000', 810000 -> plain int (dollars)."""
    if _is_blank(value):
        return ""
    s = str(value).strip()
    multiplier = 1
    if s.lower().endswith("k"):
        multiplier = 1_000
    elif s.lower().endswith("m"):
        multiplier = 1_000_000
    cleaned = _CURRENCY_RE.sub("", s).rstrip("kKmM")
    try:
        return int(round(float(cleaned) * multiplier))
    except (ValueError, TypeError):
        return ""


def clean_phone(value):
    """Normalizes to digits only, preserving a leading '+' if present."""
    if _is_blank(value):
        return ""
    s = str(value).strip()
    plus = "+" if s.startswith("+") else ""
    digits = _DIGITS_RE.sub("", s)
    return f"{plus}{digits}" if digits else ""


def clean_url(value) -> str:
    if _is_blank(value):
        return ""
    s = str(value).strip()
    if s and not s.lower().startswith(("http://", "https://")):
        s = "https://" + s
    return s


CLEANERS = {
    "str": clean_str,
    "int": clean_int,
    "float": clean_float,
    "currency": clean_currency,
    "phone": clean_phone,
    "url": clean_url,
}


def clean_value(dtype: str, value):
    fn = CLEANERS.get(dtype, clean_str)
    return fn(value)
