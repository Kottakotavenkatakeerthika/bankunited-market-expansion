import json
import zipfile

import pandas as pd
import pytest
from openpyxl import Workbook

from src import config, ingest_bea_bls


# --------------------------------------------------------------- BEA
def write_bea_json(project, table_key, rows):
    """A fake BEA Regional API response. rows: (GeoFips, TimePeriod, DataValue) triples."""
    folder = project["RAW"] / "bea"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{table_key}.json"
    data = [{"GeoFips": fips, "GeoName": "Test", "TimePeriod": year, "DataValue": value} for fips, year, value in rows]
    path.write_text(json.dumps({"BEAAPI": {"Results": {"Data": data}}}), encoding="utf-8")
    return path


def bea_result(project):
    out = pd.read_parquet(project["INTERIM"] / "msa_year" / "bea.parquet")
    return out.set_index(["cbsa_code", "year"])


def test_bea_values_are_converted_from_thousands_and_summed_to_the_metro(project, crosswalk_csv):
    income = write_bea_json(project, "cainc1", [("37119", "2023", "1,234,567"), ("45091", "2023", "100")])
    gdp = write_bea_json(project, "cagdp2", [("37119", "2023", "2,000"), ("45091", "2023", "500")])
    ingest_bea_bls._transform_bea([income, gdp], [2023])
    row = bea_result(project).loc[("16740", 2023)]
    assert row["bea_personal_income_usd"] == (1_234_567 + 100) * 1000     # $1,000s to whole dollars
    assert row["bea_gdp_usd"] == (2_000 + 500) * 1000


def test_bea_missing_markers_and_state_rows_do_not_enter_the_metro_total(project, crosswalk_csv):
    income = write_bea_json(project, "cainc1", [
        ("37119", "2023", "1,000"), ("45091", "2023", "(NA)"), ("37000", "2023", "9,999,999")])  # state row
    gdp = write_bea_json(project, "cagdp2", [("37119", "2023", "10"), ("45091", "2023", "(D)")])
    ingest_bea_bls._transform_bea([income, gdp], [2023])
    row = bea_result(project).loc[("16740", 2023)]
    assert row["bea_personal_income_usd"] == 1_000_000      # York's "(NA)" adds nothing; the state value is not included
    assert row["bea_gdp_usd"] == 10_000


def test_bea_download_asks_for_the_current_dollar_gdp_table_and_personal_income(project, monkeypatch):
    calls = []

    def fake_fetch(url, source, filename=None, *, params=None, force=False, notes=""):
        calls.append({"filename": filename, "params": params})
        return project["RAW"] / source / filename

    monkeypatch.setattr(ingest_bea_bls, "fetch", fake_fetch)
    monkeypatch.setattr(config, "BEA_API_KEY", "not-a-real-key")
    ingest_bea_bls._download_bea(force=False)
    by_file = {call["filename"]: call["params"] for call in calls}
    assert set(by_file) == {"cainc1.json", "cagdp2.json"}
    assert by_file["cainc1.json"]["TableName"] == "CAINC1" and by_file["cainc1.json"]["LineCode"] == "1"
    assert by_file["cagdp2.json"]["TableName"] == "CAGDP2" and by_file["cagdp2.json"]["LineCode"] == "1"  # current dollars, not CAGDP1/CAGDP9
    assert all(p["GeoFips"] == "COUNTY" and p["Year"] == "ALL" for p in by_file.values())


def test_documents_that_a_bea_combined_virginia_area_is_dropped_silently(project, crosswalk_csv):
    income = write_bea_json(project, "cainc1", [("37119", "2023", "1,000"), ("51901", "2023", "5,000,000")])
    gdp = write_bea_json(project, "cagdp2", [("37119", "2023", "10"), ("51901", "2023", "9,000,000")])
    ingest_bea_bls._transform_bea([income, gdp], [2023])
    out = bea_result(project)
    assert list(out.index.get_level_values("cbsa_code").unique()) == ["16740"]
    assert out.loc[("16740", 2023), "bea_personal_income_usd"] == 1_000_000   # no row, no error for 51901


# --------------------------------------------------------------- BLS LAUS
LAUS_HEADER = ["LAUS Code", "State FIPS Code", "County FIPS Code", "County Name/State Abbreviation", "Year",
               "Labor Force", "Employed", "Unemployed", "Unemployment Rate (%)"]


def write_laus_xlsx(project, year, rows):
    """A fake laucnty<YY>.xlsx: title rows, a header row, county rows, then a footnote."""
    folder = project["RAW"] / "bls"
    folder.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    sheet = book.active
    sheet.append(["Local Area Unemployment Statistics, county annual averages"])
    sheet.append([])
    sheet.append(LAUS_HEADER)
    for fips_state, fips_county, labor_force, employed, unemployed in rows:
        sheet.append([f"CN{fips_state}{fips_county}", fips_state, fips_county, "Test County", year,
                      labor_force, employed, unemployed, None])
    sheet.append(["Source: synthetic file for tests."])
    path = folder / f"laucnty{year % 100:02d}.xlsx"
    book.save(path)
    return path


def test_laus_reads_numeric_codes_commas_and_skips_the_footnote(project, crosswalk_csv):
    path = write_laus_xlsx(project, 2023, [(37, 119, "1,000", "950", "50"), (45, 91, 200, 190, 10)])  # codes stored as numbers
    county = ingest_bea_bls._read_one_laus_year(path)
    assert sorted(county["county_fips"]) == ["37119", "45091"]           # zero-padded, footnote row dropped
    assert county.set_index("county_fips").loc["37119", "bls_labor_force_count"] == 1000


def test_laus_unemployment_rate_comes_from_summed_counts_not_averaged_county_rates(project, crosswalk_csv):
    path = write_laus_xlsx(project, 2023, [(37, 119, 1000, 950, 50), (45, 91, 100, 80, 20)])  # 5% and 20%
    metro = ingest_bea_bls._transform_laus([path]).set_index(["cbsa_code", "year"]).loc[("16740", 2023)]
    assert metro["bls_labor_force_count"] == 1100
    assert metro["bls_unemployment_rate_pct"] == pytest.approx(70 / 1100 * 100)    # 6.36, not the 12.5 average


def test_documents_that_a_metro_with_zero_labor_force_gets_a_missing_rate_and_no_laus_file_gives_a_bare_error(project, crosswalk_csv):
    path = write_laus_xlsx(project, 2023, [(37, 119, 0, 0, 0)])
    metro = ingest_bea_bls._transform_laus([path]).set_index(["cbsa_code", "year"]).loc[("16740", 2023)]
    assert pd.isna(metro["bls_unemployment_rate_pct"])          # 0 / 0
    with pytest.raises(ValueError):                              # pd.concat of nothing: not a clear message
        ingest_bea_bls._transform_laus([])


# --------------------------------------------------------------- BLS QCEW
QCEW_COLUMNS = ["area_fips", "own_code", "industry_code", "agglvl_code", "size_code", "year", "qtr",
                "disclosure_code", "area_title", "annual_avg_estabs_count", "annual_avg_emplvl", "total_annual_wages"]


def qcew_row(area, own, industry, estabs, emp, wages, disclosure=""):
    return {"area_fips": area, "own_code": own, "industry_code": industry, "agglvl_code": 70, "size_code": 0,
            "year": 2024, "qtr": "A", "disclosure_code": disclosure, "area_title": "Test",
            "annual_avg_estabs_count": estabs, "annual_avg_emplvl": emp, "total_annual_wages": wages}


def write_qcew_zip(project, year, files):
    """A fake <year>_annual_by_area.zip. files: {"<area code> <title>": [rows]}, one inner CSV per area."""
    folder = project["RAW"] / "bls"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{year}_annual_by_area.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for label, rows in files.items():
            frame = pd.DataFrame(rows, columns=QCEW_COLUMNS)
            archive.writestr(f"{year}.annual.by_area/{year}.annual {label}.csv", frame.to_csv(index=False))
    return path


def qcew_result(paths):
    return ingest_bea_bls._transform_qcew(paths).set_index(["cbsa_code", "year"])


def test_qcew_reads_only_county_files_and_the_all_ownership_all_industry_row(project, crosswalk_csv):
    path = write_qcew_zip(project, 2024, {
        "37119 Mecklenburg County, North Carolina": [
            qcew_row("37119", "0", "10", 100, 1000, 50_000),       # the row we want
            qcew_row("37119", "5", "10", 90, 900, 40_000),         # private only: not wanted
            qcew_row("37119", "0", "1011", 10, 99, 99),            # a sector, not the all-industry total
        ],
        "45091 York County, South Carolina": [qcew_row("45091", "0", "10", 20, 200, 8_000)],
        "37000 North Carolina -- Statewide": [qcew_row("37000", "0", "10", 9999, 99_999, 9_999_999)],   # the state
        "C1674 Charlotte-Concord-Gastonia, NC-SC MSA": [qcew_row("C1674", "0", "10", 9999, 99_999, 9_999_999)],
        "CS172 Charlotte-Concord, NC-SC CSA": [qcew_row("CS172", "0", "10", 9999, 99_999, 9_999_999)],
    })
    row = qcew_result([path]).loc[("16740", 2024)]
    assert row["bls_qcew_employment_count"] == 1200                # 1000 + 200: no state, MSA or CSA values
    assert row["bls_qcew_total_wages_usd"] == 58_000


def test_qcew_suppressed_row_has_missing_employment_and_wages_not_zero(project, crosswalk_csv):
    path = write_qcew_zip(project, 2024, {
        "37119 Mecklenburg County, North Carolina": [qcew_row("37119", "0", "10", 100, 1000, 50_000)],
        "01073 Jefferson County, Alabama": [qcew_row("01073", "0", "10", 3, 0, 0, disclosure="N")],  # suppressed
    })
    county = ingest_bea_bls._read_one_qcew_year(path, 2024).set_index("county_fips")
    assert pd.isna(county.loc["01073", "bls_qcew_employment_count"])
    assert pd.isna(county.loc["01073", "bls_qcew_total_wages_usd"])
    assert county.loc["37119", "bls_qcew_employment_count"] == 1000
    metro = qcew_result([path])
    assert pd.isna(metro.loc[("13820", 2024), "bls_qcew_employment_count"])   # a metro with only that county: missing, not 0
    assert metro.loc[("16740", 2024), "bls_qcew_employment_count"] == 1000


def test_qcew_metro_sums_only_the_counties_present(project, crosswalk_csv):
    path = write_qcew_zip(project, 2024, {
        "37119 Mecklenburg County, North Carolina": [qcew_row("37119", "0", "10", 100, 1000, 50_000)],
        # York has no file, and Jefferson's file has no all-industry row
        "01073 Jefferson County, Alabama": [qcew_row("01073", "5", "10", 3, 30, 300)],
    })
    out = qcew_result([path])
    assert out.loc[("16740", 2024), "bls_qcew_employment_count"] == 1000   # Mecklenburg alone, not Mecklenburg + 0
    assert ("13820", 2024) not in out.index                                  # nothing to add up, so no row (not a 0)
