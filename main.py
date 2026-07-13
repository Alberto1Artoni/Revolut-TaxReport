#!/usr/bin/env python3
"""Repo-root entry point — a thin shim over ``foglio_calcoli.cli``.

Requires the package to be installed (``pip install -e .``); then, from the repo root:
    python main.py --test
    python main.py --config cases/<name>/config.toml
Equivalent to the ``foglio-calcoli`` console script and ``python -m foglio_calcoli``.
"""
try:
    from foglio_calcoli.cli import main
except ModuleNotFoundError as e:
    if e.name and e.name.split(".")[0] == "foglio_calcoli":
        raise SystemExit(
            "foglio_calcoli is not installed. From the repo root:\n"
            "    python3 -m venv .venv && ./.venv/bin/pip install -e .\n"
            "then run:  ./.venv/bin/python main.py --test"
        ) from e
    raise

if __name__ == "__main__":
    raise SystemExit(main())
