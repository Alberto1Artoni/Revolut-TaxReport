"""Text report (render) and summary-table writers (CSV + report.txt). The named-metrics map
lives in ``models.metrics`` — this module only presents a computed ``Result``."""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from .common import D, fmt
from .models import Result, metrics


# --------------------------------------------------------------------------------------
# Text report
# --------------------------------------------------------------------------------------
def _d(x) -> str:
    return x.strftime("%d/%m/%Y") if isinstance(x, date) else fmt(x)


def _table(rows: list[dict], cols: list[str]) -> str:
    if not rows:
        return "  (nessuna riga)\n"
    data = [[_d(r.get(c)) for c in cols] for r in rows]
    widths = [max(len(cols[i]), *(len(row[i]) for row in data)) for i in range(len(cols))]
    line = lambda cells: "  " + " | ".join(c.rjust(widths[i]) for i, c in enumerate(cells))
    out = [line(cols), "  " + "-+-".join("-" * w for w in widths)]
    out += [line(r) for r in data]
    return "\n".join(out) + "\n"


def render(res: Result) -> str:
    cfg = res.config
    o: list[str] = ["=" * 90,
                    f"  FOGLIO CALCOLI — {cfg['broker_code']} ({cfg['broker_country']}) — "
                    f"anno fiscale {cfg['fiscal_year']}",
                    f"  Intestatario: {cfg['holders'][0]['name']} "
                    f"({fmt(cfg['holders'][0]['share'] * 100)}%)  —  codice paese broker "
                    f"{cfg['broker_country_code']}", "=" * 90]

    if res.warnings:
        o.append("\n### AVVISI")
        o += [f"  ! {w}" for w in res.warnings]

    o.append("\n### QUADRO RM/M — Redditi di capitale (imposta sostitutiva 26%)\n")
    o.append("-- Dividendi esteri (codice H) --")
    o.append(_table(res.rm_dividends.summary, ["Tipo", "Codice Stato estero", "Ammontare reddito"]))
    for code, g in sorted(res.rm_dividends.groups.items()):
        o.append(f"  H-{code}-26%  (totale {fmt(g.total)})")
        o.append(_table(g.rows, ["Data", "Ticker", "ISIN", "Valuta",
                                 "Importo Valuta", "Cambio EUR", "Importo EUR"]))
    o.append("-- Fondi UCITS — plusvalenze (codice B) --")
    o.append(_table(res.rm_funds.summary, ["Tipo", "Codice Stato estero", "Ammontare reddito"]))
    for code, g in sorted(res.rm_funds.groups.items()):
        o.append(f"  B-{code}-26%  (totale {fmt(g.total)})")
        o.append(_table(g.rows, ["Data chiusura", "Tipo", "Ticker", "Valuta", "Leva",
                                 "Quantità", "PMC EUR", "Prezzo chiusura", "Cambio EUR", "Importo EUR"]))

    rt = res.rt
    o.append("\n### QUADRO RT/T — Plusvalenze (redditi diversi)\n")
    o.append(f"  Totale corrispettivi: {fmt(rt.corrispettivi)}")
    o.append(f"  Totale costi:         {fmt(rt.costi)}")
    o.append(f"  Plusvalenza:          {fmt(rt.plus)}")
    o.append(f"  Minusvalenza:         {fmt(rt.minus)}")
    o.append(f"  Plusvalenza netta imponibile: {fmt(rt.net_imponibile)}\n")
    o.append(_table(rt.rows, ["Ticker", "Valuta", "Quantità", "Data Ch.", "Cambio Ch.",
                              "Prezzo Ch.", "Data Ap.", "Cambio Ap.", "Prezzo Ap.", "Ricavi", "Costi"]))

    rw = res.rw_instruments
    o.append("\n### QUADRO RW/W — Strumenti finanziari (IVAFE 0,2%)\n")
    o.append(_table(rw.summary, ["Tipo", "Codice", "Valore Iniziale", "Valore Finale", "Giorni Ivafe", "IVAFE"]))
    for cat in ("Azioni", "ETF"):
        tickers = sorted(t for t, d in rw.per_ticker.items()
                         if ("ETF" if d["is_fund"] else "Azioni") == cat)
        if not tickers:
            continue
        o.append(f"  -- {cat} — riepilogo per ticker --")
        rows = [{"Ticker": t, **{k: rw.per_ticker[t][k]
                 for k in ("Valore Iniziale", "Valore Finale", "Valore Ivafe")}} for t in tickers]
        rows.append({"Ticker": "TOTALE",
                     "Valore Iniziale": sum((r["Valore Iniziale"] for r in rows), D(0)),
                     "Valore Finale": sum((r["Valore Finale"] for r in rows), D(0)),
                     "Valore Ivafe": sum((r["Valore Ivafe"] for r in rows), D(0))})
        o.append(_table(rows, ["Ticker", "Valore Iniziale", "Valore Finale", "Valore Ivafe"]))

    o.append("\n### QUADRO RW/W — Liquidità (deposito infruttifero → solo monitoraggio)\n")
    o.append(_table(res.rw_liquidity.summary,
                    ["Tipo", "Codice", "Valore Iniziale", "Valore Finale", "Giorni Ivafe", "IVAFE"]))

    o.append("\n### EXTRA — Prezzo Medio di Carico (PMC) fondi\n")
    for tk, t in res.extra["funds"].items():
        o.append(f"  {tk}  (PMC finale {fmt(t['final_pmc'])} EUR)")
        o.append(_table(t["rows"], ["Data", "Valuta", "Quantità precedente", "PMC EUR precedente",
                                    "Quantità di acquisto", "Prezzo di acquisto", "Cambio EUR",
                                    "Quantità attuale", "PMC EUR attuale"]))
    return "\n".join(o)


# --------------------------------------------------------------------------------------
# Summary tables -> output/ (CSV + the full text report)
# --------------------------------------------------------------------------------------
def _write_csv(path: Path, rows: list[dict], cols: list[str]) -> bool:
    if not rows:
        return False
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([_d(r.get(c)) for c in cols])
    return True


def write_summaries(res: Result, out_dir) -> list[Path]:
    """Write the summary tables (CSV) and the full text report into ``out_dir``.
    Returns the list of files written."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def wr(name, rows, cols):
        p = out_dir / name
        if _write_csv(p, rows, cols):
            written.append(p)

    rw_cols = ["Tipo", "Codice", "Valore Iniziale", "Valore Finale", "Giorni Ivafe", "IVAFE"]
    wr("summary_rm_dividendi.csv", res.rm_dividends.summary,
       ["Tipo", "Codice Stato estero", "Ammontare reddito"])
    wr("summary_rm_fondi.csv", res.rm_funds.summary,
       ["Tipo", "Codice Stato estero", "Ammontare reddito"])
    rt = res.rt.summary
    wr("summary_rt.csv", [rt], list(rt.keys()))
    wr("summary_rw_strumenti.csv", res.rw_instruments.summary, rw_cols)
    wr("summary_rw_liquidita.csv", res.rw_liquidity.summary, rw_cols)
    wr("metrics.csv", [{"Voce": k, "Valore": v} for k, v in metrics(res).items()], ["Voce", "Valore"])

    report_path = out_dir / "report.txt"
    report_path.write_text(render(res) + "\n", encoding="utf-8")
    written.append(report_path)
    return written
