import pandas as pd
import pytest

from src import config
from src import market_attractiveness as ma
from src import pillar_sensitivity as ps

needs_data = pytest.mark.skipif(not (config.ROOT / "data" / "processed" / "msa_year.parquet").exists(),
                                reason="needs data/processed")


def test_baseline_weights_and_shares():
    weights, name = ps.read_weights(config.ROOT)
    assert name == "baseline"
    share = ps.shares(weights)
    assert len(share) == len(ps.scored_metrics(weights)) == 27
    assert sum(share.values()) == pytest.approx(1.0)
    assert share[("pillar1", "local_ci_growth")] == pytest.approx(0.025)
    assert share[("pillar3", "deposit_hhi")] == pytest.approx(0.05)


def test_changing_a_weight_leaves_the_original_alone():
    weights, _ = ps.read_weights(config.ROOT)
    w = ps.with_metric_weight(weights, "pillar1", "mm_growth", 0.0)
    assert w["metrics"]["pillar1"]["mm_growth"] == 0
    assert weights["metrics"]["pillar1"]["mm_growth"] == 20


def test_compare_identical_ranking():
    r = pd.Series([1.0, 2.0, 3.0, None], index=list("abcd"))
    c = ps.compare(r, r, top_n=2)
    assert c["biggest"] == 0 and c["over_5"] == 0 and c["top_kept"] == 2
    assert c["similarity"] == pytest.approx(1.0)


def test_compare_counts_moves_among_metros_ranked_in_both():
    base = pd.Series({"a": 1, "b": 2, "c": 30, "d": 40}, dtype=float)
    new = pd.Series({"a": 12, "b": 1, "c": 30, "d": None}, dtype=float)
    c = ps.compare(base, new, top_n=2)
    assert c["biggest"] == 11 and c["over_10"] == 1 and c["over_5"] == 1
    assert c["top_kept"] == 1                       # b stays, a drops out


@needs_data
def test_one_metric_matches_a_direct_run():
    """Dropping a metric here gives the same ranks as running the engine with that weight at 0."""
    weights, _ = ps.read_weights(config.ROOT)
    base = ps._ranks(config.ROOT, weights, None)
    committed = pd.read_csv(config.ROOT / "outputs" / "final_scores" / "market_attractiveness_scores.csv",
                            dtype={"cbsa_code": str}).set_index("cbsa_code")["rank"]
    pd.testing.assert_series_equal(base.reindex(committed.index), committed, check_names=False)
    w = ps.with_metric_weight(weights, "pillar4", "population_growth", 0.0)
    dropped = ps.compare(base, ps._ranks(config.ROOT, w, None))
    assert dropped["biggest"] > 0 and dropped["similarity"] < 1


@needs_data
def test_scenario_file_is_read_with_its_own_weights():
    weights, name = ps.read_weights(config.ROOT, "weights/strategy/cre_led.toml")
    assert name == "cre_led"
    assert ps.output_path(config.ROOT, name).name == "pillar_metric_sensitivity_cre_led.csv"
    assert ps.output_path(config.ROOT, "baseline", "2025-06-30").parts[-4:] == (
        "as_of", "2025-06-30", "sensitivity", "pillar_metric_sensitivity.csv")


def test_missing_weights_file():
    with pytest.raises(FileNotFoundError):
        ps.read_weights(config.ROOT, "weights/nope.toml")
