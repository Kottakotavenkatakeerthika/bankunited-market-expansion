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

import json
from pathlib import Path

import pandas as pd

from src import config
from src.crosswalk import to_parent_cbsa
from src.utils import fetch, normalize_code, write_interim

SOURCE = "fred"

VALID_ANNUALIZE = {"mean", "sum", "last"}


def _load_series_list() -> pd.DataFrame:
    if not config.FRED_SERIES.exists():
        raise FileNotFoundError(f"fred: {config.FRED_SERIES} doesn't exist; add at least one series row first")
    series = pd.read_csv(config.FRED_SERIES, dtype=str)
    required = ["series_id", "cbsa_code", "column", "annualize"]
    missing = [col for col in required if col not in series.columns]
    if missing:
        raise ValueError(f"fred_series.csv is missing columns: {missing}")
    bad_annualize = ~series["annualize"].isin(VALID_ANNUALIZE)
    if bad_annualize.any():
        bad = series.loc[bad_annualize, ["series_id", "annualize"]].to_dict("records")
        raise ValueError(f"fred_series.csv has an unrecognized 'annualize' value: {bad}; expected one of {VALID_ANNUALIZE}")
    return series


def download(years: list[int], force: bool = False) -> list[Path]:
    """Pull every series in fred_series.csv into data/raw/fred/ with fetch(url, SOURCE, params=...)."""
    series = _load_series_list()
    paths = []
    for series_id in series["series_id"].unique():
        params = {
            "series_id": series_id,
            "api_key": config.FRED_API_KEY,
            "file_type": "json",
        }
        path = fetch(
            "https://api.stlouisfed.org/fred/series/observations",
            SOURCE,
            filename=f"{series_id}.json",
            params=params,
            force=force,
            notes=f"FRED series {series_id}, all observations",
        )
        paths.append(path)
    return paths


def _annual_value(values: pd.Series, how: str) -> float:
    if how == "mean":
        return values.mean()
    if how == "sum":
        return values.sum()
    return values.sort_index().iloc[-1]  # "last"


def _read_one_series(path: Path, years: list[int]) -> pd.DataFrame:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    observations = payload.get("observations")
    if not observations:
        raise ValueError(f"{path.name}: no observations in the FRED response; check the series ID and API key")
    obs = pd.DataFrame(observations)
    obs = obs[obs["value"] != "."]  # FRED's placeholder for a missing observation
    obs["value"] = pd.to_numeric(obs["value"], errors="coerce")
    obs["date"] = pd.to_datetime(obs["date"])
    obs["year"] = obs["date"].dt.year
    return obs[obs["year"].isin(years)][["year", "value"]]


def transform(paths: list[Path], years: list[int]) -> list[Path]:
    """Observations -> annual values per metro; save with write_interim(df, SOURCE, "msa_year")."""
    series = _load_series_list()
    by_series_id = {path.stem: path for path in paths if path.parent.name == SOURCE}

    rows = []
    for _, meta in series.iterrows():
        series_id = meta["series_id"]
        if series_id not in by_series_id:
            raise ValueError(f"fred: no downloaded file for series {series_id}; did download() run first?")
        obs = _read_one_series(by_series_id[series_id], years)
        annual = obs.groupby("year")["value"].apply(lambda v: _annual_value(v, meta["annualize"]))
        for year, value in annual.items():
            rows.append({"cbsa_code": meta["cbsa_code"], "year": year, "column": meta["column"], "value": value})

    long_form = pd.DataFrame(rows)
    long_form["cbsa_code"] = to_parent_cbsa(long_form["cbsa_code"])
    wide = long_form.pivot_table(index=["cbsa_code", "year"], columns="column", values="value").reset_index()
    wide.columns.name = None

    output_path = write_interim(wide, SOURCE, "msa_year")
    return [output_path]


def run(years: list[int] | None = None, force: bool = False) -> list[Path]:
    years = list(years or config.YEARS)
    return transform(download(years, force=force), years)


if __name__ == "__main__":
    run()