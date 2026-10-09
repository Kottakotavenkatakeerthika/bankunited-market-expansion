import pandas as pd
import pytest

from src import config
from src.ingest_pep import NEW_FILE, OLD_FILE, transform

OLD_YEARS = [2018, 2019]
NEW_YEARS = [2020, 2021, 2022]


def write_pep_csv(path, natural, years, rows):
    """A tiny file laid out like a Census county file. rows: (state, county, name, {year: (pop, nat, dom, intl, net)})."""
    records = []
    for state, county, name, by_year in rows:
        record = {"SUMLEV": "050" if county != "000" else "040", "STATE": state, "COUNTY": county,
                  "STNAME": "Test", "CTYNAME": name}
        for year in years:
            pop, nat, dom, intl, net = by_year.get(year, (None,) * 5)
            record.update({f"POPESTIMATE{year}": pop, f"{natural}{year}": nat, f"DOMESTICMIG{year}": dom,
                           f"INTERNATIONALMIG{year}": intl, f"NETMIG{year}": net})
        records.append(record)
    pd.DataFrame(records).to_csv(path, index=False, encoding="latin-1")
    return path


@pytest.fixture
def pep_files(tmp_path):
    old = write_pep_csv(tmp_path / OLD_FILE, "NATURALINC", OLD_YEARS, [
        ("37", "000", "North Carolina", {2019: (999, 9, 9, 9, 9)}),
        ("37", "119", "Mecklenburg County", {2018: (1000, 10, 5, 2, 7), 2019: (1100, 11, 6, 3, 9)}),
        ("45", "091", "York County", {2018: (300, 3, 1, 1, 2), 2019: (320, 4, 2, 1, 3)}),
        ("09", "001", "Fairfield County", {2019: (900, 5, 5, 5, 10)}),
    ])
    new = write_pep_csv(tmp_path / NEW_FILE, "NATURALCHG", NEW_YEARS, [
        ("37", "000", "North Carolina", {2021: (999, 9, 9, 9, 9)}),
        ("37", "119", "Mecklenburg County", {
            2020: (1090, 1, 1, 1, 2), 2021: (1120, -4, -20, 5, -15), 2022: (1150, 12, 8, 3, 11)}),
        ("45", "091", "York County", {
            2020: (310, 1, 1, 1, 2), 2021: (330, 2, -3, 1, -2), 2022: (None, None, None, None, None)}),
    ])
    return [old, new]


def build(pep_files, years, project, crosswalk_csv):
    transform(pep_files, years)
    return pd.read_parquet(project["INTERIM"] / "msa_year" / "pep.parquet").set_index(["cbsa_code", "year"])


def test_old_and_new_file_formats_are_both_read(pep_files, project, crosswalk_csv):
    out = build(pep_files, [2019, 2021], project, crosswalk_csv)
    assert out.loc[("16740", 2019), "pep_population_count"] == 1100 + 320
    assert out.loc[("16740", 2019), "pep_natural_change_net"] == 11 + 4        # NATURALINC
    assert out.loc[("16740", 2021), "pep_natural_change_net"] == -4 + 2        # NATURALCHG
    assert out.loc[("16740", 2021), "pep_international_migration_net"] == 5 + 1


def test_2020_keeps_population_but_blanks_all_flows(pep_files, project, crosswalk_csv):
    row = build(pep_files, [2019, 2020], project, crosswalk_csv).loc[("16740", 2020)]
    assert row["pep_population_count"] == 1090 + 310
    flows = ["pep_natural_change_net", "pep_domestic_migration_net",
             "pep_international_migration_net", "pep_migration_net"]
    assert row[flows].isna().all()


def test_negative_flows_are_kept_as_negatives(pep_files, project, crosswalk_csv):
    row = build(pep_files, [2021], project, crosswalk_csv).loc[("16740", 2021)]
    assert row["pep_migration_net"] == -15 + -2
    assert row["pep_domestic_migration_net"] == -20 + -3
    assert pd.read_parquet(project["INTERIM"] / "msa_year" / "pep.parquet")["pep_natural_change_net"].min() < 0
    assert build(pep_files, [2021], project, crosswalk_csv)["pep_natural_change_net"].notna().all()


def test_state_rows_are_excluded(pep_files, project, crosswalk_csv):
    # The state row's 999 population must not leak into any metro.
    out = build(pep_files, [2019, 2021], project, crosswalk_csv)
    assert out["pep_population_count"].max() < 999 + 1100
    assert out.loc[("16740", 2021), "pep_counties_reported_count"] == 2


def test_county_not_in_crosswalk_is_dropped_and_counted(pep_files, project, crosswalk_csv, capsys):
    out = build(pep_files, [2019], project, crosswalk_csv)
    assert out.loc[("16740", 2019), "pep_population_count"] == 1100 + 320    # Fairfield (09001) not added
    assert list(out.index.get_level_values("cbsa_code")) == ["16740"]
    printed = capsys.readouterr().out
    assert "2019: 1 county rows not in the crosswalk" in printed and "old Connecticut codes: 1" in printed


def test_missing_county_is_left_out_of_the_sum_and_shows_in_the_count(pep_files, project, crosswalk_csv):
    out = build(pep_files, [2021, 2022], project, crosswalk_csv)
    assert out.loc[("16740", 2021), "pep_counties_reported_count"] == 2
    assert out.loc[("16740", 2022), "pep_counties_reported_count"] == 1      # York has no 2022 population
    assert out.loc[("16740", 2022), "pep_population_count"] == 1150          # not 1150 + 0 for York


def test_2025_is_skipped(pep_files, project, crosswalk_csv, capsys):
    out = build(pep_files, [2021, 2025], project, crosswalk_csv)
    assert sorted(out.index.get_level_values("year").unique()) == [2021]
    assert "skipping 2025" in capsys.readouterr().out


def test_vintage_year_comes_from_the_source_file_and_is_not_summed(pep_files, project, crosswalk_csv):
    out = build(pep_files, [2019, 2020, 2021], project, crosswalk_csv)
    assert out.loc[("16740", 2019), "pep_vintage_year"] == 2020
    assert out.loc[("16740", 2020), "pep_vintage_year"] == 2025
    assert out.loc[("16740", 2021), "pep_vintage_year"] == 2025   # two counties, still 2025 and not 4050
