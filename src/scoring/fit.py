"""Fit & Feasibility measures: how a metro relates to BankUnited's current footprint.

Not scored. The final score reports these as columns and can use them as filters ([fit] in the weights
files): a metro outside a filter keeps its score but gets no rank, exactly like the size floor.

Industry share: the percent of a metro's CBP employment in the industries selected in [fit.industries]
(true/false per two-digit sector), with the published all-industry total as the denominator. A selected
sector that CBP suppresses for a metro leaves its share blank; unselected sectors never matter. Rules carried
over from the industry-fit research in pull request 124 (docs/industry_fit_research.md).

Distance (T71): straight-line (great-circle) miles from each metro's Census Gazetteer internal point to the
nearest BankUnited market. BankUnited's markets are its SOD branch markets in the year being scored plus its
office-only markets (Atlanta, Charlotte, Houston), as of the run's date (src/market_attractiveness.py).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

LAT = "gazetteer_internal_point_latitude"    # msa_year, data-v0.6 (T71); the same value every year
LON = "gazetteer_internal_point_longitude"
EARTH_RADIUS_MILES = 3958.8
INDUSTRY_COLUMNS = ["industry_share", "industry_share_percentile", "industry_sectors_missing"]

# The 20 two-digit sectors in CBP (combined ranges use their first code: 31 = 31-33, 44 = 44-45, 48 = 48-49).
# 92 Public administration is not in CBP. Default selection = the High and Medium sectors of the original mapping.
CBP_SECTORS = {
    "11": "Agriculture, forestry, fishing and hunting", "21": "Mining, quarrying, and oil and gas extraction",
    "22": "Utilities", "23": "Construction", "31": "Manufacturing", "42": "Wholesale trade", "44": "Retail trade",
    "48": "Transportation and warehousing", "51": "Information", "52": "Finance and insurance",
    "53": "Real estate and rental and leasing", "54": "Professional, scientific, and technical services",
    "55": "Management of companies and enterprises", "56": "Administrative and support and waste management",
    "61": "Educational services", "62": "Health care and social assistance", "71": "Arts, entertainment, and recreation",
    "72": "Accommodation and food services", "81": "Other services", "99": "Industries not classified",
}
DEFAULT_INDUSTRIES = ["22", "23", "31", "42", "44", "48", "52", "53", "54", "61", "62"]

DISTANCE_COLUMNS = ["miles_to_nearest_bankunited_market", "nearest_bankunited_market", "is_bankunited_market"]


def miles_between(lat1, lon1, lat2, lon2):
    """Great-circle (haversine) distance in miles; inputs in decimal degrees; works on arrays."""
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(x, dtype=float)) for x in (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return EARTH_RADIUS_MILES * 2 * np.arcsin(np.sqrt(a))


def coordinates(msa_year: pd.DataFrame) -> pd.DataFrame | None:
    """One row per metro: cbsa_title, lat, lon. None if msa_year has no coordinate columns yet."""
    if LAT not in msa_year.columns or LON not in msa_year.columns:
        return None
    c = (msa_year.dropna(subset=[LAT, LON]).sort_values("year")
         .drop_duplicates("cbsa_code", keep="last").set_index("cbsa_code"))
    return pd.DataFrame({"cbsa_title": c["cbsa_title"], "lat": c[LAT].astype(float), "lon": c[LON].astype(float)})


def load_coordinates(root: Path) -> pd.DataFrame | None:
    path = Path(root) / "data" / "processed" / "msa_year.parquet"
    if not path.exists():
        return None
    cols = pd.read_parquet(path, columns=None).columns
    if LAT not in cols or LON not in cols:
        return None
    return coordinates(pd.read_parquet(path, columns=["cbsa_code", "cbsa_title", "year", LAT, LON]))


def distance_columns(index: pd.Index, coords: pd.DataFrame | None, markets: pd.Index) -> pd.DataFrame:
    """Distance to the nearest BankUnited market for every metro in index.

    Without coordinates (before data-v0.6) the distance columns are blank; is_bankunited_market is always set."""
    out = pd.DataFrame(index=index)
    out["is_bankunited_market"] = index.isin(markets)
    out["miles_to_nearest_bankunited_market"] = np.nan
    out["nearest_bankunited_market"] = pd.Series(pd.NA, index=index, dtype="string")
    if coords is None:
        return out[DISTANCE_COLUMNS]
    m = coords.reindex([c for c in markets if c in coords.index])
    here = coords.reindex(index)
    have = here["lat"].notna()
    if m.empty or not have.any():
        return out[DISTANCE_COLUMNS]
    d = miles_between(here.loc[have, "lat"].to_numpy()[:, None], here.loc[have, "lon"].to_numpy()[:, None],
                      m["lat"].to_numpy()[None, :], m["lon"].to_numpy()[None, :])
    nearest = d.argmin(axis=1)
    short = m["cbsa_title"].str.split(",").str[0].str.split("-").str[0]
    out.loc[have, "miles_to_nearest_bankunited_market"] = d.min(axis=1).round(1)
    out.loc[have, "nearest_bankunited_market"] = short.to_numpy()[nearest]
    return out[DISTANCE_COLUMNS]


def load_industry_inputs(root: Path) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """(msa_naics_year, msa_year totals) from data/processed, or None if either is missing."""
    proc = Path(root) / "data" / "processed"
    if not (proc / "msa_naics_year.parquet").exists() or not (proc / "msa_year.parquet").exists():
        return None
    sectors = pd.read_parquet(proc / "msa_naics_year.parquet", columns=["cbsa_code", "naics_code", "year",
                                                                        "cbp_employment_count"])
    totals = pd.read_parquet(proc / "msa_year.parquet", columns=["cbsa_code", "year", "cbp_employment_count"])
    return sectors, totals


def industry_share(index: pd.Index, sectors: pd.DataFrame, totals: pd.DataFrame, year: int,
                   selected: list[str]) -> pd.DataFrame:
    """Percent of each metro's CBP employment in the selected sectors, and its percentile.

    share = sum of the selected sectors' employment / the metro's published all-industry total x 100.
    Blank (with the missing codes listed) if any selected sector has no published employment for the metro,
    or if the total is missing or not positive. Percentile: 100 x (average rank - 1) / (count - 1) among
    metros with a share, higher share = higher percentile."""
    out = pd.DataFrame(index=index)
    s = sectors[sectors["year"] == int(year)].copy()
    s["naics_code"] = s["naics_code"].astype(str).str.strip().str.zfill(2)
    wide = s.pivot_table(index="cbsa_code", columns="naics_code", values="cbp_employment_count",
                         aggfunc="first").reindex(index=index, columns=selected)
    total = (totals[totals["year"] == int(year)].drop_duplicates("cbsa_code")
             .set_index("cbsa_code")["cbp_employment_count"].reindex(index).astype(float))
    have_all = wide.notna().all(axis=1)
    share = (100 * wide.sum(axis=1, min_count=1) / total).where(have_all & (total > 0))
    n = share.notna().sum()
    out["industry_share"] = share.round(6)
    out["industry_share_percentile"] = (100 * (share.rank(method="average") - 1) / (n - 1)) if n > 1 else np.nan
    missing = wide.isna().apply(lambda r: ", ".join(c for c in r.index if r[c]), axis=1)
    out["industry_sectors_missing"] = missing.where(missing != "", "")
    return out[INDUSTRY_COLUMNS]
