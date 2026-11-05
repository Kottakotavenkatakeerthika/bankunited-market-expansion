"""Shared pieces for the pillar metric builders and the scoring engine."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from src import config

SETTINGS_FILE = config.ROOT / "config" / "settings.toml"
HIGHER, LOWER = "Higher", "Lower"


@dataclass(frozen=True)
class Metric:
    """One metric's definition. `direction` says which way is more attractive."""
    key: str
    label: str
    direction: str            # HIGHER or LOWER
    period: str
    source: str
    group: str = ""
    metric_id: str = ""       # e.g. "P3-01", where a pillar has published ids
    available: bool = True    # False: defined but no data in data/processed yet

    def __post_init__(self):
        if self.direction not in (HIGHER, LOWER):
            raise ValueError(f"{self.key}: direction must be {HIGHER!r} or {LOWER!r}")


@dataclass
class MetricSet:
    """What a pillar builder returns: raw values for every metric it defines, one row per metro."""
    pillar: str
    label: str
    metrics: list[Metric]
    values: pd.DataFrame                  # index cbsa_code, one column per available metric
    titles: pd.Series                     # cbsa_code -> metro title
    settings: dict = field(default_factory=dict)
    diagnostics: pd.DataFrame | None = None   # extra per-metro columns a pillar reports (not scored)

    def __post_init__(self):
        keys = [m.key for m in self.metrics]
        if len(set(keys)) != len(keys):
            raise ValueError(f"{self.pillar}: duplicate metric keys")
        missing = [m.key for m in self.metrics if m.available and m.key not in self.values.columns]
        if missing:
            raise ValueError(f"{self.pillar}: builder returned no values for {missing}")
        extra = sorted(set(self.values.columns) - set(keys))
        if extra:
            raise ValueError(f"{self.pillar}: values for undefined metrics {extra}")

    @property
    def registry(self) -> dict[str, Metric]:
        return {m.key: m for m in self.metrics}

    @property
    def not_available(self) -> list[str]:
        return [m.key for m in self.metrics if not m.available]


def load_settings(path: Path | str | None = None) -> dict:
    with open(path or SETTINGS_FILE, "rb") as f:
        return tomllib.load(f)


def load_tables(processed: Path | str | None = None, names=("msa_year", "bank_msa_year", "bank_quarter")) -> dict:
    processed = Path(processed or config.PROCESSED)
    return {n: pd.read_parquet(processed / f"{n}.parquet") for n in names if (processed / f"{n}.parquet").exists()}


def states_universe(msa_year: pd.DataFrame) -> pd.DataFrame:
    """The 387 metros in the 50 states and DC (Puerto Rico excluded): Pillars 1, 2 and 4."""
    return (msa_year.loc[~msa_year.cbsa_title.str.endswith(", PR"), ["cbsa_code", "cbsa_title"]]
            .drop_duplicates().sort_values("cbsa_code").set_index("cbsa_code"))


def wide(msa_year: pd.DataFrame, col: str, cbsas) -> pd.DataFrame:
    """An msa_year column as a metro x year table, restricted to `cbsas`."""
    return msa_year.pivot(index="cbsa_code", columns="year", values=col).reindex(cbsas)


def call(bank_quarter: pd.DataFrame, quarter_end: str) -> pd.DataFrame:
    """Call Report values for one quarter, indexed by RSSD ID."""
    return bank_quarter[pd.to_datetime(bank_quarter.quarter_end) == pd.Timestamp(quarter_end)].set_index("rssd_id")


def r12(s):
    """Round to 12 decimals, as the notebooks do, so tiny float noise doesn't reorder ties."""
    return s.astype(float).round(12)


def cagr(start, end, years):
    """Compound annual growth; blank unless both ends exist and the start is positive."""
    ok = start.notna() & end.notna() & (start > 0)
    return r12((end / start) ** (1 / years) - 1).where(ok)


def ratio(num, den):
    """num / den; blank unless both exist and den is positive."""
    ok = num.notna() & den.notna() & (den > 0)
    return r12(num / den).where(ok)


def oriented_percentiles(values: pd.DataFrame, directions: dict[str, str]) -> pd.DataFrame:
    """Average-rank percentiles (0-100) among metros that have the metric; higher is always more attractive.
    Same rule as the pillar notebooks: 100 x (average oriented rank - 1) / (valid count - 1)."""
    P = pd.DataFrame(index=values.index)
    for col in values.columns:
        v = values[col] if directions[col] == HIGHER else -values[col]
        n = v.notna().sum()
        P[col] = 100 * (v.rank(method="average") - 1) / (n - 1) if n > 1 else np.nan
    return P
