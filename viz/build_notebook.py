"""Generate viz/Foglio_Calcoli.ipynb from the foglio_calcoli library.

    python viz/build_notebook.py                              # default: cases/anonymous_2025
    python viz/build_notebook.py cases/synthetic_carryover/config.toml   # any case's config.toml

The chosen case is baked into the notebook, so the generated .ipynb runs standalone."""
import sys
from pathlib import Path

import nbformat as nbf
from nbformat.v4 import new_notebook, new_markdown_cell, new_code_cell

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                                    # repo root (contains src/, cases/, data/)

_arg = sys.argv[1] if len(sys.argv) > 1 else "cases/anonymous_2025/config.toml"
_case = Path(_arg)
if not _case.is_absolute():
    _case = ROOT / _case
if not _case.is_file():
    sys.exit(f"case config not found: {_case}")
try:                                                  # portable: notebook does `root / CASE_REL`
    CASE_LINE = 'CASE = root / "%s"' % _case.resolve().relative_to(ROOT).as_posix()
except ValueError:                                    # case lives outside the repo
    CASE_LINE = 'CASE = Path(r"%s")' % _case.resolve()
CASE_NAME = _case.resolve().parent.name

cells = []


def md(t):
    cells.append(new_markdown_cell(t))


def code(t):
    cells.append(new_code_cell(t.strip("\n")))


md("""# Foglio Calcoli — Revolut → Dichiarazione dei Redditi

Questo notebook calcola, a partire dall'export **Revolut**, i valori del *Foglio Calcoli* per la
dichiarazione dei redditi italiana sui conti esteri, e — nell'ultima sezione — **dice esattamente
dove trascriverli** nel Modello Redditi PF o nel Modello 730.

**Cosa fa:** produce i numeri dei quadri **RM/M** (redditi di capitale), **RT/T** (plusvalenze) e
**RW/W** (monitoraggio + IVAFE), e calcola l'**imposta dovuta**.
**Cosa NON fa:** non compila né invia il modello per te, non recupera prezzi di mercato (le posizioni
aperte al 31/12 sono valutate al costo) e non gestisce crediti d'imposta esteri (i redditi a imposta
sostitutiva non danno diritto a credito). La compilazione materiale del modello resta un tuo passaggio,
guidato dalla sezione **«Come riportare in dichiarazione»** in fondo.

Caso attivo: **cases/__CASE_NAME__** — per un altro export rigenera con
`python viz/build_notebook.py cases/<nome>/config.toml`.""".replace("__CASE_NAME__", CASE_NAME))

code("""
import sys, datetime
from pathlib import Path
from decimal import Decimal
import pandas as pd

# locate the repo root (the directory containing 'src') regardless of cwd
here = Path.cwd()
root = next((p for p in [here, *here.parents] if (p / "src").is_dir()), here)
sys.path.insert(0, str(root / "src"))
import foglio_calcoli as fc
from foglio_calcoli.common import euro          # round to whole euro (half-up), as the forms want

pd.set_option("display.max_rows", 300)
pd.set_option("display.max_columns", 40)

__CASE_LINE__
cfg = fc.load_config(CASE)
res = fc.compute(cfg)

SHARE = cfg["holders"][0]["share"]               # ownership fraction (already applied to IVAFE)
QUOTA = fc.fmt(SHARE * 100)                       # e.g. "100"
STATO_BROKER = cfg["broker_country_code"]         # AdE country code of the broker (RW)

def imposta26(v):
    \"\"\"Imposta sostitutiva del 26% sull'importo (arrotondato all'euro, come nel modello).\"\"\"
    return euro(Decimal(euro(v)) * Decimal("0.26"))

def show(rows, cols=None):
    \"\"\"list[dict] (Decimal/date) -> DataFrame formattato (4 dp troncati, dd/mm/yyyy).\"\"\"
    if not rows:
        return pd.DataFrame()
    cols = cols or list(rows[0].keys())
    def cell(v):
        if isinstance(v, datetime.date):
            return v.strftime("%d/%m/%Y")
        if isinstance(v, Decimal):
            return fc.fmt(v)
        return "" if v is None else v
    return pd.DataFrame([{c: cell(r.get(c)) for c in cols} for r in rows])

for w in res.warnings:
    print("AVVISO:", w)
""".replace("__CASE_LINE__", CASE_LINE))

# ----------------------------------------------------------------------------------------
md("""## Riepilogo — in una tabella

I redditi imponibili e l'imposta dovuta, per quadro. Le cifre di dettaglio sono nelle sezioni
successive; le istruzioni di compilazione sono in fondo.""")
code("""
h = cfg["holders"][0]
print(f"Broker {cfg['broker_code']} ({cfg['broker_country']}, cod. {STATO_BROKER}) — "
      f"intestatario {h['name']} — quota {QUOTA}% — anno {cfg['fiscal_year']}")

righe = []
for g in sorted(res.rm_dividends.groups.values(), key=lambda x: x.codice):
    righe.append(["RM/M — dividendi esteri (H)", f"Stato {g.codice}", euro(g.total), imposta26(g.total)])
for g in sorted(res.rm_funds.groups.values(), key=lambda x: x.codice):
    righe.append(["RM/M — plusval. fondi/ETF (B)", f"Stato {g.codice}", euro(g.total), imposta26(g.total)])
if res.rt.plus > 0:
    righe.append(["RT/T — plusvalenze azioni/ETF", "netto", euro(res.rt.net_imponibile),
                  imposta26(res.rt.net_imponibile)])
elif res.rt.minus > 0:
    righe.append(["RT/T — minusvalenza (da riportare)", "netto", -euro(res.rt.minus), 0])
for s in res.rw_instruments.summary:
    righe.append([f"RW/W — strumenti ({s['Tipo']})", "IVAFE 0,2%", euro(s["Valore Finale"]), s["IVAFE"]])
for s in res.rw_liquidity.summary:
    righe.append([f"RW/W — liquidità ({s['Tipo']})", "solo monitoraggio", euro(s["Valore Finale"]), s["IVAFE"]])

riepilogo = pd.DataFrame(righe, columns=["Quadro", "Voce", "Imponibile / Valore €", "Imposta €"])
tot_imposta = sum(r[3] for r in righe)
display(riepilogo)
print(f"TOTALE imposta da versare (F24): {tot_imposta} €")
""")

# ----------------------------------------------------------------------------------------
md("""## Quadro RM/M — Redditi di capitale (imposta sostitutiva 26%)

Dividendi esteri (codice **H**, al lordo della ritenuta estera) e plusvalenze da fondi/ETF UCITS
(codice **B**, metodo PMC), raggruppati per Stato. Le minusvalenze da fondi confluiscono nel quadro RT.""")
code("""
print("Dividendi (H) e fondi (B) — sommario per Stato")
display(show(res.rm_dividends.summary))
display(show(res.rm_funds.summary))
for etichetta, gruppi, colonne in [
    ("H", res.rm_dividends.groups, ["Data","Ticker","ISIN","Valuta","Importo Valuta","Cambio EUR","Importo EUR"]),
    ("B", res.rm_funds.groups, ["Data chiusura","Ticker","Valuta","Quantità","PMC EUR","Prezzo chiusura","Cambio EUR","Importo EUR"]),
]:
    for code_, g in sorted(gruppi.items()):
        print(f"{etichetta}-{code_}-26%  —  reddito {euro(g.total)} €  ·  imposta {imposta26(g.total)} €")
        display(show(g.rows, colonne))
""")

# ----------------------------------------------------------------------------------------
md("""## Quadro RT/T — Plusvalenze (redditi diversi, 26%)

Azioni con metodo **LIFO**, fondi/ETF in minusvalenza con **PMC**. Se il saldo netto è positivo è
imponibile al 26%; se negativo, la minusvalenza si riporta nei 4 anni successivi.""")
code("""
print(f"Totale corrispettivi {fc.fmt(res.rt.corrispettivi)}  ·  totale costi {fc.fmt(res.rt.costi)}")
print(f"Plusvalenza {fc.fmt(res.rt.plus)}  ·  minusvalenza {fc.fmt(res.rt.minus)}  ·  "
      f"imponibile netto {fc.fmt(res.rt.net_imponibile)}  ·  imposta {imposta26(res.rt.net_imponibile) if res.rt.plus>0 else 0} €")
display(show(res.rt.rows,
             ["Ticker","Valuta","Quantità","Data Ch.","Cambio Ch.","Prezzo Ch.",
              "Data Ap.","Cambio Ap.","Prezzo Ap.","Ricavi","Costi"]))
""")

# ----------------------------------------------------------------------------------------
md("""## Quadro RW/W — Monitoraggio e IVAFE (0,2%)

Un rigo per prodotto (azioni, ETF) e per valuta di liquidità. Posizioni aperte al 31/12 al costo;
posizioni ereditate da un anno precedente valutate al 01/01. `IVAFE = valore finale × giorni ÷ 365 ×
0,2% × quota`. La liquidità è un **deposito infruttifero** → solo monitoraggio, **IVAFE 0**.""")
code("""
print("Strumenti finanziari")
display(show(res.rw_instruments.summary,
             ["Tipo","Codice","Valore Iniziale","Valore Finale","Giorni Ivafe","IVAFE"]))
print("Liquidità")
display(show(res.rw_liquidity.summary,
             ["Tipo","Codice","Valore Iniziale","Valore Finale","Giorni Ivafe","IVAFE"]))
""")

# ----------------------------------------------------------------------------------------
md("""# Come riportare in dichiarazione

Puoi presentare **UNA** delle due dichiarazioni — riportano gli stessi dati con nomi di quadro diversi:

| | Redditi di capitale | Plusvalenze | Monitoraggio + IVAFE |
|---|---|---|---|
| **Modello Redditi PF** | Quadro **RM**, Sez. II-A | Quadro **RT**, Sez. II | Quadro **RW** |
| **Modello 730** | Quadro **M**, Sez. II-A | Quadro **T**, Sez. II | Quadro **W** |

**Tre passi:**
1. **Redditi (RM/M e RT/T):** riporta le righe della prima tabella qui sotto; l'imposta sostitutiva
   del 26% è già calcolata.
2. **Monitoraggio (RW/W):** riporta la seconda tabella, un rigo per prodotto/valuta — il `Codice
   Stato estero` del broker e la tua quota di possesso sono già indicati in ciascuna riga.
3. **Versa** il totale con **F24** (imposta sostitutiva su redditi di capitale e plusvalenze + IVAFE,
   cod. tributo IVAFE **4043**) — verifica sempre i codici tributo dell'anno.

Le cifre sotto sono già arrotondate all'euro (come richiede il modello).""")
code("""
# ---- Tabella 1: redditi e imposta (RM + RT) ----
map_redditi = []
for tipo, gruppi, descr in [("H", res.rm_dividends.groups, "Dividendi esteri"),
                            ("B", res.rm_funds.groups, "Plusvalenze fondi/ETF")]:
    for code_, g in sorted(gruppi.items()):
        amm, imp = euro(g.total), imposta26(g.total)
        map_redditi.append({
            "Voce": f"{descr} — Stato {code_}",
            "Importo €": amm, "Imposta 26% €": imp,
            "Redditi PF": f"RM31 (un modulo per riga): col.1 «{tipo}» · col.2 «{code_}» · col.3 «{amm}» · col.4 «26%» · imposta «{imp}»",
            "Modello 730": f"M, Sez. II-A: Tipo «{tipo}» · Stato «{code_}» · reddito «{amm}»",
        })
if res.rt.plus > 0:
    corr, cost, net, imp = euro(res.rt.corrispettivi), euro(res.rt.costi), euro(res.rt.net_imponibile), imposta26(res.rt.net_imponibile)
    map_redditi.append({
        "Voce": "Plusvalenze azioni/ETF (RT)",
        "Importo €": net, "Imposta 26% €": imp,
        "Redditi PF": f"RT11: corrispettivi «{corr}», costi «{cost}» → plusvalenza «{net}» → imposta RT «{imp}»",
        "Modello 730": f"T11: corrispettivi «{corr}», costi «{cost}»",
    })
elif res.rt.minus > 0:
    map_redditi.append({
        "Voce": "Minusvalenza azioni/ETF (RT)",
        "Importo €": -euro(res.rt.minus), "Imposta 26% €": 0,
        "Redditi PF": f"RT: eccedenza minusvalenze «{euro(res.rt.minus)}» da riportare nei 4 anni successivi",
        "Modello 730": f"T: eccedenza minusvalenze «{euro(res.rt.minus)}» da riportare",
    })
display(pd.DataFrame(map_redditi))

# ---- Tabella 2: monitoraggio + IVAFE (RW) ----
map_rw = []
for s in res.rw_instruments.summary:
    map_rw.append({
        "Prodotto": f"Strumenti — {s['Tipo']}", "Natura": "titoli/strumenti finanziari",
        "Stato": STATO_BROKER, "Valore €": euro(s["Valore Finale"]),
        "Giorni": fc.fmt(s["Giorni Ivafe"]), "Quota %": QUOTA, "IVAFE €": s["IVAFE"],
    })
for s in res.rw_liquidity.summary:
    map_rw.append({
        "Prodotto": f"Liquidità — {s['Tipo']}", "Natura": "conto/deposito (infruttifero, cod. 14)",
        "Stato": STATO_BROKER, "Valore €": euro(s["Valore Finale"]),
        "Giorni": fc.fmt(s["Giorni Ivafe"]), "Quota %": QUOTA, "IVAFE €": s["IVAFE"],
    })
print("Quadro RW (Redditi PF) / Quadro W (730) — un rigo per prodotto/valuta")
display(pd.DataFrame(map_rw))

tot = sum(r["Imposta 26% €"] for r in map_redditi if isinstance(r["Imposta 26% €"], int)) \\
      + sum(r["IVAFE €"] for r in map_rw)
print(f"TOTALE da versare con F24: {tot} €")
""")

nb = new_notebook()
nb["cells"] = cells
nb["metadata"] = {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                  "language_info": {"name": "python"}}
with open(HERE / "Foglio_Calcoli.ipynb", "w") as f:
    nbf.write(nb, f)
print(f"wrote {HERE/'Foglio_Calcoli.ipynb'} ({len(cells)} cells)")
