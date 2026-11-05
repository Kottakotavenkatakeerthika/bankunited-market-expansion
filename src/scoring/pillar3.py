"""Pillar 3 metric builder: competition and entry windows. How hard is it to win share, and is there an opening?

Self-contained, like the other pillar builders: gathers the metrics only. Directions are part of each
metric's definition; weights live in weights/baseline.toml; settings in config/settings.toml [pillar3].
Ported from src/pillar3_competition.py on 2026-11-05 (that module has since been removed).

Deposits leave out main-office and home-banking-office bookings when hq_adjusted is true (matching the
data-v0.5 `_ex_main_office` columns). Competitors are top holding companies (`sod_top_holder_rssd_id`), so
affiliated banks count once. Every metric is computed for all SOD years; the builder keeps the score year.
"""
from __future__ import annotations

import pandas as pd

from src.scoring.common import HIGHER, LOWER, Metric, MetricSet, oriented_percentiles, states_universe

PILLAR, LABEL = "pillar3", "Competition and entry windows"
SOURCE = "bank_msa_year SOD"
KEYS = ["cbsa_code", "year"]
TOP_N = 3                    # leaders for top-3 share and leader share change
CHANGE_WINDOW_YEARS = 3      # leader share change: leaders fixed this many years before the score year
HQ_DISTORTION_SHARE = 0.5    # diagnostic flag: booked (main + home-banking) deposits >= this share of reported

METRICS = [
    Metric("deposit_hhi", "Deposit HHI across holding companies", LOWER, "June {y}", SOURCE, "Concentration", "P3-01"),
    Metric("top3_share", "Top-3 holding-company deposit share", LOWER, "June {y}", SOURCE, "Concentration", "P3-02"),
    Metric("competitors_per_billion", "Competitors per $1B of local deposits", LOWER, "June {y}", SOURCE,
           "Market thinness", "P3-03"),
    Metric("branches_per_billion", "Full-service branches per $1B of local deposits", LOWER, "June {y}", SOURCE,
           "Market thinness", "P3-04"),
    Metric("leader_share_change", "3-year change in leaders' deposit share", LOWER, "{y0}→{y}", SOURCE,
           "Opening", "P3-07"),
]


# Built after every pillar's raw metrics exist, because it combines metrics from Pillars 1, 2 and 4.
COMPETITION_GROWTH = Metric(
    "competition_growth", "Competition × growth (few competitors pay off only where the market grows)", HIGHER,
    "June {y}", "composite: P3 deposit HHI × growth from Pillars 1, 2 and 4", "Competition × growth", "P3-08")


def holder_deposits(bank_msa_year: pd.DataFrame, hq_adjusted: bool = True) -> pd.DataFrame:
    """Deposits and branches per holding company per metro-year. Rows without SOD deposits are dropped."""
    sod = bank_msa_year.dropna(subset=["sod_deposits_usd"]).copy()
    sod["holder"] = sod["sod_top_holder_rssd_id"].fillna(sod["rssd_id"])
    reported = sod["sod_deposits_usd"].astype("float64")
    booked = sod["sod_main_office_deposits_usd"].fillna(0).astype("float64")
    if "sod_home_banking_office_deposits_usd" in sod.columns:
        booked = booked + sod["sod_home_banking_office_deposits_usd"].fillna(0).astype("float64")
    sod["deposits"] = (reported - booked).clip(lower=0) if hq_adjusted else reported
    sod["booked"], sod["reported"] = booked, reported
    return (sod.groupby([*KEYS, "holder"], as_index=False)[["deposits", "booked", "reported", "sod_branches_count"]]
            .sum().rename(columns={"sod_branches_count": "branches"}))


def _shares(holders: pd.DataFrame) -> pd.DataFrame:
    total = holders.groupby(KEYS)["deposits"].transform("sum")
    return holders.assign(share=holders["deposits"] / total.where(total > 0))


def metro_metrics(bank_msa_year: pd.DataFrame, hq_adjusted: bool = True) -> pd.DataFrame:
    """Every Pillar 3 metric for every metro-year in SOD, one row per metro-year."""
    holders = holder_deposits(bank_msa_year, hq_adjusted)
    shares = _shares(holders)
    out = shares[KEYS].drop_duplicates().set_index(KEYS)

    # P3-01: Herfindahl-Hirschman index of deposit shares across holding companies, 0 to 10,000
    out["deposit_hhi"] = ((shares["share"] * 100) ** 2).groupby([shares[k] for k in KEYS]).sum(min_count=1)
    # P3-02: combined deposit share of the three largest holding companies, 0 to 1
    out["top3_share"] = (shares.sort_values("share", ascending=False).groupby(KEYS)["share"]
                         .apply(lambda s: s.head(TOP_N).sum(min_count=1)))
    # P3-03 and P3-04: holding companies and full-service branches per $1B of local deposits
    metro = holders.groupby(KEYS).agg(count=("holder", "nunique"), branches=("branches", "sum"),
                                      deposits=("deposits", "sum"))
    per_billion = (metro["deposits"] / 1e9).where(metro["deposits"] > 0)
    out["competitors_per_billion"] = metro["count"] / per_billion
    out["branches_per_billion"] = metro["branches"] / per_billion
    # P3-07: change in the deposit share of the metro's three leaders, fixed CHANGE_WINDOW_YEARS earlier
    leaders = (shares[[*KEYS, "holder", "share"]].sort_values("share", ascending=False).groupby(KEYS).head(TOP_N)
               .rename(columns={"share": "share_start"}))
    leaders["year"] = leaders["year"] + CHANGE_WINDOW_YEARS
    later = leaders.merge(shares[[*KEYS, "holder", "share"]], on=[*KEYS, "holder"], how="left")
    later["share"] = later["share"].fillna(0.0)
    change = later.groupby(KEYS)[["share", "share_start"]].sum()
    out["leader_share_change"] = change["share"] - change["share_start"]

    # diagnostic: how much of the metro's reported deposits are booked at main or home-banking offices
    raw = holder_deposits(bank_msa_year, hq_adjusted=False).groupby(KEYS)[["booked", "reported"]].sum()
    out["hq_booked_share"] = raw["booked"] / raw["reported"].where(raw["reported"] > 0)
    out["hq_distortion"] = out["hq_booked_share"].ge(HQ_DISTORTION_SHARE)
    return out.reset_index()


def build(tables: dict[str, pd.DataFrame], settings: dict) -> MetricSet:
    """Raw values of every Pillar 3 metric for the 387 metros in the 50 states and DC.

    Until 2026-11-05 the notebook ranked Pillar 3 among 393 metros, Puerto Rico included; it now uses the
    same universe as the other pillars, so Puerto Rico no longer shifts Pillar 3 percentiles."""
    year, hq = int(settings["score_year"]), bool(settings["hq_adjusted"])
    universe = states_universe(tables["msa_year"])
    cbsas = list(universe.index)
    bmy = tables["bank_msa_year"].assign(cbsa_code=lambda d: d["cbsa_code"].astype(str).str.zfill(5))
    snap = metro_metrics(bmy, hq).query("year == @year").set_index("cbsa_code").reindex(cbsas)
    snap.index.name = "cbsa_code"
    keys = [m.key for m in METRICS]
    metrics = [Metric(m.key, m.label, m.direction, m.period.format(y=year, y0=year - CHANGE_WINDOW_YEARS),
                      m.source, m.group, m.metric_id) for m in METRICS]
    return MetricSet(PILLAR, LABEL, metrics, snap[keys], universe["cbsa_title"], {"score_year": year, "hq_adjusted": hq},
                     snap[["hq_booked_share", "hq_distortion"]])


def corner_score(fewness: pd.Series, growth: pd.Series, corners: dict) -> pd.Series:
    """Bilinear blend of the four corner values (0-100) by fewness and growth percentiles (0-100).

    corners: few_growing, many_growing, few_stable, many_stable. A metro at fewness 100 and growth 100
    gets few_growing, and so on; everything in between is interpolated."""
    c, g = fewness / 100, growth / 100
    return (corners["few_growing"] * c * g + corners["many_growing"] * (1 - c) * g
            + corners["few_stable"] * c * (1 - g) + corners["many_stable"] * (1 - c) * (1 - g))


def add_competition_growth(ms: MetricSet, sets: dict[str, MetricSet], settings: dict) -> MetricSet:
    """Pillar 3 with competition_growth added, from the other pillars' raw metrics.

    fewness = percentile of deposit HHI, 100 = most concentrated (a few banks hold most deposits).
    growth  = mean percentile of the growth metrics listed in settings (all must be present).
    Both are percentiles among the 387 metros, oriented so 100 = most concentrated / fastest growing."""
    cfg = settings["competition_growth"]
    hhi = ms.values[cfg["concentration_metric"]]
    fewness = 100 - oriented_percentiles(hhi.to_frame(), {hhi.name: LOWER})[hhi.name]
    parts = []
    for ref in cfg["growth_metrics"]:
        pillar, key = ref.split(".")
        m = sets[pillar].registry[key]
        v = sets[pillar].values[key].reindex(ms.values.index)
        parts.append(oriented_percentiles(v.to_frame(), {key: m.direction})[key])
    G = pd.concat(parts, axis=1)
    growth = G.mean(axis=1).where(G.notna().all(axis=1))
    values = ms.values.assign(competition_growth=corner_score(fewness, growth, cfg["corners"]).round(12))
    metric = Metric(COMPETITION_GROWTH.key, COMPETITION_GROWTH.label, HIGHER,
                    COMPETITION_GROWTH.period.format(y=ms.settings["score_year"]), COMPETITION_GROWTH.source,
                    COMPETITION_GROWTH.group, COMPETITION_GROWTH.metric_id)
    diagnostics = ms.diagnostics.assign(competition_fewness=fewness, market_growth=growth)
    return MetricSet(ms.pillar, ms.label, [*ms.metrics, metric], values, ms.titles,
                     {**ms.settings, "competition_growth": cfg}, diagnostics)
