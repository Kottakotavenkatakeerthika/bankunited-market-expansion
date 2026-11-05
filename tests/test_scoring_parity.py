"""Parity: the scripted pillar builders must reproduce the notebooks' committed exports.

Each ported pillar is rebuilt from data/processed into a temporary folder and compared, column by
column, with outputs/pillar_scores/<pillar>_scores.csv as the notebook last wrote it (tag
parity-reference). Numbers must agree to 1e-9; text columns exactly. A failure means either a porting
bug or a deliberate change; a deliberate change must update the reference export in the same commit.
"""
import json

import pandas as pd
import pytest

from src import config
from src.scoring import run

PROCESSED = config.ROOT / "data" / "processed"
REFERENCE = config.ROOT / "outputs" / "pillar_scores"
TOL = 1e-9

pytestmark = pytest.mark.skipif(not (PROCESSED / "msa_year.parquet").exists(), reason="needs data/processed")


def differences(new: pd.DataFrame, old: pd.DataFrame) -> list[str]:
    """Column-level differences between two exports indexed by cbsa_code."""
    out = []
    if list(new.columns) != list(old.columns):
        out.append(f"columns differ: new {list(new.columns)} vs reference {list(old.columns)}")
    if set(new.index) != set(old.index):
        out.append(f"metros differ: {len(set(new.index) ^ set(old.index))} not in both")
    new = new.reindex(old.index)
    for c in [c for c in old.columns if c in new.columns]:
        a, b = new[c], old[c]
        if pd.api.types.is_numeric_dtype(b) and pd.api.types.is_numeric_dtype(a):
            gap = (a.astype(float) - b.astype(float)).abs()
            bad = (gap > TOL) | (a.isna() != b.isna())
        else:
            bad = a.fillna("").astype(str) != b.fillna("").astype(str)
        if bad.any():
            out.append(f"{c}: {int(bad.sum())} metros differ, e.g. {bad[bad].index[:3].tolist()}")
    return out


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("exports")
    return run.build_all(out_dir=out)


@pytest.mark.parametrize("pillar", sorted(run.BUILDERS))
def test_export_matches_notebook(built, pillar):
    new = pd.read_csv(built[pillar][0], dtype={"cbsa_code": str}).set_index("cbsa_code")
    old = pd.read_csv(REFERENCE / f"{pillar}_scores.csv", dtype={"cbsa_code": str}).set_index("cbsa_code")
    assert differences(new, old) == []
    assert list(new.index) == list(old.index), "row order differs from the notebook export"


@pytest.mark.parametrize("pillar", sorted(k for k in run.BUILDERS if k not in run.EXPORTERS))
def test_run_file_matches_notebook(built, pillar):
    new = json.loads(built[pillar][1].read_text())
    old = json.loads((REFERENCE / f"{pillar}_run.json").read_text())
    for k in ("effective_weights", "settings", "complete_msas", "metric_ids", "not_available"):
        assert new.get(k) == old.get(k), k
