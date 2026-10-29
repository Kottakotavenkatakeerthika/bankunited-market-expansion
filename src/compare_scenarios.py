"""Compare weight-scenario runs of Market Attractiveness against the baseline. Owner: ML pod.

Run the baseline and the scenarios first (python -m src.market_attractiveness [--weights ...]), then:

    python -m src.compare_scenarios

Reads every outputs/final_scores/market_attractiveness*_scores.csv. Prints and writes:
    outputs/final_scores/scenario_summary.csv          one row per scenario
    outputs/final_scores/scenario_bankunited_ranks.csv BankUnited markets' rank in each scenario
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src import config

PREFIX = "market_attractiveness"
EXAMPLE_CBSA = "16740"  # Charlotte


def load_runs(folder: Path) -> dict[str, pd.DataFrame]:
    runs = {}
    for f in sorted(folder.glob(f"{PREFIX}*_scores.csv")):
        name = f.name[len(PREFIX):-len("_scores.csv")].lstrip("_") or "baseline"
        runs[name] = pd.read_csv(f, dtype={"cbsa_code": str}).set_index("cbsa_code")
    return runs


def population(root: Path) -> pd.Series | None:
    path = root / "data" / "processed" / "msa_year.parquet"
    if not path.exists():
        return None
    m = pd.read_parquet(path, columns=["cbsa_code", "year", "pep_population_count"])
    return m[m.year == m.year.max()].set_index("cbsa_code")["pep_population_count"]


def summarize(runs: dict[str, pd.DataFrame], pop: pd.Series | None) -> pd.DataFrame:
    base = runs["baseline"]
    base_top25 = set(base.index[base["rank"] <= 25])
    rows = []
    for name, d in runs.items():
        both = d["complete_score"].notna() & base["complete_score"].reindex(d.index).notna()
        now = d.loc[both, "complete_score"].rank(ascending=False, method="min")
        before = base.loc[both[both].index, "complete_score"].rank(ascending=False, method="min")
        bu = d[d["bankunited_market"].notna()]
        rows.append({
            "scenario": name,
            "complete_msas": int(d["complete_score"].notna().sum()),
            "rank_corr_vs_baseline": round(now.corr(before, method="spearman"), 3),
            "top25_shared_with_baseline": len(set(d.index[d["rank"] <= 25]) & base_top25),
            "msas_moved_10plus": int(((now - before).abs() >= 10).sum()),
            "corr_with_population": (round(d["complete_score"].corr(pop.reindex(d.index), method="spearman"), 2)
                                     if pop is not None else np.nan),
            "charlotte_rank": d["rank"].get(EXAMPLE_CBSA, np.nan),
            "bankunited_ranked": int(bu["rank"].notna().sum()),
            "bankunited_median_rank": bu["rank"].median(),
            "top5": "; ".join(d.sort_values("rank").head(5)["msa"].str.split(",").str[0].str.split("-").str[0]),
        })
    out = pd.DataFrame(rows).set_index("scenario")
    return out.loc[["baseline", *[n for n in out.index if n != "baseline"]]]


def bankunited_ranks(runs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    base = runs["baseline"]
    bu = base.index[base["bankunited_market"].notna()]
    order = ["baseline", *[n for n in runs if n != "baseline"]]
    table = pd.DataFrame({name: runs[name]["rank"].reindex(bu) for name in order})
    table.insert(0, "msa", base.loc[bu, "msa"].str.split(",").str[0])
    return table.sort_values("baseline")


def main(argv=None) -> int:
    root = config.ROOT
    folder = root / "outputs" / "final_scores"
    runs = load_runs(folder)
    if "baseline" not in runs:
        print("No baseline run found; run python -m src.market_attractiveness first.", file=sys.stderr)
        return 1
    if len(runs) == 1:
        print("Only the baseline is in outputs/final_scores; run some scenarios first.", file=sys.stderr)
        return 1
    summary = summarize(runs, population(root))
    bu = bankunited_ranks(runs)
    summary.to_csv(folder / "scenario_summary.csv")
    bu.to_csv(folder / "scenario_bankunited_ranks.csv")
    with pd.option_context("display.width", 250, "display.max_columns", 20, "display.max_colwidth", 60):
        print("Scenarios vs baseline\n", summary.drop(columns="top5").to_string(), "\n")
        print("Top 5 by scenario\n", summary["top5"].to_string(), "\n")
        print("BankUnited markets: rank by scenario (blank = not complete)\n",
              bu.to_string(na_rep="—", float_format="{:.0f}".format))
    print("\nwrote outputs/final_scores/scenario_summary.csv and scenario_bankunited_ranks.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
