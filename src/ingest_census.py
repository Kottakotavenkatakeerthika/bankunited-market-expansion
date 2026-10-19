"""Census County Business Patterns (CBP): establishments, employment, and payroll by county.

Output:  data/interim/msa_year/cbp.parquet         keys: cbsa_code, year               measures: cbp_*
         data/interim/msa_naics_year/cbp.parquet   keys: cbsa_code, naics_code, year   measures: cbp_*

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

Each county file is read once and used for both tables:
  - msa_year: the all-industry rows ("------"), plus two establishment size-class counts built from
    the same rows (see _size_class_counts).
  - msa_naics_year: the sector rows, where NAICS is two digits plus four dashes. naics_code is the first
    two characters, kept as text: "31" covers 31-33, "44" covers 44-45, "48" covers 48-49, and "99" is
    unclassified. A county-sector with no row was omitted by Census (fewer than 3 establishments from
    2017), so it is absent from the table, never 0.

Withheld cells in the sector table (never turned into 0):
  - 2015-2017 files: a withheld cell has flag D or S in EMP_NF / AP_NF (EMPFLAG also holds a letter) and
    the value field holds a literal 0. Those EMP and AP values become NaN. EST is always published.
  - 2018 onward: no cells are withheld; Census adds noise instead (flags G, H, J) and the values are
    used as published.
  - The all-industry rows keep the behavior they had before the sector table existed: their flags are
    not read.
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

ALL_INDUSTRY_NAICS = "------"
SECTOR_NAICS = re.compile(r"\d\d----")
WITHHELD_FLAGS = {"D", "S"}  # D: withheld to avoid disclosure; S: withheld, doesn't meet publication standards

VALUE_COLUMNS = [
    "cbp_establishments_count",
    "cbp_employment_count",
    "cbp_first_quarter_payroll_usd",
    "cbp_annual_payroll_usd",
]
SIZE_CLASS_COLUMNS = [
    "cbp_establishments_20plus_count",
    "cbp_establishments_20_249_count",
]
SECTOR_VALUE_COLUMNS = [
    "cbp_establishments_count",
    "cbp_employment_count",
    "cbp_annual_payroll_usd",
    "cbp_counties_reported_count",
]

# Establishment counts by employment size class. The smallest class is called N1_4 in the 2015 and 2016
# files and N<5 from 2017 on. N1000_1 to N1000_4 split N1000, so they are never added to it.
SMALLEST_CLASSES = ("N1_4", "N<5")
SMALL_CLASSES = ["N5_9", "N10_19"]
MID_CLASSES = ["N20_49", "N50_99", "N100_249"]
LARGE_CLASSES = ["N250_499", "N500_999", "N1000"]


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


def _read_raw(path: Path) -> tuple[int, pd.DataFrame]:
    """Read one cbp<YY>co.zip as text, with upper-case headers and a county_fips column."""
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

    raw["NAICS"] = raw["NAICS"].str.strip()
    raw["county_fips"] = normalize_code(raw["FIPSTATE"], 2) + normalize_code(raw["FIPSCTY"], 3)
    return year, raw


def _size_class_counts(rows: pd.DataFrame, name: str) -> pd.DataFrame:
    """Establishments with 20 or more employees, and with 20 to 249, for each row of a county file.

    'N' in a size class means Census suppressed the count; it is read as missing and treated as 0 only
    in the sums below. 20+ is EST minus the three small classes. If any of those is suppressed it can't
    be subtracted, so 20+ is the sum of the classes from 20_49 up instead (N1000_1 to N1000_4 are never
    added: they split N1000). The 20-249 count can therefore run short by up to 2 per suppressed cell.
    """
    smallest = next((c for c in SMALLEST_CLASSES if c in rows.columns), None)
    wanted = [*SMALL_CLASSES, *MID_CLASSES, *LARGE_CLASSES]
    present = [c for c in wanted if c in rows.columns]
    if smallest is None and not present:
        # No size-class fields at all (not true of any real CBP county file): leave both measures missing.
        print(f"[cbp] {name}: no size-class columns; the size-class counts are left missing")
        return pd.DataFrame({c: pd.Series(float("nan"), index=rows.index) for c in SIZE_CLASS_COLUMNS})
    absent = ([] if smallest else ["N1_4 or N<5"]) + [c for c in wanted if c not in rows.columns]
    if absent:
        raise ValueError(f"{name}: missing expected size-class columns {absent}")

    size = {c: pd.to_numeric(rows[c], errors="coerce") for c in [smallest, *wanted]}  # 'N' becomes NaN
    small = [size[smallest], *(size[c] for c in SMALL_CLASSES)]
    any_suppressed = pd.concat(small, axis=1).isna().any(axis=1)
    by_subtraction = pd.to_numeric(rows["EST"], errors="coerce") - sum(s.fillna(0) for s in small)
    by_summing = sum(size[c].fillna(0) for c in [*MID_CLASSES, *LARGE_CLASSES])
    mid = sum(size[c].fillna(0) for c in MID_CLASSES)
    return pd.DataFrame({
        "cbp_establishments_20plus_count": by_subtraction.where(~any_suppressed, by_summing),
        "cbp_establishments_20_249_count": mid,
    })


def _totals(year: int, raw: pd.DataFrame, name: str) -> pd.DataFrame:
    """The all-industry row of each county, with the size-class counts built from the same row."""
    totals = raw.loc[raw["NAICS"] == ALL_INDUSTRY_NAICS].copy()
    return pd.DataFrame({
        "county_fips": totals["county_fips"],
        "year": year,
        "cbp_establishments_count": pd.to_numeric(totals["EST"], errors="coerce"),
        "cbp_employment_count": pd.to_numeric(totals["EMP"], errors="coerce"),
        "cbp_first_quarter_payroll_usd": pd.to_numeric(totals["QP1"], errors="coerce") * 1000,
        "cbp_annual_payroll_usd": pd.to_numeric(totals["AP"], errors="coerce") * 1000,
        **_size_class_counts(totals, name),
    })


def _sectors(year: int, raw: pd.DataFrame) -> pd.DataFrame:
    """The sector rows (two digits plus four dashes) of each county; withheld 2015-2017 cells are missing."""
    rows = raw.loc[raw["NAICS"].str.fullmatch(SECTOR_NAICS)].copy()
    for column in ("EMP_NF", "AP_NF"):
        if column not in rows.columns:
            rows[column] = pd.NA
    emp_withheld = rows["EMP_NF"].fillna("").str.strip().isin(WITHHELD_FLAGS)
    if "EMPFLAG" in rows.columns:  # 2015-2017: a letter here means employment is withheld
        emp_withheld |= rows["EMPFLAG"].fillna("").str.strip() != ""
    ap_withheld = rows["AP_NF"].fillna("").str.strip().isin(WITHHELD_FLAGS)
    return pd.DataFrame({
        "county_fips": rows["county_fips"],
        "naics_code": rows["NAICS"].str[:2],
        "year": year,
        "cbp_establishments_count": pd.to_numeric(rows["EST"], errors="coerce"),
        "cbp_employment_count": pd.to_numeric(rows["EMP"], errors="coerce").mask(emp_withheld),
        "cbp_annual_payroll_usd": (pd.to_numeric(rows["AP"], errors="coerce") * 1000).mask(ap_withheld),
        "cbp_counties_reported_count": 1,  # this county has a row for the sector; the sum is the metro's count
    })


def _read_one_year(path: Path) -> pd.DataFrame:
    """Read one cbp<YY>co.zip and keep the all-industry total row for each county."""
    year, raw = _read_raw(path)
    return _totals(year, raw, path.name)


def transform(paths: list[Path], years: list[int]) -> list[Path]:
    """County rows -> metro-year and metro-sector-year with counties_to_cbsa(); save with write_interim()."""
    if not paths:
        raise ValueError("cbp: no raw files to transform; did download() run first?")

    totals, sectors = [], []
    for path in paths:
        year, raw = _read_raw(path)
        totals.append(_totals(year, raw, path.name))
        sectors.append(_sectors(year, raw))

    metro_level = counties_to_cbsa(
        pd.concat(totals, ignore_index=True),
        value_cols=[*VALUE_COLUMNS, *SIZE_CLASS_COLUMNS],
        county_col="county_fips",
        by=("year",),
        metro_only=True,
    )
    sector_level = counties_to_cbsa(
        pd.concat(sectors, ignore_index=True),
        value_cols=SECTOR_VALUE_COLUMNS,
        county_col="county_fips",
        by=("naics_code", "year"),
        metro_only=True,
    )
    return [write_interim(metro_level, SOURCE, "msa_year"),
            write_interim(sector_level, SOURCE, "msa_naics_year")]


def run(years: list[int] | None = None, force: bool = False) -> list[Path]:
    years = list(years or config.YEARS)
    return transform(download(years, force=force), years)


if __name__ == "__main__":
    run()
