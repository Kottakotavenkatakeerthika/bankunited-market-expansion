"""Tests for src/market_attractiveness.py on small synthetic pillar exports (no data files needed)."""
import json

import numpy as np
import pandas as pd
import pytest

from src import market_attractiveness as ma

CODES = ["10000", "20000", "30000", "40000", "50000"]


def write_standard(root, key, complete, available=None, coverage=None, codes=CODES, pct=None, run_json=None):
    """A pillar 1-3 style export: complete_score, rank, available_score, ..., pct_<metric>."""
    if pct is not None:  # scores consistent with equal metric weights, as a notebook would export them
        P = pd.DataFrame(pct, dtype=float)
        have = P.notna()
        available = (P.fillna(0).sum(axis=1) / have.sum(axis=1)).tolist()
        complete = pd.Series(available).where(have.all(axis=1).values).tolist()
        coverage = (have.sum(axis=1) / P.shape[1]).tolist()
    available = complete if available is None else available
    coverage = [1.0] * len(codes) if coverage is None else coverage
    complete = pd.Series(complete, dtype=float)
    df = pd.DataFrame({
        "cbsa_code": codes, "msa": [f"Metro {c}" for c in codes], "complete_score": complete,
        "rank": complete.rank(ascending=False, method="min"), "available_score": available,
        "valid_metrics": 5, "weight_coverage": coverage, "missing_metrics": "",
    })
    for m, v in (pct or {}).items():
        df[f"pct_{m}"] = v
    path = root / "outputs" / "pillar_scores" / f"{key}_scores.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    if run_json is not None:
        path.with_name(f"{key}_run.json").write_text(json.dumps(run_json))
    return path


def write_pillar4(root, complete, available=None, folder="outputs/pillar_scores", pct=None):
    if pct is not None:
        P = pd.DataFrame(pct, dtype=float)
        available = P.mean(axis=1).tolist()
        complete = pd.Series(available).where(P.notna().all(axis=1).values).tolist()
    available = complete if available is None else available
    complete = pd.Series(complete, dtype=float)
    df = pd.DataFrame({
        "cbsa_code": CODES, "cbsa_title": [f"Metro {c}" for c in CODES], "complete_8_score": complete,
        "complete_8_rank": complete.rank(ascending=False, method="min"), "available_data_score": available,
        "valid_metrics_out_of_8": 8, "original_weight_coverage": 1.0, "missing_metrics": "",
    })
    for m, v in (pct or {}).items():
        df[f"{m}_percentile"] = v
    path = root / folder / "pillar4_scores.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def write_toml(path, pillars, metrics=None):
    lines = ["[pillars]", *[f"{k} = {v}" for k, v in pillars.items()]]
    for k, mw in (metrics or {}).items():
        lines += ["", f"[{k}]", *[f"{m} = {w}" for m, w in mw.items()]]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


EQUAL = {f"pillar{i}": 25 for i in range(1, 5)}
P1_PCT = {"size": [100, 75, 50, 25, 0], "growth": [0, 25, 50, 75, 100]}
P4_PCT = {"gdp_growth": [100, 75, 50, 25, 0], "industry_hhi": [0, 25, np.nan, 75, 100]}


@pytest.fixture
def four_pillars(tmp_path):
    write_standard(tmp_path, "pillar1", [90, 70, 50, 30, 10])
    write_standard(tmp_path, "pillar2", [10, 30, 50, 70, 90])
    write_standard(tmp_path, "pillar3", [80, 60, 40, 20, 0])
    write_pillar4(tmp_path, [50, 50, 60, 40, 55])
    return tmp_path


@pytest.fixture
def with_metrics(tmp_path):
    """Pillars 1 and 4 export metric percentiles; pillars 2 and 3 only scores."""
    write_standard(tmp_path, "pillar1", None, pct=P1_PCT, run_json={"not_available": ["multifamily_permits"]})
    write_standard(tmp_path, "pillar2", [10, 30, 50, 70, 90])
    write_standard(tmp_path, "pillar3", [80, 60, 40, 20, 0])
    write_pillar4(tmp_path, None, pct=P4_PCT)
    return tmp_path


def test_percentile_matches_notebook_rule():
    s = pd.Series([5.0, 1.0, np.nan, 3.0])
    assert ma.percentile(s).tolist()[:2] == [100.0, 0.0]
    assert np.isnan(ma.percentile(s)[2]) and ma.percentile(s)[3] == 50.0


def test_combines_four_pillars_and_writes_outputs(four_pillars):
    out, report = ma.run(root=four_pillars)
    assert report["pillars_in_run"] == ["pillar1", "pillar2", "pillar3", "pillar4"]
    assert report["complete_msas"] == 5
    # Metro 10000: percentiles 100, 0, 100, 37.5 (pillar 4: its 50 ties another 50 at average rank 2.5 of 5)
    assert out.loc["10000", "complete_score"] == pytest.approx((100 + 0 + 100 + 37.5) / 4)
    points = out[[f"pillar{i}_points" for i in range(1, 5)]].sum(axis=1)
    assert np.allclose(points, out["complete_score"])
    assert out["rank"].min() == 1 and out.index[0] == out["complete_score"].idxmax()
    assert (four_pillars / "outputs/final_scores/market_attractiveness_scores.csv").exists()
    saved = json.loads((four_pillars / "outputs/final_scores/market_attractiveness_run.json").read_text())
    assert saved["weights_effective"]["pillar1"] == 0.25


def test_missing_pillar_fails_the_gate_unless_allowed(tmp_path):
    write_standard(tmp_path, "pillar1", [90, 70, 50, 30, 10])
    write_standard(tmp_path, "pillar2", [10, 30, 50, 70, 90])
    write_pillar4(tmp_path, [50, 50, 60, 40, 55])
    with pytest.raises(ma.GateError, match="pillar3"):
        ma.run(root=tmp_path, write=False)
    out, report = ma.run(root=tmp_path, write=False, allow_missing=True)
    assert report["pillars_missing"] == ["pillar3"]
    assert "pillar3_points" not in out.columns
    assert report["weights_effective"]["pillar1"] == pytest.approx(1 / 3)


def test_pillar4_found_next_to_its_notebook(tmp_path):
    for k in ("pillar1", "pillar2", "pillar3"):
        write_standard(tmp_path, k, [90, 70, 50, 30, 10])
    write_pillar4(tmp_path, [50, 50, 60, 40, 55], folder="notebooks")
    _, report = ma.run(root=tmp_path, write=False)
    assert report["inputs"]["pillar4"]["file"] == "notebooks/pillar4_scores.csv"


def test_partial_pillar_is_provisional_and_low_coverage_is_dropped(four_pillars):
    write_standard(four_pillars, "pillar1", [90, 70, np.nan, np.nan, 10],
                   available=[90, 70, 55, 20, 10], coverage=[1, 1, 0.8, 0.3, 1])
    out, _ = ma.run(root=four_pillars, write=False)
    assert out.loc["30000", "pillar1_status"] == "partial"
    assert np.isnan(out.loc["30000", "complete_score"]) and np.isnan(out.loc["30000", "rank"])
    assert not np.isnan(out.loc["30000", "available_score"])
    assert out.loc["40000", "pillar1_status"] == "missing"          # 30% coverage < 50% floor
    assert out.loc["40000", "weight_coverage"] == pytest.approx(0.75)


@pytest.mark.parametrize("problem, message", [
    ("duplicate", "repeated cbsa_code"),
    ("range", "outside 0-100"),
    ("mismatch", "differs from available_score"),
])
def test_bad_exports_fail_the_gate(four_pillars, problem, message):
    path = four_pillars / "outputs/pillar_scores/pillar2_scores.csv"
    df = pd.read_csv(path, dtype={"cbsa_code": str})
    if problem == "duplicate":
        df.loc[1, "cbsa_code"] = df.loc[0, "cbsa_code"]
    elif problem == "range":
        df.loc[0, ["complete_score", "available_score"]] = 120
    else:
        df.loc[0, "available_score"] = 1
    df.to_csv(path, index=False)
    with pytest.raises(ma.GateError, match=message):
        ma.run(root=four_pillars, write=False)


def test_missing_column_fails_the_gate(four_pillars):
    path = four_pillars / "outputs/pillar_scores/pillar3_scores.csv"
    pd.read_csv(path).drop(columns="available_score").to_csv(path, index=False)
    with pytest.raises(ma.GateError, match="missing columns"):
        ma.run(root=four_pillars, write=False)


def test_universe_mismatch_is_a_warning(four_pillars):
    write_standard(four_pillars, "pillar3", [80, 60, 40, 20], codes=CODES[:4])
    out, report = ma.run(root=four_pillars, write=False)
    assert any("pillar3: 1 MSAs" in w for w in report["warnings"])
    assert out.loc["50000", "pillar3_status"] == "missing"


def test_pillar_weights_rescale_and_zero_weight_drops_a_pillar(four_pillars):
    w = {"pillar1": 2, "pillar2": 0, "pillar3": 1, "pillar4": 1}
    out, report = ma.run(root=four_pillars, weights=w, write=False)
    assert report["pillars_in_run"] == ["pillar1", "pillar3", "pillar4"]
    assert report["weights_effective"]["pillar1"] == 0.5
    with pytest.raises(ValueError):
        ma.run(root=four_pillars, weights={"pillar1": 1}, write=False)


def test_no_normalization_averages_published_scores(four_pillars):
    out, _ = ma.run(root=four_pillars, normalize="none", write=False)
    assert out.loc["10000", "complete_score"] == pytest.approx((90 + 10 + 80 + 50) / 4)
    assert "pillar1_percentile" not in out.columns


# --- Metric weights -------------------------------------------------------------------------------------
def test_notebook_metric_weights_reproduce_the_exported_scores(with_metrics):
    same = {"pillars": EQUAL, "metrics": {"pillar1": {"size": 1, "growth": 1},
                                          "pillar4": {"gdp_growth": 12.5, "industry_hhi": 12.5}}}
    out, report = ma.run(root=with_metrics, weights=same, write=False)
    plain, _ = ma.run(root=with_metrics, weights=EQUAL, write=False)
    assert report["inputs"]["pillar1"]["matches_notebook_weights"] is True
    assert report["inputs"]["pillar4"]["matches_notebook_weights"] is True
    pd.testing.assert_series_equal(out["available_score"], plain["available_score"])


def test_metric_weights_change_the_pillar_score(with_metrics):
    w = {"pillars": EQUAL, "metrics": {"pillar1": {"size": 3, "growth": 1}}}
    out, report = ma.run(root=with_metrics, weights=w, write=False)
    assert out.loc["10000", "pillar1_score"] == pytest.approx(0.75 * 100 + 0.25 * 0)
    assert report["metric_weights_effective"]["pillar1"] == {"size": 0.75, "growth": 0.25}
    assert report["inputs"]["pillar1"]["matches_notebook_weights"] is False
    assert any("pillar1: metric weights differ" in x for x in report["warnings"])


def test_zero_weight_on_a_metric_with_gaps_makes_msas_complete(with_metrics):
    base, _ = ma.run(root=with_metrics, weights=EQUAL, write=False)
    assert base.loc["30000", "pillar4_status"] == "partial"
    w = {"pillars": EQUAL, "metrics": {"pillar4": {"gdp_growth": 1, "industry_hhi": 0}}}
    out, _ = ma.run(root=with_metrics, weights=w, write=False)
    assert out.loc["30000", "pillar4_status"] == "complete"
    assert out.loc["30000", "pillar4_score"] == 50


def test_unknown_metric_fails_and_unavailable_metric_is_skipped(with_metrics):
    with pytest.raises(ma.GateError, match="sise"):
        ma.run(root=with_metrics, weights={"pillars": EQUAL, "metrics": {"pillar1": {"sise": 1, "growth": 1}}},
               write=False)
    w = {"pillars": EQUAL, "metrics": {"pillar1": {"size": 1, "growth": 1, "multifamily_permits": 1}}}
    _, report = ma.run(root=with_metrics, weights=w, write=False)
    assert any("multifamily_permits" in x and "not available" in x for x in report["warnings"])
    assert report["inputs"]["pillar1"]["matches_notebook_weights"] is True


def test_metric_weights_need_exported_percentiles(four_pillars):
    with pytest.raises(ma.GateError, match="no metric percentile columns"):
        ma.run(root=four_pillars, weights={"pillars": EQUAL, "metrics": {"pillar2": {"x": 1}}}, write=False)


def test_weights_file_baseline_and_scenario(with_metrics):
    write_toml(with_metrics / "weights/baseline.toml", EQUAL,
               {"pillar1": {"size": 1, "growth": 1}, "pillar4": {"gdp_growth": 1, "industry_hhi": 1}})
    out, report = ma.run(root=with_metrics)
    assert report["scenario"] == "baseline" and report["weights_source"] == "weights/baseline.toml"
    assert "rank_change" not in out.columns

    scen = write_toml(with_metrics / "weights/size heavy.toml", {**EQUAL, "pillar1": 50},
                      {"pillar1": {"size": 1, "growth": 0}, "pillar4": {"gdp_growth": 1, "industry_hhi": 0}})
    out, report = ma.run(root=with_metrics, weights_file=scen)
    assert report["scenario"] == "size_heavy"
    assert (with_metrics / "outputs/final_scores/market_attractiveness_size_heavy_scores.csv").exists()
    assert report["compared_to_baseline"] and report["entered_complete_set"] == 1   # 30000: HHI no longer needed
    assert out["rank_change"].notna().sum() == 4 and np.isnan(out.loc["30000", "rank_change"])
    table = ma.weight_table(report)
    assert table["share_of_final"].sum() == pytest.approx(1)


@pytest.mark.parametrize("bad, message", [
    ("[pillars]\npillar1 = 1\n", "one weight for each"),
    ("[pillars]\npillar1 = 1\npillar2 = 1\npillar3 = 1\npillar4 = 1\n[pilar1]\nsize = 1\n", "unknown section"),
    ("[pillars]\npillar1 = 1\npillar2 = 1\npillar3 = 1\npillar4 = 1\n[pillar1]\nsize = -1\n", "zero or positive"),
])
def test_bad_weights_files_are_rejected(tmp_path, bad, message):
    path = tmp_path / "w.toml"
    path.write_text(bad)
    with pytest.raises(ValueError, match=message):
        ma.load_weights(path)


def test_cli_show_weights(with_metrics, monkeypatch, capsys):
    write_toml(with_metrics / "weights/baseline.toml", EQUAL, {"pillar1": {"size": 3, "growth": 1}})
    monkeypatch.setattr(ma.config, "ROOT", with_metrics)
    monkeypatch.setattr(ma.run, "__defaults__", (with_metrics, *ma.run.__defaults__[1:]))
    assert ma.main(["--show-weights"]) == 0
    printed = capsys.readouterr().out
    assert "18.8%" in printed and "notebook score as exported" in printed   # 25% x 75% for pillar1 size
    assert not (with_metrics / "outputs/final_scores").exists()
