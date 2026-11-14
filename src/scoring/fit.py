"""Fit & Feasibility measures: how a metro relates to BankUnited's current footprint.

Not scored. The final score reports these as columns and can use them as filters ([fit] in the weights
files): a metro outside a filter keeps its score but gets no rank, exactly like the size floor.

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
