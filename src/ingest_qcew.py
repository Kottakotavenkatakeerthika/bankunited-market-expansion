"""BLS QCEW by industry: private-sector establishments, employment and wages, by metro and industry.

Output:  data/interim/msa_industry_year/bls.parquet   keys: cbsa_code, industry_code, year   measures: bls_*
         data/interim/us_industry_year/bls.parquet    keys: industry_code, year              measures: bls_*

Source: the QCEW annual-by-area ZIPs (<YYYY>_annual_by_area.zip) that ingest_bea_bls.py already
downloaded into data/raw/bls/. This module downloads nothing and logs nothing new in the manifest.

Rows read: private ownership (own_code 5) at three industry levels of BLS's agglvl_code:
  71  the private total (industry_code 10)
  73  the 11 supersectors (1011-1013, 1021-1027, 1029; 1029 is Unclassified)
  74  the 20 two-digit NAICS sectors (11, 21, 22, 23, 31-33, 42, 44-45, 48-49, 51, ..., 81, 99)
Sector codes 31-33, 44-45 and 48-49 are recoded to 31, 44 and 48, as in msa_naics_year. Five sectors (23, 31,
51, 81 and 99) repeat a supersector's numbers exactly (1012, 1013, 1022, 1027 and 1029); both rows are kept.

A county row with disclosure_code N is suppressed: BLS shows its employment and wages as 0, but the values are not
published. They become empty, never 0, and the establishment count (which BLS does publish) is kept. A metro's
value is the sum of its counties' published values, so a metro with a suppressed county is an undercount;
bls_qcew_private_counties_reported_count (employment and wages both published) and
bls_qcew_private_counties_suppressed_count say how many counties were in and out. A county with no row at all is
in neither count. A metro whose counties are all suppressed has empty employment and wages.

The U.S. rows come from the file for area US000 inside each ZIP, so a location quotient can be computed.

Only counties in the crosswalk's metros are read. Connecticut's metros have no rows for 2015-2023: BLS reports
Connecticut under its old county codes until 2024, and the crosswalk maps only the planning regions.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pandas as pd

from src import config
from src.crosswalk import load_crosswalk
from src.utils import normalize_code, write_interim

SOURCE = "bls"
RAW_SOURCE = "bls"  # the QCEW ZIPs live in data/raw/bls/, put there by ingest_bea_bls.py
PRIVATE_OWNERSHIP = "5"  # own_code 5 = private
COUNTY_AREA_RE = re.compile(r"^\d{2}(?!000)\d{3}$")  # 5-digit county codes, not state (37000) or metro (C1674)
US_AREA = "US000"

# BLS agglvl_code (county files) -> level. The U.S. file uses 11, 13 and 14 for the same three levels.
LEVELS = {"71": "total", "73": "supersector", "74": "sector",
          "11": "total", "13": "supersector", "14": "sector"}
SECTOR_RECODE = {"31-33": "31", "44-45": "44", "48-49": "48"}
SUPERSECTORS = ["1011", "1012", "1013", "1021", "1022", "1023", "1024", "1025", "1026", "1027", "1029"]
SECTORS = ["11", "21", "22", "23", "31", "42", "44", "48", "51", "52", "53", "54", "55", "56", "61", "62",
           "71", "72", "81", "99"]
TOTAL = "10"
INDUSTRY_CODES = [TOTAL, *SUPERSECTORS, *SECTORS]  # the 32 codes the tables may hold
INDUSTRY_LEVELS = {TOTAL: "total", **{code: "supersector" for code in SUPERSECTORS},
                   **{code: "sector" for code in SECTORS}}

READ_COLUMNS = ["area_fips", "own_code", "industry_code", "agglvl_code", "disclosure_code",
                "annual_avg_estabs_count", "annual_avg_emplvl", "total_annual_wages"]
MEASURES = ["bls_qcew_private_establishments_count", "bls_qcew_private_employment_count",
            "bls_qcew_private_total_wages_usd"]
COUNT_COLUMNS = ["bls_qcew_private_counties_reported_count", "bls_qcew_private_counties_suppressed_count"]
LEVEL_COLUMN = "bls_industry_level"


# --------------------------------------------------------------- download
def download(years: list[int], force: bool = False) -> list[Path]:
    """The QCEW ZIPs ingest_bea_bls.py already put in data/raw/bls/. Nothing is downloaded here."""
    paths = []
    for year in years:
        path = config.RAW / RAW_SOURCE / f"{year}_annual_by_area.zip"
        if not path.exists():
            raise FileNotFoundError(f"qcew: {path} is missing; run ingest_bea_bls first, it downloads the QCEW files")
        paths.append(path)
    return paths


# --------------------------------------------------------------- transform
def _industry_rows(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    """One area's private total, supersector and sector rows, with numbers and the suppression flag."""
    df.columns = [c.strip().lower() for c in df.columns]
    absent = [c for c in READ_COLUMNS if c not in df.columns]
    if absent:
        raise ValueError(f"{source_name} is missing expected columns {absent}")
    for column in ("own_code", "industry_code", "agglvl_code"):
        df[column] = df[column].str.strip()
    rows = df.loc[(df["own_code"] == PRIVATE_OWNERSHIP) & df["agglvl_code"].isin(LEVELS)].copy()
    rows["industry_code"] = rows["industry_code"].replace(SECTOR_RECODE)
    rows[LEVEL_COLUMN] = rows["agglvl_code"].map(LEVELS)
    unknown = sorted(set(rows["industry_code"]) - set(INDUSTRY_CODES))
    wrong_level = rows[rows["industry_code"].map(INDUSTRY_LEVELS) != rows[LEVEL_COLUMN]]
    if unknown or len(wrong_level):
        raise ValueError(f"{source_name}: industry codes {unknown or wrong_level['industry_code'].unique().tolist()} "
                         f"are not in the expected 32; has BLS changed the layout?")
    rows["suppressed"] = rows["disclosure_code"].fillna("").str.strip() == "N"
    numbers = {"annual_avg_estabs_count": "bls_qcew_private_establishments_count",
               "annual_avg_emplvl": "bls_qcew_private_employment_count",
               "total_annual_wages": "bls_qcew_private_total_wages_usd"}
    for raw, name in numbers.items():
        rows[name] = pd.to_numeric(rows[raw], errors="coerce")
    for name in MEASURES[1:]:  # employment and wages of a suppressed row are shown as 0 but not published
        rows[name] = rows[name].mask(rows["suppressed"])
    keep = ["area_fips", "industry_code", LEVEL_COLUMN, "suppressed", *MEASURES]
    return rows[keep].drop_duplicates(["area_fips", "industry_code"])


def _read_one_year(path: Path, year: int, counties: set[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One <YYYY>_annual_by_area.zip -> (county rows for the given counties, the U.S. rows)."""
    county_rows, us_rows = [], None
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            stem = Path(name).stem
            area = stem.split(" ")[1] if " " in stem else ""
            is_us = area == US_AREA
            if not is_us and not (COUNTY_AREA_RE.match(area) and area in counties):
                continue
            with archive.open(name) as handle:
                df = pd.read_csv(handle, dtype=str, usecols=lambda c: c.strip().lower() in READ_COLUMNS)
            rows = _industry_rows(df, f"{path.name}: {name}")
            if is_us:
                us_rows = rows
            else:
                county_rows.append(rows)
    if us_rows is None:
        raise ValueError(f"{path.name}: no U.S. file ({US_AREA}) found inside; has BLS changed the layout?")
    county = pd.concat(county_rows, ignore_index=True) if county_rows else pd.DataFrame(
        columns=["area_fips", "industry_code", LEVEL_COLUMN, "suppressed", *MEASURES])
    county["year"] = year
    us_rows = us_rows.drop(columns=["area_fips", "suppressed"])
    us_rows["year"] = year
    return county, us_rows


def counties_to_metro_industries(county_level: pd.DataFrame) -> pd.DataFrame:
    """Sum county industry rows to metros by (year, industry), with counts of reporting and suppressed counties.

    Like counties_to_cbsa, a missing value adds nothing and a metro whose counties are all missing stays missing,
    never 0. Unlike it, the counts show how many counties the sum is built from.
    """
    xwalk = load_crosswalk(metro_only=True)[["county_fips", "cbsa_code"]]
    data = county_level.copy()
    data["county_fips"] = normalize_code(data["area_fips"], 5)
    merged = data.merge(xwalk, on="county_fips", how="inner")
    merged["bls_qcew_private_counties_reported_count"] = (
        merged["bls_qcew_private_employment_count"].notna() & merged["bls_qcew_private_total_wages_usd"].notna()
    ).astype(int)
    merged["bls_qcew_private_counties_suppressed_count"] = merged["suppressed"].astype(int)
    keys = ["cbsa_code", "industry_code", "year"]
    sums = merged.groupby(keys, as_index=False)[MEASURES].sum(min_count=1)
    counts = merged.groupby(keys, as_index=False)[COUNT_COLUMNS].sum()
    out = sums.merge(counts, on=keys, validate="one_to_one")
    out[LEVEL_COLUMN] = out["industry_code"].map(INDUSTRY_LEVELS)
    return out


def transform(paths: list[Path], years: list[int]) -> list[Path]:
    """County and U.S. rows -> msa_industry_year and us_industry_year, saved with write_interim(df, SOURCE, table)."""
    if not paths:
        raise ValueError("qcew: no raw files to transform; did download() run first?")
    counties = set(load_crosswalk(metro_only=True)["county_fips"])
    county_frames, us_frames = [], []
    for path in sorted(paths):
        match = re.search(r"(\d{4})_annual_by_area\.zip$", path.name)
        if not match or int(match.group(1)) not in years:
            continue
        county, us = _read_one_year(path, int(match.group(1)), counties)
        county_frames.append(county)
        us_frames.append(us)
    if not county_frames:
        raise ValueError(f"qcew: none of the files is a QCEW annual-by-area ZIP for {years}")
    county_level = pd.concat(county_frames, ignore_index=True)
    if county_level.empty:
        raise ValueError("qcew: no private county rows found; check the required columns against the QCEW file schema")

    metro_level = counties_to_metro_industries(county_level)
    suppressed = metro_level[metro_level["bls_qcew_private_counties_suppressed_count"] > 0]
    print(f"[qcew] msa_industry_year: {len(metro_level):,} metro-industry-years, {len(suppressed):,} with at least "
          f"one suppressed county (their employment and wages are undercounts)")
    us_level = pd.concat(us_frames, ignore_index=True)
    return [write_interim(metro_level, SOURCE, "msa_industry_year"),
            write_interim(us_level, SOURCE, "us_industry_year")]


def run(years: list[int] | None = None, force: bool = False) -> list[Path]:
    years = list(years or config.YEARS)
    return transform(download(years, force=force), years)


if __name__ == "__main__":
    run()
