"""FFIEC CRA small-business lending: county totals rolled up to metros (the lending pool). Owner: Bhavana.

Output:  data/interim/msa_year/cra.parquet   keys: cbsa_code, year   measures: cra_*

Starting points (verify before relying on them):
  - CRA aggregate flat files report small-business lending by county each year.
    Map them with state + county FIPS and counties_to_cbsa(), not the file's
    MSA/MD field, where large metros appear as Metropolitan Divisions.
  - Loan amounts may be reported in $1,000s: convert to whole dollars.
  - Each bank's share of that lending is Austin's, in src/ingest_ffiec.py.

File format (verified against FFIEC's official 2023 Aggregate File Specs,
ffiec.gov/sites/default/files/data/cra/flat-files/23FlatAggSpecs.pdf):
  - Download: one ZIP per year, https://www.ffiec.gov/sites/default/files/data/cra/flat-files/<YY>exp_aggr.zip
  - Fixed-width text file inside, record length 145, mixing several tables by
    a Table ID in columns 1-5. We use Table A1-1 (Small Business Loans by
    County - Originations), County Total rows only (Report Level = "200").
  - Columns used (1-indexed, inclusive): State 12-13, County 14-16,
    Report Level 34-36, then three loan-count/loan-amount pairs by size
    bucket: <$100k (37-46 / 47-56), $100k-$250k (57-66 / 67-76),
    $250k-$1M (77-86 / 87-96). Amounts are in $1,000s.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pandas as pd

from src import config
from src.crosswalk import counties_to_cbsa
from src.utils import fetch, write_interim

SOURCE = "cra"

CRA_LATEST_AVAILABLE_YEAR = 2024

# 1-indexed, inclusive byte positions from the FFIEC spec, converted to
# 0-indexed Python slice (start, end) pairs.
FIELDS = {
    "table_id": (0, 5),
    "state": (11, 13),
    "county": (13, 16),
    "report_level": (33, 36),
    "count_under_100k": (36, 46),
    "amount_under_100k": (46, 56),
    "count_100k_250k": (56, 66),
    "amount_100k_250k": (66, 76),
    "count_250k_1m": (76, 86),
    "amount_250k_1m": (86, 96),
}


def download(years: list[int], force: bool = False) -> list[Path]:
    """Pull the CRA aggregate files for each year into data/raw/cra/ with fetch(url, SOURCE)."""
    paths = []
    for year in years:
        if year > CRA_LATEST_AVAILABLE_YEAR:
            print(f"[cra] skipping {year}: CRA hasn't published past {CRA_LATEST_AVAILABLE_YEAR} yet")
            continue
        yy = f"{year % 100:02d}"
        filename = f"{yy}exp_aggr.zip"
        url = f"https://www.ffiec.gov/sites/default/files/data/cra/flat-files/{filename}"
        path = fetch(url, SOURCE, filename=filename, force=force,
                      notes=f"FFIEC CRA aggregate flat file, {year}")
        paths.append(path)
    return paths


def _read_one_year(path: Path) -> pd.DataFrame:
    """Read one <YY>exp_aggr.zip and keep County Total rows from Table A1-1 (small business, originations)."""
    match = re.search(r"(\d{2})exp_aggr\.zip$", path.name)
    if not match:
        raise ValueError(f"Can't tell what year {path.name} is for; expected <YY>exp_aggr.zip")
    year = 2000 + int(match.group(1))

    with zipfile.ZipFile(path) as archive:
        inner_name = next(
            (name for name in archive.namelist() if not name.endswith("/")),
            None,
        )
        if inner_name is None:
            raise ValueError(f"No file found inside {path.name}")
        with archive.open(inner_name) as handle:
            lines = handle.read().decode("latin-1").splitlines()

    rows = []
    for line in lines:
        if len(line) < 96:
            continue
        table_id = line[FIELDS["table_id"][0]:FIELDS["table_id"][1]].strip()
        if table_id != "A1-1":
            continue
        report_level = line[FIELDS["report_level"][0]:FIELDS["report_level"][1]].strip()
        if report_level != "200":  # County Total rows only
            continue
        state = line[FIELDS["state"][0]:FIELDS["state"][1]].strip()
        county = line[FIELDS["county"][0]:FIELDS["county"][1]].strip()
        if not state or not county:
            continue

        def field(name):
            s, e = FIELDS[name]
            return int(line[s:e])

        rows.append({
            "county_fips": state + county,
            "year": year,
            "cra_small_business_loan_count": (
                field("count_under_100k") + field("count_100k_250k") + field("count_250k_1m")
            ),
            "cra_small_business_loan_amount_usd": (
                field("amount_under_100k") + field("amount_100k_250k") + field("amount_250k_1m")
            ) * 1000,
        })

    if not rows:
        raise ValueError(f"{path.name}: no County Total rows found for table A1-1; has the file layout changed?")
    return pd.DataFrame(rows)


def transform(paths: list[Path], years: list[int]) -> list[Path]:
    """County totals -> metro-year with counties_to_cbsa(); save with write_interim(df, SOURCE, "msa_year")."""
    if not paths:
        raise ValueError("cra: no raw files to transform; did download() run first?")

    county_level = pd.concat([_read_one_year(path) for path in paths], ignore_index=True)
    metro_level = counties_to_cbsa(
        county_level,
        value_cols=["cra_small_business_loan_count", "cra_small_business_loan_amount_usd"],
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