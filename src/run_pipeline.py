"""Run the data pipeline end to end: crosswalk -> ingest -> build -> checks.

    python -m src.run_pipeline                    # everything
    python -m src.run_pipeline --sources fdic     # one source, then rebuild and check
    python -m src.run_pipeline --skip-ingest      # rebuild processed tables from interim files
    python -m src.run_pipeline --force-download   # pull raw files again even if already downloaded

Exits with code 1 if any check fails, so a bad build can't slip through.
"""
from __future__ import annotations

import argparse
import importlib
import sys

from src import build_panel, checks, config, crosswalk
from src.utils import ensure_dirs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sources", nargs="+", default=config.SOURCES, choices=config.SOURCES)
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--rebuild-crosswalk", action="store_true")
    args = parser.parse_args(argv)

    ensure_dirs()
    if args.rebuild_crosswalk or not config.COUNTY_CBSA_XWALK.exists():
        crosswalk.build_crosswalk(force_download=args.rebuild_crosswalk)

    if not args.skip_ingest:
        for name in args.sources:
            module = importlib.import_module(f"src.ingest_{name}")
            try:
                module.run(years=config.YEARS, force=args.force_download)
            except NotImplementedError as step:
                print(f"[ingest] {name}: not built yet ({step}), skipped")

    build_panel.build_all()
    return 0 if checks.run_checks() else 1


if __name__ == "__main__":
    sys.exit(main())
