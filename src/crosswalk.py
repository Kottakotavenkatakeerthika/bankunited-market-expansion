"""County -> CBSA crosswalk from one OMB delineation vintage (Census "List 1").

Map every source to metros through county FIPS with this crosswalk instead of
the metro codes a source ships with. Sources use different delineation years,
and some report large metros (Miami, Washington, Philadelphia) by Metropolitan
Division rather than by metro.

    python -m src.crosswalk      # download the delineation file and rebuild the crosswalk
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src import config
from src.utils import fetch, normalize_code

SOURCE = "omb_delineation"

# Census header text (lowercased) -> our column names
HEADERS = {
    "cbsa code": "cbsa_code",
    "metropolitan division code": "metro_division_code",
    "csa code": "csa_code",
    "cbsa title": "cbsa_title",
    "metropolitan/micropolitan statistical area": "cbsa_type",
    "metropolitan division title": "metro_division_title",
    "csa title": "csa_title",
    "county/county equivalent": "county_name",
    "state name": "state_name",
    "fips state code": "state_fips",
    "fips county code": "county_code",
    "central/outlying county": "central_outlying",
}
REQUIRED = ["cbsa_code", "cbsa_title", "cbsa_type", "state_fips", "county_code"]
COLUMNS = [
    "county_fips", "state_fips", "county_name", "state_name",
    "cbsa_code", "cbsa_title", "cbsa_type",
    "metro_division_code", "metro_division_title",
    "csa_code", "csa_title", "central_outlying",
]
TEXT_COLUMNS = ["county_name", "state_name", "cbsa_title", "cbsa_type",
                "metro_division_title", "csa_title", "central_outlying"]


def download_delineation(force: bool = False) -> Path:
    return fetch(config.DELINEATION_URL, SOURCE, force=force,
                 notes=f"OMB delineation, vintage {config.DELINEATION_VINTAGE}")


def parse_delineation(path) -> pd.DataFrame:
    """Read Census List 1 (title rows on top, footnotes at the bottom) into one row per county."""
    sheet = pd.read_excel(path, header=None, dtype=str)
    header_row = next(
        (i for i, row in sheet.iterrows()
         if any(isinstance(v, str) and v.strip().lower() == "cbsa code" for v in row)),
        None,
    )
    if header_row is None:
        raise ValueError(f"No 'CBSA Code' header row in {path}; has the file layout changed?")
    body = sheet.iloc[header_row + 1:].copy()
    body.columns = [v.strip().lower() if isinstance(v, str) else f"blank_{i}"
                    for i, v in enumerate(sheet.iloc[header_row])]
    body = body.rename(columns=HEADERS)
    missing = [col for col in REQUIRED if col not in body.columns]
    if missing:
        raise ValueError(f"Delineation file is missing expected columns: {missing}")
    body = body[[col for col in HEADERS.values() if col in body.columns]].copy()

    body["state_fips"] = normalize_code(body["state_fips"], 2)
    body["county_code"] = normalize_code(body["county_code"], 3)
    is_county = (body["state_fips"].str.fullmatch(r"\d{2}", na=False)
                 & body["county_code"].str.fullmatch(r"\d{3}", na=False))
    body = body.loc[is_county].copy()  # drops the footnote rows
    body["county_fips"] = body["state_fips"] + body["county_code"]
    body["cbsa_code"] = normalize_code(body["cbsa_code"], 5)
    if "metro_division_code" in body:
        body["metro_division_code"] = normalize_code(body["metro_division_code"], 5)
    if "csa_code" in body:
        body["csa_code"] = normalize_code(body["csa_code"], 3)
    for col in TEXT_COLUMNS:
        if col in body:
            body[col] = body[col].astype("string").str.strip()

    repeated = body["county_fips"].duplicated(keep=False)
    if repeated.any():
        raise ValueError(f"Counties listed in more than one CBSA: {body.loc[repeated, 'county_fips'].unique()[:5].tolist()}")
    for col in COLUMNS:
        if col not in body:
            body[col] = pd.NA
    return body[COLUMNS].sort_values("county_fips").reset_index(drop=True)


def build_crosswalk(force_download: bool = False) -> Path:
    """Download (or reuse) the delineation file and write data/reference/county_cbsa_xwalk.csv."""
    xwalk = parse_delineation(download_delineation(force=force_download))
    config.COUNTY_CBSA_XWALK.parent.mkdir(parents=True, exist_ok=True)
    xwalk.to_csv(config.COUNTY_CBSA_XWALK, index=False)
    metros = xwalk.loc[xwalk["cbsa_type"].str.startswith("Metropolitan", na=False), "cbsa_code"].nunique()
    print(f"[crosswalk] {len(xwalk):,} counties in {metros} metros (vintage {config.DELINEATION_VINTAGE})")
    return config.COUNTY_CBSA_XWALK


def load_crosswalk(metro_only: bool = True) -> pd.DataFrame:
    """The committed crosswalk with codes as strings. metro_only drops micropolitan areas."""
    xwalk = pd.read_csv(config.COUNTY_CBSA_XWALK, dtype=str)
    widths = {"county_fips": 5, "state_fips": 2, "cbsa_code": 5, "metro_division_code": 5, "csa_code": 3}
    for col, width in widths.items():
        xwalk[col] = normalize_code(xwalk[col], width)
    if metro_only:
        xwalk = xwalk[xwalk["cbsa_type"].str.startswith("Metropolitan", na=False)]
    return xwalk.reset_index(drop=True)


def to_parent_cbsa(codes) -> pd.Series:
    """Map Metropolitan Division codes to their metro's CBSA code; other codes pass through.

    For sources that only publish metro or division codes (some BLS and FRED series).
    When a source has counties, use counties_to_cbsa() instead.
    """
    xwalk = load_crosswalk(metro_only=True).dropna(subset=["metro_division_code"])
    parent = dict(zip(xwalk["metro_division_code"], xwalk["cbsa_code"]))
    codes = normalize_code(codes, 5)
    return codes.map(lambda code: pd.NA if pd.isna(code) else parent.get(code, code)).astype("string")


def counties_to_cbsa(df: pd.DataFrame, value_cols, county_col: str = "county_fips",
                     by=("year",), metro_only: bool = True) -> pd.DataFrame:
    """Sum county rows up to metros, keeping only counties that belong to a metro.

    For additive measures (counts, dollars) only. For rates or medians, aggregate
    the numerator and denominator separately, then divide. A metro whose counties
    are all missing stays missing instead of becoming 0.
    """
    xwalk = load_crosswalk(metro_only=metro_only)[["county_fips", "cbsa_code"]]
    data = df.copy()
    data["county_fips"] = normalize_code(data[county_col], 5)
    merged = data.merge(xwalk, on="county_fips", how="inner")
    keys = ["cbsa_code", *by]
    return merged.groupby(keys, as_index=False)[list(value_cols)].sum(min_count=1)


if __name__ == "__main__":
    build_crosswalk(force_download=True)
