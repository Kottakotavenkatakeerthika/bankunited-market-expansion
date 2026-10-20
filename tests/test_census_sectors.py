import zipfile

import pandas as pd
import pytest

from src import ingest_census

ALL_INDUSTRY = "------"


def row(county_fips, naics, est, emp, qp1, ap, flag="G", empflag=None, sizes=None):
    """One line of a CBP county file. qp1 and ap are in $1,000s, as published.

    sizes: establishment size-class counts by column name, e.g. {"n<5": 40, "n5_9": "N"}.
    """
    return {
        "fipstate": county_fips[:2], "fipscty": county_fips[2:], "naics": naics,
        "empflag": empflag, "emp_nf": flag, "emp": emp, "qp1_nf": flag, "qp1": qp1,
        "ap_nf": flag, "ap": ap, "est": est, **(sizes or {}),
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




# --------------------------------------------------------------- sectors and size classes
# Establishments by size class for one county, adding up to est=103. N1000_1 and N1000_2 split N1000.
SIZES = {"n<5": 40, "n5_9": 20, "n10_19": 15, "n20_49": 10, "n50_99": 8, "n100_249": 4,
         "n250_499": 2, "n500_999": 1, "n1000": 3, "n1000_1": 1, "n1000_2": 2}
ONES = {key: 1 for key in ("n<5", "n5_9", "n10_19", "n20_49", "n50_99", "n100_249", "n250_499", "n500_999", "n1000")}
MSA_YEAR_COLUMNS = ["cbp_establishments_count", "cbp_employment_count", "cbp_first_quarter_payroll_usd",
                    "cbp_annual_payroll_usd", "cbp_establishments_20plus_count",
                    "cbp_establishments_20_249_count"]


def sectors(project):
    out = pd.read_parquet(project["INTERIM"] / "msa_naics_year" / "cbp.parquet")
    return out.set_index(["cbsa_code", "naics_code", "year"])


def total_with_sizes(county_fips="37119", est=103, sizes=SIZES):
    return row(county_fips, ALL_INDUSTRY, est=est, emp=50, qp1=100, ap=400, sizes=sizes)


def test_sector_rows_are_kept_and_the_all_industry_and_detailed_rows_are_not(project, crosswalk_csv):
    path = write_cbp_zip(project, 2023, [
        row("37119", ALL_INDUSTRY, est=50, emp=500, qp1=50, ap=900),
        row("37119", "23----", est=10, emp=100, qp1=20, ap=400),
        row("37119", "99----", est=1, emp=2, qp1=1, ap=3),
        row("37119", "531///", est=88, emp=888, qp1=88, ap=888),      # a detailed industry: not a sector
        row("37119", "236///", est=77, emp=777, qp1=77, ap=777),      # three digits: not a sector
    ])
    ingest_census.transform([path], [2023])
    out = sectors(project)
    assert sorted(out.index.get_level_values("naics_code")) == ["23", "99"]      # 99 is unclassified and kept
    assert out.loc[("16740", "23", 2023), "cbp_establishments_count"] == 10


def test_naics_code_is_a_two_character_string_and_ranges_are_not_expanded(project, crosswalk_csv):
    path = write_cbp_zip(project, 2023, [
        row("37119", "31----", est=5, emp=50, qp1=1, ap=10),          # 31 covers 31-33
        row("37119", "44----", est=6, emp=60, qp1=1, ap=10),          # 44 covers 44-45
        row("37119", "48----", est=7, emp=70, qp1=1, ap=10),          # 48 covers 48-49
    ])
    ingest_census.transform([path], [2023])
    codes = pd.read_parquet(project["INTERIM"] / "msa_naics_year" / "cbp.parquet")["naics_code"]
    assert str(codes.dtype) == "string"
    assert codes.str.len().eq(2).all()
    assert codes.tolist() == ["31", "44", "48"]                     # no 32, 33, 45 or 49


def test_2015_to_2017_withheld_cells_become_missing_and_establishments_stay(project, crosswalk_csv):
    path = write_cbp_zip(project, 2016, [
        row("37119", "23----", est=3, emp=0, qp1=0, ap=0, flag="D", empflag="A"),      # both withheld, zeros published
        row("45091", "23----", est=4, emp=16, qp1=30, ap=90),
        row("37119", "54----", est=2, emp=0, qp1=0, ap=0, flag="S", empflag="B"),      # both withheld
        row("45091", "54----", est=5, emp=0, qp1=9, ap=60, empflag="C"),               # only the EMPFLAG letter: employment
    ], old_format=True)
    ingest_census.transform([path], [2016])
    out = sectors(project)
    s23, s54 = out.loc[("16740", "23", 2016)], out.loc[("16740", "54", 2016)]
    assert s23["cbp_establishments_count"] == 7                     # EST is published even when EMP and AP are not
    assert s23["cbp_employment_count"] == 16                        # Mecklenburg's withheld 0 adds nothing
    assert s23["cbp_annual_payroll_usd"] == 90_000
    assert s54["cbp_establishments_count"] == 7
    assert pd.isna(s54["cbp_employment_count"])                     # every county withheld: missing, never 0
    assert s54["cbp_annual_payroll_usd"] == 60_000                  # York's payroll was published


def test_2018_on_values_are_used_as_published_with_their_noise_flags(project, crosswalk_csv):
    path = write_cbp_zip(project, 2018, [
        row("37119", "23----", est=10, emp=100, qp1=20, ap=400, flag="G"),
        row("45091", "23----", est=4, emp=50, qp1=10, ap=100, flag="J"),
    ])
    ingest_census.transform([path], [2018])
    s23 = sectors(project).loc[("16740", "23", 2018)]
    assert s23["cbp_employment_count"] == 150
    assert s23["cbp_annual_payroll_usd"] == 500_000


def test_an_omitted_county_sector_gives_no_row_and_counties_reported_counts_counties_with_a_row(
        project, crosswalk_csv):
    path = write_cbp_zip(project, 2023, [
        row("37119", "23----", est=10, emp=100, qp1=20, ap=400),
        row("45091", "23----", est=4, emp=16, qp1=5, ap=90),
        row("37119", "54----", est=6, emp=60, qp1=9, ap=300),          # York has no 54 row: Census omitted it
    ])
    ingest_census.transform([path], [2023])
    out = sectors(project)
    assert out.loc[("16740", "23", 2023), "cbp_counties_reported_count"] == 2
    assert out.loc[("16740", "54", 2023), "cbp_counties_reported_count"] == 1
    assert out.loc[("16740", "54", 2023), "cbp_establishments_count"] == 6         # nothing added for York, no 0 row
    assert ("16740", "62", 2023) not in out.index                                  # no county has a 62 row: no row


def test_a_withheld_county_is_not_counted_as_reported(project, crosswalk_csv):
    path = write_cbp_zip(project, 2016, [
        row("37119", "23----", est=3, emp=0, qp1=0, ap=0, flag="D", empflag="A"),
        row("45091", "23----", est=4, emp=16, qp1=30, ap=90),
    ], old_format=True)
    ingest_census.transform([path], [2016])
    s23 = sectors(project).loc[("16740", "23", 2016)]
    assert s23["cbp_counties_reported_count"] == 1                  # only York published employment and payroll
    assert s23["cbp_establishments_count"] == 7                     # EST is still summed over both


def test_when_some_but_not_all_counties_are_withheld_only_the_published_ones_count(project, crosswalk_csv):
    path = write_cbp_zip(project, 2016, [
        row("37119", "23----", est=3, emp=0, qp1=0, ap=0, flag="D", empflag="A"),      # both withheld
        row("45091", "23----", est=4, emp=16, qp1=30, ap=90),                          # published
        row("37119", "54----", est=2, emp=0, qp1=0, ap=0, flag="S", empflag="B"),      # both withheld
        row("45091", "54----", est=5, emp=0, qp1=9, ap=60, empflag="C"),               # employment withheld only
        row("37119", "62----", est=8, emp=80, qp1=9, ap=300),                          # published
        row("45091", "62----", est=6, emp=60, qp1=9, ap=200),                          # published
        row("01073", "62----", est=1, emp=0, qp1=0, ap=0, flag="D", empflag="A"),      # Birmingham: every county withheld
    ], old_format=True)
    ingest_census.transform([path], [2016])
    out = sectors(project)
    assert out.loc[("16740", "23", 2016), "cbp_counties_reported_count"] == 1     # 1 of 2
    assert out.loc[("16740", "54", 2016), "cbp_counties_reported_count"] == 0     # none: employment or payroll withheld
    assert out.loc[("16740", "62", 2016), "cbp_counties_reported_count"] == 2     # all published
    assert out.loc[("13820", "62", 2016), "cbp_counties_reported_count"] == 0     # 0, not missing: the row exists


def test_two_counties_sum_to_the_metro_for_every_sector_measure(project, crosswalk_csv):
    path = write_cbp_zip(project, 2023, [
        row("37119", "23----", est=10, emp=100, qp1=20, ap=400),
        row("45091", "23----", est=4, emp=16, qp1=5, ap=90),
        row("01073", "23----", est=99, emp=999, qp1=99, ap=999),       # Birmingham: its own metro
    ])
    ingest_census.transform([path], [2023])
    out = sectors(project)
    charlotte = out.loc[("16740", "23", 2023)]
    assert charlotte["cbp_establishments_count"] == 14
    assert charlotte["cbp_employment_count"] == 116
    assert charlotte["cbp_annual_payroll_usd"] == 490_000              # $1,000s converted to dollars
    assert charlotte["cbp_counties_reported_count"] == 2
    assert out.loc[("13820", "23", 2023), "cbp_establishments_count"] == 99


def test_transform_writes_both_interim_files_and_returns_both_paths(project, crosswalk_csv):
    path = write_cbp_zip(project, 2023, [
        row("37119", ALL_INDUSTRY, est=50, emp=500, qp1=50, ap=900),
        row("37119", "23----", est=10, emp=100, qp1=20, ap=400),
    ])
    paths = ingest_census.transform([path], [2023])
    assert [p.parent.name for p in paths] == ["msa_year", "msa_naics_year"]
    assert all(p.name == "cbp.parquet" and p.exists() for p in paths)


def test_the_existing_msa_year_columns_and_values_are_unchanged(project, crosswalk_csv):
    path = write_cbp_zip(project, 2023, [
        total_with_sizes("37119"),
        total_with_sizes("45091", est=9, sizes=ONES),
        row("37119", "23----", est=999, emp=999, qp1=999, ap=999),      # a sector row must not leak into msa_year
    ])
    ingest_census.transform([path], [2023])
    out = pd.read_parquet(project["INTERIM"] / "msa_year" / "cbp.parquet")
    assert list(out.columns) == ["cbsa_code", "year", *MSA_YEAR_COLUMNS]
    charlotte = out.set_index(["cbsa_code", "year"]).loc[("16740", 2023)]
    assert charlotte["cbp_establishments_count"] == 112                # 103 + 9, sector row excluded
    assert charlotte["cbp_employment_count"] == 100
    assert charlotte["cbp_first_quarter_payroll_usd"] == 200_000
    assert charlotte["cbp_annual_payroll_usd"] == 800_000


def test_20_plus_is_est_minus_the_three_small_classes(project):
    path = write_cbp_zip(project, 2023, [total_with_sizes()])
    county = ingest_cbp_county(path, "37119")
    assert county["cbp_establishments_20plus_count"] == 28            # 103 - (40 + 20 + 15)
    assert county["cbp_establishments_20_249_count"] == 22            # 10 + 8 + 4


def test_20_plus_falls_back_to_summing_the_large_classes_when_a_small_class_is_suppressed(project):
    for suppressed in ("n<5", "n5_9", "n10_19"):
        path = write_cbp_zip(project, 2023, [total_with_sizes(sizes={**SIZES, suppressed: "N"})])
        county = ingest_cbp_county(path, "37119")
        # 10 + 8 + 4 + 2 + 1 + 3; N1000_1 and N1000_2 split N1000 and are not added again.
        assert county["cbp_establishments_20plus_count"] == 28, suppressed


def test_the_smallest_size_class_is_read_as_n1_4_in_2015_and_2016_and_n_lt_5_from_2017(project):
    old_sizes = {("n1_4" if key == "n<5" else key): value for key, value in SIZES.items()}
    old = write_cbp_zip(project, 2016, [total_with_sizes(sizes=old_sizes)], old_format=True)
    new = write_cbp_zip(project, 2017, [total_with_sizes(sizes=SIZES)], old_format=True)
    assert ingest_cbp_county(old, "37119")["cbp_establishments_20plus_count"] == 28
    assert ingest_cbp_county(new, "37119")["cbp_establishments_20plus_count"] == 28


def test_20_to_249_counts_a_suppressed_class_as_zero(project):
    path = write_cbp_zip(project, 2023, [total_with_sizes(sizes={**SIZES, "n50_99": "N"})])
    county = ingest_cbp_county(path, "37119")
    assert county["cbp_establishments_20_249_count"] == 14            # 10 + 0 + 4, short by the hidden 8
    assert county["cbp_establishments_20plus_count"] == 28            # the small classes are present: subtraction


def test_size_class_counts_sum_county_to_metro(project, crosswalk_csv):
    path = write_cbp_zip(project, 2023, [total_with_sizes("37119"), total_with_sizes("45091", est=9, sizes=ONES)])
    ingest_census.transform([path], [2023])
    charlotte = result(project).loc[("16740", 2023)]
    assert charlotte["cbp_establishments_20plus_count"] == 34         # 28 + 6
    assert charlotte["cbp_establishments_20_249_count"] == 25         # 22 + 3


def test_a_file_without_any_size_class_columns_leaves_the_size_measures_missing_not_zero(project):
    path = write_cbp_zip(project, 2023, [row("37119", ALL_INDUSTRY, est=10, emp=50, qp1=100, ap=400)])
    county = ingest_cbp_county(path, "37119")
    assert pd.isna(county["cbp_establishments_20plus_count"])
    assert pd.isna(county["cbp_establishments_20_249_count"])


def test_a_file_with_only_some_size_class_columns_is_rejected(project):
    path = write_cbp_zip(project, 2023, [row("37119", ALL_INDUSTRY, est=10, emp=50, qp1=100, ap=400,
                                             sizes={"n<5": 4})])
    with pytest.raises(ValueError, match="missing expected size-class columns"):
        ingest_census._read_one_year(path)
