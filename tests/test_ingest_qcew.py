import pandas as pd
import pytest

from src import build_panel, checks, config, ingest_qcew
from tests.test_ingest_bea_bls import write_qcew_zip

P = "bls_qcew_private_"
TOTAL_LEVEL, SUPER_LEVEL, SECTOR_LEVEL = 71, 73, 74
US_TOTAL_LEVEL, US_SUPER_LEVEL, US_SECTOR_LEVEL = 11, 13, 14


def row(area, industry, level, estabs, emp, wages, own="5", disclosure=""):
    """One QCEW line: private ownership by default; level is BLS's agglvl_code."""
    return {"area_fips": area, "own_code": own, "industry_code": industry, "agglvl_code": level, "size_code": 0,
            "year": 2023, "qtr": "A", "disclosure_code": disclosure, "area_title": "Test",
            "annual_avg_estabs_count": estabs, "annual_avg_emplvl": emp, "total_annual_wages": wages}


def us_files():
    """The U.S. file: the private total, two supersectors and two sectors."""
    return {"US000 U.S. TOTAL": [
        row("US000", "10", US_TOTAL_LEVEL, 1000, 10_000, 500_000),
        row("US000", "1012", US_SUPER_LEVEL, 400, 4_000, 150_000),
        row("US000", "1029", US_SUPER_LEVEL, 600, 6_000, 350_000),
        row("US000", "23", US_SECTOR_LEVEL, 400, 4_000, 150_000),
        row("US000", "31-33", US_SECTOR_LEVEL, 100, 1_000, 60_000),
    ]}


def run_transform(project, files, year=2023):
    path = write_qcew_zip(project, year, {**files, **us_files()})
    ingest_qcew.transform([path], [year])
    metro = pd.read_parquet(project["INTERIM"] / "msa_industry_year" / "bls.parquet")
    us = pd.read_parquet(project["INTERIM"] / "us_industry_year" / "bls.parquet")
    return metro.set_index(["cbsa_code", "industry_code", "year"]), us.set_index(["industry_code", "year"])


def charlotte_files():
    """Mecklenburg and York, with a total, two supersectors and a sector; the supersectors add up to the total."""
    return {
        "37119 Mecklenburg County, North Carolina": [
            row("37119", "10", TOTAL_LEVEL, 100, 1000, 50_000),
            row("37119", "1012", SUPER_LEVEL, 40, 400, 20_000),
            row("37119", "1029", SUPER_LEVEL, 60, 600, 30_000),
            row("37119", "31-33", SECTOR_LEVEL, 10, 100, 6_000),
        ],
        "45091 York County, South Carolina": [
            row("45091", "10", TOTAL_LEVEL, 20, 200, 8_000),
            row("45091", "1012", SUPER_LEVEL, 20, 200, 8_000),
        ],
    }


def test_only_private_rows_at_the_total_supersector_and_sector_levels_are_read(project, crosswalk_csv):
    files = charlotte_files()
    files["37119 Mecklenburg County, North Carolina"] += [
        row("37119", "10", 70, 999, 99_999, 9_999_999, own="0"),        # all ownerships: not wanted
        row("37119", "10", 71, 888, 88_888, 8_888_888, own="3"),        # local government: not wanted
        row("37119", "101", 72, 777, 77_777, 7_777_777),                # a domain, not a supersector
        row("37119", "2362", 78, 666, 66_666, 6_666_666),               # a detailed NAICS industry
    ]
    metro, _ = run_transform(project, files)
    assert set(metro.loc["16740"].index.get_level_values("industry_code")) == {"10", "1012", "1029", "31"}
    total = metro.loc[("16740", "10", 2023)]
    assert total[P + "employment_count"] == 1200          # 1000 + 200, nothing from the other ownerships
    assert total[P + "establishments_count"] == 120
    assert total[P + "total_wages_usd"] == 58_000


def test_state_metro_combined_and_non_metro_county_files_are_ignored(project, crosswalk_csv):
    files = charlotte_files()
    files["37000 North Carolina -- Statewide"] = [row("37000", "10", 51, 9999, 99_999, 9_999_999)]
    files["C1674 Charlotte-Concord-Gastonia, NC-SC MSA"] = [row("C1674", "10", 41, 9999, 99_999, 9_999_999)]
    files["CS172 Charlotte-Concord, NC-SC CSA"] = [row("CS172", "10", 31, 9999, 99_999, 9_999_999)]
    files["06037 Los Angeles County, California"] = [row("06037", "10", TOTAL_LEVEL, 9999, 99_999, 9_999_999)]  # not in the crosswalk
    files["37999 Test County, North Carolina"] = [row("37999", "10", TOTAL_LEVEL, 9999, 99_999, 9_999_999)]     # micropolitan
    metro, _ = run_transform(project, files)
    assert set(metro.index.get_level_values("cbsa_code")) == {"16740"}
    assert metro.loc[("16740", "10", 2023), P + "employment_count"] == 1200


def test_a_suppressed_county_has_empty_employment_and_wages_but_keeps_its_establishments(project, crosswalk_csv):
    files = charlotte_files()
    files["45091 York County, South Carolina"][1] = row("45091", "1012", SUPER_LEVEL, 20, 0, 0, disclosure="N")
    metro, _ = run_transform(project, files)
    metro_row = metro.loc[("16740", "1012", 2023)]
    assert metro_row[P + "employment_count"] == 400         # Mecklenburg only: a partial sum, not 400 + 0
    assert metro_row[P + "total_wages_usd"] == 20_000
    assert metro_row[P + "establishments_count"] == 60      # York's 20 establishments are kept


def test_a_metro_whose_only_county_is_suppressed_has_empty_employment_and_wages_not_zero(project, crosswalk_csv):
    files = {"01073 Jefferson County, Alabama": [row("01073", "1012", SUPER_LEVEL, 3, 0, 0, disclosure="N")]}
    metro, _ = run_transform(project, files)
    birmingham = metro.loc[("13820", "1012", 2023)]
    assert pd.isna(birmingham[P + "employment_count"])
    assert pd.isna(birmingham[P + "total_wages_usd"])
    assert birmingham[P + "establishments_count"] == 3
    assert birmingham[P + "counties_reported_count"] == 0
    assert birmingham[P + "counties_suppressed_count"] == 1


def test_the_reported_and_suppressed_counties_are_counted(project, crosswalk_csv):
    files = charlotte_files()
    files["45091 York County, South Carolina"][1] = row("45091", "1012", SUPER_LEVEL, 20, 0, 0, disclosure="N")
    metro, _ = run_transform(project, files)
    suppressed_row = metro.loc[("16740", "1012", 2023)]
    assert (suppressed_row[P + "counties_reported_count"], suppressed_row[P + "counties_suppressed_count"]) == (1, 1)
    both = metro.loc[("16740", "10", 2023)]
    assert (both[P + "counties_reported_count"], both[P + "counties_suppressed_count"]) == (2, 0)
    only_one = metro.loc[("16740", "1029", 2023)]   # York has no 1029 row: not reported, not suppressed
    assert (only_one[P + "counties_reported_count"], only_one[P + "counties_suppressed_count"]) == (1, 0)


def test_supersectors_plus_unclassified_equal_the_total_and_the_checks_see_it(project, crosswalk_csv):
    metro, us = run_transform(project, charlotte_files())
    total = metro.loc[("16740", "10", 2023), P + "employment_count"]
    supers = metro.xs("16740").loc[["1012", "1029"], P + "employment_count"].sum()
    assert supers == total == 1200   # 1012: 400 + 200, and 1029: 600
    results = checks.industry_checks(metro.reset_index(), us.reset_index())
    assert all(r.passed for r in results if r.check.startswith("supersectors add up") or r.level == "error")


def test_a_gap_between_supersectors_and_total_is_an_error_unless_a_county_is_suppressed(project, crosswalk_csv):
    files = charlotte_files()
    files["37119 Mecklenburg County, North Carolina"][1] = row("37119", "1012", SUPER_LEVEL, 40, 300, 20_000)  # 100 jobs short
    metro, us = run_transform(project, files)
    failures = [r for r in checks.industry_checks(metro.reset_index(), us.reset_index()) if not r.passed and r.table == "msa_industry_year"]
    assert [(r.level, "employment_count" in r.check) for r in failures] == [("error", True)]

    files = charlotte_files()
    files["37119 Mecklenburg County, North Carolina"][1] = row("37119", "1012", SUPER_LEVEL, 40, 0, 0, disclosure="N")
    metro, us = run_transform(project, files)
    failures = [r for r in checks.industry_checks(metro.reset_index(), us.reset_index()) if not r.passed and r.table == "msa_industry_year"]
    assert failures and all(r.level == "warning" for r in failures)   # the supersectors fall short by design


def test_the_sector_ranges_are_recoded_and_each_row_gets_its_level(project, crosswalk_csv):
    files = {"37119 Mecklenburg County, North Carolina": [
        row("37119", "10", TOTAL_LEVEL, 100, 1000, 50_000),
        row("37119", "31-33", SECTOR_LEVEL, 10, 100, 6_000),
        row("37119", "44-45", SECTOR_LEVEL, 11, 110, 7_000),
        row("37119", "48-49", SECTOR_LEVEL, 12, 120, 8_000),
        row("37119", "52", SECTOR_LEVEL, 13, 130, 9_000),
        row("37119", "1013", SUPER_LEVEL, 10, 100, 6_000),
    ]}
    metro, us = run_transform(project, files)
    codes = set(metro.loc["16740"].index.get_level_values("industry_code"))
    assert {"31", "44", "48", "52", "1013", "10"} == codes
    assert not {"31-33", "44-45", "48-49"} & codes
    levels = metro.loc["16740"].groupby("industry_code")["bls_industry_level"].first()
    assert levels.to_dict() == {"10": "total", "1013": "supersector", "31": "sector", "44": "sector",
                                "48": "sector", "52": "sector"}
    assert set(us.index.get_level_values("industry_code")) == {"10", "1012", "1029", "23", "31"}   # the U.S. file's 31-33 too


def test_a_sector_that_repeats_a_supersector_keeps_both_rows(project, crosswalk_csv):
    files = {"37119 Mecklenburg County, North Carolina": [
        row("37119", "1012", SUPER_LEVEL, 40, 400, 20_000),
        row("37119", "23", SECTOR_LEVEL, 40, 400, 20_000),
    ]}
    metro, _ = run_transform(project, files)
    assert metro.loc[("16740", "1012", 2023), P + "employment_count"] == metro.loc[("16740", "23", 2023), P + "employment_count"] == 400


def test_the_us_rows_are_read_with_the_same_columns(project, crosswalk_csv):
    _, us = run_transform(project, charlotte_files())
    total = us.loc[("10", 2023)]
    assert total["bls_industry_level"] == "total"
    assert (total[P + "establishments_count"], total[P + "employment_count"], total[P + "total_wages_usd"]) == (1000, 10_000, 500_000)
    assert us.loc[("1029", 2023), "bls_industry_level"] == "supersector"
    assert us.loc[("23", 2023), "bls_industry_level"] == "sector"
    assert not [c for c in us.columns if not c.startswith("bls_")]


def test_a_missing_unclassified_row_is_absent_not_zero(project, crosswalk_csv):
    files = {"45091 York County, South Carolina": [row("45091", "10", TOTAL_LEVEL, 20, 200, 8_000)]}   # no 1029
    metro, _ = run_transform(project, files)
    assert ("16740", "1029", 2023) not in metro.index


def test_a_zip_without_the_us_file_or_with_an_unknown_industry_code_is_rejected(project, crosswalk_csv):
    path = write_qcew_zip(project, 2023, charlotte_files())    # no U.S. file inside
    with pytest.raises(ValueError, match="no U.S. file"):
        ingest_qcew.transform([path], [2023])
    files = charlotte_files()
    files["37119 Mecklenburg County, North Carolina"].append(row("37119", "9999", SECTOR_LEVEL, 1, 1, 1))
    path = write_qcew_zip(project, 2023, {**files, **us_files()})
    with pytest.raises(ValueError, match="not in the expected 32"):
        ingest_qcew.transform([path], [2023])


def test_download_returns_the_existing_files_and_asks_for_a_missing_one(project):
    path = write_qcew_zip(project, 2023, us_files())
    assert ingest_qcew.download([2023]) == [path]
    with pytest.raises(FileNotFoundError, match="run ingest_bea_bls first"):
        ingest_qcew.download([2023, 2022])


def test_years_that_were_not_asked_for_are_skipped(project, crosswalk_csv):
    path_2022 = write_qcew_zip(project, 2022, {**charlotte_files(), **us_files()})
    path_2023 = write_qcew_zip(project, 2023, {**charlotte_files(), **us_files()})
    ingest_qcew.transform([path_2022, path_2023], [2023])
    metro = pd.read_parquet(project["INTERIM"] / "msa_industry_year" / "bls.parquet")
    assert set(metro["year"]) == {2023}


def test_the_build_and_the_checks_pass_on_the_fake_data(project, crosswalk_csv):
    run_transform(project, charlotte_files())
    build_panel.build_all()
    metro = pd.read_parquet(project["PROCESSED"] / "msa_industry_year.parquet")
    us = pd.read_parquet(project["PROCESSED"] / "us_industry_year.parquet")
    assert len(metro) == 4 and len(us) == 5   # Charlotte's total, two supersectors and one sector
    assert checks.run_checks()
    assert set(config.TABLES["msa_industry_year"]) == {"cbsa_code", "industry_code", "year"}
