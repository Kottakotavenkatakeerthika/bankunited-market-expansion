"""Scoring engine helpers: effective metric weights, pillar scores, and the per-pillar files.

The final score (src/market_attractiveness.py) builds each pillar from its MetricSet directly. The files
written here are for reading, the app and the dashboard; nothing reads them back:

    outputs/pillar_scores/<pillar>_scores.csv   one row per metro: the pillar score under the baseline
                                                weights, then raw_<metric> and pct_<metric> for EVERY metric
                                                (weighted or not), then any diagnostics the pillar reports
    outputs/pillar_scores/<pillar>_run.json     settings, effective weights and coverage for that file
    outputs/pillar_scores/metric_catalog.csv    one row per metric: pillar, label, direction, period, source,
                                                baseline weight

score_pillar() applies the pillar notebooks' rule: each metric becomes an oriented percentile among the
metros that have it; the available-data score is the weighted mean of the percentiles a metro has
(weights rescaled over them); the complete score needs every weighted metric; rank is among complete metros.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src import config
from src.scoring.common import MetricSet, oriented_percentiles

WEIGHTS_FILE = config.ROOT / "weights" / "baseline.toml"


def pillar_weights(ms: MetricSet, weights_cfg: dict) -> tuple[pd.Series, list[str]]:
    """Effective metric weights (positive, available, summing to 1) and the metrics weighted but not available."""
    entered = pd.Series(weights_cfg["metrics"].get(ms.pillar, {}), dtype=float)
    unknown = sorted(set(entered.index) - set(ms.registry))
    if unknown:
        raise ValueError(f"{ms.pillar}: weights for metrics the builder doesn't define: {unknown}")
    if (entered < 0).any():
        raise ValueError(f"{ms.pillar}: weights must be zero or positive")
    skipped = [k for k in entered.index if entered[k] > 0 and not ms.registry[k].available]
    used = entered[[k for k in entered.index if entered[k] > 0 and ms.registry[k].available]]
    if used.empty:
        raise ValueError(f"{ms.pillar}: no weighted metric is available")
    return used / used.sum(), skipped


def percentiles(ms: MetricSet) -> pd.DataFrame:
    """Oriented percentiles of every available metric."""
    keys = [m.key for m in ms.metrics if m.available]
    return oriented_percentiles(ms.values[keys], {m.key: m.direction for m in ms.metrics})


def score_pillar(ms: MetricSet, weights: pd.Series, P: pd.DataFrame | None = None) -> pd.DataFrame:
    """Pillar score table for the weighted metrics."""
    P = (percentiles(ms) if P is None else P)[list(weights.index)]
    have = P.notna()
    cover = have.mul(weights, axis=1).sum(axis=1)
    available = P.fillna(0).mul(weights, axis=1).sum(axis=1) / cover.where(cover > 0)
    complete = available.where(have.all(axis=1))
    return pd.DataFrame({
        "msa": ms.titles.reindex(P.index),
        "complete_score": complete,
        "rank": complete.rank(ascending=False, method="min"),
        "available_score": available,
        "valid_metrics": have.sum(axis=1),
        "weight_coverage": cover,
        "missing_metrics": have.apply(lambda r: ", ".join(c for c in r.index if not r[c]), axis=1),
    })


def write_pillar_file(ms: MetricSet, weights_cfg: dict, out_dir: Path | None = None) -> tuple[Path, Path]:
    """Write <pillar>_scores.csv and <pillar>_run.json (see the module docstring)."""
    weights, skipped = pillar_weights(ms, weights_cfg)
    P = percentiles(ms)
    results = score_pillar(ms, weights, P)
    keys = list(P.columns)
    table = results.join(ms.values[keys].add_prefix("raw_")).join(P.add_prefix("pct_"))
    if ms.diagnostics is not None:
        table = table.join(ms.diagnostics)
    table = table.sort_values(["complete_score", "available_score"], ascending=False)
    out_dir = Path(out_dir or config.ROOT / "outputs" / "pillar_scores")
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path, json_path = out_dir / f"{ms.pillar}_scores.csv", out_dir / f"{ms.pillar}_run.json"
    table.rename_axis("cbsa_code").to_csv(csv_path)
    run = {
        "pillar": ms.pillar,
        "label": ms.label,
        "built_by": f"src.scoring.{ms.pillar}",
        "run_date": str(pd.Timestamp.today().date()),
        "weights_file": "weights/baseline.toml",
        "effective_weights": weights.round(6).to_dict(),
        "unweighted_metrics": [k for k in keys if k not in weights.index],
        "weighted_but_not_available": skipped,
        "not_available": ms.not_available,
        "settings": ms.settings,
        "metros": len(table),
        "complete_msas": int(results["rank"].notna().sum()),
        "note": "For reading only. The final score rebuilds pillars from the metric builders and weights files.",
    }
    json_path.write_text(json.dumps(run, indent=2, default=str))
    return csv_path, json_path


def catalog(sets: dict[str, MetricSet], weights_cfg: dict) -> pd.DataFrame:
    """One row per metric across every pillar, with its baseline weight."""
    rows = []
    for ms in sets.values():
        entered = weights_cfg["metrics"].get(ms.pillar, {})
        eff, _ = pillar_weights(ms, weights_cfg)
        coverage = ms.values.notna().sum()
        for m in ms.metrics:
            rows.append({"pillar": ms.pillar, "pillar_label": ms.label, "metric": m.key, "metric_id": m.metric_id,
                         "label": m.label, "group": m.group, "direction": m.direction, "period": m.period,
                         "source": m.source, "available": m.available,
                         "metros_with_value": int(coverage.get(m.key, 0)),
                         "baseline_weight_entered": entered.get(m.key, 0.0),
                         "baseline_weight_in_pillar": round(float(eff.get(m.key, 0.0)), 6)})
    return pd.DataFrame(rows)
