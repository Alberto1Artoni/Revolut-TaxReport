"""Quadro builders: RM/M (dividendi H, fondi B), RT/T (plusvalenze), RW/W (strumenti + liquidità),
Extra (PMC). Each takes the shared ``Ctx`` and returns a typed result (see ``models``); all
monetary values are Decimal — only the report layer truncates for display."""
from __future__ import annotations

from datetime import date

from .common import D, IVAFE_RATE, SOSTITUTIVA, euro, doy
from .parsing import is_fund, ade_code, isin_country
from .lots import build_segments, pmc_at_sells, pmc_history
from .models import (Ctx, RmGroup, RmDividends, RmFunds, RtResult,
                     RwCategory, RwInstruments, LiqCurrency, RwLiquidity)

UNKNOWN_CODE = "999"


# --------------------------------------------------------------------------------------
# Quadro RM/M — dividendi (codice H)
# --------------------------------------------------------------------------------------
def build_rm_dividends(ctx: Ctx) -> RmDividends:
    div_fx = {(t.d, t.ticker): (t.fx, t.currency) for t in ctx.txns if t.type == "DIVIDEND"}
    groups: dict[str, RmGroup] = {}
    for dv in ctx.divs:
        if (dv.isin or "").upper().startswith("IT"):
            continue                                       # Italian source excluded
        code = ade_code(isin_country(dv.isin, ctx.isin_ovr), ctx.ade_map, ctx.country_ovr) or UNKNOWN_CODE
        if code == UNKNOWN_CODE:
            ctx.warnings.append(f"Dividend {dv.symbol} {dv.d}: no AdE code for ISIN {dv.isin} -> {UNKNOWN_CODE}")
        if (dv.d, dv.symbol) in div_fx:
            fx, cur = div_fx[(dv.d, dv.symbol)]
        else:
            fx, cur = D(1), dv.currency or "EUR"
            if cur != "EUR":
                ctx.warnings.append(f"Dividend {dv.symbol} {dv.d}: no matching ledger DIVIDEND row; "
                                    f"cannot reconstruct FX (used 1).")
        gross_orig = dv.gross_eur * fx
        cambio = ctx.rates.cambio_eur(cur, dv.d)
        importo = gross_orig * cambio
        g = groups.get(code)
        if g is None:
            g = groups[code] = RmGroup("H", code, SOSTITUTIVA, [], D(0))
        g.rows.append({"Data": dv.d, "Ticker": dv.symbol, "ISIN": dv.isin, "Valuta": cur,
                       "Importo Valuta": gross_orig, "Cambio EUR": cambio, "Importo EUR": importo})
        g.total += importo
    return RmDividends(groups)


# --------------------------------------------------------------------------------------
# Quadro RM/M — fondi UCITS, plusvalenze (codice B); losses routed to RT/T
# --------------------------------------------------------------------------------------
def build_rm_funds(ctx: Ctx) -> RmFunds:
    groups: dict[str, RmGroup] = {}
    losses: list[dict] = []
    fund_tickers = sorted({t.ticker for t in ctx.txns if t.is_sell and is_fund(ctx.meta, t.ticker)})
    for tk in fund_tickers:
        code = ade_code(ctx.meta[tk].country, ctx.ade_map, ctx.country_ovr) or UNKNOWN_CODE
        if code == UNKNOWN_CODE:
            ctx.warnings.append(f"Fund {tk}: no AdE code for country {ctx.meta[tk].country} -> {UNKNOWN_CODE}")
        for s in pmc_at_sells(ctx.txns, tk, ctx.rates, ctx.opening):
            cambio = ctx.rates.cambio_eur(s["cur"], s["date"])
            close_eur = s["price"] * cambio
            importo = (close_eur - s["pmc_eur"]) * s["qty"]     # leva = 1
            if importo > 0:
                g = groups.get(code)
                if g is None:
                    g = groups[code] = RmGroup("B", code, SOSTITUTIVA, [], D(0))
                g.rows.append({"Data chiusura": s["date"], "Tipo": "ETF", "Ticker": tk,
                               "Valuta": s["cur"], "Leva": 1, "Quantità": s["qty"],
                               "PMC EUR": s["pmc_eur"], "Prezzo chiusura": s["price"],
                               "Cambio EUR": cambio, "Importo EUR": importo})
                g.total += importo
            else:
                losses.append({"ticker": tk, "date": s["date"], "qty": s["qty"], "cur": s["cur"],
                               "close_eur": close_eur, "pmc_eur": s["pmc_eur"]})
    return RmFunds(groups, losses)


# --------------------------------------------------------------------------------------
# Quadro RT/T — plusvalenze (azioni LIFO + fondi in minusvalenza via PMC)
# --------------------------------------------------------------------------------------
def build_rt(ctx: Ctx, fund_losses: list[dict]) -> RtResult:
    stock_tickers = sorted({t.ticker for t in ctx.txns if t.is_sell and not is_fund(ctx.meta, t.ticker)})
    rows = []
    for tk in stock_tickers:
        for seg in build_segments(ctx.txns, tk, ctx.year, ctx.opening):
            if seg.is_open:
                continue
            camb_ch = ctx.rates.cambio_eur(seg.close_currency, seg.close_date)
            camb_ap = ctx.rates.cambio_eur(seg.open_currency, seg.open_date)   # EUR carried -> 1
            ricavi = seg.qty * seg.close_price * camb_ch
            costi = seg.qty * seg.open_price * camb_ap
            rows.append({"Ticker": tk, "Valuta": seg.close_currency, "Leva": 1, "Direzione": "LONG",
                         "Quantità": seg.qty, "Data Ch.": seg.close_date, "Cambio Ch.": camb_ch,
                         "Prezzo Ch.": seg.close_price, "Comm. Ch.": D(0), "Data Ap.": seg.open_date,
                         "Cambio Ap.": camb_ap, "Prezzo Ap.": seg.open_price, "Comm. Ap.": D(0),
                         "Ricavi": ricavi, "Costi": costi})
    for loss in fund_losses:
        rows.append({"Ticker": loss["ticker"], "Valuta": loss["cur"], "Leva": 1, "Direzione": "LONG",
                     "Quantità": loss["qty"], "Data Ch.": loss["date"], "Cambio Ch.": None,
                     "Prezzo Ch.": None, "Comm. Ch.": D(0), "Data Ap.": None, "Cambio Ap.": None,
                     "Prezzo Ap.": None, "Comm. Ap.": D(0),
                     "Ricavi": loss["close_eur"] * loss["qty"], "Costi": loss["pmc_eur"] * loss["qty"]})
    rows.sort(key=lambda r: (r["Ticker"], r["Data Ch."]))
    tot_ric = sum((r["Ricavi"] for r in rows), D(0))
    tot_cost = sum((r["Costi"] for r in rows), D(0))
    diff = tot_ric - tot_cost
    plus = diff if diff > 0 else D(0)
    minus = -diff if diff < 0 else D(0)
    used = min(plus, ctx.minus_carry)
    return RtResult(rows, tot_ric, tot_cost, plus, minus, used, plus - used)


# --------------------------------------------------------------------------------------
# Quadro RW/W — strumenti finanziari (IVAFE 0,2%)
# --------------------------------------------------------------------------------------
def _rw_code(cat_tickers: set[str], rm_tickers: set[str], rt_tickers: set[str]) -> str:
    rm, rt = bool(cat_tickers & rm_tickers), bool(cat_tickers & rt_tickers)
    if rm and rt:
        return "4 - Almeno 2 quadri"
    if rm:
        return "2 - RM"
    if rt:
        return "3 - RT"
    return "5 - Nessun quadro compilato"


def build_rw_instruments(ctx: Ctx, rm_tickers: set[str], rt_tickers: set[str]) -> RwInstruments:
    year = ctx.year
    jan1 = date(year, 1, 1)
    buy_tickers = sorted({t.ticker for t in ctx.txns if t.is_buy} | set((ctx.opening or {}).keys()))
    per_ticker: dict[str, dict] = {}
    seg_rows: dict[str, list[dict]] = {}
    for tk in buy_tickers:
        vi = vf = vivafe = D(0)
        rows = []
        for seg in build_segments(ctx.txns, tk, year, ctx.opening):
            if seg.prior_year:                             # value as-of 01/01, giorni from 01/01
                camb_ap = ctx.rates.cambio_eur_monthly(seg.open_currency, year, 1)
                open_ref = jan1
            else:
                camb_ap = ctx.rates.cambio_eur_monthly(seg.open_currency, seg.open_date.year, seg.open_date.month)
                open_ref = seg.open_date
            valore_iniziale = seg.open_price * seg.qty * camb_ap
            if seg.is_open:
                camb_ch, valore_finale = camb_ap, valore_iniziale     # cost basis at 31/12
            else:
                camb_ch = ctx.rates.cambio_eur_monthly(seg.close_currency, seg.close_date.year, seg.close_date.month)
                valore_finale = seg.close_price * seg.qty * camb_ch
            giorni = (seg.close_date - open_ref).days + 1
            v_ivafe = valore_finale * giorni
            vi += valore_iniziale
            vf += valore_finale
            vivafe += v_ivafe
            rows.append({"Ticker": tk, "Valuta": seg.close_currency, "Leva": 1, "Quantità": seg.qty,
                         "Data Ap.": seg.open_date, "Data Ch.": seg.close_date, "Giorni Ivafe": giorni,
                         "Cambio Ap.": camb_ap, "Valore Iniziale": valore_iniziale,
                         "Cambio Ch.": camb_ch, "Valore Finale": valore_finale, "Valore Ivafe": v_ivafe})
        per_ticker[tk] = {"Valore Iniziale": vi, "Valore Finale": vf, "Valore Ivafe": vivafe,
                          "is_fund": is_fund(ctx.meta, tk)}
        seg_rows[tk] = rows

    accum: dict[str, dict] = {}
    for tk, d in per_ticker.items():
        cat = "ETF" if d["is_fund"] else "Azioni"
        c = accum.setdefault(cat, {"tickers": set(), "VI": D(0), "VF": D(0), "VIvafe": D(0)})
        c["tickers"].add(tk)
        c["VI"] += d["Valore Iniziale"]
        c["VF"] += d["Valore Finale"]
        c["VIvafe"] += d["Valore Ivafe"]

    categories = []
    for cat in sorted(accum):
        c = accum[cat]
        giorni_tot = c["VIvafe"] / c["VF"] if c["VF"] else D(0)
        ivafe = euro(c["VF"] * IVAFE_RATE * giorni_tot / D(365) * ctx.share)
        categories.append(RwCategory(cat, _rw_code(c["tickers"], rm_tickers, rt_tickers),
                                     c["VI"], c["VF"], c["VIvafe"], giorni_tot, ivafe))
    return RwInstruments(per_ticker, seg_rows, categories)


# --------------------------------------------------------------------------------------
# Quadro RW/W — liquidità (IVAFE, per valuta; deposito infruttifero -> IVAFE 0)
# --------------------------------------------------------------------------------------
def build_rw_liquidity(ctx: Ctx) -> RwLiquidity:
    year = ctx.year
    net_eur_by = {(dv.d, dv.symbol): dv.net_eur for dv in ctx.divs}
    events: dict[str, dict[date, dict]] = {}

    def ev(cur, d):
        return events.setdefault(cur, {}).setdefault(d, {"trade": D(0), "mov": D(0)})

    for t in ctx.txns:
        cur = t.currency
        if t.is_buy:
            ev(cur, t.d)["trade"] -= t.qty * t.price          # recompute (not Total Amount)
        elif t.is_sell:
            ev(cur, t.d)["trade"] += t.qty * t.price
        elif t.type == "CASH TOP-UP":
            ev(cur, t.d)["mov"] += t.total
        elif t.type == "CASH WITHDRAWAL":
            ev(cur, t.d)["mov"] += t.total                    # already negative
        elif t.type == "DIVIDEND":
            net_eur = net_eur_by.get((t.d, t.ticker))
            net_native = (net_eur * t.fx) if net_eur is not None else t.total
            ev(cur, t.d)["mov"] += net_native

    out: dict[str, LiqCurrency] = {}
    for cur in sorted(set(events) | set(ctx.opening_cash or {})):
        day_map = events.get(cur, {})
        boundaries = sorted(set(day_map) | {date(year, 1, 1)})
        bal = D(ctx.opening_cash.get(cur, D(0))) if ctx.opening_cash else D(0)
        periods = []
        for i, b in enumerate(boundaries):
            if b in day_map:
                bal += day_map[b]["trade"] + day_map[b]["mov"]
            end = boundaries[i + 1] if i + 1 < len(boundaries) else date(year + 1, 1, 1)
            periods.append({"start": b, "end": end, "bal": bal,
                            "trade": day_map.get(b, {}).get("trade", D(0)),
                            "mov": day_map.get(b, {}).get("mov", D(0))})
        rows = []
        VI = VF = VIvafe = D(0)
        for idx, p in enumerate(periods, 1):
            c = p["start"]
            subs = []
            while c < p["end"]:
                nm = date(c.year + 1, 1, 1) if c.month == 12 else date(c.year, c.month + 1, 1)
                seg_end = min(nm, p["end"])
                days = doy(seg_end, year) - doy(c, year)
                cambio = ctx.rates.cambio_eur_monthly(cur, c.year, c.month)
                converted = p["bal"] * cambio
                subs.append({"days": days, "tassabile": converted if converted > 0 else D(0)})
                c = seg_end
            giorni = sum(s["days"] for s in subs)
            vi_p, vf_p = subs[0]["tassabile"], subs[-1]["tassabile"]
            vivafe_p = vf_p * giorni                           # IVAFE weights by final value × days
            VI += vi_p
            VF += vf_p
            VIvafe += vivafe_p
            rows.append({"Periodo": idx, "Data": p["start"], "Saldo Reale": p["bal"],
                         "Valore Iniziale": vi_p, "Valore Finale": vf_p, "Giorni": giorni,
                         "Valore Ivafe": vivafe_p, "Flussi Trade": p["trade"], "Flussi Movimenti": p["mov"]})
        giorni_tot = VIvafe / VF if VF else D(0)
        out[cur] = LiqCurrency(cur, rows, VI, VF, VIvafe, giorni_tot)
    return RwLiquidity(out)


# --------------------------------------------------------------------------------------
# Extra — storico PMC dei fondi
# --------------------------------------------------------------------------------------
def build_extra_pmc(ctx: Ctx) -> dict:
    fund_tickers = sorted({t.ticker for t in ctx.txns if t.is_buy and is_fund(ctx.meta, t.ticker)}
                          | {tk for tk, ops in (ctx.opening or {}).items() if any(o.is_fund for o in ops)})
    tables = {}
    for tk in fund_tickers:
        rows, final_pmc = pmc_history(ctx.txns, tk, ctx.rates, ctx.opening)
        tables[tk] = {"rows": rows, "final_pmc": final_pmc}
    return {"funds": tables}
