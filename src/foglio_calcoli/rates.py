"""Banca d'Italia exchange rates: cached provider + on-demand fetch/auto-provisioning.

`rate_per_eur` in the bundled CSVs is the standard BdI quote (foreign units per 1 EUR).
"Cambio EUR" used everywhere = 1 / rate_per_eur (full precision; display truncates to 4 dp)."""
from __future__ import annotations

import csv
import json
import logging
import urllib.request
from datetime import date
from decimal import Decimal
from pathlib import Path

from .common import D

BDI_BASE = "https://tassidicambio.bancaditalia.it/terzevalute-wf-web/rest/v1.0"
log = logging.getLogger("foglio_calcoli.rates")


# --------------------------------------------------------------------------------------
# Provider (reads the cached data/*.csv)
# --------------------------------------------------------------------------------------
class RateProvider:
    """cambio_eur(cur, date) -> daily (RM/M, RT/T); cambio_eur_monthly(cur, y, m) -> monthly (RW/W).
    Both return full-precision Decimal = 1/rate_per_eur; EUR is always 1."""

    def __init__(self, ref_dir: Path):
        self.ref_dir = Path(ref_dir)
        self._daily: dict[tuple[str, str], Decimal] = {}
        self._daily_dates: dict[str, list[str]] = {}
        self._monthly: dict[tuple[str, int, int], Decimal] = {}
        self.reload()

    def reload(self) -> None:
        self._daily.clear(); self._daily_dates.clear(); self._monthly.clear()
        with open(self.ref_dir / "bdi_daily_eur.csv") as f:
            for r in csv.DictReader(f):
                self._daily[(r["date"], r["iso_code"])] = D(r["rate_per_eur"])
                self._daily_dates.setdefault(r["iso_code"], []).append(r["date"])
        for iso in self._daily_dates:
            self._daily_dates[iso].sort()
        with open(self.ref_dir / "bdi_monthly_eur.csv") as f:
            for r in csv.DictReader(f):
                self._monthly[(r["iso_code"], int(r["year"]), int(r["month"]))] = D(r["rate_per_eur"])

    def has_daily_year(self, cur: str, year: int) -> bool:
        return any(d.startswith(f"{year}-") for d in self._daily_dates.get(cur, []))

    def has_monthly_year(self, cur: str, year: int) -> bool:
        return any(k[0] == cur and k[1] == year for k in self._monthly)

    def _daily_rate(self, cur: str, d: date) -> Decimal:
        key = d.isoformat()
        if (key, cur) in self._daily:
            return self._daily[(key, cur)]
        dates = self._daily_dates.get(cur)                      # nearest prior business day
        if not dates:
            raise KeyError(f"No BdI daily rates for {cur}. Run: python3 data/fetch_bdi_rates.py "
                           f"{d.year} {cur}")
        prior = [x for x in dates if x <= key]
        if not prior:
            raise KeyError(f"No BdI daily rate on/before {key} for {cur}.")
        return self._daily[(prior[-1], cur)]

    def cambio_eur(self, cur: str, d: date) -> Decimal:
        if cur == "EUR":
            return D(1)
        return D(1) / self._daily_rate(cur, d)

    def cambio_eur_monthly(self, cur: str, year: int, month: int) -> Decimal:
        if cur == "EUR":
            return D(1)
        try:
            return D(1) / self._monthly[(cur, year, month)]
        except KeyError:
            raise KeyError(f"No BdI monthly rate for {cur} {year}-{month:02d}. Run: "
                           f"python3 data/fetch_bdi_rates.py {year} {cur}")


# --------------------------------------------------------------------------------------
# Fetch (network) — importable; also wrapped by data/fetch_bdi_rates.py as a CLI
# --------------------------------------------------------------------------------------
def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _fetch_daily(year: int, cur: str) -> list[tuple[str, str, str]]:
    url = (f"{BDI_BASE}/dailyTimeSeries?startDate={year}-01-01&endDate={year}-12-31"
           f"&baseCurrencyIsoCode={cur}&currencyIsoCode=EUR&lang=en")
    out = []
    for rec in _get(url).get("rates", []):
        d, rate = rec.get("referenceDate"), rec.get("avgRate")
        if d and rate not in (None, "", "N.A."):
            out.append((d, cur, rate))
    return out


def _fetch_monthly(year: int, cur: str) -> list[tuple[int, int, str, str]]:
    url = (f"{BDI_BASE}/monthlyTimeSeries?startMonth=1&startYear={year}&endMonth=12&endYear={year}"
           f"&baseCurrencyIsoCode={cur}&currencyIsoCode=EUR&lang=en")
    out = []
    for rec in _get(url).get("rates", []):
        ym, rate = rec.get("referenceDate", ""), rec.get("avgRate")
        if "-" in ym and rate not in (None, "", "N.A."):
            y, m = ym.split("-")
            out.append((int(y), int(m), cur, rate))
    return out


def fetch_rates(years, currencies, ref_dir: Path) -> None:
    """Merge BdI daily+monthly rates for the given years/currencies into the cached data/ CSVs
    (additive & idempotent). EUR is skipped (always 1)."""
    ref_dir = Path(ref_dir)
    years = sorted({int(y) for y in years})
    currencies = sorted({c for c in currencies if c and c != "EUR"})
    if not currencies or not years:
        return

    daily: dict[tuple[str, str], str] = {}
    monthly: dict[tuple[int, int, str], str] = {}
    dpath, mpath = ref_dir / "bdi_daily_eur.csv", ref_dir / "bdi_monthly_eur.csv"
    if dpath.exists():
        for r in csv.DictReader(open(dpath)):
            daily[(r["date"], r["iso_code"])] = r["rate_per_eur"]
    if mpath.exists():
        for r in csv.DictReader(open(mpath)):
            monthly[(int(r["year"]), int(r["month"]), r["iso_code"])] = r["rate_per_eur"]

    for cur in currencies:
        for year in years:
            for d, c, rate in _fetch_daily(year, cur):
                daily[(d, c)] = rate
            for y, m, c, rate in _fetch_monthly(year, cur):
                monthly[(y, m, c)] = rate

    with open(dpath, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "iso_code", "rate_per_eur"])
        for (d, c), rate in sorted(daily.items()):
            w.writerow([d, c, rate])
    with open(mpath, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["year", "month", "iso_code", "rate_per_eur"])
        for (y, m, c), rate in sorted(monthly.items()):
            w.writerow([y, m, c, rate])


def ensure_rates(ref_dir: Path, years, currencies, allow_fetch: bool = True) -> RateProvider:
    """Return a RateProvider whose cache covers the needed (currency, year) pairs, fetching the
    missing ones if allowed, else raising a precise, actionable error."""
    provider = RateProvider(ref_dir)
    years = sorted({int(y) for y in years})
    currencies = sorted({c for c in currencies if c and c != "EUR"})
    missing = [(c, y) for c in currencies for y in years
               if not (provider.has_daily_year(c, y) and provider.has_monthly_year(c, y))]
    if not missing:
        return provider
    pairs = ", ".join(f"{c} {y}" for c, y in missing)
    if not allow_fetch:
        raise RuntimeError(f"Missing BdI rates for: {pairs}. Run: python3 data/fetch_bdi_rates.py "
                           f"<year> <CUR ...>  (or set allow_fetch = true in config.toml)")
    try:
        log.info("Fetching missing BdI rates from Banca d'Italia: %s", pairs)
        fetch_rates({y for _, y in missing}, {c for c, _ in missing}, ref_dir)
    except Exception as e:                                  # network/offline
        raise RuntimeError(f"Could not fetch BdI rates for: {pairs} ({e}). Fetch them online with: "
                           f"python3 data/fetch_bdi_rates.py <year> <CUR ...>") from e
    provider.reload()
    return provider
