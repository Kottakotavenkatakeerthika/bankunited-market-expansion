"""Quality checks on the processed tables, so bad data never gets tagged.

    python -m src.checks      # exits with code 1 if any check fails

Results are also written to data/processed/checks_report.md: the "evidence of
what was tested" for the weekly Integration & Delivery Updates.

Column-name suffixes drive the range checks (see docs/data_dictionary.md):
_count and _usd must be >= 0, _pct must be 0-100, _share must be 0-1.
Published figures to compare against go in data/reference/spot_checks.csv.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from src import config
from src.utils import CODE_WIDTHS

NONNEGATIVE_SUFFIXES = ("_count", "_usd")
MOSTLY_EMPTY = 0.5  # warn when more than half of a column is empty


@dataclass
class Result:
    table: str
    check: str
    passed: bool
    detail: str = ""
    level: str = "error"  # "error" fails the run; "warning" is only reported


def check_table(table: str, df: pd.DataFrame) -> list[Result]:
    keys = config.TABLES[table]
    results: list[Result] = []

    missing = [key for key in keys if key not in df.columns]
    results.append(Result(table, "key columns present", not missing, f"missing {missing}" if missing else ""))
    if missing:
        return results
    null_rows = int(df[keys].isna().any(axis=1).sum())
    results.append(Result(table, "no empty keys", null_rows == 0, f"{null_rows} rows" if null_rows else ""))
    dupes = int(df.duplicated(keys).sum())
    results.append(Result(table, "one row per key", dupes == 0, f"{dupes} repeated keys" if dupes else ""))

    for col, width in CODE_WIDTHS.items():
        if col in df.columns:
            codes = df[col].dropna().astype(str)
            bad = codes[~codes.str.fullmatch(rf"\d{{{width}}}")]
            results.append(Result(table, f"{col} is {width} digits", bad.empty,
                                  f"{len(bad)} malformed, e.g. {bad.head(3).tolist()}" if len(bad) else ""))

    if table == "msa_year" and config.MSA_UNIVERSE.exists():
        universe = pd.read_csv(config.MSA_UNIVERSE, dtype=str)["cbsa_code"].dropna().str.strip().str.zfill(5)
        expected = {(code, year) for code in universe for year in config.YEARS}
        present = set(zip(df["cbsa_code"].astype(str), df["year"].astype(int)))
        gaps = sorted(expected - present)
        results.append(Result(table, "every universe metro has every year", not gaps,
                              f"{len(gaps)} missing, e.g. {gaps[:3]} (rebuild after editing msa_universe.csv)" if gaps else ""))

    for col in df.columns:
        if col in keys or not pd.api.types.is_numeric_dtype(df[col]):
            continue
        values = df[col].dropna()
        if col.endswith(NONNEGATIVE_SUFFIXES):
            bad = int((values < 0).sum())
            results.append(Result(table, f"{col} >= 0", bad == 0, f"{bad} negative" if bad else ""))
        if col.endswith("_pct"):
            bad = int(((values < 0) | (values > 100)).sum())
            results.append(Result(table, f"{col} within 0-100", bad == 0, f"{bad} out of range" if bad else ""))
        if col.endswith("_share"):
            bad = int(((values < 0) | (values > 1)).sum())
            results.append(Result(table, f"{col} within 0-1", bad == 0, f"{bad} out of range" if bad else ""))

    for col in df.columns:
        if col in keys or not len(df):
            continue
        empty = float(df[col].isna().mean())
        if empty == 1.0:
            results.append(Result(table, f"{col} has values", False, "column is empty", level="warning"))
        elif empty > MOSTLY_EMPTY:
            results.append(Result(table, f"{col} mostly filled", False, f"{empty:.0%} empty", level="warning"))
    return results


def spot_checks(df: pd.DataFrame) -> list[Result]:
    """Compare msa_year values with figures a source publishes itself (spot_checks.csv)."""
    if not config.SPOT_CHECKS.exists():
        return []
    specs = pd.read_csv(config.SPOT_CHECKS, dtype=str).dropna(how="all")
    results = []
    for _, spec in specs.iterrows():
        code, year, col = str(spec["cbsa_code"]).strip().zfill(5), int(spec["year"]), spec["column"]
        name = f"spot check: {col} for {code} in {year}"
        if col not in df.columns:
            results.append(Result("msa_year", name, False, "column not in table"))
            continue
        match = df.loc[(df["cbsa_code"] == code) & (df["year"] == year), col]
        if match.empty or pd.isna(match.iloc[0]):
            results.append(Result("msa_year", name, False, "no value to compare"))
            continue
        actual, expected = float(match.iloc[0]), float(spec["expected"])
        tolerance = float(spec["rel_tolerance"]) if pd.notna(spec.get("rel_tolerance")) else 0.001
        ok = abs(actual - expected) <= tolerance * abs(expected) if expected else actual == 0
        note = spec.get("source_note") if pd.notna(spec.get("source_note")) else ""
        results.append(Result("msa_year", name, ok, f"built {actual:,.2f} vs published {expected:,.2f} {note}".strip()))
    return results


def _git_commit() -> str:
    try:
        run = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=config.ROOT,
                             capture_output=True, text=True, check=True)
        return run.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _write_report(results: list[Result]) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    commit = _git_commit()
    lines = ["# Data checks", "", f"Run {stamp}" + (f" on commit `{commit}`" if commit else ""), "",
             "| Table | Check | Result | Detail |", "|---|---|---|---|"]
    for r in results:
        status = "pass" if r.passed else ("FAIL" if r.level == "error" else "warning")
        lines.append(f"| {r.table} | {r.check} | {status} | {r.detail.replace('|', '/')} |")
    config.PROCESSED.mkdir(parents=True, exist_ok=True)
    (config.PROCESSED / "checks_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_checks(write_report: bool = True) -> bool:
    results: list[Result] = []
    for table in config.TABLES:
        path = config.PROCESSED / f"{table}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        results += check_table(table, df)
        if table == "msa_year":
            results += spot_checks(df)
    if not results:
        print("[checks] no processed tables to check yet")
        return True

    failures = [r for r in results if not r.passed and r.level == "error"]
    warnings = [r for r in results if not r.passed and r.level == "warning"]
    for r in failures + warnings:
        print(f"[checks] {'FAIL' if r.level == 'error' else 'warn'} {r.table}: {r.check} {r.detail}".rstrip())
    print(f"[checks] {len(results) - len(failures) - len(warnings)} passed, "
          f"{len(failures)} failed, {len(warnings)} warnings")
    if write_report:
        _write_report(results)
    return not failures


if __name__ == "__main__":
    sys.exit(0 if run_checks() else 1)
