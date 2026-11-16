"""Tests for src/compare_scenarios.py: scenario groups, on small synthetic pillar exports."""
import pandas as pd
import pytest

from src import compare_scenarios as cs
from src import market_attractiveness as ma
from tests.test_market_attractiveness import four_pillars, write_toml  # noqa: F401 (fixture)



@pytest.fixture(autouse=True)
def _read_exports(monkeypatch):
    """Synthetic notebook-format exports: read them instead of building metrics."""
    monkeypatch.setattr(ma, "DEFAULT_SOURCE", "exports")


EQUAL = {"pillar1": 25, "pillar2": 25, "pillar3": 25, "pillar4": 25}


@pytest.fixture
def grouped(four_pillars):  # noqa: F811
    root = four_pillars
    write_toml(root / "weights/baseline.toml", EQUAL)
    write_toml(root / "weights/scenarios/lending_heavy.toml", {**EQUAL, "pillar1": 60})
    write_toml(root / "weights/strategy/deposit_led.toml", {**EQUAL, "pillar2": 60})
    write_toml(root / "weights/strategy/talent_led.toml", EQUAL)   # differs only in Fit, like the real one
    return root


def test_group_of():
    assert cs.group_of("weights/scenarios/x.toml") == "sensitivity"
    assert cs.group_of("weights/strategy/x.toml") == "strategy"
    assert cs.group_of("weights/baseline.toml") is None and cs.group_of(None) is None


def test_groups_are_compared_separately(grouped):
    assert cs.run_group(grouped, "sensitivity") == ["lending_heavy"]
    assert cs.run_group(grouped, "strategy") == ["deposit_led", "talent_led"]
    runs = cs.load_runs(grouped / "outputs/final_scores")

    sens, _ = cs.compare(grouped, "sensitivity", None, runs)
    assert list(sens.index) == ["baseline", "lending_heavy"]
    assert (grouped / "outputs/final_scores/scenario/scenario_summary.csv").exists()
    assert (grouped / "outputs/final_scores/scenario/market_attractiveness_lending_heavy_scores.csv").exists()

    strat, bu = cs.compare(grouped, "strategy", None, runs)
    assert list(strat.index) == ["baseline (balanced franchise)", "deposit_led", "talent_led"]  # ORDER
    assert strat.loc["deposit_led", "w_pillar2"] == pytest.approx(100 * 60 / 135, abs=0.1)
    assert strat.loc["talent_led", "same_as_baseline"] and not strat.loc["deposit_led", "same_as_baseline"]
    assert (grouped / "outputs/final_scores/strategy/scenario_summary_strategy.csv").exists()
    assert (grouped / "outputs/final_scores/strategy/scenario_bankunited_ranks_strategy.csv").exists()
    assert not list((grouped / "outputs/final_scores").glob("*_led_scores.csv"))   # nothing left at the top level


def test_same_name_in_two_groups_is_rejected(grouped):
    write_toml(grouped / "weights/scenarios/deposit_led.toml", EQUAL)
    with pytest.raises(ValueError, match="both"):
        cs.check_names(grouped)
