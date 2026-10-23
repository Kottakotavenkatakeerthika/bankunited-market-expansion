import zipfile

import pandas as pd
import pytest

from src import ingest_census

ALL_INDUSTRY = "------"


def row(county_fips, naics, est, emp, qp1, ap, flag="G", empflag=None):
    """One line of a CBP county file. qp1 and ap are in $1,000s, as published."""
    return {
        "fipstate": county_fips[:2], "fipscty": county_fips[2:], "naics": naics,
        "empflag": empflag, "emp_nf": flag, "emp": emp, "qp1_nf": flag, "qp1": qp1,
        "ap_nf": flag, "ap": ap, "est": est,
    }


def write_cbp_zip(project, year, rows, old_format=False, drop=None, name=None):
    """Write a fake cbp<YY>co.zip into the temporary raw folder."""
    frame = pd.DataFrame(rows)
    if old_format:  # 2015-2017: upper-case headers and an EMPFLAG column
        frame = frame.rename(columns=str.upper)
    else:
        frame = frame.drop(columns="empflag")
    if drop:
        frame = frame.drop(columns=drop)
    folder = project["RAW"] / "cbp"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (name or f"cbp{year % 100:02d}co.zip")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("cbp_county.txt", frame.to_csv(index=False))
    return path


def result(project):
    out = pd.read_parquet(project["INTERIM"] / "msa_year" / "cbp.parquet")
    return out.set_index(["cbsa_code", "year"])


def ingest_cbp_county(path, county_fips):
    return ingest_census._read_one_year(path).set_index("county_fips").loc[county_fips]


def test_payroll_is_converted_from_thousands_to_whole_dollars(project):
    path = write_cbp_zip(project, 2023, [row("37119", ALL_INDUSTRY, est=10, emp=50, qp1=100, ap=2000)])
    county = ingest_cbp_county(path, "37119")
    assert county["cbp_first_quarter_payroll_usd"] == 100_000     # $1,000s to dollars
    assert county["cbp_annual_payroll_usd"] == 2_000_000
    assert county["cbp_establishments_count"] == 10               # counts are not scaled
    assert county["cbp_employment_count"] == 50
    assert county["year"] == 2023                                 # taken from the file name


def test_only_the_all_industry_row_is_kept_and_codes_are_zero_padded(project):
    total = row("01073", ALL_INDUSTRY, est=7, emp=70, qp1=10, ap=40)
    total.update(fipstate="1", fipscty="73")                            # written without padding, as a number would be
    path = write_cbp_zip(project, 2023, [
        total,
        row("01073", "23----", est=99, emp=999, qp1=999, ap=999),      # a sector row: not wanted
        row("01073", "531///", est=88, emp=888, qp1=888, ap=888),      # a detailed industry row: not wanted
    ])
    counties = ingest_census._read_one_year(path)
    assert counties["county_fips"].tolist() == ["01073"]
    assert counties["cbp_establishments_count"].tolist() == [7]


def test_two_counties_in_one_metro_sum_for_every_measure(project, crosswalk_csv):
    path = write_cbp_zip(project, 2023, [
        row("37119", ALL_INDUSTRY, est=10, emp=50, qp1=100, ap=400),     # Mecklenburg
        row("45091", ALL_INDUSTRY, est=4, emp=16, qp1=30, ap=90),        # York
    ])
    ingest_census.transform([path], [2023])
    charlotte = result(project).loc[("16740", 2023)]
    assert charlotte["cbp_establishments_count"] == 14
    assert charlotte["cbp_employment_count"] == 66
    assert charlotte["cbp_first_quarter_payroll_usd"] == 130_000
    assert charlotte["cbp_annual_payroll_usd"] == 490_000


def test_counties_outside_the_crosswalk_are_dropped_without_error(project, crosswalk_csv):
    path = write_cbp_zip(project, 2023, [
        row("37119", ALL_INDUSTRY, est=10, emp=50, qp1=100, ap=400),
        row("99999", ALL_INDUSTRY, est=777, emp=777, qp1=777, ap=777),   # not in the crosswalk at all
        row("37999", ALL_INDUSTRY, est=555, emp=555, qp1=555, ap=555),   # micropolitan: not a metro
    ])
    ingest_census.transform([path], [2023])
    out = result(project)
    assert list(out.index.get_level_values("cbsa_code").unique()) == ["16740"]
    assert out.loc[("16740", 2023), "cbp_establishments_count"] == 10       # nothing from the dropped counties


def test_download_skips_2024_with_a_message_and_asks_for_one_zip_per_earlier_year(project, monkeypatch, capsys):
    calls = []

    def fake_fetch(url, source, filename=None, *, force=False, notes=""):
        calls.append((url, filename))
        return project["RAW"] / source / filename

    monkeypatch.setattr(ingest_census, "fetch", fake_fetch)
    paths = ingest_census.download([2022, 2023, 2024])
    assert [path.name for path in paths] == ["cbp22co.zip", "cbp23co.zip"]
    assert calls[1] == ("https://www2.census.gov/programs-surveys/cbp/datasets/2023/cbp23co.zip", "cbp23co.zip")
    assert "skipping 2024: CBP hasn't published past 2023 yet" in capsys.readouterr().out


def test_2015_to_2017_layout_with_empflag_and_upper_case_headers_is_read(project, crosswalk_csv):
    path = write_cbp_zip(project, 2016, [
        row("37119", ALL_INDUSTRY, est=10, emp=50, qp1=100, ap=400, empflag=None),
        row("45091", ALL_INDUSTRY, est=4, emp=16, qp1=30, ap=90, empflag=None),
    ], old_format=True)
    ingest_census.transform([path], [2016])
    assert result(project).loc[("16740", 2016), "cbp_establishments_count"] == 14


def test_a_missing_column_and_a_file_name_without_a_year_are_rejected_clearly(project):
    no_est = write_cbp_zip(project, 2023, [row("37119", ALL_INDUSTRY, est=10, emp=50, qp1=100, ap=400)], drop="est")
    with pytest.raises(ValueError, match="missing expected columns"):
        ingest_census._read_one_year(no_est)

    nameless = write_cbp_zip(project, 2023, [row("37119", ALL_INDUSTRY, est=10, emp=50, qp1=100, ap=400)],
                             name="cbp_data.zip")
    with pytest.raises(ValueError, match="Can't tell what year"):
        ingest_census._read_one_year(nameless)


def test_documents_that_transform_ignores_its_years_argument(project, crosswalk_csv):
    older = write_cbp_zip(project, 2022, [row("37119", ALL_INDUSTRY, est=10, emp=50, qp1=100, ap=400)])
    newer = write_cbp_zip(project, 2023, [row("37119", ALL_INDUSTRY, est=11, emp=55, qp1=110, ap=440)])
    ingest_census.transform([older, newer], [2023])        # only 2023 was asked for
    out = result(project)
    assert sorted(out.index.get_level_values("year").unique()) == [2022, 2023]   # 2022 is kept anyway


def test_documents_that_a_withheld_all_industry_row_comes_through_as_zero(project, crosswalk_csv):
    path = write_cbp_zip(project, 2016, [
        row("37119", ALL_INDUSTRY, est=1, emp=0, qp1=0, ap=0, flag="D", empflag="A"),   # D: withheld; the 0s mean not published
    ], old_format=True)
    county = ingest_cbp_county(path, "37119")
    assert county["cbp_employment_count"] == 0               # today the flag is ignored, so it reads as a real zero
    assert county["cbp_annual_payroll_usd"] == 0
    assert county["cbp_establishments_count"] == 1
