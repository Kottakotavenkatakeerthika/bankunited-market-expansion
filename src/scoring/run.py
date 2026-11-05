"""One command for the whole score: build every pillar's metrics, write the pillar files, then score the
baseline and every scenario.

    python -m src.scoring.run                    # metrics -> pillar files -> baseline + all scenarios
    python -m src.scoring.run --group strategy   # ...only the strategy scenarios
    python -m src.scoring.run --pillars-only     # metrics and pillar files only
    python -m src.scoring.run --as-of 2025-06-30 # point in time: data released by then -> outputs/as_of/<date>/

Each pillar builder (src/scoring/pillarN.py) only gathers metrics: raw values for every metric it defines,
each with its direction. How metrics are built is set in config/settings.toml; how much they count is set in
the weights files. Adding a metric = add it to its pillar builder; using it = give it a weight.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from src import config
from src import market_attractiveness as ma
from src.scoring import engine, pillar1, pillar2, pillar3, pillar4
from src.scoring.common import load_settings, load_tables

BUILDERS = {"pillar1": pillar1.build, "pillar2": pillar2.build, "pillar3": pillar3.build, "pillar4": pillar4.build}
TABLES = ("msa_year", "bank_msa_year", "bank_quarter", "msa_naics_year")


def build_metric_sets(root=config.ROOT, settings_file=None, as_of=None) -> dict:
    """Every pillar's MetricSet (raw values of all its metrics) from data/processed.
    With as_of, the settings move to what was released by that date (src/scoring/asof.py)."""
    settings = load_settings(settings_file)
    tables = load_tables(Path(root) / "data" / "processed", names=TABLES)
    if as_of is not None:
        from src.scoring.asof import settings_as_of
        settings, report = settings_as_of(settings, as_of, tables)
        for key in BUILDERS:
            settings[key]["_as_of"] = report
    sets = {key: build(tables, settings[key]) for key, build in BUILDERS.items()}
    # composite metrics, which combine metrics from more than one pillar
    sets["pillar3"] = pillar3.add_competition_growth(sets["pillar3"], sets, settings["pillar3"])
    return sets


def write_pillar_files(root=config.ROOT, out_dir=None, weights_file=None, as_of=None) -> dict:
    """Pillar files and the metric catalog (for reading, the app and the dashboard)."""
    root = Path(root)
    weights_cfg = ma.load_weights(weights_file or root / "weights" / "baseline.toml")
    sets = ma.metric_sets(root, as_of)
    if out_dir is None and as_of is not None:
        out_dir = root / "outputs" / "as_of" / str(pd.Timestamp(as_of).date()) / "pillar_scores"
    out_dir = Path(out_dir or root / "outputs" / "pillar_scores")
    written = {k: engine.write_pillar_file(ms, weights_cfg, out_dir) for k, ms in sets.items()}
    engine.catalog(sets, weights_cfg).to_csv(out_dir / "metric_catalog.csv", index=False)
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the metrics and run the final score and scenarios.")
    ap.add_argument("--pillars-only", action="store_true", help="metrics and pillar files only")
    ap.add_argument("--group", choices=["sensitivity", "strategy", "all"], default="all")
    ap.add_argument("--as-of", help="decision date (YYYY-MM-DD): data released by then; writes outputs/as_of/<date>/")
    args = ap.parse_args(argv)
    try:
        for key, (csv_path, _) in write_pillar_files(as_of=args.as_of).items():
            print(f"{key}: wrote {csv_path.relative_to(config.ROOT)}")
    except (ValueError, ma.GateError) as e:
        print(e, file=sys.stderr)
        return 1
    print(f"wrote {csv_path.parent.relative_to(config.ROOT).as_posix()}/metric_catalog.csv")
    if args.pillars_only:
        return 0
    from src import compare_scenarios
    return compare_scenarios.main(["--run", "--group", args.group] + (["--as-of", args.as_of] if args.as_of else []))


if __name__ == "__main__":
    sys.exit(main())
