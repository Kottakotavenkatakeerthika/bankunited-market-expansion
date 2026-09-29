"""BEA regional accounts and BLS labor data by county.

Outputs:
  data/interim/msa_year/bea.parquet   keys: cbsa_code, year   measures: bea_*
  data/interim/msa_year/bls.parquet   keys: cbsa_code, year   measures: bls_*

Starting points (verify before relying on them):
  - BEA Regional API (BEA_API_KEY in .env): county tables such as CAINC1 (personal
    income) and CAGDP (GDP). Pull counties rather than BEA's own metro totals, so
    every source uses the same delineation.
  - BLS QCEW annual averages by county (open-data files or API).
  - Rates such as unemployment can't be summed across counties: aggregate the
    counts (unemployed, labor force) with counties_to_cbsa(), then divide.

Availability (Data Source Log, Bhavana, 2026-09-28):
  - BEA GDP by county, with industry detail: 2001-2024
  - BEA personal income by county (wages, proprietors' income, dividends,
    interest, rents): years still to confirm, likely 1969 onward
    Source page: https://www.bea.gov/data/by-place-county-metro-local
  - BLS LAUS (labor force, employment, unemployment, unemployment rate):
    1990-2025, monthly back to 1990. Source page: https://www.bls.gov/lau/
  - BLS QCEW (employers, jobs, total and average wages, by industry):
    1990-2025 with full NAICS detail; partial 1975-1989 and 2026.
    Source page: https://www.bls.gov/cew/
  - 1990-2025 is the reliable range for both LAUS and QCEW.
"""
from __future__ import annotations

from pathlib import Path

from src import config
from src.crosswalk import counties_to_cbsa  # noqa: F401
from src.utils import fetch, save_raw, write_interim  # noqa: F401

SOURCE_BEA = "bea"
SOURCE_BLS = "bls"


def download(years: list[int], force: bool = False) -> list[Path]:
    """Pull BEA and BLS county data into data/raw/bea/ and data/raw/bls/."""
    raise NotImplementedError("download")


def transform(paths: list[Path], years: list[int]) -> list[Path]:
    """County rows -> metro-year; save with write_interim(df, SOURCE_BEA or SOURCE_BLS, "msa_year")."""
    raise NotImplementedError("transform")


def run(years: list[int] | None = None, force: bool = False) -> list[Path]:
    years = list(years or config.YEARS)
    return transform(download(years, force=force), years)
