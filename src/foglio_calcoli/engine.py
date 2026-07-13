"""Pipeline orchestration: ``compute(config) -> Result`` (parse → provision rates → quadri)."""
from __future__ import annotations

import logging
from datetime import date

from .common import fmt
from .parsing import parse_account, parse_pnl, parse_opening, build_meta, load_ade_codes, find
from .rates import ensure_rates
from .models import Ctx, Result
from .quadri import (build_rm_dividends, build_rm_funds, build_rt,
                     build_rw_instruments, build_rw_liquidity, build_extra_pmc)

log = logging.getLogger("foglio_calcoli")


def _currencies_present(txns, divs) -> set[str]:
    cur = set()
    for t in txns:
        cur.add(t.currency)
        cur.add(t.price_cur)
    for dv in divs:
        cur.add(dv.currency)
    cur.discard("EUR")
    cur.discard(None)
    cur.discard("")
    return cur


def compute(config: dict) -> Result:
    year = config["fiscal_year"]
    input_dir = config["input_dir"]
    warnings: list[str] = []

    log.info("Compute start: broker=%s fiscal_year=%s input=%s",
             config.get("broker_code"), year, input_dir)
    acc_path = find(input_dir, "trading-account-statement_*.csv")
    pnl_path = find(input_dir, "trading-pnl-statement_*.csv")
    txns = parse_account(acc_path)
    sells, divs = parse_pnl(pnl_path)
    opening_pos, opening_cash = parse_opening(input_dir, config)
    meta = build_meta(sells, divs, config["fund_overrides"], opening_pos)
    ade_map = load_ade_codes(config["ref_dir"])
    log.info("Parsed %d transactions, %d realized sells, %d dividends; opening positions=%d, "
             "opening cash=%s", len(txns), len(sells), len(divs), len(opening_pos),
             {k: str(v) for k, v in opening_cash.items()} or "none")

    currencies = _currencies_present(txns, divs)
    years = {year} | {t.d.year for t in txns}
    log.info("Currencies present: %s; ensuring BdI rates for years %s (allow_fetch=%s)",
             sorted(currencies) or "EUR only", sorted(years), config["allow_fetch"])
    rates = ensure_rates(config["ref_dir"], years, currencies, config["allow_fetch"])

    first = min((t.d for t in txns), default=None)
    if first and first > date(year, 1, 1) and not opening_pos and not opening_cash:
        warnings.append(f"First transaction is {first} (after 01/01/{year}) and no opening balances "
                        f"were provided. If this account held positions/cash before 01/01/{year}, add "
                        f"opening_positions.csv / opening_cash.csv (or a [opening] config block).")
    for w in warnings:
        log.warning(w)

    ctx = Ctx(txns=txns, sells=sells, divs=divs, meta=meta, rates=rates, ade_map=ade_map,
              isin_ovr=config["isin_country_overrides"], country_ovr=config["country_ade_overrides"],
              opening=opening_pos, opening_cash=opening_cash, share=config["holders"][0]["share"],
              year=year, minus_carry=config["minus_carryforward"], warnings=warnings)

    rm_div = build_rm_dividends(ctx)
    rm_fund = build_rm_funds(ctx)
    rt = build_rt(ctx, rm_fund.losses)

    rm_tickers = {dv.symbol for dv in divs if not (dv.isin or "").upper().startswith("IT")}
    rm_tickers |= {r["Ticker"] for g in rm_fund.groups.values() for r in g.rows}
    rt_tickers = {r["Ticker"] for r in rt.rows}

    rw_instr = build_rw_instruments(ctx, rm_tickers, rt_tickers)
    rw_liq = build_rw_liquidity(ctx)
    extra = build_extra_pmc(ctx)

    log.info("RM/M dividendi: %s", {f"H-{c}": fmt(g.total) for c, g in rm_div.groups.items()} or "none")
    log.info("RM/M fondi: %s", {f"B-{c}": fmt(g.total) for c, g in rm_fund.groups.items()} or "none")
    log.info("RT/T: corrispettivi=%s costi=%s plus=%s minus=%s",
             fmt(rt.corrispettivi), fmt(rt.costi), fmt(rt.plus), fmt(rt.minus))
    for c in rw_instr.categories:
        log.info("RW strumenti %s: VF=%s giorni=%s IVAFE=%s", c.tipo, fmt(c.vf), fmt(c.giorni), c.ivafe)
    for cur, liq in rw_liq.currencies.items():
        log.info("RW liquidità %s: VF=%s giorni=%s IVAFE=0", cur, fmt(liq.vf), fmt(liq.giorni))
    log.info("Compute done (%d warning(s)).", len(warnings))

    return Result(config=config, warnings=warnings, txns=txns, sells=sells, divs=divs, meta=meta,
                  opening_positions=opening_pos, opening_cash=opening_cash, rates=rates,
                  rm_dividends=rm_div, rm_funds=rm_fund, rt=rt,
                  rw_instruments=rw_instr, rw_liquidity=rw_liq, extra=extra)
