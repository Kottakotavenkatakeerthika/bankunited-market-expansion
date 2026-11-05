"""Build every ported pillar's metrics and write its export.

    python -m src.scoring.run                 # all ported pillars, then nothing else
    python -m src.scoring.run --then-score    # ...then the final score and every scenario

Pillars not yet ported keep the exports their notebooks wrote.
"""
from __future__ import annotations

import argparse
import sys

from src import config
from src import market_attractiveness as ma
from src.scoring import engine, pillar1, pillar2, pillar3, pillar4
from src.scoring.common import load_settings, load_tables

BUILDERS = {"pillar1": pillar1.build, "pillar2": pillar2.build, "pillar3": pillar3.build, "pillar4": pillar4.build}
EXPORTERS = {"pillar4": pillar4.write_export}   # pillars with their own export layout


def build_all(root=config.ROOT, settings=None, weights_file=None, out_dir=None, pillars=None) -> dict:
    settings = settings or load_settings()
    weights_cfg = ma.load_weights(weights_file or engine.WEIGHTS_FILE)
    tables = load_tables(root / "data" / "processed", names=("msa_year", "bank_msa_year", "bank_quarter", "msa_naics_year"))
    written = {}
    for key, build in BUILDERS.items():
        if pillars and key not in pillars:
            continue
        ms = build(tables, settings[key])
        written[key] = EXPORTERS.get(key, engine.write_export)(ms, weights_cfg, out_dir)
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build pillar metrics and write their exports.")
    ap.add_argument("--then-score", action="store_true", help="then run src.compare_scenarios --run")
    args = ap.parse_args(argv)
    for key, (csv_path, _) in build_all().items():
        print(f"{key}: wrote {csv_path.relative_to(config.ROOT)}")
    if args.then_score:
        from src import compare_scenarios
        return compare_scenarios.main(["--run"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
