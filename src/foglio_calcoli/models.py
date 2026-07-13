"""Pipeline data model: the input context (``Ctx``), the typed per-quadro results and the
top-level ``Result``, plus ``metrics()`` (the named scalar values derived from a ``Result``).

Each result exposes a ``.summary`` projection (the display/AdE-facing table for that quadro) so
``report.py``, the CSV writers and the notebook all share one definition — the typed fields
(``total``, ``vf``, ``giorni`` …) are the source of truth; only the report layer truncates for
display. ``metrics()`` lives here, next to ``Result``, so ``validate.py`` needn't depend on the
reporting layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .common import euro
from .parsing import Txn, Sell, Dividend, Meta, OpeningPosition
from .rates import RateProvider

LIQ_CODE = "5 - Nessun quadro compilato"          # liquidità: deposito infruttifero, IVAFE 0


# --------------------------------------------------------------------------------------
# Input context — the invariant inputs every quadro builder shares (assembled once)
# --------------------------------------------------------------------------------------
@dataclass
class Ctx:
    txns: list[Txn]
    sells: list[Sell]
    divs: list[Dividend]
    meta: dict[str, Meta]
    rates: RateProvider
    ade_map: dict[str, str]
    isin_ovr: dict
    country_ovr: dict
    opening: dict[str, list[OpeningPosition]]
    opening_cash: dict[str, Decimal]
    share: Decimal
    year: int
    minus_carry: Decimal
    warnings: list[str]


# --------------------------------------------------------------------------------------
# Per-quadro results
# --------------------------------------------------------------------------------------
@dataclass
class RmGroup:
    """One RM/M group (a foreign-state code): its rows and running total."""
    tipo: str                       # "H" (dividendi) or "B" (fondi)
    codice: str                     # AdE foreign-state code
    aliquota: Decimal
    rows: list[dict]
    total: Decimal


@dataclass
class RmDividends:
    groups: dict[str, RmGroup]

    @property
    def summary(self) -> list[dict]:
        return [{"Tipo": "H", "Codice Stato estero": c, "Ammontare reddito": euro(g.total)}
                for c, g in sorted(self.groups.items())]


@dataclass
class RmFunds:
    groups: dict[str, RmGroup]
    losses: list[dict]              # fund losses routed to RT/T

    @property
    def summary(self) -> list[dict]:
        return [{"Tipo": "B", "Codice Stato estero": c, "Ammontare reddito": euro(g.total)}
                for c, g in sorted(self.groups.items())]


@dataclass
class RtResult:
    rows: list[dict]
    corrispettivi: Decimal
    costi: Decimal
    plus: Decimal
    minus: Decimal
    minus_used: Decimal
    net_imponibile: Decimal

    @property
    def summary(self) -> dict:
        return {"Totale corrispettivi": self.corrispettivi, "Totale costi": self.costi,
                "Plusvalenza": self.plus, "Minusvalenza": self.minus,
                "Minus. pregresse usate": self.minus_used,
                "Plusvalenza netta imponibile": self.net_imponibile}


@dataclass
class RwCategory:
    """RW/W instruments, one category (Azioni / ETF)."""
    tipo: str
    codice: str
    vi: Decimal
    vf: Decimal
    vivafe: Decimal
    giorni: Decimal
    ivafe: int


@dataclass
class RwInstruments:
    per_ticker: dict[str, dict]
    seg_rows: dict[str, list[dict]]
    categories: list[RwCategory]

    @property
    def summary(self) -> list[dict]:
        return [{"Tipo": c.tipo, "Codice": c.codice, "Valore Iniziale": c.vi,
                 "Valore Finale": c.vf, "Giorni Ivafe": c.giorni, "IVAFE": c.ivafe}
                for c in self.categories]


@dataclass
class LiqCurrency:
    """RW/W liquidity, one currency."""
    tipo: str                       # the currency code
    rows: list[dict]
    vi: Decimal
    vf: Decimal
    vivafe: Decimal
    giorni: Decimal


@dataclass
class RwLiquidity:
    currencies: dict[str, LiqCurrency]

    @property
    def summary(self) -> list[dict]:
        return [{"Tipo": liq.tipo, "Codice": LIQ_CODE, "Valore Iniziale": liq.vi,
                 "Valore Finale": liq.vf, "Giorni Ivafe": liq.giorni, "IVAFE": 0}
                for liq in self.currencies.values()]


@dataclass
class Result:
    config: dict
    warnings: list[str]
    txns: list[Txn]
    sells: list[Sell]
    divs: list[Dividend]
    meta: dict[str, Meta]
    opening_positions: dict[str, list[OpeningPosition]]
    opening_cash: dict[str, Decimal]
    rates: RateProvider
    rm_dividends: RmDividends
    rm_funds: RmFunds
    rt: RtResult
    rw_instruments: RwInstruments
    rw_liquidity: RwLiquidity
    extra: dict                     # {"funds": {ticker: {"rows": [...], "final_pmc": Decimal}}}


# --------------------------------------------------------------------------------------
# metrics() — stable named scalar values (source of truth for validation & --format json)
# --------------------------------------------------------------------------------------
def metrics(res: Result) -> dict[str, object]:
    m: dict[str, object] = {}
    for code, g in res.rm_dividends.groups.items():
        m[f"RM/M H-{code}"] = g.total
    for code, g in res.rm_funds.groups.items():
        m[f"RM/M B-{code}"] = g.total
    rt = res.rt
    m["RT corrispettivi"] = rt.corrispettivi
    m["RT costi"] = rt.costi
    m["RT plus"] = rt.plus
    m["RT minus"] = rt.minus
    for c in res.rw_instruments.categories:
        m[f"RW {c.tipo} VI"] = c.vi
        m[f"RW {c.tipo} VF"] = c.vf
        m[f"RW {c.tipo} VIvafe"] = c.vivafe
        m[f"RW {c.tipo} giorni"] = c.giorni
        m[f"RW {c.tipo} IVAFE"] = c.ivafe
    for cur, liq in res.rw_liquidity.currencies.items():
        m[f"RW Liq {cur} VI"] = liq.vi
        m[f"RW Liq {cur} VF"] = liq.vf
        m[f"RW Liq {cur} VIvafe"] = liq.vivafe
        m[f"RW Liq {cur} giorni"] = liq.giorni
    return m
