"""Configuration loading from a config.toml file (stdlib tomllib)."""
from __future__ import annotations

from pathlib import Path
import tomllib

from .common import D, dec


def load_config(path: "Path | str | None" = None) -> dict:
    """Read a config.toml into the internal flat config dict used across the library.

    Directories resolve relative to the config file (or absolute if given so). The optional
    ``[test]`` block (with ``[test.expected]``) is passed through untouched for the test runner.
    """
    path = Path(path) if path else Path("config.toml")
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    base = path.resolve().parent

    def resolve(p) -> Path:
        p = Path(p)
        return p if p.is_absolute() else base / p

    broker = raw.get("broker", {})
    holders = [{"name": h.get("name", ""), "share": dec(h.get("share", 1))}
               for h in raw.get("holders", [])]
    opening = raw.get("opening", {})
    return {
        "broker_code": broker.get("code"),
        "broker_country": broker.get("country"),
        "broker_country_code": str(broker.get("country_code", "")),
        "fiscal_year": int(raw["fiscal_year"]),
        "holders": holders or [{"name": "", "share": D(1)}],
        "input_dir": resolve(raw.get("input_dir", "input")),
        "ref_dir": resolve(raw.get("ref_dir", "data")),
        "fund_overrides": dict(raw.get("fund_overrides", {})),
        "minus_carryforward": dec(raw.get("minus_carryforward", 0)),
        "allow_fetch": bool(raw.get("allow_fetch", True)),
        "isin_country_overrides": dict(raw.get("isin_country_overrides", {})),
        "country_ade_overrides": dict(raw.get("country_ade_overrides", {})),
        # opening balances may be given inline in config or via input CSVs (see parsing.py)
        "opening_cash": {k: dec(v) for k, v in dict(opening.get("cash", {})).items()},
        "opening_positions": list(opening.get("positions", [])),
        # test block passed through verbatim for the test runner
        "test": raw.get("test"),
        "config_path": str(path),
        "config_dir": base,
    }
