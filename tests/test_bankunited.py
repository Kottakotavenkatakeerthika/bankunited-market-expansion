"""BankUnited's footprint in msa_year, built from the bank_msa_year interim files."""
import pandas as pd

from src import bankunited, build_panel, checks, config
from src.utils import write_interim

BU = config.BANKUNITED_RSSD_ID


def seed_bank_tables():
    write_interim(pd.DataFrame({
        "rssd_id": [BU, "111", "111", BU, BU],
        "cbsa_code": ["16740", "16740", "13820", "13820", "19100"],
        "year": [2023, 2023, 2023, 2022, 2022],
        "sod_offices_count": [2, 7, 5, 1, 1],
        # An office row with empty deposits, which real SOD data never has for BankUnited, and a real 0:
        # its Dallas office reported $0 at June 30, 2022, its first survey there
        "sod_deposits_usd": [5e6, 2e9, 1e9, None, 0.0],
    }), "sod", "bank_msa_year")
    write_interim(pd.DataFrame({
        "rssd_id": ["111", BU], "cbsa_code": ["13820", "13820"], "year": [2023, 2023],
        "cra_bank_small_business_loan_count": [10, 3],
        "cra_bank_small_business_loan_amount_usd": [1e6, 3e5],
    }), "cra_bank", "bank_msa_year")


def test_zero_where_bankunited_has_none_and_empty_where_a_source_says_nothing(project):
    seed_bank_tables()
    bankunited.build_presence()
    out = pd.read_parquet(config.INTERIM / "msa_year" / "bankunited.parquet").set_index(["cbsa_code", "year"])
    charlotte = out.loc[("16740", 2023)]
    assert (charlotte["bankunited_sod_offices_count"], charlotte["bankunited_sod_deposits_usd"]) == (2, 5e6)
    assert pd.isna(charlotte["bankunited_cra_small_business_loan_count"])  # no CRA lending reported there at all
    birmingham = out.loc[("13820", 2023)]
    assert (birmingham["bankunited_sod_offices_count"], birmingham["bankunited_sod_deposits_usd"]) == (0, 0)
    assert birmingham["bankunited_cra_small_business_loan_count"] == 3
    assert birmingham["bankunited_cra_small_business_loan_amount_usd"] == 3e5
    earlier = out.loc[("13820", 2022)]
    assert earlier["bankunited_sod_offices_count"] == 1 and pd.isna(earlier["bankunited_sod_deposits_usd"])  # empty stays empty
    dallas = out.loc[("19100", 2022)]
    assert dallas["bankunited_sod_offices_count"] == 1 and dallas["bankunited_sod_deposits_usd"] == 0  # a real 0 stays 0

    build_panel.build_all()  # writes the file again on its own, then joins it into msa_year
    panel = pd.read_parquet(config.PROCESSED / "msa_year.parquet").set_index(["cbsa_code", "year"])
    assert panel.loc[("16740", 2023), "bankunited_sod_offices_count"] == 2
    assert panel.loc[("16740", 2022), ["bankunited_sod_offices_count", "bankunited_cra_small_business_loan_count"]].isna().all()
    assert checks.run_checks()


def test_nothing_is_written_without_bank_tables(project):
    assert bankunited.build_presence() is None
    assert not (config.INTERIM / "msa_year" / "bankunited.parquet").exists()


def test_one_source_alone_says_which_columns_are_left_out(project, capsys):
    seed_bank_tables()
    (config.INTERIM / "bank_msa_year" / "cra_bank.parquet").unlink()
    bankunited.build_presence()
    assert ("cra_bank.parquet isn't built yet, so msa_year has no bankunited_cra_small_business_loan_count, "
            "bankunited_cra_small_business_loan_amount_usd") in capsys.readouterr().out
    out = pd.read_parquet(config.INTERIM / "msa_year" / "bankunited.parquet")
    assert [column for column in out.columns if column.startswith("bankunited_")] == [
        "bankunited_sod_offices_count", "bankunited_sod_deposits_usd"]
