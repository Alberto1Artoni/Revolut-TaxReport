# `data/` — official Banca d'Italia exchange rates

Bundled reference exchange rates so the notebook runs **offline and reproducibly**. Source:
Banca d'Italia "tassidicambio" REST service (the official rates Italian tax filings must use).

## Files
- **`bdi_daily_eur.csv`** — `date, iso_code, rate_per_eur` — daily rates, business days only
  (255 rows for 2025). Used for **Quadro RM/M** (dividends, fund gains) and **Quadro RT/T**
  (proceeds/costs), which require the *cambio medio giornaliero*.
- **`bdi_monthly_eur.csv`** — `year, month, iso_code, rate_per_eur` — monthly averages (12 rows).
  Used for **Quadro RW/W** IVAFE (instruments + liquidity), which requires the *cambio medio mensile*.
- **`fetch_bdi_rates.py`** — regenerates/extends the two rate CSVs.
- **`ade_country_codes.csv`** — official Agenzia delle Entrate *Elenco codici Stati esteri*
  (`ade_code, iso2, name_it`). Maps an instrument's country (from its ISIN alpha-2 prefix) to the
  numeric "Codice Stato estero" used in quadri RM/M and RW/W. Rows for territories without a
  standard ISO alpha-2 leave `iso2` blank.

## Convention (important)
`rate_per_eur` is the **standard BdI quote = units of foreign currency per 1 EUR** (e.g.
`USD/EUR = 1.1754`), at BdI's full published precision.

The Foglio Calcoli's **"Cambio EUR"** (the EUR value of 1 unit of foreign currency) is:

```
cambio_eur = trunc4( 1 / rate_per_eur )        # Decimal, truncate to 4 decimals
```

Store the per-EUR quote and invert in code — do **not** store a pre-inverted value. Inverting
then truncating is what matches the reference PDF exactly, e.g. `1/1.1754 = 0.850774… → 0.8507`
(BdI's own pre-inverted figure would round to `0.8508`). EUR itself is always `cambio_eur = 1`
and is not stored.

## Lookup rules for the notebook
- **EUR**: `cambio_eur = 1`.
- **Daily**: look up `(date, iso_code)`; if the date is missing (weekend/holiday, e.g. 2025-12-26
  Santo Stefano), use the **most recent prior business day**. (That fallback reproduces the
  reference's `0.8483` for the 26/12 NVDA dividend, taken from 24/12.)
- **Monthly**: look up `(year, month, iso_code)`.

## Validated against the reference PDF
`fetch_bdi_rates.py` asserts, among others: daily 06/25 → 0.8622, 06/30 → 0.8532, 10/02 → 0.8507,
10/06 → 0.8563; monthly 03 → 0.9253, 10 → 0.8598 — all matching
the reference Foglio Calcoli PDF.

## Regenerate / extend
```bash
python3 data/fetch_bdi_rates.py 2025 USD          # default
python3 data/fetch_bdi_rates.py 2025 USD GBP CHF  # add currencies if a future export needs them
```
The Revolut sample only uses EUR + USD; add currencies here if new exports reference others.
