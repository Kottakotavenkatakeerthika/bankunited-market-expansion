"""Market Attractiveness: combine the four pillar scores into one score per MSA. Owner: ML pod.

Builds each pillar from its metric builder in src/scoring and combines them. Usually run through
`python -m src.scoring.run`, which also writes the pillar files and runs every scenario. Directly:

    python -m src.market_attractiveness                                  # weights/baseline.toml, all 4 pillars
    python -m src.market_attractiveness --weights weights/my_case.toml   # a weight scenario, vs the baseline
    python -m src.market_attractiveness --show-weights                   # print the weights and stop

Weights: weights/baseline.toml holds the pillar weights and every metric weight within each pillar; a metric
not listed counts 0. In code (e.g. the app's sliders):
    run(weights={"pillars": {"pillar1": 30, ...}, "metrics": {"pillar1": {"mm_establishments": 40, ...}}})

Inputs: data/processed, through the pillar builders src/scoring/pillar1.py .. pillar4.py (settings in
config/settings.toml). Every pillar uses the same 387 metros (50 states and DC). source="exports" instead
reads notebook-format files in outputs/pillar_scores/ (legacy; kept for the synthetic-input tests).

Outputs (scenario runs add _<scenario name> after market_attractiveness):
    outputs/final_scores/market_attractiveness_scores.csv   one row per MSA
    outputs/final_scores/market_attractiveness_run.json     weights, settings, inputs and the gate report

Method (same conventions as the pillar notebooks):
    1. Pillar score = weighted mean of the pillar's metric percentiles. The complete score needs every
       weighted metric; the available-data score renormalizes over the metrics an MSA has.
    2. Each pillar's score is turned into a percentile (0-100) among the MSAs that have it, so a 25% weight
       gives a pillar 25% of the influence whatever the spread of its raw score. A pillar's complete score is
       used where it exists, otherwise its available-data score if it covers at least MIN_PILLAR_COVERAGE of
       the pillar's weight.
    3. available_score = weighted mean of the pillar percentiles an MSA has (weights renormalized).
       complete_score = the same, only when every pillar in the run is complete for that MSA.
       rank is among complete MSAs only.
    4. best_rank / worst_rank: rank range when each pillar weight alone moves +/-25%, as in the notebooks.

Optional [fill] table in the weights file: metrics listed there count as the FILL_PERCENTILE (50th) where an
MSA has no value, instead of leaving the pillar partial. Filled metrics are listed per MSA in filled_metrics.

This is Market Attractiveness only. The Fit & Feasibility gate (src/bankunited_fit.py) is applied after it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from src import config

# --- Settings -----------------------------------------------------------------------------------------
WEIGHTS_DIR = "weights"
BASELINE = "baseline"         # weights/baseline.toml
# Used only when no weights file exists: equal pillars, each pillar scored as its notebook exported it.
DEFAULT_PILLAR_WEIGHTS = {"pillar1": 0.25, "pillar2": 0.25, "pillar3": 0.25, "pillar4": 0.25}
NORMALIZE = "percentile"      # "percentile" (default) or "none" to average the pillar scores as published
MIN_PILLAR_COVERAGE = 0.50    # a partial pillar score counts only if it covers this share of the pillar's weight
SENSITIVITY = 0.25            # +/- shock to each pillar weight for best_rank / worst_rank
FILL_PERCENTILE = 50.0        # value given to a missing metric listed under [fill] in the weights file
EXAMPLE_CBSA = "16740"        # Charlotte, the pilot
DEFAULT_SOURCE = "metrics"    # "metrics": build pillars from src/scoring; "exports": read notebook-format files (legacy)

# Markets BankUnited serves from offices with no branch, which SOD can't see (same list as the pillar notebooks).
BU_OFFICE_ONLY = {"12060": "Atlanta office", "16740": "Charlotte (entered Jul 2025)", "26420": "Houston office"}
# Entry dates where known (src/bankunited.py; Charlotte announcement 2025-07-17). An as-of run before a date
# doesn't label that market; Houston's office has no date on file, so it is always labelled.
BU_OFFICE_ENTRY = {"12060": "2022-04-07", "16740": "2025-07-17"}


@dataclass(frozen=True)
class Pillar:
    """Where a pillar's export lives and which of its columns hold the shared fields."""
    key: str
    label: str
    notebook: str
    files: tuple[str, ...]          # first one that exists is used, relative to the repo root
    columns: dict[str, str] = field(default_factory=lambda: {
        "msa": "msa", "complete_score": "complete_score", "available_score": "available_score",
        "rank": "rank", "valid_metrics": "valid_metrics", "weight_coverage": "weight_coverage",
        "missing_metrics": "missing_metrics",
    })
    percentile_col: str = "pct_{}"  # column holding a metric's oriented percentile


PILLARS = [
    Pillar("pillar1", "Commercial lending", "pillar1_commercial_lending_1.ipynb",
           ("outputs/pillar_scores/pillar1_scores.csv",)),
    Pillar("pillar2", "Deposits and treasury", "pillar2_deposits_treasury.ipynb",
           ("outputs/pillar_scores/pillar2_scores.csv",)),
    Pillar("pillar3", "Competition and entry windows", "pillar3_competition.ipynb",
           ("outputs/pillar_scores/pillar3_scores.csv",)),
    # Pillar 4 has its own column names and writes next to the notebook by default.
    Pillar("pillar4", "Market quality and durability", "pillar4_market_quality_durability.ipynb",
           ("outputs/pillar_scores/pillar4_scores.csv", "notebooks/pillar4_scores.csv"),
           {"msa": "cbsa_title", "complete_score": "complete_8_score", "available_score": "available_data_score",
            "rank": "complete_8_rank", "valid_metrics": "valid_metrics_out_of_8",
            "weight_coverage": "original_weight_coverage", "missing_metrics": "missing_metrics"},
           percentile_col="{}_percentile"),
]
PILLAR_KEYS = [p.key for p in PILLARS]


class GateError(RuntimeError):
    """An input failed a hard check; the final scores are not written."""


# --- Weights ------------------------------------------------------------------------------------------
def load_weights(path: Path) -> dict:
    """Read a weights TOML: a [pillars] table, plus an optional [pillarN] table of metric weights per pillar."""
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    return normalize_weights({"pillars": cfg.get("pillars", {}), "fill": cfg.get("fill", {}),
                              "universe": cfg.get("universe", {}),
                              "metrics": {k: v for k, v in cfg.items() if k not in ("pillars", "fill", "universe")}},
                             source=str(path))


def normalize_weights(weights: dict | None, source: str = "weights") -> dict:
    """Accept {pillar: w} or {"pillars": {...}, "metrics": {pillar: {metric: w}}, "fill": {pillar: [metric]}};
    check and return the long form."""
    if weights is None:
        weights = {"pillars": DEFAULT_PILLAR_WEIGHTS}
    elif "pillars" not in weights:
        weights = {"pillars": weights}
    pillars = {k: float(v) for k, v in weights["pillars"].items()}
    metrics = {k: {m: float(w) for m, w in v.items()} for k, v in (weights.get("metrics") or {}).items()}
    if set(pillars) != set(PILLAR_KEYS):
        raise ValueError(f"{source}: [pillars] needs one weight for each of {PILLAR_KEYS}; got {sorted(pillars)}")
    unknown = sorted(set(metrics) - set(PILLAR_KEYS))
    if unknown:
        raise ValueError(f"{source}: unknown section(s) {unknown}; use [pillars] and [pillar1]..[pillar4]")
    if any(v < 0 for v in pillars.values()) or any(w < 0 for m in metrics.values() for w in m.values()):
        raise ValueError(f"{source}: weights must be zero or positive")
    if sum(pillars.values()) <= 0:
        raise ValueError(f"{source}: every pillar weight is 0")
    for k, m in metrics.items():
        if m and sum(m.values()) <= 0 and pillars[k] > 0:
            raise ValueError(f"{source}: every metric weight in [{k}] is 0; set the pillar weight to 0 instead")
    fill = weights.get("fill") or {}
    if not isinstance(fill, dict):
        raise ValueError(f"{source}: [fill] must map pillars to lists of metrics, e.g. pillar1 = [\"local_ci_growth\"]")
    for k, ms in fill.items():
        if k not in PILLAR_KEYS:
            raise ValueError(f"{source}: [fill] has unknown pillar {k!r}; use pillar1..pillar4")
        if not isinstance(ms, list) or not all(isinstance(m, str) for m in ms):
            raise ValueError(f"{source}: [fill] {k} must be a list of metric names in quotes")
        if ms and not metrics.get(k):
            raise ValueError(f"{source}: [fill] {k} needs a [{k}] section of metric weights, since filling "
                             f"rebuilds the pillar from its metrics")
    universe = dict(weights.get("universe") or {})
    unknown_u = sorted(set(universe) - {"min_population"})
    if unknown_u:
        raise ValueError(f"{source}: [universe] only takes min_population; got {unknown_u}")
    floor = universe.get("min_population", 0)
    if not isinstance(floor, (int, float)) or isinstance(floor, bool) or floor < 0:
        raise ValueError(f"{source}: [universe] min_population must be a number, 0 or more (0 = off)")
    return {"pillars": pillars, "metrics": metrics, "fill": {k: list(v) for k, v in fill.items() if v},
            "universe": {"min_population": int(floor)}, "universe_set": "min_population" in universe}


def scenario_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "custom"


# Scenario runs are written to a subfolder of outputs/final_scores named for their group
SCENARIO_OUTPUT_DIRS = {"weights/scenarios": "scenario", "weights/strategy": "strategy"}


def scenario_subdir(root: Path, weights_file) -> str | None:
    """'scenario' or 'strategy' for a weights file in one of the scenario folders, else None."""
    if weights_file is None:
        return None
    try:
        folder = Path(weights_file).resolve().parent.relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return None
    return SCENARIO_OUTPUT_DIRS.get(folder)


def output_paths(out_dir: Path, name: str) -> tuple[Path, Path]:
    stem = "market_attractiveness" if name == BASELINE else f"market_attractiveness_{name}"
    return out_dir / f"{stem}_scores.csv", out_dir / f"{stem}_run.json"


# --- Loading and checking -----------------------------------------------------------------------------
def find_file(p: Pillar, root: Path) -> Path | None:
    for rel in p.files:
        if (root / rel).exists():
            return root / rel
    return None


def load_pillar(p: Pillar, path: Path) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Read one pillar export: the shared fields, the metric percentiles, and any hard-check failures."""
    raw = pd.read_csv(path, dtype={"cbsa_code": str})
    missing = [src for src in ["cbsa_code", *p.columns.values()] if src not in raw.columns]
    if missing:
        return pd.DataFrame(), pd.DataFrame(), [f"{p.key}: missing columns {missing} in {path.name}"]
    errors = []
    raw["cbsa_code"] = raw["cbsa_code"].str.strip().str.zfill(5)
    df = raw[["cbsa_code", *p.columns.values()]].rename(columns={v: k for k, v in p.columns.items()})
    if not df["cbsa_code"].str.fullmatch(r"\d{5}").all():
        errors.append(f"{p.key}: cbsa_code values that aren't 5 digits")
    if df["cbsa_code"].duplicated().any():
        errors.append(f"{p.key}: {int(df['cbsa_code'].duplicated().sum())} repeated cbsa_code rows")
    for col in ("complete_score", "available_score", "weight_coverage", "rank"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ("complete_score", "available_score"):
        if ((df[col] < -1e-9) | (df[col] > 100 + 1e-9)).any():
            errors.append(f"{p.key}: {col} outside 0-100")
    both = df["complete_score"].notna()
    if (df.loc[both, "complete_score"] - df.loc[both, "available_score"]).abs().gt(1e-6).any():
        errors.append(f"{p.key}: complete_score differs from available_score where both exist")
    if df["available_score"].notna().sum() < 2:
        errors.append(f"{p.key}: fewer than 2 scored MSAs")

    pre, suf = p.percentile_col.split("{}")
    pct_cols = {c: c[len(pre):len(c) - len(suf)] for c in raw.columns
                if c.startswith(pre) and c.endswith(suf) and len(c) > len(pre) + len(suf)}
    pct = raw.set_index("cbsa_code")[list(pct_cols)].rename(columns=pct_cols).apply(pd.to_numeric, errors="coerce")
    if ((pct < -1e-9) | (pct > 100 + 1e-9)).any().any():
        errors.append(f"{p.key}: metric percentiles outside 0-100")
    return df.set_index("cbsa_code"), pct, errors


def rescore_pillar(key: str, t: pd.DataFrame, pct: pd.DataFrame, metric_weights: dict[str, float],
                   not_available: list[str], fill: list[str] | None = None, warn_unweighted: bool = True):
    """Rebuild a pillar's scores from its metric percentiles with new weights (same rule as the notebooks).

    Metrics in `fill` count as FILL_PERCENTILE where missing. matches_notebook compares the weights only
    (before filling). Returns (table, effective metric weights, matches_notebook, errors, warnings, filled),
    where filled lists the filled metrics per MSA ("" if none).
    """
    fill = fill or []
    errors, warnings = [], []
    if pct.empty:
        return t, None, None, [f"{key}: the export has no metric percentile columns, so its metric weights "
                               f"can't be changed here; delete [{key}] from the weights file"], [], None
    unknown = [m for m in metric_weights if m not in pct.columns and m not in not_available]
    if unknown:
        errors.append(f"{key}: {unknown} are not metrics of this pillar (check the spelling). "
                      f"Metrics: {list(pct.columns)}")
    skipped = [m for m, w in metric_weights.items() if m in not_available and m not in pct.columns and w > 0]
    if skipped:
        warnings.append(f"{key}: {skipped} not available in data/processed; left out and the rest rescaled")
    unweighted = [m for m in pct.columns if m not in metric_weights]
    if unweighted and warn_unweighted:
        warnings.append(f"{key}: exported metrics not in the weights file, so weighted 0: {unweighted}")
    bad_fill = [m for m in fill if m not in pct.columns]
    if bad_fill:
        errors.append(f"{key}: [fill] lists {bad_fill}, which are not metrics of this pillar. Metrics: {list(pct.columns)}")
    w = pd.Series({m: v for m, v in metric_weights.items() if m in pct.columns and v > 0}, dtype=float)
    if w.empty and not errors:
        errors.append(f"{key}: no weighted metric is in the export")
    if errors:
        return t, None, None, errors, warnings, None
    unweighted_fill = [m for m in fill if m not in w.index]
    if unweighted_fill:
        warnings.append(f"{key}: [fill] lists {unweighted_fill}, which have weight 0, so filling them does nothing")
    w = w / w.sum()

    def scores(P):
        have = P.notna()
        cover = have.mul(w, axis=1).sum(axis=1)
        available = P.fillna(0).mul(w, axis=1).sum(axis=1) / cover.where(cover > 0)
        return available.where(have.all(axis=1)), available, cover, have

    P = pct[w.index].reindex(t.index)
    complete, available, _, _ = scores(P)
    matches = bool(np.allclose(available, t["available_score"], atol=1e-6, equal_nan=True)
                   and complete.notna().equals(t["complete_score"].notna()))
    to_fill = [m for m in fill if m in w.index]
    was_missing = P[to_fill].isna()
    P[to_fill] = P[to_fill].fillna(FILL_PERCENTILE)
    complete, available, cover, have = scores(P)
    filled = was_missing.apply(lambda r: ", ".join(c for c in r.index if r[c]), axis=1).reindex(t.index).fillna("")
    out = t.copy()
    out["complete_score"], out["available_score"], out["weight_coverage"] = complete, available, cover
    out["rank"] = complete.rank(ascending=False, method="min")
    out["valid_metrics"] = have.sum(axis=1)
    out["missing_metrics"] = have.apply(lambda r: ", ".join(c for c in r.index if not r[c]), axis=1)
    return out, w, matches, [], warnings, filled


def percentile(s: pd.Series) -> pd.Series:
    """Average-rank percentile (0-100) among non-missing values; same rule as the pillar notebooks."""
    n = s.notna().sum()
    return 100 * (s.rank(method="average") - 1) / (n - 1) if n > 1 else s * np.nan


# --- Scoring ------------------------------------------------------------------------------------------
def pillar_inputs(tables: dict[str, pd.DataFrame], normalize: str, min_coverage: float):
    """Per pillar: the score used, its status, and its (optionally percentiled) value on a 0-100 scale."""
    used, status, scaled = {}, {}, {}
    for key, t in tables.items():
        partial_ok = t["available_score"].where(t["weight_coverage"].fillna(0) >= min_coverage)
        s = t["complete_score"].combine_first(partial_ok)
        used[key] = s
        status[key] = pd.Series(np.select([t["complete_score"].notna(), partial_ok.notna()],
                                          ["complete", "partial"], "missing"), index=t.index)
        scaled[key] = percentile(s) if normalize == "percentile" else s
    return pd.DataFrame(used), pd.DataFrame(status), pd.DataFrame(scaled)


def combine(scaled: pd.DataFrame, status: pd.DataFrame, weights: dict[str, float],
            eligible: pd.Series | None = None) -> pd.DataFrame:
    """Combine pillar percentiles. Only complete metros that are eligible (at or above the size floor) rank."""
    w = pd.Series(weights, dtype=float)[scaled.columns]
    w = w / w.sum()
    have = scaled.notna()
    cover = have.mul(w, axis=1).sum(axis=1)
    available = scaled.fillna(0).mul(w, axis=1).sum(axis=1) / cover.where(cover > 0)
    complete = available.where(status.eq("complete").all(axis=1))
    if eligible is not None:
        complete = complete.where(eligible.reindex(complete.index).fillna(False).astype(bool))
    return pd.DataFrame({
        "complete_score": complete,
        "rank": complete.rank(ascending=False, method="min"),
        "available_score": available,
        "pillars_complete": status.eq("complete").sum(axis=1),
        "pillars_scored": have.sum(axis=1),
        "weight_coverage": cover,
    })


def rank_ranges(scaled, status, weights, shock, eligible=None):
    ranks = [combine(scaled, status, weights, eligible)["rank"]]
    for k in scaled.columns:
        for s in (-shock, shock):
            w = dict(weights)
            w[k] = weights[k] * (1 + s)
            ranks.append(combine(scaled, status, w, eligible)["rank"])
    R = pd.concat(ranks, axis=1)
    return pd.DataFrame({"best_rank": R.min(axis=1), "worst_rank": R.max(axis=1)})


def bankunited_markets(root: Path, sod_year: int | None = None, as_of=None) -> pd.Series:
    """Label BankUnited's markets: SOD branch markets (in sod_year, default the latest) plus office-only markets
    (those entered by as_of, when given)."""
    labels = {}
    path = root / "data" / "processed" / "msa_year.parquet"
    if path.exists():
        m = pd.read_parquet(path, columns=["cbsa_code", "year", "bankunited_sod_offices_count"])
        latest = m[m.year == (sod_year or m.year.max())]
        for c in latest.loc[latest.bankunited_sod_offices_count.fillna(0) > 0, "cbsa_code"]:
            labels[str(c)] = "branch market"
    for c, label in BU_OFFICE_ONLY.items():
        if as_of is None or c not in BU_OFFICE_ENTRY or pd.Timestamp(BU_OFFICE_ENTRY[c]) <= pd.Timestamp(as_of):
            labels.setdefault(c, label)
    return pd.Series(labels, name="bankunited_market", dtype="string")


def population(root: Path, year: int) -> pd.Series:
    """Census PEP population by metro for one year (for the size floor)."""
    m = pd.read_parquet(root / "data" / "processed" / "msa_year.parquet",
                        columns=["cbsa_code", "year", "pep_population_count"])
    return m[m.year == year].set_index("cbsa_code")["pep_population_count"].astype(float)


def weight_table(report: dict) -> pd.DataFrame:
    """Each pillar's and metric's weight, and its nominal share of the final score (pillar x metric)."""
    rows = []
    for k, pw in report["weights_effective"].items():
        mw = report["metric_weights_effective"].get(k)
        if not mw:
            rows.append((k, "(notebook score as exported)", pw, np.nan, pw))
        for m, w in (mw or {}).items():
            rows.append((k, m, pw, w, pw * w))
    return pd.DataFrame(rows, columns=["pillar", "metric", "pillar_weight", "weight_in_pillar", "share_of_final"])


# --- Pillar inputs built from src/scoring ------------------------------------------------------------
_METRIC_CACHE: dict = {}


def metric_sets(root: Path, as_of=None) -> dict:
    """Every pillar's MetricSet, built once per process for a given repo, settings file and as-of date.
    With as_of, every year and window is moved to what was released by that date (src/scoring/asof.py)."""
    from src.scoring.run import build_metric_sets
    from src.scoring.common import SETTINGS_FILE
    settings = Path(root) / "config" / "settings.toml"
    settings = settings if settings.exists() else SETTINGS_FILE
    key = (str(Path(root).resolve()), str(settings), settings.stat().st_mtime, str(as_of))
    if key not in _METRIC_CACHE:
        if len(_METRIC_CACHE) > 4:
            _METRIC_CACHE.clear()
        _METRIC_CACHE[key] = build_metric_sets(root, settings, as_of=as_of)
    return _METRIC_CACHE[key]


def pillar_from_metrics(ms) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(table, metric percentiles) for one MetricSet, in the shape rescore_pillar expects."""
    from src.scoring.common import oriented_percentiles
    available = [m.key for m in ms.metrics if m.available]
    pct = oriented_percentiles(ms.values[available], {m.key: m.direction for m in ms.metrics})
    t = pd.DataFrame({"msa": ms.titles.reindex(pct.index), "complete_score": np.nan, "available_score": np.nan,
                      "weight_coverage": np.nan, "rank": np.nan}, index=pct.index)
    t.index.name = "cbsa_code"
    return t, pct


# --- Run ----------------------------------------------------------------------------------------------
def run(root: Path = config.ROOT, weights: dict | None = None, weights_file: Path | str | None = None,
        name: str | None = None, normalize: str = NORMALIZE, min_coverage: float = MIN_PILLAR_COVERAGE,
        allow_missing: bool = False, out_dir: Path | None = None, write: bool = True,
        compare_baseline: bool = True, source: str | None = None, as_of=None,
        min_population: int | None = None) -> tuple[pd.DataFrame, dict]:
    """Build (or read) the pillars, score and combine them, and (if write) save the final table and run report.

    source "metrics" (default) builds every pillar from its metric builder in src/scoring; "exports" reads
    the notebook-format files in outputs/pillar_scores/ (legacy, kept for the synthetic-input tests).
    as_of (a date) rebuilds every pillar from what was released by then (metrics source only).
    min_population overrides the weights file's [universe] min_population (0 = no size floor).

    Weights come from `weights` (a dict), else `weights_file`, else weights/baseline.toml under root, else
    equal pillar weights with each pillar scored as its notebook exported it.
    """
    root = Path(root)
    input_source = source or DEFAULT_SOURCE
    if input_source not in {"metrics", "exports"}:
        raise ValueError("source must be 'metrics' or 'exports'")
    if normalize not in {"percentile", "none"}:
        raise ValueError("normalize must be 'percentile' or 'none'")
    if weights is not None:
        cfg, source = normalize_weights(weights), "passed in code"
        name = name or "custom"
    else:
        path = Path(weights_file) if weights_file else root / WEIGHTS_DIR / f"{BASELINE}.toml"
        if not path.is_absolute():
            path = (root / path) if (root / path).exists() else path
        if path.exists():
            cfg = load_weights(path)
            source = path.resolve().relative_to(root.resolve()).as_posix() if path.resolve().is_relative_to(
                root.resolve()) else path.resolve().as_posix()
            name = name or path.stem
        elif weights_file:
            raise FileNotFoundError(f"weights file not found: {weights_file}")
        else:
            cfg, source = normalize_weights(None), "default (no weights file)"
            name = name or BASELINE
    name = scenario_name(name)

    errors, warnings, inputs, tables, metric_eff, filled, fill_report = [], [], {}, {}, {}, {}, {}
    processed = root / "data" / "processed" / "msa_year.parquet"
    if as_of is not None and input_source != "metrics":
        raise ValueError("as_of needs source 'metrics'")
    sets = metric_sets(root, as_of) if input_source == "metrics" else {}
    for p in PILLARS:
        if cfg["pillars"][p.key] == 0:
            warnings.append(f"{p.key}: weight is 0, left out")
            continue
        if input_source == "metrics":
            if not cfg["metrics"].get(p.key):
                errors.append(f"{p.key}: the weights file needs a [{p.key}] table of metric weights")
                continue
            ms = sets[p.key]
            df, pct = pillar_from_metrics(ms)
            df, eff, _, errs, warns, fl = rescore_pillar(p.key, df, pct, cfg["metrics"][p.key], ms.not_available,
                                                         cfg["fill"].get(p.key), warn_unweighted=False)
            errors += errs
            warnings += warns
            if errs:
                continue
            metric_eff[p.key] = eff.round(6).to_dict()
            if cfg["fill"].get(p.key):
                filled[p.key] = fl
                n = int((fl != "").sum())
                fill_report[p.key] = {"metrics": cfg["fill"][p.key], "msas_filled": n}
                warnings.append(f"{p.key}: {n} MSAs had missing {', '.join(cfg['fill'][p.key])} "
                                f"set to the {FILL_PERCENTILE:g}th percentile")
            tables[p.key] = df
            inputs[p.key] = {"source": f"src.scoring.{p.key}", "rows": len(df),
                             "complete": int(df["complete_score"].notna().sum()),
                             "metrics_defined": len(ms.metrics), "metrics_weighted": len(eff),
                             "settings": ms.settings}
            continue
        path = find_file(p, root)
        if path is None:
            msg = f"{p.key} ({p.label}): no export found; run notebooks/{p.notebook} (looked in {', '.join(p.files)})"
            (warnings if allow_missing else errors).append(msg)
            continue
        df, pct, errs = load_pillar(p, path)
        if errs:
            errors += errs
            continue
        run_json = path.with_name(f"{p.key}_run.json")
        meta = json.loads(run_json.read_text()) if run_json.exists() else {}
        matches = None
        if cfg["metrics"].get(p.key):
            df, eff, matches, errs, warns, fl = rescore_pillar(p.key, df, pct, cfg["metrics"][p.key],
                                                              meta.get("not_available", []),
                                                              cfg["fill"].get(p.key))
            errors += errs
            warnings += warns
            if errs:
                continue
            metric_eff[p.key] = eff.round(6).to_dict()
            if not matches:
                warnings.append(f"{p.key}: metric weights differ from the notebook's last run; pillar rescored here")
            if cfg["fill"].get(p.key):
                filled[p.key] = fl
                n = int((fl != "").sum())
                fill_report[p.key] = {"metrics": cfg["fill"][p.key], "msas_filled": n}
                warnings.append(f"{p.key}: {n} MSAs had missing {', '.join(cfg['fill'][p.key])} "
                                f"set to the {FILL_PERCENTILE:g}th percentile")
        tables[p.key] = df
        inputs[p.key] = {"file": path.relative_to(root).as_posix(), "rows": len(df),
                         "complete": int(df["complete_score"].notna().sum()),
                         "matches_notebook_weights": matches,
                         "notebook_run_date": meta.get("run_date"),
                         "notebook_weights": meta.get("effective_weights")}
        if processed.exists() and path.stat().st_mtime < processed.stat().st_mtime:
            warnings.append(f"{p.key}: export is older than data/processed/msa_year.parquet; rerun the notebook")

    # Need two pillars, unless the weights deliberately use fewer (others set to 0): then all weighted ones.
    weighted = sum(1 for p in PILLARS if cfg["pillars"][p.key] > 0)
    if len(tables) < min(2, weighted) and not errors:
        errors.append(f"only {len(tables)} pillar(s) available; need at least {min(2, weighted)}")
    if errors:
        raise GateError("Integration gate failed:\n  - " + "\n  - ".join(errors))

    # Universe: every MSA any pillar lists, with a warning for those some pillars leave out.
    universe = sorted(set().union(*(t.index for t in tables.values())))
    for key, t in tables.items():
        absent = len(set(universe) - set(t.index))
        if absent:
            warnings.append(f"{key}: {absent} MSAs listed by other pillars are not in this export")
        tables[key] = t.reindex(universe)

    run_weights = {k: cfg["pillars"][k] for k in tables}
    used, status, scaled = pillar_inputs(tables, normalize, min_coverage)
    # A scenario file without [universe] uses the baseline's size floor, so changing it in one place applies to all.
    if min_population is not None:
        floor = int(min_population)
    elif cfg.get("universe_set") or not (root / WEIGHTS_DIR / f"{BASELINE}.toml").exists():
        floor = cfg["universe"]["min_population"]
    else:
        floor = load_weights(root / WEIGHTS_DIR / f"{BASELINE}.toml")["universe"]["min_population"]
    pop_year = int(sets["pillar4"].settings["end_year"]) if sets else None
    pop = None
    if floor > 0 or sets:
        if not (root / "data" / "processed" / "msa_year.parquet").exists():
            raise GateError("a size floor needs data/processed/msa_year.parquet for population")
        if pop_year is None:
            pop_year = int(pd.read_parquet(root / "data" / "processed" / "msa_year.parquet", columns=["year"]).year.max())
        pop = population(root, pop_year).reindex(universe)
    eligible = (pop >= floor) if floor > 0 else None
    result = combine(scaled, status, run_weights, eligible).join(
        rank_ranges(scaled, status, run_weights, SENSITIVITY, eligible))
    wn = pd.Series(run_weights) / sum(run_weights.values())

    title = pd.concat([t["msa"] for t in tables.values()], axis=1).bfill(axis=1).iloc[:, 0]
    out = pd.DataFrame({"msa": title}).join(result)
    all_complete = status.eq("complete").all(axis=1).reindex(out.index)
    below = (pop < floor).reindex(out.index).fillna(False) if floor > 0 else pd.Series(False, index=out.index)
    out["coverage_status"] = np.select(
        [out.complete_score.notna(), all_complete & below, out.pillars_scored > 0],
        [f"Complete ({len(tables)}/{len(tables)} pillars)", f"Below size floor ({floor:,})", "Partial"],
        "No pillar scores")
    if pop is not None:
        out["population"] = pop.reindex(out.index)
    out["below_size_floor"] = below
    out["missing_or_partial_pillars"] = status.apply(
        lambda r: ", ".join(f"{k} {v}" for k, v in r.items() if v != "complete"), axis=1)
    if filled:
        fl = pd.DataFrame({k: v.reindex(universe).fillna("") for k, v in filled.items()})
        out["filled_metrics"] = fl.apply(lambda r: "; ".join(f"{k}: {v}" for k, v in r.items() if v), axis=1)
    for k in tables:
        out[f"{k}_score"] = used[k]
        out[f"{k}_status"] = status[k]
        out[f"{k}_pillar_rank"] = tables[k]["rank"]
        if normalize == "percentile":
            out[f"{k}_percentile"] = scaled[k]
        out[f"{k}_points"] = scaled[k] * wn[k]   # the points sum to complete_score for complete MSAs
    out = out.join(bankunited_markets(root, int(sets["pillar3"].settings["score_year"]) if sets else None, as_of))
    out.index.name = "cbsa_code"

    baseline_file = root / WEIGHTS_DIR / f"{BASELINE}.toml"
    compared = compare_baseline and name != BASELINE and baseline_file.exists()
    if compared:
        base, _ = run(root, weights_file=baseline_file, normalize=normalize, min_coverage=min_coverage,
                      allow_missing=allow_missing, write=False, compare_baseline=False,
                      source=input_source, as_of=as_of, min_population=min_population)
        out["baseline_rank"] = base["rank"].reindex(out.index)
        # Rank change among MSAs complete in both runs, so MSAs entering or leaving the complete set
        # (e.g. when a metric with gaps is weighted 0) don't shift everyone else. Positive = moved up.
        common = out["complete_score"].notna() & out["baseline_rank"].notna()
        now = out.loc[common, "complete_score"].rank(ascending=False, method="min")
        before = base.loc[common[common].index, "complete_score"].rank(ascending=False, method="min")
        out["rank_change"] = (before - now).reindex(out.index)
        report_extra = {"entered_complete_set": int((out["complete_score"].notna() & out["baseline_rank"].isna()).sum()),
                        "left_complete_set": int((out["complete_score"].isna() & out["baseline_rank"].notna()).sum())}
    else:
        report_extra = {}
    out = out.sort_values(["complete_score", "available_score"], ascending=False)

    report = {
        "run_date": str(pd.Timestamp.today().date()),
        "score": "Market Attractiveness (Fit & Feasibility gate not applied)",
        "scenario": name,
        "weights_source": source,
        "pillars_in_run": list(tables),
        "pillars_missing": [k for k in PILLAR_KEYS if k not in tables and cfg["pillars"][k] > 0],
        "weights_entered": cfg,
        "weights_effective": wn.round(6).to_dict(),
        "metric_weights_effective": metric_eff,
        "fill": {"percentile": FILL_PERCENTILE, "pillars": fill_report} if fill_report else None,
        "compared_to_baseline": compared,
        **report_extra,
        "settings": {"normalize": normalize, "min_pillar_coverage": min_coverage, "sensitivity": SENSITIVITY,
                     "source": input_source},
        "universe": {"min_population": floor, "population_year": pop_year,
                     "below_size_floor": int((all_complete & below).sum())},
        "as_of": sets["pillar1"].settings.get("_as_of") if sets else None,
        "inputs": inputs,
        "msas": len(out),
        "complete_msas": int(out.complete_score.notna().sum()),
        "warnings": warnings,
    }
    if write:
        if out_dir is None:
            out_dir = root / "outputs" / "final_scores"
            sub = scenario_subdir(root, weights_file)
            if sub:
                out_dir = out_dir / sub
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_path, json_path = output_paths(out_dir, name)
        out.to_csv(csv_path)
        json_path.write_text(json.dumps(report, indent=2, default=str))
        report["written"] = [csv_path.relative_to(root).as_posix() if csv_path.is_relative_to(root) else str(csv_path),
                             json_path.name]
    return out, report


def summary(out: pd.DataFrame, report: dict, n: int = 15) -> str:
    lines = [f"Market Attractiveness [{report['scenario']}]: {report['complete_msas']} of {report['msas']} MSAs "
             f"complete on {len(report['pillars_in_run'])} pillars ({', '.join(report['pillars_in_run'])})",
             f"weights: {report['weights_source']}"]
    if report["pillars_missing"]:
        lines.append(f"WARNING: scored WITHOUT {', '.join(report['pillars_missing'])}; not a final four-pillar score")
    lines += [f"warning: {w}" for w in report["warnings"]]
    cols = ["msa", "complete_score", "rank", "best_rank", "worst_rank"]
    if report["compared_to_baseline"]:
        cols += ["baseline_rank", "rank_change"]
    lines += ["", f"Top {n}:", out[cols].head(n).round(1).to_string()]
    bu = out[out.bankunited_market.notna()]
    bu_cols = cols + ["bankunited_market"] + (["filled_metrics"] if "filled_metrics" in out else [])
    lines += ["", "BankUnited markets:", bu[bu_cols].round(1).to_string()]
    if report["compared_to_baseline"]:
        movers = out.dropna(subset=["rank_change"]).reindex(
            out["rank_change"].abs().dropna().sort_values(ascending=False).index[:10])
        lines += ["", f"Biggest moves vs baseline (among MSAs complete in both runs; "
                      f"{report['entered_complete_set']} MSAs became complete, {report['left_complete_set']} stopped being complete):",
                  movers[["msa", "baseline_rank", "rank", "rank_change"]].to_string()]
    if EXAMPLE_CBSA in out.index:
        r = out.loc[EXAMPLE_CBSA]
        parts = [f"{k} {r[f'{k}_points']:.1f}" for k in report["pillars_in_run"] if pd.notna(r[f"{k}_points"])]
        lines += ["", f"{r['msa']}: points by pillar: {', '.join(parts)}"]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Combine the four pillar scores into Market Attractiveness.")
    ap.add_argument("--weights", help="weights TOML (default weights/baseline.toml)")
    ap.add_argument("--name", help="scenario name for the output files (default: the weights file's name)")
    ap.add_argument("--allow-missing", action="store_true", help="score on the pillars that exist")
    ap.add_argument("--normalize", choices=["percentile", "none"], default=NORMALIZE)
    ap.add_argument("--show-weights", action="store_true", help="print the effective weights and stop")
    ap.add_argument("--min-population", type=int, help="size floor: metros below it are scored, not ranked (0 = off)")
    ap.add_argument("--as-of", help="decision date (YYYY-MM-DD): use only data released by then")
    args = ap.parse_args(argv)
    try:
        out, report = run(weights_file=args.weights, name=args.name, allow_missing=args.allow_missing,
                          min_population=args.min_population, as_of=args.as_of,
                          normalize=args.normalize, write=not args.show_weights)
    except (GateError, ValueError, FileNotFoundError) as e:
        print(e, file=sys.stderr)
        return 1
    table = weight_table(report)
    if args.show_weights:
        with pd.option_context("display.float_format", "{:.1%}".format, "display.max_rows", 100):
            print(table.to_string(index=False))
        return 0
    print(summary(out, report))
    print(f"\nwrote {report['written'][0]} and {report['written'][1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
