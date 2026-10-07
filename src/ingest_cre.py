"""Commercial real estate (CRE) activity from Census County Business Patterns: real estate (NAICS 531)
and nonresidential building construction (NAICS 2362), by county rolled up to metros.

Output:  data/interim/msa_year/cre.parquet    keys: cbsa_code, year    measures: cre_*

Reuses the CBP county ZIPs that ingest_census.py already downloaded into data/raw/cbp/
(cbp<YY>co.zip); this module downloads nothing and logs nothing new in the manifest.

Rows kept (county files, NAICS column): "531///" real estate, "2362//" nonresidential building
construction. County totals ("------") are read only to list which counties exist that year.

Withheld and missing cells (never turned into 0):
  - A county with no row for an industry in a year has nothing published: all its measures are NaN.
  - 2015-2017 files: a withheld cell has flag D or S in EMP_NF / AP_NF (EMPFLAG also holds a size
    class letter) and the value field holds a literal 0. Those EMP and AP values become NaN.
    EST is always published, so it is kept.
  - 2018 onward: no cells are withheld; Census adds noise instead (flags G, H, J) and the values are
    used as published.
  - When counties are summed to a metro, a missing county adds nothing (it is not a 0), and a metro
    whose counties are all missing for a measure stays NaN.
  - cre_<industry>_counties_reported_count is how many of the metro's counties had a usable row
    (establishments, employment and payroll all published). Establishments can be built from more
    counties than that, because EST is published even when EMP and AP are withheld.

Payroll is annual payroll (AP, reported in $1,000s) converted to whole dollars.
NAICS version: not recorded in the files; confirm before treating 2015-2023 as one consistent series.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pandas as pd

from src import config
from src.crosswalk import counties_to_cbsa
from src.utils import normalize_code, write_interim

SOURCE = "cre"
CBP_SOURCE = "cbp"  # the raw files live in data/raw/cbp/, put there by ingest_census.py

# CBP's county file for a given year isn't published until more than a year
# after that year ends; 2023 is the most recent one available as of this writing.
LATEST_AVAILABLE_YEAR = 2023

# column prefix -> CBP NAICS code as written in the county files
INDUSTRIES = {
    "real_estate": "531///",
    "nonres_construction": "2362//",
}
ALL_INDUSTRY_NAICS = "------"
WITHHELD_FLAGS = {"D", "S"}  # D: withheld to avoid disclosure; S: withheld, doesn't meet publication standards

VALUE_COLUMNS = [
    f"{SOURCE}_{industry}_{measure}"
    for industry in INDUSTRIES
    for measure in ("establishments_count", "employment_count", "payroll_usd", "counties_reported_count")
]


def download(years: list[int], force: bool = False) -> list[Path]:
    """Find the CBP county ZIPs already in data/raw/cbp/. Nothing is downloaded (force is unused)."""
    paths = []
    for year in years:
        if year > LATEST_AVAILABLE_YEAR:
            print(f"[cre] skipping {year}: CBP hasn't published past {LATEST_AVAILABLE_YEAR} yet")
            continue
        path = config.RAW / CBP_SOURCE / f"cbp{year % 100:02d}co.zip"
        if not path.exists():
            raise FileNotFoundError(f"cre: {path} is missing; run ingest_census first, it downloads the CBP county files")
        paths.append(path)
    return paths


def _read_one_year(path: Path) -> pd.DataFrame:
    """Read one cbp<YY>co.zip: one row per county, with the CRE measures for each industry."""
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
    required = ["FIPSTATE", "FIPSCTY", "NAICS", "EST", "EMP", "EMP_NF", "AP", "AP_NF"]
    missing = [c for c in required if c not in raw.columns]
    if missing:
        raise ValueError(f"{path.name}: missing expected columns {missing}")

    raw["NAICS"] = raw["NAICS"].str.strip()
    raw["county_fips"] = normalize_code(raw["FIPSTATE"], 2) + normalize_code(raw["FIPSCTY"], 3)

    # Every county in the file has an all-industry row, so it tells us which counties exist.
    counties = raw.loc[raw["NAICS"] == ALL_INDUSTRY_NAICS, "county_fips"].drop_duplicates()
    result = pd.DataFrame({"county_fips": counties.to_numpy(), "year": year}).set_index("county_fips")

    for industry, naics in INDUSTRIES.items():
        rows = raw.loc[raw["NAICS"] == naics].drop_duplicates("county_fips").set_index("county_fips")
        emp_withheld = rows["EMP_NF"].str.strip().isin(WITHHELD_FLAGS)
        if "EMPFLAG" in rows.columns:  # 2015-2017: a size-class letter means employment is withheld
            emp_withheld |= rows["EMPFLAG"].fillna("").str.strip() != ""
        ap_withheld = rows["AP_NF"].str.strip().isin(WITHHELD_FLAGS)

        establishments = pd.to_numeric(rows["EST"], errors="coerce")
        employment = pd.to_numeric(rows["EMP"], errors="coerce").mask(emp_withheld)
        payroll = (pd.to_numeric(rows["AP"], errors="coerce") * 1000).mask(ap_withheld)

        prefix = f"{SOURCE}_{industry}"
        result[f"{prefix}_establishments_count"] = establishments
        result[f"{prefix}_employment_count"] = employment
        result[f"{prefix}_payroll_usd"] = payroll
        result[f"{prefix}_counties_reported_count"] = (
            establishments.notna() & employment.notna() & payroll.notna()
        ).reindex(result.index, fill_value=False).astype(int)
        # Bookkeeping for the summary printed in transform(); not written to the output.
        result[f"{industry}_absent"] = ~result.index.isin(rows.index)
        result[f"{industry}_withheld"] = (emp_withheld | ap_withheld).reindex(result.index, fill_value=False)

    return result.reset_index()


def transform(paths: list[Path], years: list[int]) -> list[Path]:
    """County rows -> metro-year with counties_to_cbsa(); save with write_interim(df, SOURCE, "msa_year")."""
    if not paths:
        raise ValueError("cre: no raw files to transform; did download() run first?")

    county_level = pd.concat([_read_one_year(path) for path in paths], ignore_index=True)
    county_level = county_level[county_level["year"].isin(years)]

    for industry in INDUSTRIES:
        absent = int(county_level[f"{industry}_absent"].sum())
        withheld = int(county_level[f"{industry}_withheld"].sum())
        print(f"[cre] {industry}: {len(county_level):,} county-years, {absent:,} with no row (nothing published), "
              f"{withheld:,} with employment or payroll withheld; all left as missing, not 0")

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
