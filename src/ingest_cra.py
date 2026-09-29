"""FFIEC CRA small-business lending: county totals rolled up to metros (the lending pool). Owner: Bhavana.

Output:  data/interim/msa_year/cra.parquet   keys: cbsa_code, year   measures: cra_*

Starting points (verify before relying on them):
  - CRA aggregate flat files report small-business lending by county each year.
    Map them with state + county FIPS and counties_to_cbsa(), not the file's
    MSA/MD field, where large metros appear as Metropolitan Divisions.
  - Loan amounts may be reported in $1,000s: convert to whole dollars.
  - Each bank's share of that lending is Austin's, in src/ingest_ffiec.py.
"""
from __future__ import annotations

from pathlib import Path

from src import config
from src.crosswalk import counties_to_cbsa  # noqa: F401
from src.utils import fetch, write_interim  # noqa: F401

SOURCE = "cra"


def download(years: list[int], force: bool = False) -> list[Path]:
    """Pull the CRA aggregate files for each year into data/raw/cra/ with fetch(url, SOURCE)."""
    raise NotImplementedError("download")


def transform(paths: list[Path], years: list[int]) -> list[Path]:
    """County totals -> metro-year with counties_to_cbsa(); save with write_interim(df, SOURCE, "msa_year")."""
    raise NotImplementedError("transform")


def run(years: list[int] | None = None, force: bool = False) -> list[Path]:
    years = list(years or config.YEARS)
    return transform(download(years, force=force), years)
