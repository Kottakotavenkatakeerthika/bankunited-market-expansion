"""Legacy entry point for notebooks/pillar3_competition.ipynb only. Delete with the old notebooks.

Pillar 3's metrics now live in src/scoring/pillar3.py, which the scoring pipeline uses directly. This file
only rebuilds the notebook's long and wide tables from it, so the old notebook keeps running.
"""
from __future__ import annotations

import pandas as pd

from src.scoring import pillar3
from src.scoring.common import load_tables as _load

KEYS = pillar3.KEYS
IDS = {m.key: m.metric_id for m in pillar3.METRICS}


def load_tables(processed=None) -> dict[str, pd.DataFrame]:
    return _load(processed, names=("msa_year", "bank_msa_year"))


def compute_all(tables, hq_adjusted: bool = True) -> pd.DataFrame:
    """metric_id | cbsa_code | year | value | flags, as the old module returned."""
    m = pillar3.metro_metrics(tables["bank_msa_year"], hq_adjusted)
    hq = m["hq_distortion"].fillna(False).astype(bool).map({True: "HQ_DISTORTION", False: ""})
    frames = []
    for key, mid in IDS.items():
        f = m[KEYS].assign(metric_id=mid, value=m[key], flags=hq)
        miss = f["value"].isna()
        f.loc[miss, "flags"] = f.loc[miss, "flags"].map(lambda s: "SUPPRESSED_INPUTS" if not s else f"{s};SUPPRESSED_INPUTS")
        frames.append(f[["metric_id", *KEYS, "value", "flags"]].sort_values(KEYS, ignore_index=True))
    return pd.concat(frames, ignore_index=True)


def to_wide(long: pd.DataFrame) -> pd.DataFrame:
    wide = long.pivot_table(index=KEYS, columns="metric_id", values="value", aggfunc="first", dropna=False)
    tagged = long.assign(flags=[";".join(f"{mid}:{f}" for f in text.split(";") if f)
                                for mid, text in zip(long["metric_id"], long["flags"])])
    flags = tagged.groupby(KEYS)["flags"].agg(lambda s: ";".join(v for v in s if v))
    return wide.join(flags).reset_index().rename_axis(columns=None)
