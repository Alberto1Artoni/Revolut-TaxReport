"""Shared primitives: Decimal setup, constants, and small parsing/formatting helpers."""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, getcontext, ROUND_DOWN, ROUND_HALF_UP
from zoneinfo import ZoneInfo

getcontext().prec = 28
D = Decimal
ROME = ZoneInfo("Europe/Rome")

IVAFE_RATE = D("0.002")            # 0.2%
SOSTITUTIVA = D("0.26")            #  26%


def dec(x) -> Decimal:
    """Coerce a value (str/number/Decimal) to Decimal without float rounding."""
    return x if isinstance(x, Decimal) else D(str(x))


def trunc4(x: Decimal) -> Decimal:
    """Truncate (not round) to 4 decimals — mirrors the reference display."""
    return x.quantize(D("0.0001"), rounding=ROUND_DOWN)


def euro(x: Decimal) -> int:
    """Round to nearest integer euro (summary 'Ammontare' / 'IVAFE')."""
    return int(x.quantize(D("1"), rounding=ROUND_HALF_UP))


def fmt(x) -> str:
    """Human display: truncate to 4 dp, trim trailing zeros."""
    if x is None:
        return ""
    if isinstance(x, Decimal):
        s = format(trunc4(x), "f")
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s
    return str(x)


def parse_money(s: str) -> tuple[str | None, Decimal | None]:
    """'EUR 500' / 'USD -539.40' -> ('USD', Decimal). Empty -> (None, None)."""
    s = (s or "").strip()
    if not s:
        return None, None
    parts = s.split()
    if len(parts) == 1:                       # no currency prefix
        return None, D(parts[0].replace(",", ""))
    cur = parts[0]
    val = D("".join(parts[1:]).replace(",", ""))
    return cur, val


def parse_num(s: str) -> Decimal:
    """Strip currency symbols/spaces from a numeric string: '€1.27' -> 1.27, '$0' -> 0."""
    s = (s or "").strip()
    s = re.sub(r"[€$£\s]", "", s).replace(",", "")
    return D(s) if s not in ("", "-") else D("0")


def to_date(iso: str) -> date:
    """ISO-8601 UTC timestamp -> calendar date in Europe/Rome (CET/CEST)."""
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return dt.astimezone(ROME).date()


def doy(d: date, year: int) -> int:
    """Day-of-year index with Jan 1 = 1; Jan 1 of the next year = 366 (365-day partition)."""
    return (d - date(year, 1, 1)).days + 1
