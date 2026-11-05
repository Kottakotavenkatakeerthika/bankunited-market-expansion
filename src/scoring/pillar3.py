"""Pillar 3 metric builder: competition and entry windows.

Gathers the metrics only; directions are part of each metric's definition, and weights live in
weights/baseline.toml. The metric calculations are in src/pillar3_competition.py.
"""
from __future__ import annotations

import pandas as pd

from src import pillar3_competition as p3
from src.scoring.common import LOWER, Metric, MetricSet

PILLAR, LABEL = "pillar3", "Competition and entry windows"
SOURCE = "bank_msa_year SOD"

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


def build(tables: dict[str, pd.DataFrame], settings: dict) -> MetricSet:
    """Raw values of every Pillar 3 metric for the metros in msa_year in the score year."""
    year, hq = int(settings["score_year"]), bool(settings["hq_adjusted"])
    msa_year = tables["msa_year"]
    universe = (msa_year.loc[msa_year.year == year, ["cbsa_code", "cbsa_title"]]
                .drop_duplicates().sort_values("cbsa_code").set_index("cbsa_code"))
    cbsas = list(universe.index)

    wide = p3.to_wide(p3.compute_all(tables, hq_adjusted=hq))
    snap = wide[wide["year"] == year].set_index("cbsa_code").reindex(cbsas)
    values = pd.DataFrame({m.key: snap[m.metric_id] for m in METRICS}, index=cbsas)
    values.index.name = "cbsa_code"
    metrics = [Metric(m.key, m.label, m.direction, m.period.format(y=year, y0=year - 3), m.source, m.group,
                      m.metric_id) for m in METRICS]
    return MetricSet(PILLAR, LABEL, metrics, values, universe["cbsa_title"],
                     {"score_year": year, "hq_adjusted": hq})
