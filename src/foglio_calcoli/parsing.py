"""Input parsing (Revolut account statement + P&L statement), instrument metadata,
AdE country codes, and optional opening-position/opening-cash inputs."""
from __future__ import annotations

import csv
import glob
import html
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from .common import D, ROME, dec, parse_money, parse_num


# --------------------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------------------
@dataclass
class Txn:
    dt: datetime
    d: date
    ticker: str
    type: str                       # CASH TOP-UP / CASH WITHDRAWAL / BUY / SELL / DIVIDEND
    qty: Decimal | None
    price_cur: str | None
    price: Decimal | None
    total_cur: str | None
    total: Decimal | None
    currency: str
    fx: Decimal                     # units of `currency` per 1 EUR (Revolut)

    @property
    def is_buy(self) -> bool:
        return self.type.startswith("BUY")

    @property
    def is_sell(self) -> bool:
        return self.type.startswith("SELL")


@dataclass
class Dividend:
    d: date
    symbol: str
    name: str
    isin: str
    country: str
    gross_eur: Decimal
    wh_eur: Decimal
    net_eur: Decimal
    currency: str


@dataclass
class Sell:
    acquired: date
    sold: date
    symbol: str
    name: str
    isin: str
    country: str
    qty: Decimal
    cost_basis: Decimal
    gross_proceeds: Decimal
    gross_pnl: Decimal
    currency: str


@dataclass
class Meta:
    isin: str | None = None
    name: str | None = None
    country: str | None = None
    is_fund: bool = False


@dataclass
class OpeningPosition:
    """A holding carried into the fiscal year from a prior year.
    `pmc_eur` is the carried average cost per unit expressed in EUR."""
    ticker: str
    qty: Decimal
    pmc_eur: Decimal
    open_date: date
    currency: str
    is_fund: bool = False


KNOWN_TYPES = {"CASH TOP-UP", "CASH WITHDRAWAL", "BUY - MARKET", "SELL - MARKET",
               "BUY", "SELL", "DIVIDEND"}


# --------------------------------------------------------------------------------------
# File discovery
# --------------------------------------------------------------------------------------
def find(input_dir: Path, pattern: str) -> Path:
    matches = sorted(glob.glob(str(input_dir / pattern)))
    if not matches:
        raise FileNotFoundError(f"No file matching {pattern} in {input_dir}")
    return Path(matches[0])


# --------------------------------------------------------------------------------------
# Account statement (transaction ledger)
# --------------------------------------------------------------------------------------
def parse_account(path: Path) -> list[Txn]:
    txns: list[Txn] = []
    with open(path) as f:
        for i, r in enumerate(csv.DictReader(f), start=2):
            typ = r["Type"].strip()
            if typ and not any(typ.startswith(k) for k in ("BUY", "SELL")) and typ not in KNOWN_TYPES:
                raise ValueError(f"{path.name}:{i}: unknown transaction Type {typ!r}")
            dt = datetime.fromisoformat(r["Date"].replace("Z", "+00:00"))
            pcur, pval = parse_money(r["Price per share"])
            tcur, tval = parse_money(r["Total Amount"])
            qty = D(r["Quantity"]) if r["Quantity"].strip() else None
            fx = D(r["FX Rate"]) if r["FX Rate"].strip() else D(1)
            txns.append(Txn(
                dt=dt, d=dt.astimezone(ROME).date(), ticker=r["Ticker"].strip(),
                type=typ, qty=qty, price_cur=pcur, price=pval,
                total_cur=tcur, total=tval, currency=r["Currency"].strip(), fx=fx,
            ))
    txns.sort(key=lambda t: t.dt)
    return txns


# --------------------------------------------------------------------------------------
# P&L statement (two stacked sections)
# --------------------------------------------------------------------------------------
def parse_pnl(path: Path) -> tuple[list[Sell], list[Dividend]]:
    sells: list[Sell] = []
    divs: list[Dividend] = []
    mode: str | None = None
    header_seen = False
    with open(path) as f:
        for row in csv.reader(f):
            cells = [c.strip() for c in row]
            if not any(cells):
                mode, header_seen = None, False
                continue
            head = cells[0]
            if head == "Income from Sells":
                mode, header_seen = "sells", False
                continue
            if head.startswith("Other income"):
                mode, header_seen = "div", False
                continue
            if not header_seen:               # this row is the column header
                header_seen = True
                continue
            if mode == "sells":
                sells.append(Sell(
                    acquired=date.fromisoformat(cells[0]),
                    sold=date.fromisoformat(cells[1]),
                    symbol=cells[2], name=html.unescape(cells[3]), isin=cells[4],
                    country=cells[5], qty=D(cells[6]), cost_basis=parse_num(cells[7]),
                    gross_proceeds=parse_num(cells[8]), gross_pnl=parse_num(cells[9]),
                    currency=cells[10],
                ))
            elif mode == "div":
                divs.append(Dividend(
                    d=date.fromisoformat(cells[0]), symbol=cells[1],
                    name=html.unescape(cells[2]), isin=cells[3], country=cells[4],
                    gross_eur=parse_num(cells[5]), wh_eur=parse_num(cells[6]),
                    net_eur=parse_num(cells[7]), currency=cells[8],
                ))
    return sells, divs


# --------------------------------------------------------------------------------------
# Opening balances (prior-year carried positions & cash)
# --------------------------------------------------------------------------------------
def _truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "y", "si", "sì")


def parse_opening(input_dir: Path, config: dict) -> tuple[dict[str, list[OpeningPosition]], dict[str, Decimal]]:
    """Read opening positions/cash from input CSVs and/or the config `[opening]` block.
    Returns (positions_by_ticker, cash_by_currency)."""
    rows: list[dict] = list(config.get("opening_positions", []))
    pos_csv = input_dir / "opening_positions.csv"
    if pos_csv.exists():
        with open(pos_csv) as f:
            rows += list(csv.DictReader(f))

    positions: dict[str, list[OpeningPosition]] = {}
    for r in rows:
        op = OpeningPosition(
            ticker=str(r["ticker"]).strip(),
            qty=dec(r["qty"]),
            pmc_eur=dec(r["pmc_eur"]),
            open_date=date.fromisoformat(str(r["open_date"])),
            currency=str(r.get("currency", "EUR")).strip() or "EUR",
            is_fund=_truthy(r.get("is_fund", False)),
        )
        positions.setdefault(op.ticker, []).append(op)

    cash: dict[str, Decimal] = {k: dec(v) for k, v in config.get("opening_cash", {}).items()}
    cash_csv = input_dir / "opening_cash.csv"
    if cash_csv.exists():
        with open(cash_csv) as f:
            for r in csv.DictReader(f):
                cash[str(r["currency"]).strip()] = dec(r["balance"])
    return positions, cash


# --------------------------------------------------------------------------------------
# AdE foreign-state numeric codes
# --------------------------------------------------------------------------------------
def load_ade_codes(ref_dir: Path) -> dict[str, str]:
    """ISO alpha-2 -> AdE 3-digit country code, from data/ade_country_codes.csv."""
    mapping: dict[str, str] = {}
    with open(ref_dir / "ade_country_codes.csv") as f:
        for r in csv.DictReader(f):
            iso = (r.get("iso2") or "").strip().upper()
            code = (r.get("ade_code") or "").strip()
            if iso and code:
                mapping[iso] = code
    return mapping


def isin_country(isin: str | None, overrides: dict | None = None) -> str | None:
    if isin and overrides and isin in overrides:
        return str(overrides[isin]).upper()
    return isin[:2].upper() if isin and len(isin) >= 2 else None


def ade_code(iso2: str | None, mapping: dict[str, str], country_overrides: dict | None = None) -> str | None:
    iso2 = (iso2 or "").upper()
    if country_overrides and iso2 in country_overrides:
        return str(country_overrides[iso2])
    return mapping.get(iso2)


# --------------------------------------------------------------------------------------
# Instrument metadata / classification
# --------------------------------------------------------------------------------------
def _fund_from_name(name: str) -> bool:
    u = (name or "").upper()
    return "ETF" in u or "UCITS" in u


def build_meta(sells: list[Sell], divs: list[Dividend], overrides: dict,
               opening: dict[str, list[OpeningPosition]] | None = None) -> dict[str, Meta]:
    """Security metadata comes from the PnL statement (sold or dividend-paying tickers) and
    from opening positions. Buy-only tickers with no metadata are classified as stock (matches
    the reference — e.g. VWCE lands under 'Azioni' because it was never sold)."""
    meta: dict[str, Meta] = {}
    for s in sells:
        meta.setdefault(s.symbol, Meta(s.isin, s.name, isin_country(s.isin), _fund_from_name(s.name)))
    for dv in divs:
        meta.setdefault(dv.symbol, Meta(dv.isin, dv.name, isin_country(dv.isin), _fund_from_name(dv.name)))
    for tk, ops in (opening or {}).items():
        if tk not in meta:
            meta[tk] = Meta(is_fund=any(op.is_fund for op in ops))
    for tk, val in overrides.items():
        meta.setdefault(tk, Meta()).is_fund = bool(val)
    return meta


def is_fund(meta: dict[str, Meta], ticker: str) -> bool:
    m = meta.get(ticker)
    return bool(m and m.is_fund)
