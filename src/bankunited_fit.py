"""Industry Fit priorities and metro joins from msa_naics_year.

Use CBP `msa_naics_year`;
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src import config

PRIORITIES_PATH = config.REFERENCE / "industry_fit_priorities.csv"
DEFAULT_YEAR = 2023


def load_fit_priorities(path: Path | None = None) -> pd.DataFrame:
    """Two-digit NAICS → High / Medium / Low / Exclude."""
    frame = pd.read_csv(path or PRIORITIES_PATH, dtype={"naics_2digit": str})
    frame["naics_2digit"] = frame["naics_2digit"].astype(str).str.zfill(2).str[:2]
    return frame


def utilities_fit(msa_naics_year: pd.DataFrame, year: int = DEFAULT_YEAR) -> pd.DataFrame:
    """Metro employment / establishments for NAICS 22 (Medium Fit) in `year`.

    Returns one row per CBSA with utilities employment share of metro total
    (total = sum of all 2-digit sectors present for that metro-year).
    """
    naics = msa_naics_year.copy()
    naics["cbsa_code"] = naics["cbsa_code"].astype(str).str.zfill(5)
    naics["naics_code"] = naics["naics_code"].astype(str).str.strip()
    snap = naics[naics["year"] == int(year)].copy()
    if snap.empty:
        return pd.DataFrame(columns=[
            "cbsa_code", "year", "naics_code", "fit_priority",
            "cbp_establishments_count", "cbp_employment_count",
            "metro_employment_count", "utilities_emp_share",
        ])

    totals = (
        snap.groupby("cbsa_code", as_index=False)["cbp_employment_count"]
        .sum()
        .rename(columns={"cbp_employment_count": "metro_employment_count"})
    )
    util = snap[snap["naics_code"].eq("22")].copy()
    out = totals.merge(
        util[["cbsa_code", "cbp_establishments_count", "cbp_employment_count"]],
        on="cbsa_code",
        how="left",
    )
    out["year"] = int(year)
    out["naics_code"] = "22"
    out["fit_priority"] = fit_priority_for("22")
    out["utilities_emp_share"] = (
        out["cbp_employment_count"] / out["metro_employment_count"]
    ).where(out["metro_employment_count"] > 0)
    return out.sort_values("cbsa_code", ignore_index=True)


def fit_priority_for(naics_2digit: str, priorities: pd.DataFrame | None = None) -> str | None:
    priorities = load_fit_priorities() if priorities is None else priorities
    code = str(naics_2digit).zfill(2)[:2]
    hit = priorities.loc[priorities["naics_2digit"] == code, "fit_priority"]
    return None if hit.empty else str(hit.iloc[0])
