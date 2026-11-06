"""Compare weight-scenario runs of Market Attractiveness against the baseline. Owner: ML pod.

Scenarios come in two groups, by the folder their weights file is in:
    sensitivity  weights/scenarios/*.toml  robustness tests: drop a metric or pillar, fill gaps, tilt lending
    strategy     weights/strategy/*.toml   the Phase 1 methodology's strategy scenarios (C&I-led, CRE-led, ...)
The baseline (weights/baseline.toml) is in both. In the strategy group it is the Balanced franchise scenario.

    python -m src.compare_scenarios                          # compare every group from existing runs
    python -m src.compare_scenarios --group strategy --run   # rerun the baseline and the group, then compare

--run calls src.market_attractiveness for the baseline and each weights file in the group, so the runs are
fresh and on the same pillar exports. Without it, the comparison reads whatever is in outputs/final_scores.

Writes, per group, to outputs/final_scores/:
    sensitivity: scenario_summary.csv and scenario_bankunited_ranks.csv (names kept from before the groups)
    strategy:    scenario_summary_strategy.csv and scenario_bankunited_ranks_strategy.csv
summary: one row per scenario, with its pillar weights; bankunited_ranks: BankUnited markets' rank in each.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src import config

PREFIX = "market_attractiveness"
EXAMPLE_CBSA = "16740"  # Charlotte
BASELINE = "baseline"
GROUPS = {"sensitivity": "weights/scenarios", "strategy": "weights/strategy"}
BASELINE_LABEL = {"strategy": "baseline (balanced franchise)"}
OUTPUT_SUFFIX = {"sensitivity": "", "strategy": "_strategy"}
# Row order in the outputs; runs not listed follow in file-name order.
ORDER = {"strategy": ["ci_led", "cre_led", "deposit_led", "talent_led", "adjacency", "emerging_market"]}


def group_of(weights_source: str | None) -> str | None:
    """The group a run belongs to, from the folder of its weights file (None for the baseline or a custom run)."""
    if not weights_source:
        return None
    folder = Path(weights_source).parent.as_posix()
    return next((g for g, f in GROUPS.items() if folder == f), None)


def load_runs(folder: Path) -> dict[str, tuple[pd.DataFrame, dict]]:
    """Every saved run: name -> (scores, run report). The name is the weights file's stem."""
    runs = {}
    for f in sorted(folder.glob(f"{PREFIX}*_scores.csv")):
        name = f.name[len(PREFIX):-len("_scores.csv")].lstrip("_") or BASELINE
        report_path = f.with_name(f.name.replace("_scores.csv", "_run.json"))
        report = json.loads(report_path.read_text()) if report_path.exists() else {}
        runs[name] = (pd.read_csv(f, dtype={"cbsa_code": str}).set_index("cbsa_code"), report)
    return runs


def runs_in_group(runs: dict, group: str) -> dict[str, tuple[pd.DataFrame, dict]]:
    """The baseline first, then the group's runs in ORDER, then any others in file-name order."""
    picked = {n: r for n, r in runs.items() if n != BASELINE and group_of(r[1].get("weights_source")) == group}
    order = [n for n in ORDER.get(group, []) if n in picked] + sorted(n for n in picked if n not in ORDER.get(group, []))
    return {BASELINE: runs[BASELINE], **{n: picked[n] for n in order}}


def population(root: Path) -> pd.Series | None:
    path = root / "data" / "processed" / "msa_year.parquet"
    if not path.exists():
        return None
    m = pd.read_parquet(path, columns=["cbsa_code", "year", "pep_population_count"])
    return m[m.year == m.year.max()].set_index("cbsa_code")["pep_population_count"]


def pillar_weights(report: dict) -> dict[str, float]:
    """Each pillar's effective weight in percent; 0 for a pillar left out of the run."""
    w = report.get("weights_effective") or {}
    return {f"w_pillar{i}": round(100 * w.get(f"pillar{i}", 0.0), 1) for i in range(1, 5)}


def summarize(runs: dict[str, tuple[pd.DataFrame, dict]], pop: pd.Series | None) -> pd.DataFrame:
    base = runs[BASELINE][0]
    base_top25 = set(base.index[base["rank"] <= 25])
    rows = []
    for name, (d, report) in runs.items():
        both = d["complete_score"].notna() & base["complete_score"].reindex(d.index).notna()
        now = d.loc[both, "complete_score"].rank(ascending=False, method="min")
        before = base.loc[both[both].index, "complete_score"].rank(ascending=False, method="min")
        bu = d[d["bankunited_market"].notna()]
        same = name != BASELINE and d["complete_score"].reindex(base.index).equals(base["complete_score"])
        rows.append({
            "scenario": name,
            **pillar_weights(report),
            "complete_msas": int(d["complete_score"].notna().sum()),
            "same_as_baseline": same,
            "rank_corr_vs_baseline": round(now.corr(before, method="spearman"), 3),
            "top25_shared_with_baseline": len(set(d.index[d["rank"] <= 25]) & base_top25),
            "msas_moved_10plus": int(((now - before).abs() >= 10).sum()),
            "corr_with_population": (round(d["complete_score"].corr(pop.reindex(d.index), method="spearman"), 2)
                                     if pop is not None else np.nan),
            "charlotte_rank": d["rank"].get(EXAMPLE_CBSA, np.nan),
            "charlotte_best_rank": d["best_rank"].get(EXAMPLE_CBSA, np.nan) if "best_rank" in d else np.nan,
            "charlotte_worst_rank": d["worst_rank"].get(EXAMPLE_CBSA, np.nan) if "worst_rank" in d else np.nan,
            "bankunited_ranked": int(bu["rank"].notna().sum()),
            "bankunited_median_rank": bu["rank"].median(),
            "top5": "; ".join(d.sort_values("rank").head(5)["msa"].str.split(",").str[0].str.split("-").str[0]),
        })
    return pd.DataFrame(rows).set_index("scenario")


def bankunited_ranks(runs: dict[str, tuple[pd.DataFrame, dict]]) -> pd.DataFrame:
    base = runs[BASELINE][0]
    bu = base.index[base["bankunited_market"].notna()]
    table = pd.DataFrame({name: d["rank"].reindex(bu) for name, (d, _) in runs.items()})
    table.insert(0, "msa", base.loc[bu, "msa"].str.split(",").str[0])
    return table.sort_values(BASELINE)


def run_group(root: Path, group: str) -> list[str]:
    """Rerun the baseline and every weights file in the group. Returns the scenario names run."""
    from src import market_attractiveness as ma
    files = sorted((root / GROUPS[group]).glob("*.toml"))
    if not files:
        raise FileNotFoundError(f"no weights files in {GROUPS[group]}/")
    clash = [f.stem for f in files if f.stem == BASELINE]
    if clash:
        raise ValueError(f"{GROUPS[group]}/ has a file named {BASELINE}.toml; rename it")
    ma.run(root=root, compare_baseline=False)
    for f in files:
        ma.run(root=root, weights_file=f)
    return [f.stem for f in files]


def check_names(root: Path) -> None:
    """Output files are named by the weights file's stem, so a stem used in two groups would overwrite."""
    seen: dict[str, str] = {}
    for g, folder in GROUPS.items():
        for f in (root / folder).glob("*.toml"):
            if f.stem in seen:
                raise ValueError(f"{f.stem}.toml is in both {seen[f.stem]}/ and {folder}/; their runs would "
                                 f"write the same output files. Rename one.")
            seen[f.stem] = folder


def compare(root: Path, group: str, pop: pd.Series | None, runs: dict) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    picked = runs_in_group(runs, group)
    if len(picked) == 1:
        return None
    summary = summarize(picked, pop)
    bu = bankunited_ranks(picked)
    label = BASELINE_LABEL.get(group)
    if label:
        summary = summary.rename(index={BASELINE: label})
        bu = bu.rename(columns={BASELINE: label})
    folder = root / "outputs" / "final_scores"
    sfx = OUTPUT_SUFFIX[group]
    summary.to_csv(folder / f"scenario_summary{sfx}.csv")
    bu.to_csv(folder / f"scenario_bankunited_ranks{sfx}.csv")
    return summary, bu


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Compare weight scenarios against the baseline.")
    ap.add_argument("--group", choices=[*GROUPS, "all"], default="all")
    ap.add_argument("--run", action="store_true", help="rerun the baseline and the group's scenarios first")
    args = ap.parse_args(argv)
    root = config.ROOT
    groups = list(GROUPS) if args.group == "all" else [args.group]
    try:
        check_names(root)
        if args.run:
            for g in groups:
                print(f"running {g}: {', '.join(run_group(root, g))}")
    except (ValueError, FileNotFoundError) as e:
        print(e, file=sys.stderr)
        return 1
    runs = load_runs(root / "outputs" / "final_scores")
    if BASELINE not in runs:
        print("No baseline run found; run python -m src.market_attractiveness first.", file=sys.stderr)
        return 1
    pop = population(root)
    wrote = 0
    for g in groups:
        result = compare(root, g, pop, runs)
        if result is None:
            print(f"[{g}] no runs found; run with --run, or run its weights files in {GROUPS[g]}/\n")
            continue
        summary, bu = result
        wrote += 1
        with pd.option_context("display.width", 250, "display.max_columns", 30, "display.max_colwidth", 60):
            print(f"=== {g} scenarios vs baseline ===\n", summary.drop(columns="top5").to_string(), "\n")
            print("Top 5 by scenario\n", summary["top5"].to_string(), "\n")
            print("BankUnited markets: rank by scenario (blank = not complete)\n",
                  bu.to_string(na_rep="—", float_format="{:.0f}".format), "\n")
        same = summary.index[summary["same_as_baseline"]].tolist()
        if same:
            print(f"note: same ranking as the baseline (same Market Attractiveness weights): {', '.join(same)}\n")
        print(f"wrote outputs/final_scores/scenario_summary{OUTPUT_SUFFIX[g]}.csv and "
              f"scenario_bankunited_ranks{OUTPUT_SUFFIX[g]}.csv\n")
    return 0 if wrote else 1


if __name__ == "__main__":
    sys.exit(main())
