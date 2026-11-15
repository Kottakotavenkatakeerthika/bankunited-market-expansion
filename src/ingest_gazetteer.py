"""Census Gazetteer: each metro's internal point (latitude and longitude), for distances between metros.

Output:  data/interim/msa_year/gazetteer.parquet   keys: cbsa_code, year   measures: gazetteer_*

Source: the Census Bureau's Gazetteer file for Core Based Statistical Areas, one national file per year
(GAZETTEER_YEAR and GAZETTEER_URL in src/config.py):
  https://www2.census.gov/geo/docs/maps-data/data/gazetteer/<YYYY>_Gazetteer/<YYYY>_Gaz_cbsa_national.zip
  Record layout: https://www.census.gov/programs-surveys/geography/technical-documentation/records-layout/gaz-record-layouts.html

  - One row per CBSA, metro and micro (CBSA_TYPE 1 and 2), keyed by GEOID, the 5-digit CBSA code.
  - INTPTLAT and INTPTLONG are the area's internal point in decimal degrees: its centroid, or, where an
    irregular boundary puts the centroid outside the area, the point inside it nearest the centroid. It is
    a geographic point, not a population center.
  - The 2025 and later files are pipe-delimited with a GEOIDFQ column; 2024 and earlier are tab-delimited,
    with trailing spaces after the last header name. Both read the same way here. The text is UTF-8.

Checked 2026-11-12: the 2023, 2024, 2025 and 2026 files all list exactly the 393 metros of the July 2023
delineation (DELINEATION_VINTAGE), with the codes and titles in data/reference/msa_universe.csv. Points move
a little with boundary updates: by at most 3.1 miles for these metros between the 2024 and 2026 files.

The points are geography, like the delineation: the same value in every panel year, no row in
data/reference/release_dates.csv, and no limit in as-of runs.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd

from src import config
from src.utils import fetch, normalize_code, write_interim

SOURCE = "gazetteer"

METRO = "1"  # CBSA_TYPE: 1 metropolitan, 2 micropolitan
FIELDS = {"INTPTLAT": "gazetteer_internal_point_latitude", "INTPTLONG": "gazetteer_internal_point_longitude"}
VALUE_COLUMNS = list(FIELDS.values())


def download(years: list[int] | None = None, force: bool = False) -> list[Path]:
    """Pull the national CBSA file into data/raw/gazetteer/ with fetch(). One file covers every panel year."""
    return [fetch(config.GAZETTEER_URL, SOURCE, force=force,
                  notes=f"Census Gazetteer, Core Based Statistical Areas, {config.GAZETTEER_YEAR} file")]


def read_points(path) -> pd.DataFrame:
    """Every metro's internal point in a Gazetteer CBSA file: cbsa_code plus the two gazetteer_ columns."""
    name = Path(path).name
    with zipfile.ZipFile(path) as archive:
        members = [member for member in archive.namelist() if member.lower().endswith(".txt")]
        if len(members) != 1:
            raise ValueError(f"{name}: expected one .txt file inside, found {members}")
        text = archive.read(members[0]).decode("utf-8-sig")
    header = text.split("\n", 1)[0]
    raw = pd.read_csv(io.StringIO(text), sep="|" if "|" in header else "\t", dtype=str, keep_default_na=False)
    raw.columns = [column.strip() for column in raw.columns]
    missing = [column for column in ("GEOID", "CBSA_TYPE", *FIELDS) if column not in raw.columns]
    if missing:
        raise ValueError(f"{name}: missing expected columns {missing}")

    metros = raw.loc[raw["CBSA_TYPE"].str.strip() == METRO].reset_index(drop=True)
    points = pd.DataFrame({"cbsa_code": normalize_code(metros["GEOID"], 5)})
    for field, column in FIELDS.items():
        points[column] = pd.to_numeric(metros[field].str.strip(), errors="coerce")
    unreadable = points.loc[points[VALUE_COLUMNS].isna().any(axis=1), "cbsa_code"]
    if len(unreadable):
        raise ValueError(f"{name}: {len(unreadable)} metros without a readable point, e.g. {unreadable.head(3).tolist()}")
    repeated = points.loc[points["cbsa_code"].duplicated(), "cbsa_code"]
    if len(repeated):
        raise ValueError(f"{name}: metros listed more than once, e.g. {repeated.head(3).tolist()}")
    return points


def transform(paths: list[Path], years: list[int]) -> list[Path]:
    """Metro points, repeated for each panel year. Every metro in msa_universe.csv must have one."""
    if len(paths) != 1:
        raise ValueError(f"gazetteer: expected the one CBSA file, got {[Path(p).name for p in paths]}")
    points = read_points(paths[0])
    universe = normalize_code(pd.read_csv(config.MSA_UNIVERSE, dtype=str)["cbsa_code"].dropna(), 5)
    missing = sorted(set(universe) - set(points["cbsa_code"]))
    if missing:
        raise ValueError(
            f"gazetteer: {len(missing)} metros in msa_universe.csv have no point in the {config.GAZETTEER_YEAR} "
            f"file, e.g. {missing[:5]}. Set GAZETTEER_YEAR to a year whose metros match DELINEATION_VINTAGE "
            f"({config.DELINEATION_VINTAGE}).")
    panel = points.merge(pd.DataFrame({"year": list(years)}), how="cross")
    return [write_interim(panel[["cbsa_code", "year", *VALUE_COLUMNS]], SOURCE, "msa_year")]


def run(years: list[int] | None = None, force: bool = False) -> list[Path]:
    years = list(years or config.YEARS)
    return transform(download(years, force=force), years)


if __name__ == "__main__":
    run()
