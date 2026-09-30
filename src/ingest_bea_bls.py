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

Verify before relying on these (not yet confirmed the way Census CBP was):
  - BEA table/line codes: CAINC1 line 1 (total personal income, $1,000s) and
    CAGDP2 line 1 (all-industry GDP, current $1,000s). Not CAGDP1 line 1 or
    CAGDP9, which are real GDP in chained 2017 dollars. BEA offers far more
    detail (income components, GDP by industry) if the pod wants it later.
  - BLS QCEW: uses the "annual by area" bulk ZIP
    (https://www.bls.gov/cew/data/files/<YEAR>/csv/<YEAR>_annual_by_area.zip),
    one giant file per year covering every county, state, and MSA. Only
    county-coded files inside are read. Confirm this URL still resolves and
    the inner file naming hasn't changed before trusting the output.
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import pandas as pd

from src import config
from src.crosswalk import counties_to_cbsa
from src.utils import fetch, normalize_code, write_interim

SOURCE_BEA = "bea"
SOURCE_BLS = "bls"

BEA_LATEST_AVAILABLE_YEAR = 2024
LAUS_LATEST_AVAILABLE_YEAR = 2025
QCEW_LATEST_AVAILABLE_YEAR = 2025

BEA_TABLES = {
    "cainc1": {"TableName": "CAINC1", "LineCode": "1"},   # total personal income, $1,000s
    "cagdp2": {"TableName": "CAGDP2", "LineCode": "1"},   # all-industry GDP, current $1,000s
}


# --------------------------------------------------------------- download
def download(years: list[int], force: bool = False) -> list[Path]:
    """Pull BEA and BLS county data into data/raw/bea/ and data/raw/bls/."""
    paths = []
    paths += _download_bea(force=force)
    paths += _download_laus(years, force=force)
    paths += _download_qcew(years, force=force)
    return paths


def _download_bea(force: bool) -> list[Path]:
    paths = []
    for table_key, table_params in BEA_TABLES.items():
        params = {
            "UserID": config.BEA_API_KEY,
            "method": "GetData",
            "datasetname": "Regional",
            "GeoFips": "COUNTY",
            "Year": "ALL",
            "ResultFormat": "JSON",
            **table_params,
        }
        path = fetch(
            "https://apps.bea.gov/api/data/",
            SOURCE_BEA,
            filename=f"{table_key}.json",
            params=params,
            force=force,
            notes=f"BEA Regional API, table {table_params['TableName']}, all counties, all years",
        )
        paths.append(path)
    return paths


def _download_laus(years: list[int], force: bool) -> list[Path]:
    paths = []
    for year in years:
        if year > LAUS_LATEST_AVAILABLE_YEAR:
            print(f"[laus] skipping {year}: not published past {LAUS_LATEST_AVAILABLE_YEAR} yet")
            continue
        yy = f"{year % 100:02d}"
        filename = f"laucnty{yy}.xlsx"
        url = f"https://www.bls.gov/lau/{filename}"
        path = fetch(url, SOURCE_BLS, filename=filename, force=force,
                      notes=f"BLS LAUS county annual averages, {year}")
        paths.append(path)
    return paths


def _download_qcew(years: list[int], force: bool) -> list[Path]:
    paths = []
    for year in years:
        if year > QCEW_LATEST_AVAILABLE_YEAR:
            print(f"[qcew] skipping {year}: not published past {QCEW_LATEST_AVAILABLE_YEAR} yet")
            continue
        filename = f"{year}_annual_by_area.zip"
        url = f"https://www.bls.gov/cew/data/files/{year}/csv/{filename}"
        path = fetch(url, SOURCE_BLS, filename=filename, force=force,
                      notes=f"BLS QCEW annual-by-area bulk file, {year}")
        paths.append(path)
    return paths


# --------------------------------------------------------------- BEA transform
def _parse_bea_table(path: Path, measure_name: str) -> pd.DataFrame:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    results = payload.get("BEAAPI", {}).get("Results", {})
    if isinstance(results, list):
        results = results[0]
    rows = results.get("Data")
    if not rows:
        error = payload.get("BEAAPI", {}).get("Error")
        raise ValueError(f"{path.name}: no data returned from BEA API ({error or 'unknown error'})")

    frame = pd.DataFrame(rows)
    frame = frame.loc[frame["GeoFips"].str.fullmatch(r"\d{5}")]  # counties only, drop states/US
    frame["county_fips"] = normalize_code(frame["GeoFips"], 5)
    frame["year"] = pd.to_numeric(frame["TimePeriod"], errors="coerce").astype("Int64")
    frame[measure_name] = (
        pd.to_numeric(frame["DataValue"].str.replace(",", "", regex=False), errors="coerce") * 1000
    )
    return frame[["county_fips", "year", measure_name]].dropna(subset=["year"])


def _transform_bea(paths: list[Path], years: list[int]) -> Path:
    by_table = {path.stem: path for path in paths if path.parent.name == SOURCE_BEA}
    income = _parse_bea_table(by_table["cainc1"], "bea_personal_income_usd")
    gdp = _parse_bea_table(by_table["cagdp2"], "bea_gdp_usd")
    county_level = income.merge(gdp, on=["county_fips", "year"], how="outer")
    county_level = county_level[county_level["year"].isin(years)]

    metro_level = counties_to_cbsa(
        county_level,
        value_cols=["bea_personal_income_usd", "bea_gdp_usd"],
        county_col="county_fips",
        by=("year",),
        metro_only=True,
    )
    return write_interim(metro_level, SOURCE_BEA, "msa_year")


# --------------------------------------------------------------- BLS LAUS transform
def _read_one_laus_year(path: Path) -> pd.DataFrame:
    sheet = pd.read_excel(path, header=None, dtype=str)
    header_row = next(
        (i for i, row in sheet.iterrows()
         if any(isinstance(v, str) and v.strip().lower() == "laus code" for v in row)),
        None,
    )
    if header_row is None:
        raise ValueError(f"No 'LAUS Code' header row in {path.name}; has the file layout changed?")
    body = sheet.iloc[header_row + 1:].copy()
    body.columns = [v.strip() if isinstance(v, str) else f"blank_{i}"
                    for i, v in enumerate(sheet.iloc[header_row])]
    body = body.dropna(subset=["State FIPS Code", "County FIPS Code"])

    def clean_number(series):
        return pd.to_numeric(series.astype(str).str.replace(",", "", regex=False).str.strip(),
                              errors="coerce")

    return pd.DataFrame({
        "county_fips": normalize_code(body["State FIPS Code"], 2) + normalize_code(body["County FIPS Code"], 3),
        "year": pd.to_numeric(body["Year"], errors="coerce").astype("Int64"),
        "bls_labor_force_count": clean_number(body["Labor Force"]),
        "bls_employed_count": clean_number(body["Employed"]),
        "bls_unemployed_count": clean_number(body["Unemployed"]),
    }).dropna(subset=["year"])


def _transform_laus(paths: list[Path]) -> pd.DataFrame:
    laus_paths = [p for p in paths if p.name.startswith("laucnty")]
    county_level = pd.concat([_read_one_laus_year(p) for p in laus_paths], ignore_index=True)
    metro_level = counties_to_cbsa(
        county_level,
        value_cols=["bls_labor_force_count", "bls_employed_count", "bls_unemployed_count"],
        county_col="county_fips",
        by=("year",),
        metro_only=True,
    )
    metro_level["bls_unemployment_rate_pct"] = (
        metro_level["bls_unemployed_count"] / metro_level["bls_labor_force_count"] * 100
    )
    return metro_level


# --------------------------------------------------------------- BLS QCEW transform
COUNTY_AREA_RE = re.compile(r"^\d{2}(?!000)\d{3}$")  # county area codes: 5 digits (e.g. 37119), not 37000 (state) or C1234 (MSA)


def _read_one_qcew_year(path: Path, year: int) -> pd.DataFrame:
    rows = []
    with zipfile.ZipFile(path) as archive:
        county_files = [
            name for name in archive.namelist()
            if COUNTY_AREA_RE.match(Path(name).stem.split(" ")[1] if " " in Path(name).stem else "")
        ]
        if not county_files:
            raise ValueError(f"{path.name}: no county-level files found inside; has BLS changed the layout?")
        for name in county_files:
            with archive.open(name) as handle:
                df = pd.read_csv(handle, dtype=str)
            df.columns = [c.strip().lower() for c in df.columns]
            required = ["area_fips", "own_code", "industry_code", "annual_avg_emplvl", "total_annual_wages"]
            if any(col not in df.columns for col in required):
                continue
            total = df[(df["own_code"] == "0") & (df["industry_code"].str.strip() == "10")]
            if total.empty:
                continue
            rows.append({
                "county_fips": total["area_fips"].iloc[0],
                "year": year,
                "bls_qcew_employment_count": pd.to_numeric(total["annual_avg_emplvl"].iloc[0], errors="coerce"),
                "bls_qcew_total_wages_usd": pd.to_numeric(total["total_annual_wages"].iloc[0], errors="coerce"),
            })
    return pd.DataFrame(rows)


def _transform_qcew(paths: list[Path]) -> pd.DataFrame:
    qcew_paths = [p for p in paths if p.name.endswith("_annual_by_area.zip")]
    frames = []
    for path in qcew_paths:
        match = re.match(r"(\d{4})_annual_by_area\.zip$", path.name)
        if not match:
            continue
        frames.append(_read_one_qcew_year(path, int(match.group(1))))
    county_level = pd.concat(frames, ignore_index=True)
    if county_level.empty:
        raise ValueError("qcew: no county rows found across any year's file; check the required columns list against the actual QCEW file schema")
    return counties_to_cbsa(
        county_level,
        value_cols=["bls_qcew_employment_count", "bls_qcew_total_wages_usd"],
        county_col="county_fips",
        by=("year",),
        metro_only=True,
    )


# --------------------------------------------------------------- combine and run
def transform(paths: list[Path], years: list[int]) -> list[Path]:
    """County rows -> metro-year; save with write_interim(df, SOURCE_BEA or SOURCE_BLS, "msa_year")."""
    bea_path = _transform_bea(paths, years)

    laus = _transform_laus(paths)
    qcew = _transform_qcew(paths)
    bls_combined = laus.merge(qcew, on=["cbsa_code", "year"], how="outer")
    bls_path = write_interim(bls_combined, SOURCE_BLS, "msa_year")

    return [bea_path, bls_path]


def run(years: list[int] | None = None, force: bool = False) -> list[Path]:
    years = list(years or config.YEARS)
    return transform(download(years, force=force), years)


if __name__ == "__main__":
    run()