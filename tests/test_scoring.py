"""Tests for the scoring pipeline: pillar metric builders (src/scoring) feeding the final score.

The regression tests rebuild everything from data/processed and require the committed outputs to match
to 1e-9. A failure means either a bug or a deliberate change; a deliberate change must regenerate the
outputs (python -m src.scoring.run) in the same commit.

History: on 2026-11-05 the builders reproduced the notebooks' pillar exports and all 13 final runs exactly
(Pillar 3 on 393 metros). Pillar 3 then moved to the 387-metro universe, a deliberate change.
"""
import io
import json
import tomllib

import pandas as pd
import pytest

from src import config
from src import market_attractiveness as ma
from src.scoring import engine, run
from src.scoring.common import HIGHER, LOWER

PROCESSED = config.ROOT / "data" / "processed"
FINAL = config.ROOT / "outputs" / "final_scores"
PILLAR_FILES = config.ROOT / "outputs" / "pillar_scores"
WEIGHTS = sorted((config.ROOT / "weights").rglob("*.toml"))
TOL = 1e-9

needs_data = pytest.mark.skipif(not (PROCESSED / "msa_year.parquet").exists(), reason="needs data/processed")


def differences(new: pd.DataFrame, old: pd.DataFrame) -> list[str]:
    """Column-level differences between two tables indexed by cbsa_code."""
    out = []
    if list(new.columns) != list(old.columns):
        out.append(f"columns differ: new {list(new.columns)} vs committed {list(old.columns)}")
    if set(new.index) != set(old.index):
        out.append(f"metros differ: {len(set(new.index) ^ set(old.index))} not in both")
    new = new.reindex(old.index)
    for c in [c for c in old.columns if c in new.columns]:
        a, b = new[c], old[c]
        if pd.api.types.is_numeric_dtype(b) and pd.api.types.is_numeric_dtype(a):
            bad = ((a.astype(float) - b.astype(float)).abs() > TOL) | (a.isna() != b.isna())
        else:
            bad = a.fillna("").astype(str) != b.fillna("").astype(str)
        if bad.any():
            out.append(f"{c}: {int(bad.sum())} metros differ, e.g. {bad[bad].index[:3].tolist()}")
    return out


def as_csv(df: pd.DataFrame) -> pd.DataFrame:
    """Round-trip through CSV so dtypes match a file read back from disk."""
    return pd.read_csv(io.StringIO(df.to_csv()), dtype={"cbsa_code": str}).set_index("cbsa_code")


@pytest.fixture(scope="module")
def sets():
    return ma.metric_sets(config.ROOT)


@needs_data
def test_every_pillar_uses_the_same_387_metros(sets):
    idx = [ms.values.index for ms in sets.values()]
    assert all(len(i) == 387 for i in idx)
    assert all(i.equals(idx[0]) for i in idx)
    assert not any(t.endswith(", PR") for t in sets["pillar1"].titles)


@needs_data
def test_metric_definitions(sets):
    for ms in sets.values():
        for m in ms.metrics:
            assert m.direction in (HIGHER, LOWER), m.key
            assert m.label and m.source, m.key


@needs_data
@pytest.mark.parametrize("path", WEIGHTS, ids=lambda p: p.relative_to(config.ROOT).as_posix())
def test_weights_files_name_only_defined_metrics(sets, path):
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    for pillar, ms in sets.items():
        unknown = set(cfg.get(pillar, {})) - set(ms.registry)
        assert not unknown, f"{pillar}: {sorted(unknown)} are not defined in src/scoring/{pillar}.py"


@needs_data
def test_baseline_matches_committed_final_scores():
    new, report = ma.run(write=False, compare_baseline=False)
    old = pd.read_csv(FINAL / "market_attractiveness_scores.csv", dtype={"cbsa_code": str}).set_index("cbsa_code")
    assert differences(as_csv(new), old) == []
    assert report["settings"]["source"] == "metrics"


@needs_data
@pytest.mark.parametrize("path", [p for p in WEIGHTS if p.stem != "baseline"], ids=lambda p: p.stem)
def test_scenarios_match_committed_final_scores(path):
    new, _ = ma.run(weights_file=path, write=False)
    sub = ma.scenario_subdir(config.ROOT, path)
    old = pd.read_csv(FINAL / sub / f"market_attractiveness_{path.stem}_scores.csv",
                      dtype={"cbsa_code": str}).set_index("cbsa_code")
    assert differences(as_csv(new), old) == []


@needs_data
def test_pillar_files_carry_every_metric(sets, tmp_path):
    run.write_pillar_files(out_dir=tmp_path)
    for key, ms in sets.items():
        t = pd.read_csv(tmp_path / f"{key}_scores.csv", dtype={"cbsa_code": str})
        for m in ms.metrics:
            assert f"raw_{m.key}" in t and f"pct_{m.key}" in t, (key, m.key)
        meta = json.loads((tmp_path / f"{key}_run.json").read_text())
        assert meta["built_by"] == f"src.scoring.{key}"
    cat = pd.read_csv(tmp_path / "metric_catalog.csv")
    assert len(cat) == sum(len(ms.metrics) for ms in sets.values())


@needs_data
def test_committed_pillar_files_are_current(sets, tmp_path):
    run.write_pillar_files(out_dir=tmp_path)
    for key in sets:
        new = pd.read_csv(tmp_path / f"{key}_scores.csv", dtype={"cbsa_code": str}).set_index("cbsa_code")
        old = pd.read_csv(PILLAR_FILES / f"{key}_scores.csv", dtype={"cbsa_code": str}).set_index("cbsa_code")
        assert differences(new, old) == [], key


def test_weights_for_undefined_metric_are_rejected():
    class FakeSet:
        pillar, registry = "pillar1", {"a": None}
    with pytest.raises(ValueError, match="doesn't define"):
        engine.pillar_weights(FakeSet(), {"metrics": {"pillar1": {"b": 1}}})


# --- competition x growth (Pillar 3, T70) ------------------------------------------------------------
from src.scoring import pillar3  # noqa: E402

CORNERS = {"few_growing": 100, "many_growing": 50, "few_stable": 0, "many_stable": 50}


def test_corner_score_hits_each_corner_and_interpolates():
    s = pd.Series
    f = pillar3.corner_score(s([100, 0, 100, 0, 50]), s([100, 100, 0, 0, 50]), CORNERS)
    assert f.tolist() == [100, 50, 0, 50, 50]


def test_fewness_helps_only_where_the_market_grows():
    few, many = pd.Series([90.0]), pd.Series([10.0])
    growing, stable = pd.Series([90.0]), pd.Series([10.0])
    assert pillar3.corner_score(few, growing, CORNERS)[0] > pillar3.corner_score(many, growing, CORNERS)[0]
    assert pillar3.corner_score(few, stable, CORNERS)[0] < pillar3.corner_score(many, stable, CORNERS)[0]


@needs_data
def test_competition_growth_is_built_from_the_other_pillars(sets):
    ms = sets["pillar3"]
    assert "competition_growth" in ms.registry and ms.registry["competition_growth"].metric_id == "P3-08"
    v = ms.values["competition_growth"]
    assert v.between(0, 100).all() or v.dropna().between(0, 100).all()
    # blank exactly where a growth input or HHI is missing (the 5 Connecticut metros)
    growth_inputs = pd.concat([sets["pillar2"].values.deposit_growth, sets["pillar1"].values.mm_growth,
                               sets["pillar4"].values.gdp_growth, ms.values.deposit_hhi], axis=1)
    assert v.isna().equals(growth_inputs.isna().any(axis=1))
    assert {"competition_fewness", "market_growth"} <= set(ms.diagnostics.columns)


# --- size floor -------------------------------------------------------------------------------------------
@needs_data
def test_size_floor_ranks_only_metros_above_it():
    base, _ = ma.run(write=False, compare_baseline=False, min_population=0)
    out, report = ma.run(write=False, compare_baseline=False, min_population=250_000)
    eligible = base["rank"].notna() & (base["population"] >= 250_000)
    assert out["rank"].notna().reindex(eligible.index).equals(eligible)
    assert sorted(out["rank"].dropna().astype(int)) == list(range(1, int(eligible.sum()) + 1))
    below = out[out["below_size_floor"]]
    assert below["available_score"].notna().all() and below["complete_score"].isna().all()
    assert (below.loc[base.loc[below.index, "rank"].notna(), "coverage_status"] == "Below size floor (250,000)").all()
    assert report["universe"] == {"min_population": 250_000, "population_year": 2024,
                                  "below_size_floor": int((base["rank"].notna() & ~eligible).sum())}
    # option (a): scores don't move, ranks close up
    keep = eligible[eligible].index
    assert (out.loc[keep, "available_score"] - base.loc[keep, "available_score"]).abs().max() < 1e-12


@needs_data
def test_baseline_size_floor_is_250000():
    """Gate requirement: 250,000 by default; 0 turns it off."""
    out, report = ma.run(write=False, compare_baseline=False)
    assert report["universe"]["min_population"] == 250_000
    assert (out.loc[out["rank"].notna(), "population"] >= 250_000).all()
    off, _ = ma.run(write=False, compare_baseline=False, min_population=0)
    assert off["rank"].notna().sum() > out["rank"].notna().sum()


def test_universe_table_is_checked():
    w = {"pillars": {f"pillar{i}": 25 for i in range(1, 5)}}
    assert ma.normalize_weights(w)["universe"] == {"min_population": 0}
    assert ma.normalize_weights({**w, "universe": {"min_population": 100_000}})["universe_set"] is True
    with pytest.raises(ValueError, match="min_population"):
        ma.normalize_weights({**w, "universe": {"min_population": -1}})
    with pytest.raises(ValueError, match="only takes"):
        ma.normalize_weights({**w, "universe": {"max_population": 1}})


# --- as-of -------------------------------------------------------------------------------------------------
from src.scoring import asof  # noqa: E402
from src.scoring.common import load_settings, load_tables  # noqa: E402


@pytest.fixture(scope="module")
def tables():
    return run.with_history(load_tables(PROCESSED, names=run.TABLES))


@needs_data
def test_as_of_today_reproduces_the_settings_file(tables):
    s, report = asof.settings_as_of(load_settings(), "2026-11-05", tables)
    assert all(s[k] == load_settings()[k] for k in ("pillar1", "pillar2", "pillar3", "pillar4", "fit"))
    assert report["windows_shortened"] == []


@needs_data
def test_as_of_mid_2025_uses_only_released_data(tables):
    s, report = asof.settings_as_of(load_settings(), "2025-06-30", tables)
    years = report["latest_year_used"]
    assert years["bea_gdp"] == 2023 and years["bea_income"] == 2023   # 2024 county GDP/income came out 2026-02-05
    assert years["sod"] == 2024 and years["cbp"] == 2023 and years["pep"] == 2024
    assert s["pillar4"]["end_year"] == 2023 and s["pillar2"]["bea_end"] == 2023
    assert s["pillar1"]["end_quarter"] == "2024-06-30"


@needs_data
def test_as_of_before_the_data_is_rejected(tables):
    with pytest.raises(ValueError, match="pick a later date"):
        asof.settings_as_of(load_settings(), "2015-01-01", tables)


@needs_data
def test_as_of_run_drops_markets_entered_later():
    out, report = ma.run(write=False, compare_baseline=False, as_of="2025-06-30")
    assert report["as_of"]["as_of"] == "2025-06-30"
    assert "16740" not in out.index[out["bankunited_market"].notna()]      # Charlotte entered July 2025
    assert "12060" in out.index[out["bankunited_market"].notna()]          # Atlanta entered 2022


@needs_data
def test_as_of_mid_2022_handles_the_census_year(tables):
    """PEP has no 2020 migration (Census base year): an end year of 2020 must fall back to 2019, not blank Pillar 4."""
    s, report = asof.settings_as_of(load_settings(), "2022-06-30", tables)
    assert s["pillar4"]["end_year"] == 2020 and s["pillar4"]["migration_year"] == 2019
    assert any("net migration" in w for w in report["windows_shortened"])
    _, rep = ma.run(write=False, compare_baseline=False, as_of="2022-06-30", min_population=0)
    assert rep["complete_msas"] > 250


@needs_data
def test_as_of_uses_the_bea_history(tables):
    """BEA GDP and income for 2010-2014 (msa_year_history) give back-tests full-length GDP windows."""
    s, report = asof.settings_as_of(load_settings(), "2023-06-30", tables)
    assert s["pillar4"]["gdp_volatility_start"] == 2013 and s["pillar4"]["end_year"] == 2021   # 9 rates, not shortened
    assert not any("GDP volatility" in w for w in report["windows_shortened"])
    # population has no history, so the shared GDP/population growth window still starts no earlier than 2015
    s, _ = asof.settings_as_of(load_settings(), "2020-06-30", tables)
    assert s["pillar4"]["growth_start"] == 2015


@needs_data
def test_earliest_as_of_date_is_the_first_county_gdp_release():
    _, rep = ma.run(write=False, compare_baseline=False, as_of="2019-12-12", min_population=0)
    assert rep["complete_msas"] > 150
    with pytest.raises(ValueError, match="bea_gdp"):
        ma.run(write=False, compare_baseline=False, as_of="2019-12-11")


@needs_data
def test_a_single_weighted_metric_can_be_scored():
    """Every metric off except one (a dashboard check): the final score is that metric's percentile order."""
    w = {"pillars": {"pillar1": 0, "pillar2": 100, "pillar3": 0, "pillar4": 0},
         "metrics": {"pillar2": {"deposit_growth": 1}}}
    out, rep = ma.run(weights=w, write=False, compare_baseline=False)
    assert rep["weights_effective"] == {"pillar2": 1.0}
    v = ma.metric_sets(config.ROOT)["pillar2"].values["deposit_growth"].reindex(out.index)
    ranked = out["rank"].notna()
    assert out.loc[ranked, "complete_score"].corr(v[ranked], method="spearman") > 0.999


# --- Fit: distance to BankUnited markets (T71) ---------------------------------------------------------------
# Uses the Census Gazetteer points that data-v0.6 adds to msa_year; skipped on older data.
from src.scoring import fit as fitm  # noqa: E402

HAS_GAZETTEER = (PROCESSED / "msa_year.parquet").exists() and fitm.LAT in pd.read_parquet(
    PROCESSED / "msa_year.parquet").columns
needs_coordinates = pytest.mark.skipif(not HAS_GAZETTEER, reason="needs data-v0.6 (Gazetteer coordinates in msa_year)")


def test_miles_between():
    assert fitm.miles_between(0, 0, 1, 0) == pytest.approx(69.09, abs=0.01)          # one degree of latitude
    assert fitm.miles_between(35.24, -80.83, 35.24, -80.83) == 0


def test_distance_columns_without_coordinates_are_blank():
    idx = pd.Index(["16740", "33100"], name="cbsa_code")
    out = fitm.distance_columns(idx, None, pd.Index(["33100"]))
    assert out["miles_to_nearest_bankunited_market"].isna().all()
    assert out["is_bankunited_market"].tolist() == [False, True]


@needs_coordinates
def test_distances_to_bankunited_markets():
    out, rep = ma.run(write=False, compare_baseline=False)
    bu = out["is_bankunited_market"]
    assert bu.sum() == 13 and (out.loc[bu, "miles_to_nearest_bankunited_market"] == 0).all()
    clt = out.loc["16740"]
    assert clt["miles_to_nearest_bankunited_market"] == 0 and clt["nearest_bankunited_market"] == "Charlotte"
    # Raleigh's nearest BankUnited market is Charlotte, about 130 miles away
    assert out.loc["39580", "nearest_bankunited_market"] == "Charlotte"
    assert 100 < out.loc["39580", "miles_to_nearest_bankunited_market"] < 160
    assert rep["fit"]["coordinates_available"] is True


@needs_coordinates
def test_max_distance_filter_ranks_only_metros_within_it():
    base, _ = ma.run(write=False, compare_baseline=False)
    out, rep = ma.run(write=False, compare_baseline=False, max_miles=300)
    ranked = out["rank"].notna()
    assert (out.loc[ranked, "miles_to_nearest_bankunited_market"] <= 300).all()
    expected = base["rank"].notna() & (base["miles_to_nearest_bankunited_market"] <= 300)
    assert ranked.reindex(expected.index).equals(expected)
    assert sorted(out["rank"].dropna().astype(int)) == list(range(1, int(ranked.sum()) + 1))
    keep = expected[expected].index                       # filters don't move anyone's score
    assert (out.loc[keep, "available_score"] - base.loc[keep, "available_score"]).abs().max() < 1e-12
    gone = out.index[base["rank"].notna().reindex(out.index) & ~ranked]
    assert (out.loc[gone, "coverage_status"] == "Outside distance range (max 300 mi)").all()
    assert rep["fit"]["outside_distance_range"] == len(gone)


@needs_coordinates
def test_exclude_current_markets():
    out, rep = ma.run(write=False, compare_baseline=False, exclude_current_markets=True)
    assert out.loc[out["is_bankunited_market"], "rank"].isna().all()
    assert (out.loc[out["is_bankunited_market"] & out["available_score"].notna()
                    & (out["coverage_status"] != "Partial"), "coverage_status"]
            .isin(["Current BankUnited market", "Below size floor (250,000)"])).all()


@needs_coordinates
def test_as_of_distances_use_the_markets_of_that_date():
    out, _ = ma.run(write=False, compare_baseline=False, as_of="2025-06-30")
    assert not out.loc["16740", "is_bankunited_market"]                 # Charlotte entered July 2025
    assert out.loc["16740", "nearest_bankunited_market"] == "Atlanta"
    assert 200 < out.loc["16740", "miles_to_nearest_bankunited_market"] < 250


@needs_data
def test_distance_filter_without_coordinates_stops(monkeypatch):
    monkeypatch.setattr(fitm, "load_coordinates", lambda root: None)
    with pytest.raises(ma.GateError, match="Gazetteer coordinates"):
        ma.run(write=False, compare_baseline=False, max_miles=300)
    out, _ = ma.run(write=False, compare_baseline=False)                # filters off: runs, columns blank
    assert out["miles_to_nearest_bankunited_market"].isna().all()


def test_fit_table_is_checked():
    w = {"pillars": {f"pillar{i}": 25 for i in range(1, 5)}}
    assert ma.normalize_weights(w)["fit"] == ma.FIT_DEFAULTS
    assert ma.normalize_weights({**w, "fit": {"max_miles_to_bankunited": 400}})["fit_set"] is True
    with pytest.raises(ValueError, match="max_miles_to_bankunited"):
        ma.normalize_weights({**w, "fit": {"max_miles_to_bankunited": -5}})
    with pytest.raises(ValueError, match="takes"):
        ma.normalize_weights({**w, "fit": {"max_distance": 5}})
    with pytest.raises(ValueError, match="above"):
        ma.normalize_weights({**w, "fit": {"max_miles_to_bankunited": 100, "min_miles_to_bankunited": 200}})


@needs_coordinates
def test_real_gazetteer_coordinates():
    coords = fitm.load_coordinates(config.ROOT)
    out, _ = ma.run(write=False, compare_baseline=False)
    assert out["miles_to_nearest_bankunited_market"].notna().all()       # every scored metro has a point
    clt, mia = coords.loc["16740"], coords.loc["33100"]
    assert clt["lat"] == pytest.approx(35.166342, abs=1e-5)              # Austin's check value
    assert fitm.miles_between(clt.lat, clt.lon, mia.lat, mia.lon) == pytest.approx(627, abs=3)



# --- Fit: industry share ---------------------------------------------------------------------------------------
def _toy_industry():
    idx = pd.Index(["A", "B", "C"], name="cbsa_code")
    sectors = pd.DataFrame({"cbsa_code": ["A", "A", "A", "B", "B", "C", "C", "C"],
                            "naics_code": ["23", "31", "72", "23", "72", "23", "31", "72"],
                            "year": 2023, "cbp_employment_count": [20, 30, 50, 40, 60, 10, 10, 80]})
    totals = pd.DataFrame({"cbsa_code": ["A", "B", "C"], "year": 2023, "cbp_employment_count": [200, 100, 100]})
    return idx, sectors, totals


def test_industry_share_uses_the_published_total_and_blanks_missing_selected_sectors():
    idx, sectors, totals = _toy_industry()
    out = fitm.industry_share(idx, sectors, totals, 2023, ["23", "31"])
    assert out.loc["A", "industry_share"] == 25.0            # (20 + 30) / 200 published total, not / 100 sector sum
    assert pd.isna(out.loc["B", "industry_share"])           # 31 selected but suppressed in B
    assert out.loc["B", "industry_sectors_missing"] == "31"
    assert out.loc["C", "industry_share"] == 20.0
    assert out.loc["A", "industry_share_percentile"] == 100 and out.loc["C", "industry_share_percentile"] == 0


def test_an_unselected_suppressed_sector_does_not_blank_the_share():
    idx, sectors, totals = _toy_industry()
    out = fitm.industry_share(idx, sectors, totals, 2023, ["23"])   # 31 missing in B, but not selected
    assert out.loc["B", "industry_share"] == 40.0 and out.loc["B", "industry_sectors_missing"] == ""


@needs_data
def test_baseline_industry_share_matches_the_research_version():
    """Default selection = the High and Medium sectors; Charlotte 70.3% as in docs/industry_fit_research.md."""
    out, rep = ma.run(write=False, compare_baseline=False)
    assert rep["fit"]["industries"] == fitm.DEFAULT_INDUSTRIES and rep["fit"]["industry_year"] == 2023
    assert out.loc["16740", "industry_share"] == pytest.approx(70.32, abs=0.01)
    assert out["industry_share"].notna().sum() == 376                       # 11 metros lack Utilities (22)
    assert set(out.loc[out["industry_share"].isna(), "industry_sectors_missing"]) == {"22"}


@needs_data
def test_industry_filter_ranks_only_metros_at_or_above_it():
    base, _ = ma.run(write=False, compare_baseline=False)
    out, rep = ma.run(write=False, compare_baseline=False, min_industry_share=72)
    ranked = out["rank"].notna()
    expected = base["rank"].notna() & (base["industry_share"] >= 72)
    assert ranked.reindex(expected.index).equals(expected)
    keep = expected[expected].index
    assert (out.loc[keep, "available_score"] - base.loc[keep, "available_score"]).abs().max() < 1e-12
    gone = out.index[base["rank"].notna().reindex(out.index) & ~ranked]
    statuses = set(out.loc[gone, "coverage_status"])
    assert statuses <= {"Below industry share (72%)", "Insufficient data (selected industry suppressed)"}
    assert rep["fit"]["below_industry_share"] + rep["fit"]["industry_insufficient_data"] == len(gone)


@needs_data
def test_dropping_a_suppressed_sector_removes_insufficient_data():
    w = ma.load_weights(config.ROOT / "weights" / "baseline.toml")
    raw = {"pillars": w["pillars"], "metrics": w["metrics"], "fill": w["fill"],
           "fit": {"min_industry_share": 1, "industries": {c: c in fitm.DEFAULT_INDUSTRIES and c != "22"
                                                            for c in fitm.CBP_SECTORS}}}
    out, rep = ma.run(weights=raw, write=False, compare_baseline=False)
    assert "22" not in rep["fit"]["industries"] and rep["fit"]["industry_insufficient_data"] == 0
    assert out["industry_share"].notna().sum() == 387


@needs_data
def test_fit_settings_inherit_one_by_one_and_industries_replace_whole(monkeypatch):
    real = ma.load_weights

    def baseline_with_filters(path):
        cfg = real(path)
        if Path(path).name == "baseline.toml":                    # pretend the baseline sets two filters
            cfg["fit_given"] = {"max_miles_to_bankunited": 600, "min_industry_share": 60}
            cfg["industries_given"] = ["23", "31", "42"]
        return cfg
    from pathlib import Path
    monkeypatch.setattr(ma, "load_weights", baseline_with_filters)
    w = real(config.ROOT / "weights" / "baseline.toml")
    plain = {"pillars": w["pillars"], "metrics": w["metrics"], "fill": w["fill"]}
    _, rep = ma.run(weights={**plain, "fit": {"min_industry_share": 30}}, write=False, compare_baseline=False)
    assert rep["fit"]["min_industry_share"] == 30                        # own setting
    assert rep["fit"]["max_miles_to_bankunited"] == 600                  # inherited, not reset to 0
    assert rep["fit"]["industries"] == ["23", "31", "42"]                # inherited list
    _, rep = ma.run(weights={**plain, "fit": {"industries": {"62": True}}}, write=False, compare_baseline=False)
    assert rep["fit"]["industries"] == ["62"]                            # own list replaces the baseline's whole
    assert rep["fit"]["min_industry_share"] == 60 and rep["fit"]["max_miles_to_bankunited"] == 600


@needs_data
def test_as_of_moves_the_industry_year():
    _, rep = ma.run(write=False, compare_baseline=False, as_of="2022-06-30")
    assert rep["fit"]["industry_year"] == 2020                           # CBP 2020 was the latest released


def test_industry_settings_are_checked():
    w = {"pillars": {f"pillar{i}": 25 for i in range(1, 5)}}
    with pytest.raises(ValueError, match="aren't CBP sectors"):
        ma.normalize_weights({**w, "fit": {"industries": {"92": True}}})
    with pytest.raises(ValueError, match="true or false"):
        ma.normalize_weights({**w, "fit": {"industries": {"23": 1}}})
    with pytest.raises(ValueError, match="selects no sector"):
        ma.normalize_weights({**w, "fit": {"industries": {"23": False}}})
    with pytest.raises(ValueError, match="percent from 0 to 100"):
        ma.normalize_weights({**w, "fit": {"min_industry_share": 120}})


# --- [options]: industry HHI with suppressed sectors -------------------------------------------------------------
@needs_data
def test_industry_hhi_leaves_out_suppressed_sectors_in_the_baseline():
    out, rep = ma.run(write=False, compare_baseline=False)
    assert rep["options"]["industry_hhi_missing_sectors"] == "leave_out"
    p4 = ma.metric_sets(config.ROOT)["pillar4"]
    published = p4.diagnostics["industry_hhi_published_sectors"]
    assert published.notna().all()                                           # every metro gets an HHI
    full = p4.values["industry_hhi"].notna()                                 # nothing suppressed: identical
    assert (published[full] - p4.values["industry_hhi"][full]).abs().max() < 1e-12
    assert p4.diagnostics["industry_hhi_sectors_left_out"].max() <= 2
    assert out["rank"].notna().sum() == 190 and out.loc["26620", "rank"] == 11      # Huntsville now ranked


@needs_data
def test_industry_hhi_blank_option_restores_the_strict_rule():
    w = ma.load_weights(config.ROOT / "weights" / "baseline.toml")
    raw = {"pillars": w["pillars"], "metrics": w["metrics"], "fill": w["fill"],
           "options": {"industry_hhi_missing_sectors": "blank"}}
    out, rep = ma.run(weights=raw, write=False, compare_baseline=False)
    assert rep["options"]["industry_hhi_missing_sectors"] == "blank"
    assert out["rank"].notna().sum() == 176 and pd.isna(out.loc["26620", "rank"])
    assert out.loc["16740", "rank"] == 17


@needs_data
def test_options_inherit_from_the_baseline():
    w = ma.load_weights(config.ROOT / "weights" / "baseline.toml")
    raw = {"pillars": w["pillars"], "metrics": w["metrics"], "fill": w["fill"]}       # no [options]
    _, rep = ma.run(weights=raw, write=False, compare_baseline=False)
    assert rep["options"]["industry_hhi_missing_sectors"] == "leave_out"


@needs_data
def test_pillar_file_uses_the_baseline_option(tmp_path):
    run.write_pillar_files(out_dir=tmp_path)
    t = pd.read_csv(tmp_path / "pillar4_scores.csv")
    assert t["raw_industry_hhi"].notna().all()


def test_options_are_checked():
    w = {"pillars": {f"pillar{i}": 25 for i in range(1, 5)}}
    with pytest.raises(ValueError, match="must be one of"):
        ma.normalize_weights({**w, "options": {"industry_hhi_missing_sectors": "estimate"}})
    with pytest.raises(ValueError, match="takes"):
        ma.normalize_weights({**w, "options": {"hhi": "leave_out"}})
