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
    old = pd.read_csv(FINAL / f"market_attractiveness_{path.stem}_scores.csv",
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
