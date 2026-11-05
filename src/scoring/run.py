"""One command for the whole score: build every pillar's metrics, write the pillar files, then score the
baseline and every scenario.

    python -m src.scoring.run                    # metrics -> pillar files -> baseline + all scenarios
    python -m src.scoring.run --group strategy   # ...only the strategy scenarios
    python -m src.scoring.run --pillars-only     # metrics and pillar files only

Each pillar builder (src/scoring/pillarN.py) only gathers metrics: raw values for every metric it defines,
each with its direction. How metrics are built is set in config/settings.toml; how much they count is set in
the weights files. Adding a metric = add it to its pillar builder; using it = give it a weight.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src import config
from src import market_attractiveness as ma
from src.scoring import engine, pillar1, pillar2, pillar3, pillar4
from src.scoring.common import load_settings, load_tables

BUILDERS = {"pillar1": pillar1.build, "pillar2": pillar2.build, "pillar3": pillar3.build, "pillar4": pillar4.build}
TABLES = ("msa_year", "bank_msa_year", "bank_quarter", "msa_naics_year")


def build_metric_sets(root=config.ROOT, settings_file=None) -> dict:
    """Every pillar's MetricSet (raw values of all its metrics) from data/processed."""
    settings = load_settings(settings_file)
    tables = load_tables(Path(root) / "data" / "processed", names=TABLES)
    return {key: build(tables, settings[key]) for key, build in BUILDERS.items()}


def write_pillar_files(root=config.ROOT, out_dir=None, weights_file=None) -> dict:
    """Pillar files and the metric catalog (for reading, the app and the dashboard)."""
    root = Path(root)
    weights_cfg = ma.load_weights(weights_file or root / "weights" / "baseline.toml")
    sets = ma.metric_sets(root)
    out_dir = Path(out_dir or root / "outputs" / "pillar_scores")
    written = {k: engine.write_pillar_file(ms, weights_cfg, out_dir) for k, ms in sets.items()}
    engine.catalog(sets, weights_cfg).to_csv(out_dir / "metric_catalog.csv", index=False)
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the metrics and run the final score and scenarios.")
    ap.add_argument("--pillars-only", action="store_true", help="metrics and pillar files only")
    ap.add_argument("--group", choices=["sensitivity", "strategy", "all"], default="all")
    args = ap.parse_args(argv)
    try:
        for key, (csv_path, _) in write_pillar_files().items():
            print(f"{key}: wrote {csv_path.relative_to(config.ROOT)}")
    except (ValueError, ma.GateError) as e:
        print(e, file=sys.stderr)
        return 1
    print("wrote outputs/pillar_scores/metric_catalog.csv")
    if args.pillars_only:
        return 0
    from src import compare_scenarios
    return compare_scenarios.main(["--run", "--group", args.group])


if __name__ == "__main__":
    sys.exit(main())
