"""FDIC Summary of Deposits (SOD): each bank's branch deposits by county, as of June 30.

Outputs:
  data/interim/bank_msa_year/sod.parquet   keys: rssd_id, cbsa_code, year   measures: sod_*
  data/interim/msa_year/sod.parquet        keys: cbsa_code, year            measures: sod_*

bank_msa_year is the bridge that connects bank-level Call Report data to metros.

Starting points (verify before relying on them):
  - Branch-level fields: RSSDID (bank), CERT, YEAR, STCNTYBR (branch county FIPS),
    DEPSUMBR (branch deposits, in $1,000s: convert to whole dollars).
"""
from __future__ import annotations

from pathlib import Path

from src import config
from src.crosswalk import counties_to_cbsa  # noqa: F401
from src.utils import fetch, write_interim  # noqa: F401

SOURCE = "sod"


def download(years: list[int], force: bool = False) -> list[Path]:
    """Pull SOD branch data for each year into data/raw/sod/ with fetch(url, SOURCE)."""
    raise NotImplementedError("download")


def transform(paths: list[Path], years: list[int]) -> list[Path]:
    """Branch rows -> bank x metro x year and metro x year; save both with write_interim()."""
    raise NotImplementedError("transform")


def run(years: list[int] | None = None, force: bool = False) -> list[Path]:
    years = list(years or config.YEARS)
    return transform(download(years, force=force), years)
