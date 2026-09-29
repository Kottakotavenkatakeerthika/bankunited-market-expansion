"""FRED series for metros, listed in data/reference/fred_series.csv.

Output:  data/interim/msa_year/fred.parquet   keys: cbsa_code, year   measures: fred_*

Starting points (verify before relying on them):
  - API (FRED_API_KEY in .env): https://api.stlouisfed.org/fred/series/observations
    with params series_id, api_key, and file_type=json. fetch() keeps the key out
    of the manifest.
  - Add one row per series to fred_series.csv: the metro it belongs to, the column
    it becomes, and how to annualize it (mean, sum, or last). If a series is only
    published for a Metropolitan Division, map it with to_parent_cbsa().
  - Some FRED series carry a third-party copyright; check the series notes before
    committing its data to this public repo.

Availability (Data Source Log, Bhavana, 2026-09-28):
  - Checked: CHAR737URN, the Charlotte metro unemployment rate, monthly and not
    seasonally adjusted, Jan 1990 - Jul 2026, tagged "Public Domain: Citation
    Requested". It's the first row in data/reference/fred_series.csv.
  - The same measure exists for Mecklenburg, Gaston, Cabarrus, Union, and Anson counties.
"""
from __future__ import annotations

from pathlib import Path

from src import config
from src.crosswalk import to_parent_cbsa  # noqa: F401
from src.utils import fetch, write_interim  # noqa: F401

SOURCE = "fred"


def download(years: list[int], force: bool = False) -> list[Path]:
    """Pull every series in fred_series.csv into data/raw/fred/ with fetch(url, SOURCE, params=...)."""
    raise NotImplementedError("download")


def transform(paths: list[Path], years: list[int]) -> list[Path]:
    """Observations -> annual values per metro; save with write_interim(df, SOURCE, "msa_year")."""
    raise NotImplementedError("transform")


def run(years: list[int] | None = None, force: bool = False) -> list[Path]:
    years = list(years or config.YEARS)
    return transform(download(years, force=force), years)
