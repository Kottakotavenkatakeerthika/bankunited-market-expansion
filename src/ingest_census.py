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

from pathlib import Path

from src import config
from src.crosswalk import counties_to_cbsa  # noqa: F401  county rows -> metro rows
from src.utils import fetch, write_interim  # noqa: F401

SOURCE = "cbp"


def download(years: list[int], force: bool = False) -> list[Path]:
    """Pull one raw file per year into data/raw/cbp/ with fetch(url, SOURCE)."""
    raise NotImplementedError("download")


def transform(paths: list[Path], years: list[int]) -> list[Path]:
    """County totals -> metro-year with counties_to_cbsa(); save with write_interim(df, SOURCE, "msa_year")."""
    raise NotImplementedError("transform")


def run(years: list[int] | None = None, force: bool = False) -> list[Path]:
    years = list(years or config.YEARS)
    return transform(download(years, force=force), years)
