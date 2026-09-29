"""Join each source's interim output into the processed tables modelers read.

    data/interim/<table>/<source>.parquet  ->  data/processed/<table>.parquet

msa_year is built on the full MSA-universe x years grid, so a value a source
doesn't report shows up as an empty cell rather than a missing row.

    python -m src.build_panel
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src import config
from src.utils import standardize_keys


def universe_grid() -> pd.DataFrame:
    """Every metro in data/reference/msa_universe.csv x every year in config.YEARS."""
    universe = pd.read_csv(config.MSA_UNIVERSE, dtype=str)
    universe = standardize_keys(universe[["cbsa_code", "cbsa_title"]].dropna(subset=["cbsa_code"]))
    if universe["cbsa_code"].duplicated().any():
        raise ValueError("msa_universe.csv lists a metro more than once")
    years = pd.DataFrame({"year": list(config.YEARS)})
    return standardize_keys(universe.merge(years, how="cross"))


def build_table(table: str) -> Path | None:
    keys = config.TABLES[table]
    files = sorted((config.INTERIM / table).glob("*.parquet"))
    base = universe_grid() if table == "msa_year" else None
    if not files and base is None:
        print(f"[build] {table}: no interim files yet, skipped")
        return None

    frames = {path.stem: standardize_keys(pd.read_parquet(path)) for path in files}
    owner: dict[str, str] = {}
    for name, frame in frames.items():
        for col in frame.columns:
            if col in keys:
                continue
            if col in owner:
                raise ValueError(f"[build] column {col!r} comes from both {owner[col]} and {name}")
            owner[col] = name

    if base is not None:
        out = base
        for name, frame in frames.items():
            placed = frame[keys].merge(base[keys], on=keys, how="left", indicator=True)
            left_out = int((placed["_merge"] == "left_only").sum())
            if left_out:
                print(f"[build] {table}/{name}: {left_out:,} rows outside the MSA universe or year range left out")
            out = out.merge(frame, on=keys, how="left", validate="one_to_one")
    else:
        out = None
        for frame in frames.values():
            out = frame if out is None else out.merge(frame, on=keys, how="outer", validate="one_to_one")

    out = out.sort_values(keys).reset_index(drop=True)
    config.PROCESSED.mkdir(parents=True, exist_ok=True)
    path = config.PROCESSED / f"{table}.parquet"
    out.to_parquet(path, index=False)
    print(f"[build] {table}.parquet: {len(out):,} rows x {out.shape[1]} columns from {len(frames)} source(s)")
    return path


def build_all() -> dict[str, Path | None]:
    return {table: build_table(table) for table in config.TABLES}


if __name__ == "__main__":
    build_all()
