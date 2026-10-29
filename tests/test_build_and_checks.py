import pandas as pd
import pytest

from src import build_panel, checks
from src.utils import write_interim


def seed(project):
    write_interim(pd.DataFrame({
        "cbsa_code": ["16740", "16740", "13820", "13820", "33100"],
        "year": [2022, 2023, 2022, 2023, 2022],
        "cbp_establishments_count": [100, 110, 50, 55, 999],
    }), "cbp", "msa_year")
    write_interim(pd.DataFrame({
        "cbsa_code": ["16740", "13820"], "year": [2023, 2023], "sod_deposits_usd": [5e9, 2e9],
    }), "sod", "msa_year")


def test_build_uses_the_universe_grid(project):
    seed(project)
    build_panel.build_all()
    panel = pd.read_parquet(project["PROCESSED"] / "msa_year.parquet")
    assert len(panel) == 4  # 2 metros x 2 years
    assert {"cbsa_title", "cbp_establishments_count", "sod_deposits_usd"} <= set(panel.columns)
    assert "33100" not in panel["cbsa_code"].tolist()  # outside the universe
    charlotte_2022 = panel[(panel["cbsa_code"] == "16740") & (panel["year"] == 2022)]
    assert charlotte_2022["sod_deposits_usd"].isna().all()  # not reported, so empty


def test_build_rejects_the_same_column_from_two_sources(project):
    seed(project)
    pd.DataFrame({"cbsa_code": ["16740"], "year": [2022], "cbp_establishments_count": [1]}).to_parquet(
        project["INTERIM"] / "msa_year" / "rogue.parquet", index=False)
    with pytest.raises(ValueError, match="comes from both"):
        build_panel.build_all()


def test_checks_pass_then_catch_a_negative_amount(project):
    seed(project)
    build_panel.build_all()
    assert checks.run_checks()
    assert (project["PROCESSED"] / "checks_report.md").exists()
    path = project["PROCESSED"] / "msa_year.parquet"
    panel = pd.read_parquet(path)
    panel.loc[0, "sod_deposits_usd"] = -1
    panel.to_parquet(path, index=False)
    assert not checks.run_checks()


def test_an_hhi_outside_0_to_10000_fails(project):
    table = pd.DataFrame({"cbsa_code": ["16740", "13820"], "year": [2023, 2023], "sod_deposit_hhi": [10_000.0, 0.0]})

    def hhi_check():
        return next(r for r in checks.check_table("msa_year", table) if r.check == "sod_deposit_hhi within 0-10,000")

    assert hhi_check().passed  # both ends are allowed
    table.loc[0, "sod_deposit_hhi"] = 10_000.5
    assert not hhi_check().passed


def test_a_change_in_a_share_outside_minus_1_to_1_fails(project):
    column = "sod_top3_deposit_share_3y_change_net"
    table = pd.DataFrame({"cbsa_code": ["16740", "13820"], "year": [2023, 2023], column: [1.0, -1.0]})

    def change_check():
        return next(r for r in checks.check_table("msa_year", table) if r.check == f"{column} within -1 to 1")

    assert change_check().passed  # both ends are allowed: a share can go from 0 to 1
    table.loc[1, column] = -1.2  # a year shifted onto the wrong metro could do this
    assert not change_check().passed
    other = pd.DataFrame({"cbsa_code": ["16740"], "year": [2023], "pep_net_migration_net": [-5_000.0]})
    assert not any("within -1 to 1" in r.check for r in checks.check_table("msa_year", other))  # other _net columns aren't held to it


def test_spot_checks_compare_with_published_figures(project):
    seed(project)
    build_panel.build_all()
    spec = {"cbsa_code": ["16740"], "year": [2023], "column": ["sod_deposits_usd"],
            "rel_tolerance": [0.001], "source_note": ["FDIC published total"]}
    pd.DataFrame({**spec, "expected": [5.001e9]}).to_csv(project["SPOT_CHECKS"], index=False)
    assert checks.run_checks()
    pd.DataFrame({**spec, "expected": [6e9]}).to_csv(project["SPOT_CHECKS"], index=False)
    assert not checks.run_checks()
