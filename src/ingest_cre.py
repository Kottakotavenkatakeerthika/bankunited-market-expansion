"""Commercial real estate (CRE) activity from Census County Business Patterns: real estate (NAICS 531)
and nonresidential building construction (NAICS 2362), by county rolled up to metros.

Output:  data/interim/msa_year/cre.parquet    keys: cbsa_code, year    measures: cre_*

Primary source: the CBP county ZIPs that ingest_census.py already downloaded into data/raw/cbp/
(cbp<YY>co.zip). Fallback source: the BLS QCEW county files that ingest_bea_bls.py downloaded into
data/raw/bls/ (<YYYY>_annual_by_area.zip). This module downloads nothing and logs nothing new in the
manifest.

These are proxies for CRE activity, not CRE itself: NAICS 531 includes residential lessors, and the
measures are business counts, employment and payroll, not vacancy, rent or transactions.
Establishment counts are the primary measure.

QCEW fallback: for each county, year, industry and measure, the value comes from CBP when CBP has one.
Where CBP has none (no row, withheld, or 2024, because CBP has no 2024 file), it comes from QCEW
private-ownership rows (own_code 5; local government, own_code 3, is ignored):
annual_avg_estabs_count, annual_avg_emplvl and total_annual_wages (already whole dollars), matched on
industry_code 531 and 2362. A CBP value is never overwritten, and a missing value never becomes 0.
A QCEW row with disclosure_code N is suppressed: its employment and wages are shown as 0 but mean
missing, so they are set to NaN; its establishment count is still published and is kept.
cre_<industry>_qcew_fallback_counties_count is how many of the metro's counties had their
establishments from QCEW. Only counties in the crosswalk's metros are read from QCEW.
Caution: QCEW counts differently from CBP (for Charlotte 2023, about 11% higher on real estate
establishments, 38% on nonresidential construction establishments and 19% on payroll), and 2024 is QCEW
only, so a change from 2023 to 2024 is partly a change of source, not growth.

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
  - cre_<industry>_counties_reported_count is how many of the metro's counties had a usable CBP row
    (establishments, employment and payroll all published by CBP; QCEW fills do not count here, so it
    is 0 for 2024). Establishments can be built from more counties than that, because EST is published
    even when EMP and AP are withheld.

Payroll is annual payroll (AP, reported in $1,000s) converted to whole dollars.
NAICS version: not recorded in the files; confirm before treating 2015-2023 as one consistent series.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pandas as pd

from src import config
from src.crosswalk import counties_to_cbsa, load_crosswalk
from src.utils import normalize_code, write_interim

SOURCE = "cre"
CBP_SOURCE = "cbp"  # the raw files live in data/raw/cbp/, put there by ingest_census.py

# CBP's county file for a given year isn't published until more than a year
# after that year ends; 2023 is the most recent one available as of this writing.
# Later years are filled from QCEW only.
LATEST_AVAILABLE_YEAR = 2023
QCEW_SOURCE = "bls"  # QCEW zips live in data/raw/bls/, put there by ingest_bea_bls.py

# column prefix -> CBP NAICS code as written in the county files
INDUSTRIES = {
    "real_estate": "531///",
    "nonres_construction": "2362//",
}
QCEW_INDUSTRY_CODES = {"real_estate": "531", "nonres_construction": "2362"}
QCEW_PRIVATE_OWNERSHIP = "5"  # own_code 5 = private; 3 = local government, ignored
COUNTY_AREA_RE = re.compile(r"^\d{2}(?!000)\d{3}$")  # 5-digit county codes, not state (37000) or metro (C1674)
MEASURES = ("establishments_count", "employment_count", "payroll_usd")
ALL_INDUSTRY_NAICS = "------"
WITHHELD_FLAGS = {"D", "S"}  # D: withheld to avoid disclosure; S: withheld, doesn't meet publication standards

VALUE_COLUMNS = [
    f"{SOURCE}_{industry}_{measure}"
    for industry in INDUSTRIES
    for measure in (*MEASURES, "counties_reported_count", "qcew_fallback_counties_count")
]


def download(years: list[int], force: bool = False) -> list[Path]:
    """Find the CBP county ZIPs (years CBP has published) and the QCEW ZIPs (every year) already on disk.

    Nothing is downloaded (force is unused).
    """
    paths = []
    for year in years:
        if year > LATEST_AVAILABLE_YEAR:
            print(f"[cre] {year}: CBP hasn't published past {LATEST_AVAILABLE_YEAR}; values come from QCEW only")
        else:
            path = config.RAW / CBP_SOURCE / f"cbp{year % 100:02d}co.zip"
            if not path.exists():
                raise FileNotFoundError(f"cre: {path} is missing; run ingest_census first, it downloads the CBP county files")
            paths.append(path)
        qcew = config.RAW / QCEW_SOURCE / f"{year}_annual_by_area.zip"
        if not qcew.exists():
            raise FileNotFoundError(f"cre: {qcew} is missing; run ingest_bea_bls first, it downloads the QCEW files")
        paths.append(qcew)
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


def _empty_cbp() -> pd.DataFrame:
    """No CBP files given (every requested year is QCEW-only): an empty frame with the CBP layout."""
    columns = {"county_fips": pd.Series(dtype="string"), "year": pd.Series(dtype="int64")}
    for industry in INDUSTRIES:
        for measure in (*MEASURES, "counties_reported_count"):
            columns[f"{SOURCE}_{industry}_{measure}"] = pd.Series(dtype="float64")
        columns[f"{industry}_absent"] = pd.Series(dtype="bool")
        columns[f"{industry}_withheld"] = pd.Series(dtype="bool")
    return pd.DataFrame(columns)


def _read_qcew_year(path: Path, year: int, counties: set[str]) -> pd.DataFrame:
    """Read one <YYYY>_annual_by_area.zip: private-ownership 531 and 2362 rows for the given counties.

    Returns one row per county with cre_<industry>_<measure> columns. A suppressed row (disclosure_code N)
    keeps its establishment count; its employment and wages, shown as 0, become NaN.
    """
    columns = ["area_fips", "own_code", "industry_code", "disclosure_code",
               "annual_avg_estabs_count", "annual_avg_emplvl", "total_annual_wages"]
    frames = []
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            stem = Path(name).stem
            area = stem.split(" ")[1] if " " in stem else ""
            if not COUNTY_AREA_RE.match(area) or area not in counties:
                continue
            with archive.open(name) as handle:
                df = pd.read_csv(handle, dtype=str)
            df.columns = [c.strip().lower() for c in df.columns]
            absent = [c for c in columns if c not in df.columns]
            if absent:
                raise ValueError(f"{path.name}: {name} is missing expected columns {absent}")
            df["industry_code"] = df["industry_code"].str.strip()
            df["own_code"] = df["own_code"].str.strip()
            keep = (df["own_code"] == QCEW_PRIVATE_OWNERSHIP) & df["industry_code"].isin(QCEW_INDUSTRY_CODES.values())
            frames.append(df.loc[keep, columns])
    if not frames or not any(len(f) for f in frames):
        return pd.DataFrame({"county_fips": pd.Series(dtype="string"), "year": pd.Series(dtype="int64")})
    rows = pd.concat(frames, ignore_index=True).drop_duplicates(["area_fips", "industry_code"])
    rows["county_fips"] = normalize_code(rows["area_fips"], 5)
    rows["suppressed"] = rows["disclosure_code"].fillna("").str.strip() == "N"
    result = pd.DataFrame(index=pd.Index(rows["county_fips"].drop_duplicates().to_numpy(), name="county_fips"))
    for industry, code in QCEW_INDUSTRY_CODES.items():
        part = rows.loc[rows["industry_code"] == code].set_index("county_fips")
        prefix = f"{SOURCE}_{industry}"
        result[f"{prefix}_establishments_count"] = pd.to_numeric(part["annual_avg_estabs_count"], errors="coerce")
        result[f"{prefix}_employment_count"] = pd.to_numeric(part["annual_avg_emplvl"], errors="coerce").mask(part["suppressed"])
        result[f"{prefix}_payroll_usd"] = pd.to_numeric(part["total_annual_wages"], errors="coerce").mask(part["suppressed"])
    result["year"] = year
    return result.reset_index()


def _fill_from_qcew(cbp: pd.DataFrame, qcew: pd.DataFrame) -> pd.DataFrame:
    """CBP values stay; QCEW fills only the measures CBP left missing, one measure at a time."""
    merged = cbp.merge(qcew, on=["county_fips", "year"], how="outer", suffixes=("", "__qcew"))
    for industry in INDUSTRIES:
        prefix = f"{SOURCE}_{industry}"
        for measure in MEASURES:
            col = f"{prefix}_{measure}"
            q = merged[f"{col}__qcew"] if f"{col}__qcew" in merged.columns else pd.Series(float("nan"), index=merged.index)
            merged[f"{col}__filled"] = merged[col].isna() & q.notna()
            merged[col] = merged[col].fillna(q)
        merged[f"{prefix}_qcew_fallback_counties_count"] = merged[f"{prefix}_establishments_count__filled"].astype(int)
        merged[f"{prefix}_counties_reported_count"] = merged[f"{prefix}_counties_reported_count"].fillna(0).astype(int)
        merged[f"{industry}_absent"] = merged[f"{industry}_absent"].fillna(True).astype(bool)
        merged[f"{industry}_withheld"] = merged[f"{industry}_withheld"].fillna(False).astype(bool)
    return merged


def transform(paths: list[Path], years: list[int]) -> list[Path]:
    """County rows -> metro-year with counties_to_cbsa(); save with write_interim(df, SOURCE, "msa_year")."""
    if not paths:
        raise ValueError("cre: no raw files to transform; did download() run first?")

    cbp_paths = [p for p in paths if re.search(r"cbp\d{2}co\.zip$", p.name)]
    qcew_paths = {}
    for path in paths:
        match = re.search(r"(\d{4})_annual_by_area\.zip$", path.name)
        if match:
            qcew_paths[int(match.group(1))] = path

    metro_counties = set(load_crosswalk(metro_only=True)["county_fips"])
    if cbp_paths:
        cbp = pd.concat([_read_one_year(path) for path in cbp_paths], ignore_index=True)
        cbp = cbp[cbp["year"].isin(years)]
    else:
        cbp = _empty_cbp()
    qcew_frames = [_read_qcew_year(path, year, metro_counties) for year, path in sorted(qcew_paths.items())
                   if year in years]
    qcew = pd.concat(qcew_frames, ignore_index=True) if qcew_frames else _read_qcew_year_empty()
    no_qcew = sorted(set(years) - set(qcew_paths))
    if no_qcew:
        print(f"[cre] no QCEW file for {no_qcew}: no fallback for those years")

    county_level = _fill_from_qcew(cbp, qcew)
    county_level = county_level[county_level["county_fips"].isin(metro_counties)]  # metro counties only

    for industry in INDUSTRIES:
        prefix = f"{SOURCE}_{industry}"
        absent = int(county_level[f"{industry}_absent"].sum())
        withheld = int(county_level[f"{industry}_withheld"].sum())
        print(f"[cre] {industry}: {len(county_level):,} metro county-years; CBP had no row for {absent:,} "
              f"and withheld employment or payroll for {withheld:,}")
        filled = {m: int(county_level[f"{prefix}_{m}__filled"].sum()) for m in MEASURES}
        still = {m: int(county_level[f"{prefix}_{m}"].isna().sum()) for m in MEASURES}
        print(f"[cre] {industry}: filled from QCEW {filled['establishments_count']:,} establishments, "
              f"{filled['employment_count']:,} employment, {filled['payroll_usd']:,} payroll county-years; "
              f"still missing {still['establishments_count']:,} / {still['employment_count']:,} / "
              f"{still['payroll_usd']:,} (left missing, never 0)")

    metro_level = counties_to_cbsa(
        county_level,
        value_cols=VALUE_COLUMNS,
        county_col="county_fips",
        by=("year",),
        metro_only=True,
    )
    output_path = write_interim(metro_level, SOURCE, "msa_year")
    return [output_path]


def _read_qcew_year_empty() -> pd.DataFrame:
    return pd.DataFrame({"county_fips": pd.Series(dtype="string"), "year": pd.Series(dtype="int64")})


def run(years: list[int] | None = None, force: bool = False) -> list[Path]:
    years = list(years or config.YEARS)
    return transform(download(years, force=force), years)


if __name__ == "__main__":
    run()
