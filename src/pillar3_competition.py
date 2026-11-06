"""Pillar 3: competition and entry windows. How hard is it to win share, and is there an opening?

Every metric returns one long table in the shared metric format:

    metric_id | cbsa_code | year | value | flags

Raw values only: orientation, percentiles and weights belong to the scoring engine.

    from src import pillar3_competition as p3
    tables = p3.load_tables()
    long = p3.compute_all(tables)
    wide = p3.to_wide(long)

Deposits default to main-office and home-banking-office removed (HQ-adjusted), matching
data-v0.5 `_ex_main_office` concentration columns. Pass hq_adjusted=False for as-reported.
Competitors are top holding companies (`sod_top_holder_rssd_id`); affiliated banks count once.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from src import config
from src.utils import standardize_keys

KEYS = ["cbsa_code", "year"]
OUTPUT_COLUMNS = ["metric_id", *KEYS, "value", "flags"]

HQ_DISTORTION_SHARE = 0.5
TOP_N = 3
CHANGE_WINDOW_YEARS = 3


@dataclass(frozen=True)
class Metric:
    metric_id: str
    name: str
    direction: str
    unit: str
    columns: tuple[str, ...]
    compute: Callable[..., pd.DataFrame]
    score_both_ways: bool = True
    notes: str = ""
    flags: tuple[str, ...] = field(default_factory=tuple)


def load_tables(processed=None) -> dict[str, pd.DataFrame]:
    """Read processed tables. Missing tables come back empty."""
    folder = processed or config.PROCESSED
    tables = {}
    for name in ("msa_year", "bank_msa_year"):
        path = folder / f"{name}.parquet"
        tables[name] = standardize_keys(pd.read_parquet(path)) if path.exists() else pd.DataFrame()
    return tables


def _booked_office_deposits(sod: pd.DataFrame) -> pd.Series:
    """Main-office + home-banking-office deposits (data-v0.5 `_ex_main_office` exclusion)."""
    main = sod["sod_main_office_deposits_usd"].fillna(0).astype("float64")
    if "sod_home_banking_office_deposits_usd" in sod.columns:
        home = sod["sod_home_banking_office_deposits_usd"].fillna(0).astype("float64")
    else:
        home = 0.0
    return main + home


def holder_deposits(bank_msa_year: pd.DataFrame, hq_adjusted: bool = True) -> pd.DataFrame:
    """Deposits and branches per holding company per metro-year. Rows without SOD deposits are dropped."""
    sod = bank_msa_year.dropna(subset=["sod_deposits_usd"]).copy()
    sod["holder"] = sod["sod_top_holder_rssd_id"].fillna(sod["rssd_id"])
    deposits = sod["sod_deposits_usd"].astype("float64")
    booked = _booked_office_deposits(sod)
    sod["deposits"] = (deposits - booked).clip(lower=0) if hq_adjusted else deposits
    sod["booked"] = booked
    sod["reported"] = deposits
    return (
        sod.groupby([*KEYS, "holder"], as_index=False)[["deposits", "booked", "reported", "sod_branches_count"]]
        .sum()
        .rename(columns={"sod_branches_count": "branches"})
    )


def metro_flags(bank_msa_year: pd.DataFrame) -> pd.DataFrame:
    """HQ_DISTORTION where booked (main + home-banking) deposits ≥ HQ_DISTORTION_SHARE of reported."""
    holders = holder_deposits(bank_msa_year, hq_adjusted=False)
    metro = holders.groupby(KEYS, as_index=False)[["booked", "reported"]].sum()
    share = metro["booked"] / metro["reported"].where(metro["reported"] > 0)
    metro["flags"] = share.ge(HQ_DISTORTION_SHARE).map({True: "HQ_DISTORTION", False: ""})
    return metro[[*KEYS, "flags"]]


def _shares(holders: pd.DataFrame) -> pd.DataFrame:
    total = holders.groupby(KEYS)["deposits"].transform("sum")
    out = holders.copy()
    out["share"] = out["deposits"] / total.where(total > 0)
    return out


def _finish(values: pd.DataFrame, metric_id: str, bank_msa_year: pd.DataFrame) -> pd.DataFrame:
    """Attach metric_id and flags; mark metro-years that could not be computed."""
    out = values.merge(metro_flags(bank_msa_year), on=KEYS, how="left")
    out["flags"] = out["flags"].fillna("")
    missing = out["value"].isna()
    out.loc[missing, "flags"] = out.loc[missing, "flags"].map(_add_flag("SUPPRESSED_INPUTS"))
    out["metric_id"] = metric_id
    return standardize_keys(out[OUTPUT_COLUMNS]).sort_values(KEYS, ignore_index=True)


def _add_flag(flag: str):
    return lambda existing: flag if not existing else f"{existing};{flag}"


def deposit_hhi(tables, hq_adjusted: bool = True) -> pd.DataFrame:
    """P3-01: Herfindahl-Hirschman index of deposit shares across holding companies, 0 to 10,000."""
    bank = tables["bank_msa_year"]
    shares = _shares(holder_deposits(bank, hq_adjusted))
    shares["sq"] = (shares["share"] * 100) ** 2
    values = shares.groupby(KEYS)["sq"].sum(min_count=1).rename("value").reset_index()
    return _finish(values, "P3-01", bank)


def top3_deposit_share(tables, hq_adjusted: bool = True) -> pd.DataFrame:
    """P3-02: combined deposit share of the three largest holding companies, 0 to 1."""
    bank = tables["bank_msa_year"]
    shares = _shares(holder_deposits(bank, hq_adjusted))
    values = (
        shares.sort_values("share", ascending=False)
        .groupby(KEYS)["share"]
        .apply(lambda s: s.head(TOP_N).sum(min_count=1))
        .rename("value")
        .reset_index()
    )
    return _finish(values, "P3-02", bank)


def competitors_per_billion(tables, hq_adjusted: bool = True) -> pd.DataFrame:
    """P3-03: holding companies with deposits in the metro per $1B of local deposits."""
    bank = tables["bank_msa_year"]
    holders = holder_deposits(bank, hq_adjusted)
    metro = holders.groupby(KEYS).agg(count=("holder", "nunique"), deposits=("deposits", "sum")).reset_index()
    metro["value"] = metro["count"] / (metro["deposits"] / 1e9).where(metro["deposits"] > 0)
    return _finish(metro[[*KEYS, "value"]], "P3-03", bank)


def branches_per_billion(tables, hq_adjusted: bool = True) -> pd.DataFrame:
    """P3-04: full-service branches per $1B of local deposits."""
    bank = tables["bank_msa_year"]
    holders = holder_deposits(bank, hq_adjusted)
    metro = holders.groupby(KEYS)[["branches", "deposits"]].sum().reset_index()
    metro["value"] = metro["branches"] / (metro["deposits"] / 1e9).where(metro["deposits"] > 0)
    return _finish(metro[[*KEYS, "value"]], "P3-04", bank)


def leader_share_change(tables, hq_adjusted: bool = True) -> pd.DataFrame:
    """P3-07: 3-year change in deposit share of the metro's three leaders fixed at t-3."""
    bank = tables["bank_msa_year"]
    shares = _shares(holder_deposits(bank, hq_adjusted))[[*KEYS, "holder", "share"]]
    leaders = (
        shares.sort_values("share", ascending=False)
        .groupby(KEYS)
        .head(TOP_N)[[*KEYS, "holder", "share"]]
        .rename(columns={"share": "share_start"})
    )
    leaders["year"] = leaders["year"] + CHANGE_WINDOW_YEARS
    later = leaders.merge(shares, on=[*KEYS, "holder"], how="left")
    later["share"] = later["share"].fillna(0.0)
    change = later.groupby(KEYS)[["share", "share_start"]].sum().reset_index()
    change["value"] = change["share"] - change["share_start"]
    grid = shares[KEYS].drop_duplicates()
    values = grid.merge(change[[*KEYS, "value"]], on=KEYS, how="left")
    return _finish(values, "P3-07", bank)


METRICS: dict[str, Metric] = {
    m.metric_id: m
    for m in (
        Metric("P3-01", "Deposit HHI across holding companies", "lower", "index_0_10000",
               ("sod_deposits_usd", "sod_main_office_deposits_usd",
                "sod_home_banking_office_deposits_usd", "sod_top_holder_rssd_id"), deposit_hhi,
               notes="More contestable markets are easier to enter.", flags=("HQ_DISTORTION",)),
        Metric("P3-02", "Top-3 holding-company deposit share", "lower", "share",
               ("sod_deposits_usd", "sod_main_office_deposits_usd",
                "sod_home_banking_office_deposits_usd", "sod_top_holder_rssd_id"), top3_deposit_share,
               flags=("HQ_DISTORTION",)),
        Metric("P3-03", "Competitors per $1B of local deposits", "lower", "per_usd_billion",
               ("sod_deposits_usd", "sod_main_office_deposits_usd",
                "sod_home_banking_office_deposits_usd", "sod_top_holder_rssd_id"),
               competitors_per_billion, notes="Fewer incumbents per dollar of deposits.", flags=("HQ_DISTORTION",)),
        Metric("P3-04", "Full-service branches per $1B of local deposits", "lower", "per_usd_billion",
               ("sod_branches_count", "sod_deposits_usd", "sod_main_office_deposits_usd",
                "sod_home_banking_office_deposits_usd"), branches_per_billion,
               flags=("HQ_DISTORTION",)),
        Metric("P3-07", "3-year change in the leading banks' deposit share", "lower", "share_points",
               ("sod_deposits_usd", "sod_main_office_deposits_usd",
                "sod_home_banking_office_deposits_usd", "sod_top_holder_rssd_id"), leader_share_change,
               notes="Falling incumbent share signals an opening for a new entrant.", flags=("HQ_DISTORTION",)),
    )
}


def compute_all(tables, hq_adjusted: bool = True) -> pd.DataFrame:
    """Stack every Pillar 3 metric in long format (P3-01..04, P3-07)."""
    frames = [metric.compute(tables, hq_adjusted=hq_adjusted) for metric in METRICS.values()]
    return pd.concat(frames, ignore_index=True)


def to_wide(long: pd.DataFrame) -> pd.DataFrame:
    """One row per metro-year, one column per metric, flags tagged by metric."""
    wide = long.pivot_table(index=KEYS, columns="metric_id", values="value", aggfunc="first", dropna=False)
    tagged = long.assign(flags=[
        ";".join(f"{metric}:{flag}" for flag in text.split(";") if flag)
        for metric, text in zip(long["metric_id"], long["flags"])
    ])
    flags = tagged.groupby(KEYS)["flags"].agg(lambda s: ";".join(v for v in s if v))
    return wide.join(flags).reset_index().rename_axis(columns=None)


def metric_catalog() -> pd.DataFrame:
    """METRICS as a table for the metric-ID-to-column mapping."""
    return pd.DataFrame([
        {"metric_id": m.metric_id, "pillar": "P3", "name": m.name, "direction": m.direction,
         "score_both_ways": m.score_both_ways, "unit": m.unit, "table": "bank_msa_year",
         "columns": ", ".join(m.columns), "flags": ", ".join(m.flags), "notes": m.notes}
        for m in METRICS.values()
    ])
