import zipfile

import pandas as pd
import pytest

from src import ingest_cra

LINE_LENGTH = 145


def cra_line(state, county, counts=(0, 0, 0), amounts=(0, 0, 0), table="A1-1", level="200"):
    """One fixed-width line, placed at the byte positions in ingest_cra.FIELDS. Amounts are in $1,000s."""
    line = [" "] * LINE_LENGTH

    def put(name, text, left=False):
        start, end = ingest_cra.FIELDS[name]
        width = end - start
        text = str(text)
        line[start:end] = list(text.ljust(width) if left else text.rjust(width))

    put("table_id", table, left=True)
    put("state", state)
    put("county", county)
    put("report_level", level)
    for name, value in zip(("count_under_100k", "count_100k_250k", "count_250k_1m"), counts):
        put(name, value)
    for name, value in zip(("amount_under_100k", "amount_100k_250k", "amount_250k_1m"), amounts):
        put(name, value)
    return "".join(line)


def write_cra_zip(project, year, lines, readme_first=False):
    """A fake <YY>exp_aggr.zip with the fixed-width file inside."""
    folder = project["RAW"] / "cra"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{year % 100:02d}exp_aggr.zip"
    with zipfile.ZipFile(path, "w") as archive:
        if readme_first:
            archive.writestr("A-README.txt", "Aggregate file notes. Not data.\n")
        archive.writestr("aggr.dat", "\n".join(lines) + "\n")
    return path


def result(project):
    out = pd.read_parquet(project["INTERIM"] / "msa_year" / "cra.parquet")
    return out.set_index(["cbsa_code", "year"])


def test_loan_count_is_summed_across_the_three_size_buckets(project, crosswalk_csv):
    path = write_cra_zip(project, 2023, [cra_line("37", "119", counts=(100, 20, 3))])
    ingest_cra.transform([path], [2023])
    assert result(project).loc[("16740", 2023), "cra_small_business_loan_count"] == 123


def test_loan_amount_is_summed_across_buckets_and_converted_from_thousands(project, crosswalk_csv):
    path = write_cra_zip(project, 2023, [cra_line("37", "119", amounts=(1000, 500, 250))])
    ingest_cra.transform([path], [2023])
    assert result(project).loc[("16740", 2023), "cra_small_business_loan_amount_usd"] == 1_750_000  # $1,000s to dollars


def test_other_tables_and_report_levels_are_ignored(project, crosswalk_csv):
    path = write_cra_zip(project, 2023, [
        cra_line("37", "119", counts=(10, 0, 0), amounts=(100, 0, 0)),                 # the County Total row we want
        cra_line("37", "119", counts=(9000, 0, 0), amounts=(9000, 0, 0), table="A1-2"),  # another table
        cra_line("37", "119", counts=(9000, 0, 0), amounts=(9000, 0, 0), level="210"),   # an MSA/MD total, not a county
        cra_line("37", "   ", counts=(9000, 0, 0), amounts=(9000, 0, 0)),                # no county code
    ])
    ingest_cra.transform([path], [2023])
    row = result(project).loc[("16740", 2023)]
    assert row["cra_small_business_loan_count"] == 10
    assert row["cra_small_business_loan_amount_usd"] == 100_000


def test_connecticut_old_county_codes_are_dropped_and_planning_regions_are_kept(project, crosswalk_csv):
    xwalk = pd.read_csv(crosswalk_csv, dtype=str)
    hartford = xwalk.iloc[0].to_dict()
    hartford.update(county_fips="09110", state_fips="09", county_name="Capitol Planning Region",
                    state_name="Connecticut", cbsa_code="25540", cbsa_title="Hartford-West Hartford-East Hartford, CT",
                    cbsa_type="Metropolitan Statistical Area", metro_division_code=None, metro_division_title=None)
    pd.concat([xwalk, pd.DataFrame([hartford])], ignore_index=True).to_csv(crosswalk_csv, index=False)  # local copy only

    old = write_cra_zip(project, 2023, [cra_line("37", "119", counts=(5, 0, 0)), cra_line("09", "003", counts=(40, 0, 0))])
    new = write_cra_zip(project, 2024, [cra_line("37", "119", counts=(6, 0, 0)), cra_line("09", "110", counts=(50, 0, 0))])
    ingest_cra.transform([old, new], [2023, 2024])
    out = result(project)
    assert ("25540", 2023) not in out.index                       # old Hartford County code 09003 maps to nothing
    assert out.loc[("25540", 2024), "cra_small_business_loan_count"] == 50
    assert out.loc[("16740", 2023), "cra_small_business_loan_count"] == 5   # no error, the rest still loads


def test_two_counties_in_one_metro_sum_and_a_micropolitan_county_is_left_out(project, crosswalk_csv):
    path = write_cra_zip(project, 2023, [
        cra_line("37", "119", counts=(10, 0, 0), amounts=(100, 0, 0)),   # Mecklenburg
        cra_line("45", "091", counts=(4, 0, 0), amounts=(40, 0, 0)),     # York
        cra_line("37", "999", counts=(777, 0, 0), amounts=(777, 0, 0)),  # micropolitan, not a metro
    ])
    ingest_cra.transform([path], [2023])
    out = result(project)
    assert out.loc[("16740", 2023), "cra_small_business_loan_count"] == 14
    assert out.loc[("16740", 2023), "cra_small_business_loan_amount_usd"] == 140_000
    assert list(out.index.get_level_values("cbsa_code").unique()) == ["16740"]


def test_a_zip_without_county_total_rows_is_rejected_clearly(project, crosswalk_csv):
    path = write_cra_zip(project, 2023, [cra_line("37", "119", table="A1-2"), cra_line("37", "119", level="210")])
    with pytest.raises(ValueError, match="no County Total rows"):
        ingest_cra.transform([path], [2023])


def test_download_skips_years_after_2024_and_asks_for_one_zip_per_earlier_year(project, monkeypatch, capsys):
    calls = []

    def fake_fetch(url, source, filename=None, *, force=False, notes=""):
        calls.append((url, filename))
        return project["RAW"] / source / filename

    monkeypatch.setattr(ingest_cra, "fetch", fake_fetch)
    paths = ingest_cra.download([2023, 2024, 2025])
    assert [path.name for path in paths] == ["23exp_aggr.zip", "24exp_aggr.zip"]
    assert calls[0] == ("https://www.ffiec.gov/sites/default/files/data/cra/flat-files/23exp_aggr.zip", "23exp_aggr.zip")
    assert "skipping 2025" in capsys.readouterr().out


def test_documents_that_a_readme_listed_first_in_the_zip_is_read_instead_of_the_data(project, crosswalk_csv):
    path = write_cra_zip(project, 2023, [cra_line("37", "119", counts=(10, 0, 0))], readme_first=True)
    with pytest.raises(ValueError, match="no County Total rows"):   # the module reads the first file in the ZIP only
        ingest_cra.transform([path], [2023])


def test_documents_that_a_blank_number_field_stops_the_run_with_a_bare_valueerror(project, crosswalk_csv):
    line = list(cra_line("37", "119", counts=(10, 0, 0)))
    start, end = ingest_cra.FIELDS["count_100k_250k"]
    line[start:end] = " " * (end - start)               # a blank where a number should be
    path = write_cra_zip(project, 2023, ["".join(line)])
    with pytest.raises(ValueError):                      # not a clear message: documents today's behavior
        ingest_cra.transform([path], [2023])
