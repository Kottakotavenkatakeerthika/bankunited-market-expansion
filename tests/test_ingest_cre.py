import zipfile

import pandas as pd
import pytest

from src import ingest_cre

REAL_ESTATE = "531///"
NONRES = "2362//"


def row(county_fips, naics, est, emp, ap, flag="G", empflag=None):
    """One line of a CBP county file. flag is the noise/withholding flag on employment and payroll."""
    return {
        "fipstate": county_fips[:2], "fipscty": county_fips[2:], "naics": naics,
        "empflag": empflag, "emp_nf": flag, "emp": emp, "qp1_nf": flag, "qp1": ap,
        "ap_nf": flag, "ap": ap, "est": est,
    }


def total(county_fips):
    """The all-industry row every county has; it is how the module knows the county exists."""
    return row(county_fips, "------", 99, 999, 9999)


def withheld(county_fips, naics, est):
    """A 2015-2017 withheld cell: flag D, a size-class letter, and a literal 0 in the value fields."""
    return row(county_fips, naics, est, 0, 0, flag="D", empflag="A")


def write_cbp_zip(project, year, rows, old_format=False):
    """Write a fake cbp<YY>co.zip into the temporary raw folder."""
    frame = pd.DataFrame(rows)
    if old_format:  # 2015-2017: upper-case headers and an EMPFLAG column
        frame = frame.rename(columns=str.upper)
    else:
        frame = frame.drop(columns="empflag")
    folder = project["RAW"] / "cbp"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"cbp{year % 100:02d}co.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"cbp{year % 100:02d}co.txt", frame.to_csv(index=False))
    return path


def metro_row(project, year, cbsa_code):
    out = pd.read_parquet(project["INTERIM"] / "msa_year" / "cre.parquet")
    return out[(out["cbsa_code"] == cbsa_code) & (out["year"] == year)].iloc[0]


def test_new_format_reads_both_industries_and_converts_payroll(project):
    path = write_cbp_zip(project, 2019, [
        total("37119"),
        row("37119", REAL_ESTATE, est=10, emp=50, ap=2000),
        row("37119", NONRES, est=3, emp=20, ap=900),
    ])
    county = ingest_cre._read_one_year(path).set_index("county_fips").loc["37119"]
    assert county["year"] == 2019
    assert county["cre_real_estate_establishments_count"] == 10
    assert county["cre_real_estate_employment_count"] == 50
    assert county["cre_real_estate_payroll_usd"] == 2_000_000  # $1,000s to whole dollars
    assert county["cre_nonres_construction_establishments_count"] == 3
    assert county["cre_nonres_construction_employment_count"] == 20
    assert county["cre_nonres_construction_payroll_usd"] == 900_000
    assert county["cre_real_estate_counties_reported_count"] == 1
    assert county["cre_nonres_construction_counties_reported_count"] == 1


@pytest.mark.parametrize("flag", ["D", "S"])
def test_old_format_withheld_cells_become_missing_not_zero(project, flag):
    path = write_cbp_zip(project, 2016, [
        total("37119"), row("37119", REAL_ESTATE, est=10, emp=50, ap=2000, empflag=None),
        total("45091"), row("45091", REAL_ESTATE, est=4, emp=0, ap=0, flag=flag, empflag="A"),
    ], old_format=True)
    counties = ingest_cre._read_one_year(path).set_index("county_fips")

    hidden = counties.loc["45091"]
    assert pd.isna(hidden["cre_real_estate_employment_count"])
    assert pd.isna(hidden["cre_real_estate_payroll_usd"])
    assert hidden["cre_real_estate_establishments_count"] == 4  # EST is published even when EMP and AP are not
    assert hidden["cre_real_estate_counties_reported_count"] == 0

    shown = counties.loc["37119"]
    assert shown["cre_real_estate_employment_count"] == 50
    assert shown["cre_real_estate_payroll_usd"] == 2_000_000
    assert shown["cre_real_estate_counties_reported_count"] == 1


def test_county_without_an_industry_row_is_missing_not_zero(project):
    path = write_cbp_zip(project, 2023, [
        total("37119"), row("37119", REAL_ESTATE, est=10, emp=50, ap=2000),
        total("45091"),  # exists, but has no real estate or construction row
    ])
    absent = ingest_cre._read_one_year(path).set_index("county_fips").loc["45091"]
    for industry in ("real_estate", "nonres_construction"):
        assert pd.isna(absent[f"cre_{industry}_establishments_count"])
        assert pd.isna(absent[f"cre_{industry}_employment_count"])
        assert pd.isna(absent[f"cre_{industry}_payroll_usd"])
        assert absent[f"cre_{industry}_counties_reported_count"] == 0


def test_metro_sums_every_county_when_all_report(project, crosswalk_csv):
    path = write_cbp_zip(project, 2023, [
        total("37119"), row("37119", REAL_ESTATE, est=10, emp=50, ap=2000),
        row("37119", NONRES, est=3, emp=20, ap=900),
        total("45091"), row("45091", REAL_ESTATE, est=4, emp=16, ap=500),
        row("45091", NONRES, est=1, emp=8, ap=300),
    ])
    ingest_cre.transform([path], [2023])
    charlotte = metro_row(project, 2023, "16740")
    assert charlotte["cre_real_estate_establishments_count"] == 14
    assert charlotte["cre_real_estate_employment_count"] == 66
    assert charlotte["cre_real_estate_payroll_usd"] == 2_500_000
    assert charlotte["cre_real_estate_counties_reported_count"] == 2
    assert charlotte["cre_nonres_construction_employment_count"] == 28
    assert charlotte["cre_nonres_construction_payroll_usd"] == 1_200_000
    assert charlotte["cre_nonres_construction_counties_reported_count"] == 2


def test_metro_total_skips_withheld_and_absent_counties(project, crosswalk_csv):
    path = write_cbp_zip(project, 2016, [
        total("37119"), row("37119", REAL_ESTATE, est=10, emp=50, ap=2000),
        row("37119", NONRES, est=3, emp=20, ap=900),
        total("45091"), withheld("45091", REAL_ESTATE, est=4),  # real estate withheld, no construction row
    ], old_format=True)
    ingest_cre.transform([path], [2016])
    charlotte = metro_row(project, 2016, "16740")
    # Real estate: York is withheld, so employment and payroll are Mecklenburg's alone, not Mecklenburg + 0.
    assert charlotte["cre_real_estate_employment_count"] == 50
    assert charlotte["cre_real_estate_payroll_usd"] == 2_000_000
    assert charlotte["cre_real_estate_establishments_count"] == 14  # EST is published for both
    assert charlotte["cre_real_estate_counties_reported_count"] == 1
    # Construction: York has no row, so the metro total is Mecklenburg's alone.
    assert charlotte["cre_nonres_construction_establishments_count"] == 3
    assert charlotte["cre_nonres_construction_employment_count"] == 20
    assert charlotte["cre_nonres_construction_payroll_usd"] == 900_000
    assert charlotte["cre_nonres_construction_counties_reported_count"] == 1


def test_metro_where_no_county_reported_is_missing_not_zero(project, crosswalk_csv):
    path = write_cbp_zip(project, 2016, [
        total("37119"), row("37119", REAL_ESTATE, est=10, emp=50, ap=2000),
        total("01073"), withheld("01073", REAL_ESTATE, est=2),  # Birmingham: withheld, and no construction row
    ], old_format=True)
    ingest_cre.transform([path], [2016])
    birmingham = metro_row(project, 2016, "13820")
    # Withheld real estate: employment and payroll are missing; EST is still published.
    assert pd.isna(birmingham["cre_real_estate_employment_count"])
    assert pd.isna(birmingham["cre_real_estate_payroll_usd"])
    assert birmingham["cre_real_estate_establishments_count"] == 2
    assert birmingham["cre_real_estate_counties_reported_count"] == 0
    # No construction row anywhere in the metro: everything is missing, and zero counties reported.
    assert pd.isna(birmingham["cre_nonres_construction_establishments_count"])
    assert pd.isna(birmingham["cre_nonres_construction_employment_count"])
    assert pd.isna(birmingham["cre_nonres_construction_payroll_usd"])
    assert birmingham["cre_nonres_construction_counties_reported_count"] == 0


def qcew_row(county_fips, industry_code, estabs, emplvl, wages, own_code="5", disclosure=""):
    """One line of a QCEW county file (annual averages)."""
    return {
        "area_fips": county_fips, "own_code": own_code, "industry_code": industry_code,
        "disclosure_code": disclosure, "annual_avg_estabs_count": estabs,
        "annual_avg_emplvl": emplvl, "total_annual_wages": wages,
    }


def write_qcew_zip(project, year, rows_by_county):
    """Write a fake <year>_annual_by_area.zip: one inner CSV per county, plus a state and a metro file to ignore."""
    folder = project["RAW"] / "bls"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{year}_annual_by_area.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for fips, rows in rows_by_county.items():
            frame = pd.DataFrame(rows)
            archive.writestr(f"{year}.annual.by_area/{year}.annual {fips} Test County, Somewhere.csv",
                             frame.to_csv(index=False))
        decoy = pd.DataFrame([qcew_row("37000", "531", 5000, 5000, 5000), qcew_row("C1674", "531", 5000, 5000, 5000)])
        archive.writestr(f"{year}.annual.by_area/{year}.annual 37000 North Carolina -- Statewide.csv", decoy.to_csv(index=False))
        archive.writestr(f"{year}.annual.by_area/{year}.annual C1674 Charlotte MSA.csv", decoy.to_csv(index=False))
    return path


def test_2024_county_with_only_qcew_gets_values_and_is_counted_as_fallback(project, crosswalk_csv):
    qcew = write_qcew_zip(project, 2024, {
        "37119": [qcew_row("37119", "531", 12, 60, 3_000_000), qcew_row("37119", " 2362", 4, 25, 1_000_000)],
    })
    ingest_cre.transform([qcew], [2024])
    charlotte = metro_row(project, 2024, "16740")
    assert charlotte["cre_real_estate_establishments_count"] == 12
    assert charlotte["cre_real_estate_employment_count"] == 60
    assert charlotte["cre_real_estate_payroll_usd"] == 3_000_000   # QCEW wages are already whole dollars
    assert charlotte["cre_nonres_construction_establishments_count"] == 4  # industry code matched after stripping spaces
    assert charlotte["cre_real_estate_qcew_fallback_counties_count"] == 1
    assert charlotte["cre_nonres_construction_qcew_fallback_counties_count"] == 1
    assert charlotte["cre_real_estate_counties_reported_count"] == 0   # that column still counts CBP rows only


def test_cbp_wins_when_both_sources_have_a_value(project, crosswalk_csv):
    cbp = write_cbp_zip(project, 2023, [
        total("37119"), row("37119", REAL_ESTATE, est=10, emp=50, ap=2000),
    ])
    qcew = write_qcew_zip(project, 2023, {"37119": [qcew_row("37119", "531", 99, 999, 9_999_999)]})
    ingest_cre.transform([cbp, qcew], [2023])
    charlotte = metro_row(project, 2023, "16740")
    assert charlotte["cre_real_estate_establishments_count"] == 10
    assert charlotte["cre_real_estate_employment_count"] == 50
    assert charlotte["cre_real_estate_payroll_usd"] == 2_000_000
    assert charlotte["cre_real_estate_qcew_fallback_counties_count"] == 0


def test_fill_is_measure_by_measure(project, crosswalk_csv):
    cbp = write_cbp_zip(project, 2016, [
        total("37119"), withheld("37119", REAL_ESTATE, est=10),  # EST published, EMP and AP withheld
    ], old_format=True)
    qcew = write_qcew_zip(project, 2016, {"37119": [qcew_row("37119", "531", 99, 70, 4_000_000)]})
    ingest_cre.transform([cbp, qcew], [2016])
    charlotte = metro_row(project, 2016, "16740")
    assert charlotte["cre_real_estate_establishments_count"] == 10      # CBP's, not QCEW's 99
    assert charlotte["cre_real_estate_employment_count"] == 70          # filled from QCEW
    assert charlotte["cre_real_estate_payroll_usd"] == 4_000_000
    assert charlotte["cre_real_estate_qcew_fallback_counties_count"] == 0  # establishments came from CBP


def test_qcew_suppressed_row_keeps_establishments_but_not_zero_employment_or_wages(project, crosswalk_csv):
    qcew = write_qcew_zip(project, 2024, {
        "37119": [qcew_row("37119", "531", 7, 0, 0, disclosure="N")],
    })
    ingest_cre.transform([qcew], [2024])
    charlotte = metro_row(project, 2024, "16740")
    assert charlotte["cre_real_estate_establishments_count"] == 7
    assert pd.isna(charlotte["cre_real_estate_employment_count"])
    assert pd.isna(charlotte["cre_real_estate_payroll_usd"])
    assert charlotte["cre_real_estate_qcew_fallback_counties_count"] == 1


def test_county_year_with_neither_source_stays_missing(project, crosswalk_csv):
    cbp = write_cbp_zip(project, 2023, [total("01073")])  # Birmingham exists but has no industry rows
    qcew = write_qcew_zip(project, 2023, {"37119": [qcew_row("37119", "531", 5, 20, 900)]})
    ingest_cre.transform([cbp, qcew], [2023])
    birmingham = metro_row(project, 2023, "13820")
    for industry in ("real_estate", "nonres_construction"):
        for measure in ("establishments_count", "employment_count", "payroll_usd"):
            assert pd.isna(birmingham[f"cre_{industry}_{measure}"])
        assert birmingham[f"cre_{industry}_qcew_fallback_counties_count"] == 0


def test_local_government_qcew_rows_are_ignored(project, crosswalk_csv):
    qcew = write_qcew_zip(project, 2024, {
        "37119": [qcew_row("37119", "531", 50, 500, 5_000_000, own_code="3")],  # local government only
        "45091": [qcew_row("45091", "531", 6, 30, 800_000, own_code="5"),
                  qcew_row("45091", "531", 40, 400, 4_000_000, own_code="3")],
    })
    ingest_cre.transform([qcew], [2024])
    charlotte = metro_row(project, 2024, "16740")
    assert charlotte["cre_real_estate_establishments_count"] == 6    # York's private row only
    assert charlotte["cre_real_estate_employment_count"] == 30
    assert charlotte["cre_real_estate_qcew_fallback_counties_count"] == 1


def test_2024_is_built_from_qcew_alone_and_needs_its_file(project, crosswalk_csv, capsys):
    write_cbp_zip(project, 2023, [total("37119"), row("37119", REAL_ESTATE, est=10, emp=50, ap=2000)])
    with pytest.raises(FileNotFoundError, match="QCEW"):
        ingest_cre.download([2023, 2024])
    write_qcew_zip(project, 2023, {"37119": [qcew_row("37119", "531", 9, 40, 1000)]})
    write_qcew_zip(project, 2024, {"37119": [qcew_row("37119", "531", 12, 60, 3_000_000)]})

    paths = ingest_cre.download([2023, 2024])
    assert [path.name for path in paths] == ["cbp23co.zip", "2023_annual_by_area.zip", "2024_annual_by_area.zip"]
    assert "values come from QCEW only" in capsys.readouterr().out

    ingest_cre.run(years=[2023, 2024])  # the whole module, not just download()
    out = pd.read_parquet(project["INTERIM"] / "msa_year" / "cre.parquet")
    assert sorted(out["year"].unique().tolist()) == [2023, 2024]
