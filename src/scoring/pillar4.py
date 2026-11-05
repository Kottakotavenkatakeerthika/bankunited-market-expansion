"""Pillar 4 metric builder: market quality and durability.

Gathers the metrics only; directions are part of each metric's definition, and weights live in
weights/baseline.toml. Ported from notebooks/pillar4_market_quality_durability.ipynb
(definition mode "dataset_2024"). write_export() keeps Pillar 4's own export layout until the final
score reads metric tables directly.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src import config
from src.scoring import engine
from src.scoring.common import HIGHER, LOWER, Metric, MetricSet, oriented_percentiles

PILLAR, LABEL = "pillar4", "Market quality and durability"

INDUSTRY_GROUPS = {
    "Natural resources and mining": ["11", "21"],
    "Construction": ["23"],
    "Manufacturing": ["31"],  # 31 represents NAICS 31–33
    "Trade, transportation, and utilities": ["22", "42", "44", "48"],
    "Information": ["51"],
    "Financial activities": ["52", "53"],
    "Professional and business services": ["54", "55", "56"],
    "Education and health services": ["61", "62"],
    "Leisure and hospitality": ["71", "72"],
    "Other services": ["81"],
}
CLASSIFIED_SECTORS = [c for codes in INDUSTRY_GROUPS.values() for c in codes]

METRICS = [
    Metric("gdp_growth", "GDP growth", HIGHER, "{p0}–{y} CAGR", "bea_gdp_usd"),
    Metric("gdp_volatility", "GDP volatility", LOWER, "{g0}–{y} annual growth; sample SD", "bea_gdp_usd"),
    Metric("unemployment_level", "Unemployment level", LOWER, "{y} annual rate / 100", "bls_unemployment_rate_pct"),
    Metric("unemployment_volatility", "Unemployment volatility", LOWER, "{u0}–{y} annual rates / 100; sample SD",
           "bls_unemployment_rate_pct"),
    Metric("industry_hhi", "Industry HHI", LOWER, "{iy} CBP; 19 sectors grouped into 10 categories",
           "msa_naics_year: cbp_employment_count"),
    Metric("establishment_growth", "Establishment growth", HIGHER, "{e0}–{e1} CAGR, all employer establishments",
           "cbp_establishments_count"),
    Metric("population_growth", "Population growth", HIGHER, "{p0}–{y} CAGR", "pep_population_count"),
    Metric("net_migration_rate", "Net migration /1,000", HIGHER,
           "{y} net migration / average {ym1}–{y} population × 1,000", "pep_migration_net; pep_population_count"),
]
KEYS = [m.key for m in METRICS]
NO_INDUSTRY = [k for k in KEYS if k != "industry_hhi"]


def _cagr(start, end, years):
    valid = start.notna() & end.notna() & (start > 0) & (end >= 0)
    out = pd.Series(np.nan, index=start.index, dtype=float)
    out.loc[valid] = (end.loc[valid] / start.loc[valid]) ** (1 / years) - 1
    return out.round(12)


def universe(msa_year: pd.DataFrame) -> pd.DataFrame:
    latest = msa_year.sort_values("year").drop_duplicates("cbsa_code", keep="last")
    pr = latest["cbsa_title"].str.strip().str.endswith(", PR")
    return latest.loc[~pr, ["cbsa_code", "cbsa_title"]].set_index("cbsa_code").sort_index()


def build(tables: dict[str, pd.DataFrame], settings: dict) -> MetricSet:
    y = int(settings["end_year"])
    g0, u0 = int(settings["gdp_volatility_start"]), int(settings["unemployment_start"])
    p0, e0, e1 = int(settings["growth_start"]), int(settings["cbp_start"]), int(settings["cbp_end"])
    iy = int(settings["industry_year"])
    panel = tables["msa_year"].copy()
    panel["cbsa_code"] = panel["cbsa_code"].astype(str).str.strip().str.zfill(5)
    panel["year"] = panel["year"].astype(int)
    uni = universe(panel)
    panel = panel[panel.cbsa_code.isin(uni.index)]

    def pw(col, yrs):
        return (panel.pivot(index="cbsa_code", columns="year", values=col)
                .reindex(index=uni.index, columns=list(yrs)).astype(float))

    gyears = list(range(g0, y + 1))
    gdp = pw("bea_gdp_usd", sorted(set([p0, y] + gyears + [v - 1 for v in gyears])))
    unemp = pw("bls_unemployment_rate_pct", range(u0, y + 1)) / 100.0
    cbp = pw("cbp_establishments_count", [e0, e1])
    pop = pw("pep_population_count", sorted({p0, y, y - 1}))
    mig = pw("pep_migration_net", [y])

    raw = pd.DataFrame(index=uni.index)
    raw["gdp_growth"] = _cagr(gdp[p0], gdp[y], y - p0)
    prev = gdp[[v - 1 for v in gyears]].copy()
    prev.columns = gyears
    annual = (gdp[gyears] / prev - 1).where(prev > 0)
    raw["gdp_volatility"] = annual.std(axis=1, ddof=1).where(annual.notna().sum(axis=1).eq(len(gyears))).round(12)
    raw["unemployment_level"] = unemp[y].round(12)
    n_u = y - u0 + 1
    raw["unemployment_volatility"] = unemp.std(axis=1, ddof=1).where(unemp.notna().sum(axis=1).eq(n_u)).round(12)

    ind = tables["msa_naics_year"].copy()
    ind["cbsa_code"] = ind["cbsa_code"].astype(str).str.strip().str.zfill(5)
    ind["naics_code"] = ind["naics_code"].astype(str).str.strip().str.zfill(2)
    ind["year"] = ind["year"].astype(int)
    ind = ind[ind.cbsa_code.isin(uni.index) & ind.year.eq(iy)]
    sectors = (ind.pivot(index="cbsa_code", columns="naics_code", values="cbp_employment_count")
               .reindex(index=uni.index, columns=CLASSIFIED_SECTORS).astype(float))
    groups = pd.DataFrame({g: sectors[c].sum(axis=1, min_count=len(c)) for g, c in INDUSTRY_GROUPS.items()})
    classified = groups.sum(axis=1, min_count=len(INDUSTRY_GROUPS))
    hhi = (groups.pow(2).sum(axis=1, min_count=len(INDUSTRY_GROUPS)) / classified.pow(2)).where(classified > 0).round(12)
    raw["industry_hhi"] = hhi
    all_jobs = pw("cbp_employment_count", [iy])[iy]
    diagnostics = pd.DataFrame({
        "published_classified_sectors": sectors.notna().sum(axis=1),
        "missing_naics_sectors": sectors.isna().apply(
            lambda r: ", ".join(c for c in CLASSIFIED_SECTORS if r[c]), axis=1),
        "classified_to_all_industry_ratio": (classified / all_jobs).where(all_jobs > 0),
    }, index=uni.index)

    raw["establishment_growth"] = _cagr(cbp[e0], cbp[e1], e1 - e0)
    raw["population_growth"] = _cagr(pop[p0], pop[y], y - p0)
    avg_pop = (pop[y - 1] + pop[y]) / 2
    raw["net_migration_rate"] = (mig[y] / avg_pop * 1_000).where(avg_pop > 0).round(12)
    raw = raw[KEYS].replace([np.inf, -np.inf], np.nan)
    raw.index.name = "cbsa_code"

    fmt = {"y": y, "ym1": y - 1, "g0": g0, "u0": u0, "p0": p0, "e0": e0, "e1": e1, "iy": iy}
    metrics = [Metric(m.key, m.label, m.direction, m.period.format(**fmt), m.source) for m in METRICS]
    return MetricSet(PILLAR, LABEL, metrics, raw, uni["cbsa_title"], dict(settings), diagnostics)


def _weighted(P, w):
    w = w.reindex(P.columns)
    have = P.notna()
    cover = have.mul(w, axis=1).sum(axis=1)
    score = P.mul(w, axis=1).sum(axis=1, min_count=1).div(cover.where(cover > 0))
    return score, cover, have.sum(axis=1)


def write_export(ms: MetricSet, weights_cfg: dict, out_dir: Path | None = None, sensitivity: float = 0.25):
    """Write pillar4_scores.csv in the Pillar 4 notebook's layout (it has no run file)."""
    weights, _ = engine.pillar_weights(ms, weights_cfg)
    weights = weights.reindex(KEYS).fillna(0)
    raw = ms.values[KEYS]
    P = oriented_percentiles(raw, {k: ms.registry[k].direction for k in KEYS})   # every metric, scored or not
    avail, cover, valid = _weighted(P, weights)
    complete = avail.where(valid.eq(len(KEYS)))
    w7 = weights[NO_INDUSTRY] / weights[NO_INDUSTRY].sum()
    a7, _, n7 = _weighted(P[NO_INDUSTRY], w7)
    s7 = a7.where(n7.eq(len(NO_INDUSTRY)))
    n_uni = len(ms.values)
    lower = pd.DataFrame(index=ms.values.index, columns=KEYS, dtype=float)
    upper = lower.copy()
    for k in KEYS:
        n_valid = int(raw[k].notna().sum())
        lower[k] = (P[k] * (n_valid - 1) / (n_uni - 1)).fillna(0)
        upper[k] = (lower[k] + 100 * (n_uni - n_valid) / (n_uni - 1)).where(P[k].notna(), 100)
    labels = {m.key: m.label for m in ms.metrics}
    scores = pd.DataFrame({
        "complete_8_score": complete,
        "complete_8_rank": complete.rank(method="min", ascending=False),
        "excluding_industry_7_score": s7,
        "excluding_industry_7_rank": s7.rank(method="min", ascending=False),
        "available_data_score": avail,
        "valid_metrics_out_of_8": valid,
        "original_weight_coverage": cover,
        "all_market_lower_8_metric": lower.mul(weights, axis=1).sum(axis=1),
        "all_market_upper_8_metric": upper.mul(weights, axis=1).sum(axis=1),
    }, index=ms.values.index)
    scores["coverage_status"] = np.where(
        scores.complete_8_score.notna(), "Complete (8/8)",
        np.where(scores.excluding_industry_7_score.notna(), "Partial (7/8; industry unavailable)",
                 "Partial; no comparable rank"))
    scores["missing_metrics"] = raw.isna().apply(lambda r: "; ".join(labels[k] for k in KEYS if r[k]), axis=1)
    results = (pd.DataFrame({"cbsa_title": ms.titles}).join(scores).join(raw.add_suffix("_raw"))
               .join(P.add_suffix("_percentile")).join(ms.diagnostics))
    results = results.sort_values(["complete_8_rank", "cbsa_title"], na_position="last")
    ranks = [scores.complete_8_rank.rename("baseline")]
    for k in KEYS:
        for sign in (-1, 1):
            w = weights.copy()
            w[k] *= 1 + sign * sensitivity
            w /= w.sum()
            cand, _, n = _weighted(P[KEYS], w)
            ranks.append(cand.where(n.eq(len(KEYS))).rank(method="min", ascending=False))
    R = pd.concat(ranks, axis=1)
    results["best_weight_rank"] = R.min(axis=1)
    results["worst_weight_rank"] = R.max(axis=1)
    out_dir = Path(out_dir or config.ROOT / "outputs" / "pillar_scores")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{PILLAR}_scores.csv"
    results.to_csv(path, index=True, index_label="cbsa_code")
    return path, None
