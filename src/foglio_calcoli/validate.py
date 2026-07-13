"""Generic validation: compare metrics(result) against an expected-values map (from a case's
config.toml [test] block). No taxpayer-specific data lives here."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .common import D, dec, fmt
from .models import Result, metrics


@dataclass
class Check:
    key: str
    expected: object
    got: object
    ok: bool

    @property
    def delta(self) -> str:
        if self.ok or self.got is None or isinstance(self.expected, (bool, int)):
            return ""
        try:
            return fmt(dec(self.got) - dec(self.expected))
        except Exception:
            return ""


def validate(res: Result, test: dict, default_tol: str = "0.01") -> list[Check]:
    """`test` is a case's [test] block ({expected: {...}, tolerance?, ...}) or a bare expected map."""
    expected = test.get("expected", test) if isinstance(test, dict) else {}
    tol_default = dec(test.get("tolerance", default_tol)) if isinstance(test, dict) else dec(default_tol)
    per_key_tol = test.get("tol", {}) if isinstance(test, dict) else {}
    m = metrics(res)
    checks: list[Check] = []
    for key, exp in expected.items():
        got = m.get(key)
        if isinstance(exp, bool):
            ok = (bool(got) == exp)
        elif isinstance(exp, int):                       # integer metric -> exact
            ok = (got is not None and int(got) == exp)
        else:
            if got is None:
                ok = False
            else:
                e, g = dec(exp), dec(got)
                tol = dec(per_key_tol[key]) if key in per_key_tol else max(tol_default, abs(e) * D("0.0005"))
                ok = abs(g - e) <= tol
        checks.append(Check(key, exp, got, ok))
    return checks


def format_checks(checks: list[Check], title: str = "") -> str:
    out = []
    if title:
        out.append(title)
    npass = sum(1 for c in checks if c.ok)
    for c in checks:
        flag = "OK  " if c.ok else "FAIL"
        d = f"  Δ={c.delta}" if (not c.ok and c.delta) else ""
        out.append(f"  [{flag}] {c.key:22s} expected {fmt(c.expected):>14s}  got {fmt(c.got):>14s}{d}")
    out.append(f"  {npass}/{len(checks)} checks passed")
    return "\n".join(out)
