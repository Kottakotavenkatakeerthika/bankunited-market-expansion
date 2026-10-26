"""Quality checks on the processed tables, so bad data never gets tagged.

    python -m src.checks      # exits with code 1 if any check fails

Results are also written to data/processed/checks_report.md: the "evidence of
what was tested" for the weekly Integration & Delivery Updates.

Column-name suffixes drive the range checks (see docs/data_dictionary.md):
_count and _usd must be >= 0, _pct must be 0-100, _share must be 0-1.
_net: can be negative; no range check.
The data dictionary drives the schema checks: every processed column needs exactly
one row in docs/data_dictionary.md, and its values must fit that row's Type (int,
numeric, string, string(N) or date). A documented column that isn't built yet is
only a warning, so a column can be documented before it's built.
Published figures to compare against go in data/reference/spot_checks.csv.
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src import config
from src.build_panel import grid_years
from src.utils import CODE_WIDTHS

NONNEGATIVE_SUFFIXES = ("_count", "_usd")
MOSTLY_EMPTY = 0.5  # warn when more than half of a column is empty
DICTIONARY_TYPES = re.compile(r"int|numeric|date|string(?:\((\d+)\))?")  # the Type column's allowed values


@dataclass
class Result:
    table: str
    check: str
    passed: bool
    detail: str = ""
    level: str = "error"  # "error" fails the run; "warning" is only reported


@dataclass
class DictionaryRow:
    column: str
    type: str
    line: int  # line number in docs/data_dictionary.md, for error messages


def read_dictionary(path: Path | None = None) -> dict[str, list[DictionaryRow]]:
    """Each table's column rows in the data dictionary, keyed by table name.

    A table's rows are the table rows (lines starting with "| `") under a heading
    like "## msa_year: one row per metro per year". Only the Column and Type cells
    are read; other sections, such as Conventions, are skipped.
    """
    path = Path(path or config.DATA_DICTIONARY)
    tables: dict[str, list[DictionaryRow]] = {}
    current = None
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.startswith("## "):
            heading = re.match(r"##\s+`?(\w+)`?\s*:", line)
            current = heading.group(1) if heading else None
            if current:
                tables.setdefault(current, [])
            continue
        if current and line.lstrip().startswith("| `"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) >= 2:
                tables[current].append(DictionaryRow(cells[0].strip("`"), cells[1], number))
    return tables


def _type_problem(values: pd.Series, column_type: str) -> str:
    """Why a column's values don't fit its dictionary Type, or "" if they do. Missing values aren't checked."""
    present = values.dropna()
    if present.empty:
        return ""
    if column_type in ("int", "numeric"):
        if not pd.api.types.is_numeric_dtype(values) or pd.api.types.is_bool_dtype(values):
            return f"stored as {values.dtype}, not numbers"
        if column_type == "int":  # decimals that are all whole numbers pass, so no stored type has to change
            numbers = present.astype("float64")
            fractional = ~np.isfinite(numbers) | (numbers != np.floor(numbers))
            if fractional.any():
                return (f"{int(fractional.sum())} values aren't whole numbers, "
                        f"e.g. {numbers[fractional].head(3).tolist()}")
        return ""
    if column_type == "date":
        return "" if pd.api.types.is_datetime64_any_dtype(values) else f"stored as {values.dtype}, not dates"
    kind = pd.api.types.infer_dtype(present, skipna=True)  # string or string(N)
    if kind != "string":
        return f"holds {kind} values, not text"
    width = DICTIONARY_TYPES.fullmatch(column_type).group(1)
    if width:
        wrong = present[present.str.len() != int(width)]
        if len(wrong):
            return f"{len(wrong)} values aren't {width} characters long, e.g. {wrong.head(3).tolist()}"
    return ""


def schema_checks(table: str, df: pd.DataFrame, rows: list[DictionaryRow]) -> list[Result]:
    """Hold a processed table to its section of the data dictionary."""
    if not rows:
        return [Result(table, "every column has a dictionary row", False,
                       f"docs/data_dictionary.md has no section headed '## {table}: ...'")]
    documented = [row.column for row in rows]
    undocumented = [col for col in df.columns if col not in documented]
    repeated = {name: [row.line for row in rows if row.column == name]
                for name in dict.fromkeys(documented) if documented.count(name) > 1}
    unknown = [f"{row.column} ({row.type!r}, line {row.line})"
               for row in rows if not DICTIONARY_TYPES.fullmatch(row.type)]
    types = {row.column: row.type for row in rows if DICTIONARY_TYPES.fullmatch(row.type)}
    misfits = [f"{col} ({types[col]}): {problem}" for col in df.columns
               if col in types and (problem := _type_problem(df[col], types[col]))]
    results = [
        Result(table, "every column has a dictionary row", not undocumented,
               f"no row in docs/data_dictionary.md for {undocumented}" if undocumented else ""),
        Result(table, "no column has two dictionary rows", not repeated,
               "; ".join(f"{name} on lines {lines}" for name, lines in repeated.items())),
        Result(table, "every dictionary Type is known", not unknown,
               f"{unknown}; use int, numeric, string, string(N) or date" if unknown else ""),
        Result(table, "values fit their dictionary Type", not misfits, "; ".join(misfits)),
    ]
    unbuilt = [name for name in dict.fromkeys(documented) if name not in df.columns]
    if unbuilt:
        results.append(Result(table, "every dictionary row is built", False,
                              f"documented but not in the table yet: {unbuilt}", level="warning"))
    return results


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

    years = grid_years(table)
    if years is not None and config.MSA_UNIVERSE.exists():
        universe = pd.read_csv(config.MSA_UNIVERSE, dtype=str)["cbsa_code"].dropna().str.strip().str.zfill(5)
        expected = {(code, year) for code in universe for year in years}
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


def _compare(table: str, name: str, match: pd.Series, spec: pd.Series) -> Result:
    """One spot check: the built value against the published one, within rel_tolerance (default 0.1%)."""
    if match.empty or pd.isna(match.iloc[0]):
        return Result(table, name, False, "no value to compare")
    actual, expected = float(match.iloc[0]), float(spec["expected"])
    tolerance = float(spec["rel_tolerance"]) if pd.notna(spec.get("rel_tolerance")) else 0.001
    ok = abs(actual - expected) <= tolerance * abs(expected) if expected else actual == 0
    note = spec.get("source_note") if pd.notna(spec.get("source_note")) else ""
    return Result(table, name, ok, f"built {actual:,.2f} vs published {expected:,.2f} {note}".strip())


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
        results.append(_compare("msa_year", name, match, spec))
    return results


def bank_spot_checks(df: pd.DataFrame) -> list[Result]:
    """Compare bank_quarter values with figures published elsewhere, such as a bank's UBPR.

    Each row of data/reference/bank_spot_checks.csv names a bank (rssd_id), a quarter_end
    (YYYY-MM-DD), a column, the published value in the column's own unit (whole dollars
    for _usd, percent for _ratio), and where it was published.
    """
    if not config.BANK_SPOT_CHECKS.exists():
        return []
    specs = pd.read_csv(config.BANK_SPOT_CHECKS, dtype=str).dropna(how="all")
    results = []
    for _, spec in specs.iterrows():
        rssd, quarter, col = str(spec["rssd_id"]).strip(), pd.Timestamp(spec["quarter_end"]), spec["column"]
        name = f"spot check: {col} for RSSD {rssd} on {quarter:%Y-%m-%d}"
        if col not in df.columns:
            results.append(Result("bank_quarter", name, False, "column not in table"))
            continue
        here = (df["rssd_id"].astype(str) == rssd) & (pd.to_datetime(df["quarter_end"]) == quarter)
        results.append(_compare("bank_quarter", name, df.loc[here, col], spec))
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
    dictionary = read_dictionary() if config.DATA_DICTIONARY.exists() else None
    for table in config.TABLES:
        path = config.PROCESSED / f"{table}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        results += check_table(table, df)
        if dictionary is None:
            results.append(Result(table, "every column has a dictionary row", False,
                                  f"{config.DATA_DICTIONARY} doesn't exist"))
        else:
            results += schema_checks(table, df, dictionary.get(table, []))
        if table == "msa_year":
            results += spot_checks(df)
        if table == "bank_quarter":
            results += bank_spot_checks(df)
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
