"""foglio_calcoli — Revolut → Italian Dichiarazione dei Redditi (foreign accounts).

Public API:
    load_config(path)      -> config dict (from config.toml)
    compute(config)        -> Result (all quadri + Extra)
    render(result)         -> text report
    metrics(result)        -> named scalar values (for validation / JSON)
    validate(result, test) -> list[Check]
    write_summaries(result, out_dir) -> [Path]   (summary CSVs + report.txt)
"""
from __future__ import annotations

import logging

from .common import fmt
from .config import load_config
from .engine import compute
from .models import Result, Ctx, metrics
from .report import render, write_summaries
from .validate import validate, Check, format_checks

__all__ = ["load_config", "compute", "render", "metrics", "validate", "Check",
           "format_checks", "write_summaries", "fmt", "Result", "Ctx"]

logging.getLogger("foglio_calcoli").addHandler(logging.NullHandler())   # library configures no handlers
