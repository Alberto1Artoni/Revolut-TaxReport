"""LIFO holding-segment engine + PMC (weighted-average cost). Shared by RT/T and RW/W.

Opening (carried) lots are seeded first; their cost basis is already in EUR (`pmc_eur`), so a
segment can have a EUR open side and a native close side. `prior_year` marks lots opened before
the fiscal year (valued as-of 01/01 in RW)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .common import D
from .parsing import Txn, OpeningPosition
from .rates import RateProvider


@dataclass
class Segment:
    ticker: str
    qty: Decimal
    open_date: date
    open_price: Decimal
    open_currency: str
    close_date: date | None
    close_price: Decimal | None
    close_currency: str | None
    is_open: bool
    prior_year: bool = False


def _seed_lots(opening: dict[str, list[OpeningPosition]] | None, ticker: str) -> list[dict]:
    lots = []
    for op in (opening or {}).get(ticker, []):
        # carried lot: cost basis is already EUR -> open side is EUR-denominated
        lots.append({"qty": op.qty, "date": op.open_date, "price": op.pmc_eur,
                     "cur": "EUR", "prior": True})
    return lots


def build_segments(txns: list[Txn], ticker: str, year: int,
                   opening: dict[str, list[OpeningPosition]] | None = None) -> list[Segment]:
    year_end = date(year, 12, 31)
    lots = _seed_lots(opening, ticker)
    segs: list[Segment] = []
    for t in [x for x in txns if x.ticker == ticker and (x.is_buy or x.is_sell)]:
        if t.is_buy:
            lots.append({"qty": t.qty, "date": t.d, "price": t.price, "cur": t.price_cur,
                         "prior": t.d.year < year})
        else:                                             # SELL — LIFO
            remaining = t.qty
            while remaining > 0:
                if not lots:
                    raise ValueError(
                        f"{ticker}: SELL on {t.d} exceeds held quantity (LIFO underflow). "
                        f"If this position was opened before {year}, add it to opening_positions.")
                lot = lots[-1]
                take = min(remaining, lot["qty"])
                segs.append(Segment(ticker, take, lot["date"], lot["price"], lot["cur"],
                                    t.d, t.price, t.price_cur, is_open=False, prior_year=lot["prior"]))
                lot["qty"] -= take
                remaining -= take
                if lot["qty"] == 0:
                    lots.pop()
    for lot in lots:                                      # still open at year end -> cost basis
        segs.append(Segment(ticker, lot["qty"], lot["date"], lot["price"], lot["cur"],
                            year_end, lot["price"], lot["cur"], is_open=True, prior_year=lot["prior"]))
    return segs


def _pmc_seed(opening: dict[str, list[OpeningPosition]] | None, ticker: str) -> tuple[Decimal, Decimal, list[dict]]:
    qty, pmc = D(0), D(0)
    rows = []
    for op in (opening or {}).get(ticker, []):
        new_qty = qty + op.qty
        pmc = (qty * pmc + op.qty * op.pmc_eur) / new_qty
        rows.append({"Data": op.open_date, "Leva": 1, "Valuta": "EUR",
                     "Quantità precedente": qty, "PMC EUR precedente": pmc if qty else D(0),
                     "Quantità di acquisto": op.qty, "Prezzo di acquisto": op.pmc_eur,
                     "Cambio EUR": D(1), "Quantità attuale": new_qty, "PMC EUR attuale": pmc,
                     "carried": True})
        qty = new_qty
    return qty, pmc, rows


def pmc_history(txns: list[Txn], ticker: str, rates: RateProvider,
                opening: dict[str, list[OpeningPosition]] | None = None) -> tuple[list[dict], Decimal]:
    qty, pmc, rows = _pmc_seed(opening, ticker)
    for t in [x for x in txns if x.ticker == ticker and x.is_buy]:
        cambio = rates.cambio_eur(t.price_cur, t.d)
        price_eur = t.price * cambio
        new_qty = qty + t.qty
        new_pmc = (qty * pmc + t.qty * price_eur) / new_qty
        rows.append({"Data": t.d, "Leva": 1, "Valuta": t.price_cur,
                     "Quantità precedente": qty, "PMC EUR precedente": pmc,
                     "Quantità di acquisto": t.qty, "Prezzo di acquisto": t.price,
                     "Cambio EUR": cambio, "Quantità attuale": new_qty, "PMC EUR attuale": new_pmc})
        qty, pmc = new_qty, new_pmc
    return rows, pmc


def pmc_at_sells(txns: list[Txn], ticker: str, rates: RateProvider,
                 opening: dict[str, list[OpeningPosition]] | None = None) -> list[dict]:
    """For each SELL emit {date, qty, price, cur, pmc_eur} using the current PMC."""
    qty, pmc, _ = _pmc_seed(opening, ticker)
    out = []
    for t in [x for x in txns if x.ticker == ticker and (x.is_buy or x.is_sell)]:
        if t.is_buy:
            price_eur = t.price * rates.cambio_eur(t.price_cur, t.d)
            new_qty = qty + t.qty
            pmc = (qty * pmc + t.qty * price_eur) / new_qty
            qty = new_qty
        else:
            out.append({"date": t.d, "qty": t.qty, "price": t.price, "cur": t.price_cur,
                        "pmc_eur": pmc})
            qty -= t.qty
    return out
