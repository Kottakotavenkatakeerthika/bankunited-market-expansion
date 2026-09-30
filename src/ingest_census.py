"""Census County Business Patterns (CBP): establishments, employment, and payroll by county.

Output:  data/interim/msa_year/cbp.parquet    keys: cbsa_code, year    measures: cbp_*

Starting points (verify before relying on them):
  - One county file per year:
    https://www2.census.gov/programs-surveys/cbp/datasets/<YYYY>/cbp<YY>co.zip
  - All-industry totals are the rows where naics == "------"; est, emp, and ap
    (annual payroll, in $1,000s: convert to whole dollars) are the core fields.
  - CBP comes out more than a year after its reference year. Record the release
    date in docs/data_dictionary.md for the Charlotte back-test.

Availability (Data Source Log, Bhavana, 2026-09-28):
  - Measures: establishments, employment, first-quarter payroll, annual payroll
  - Years: 1986-2023
  - Source page: https://www.census.gov/programs-surveys/cbp.html
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pandas as pd

from src import config
from src.crosswalk import counties_to_cbsa
from src.utils import fetch, normalize_code, write_interim

SOURCE = "cbp"

# CBP's county file for a given year isn't published until more than a year
# after that year ends; 2023 is the most recent one available as of this writing.
LATEST_AVAILABLE_YEAR = 2023

VALUE_COLUMNS = [
    "cbp_establishments_count",
    "cbp_employment_count",
    "cbp_first_quarter_payroll_usd",
    "cbp_annual_payroll_usd",
]


def download(years: list[int], force: bool = False) -> list[Path]:
    """Pull one raw file per year into data/raw/cbp/ with fetch(url, SOURCE)."""
    paths = []
    for year in years:
        if year > LATEST_AVAILABLE_YEAR:
            print(f"[cbp] skipping {year}: CBP hasn't published past {LATEST_AVAILABLE_YEAR} yet")
            continue
        yy = f"{year % 100:02d}"
        filename = f"cbp{yy}co.zip"
        url = f"https://www2.census.gov/programs-surveys/cbp/datasets/{year}/{filename}"
        path = fetch(url, SOURCE, filename=filename, force=force, notes=f"CBP county file, {year}")
        paths.append(path)
    return paths


def _read_one_year(path: Path) -> pd.DataFrame:
    """Read one cbp<YY>co.zip and keep the all-industry total row for each county."""
    match = re.search(r"cbp(\d{2})co\.zip$", path.name)
    if not match:
        raise ValueError(f"Can't tell what year {path.name} is for; expected cbp<YY>co.zip")
    year = 2000 + int(match.group(1))

    with zipfile.ZipFile(path) as archive:
        inner_name = next(
            (name for name in archive.namelist() if name.lower().endswith((".txt", ".csv"))),
            None,
        )
        if inner_name is None:
            raise ValueError(f"No .txt or .csv file found inside {path.name}")
        with archive.open(inner_name) as handle:
            raw = pd.read_csv(handle, dtype=str)

    raw.columns = [c.strip().upper() for c in raw.columns]
    required = ["FIPSTATE", "FIPSCTY", "NAICS", "EST", "EMP", "QP1", "AP"]
    missing = [c for c in required if c not in raw.columns]
    if missing:
        raise ValueError(f"{path.name}: missing expected columns {missing}")

    totals = raw.loc[raw["NAICS"].str.strip() == "------"].copy()
    county_fips = normalize_code(totals["FIPSTATE"], 2) + normalize_code(totals["FIPSCTY"], 3)

    return pd.DataFrame({
        "county_fips": county_fips,
        "year": year,
        "cbp_establishments_count": pd.to_numeric(totals["EST"], errors="coerce"),
        "cbp_employment_count": pd.to_numeric(totals["EMP"], errors="coerce"),
        "cbp_first_quarter_payroll_usd": pd.to_numeric(totals["QP1"], errors="coerce") * 1000,
        "cbp_annual_payroll_usd": pd.to_numeric(totals["AP"], errors="coerce") * 1000,
    })


def transform(paths: list[Path], years: list[int]) -> list[Path]:
    """County totals -> metro-year with counties_to_cbsa(); save with write_interim(df, SOURCE, "msa_year")."""
    if not paths:
        raise ValueError("cbp: no raw files to transform; did download() run first?")

    county_level = pd.concat([_read_one_year(path) for path in paths], ignore_index=True)
    metro_level = counties_to_cbsa(
        county_level,
        value_cols=VALUE_COLUMNS,
        county_col="county_fips",
        by=("year",),
        metro_only=True,
    )
    output_path = write_interim(metro_level, SOURCE, "msa_year")
    return [output_path]


def run(years: list[int] | None = None, force: bool = False) -> list[Path]:
    years = list(years or config.YEARS)
    return transform(download(years, force=force), years)


if __name__ == "__main__":
    run()