#!/usr/bin/env python3
"""CLI to download Banca d'Italia EUR exchange rates into data/ (delegates to the library).

The importable routine lives in `foglio_calcoli.rates.fetch_rates(years, currencies, ref_dir)`;
`compute()` calls it automatically for the currencies/years an export needs. This script is the
manual entry point.

Usage:  python3 data/fetch_bdi_rates.py YEAR [CUR ...]        (default currencies: USD)
        python3 data/fetch_bdi_rates.py 2025 USD GBP CHF
"""
import sys
from pathlib import Path

from foglio_calcoli.rates import fetch_rates

HERE = Path(__file__).resolve().parent


def main() -> None:
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
    currencies = sys.argv[2:] or ["USD"]
    fetch_rates([year], currencies, HERE)
    print(f"updated data/bdi_daily_eur.csv, data/bdi_monthly_eur.csv "
          f"(year={year}, currencies={currencies})")


if __name__ == "__main__":
    main()
