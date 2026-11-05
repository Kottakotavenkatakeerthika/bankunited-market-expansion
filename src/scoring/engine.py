"""Scoring engine: metric percentiles and pillar scores from a pillar's raw metrics.

score_pillar() applies the same rules as the pillar notebooks:
  - each metric becomes an oriented percentile among the metros that have it;
  - the available-data score is the weighted mean of the percentiles a metro has, weights rescaled
    over those metrics; the complete score needs every weighted metric;
  - rank is among complete metros only.

write_export() writes the notebook-format files (outputs/pillar_scores/<pillar>_scores.csv and
<pillar>_run.json) that src/market_attractiveness.py reads today. It goes away once the final score
reads metric tables directly.
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


def score_pillar(ms: MetricSet, weights: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(results, percentiles) for the weighted metrics, in the notebooks' layout."""
    active = list(weights.index)
    directions = {k: m.direction for k, m in ms.registry.items()}
    P = oriented_percentiles(ms.values[active], directions)
    have = P.notna()
    cover = have.mul(weights, axis=1).sum(axis=1)
    available = P.fillna(0).mul(weights, axis=1).sum(axis=1) / cover.where(cover > 0)
    complete = available.where(have.all(axis=1))
    results = pd.DataFrame({
        "msa": ms.titles.reindex(P.index),
        "complete_score": complete,
        "rank": complete.rank(ascending=False, method="min"),
        "available_score": available,
        "valid_metrics": have.sum(axis=1),
        "weight_coverage": cover,
        "missing_metrics": have.apply(lambda r: ", ".join(c for c in r.index if not r[c]), axis=1),
    })
    return results, P


def write_export(ms: MetricSet, weights_cfg: dict, out_dir: Path | None = None) -> tuple[Path, Path]:
    """Write <pillar>_scores.csv and <pillar>_run.json as the pillar notebooks do."""
    weights, _ = pillar_weights(ms, weights_cfg)
    results, P = score_pillar(ms, weights)
    active = list(weights.index)
    table = (results.join(ms.values[active].add_prefix("raw_")).join(P[active].add_prefix("pct_"))
             .sort_values(["complete_score", "available_score"], ascending=False))
    out_dir = Path(out_dir or config.ROOT / "outputs" / "pillar_scores")
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path, json_path = out_dir / f"{ms.pillar}_scores.csv", out_dir / f"{ms.pillar}_run.json"
    table.rename_axis("cbsa_code").to_csv(csv_path)
    entered = weights_cfg["metrics"].get(ms.pillar, {})
    run = {
        "pillar": ms.pillar,
        "run_date": str(pd.Timestamp.today().date()),
        "effective_weights": weights.round(6).to_dict(),
        "entered_weights": {k: float(v) / 100 for k, v in entered.items()},
        "settings": ms.settings,
        "complete_msas": int(results["rank"].notna().sum()),
        "not_available": ms.not_available,
        "built_by": "src.scoring",
    }
    ids = {m.key: m.metric_id for m in ms.metrics if m.metric_id}
    if ids:
        run["metric_ids"] = ids
    json_path.write_text(json.dumps(run, indent=2, default=str))
    return csv_path, json_path
