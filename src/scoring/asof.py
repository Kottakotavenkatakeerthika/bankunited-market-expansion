"""Point-in-time settings: what the pillars could have used on a given decision date.

    settings, report = settings_as_of(load_settings(), "2025-06-30", tables)

For each source, the latest data year is the latest one whose first release (data/reference/
release_dates.csv) came out on or before the date, and that data/processed actually holds. Every window
keeps the length set in config/settings.toml and ends at that year. A window that would start before the
data does is shortened to start at the first year held, and the report says so.

Limit: data/processed holds each source's latest vintage, so an as-of run uses values that may have been
revised since; it reproduces what was *available*, not the exact numbers published then.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pandas as pd

from src import config

RELEASES = config.REFERENCE / "release_dates.csv"

# source key -> (release_dates source, dataset or None for any, how to find the years data/processed holds)
SOURCES = {
    "sod":   ("sod", "bankfind_sod", ("bank_msa_year", "sod_deposits_usd")),
    "cbp":   ("cbp", "cbp_county", ("msa_year", "cbp_establishments_count")),
    "qcew":  ("bls", "qcew_annual_by_area", ("msa_year", "bls_qcew_total_wages_usd")),
    "laus":  ("bls", "laucnty", ("msa_year", "bls_unemployment_rate_pct")),
    "bea_income": ("bea", "cainc1", ("msa_year", "bea_personal_income_usd")),
    "bea_gdp":    ("bea", "cagdp2", ("msa_year", "bea_gdp_usd")),
    "pep":   ("pep", None, ("msa_year", "pep_population_count")),
}


def _first_releases() -> pd.DataFrame:
    r = pd.read_csv(RELEASES, dtype=str)
    r = r[r.release_type.eq("initial") & r.release_date.notna()].copy()
    r["release_date"] = pd.to_datetime(r.release_date)
    r["year"] = r.year.astype(int)
    return r


def _held_years(tables, table, column) -> list[int]:
    t = tables[table]
    return sorted(t.loc[t[column].notna(), "year"].astype(int).unique())


def latest_years(as_of, tables) -> dict[str, dict]:
    """Per source: latest year released by as_of and held in data/processed, and the first year held."""
    as_of = pd.Timestamp(as_of)
    rel = _first_releases()
    out = {}
    for key, (src, dataset, (table, col)) in SOURCES.items():
        r = rel[rel.source.eq(src) & (rel.dataset.eq(dataset) if dataset else True)]
        released = sorted(r.loc[r.release_date <= as_of, "year"].unique())
        held = _held_years(tables, table, col)
        usable = [y for y in released if y in held]
        out[key] = {"latest": int(usable[-1]) if usable else None, "first_held": int(held[0]) if held else None}
    # Call Reports: latest June quarter released (quarter_end + 35 days) and held
    r = rel[rel.source.eq("call")].dropna(subset=["quarter_end"])
    held_q = set(pd.to_datetime(tables["bank_quarter"].quarter_end).dt.strftime("%Y-%m-%d"))
    june = sorted(int(q[:4]) for q, d in zip(r.quarter_end, r.release_date)
                  if q.endswith("-06-30") and d <= as_of and q in held_q)
    out["call_june"] = {"latest": june[-1] if june else None,
                        "first_held": min(int(q[:4]) for q in held_q if q.endswith("-06-30"))}
    return out


def settings_as_of(settings: dict, as_of, tables) -> tuple[dict, dict]:
    """Settings with every year and window moved to what was available on as_of, and a report of the choices."""
    yrs = latest_years(as_of, tables)
    missing = [k for k, v in yrs.items() if v["latest"] is None]
    if missing:
        raise ValueError(f"as of {as_of}: no released data held for {missing}; pick a later date")
    s = copy.deepcopy(settings)
    shortened = []

    def window(label, end, length, source):
        start = end - length
        first = yrs[source]["first_held"]
        if start < first:
            shortened.append(f"{label}: {start}–{end} shortened to {first}–{end} (data start in {first})")
            start = first
        if start >= end:
            raise ValueError(f"as of {as_of}: {label} has no window left ({first}–{end})")
        return start

    sod, call, cbp = yrs["sod"]["latest"], yrs["call_june"]["latest"], yrs["cbp"]["latest"]
    bank_end = min(sod, call)                       # June SOD and June Call Report of the same year

    p1 = s["pillar1"]
    n = int(p1["end_quarter"][:4]) - int(p1["base_quarter"][:4])
    p1["end_quarter"] = f"{bank_end}-06-30"
    p1["base_quarter"] = f"{window('pillar1 bank-reported lending', bank_end, n, 'sod')}-06-30"
    n = int(p1["cbp_end"]) - int(p1["cbp_start"])
    p1["cbp_end"], p1["cbp_start"] = cbp, window("pillar1 CBP growth", cbp, n, "cbp")

    p2 = s["pillar2"]
    for a, b, src in (("sod_start", "sod_end", "sod"), ("qcew_start", "qcew_end", "qcew"),
                      ("bea_start", "bea_end", "bea_income")):
        n = int(p2[b]) - int(p2[a])
        end = bank_end if src == "sod" else yrs[src]["latest"]
        p2[b], p2[a] = end, window(f"pillar2 {a[:-6]} growth", end, n, src)
    p2["call_quarter"] = f"{bank_end}-06-30"
    p2["cbp_year"] = cbp

    s["pillar3"]["score_year"] = sod

    p4 = s["pillar4"]
    end = min(yrs["bea_gdp"]["latest"], yrs["laus"]["latest"], yrs["pep"]["latest"])
    old_end = int(p4["end_year"])
    p4["growth_start"] = window("pillar4 GDP and population growth", end, old_end - int(p4["growth_start"]), "bea_gdp")
    # GDP volatility starts at its first annual growth rate, which needs GDP for the year before
    n = old_end - int(p4["gdp_volatility_start"])
    first_rate = yrs["bea_gdp"]["first_held"] + 1
    gv = end - n
    if gv < first_rate:
        shortened.append(f"pillar4 GDP volatility: growth rates {gv}–{end} shortened to {first_rate}–{end} "
                         f"(GDP data start in {first_rate - 1})")
        gv = first_rate
    p4["gdp_volatility_start"] = gv
    p4["unemployment_start"] = window("pillar4 unemployment volatility", end, old_end - int(p4["unemployment_start"]), "laus")
    p4["end_year"] = end
    n = int(p4["cbp_end"]) - int(p4["cbp_start"])
    p4["cbp_end"], p4["cbp_start"] = cbp, window("pillar4 establishment growth", cbp, n, "cbp")
    p4["industry_year"] = cbp

    report = {"as_of": str(pd.Timestamp(as_of).date()),
              "latest_year_used": {k: v["latest"] for k, v in yrs.items()},
              "windows_shortened": shortened,
              "note": "Years released by the date and held in data/processed; values are the latest vintage."}
    return s, report
