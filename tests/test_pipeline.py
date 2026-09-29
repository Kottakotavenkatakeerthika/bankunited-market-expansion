import sys
import types

import pandas as pd

from src import config, run_pipeline
from src.crosswalk import counties_to_cbsa
from src.utils import write_interim


def test_pipeline_runs_end_to_end_and_skips_unbuilt_sources(project, crosswalk_csv, monkeypatch):
    finished = types.ModuleType("src.ingest_finished")

    def run(years=None, force=False):
        counties = pd.DataFrame({"county_fips": ["37119", "45091", "01073"], "year": [2022] * 3,
                                 "demo_jobs_count": [100, 40, 60]})
        return [write_interim(counties_to_cbsa(counties, ["demo_jobs_count"]), "demo", "msa_year")]

    finished.run = run
    unbuilt = types.ModuleType("src.ingest_unbuilt")

    def not_yet(years=None, force=False):
        raise NotImplementedError("download")

    unbuilt.run = not_yet
    monkeypatch.setitem(sys.modules, "src.ingest_finished", finished)
    monkeypatch.setitem(sys.modules, "src.ingest_unbuilt", unbuilt)
    monkeypatch.setattr(config, "SOURCES", ["finished", "unbuilt"])

    assert run_pipeline.main([]) == 0
    panel = pd.read_parquet(project["PROCESSED"] / "msa_year.parquet")
    charlotte = panel.loc[(panel["cbsa_code"] == "16740") & (panel["year"] == 2022), "demo_jobs_count"]
    assert charlotte.item() == 140


def test_ingest_templates_import_and_follow_the_interface():
    import importlib

    for name in config.SOURCES:
        module = importlib.import_module(f"src.ingest_{name}")
        assert callable(module.run) and callable(module.download) and callable(module.transform)
