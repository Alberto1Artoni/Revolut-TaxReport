"""Foglio Calcoli command-line interface.

Exposed three ways (all equivalent): the installed console script ``foglio-calcoli``,
``python -m foglio_calcoli``, and the repo-root ``main.py`` shim. Run from the repo root so
``--test`` can discover ``cases/*/config.toml``.

  foglio-calcoli --config cases/<name>/config.toml [--out report.txt] [--format text|json] [-v]
  foglio-calcoli --test [--config cases/<name>/config.toml] [-v]

Each processed case writes artifacts into ``cases/<name>/output/``:
  <name>.log  (run log)  +  report.txt  +  summary_*.csv / metrics.csv (summary tables).
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import foglio_calcoli as fc

LOGGER = logging.getLogger("foglio_calcoli")


def _case_name(cfg: dict) -> str:
    return Path(cfg["config_dir"]).name


def _output_dir(cfg: dict) -> Path:
    out = Path(cfg["config_dir"]) / "output"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _attach_logging(out_dir: Path, name: str, verbose: bool) -> logging.Handler:
    """Route the library logger to cases/<name>/output/<name>.log (and console if verbose).
    Removes any handler we attached on a previous case."""
    LOGGER.setLevel(logging.DEBUG)
    for h in list(LOGGER.handlers):
        if getattr(h, "_fc_managed", False):
            LOGGER.removeHandler(h)
            h.close()
    fh = logging.FileHandler(out_dir / f"{name}.log", mode="w", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
                                      "%Y-%m-%d %H:%M:%S"))
    fh._fc_managed = True
    LOGGER.addHandler(fh)
    if verbose:
        sh = logging.StreamHandler()
        sh.setLevel(logging.INFO)
        sh.setFormatter(logging.Formatter("  %(levelname)s %(message)s"))
        sh._fc_managed = True
        LOGGER.addHandler(sh)
    return fh


def _run(config_path: str, out: str | None, fmt: str, verbose: bool) -> int:
    cfg = fc.load_config(config_path)
    name = _case_name(cfg)
    out_dir = _output_dir(cfg)
    _attach_logging(out_dir, name, verbose)
    LOGGER.info("=== RUN case '%s' (config %s) ===", name, cfg["config_path"])

    res = fc.compute(cfg)
    files = fc.write_summaries(res, out_dir)
    LOGGER.info("Wrote %d summary file(s) to %s", len(files), out_dir)

    if fmt == "json":
        text = json.dumps({"metrics": {k: str(v) for k, v in fc.metrics(res).items()},
                           "warnings": res.warnings}, indent=2, ensure_ascii=False)
    else:
        text = fc.render(res)
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {out}")
    else:
        print(text)
    print(f"\nArtifacts: {out_dir}/  (log: {name}.log, report.txt, summary_*.csv)")
    return 0


def _discover_cases() -> list[Path]:
    return sorted(Path("cases").glob("*/config.toml"))


def _test(config_path: str | None, verbose: bool) -> int:
    paths = [Path(config_path)] if config_path else _discover_cases()
    ran, all_ok = 0, True
    for p in paths:
        cfg = fc.load_config(p)
        test = cfg.get("test")
        if not test or not test.get("enabled", True):
            continue
        ran += 1
        name = _case_name(cfg)
        out_dir = _output_dir(cfg)
        _attach_logging(out_dir, name, verbose)
        LOGGER.info("=== TEST case '%s' (config %s) ===", name, cfg["config_path"])

        res = fc.compute(cfg)
        fc.write_summaries(res, out_dir)
        for w in res.warnings:
            print(f"  ! {w}")
        checks = fc.validate(res, test)
        npass = sum(1 for c in checks if c.ok)
        for c in checks:
            LOGGER.info("check %-22s expected %-14s got %-14s -> %s",
                        c.key, fc.fmt(c.expected), fc.fmt(c.got), "OK" if c.ok else "FAIL")
        LOGGER.info("Result: %d/%d checks passed; artifacts in %s", npass, len(checks), out_dir)
        all_ok &= all(c.ok for c in checks)
        print(fc.format_checks(checks, title=f"== {name} =="))
        print(f"  (artifacts: {out_dir}/{name}.log, report.txt, summary_*.csv)\n")
    if ran == 0:
        print("No test cases found (a case config.toml needs a [test] block).")
        return 1
    print("ALL CASES PASSED" if all_ok else "SOME CASES FAILED")
    return 0 if all_ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="foglio-calcoli",
                                 description="Foglio Calcoli — Revolut → Dichiarazione dei Redditi")
    ap.add_argument("--config", "-c", help="path to a case config.toml")
    ap.add_argument("--test", action="store_true", help="run validation from config.toml [test] blocks")
    ap.add_argument("--out", "-o", help="write report to a file instead of stdout")
    ap.add_argument("--format", "-f", choices=["text", "json"], default="text")
    ap.add_argument("--verbose", "-v", action="store_true", help="also echo the run log to the console")
    args = ap.parse_args(argv)
    if args.test:
        return _test(args.config, args.verbose)
    if not args.config:
        ap.error("provide --config <case config.toml> to run, or --test to validate")
    return _run(args.config, args.out, args.format, args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
