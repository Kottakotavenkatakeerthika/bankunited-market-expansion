"""Metric sensitivity: how much the final ranking depends on each scored metric. Owner: ML pod.

For every metric with a weight in the weights file, two tests, each a full run of
src.market_attractiveness with one metric weight changed (gap filling, the size floor and the Fit filters
apply exactly as in the baseline):

1. Drop: the metric's weight is set to 0; the rest of its pillar rescales.
2. Weight +/-25%: its weight is raised and lowered by a quarter, other weights unchanged.
   "Biggest rank change" is the larger of the two runs; "metros moving more than 5 places" counts metros
   that move more than 5 places in either run.

Rank changes compare ranked metros only (complete and passing the size floor and any Fit filter), the same
ranks as outputs/final_scores/market_attractiveness_scores.csv.

    python -m src.pillar_sensitivity                                        # baseline weights
    python -m src.pillar_sensitivity --weights weights/strategy/cre_led.toml
    python -m src.pillar_sensitivity --as-of 2025-06-30                     # point in time

Output, one row per weighted metric:
    outputs/sensitivity/pillar_metric_sensitivity.csv                  (baseline)
    outputs/sensitivity/pillar_metric_sensitivity_<scenario>.csv       (--weights)
    outputs/as_of/<date>/sensitivity/...                               (--as-of; not committed)
"""
from __future__ import annotations

import argparse
import copy
import sys
import tomllib
from pathlib import Path

import pandas as pd

from src import config
from src import market_attractiveness as ma

WEIGHT_CHANGE = 0.25          # the +/- test
TOP_N = 25
MOVE_THRESHOLDS = (5, 10, 20)
OUTPUT_NAME = "pillar_metric_sensitivity"

PILLAR_LABELS = {"pillar1": "1 Lending", "pillar2": "2 Deposits", "pillar3": "3 Competition",
                 "pillar4": "4 Market quality"}


# --- Weights ------------------------------------------------------------------------------------------
def read_weights(root: Path, weights_file: Path | str | None = None) -> tuple[dict, str]:
    """A weights TOML as the dict that ma.run(weights=...) takes, and the scenario name.

    Keeps exactly what the file sets, so [universe], [fit] and [options] inherit from the baseline the same
    way they do when the file itself is run.
    """
    path = Path(weights_file) if weights_file else root / ma.WEIGHTS_DIR / f"{ma.BASELINE}.toml"
    if not path.is_absolute() and (root / path).exists():
        path = root / path
    if not path.exists():
        raise FileNotFoundError(f"weights file not found: {path}")
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    weights = {"pillars": raw.get("pillars", {}),
               "metrics": {k: v for k, v in raw.items() if k in ma.PILLAR_KEYS},
               "fill": raw.get("fill", {})}
    for key in ("universe", "fit", "options"):
        if key in raw:
            weights[key] = raw[key]
    ma.normalize_weights(weights, source=str(path))   # fail early with the engine's own messages
    return weights, path.stem


def scored_metrics(weights: dict) -> list[tuple[str, str]]:
    """(pillar, metric) for every metric with weight > 0 in a pillar with weight > 0, in file order."""
    return [(p, m) for p in ma.PILLAR_KEYS if float(weights["pillars"].get(p, 0)) > 0
            for m, w in weights["metrics"].get(p, {}).items() if float(w) > 0]


def shares(weights: dict) -> dict[tuple[str, str], float]:
    """Each scored metric's nominal share of the final score (pillar share x share within the pillar)."""
    pw = {p: float(w) for p, w in weights["pillars"].items()}
    total = sum(pw.values())
    out = {}
    for p, m in scored_metrics(weights):
        mw = {k: float(v) for k, v in weights["metrics"][p].items()}
        out[(p, m)] = pw[p] / total * mw[m] / sum(mw.values())
    return out


def with_metric_weight(weights: dict, pillar: str, metric: str, factor: float) -> dict:
    w = copy.deepcopy(weights)
    w["metrics"][pillar][metric] = float(w["metrics"][pillar][metric]) * factor
    return w


# --- Comparison ---------------------------------------------------------------------------------------
def rank_changes(base: pd.Series, new: pd.Series) -> pd.Series:
    """Absolute rank change for metros ranked in both runs."""
    both = pd.concat([base, new], axis=1, keys=["base", "new"]).dropna()
    return (both["new"] - both["base"]).abs()


def compare(base: pd.Series, new: pd.Series, top_n: int = TOP_N) -> dict:
    both = pd.concat([base, new], axis=1, keys=["base", "new"]).dropna()
    change = (both["new"] - both["base"]).abs()
    out = {"biggest": int(change.max()) if len(change) else 0,
           "typical": float(change.median()) if len(change) else 0.0,
           "similarity": float(both["base"].corr(both["new"], method="spearman")),
           "top_kept": len(set(both.index[both["base"] <= top_n]) & set(both.index[both["new"] <= top_n]))}
    for t in MOVE_THRESHOLDS:
        out[f"over_{t}"] = int((change > t).sum())
    return out


# --- Run ----------------------------------------------------------------------------------------------
def _ranks(root: Path, weights: dict, as_of) -> pd.Series:
    out, _ = ma.run(root=root, weights=weights, write=False, compare_baseline=False, as_of=as_of)
    return out["rank"]


def metrics_with_data(root: Path, weights: dict, as_of=None) -> tuple[dict[str, int], int]:
    """Metros with a value for each metric (after [options]), and the size of the universe."""
    cfg = ma.normalize_weights(weights)
    sets = ma.apply_options(ma.metric_sets(root, as_of), ma.resolve_options(root, cfg))
    counts = {m: int(ms.values[m].notna().sum()) for ms in sets.values() for m in ms.values.columns}
    n = max(len(ms.values) for ms in sets.values())
    return counts, n


def sensitivity(root: Path = config.ROOT, weights_file: Path | str | None = None, as_of=None,
                weight_change: float = WEIGHT_CHANGE, top_n: int = TOP_N, progress: bool = False) -> pd.DataFrame:
    """One row per scored metric: the drop test and the +/- weight test."""
    root = Path(root)
    weights, _ = read_weights(root, weights_file)
    base = _ranks(root, weights, as_of)
    counts, n_metros = metrics_with_data(root, weights, as_of)
    share = shares(weights)
    pct = round(weight_change * 100)
    rows = []
    todo = scored_metrics(weights)
    for i, (p, m) in enumerate(todo, 1):
        if progress:
            print(f"  [{i}/{len(todo)}] {p} {m}", file=sys.stderr)
        dropped = compare(base, _ranks(root, with_metric_weight(weights, p, m, 0.0), as_of), top_n)
        up = rank_changes(base, _ranks(root, with_metric_weight(weights, p, m, 1 + weight_change), as_of))
        down = rank_changes(base, _ranks(root, with_metric_weight(weights, p, m, 1 - weight_change), as_of))
        worst = pd.concat([up, down], axis=1).max(axis=1)
        rows.append({
            "Pillar": PILLAR_LABELS.get(p, p),
            "Metric": m,
            "Share of final score (%)": round(share[(p, m)] * 100, 2),
            "Biggest rank change": dropped["biggest"],
            "Metros moving more than 5 places": dropped["over_5"],
            "Metros moving more than 10 places": dropped["over_10"],
            "Metros moving more than 20 places": dropped["over_20"],
            "Typical rank change": round(dropped["typical"], 1),
            "Ranking similarity (1 = identical)": round(dropped["similarity"], 3),
            f"Top {top_n} still in top {top_n}": dropped["top_kept"],
            f"Metros with data (of {n_metros})": counts.get(m),
            f"Biggest rank change, weight ±{pct}%": int(worst.max()) if len(worst) else 0,
            f"Metros moving more than 5 places, weight ±{pct}%": int((worst > 5).sum()),
        })
    return pd.DataFrame(rows)


def output_path(root: Path, name: str, as_of=None) -> Path:
    base = root / "outputs"
    if as_of is not None:
        base = base / "as_of" / str(pd.Timestamp(as_of).date())
    suffix = "" if name == ma.BASELINE else f"_{ma.scenario_name(name)}"
    return base / "sensitivity" / f"{OUTPUT_NAME}{suffix}.csv"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Metric sensitivity of the final Market Attractiveness ranking.")
    ap.add_argument("--weights", help="weights TOML (default weights/baseline.toml)")
    ap.add_argument("--as-of", help="decision date (YYYY-MM-DD): use only data released by then")
    ap.add_argument("--weight-change", type=float, default=WEIGHT_CHANGE, help="the +/- weight test (default 0.25)")
    ap.add_argument("--top-n", type=int, default=TOP_N)
    ap.add_argument("--out", type=Path, help="output CSV (default outputs/sensitivity/...)")
    args = ap.parse_args(argv)
    root = config.ROOT
    try:
        _, name = read_weights(root, args.weights)
        table = sensitivity(root, args.weights, args.as_of, args.weight_change, args.top_n, progress=True)
    except (ma.GateError, ValueError, FileNotFoundError) as e:
        print(e, file=sys.stderr)
        return 1
    out = args.out or output_path(root, name, args.as_of)
    out.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(out, index=False, encoding="utf-8-sig")   # utf-8-sig so Excel shows the ± sign
    shown = out.relative_to(root) if out.is_relative_to(root) else out
    print(f"wrote {shown} ({len(table)} metrics)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
