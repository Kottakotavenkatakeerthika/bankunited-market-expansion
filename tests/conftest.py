import pandas as pd
import pytest
from openpyxl import Workbook

from src import config


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Point every path in config at a throwaway data/ folder with a two-metro universe."""
    data = tmp_path / "data"
    paths = {
        "DATA": data,
        "RAW": data / "raw",
        "INTERIM": data / "interim",
        "PROCESSED": data / "processed",
        "REFERENCE": data / "reference",
        "MANIFEST": data / "manifest.csv",
        "COUNTY_CBSA_XWALK": data / "reference" / "county_cbsa_xwalk.csv",
        "MSA_UNIVERSE": data / "reference" / "msa_universe.csv",
        "FRED_SERIES": data / "reference" / "fred_series.csv",
        "SPOT_CHECKS": data / "reference" / "spot_checks.csv",
    }
    for name, value in paths.items():
        monkeypatch.setattr(config, name, value)
    monkeypatch.setattr(config, "YEARS", [2022, 2023])
    for name in ("RAW", "INTERIM", "PROCESSED", "REFERENCE"):
        paths[name].mkdir(parents=True)
    pd.DataFrame({
        "cbsa_code": ["16740", "13820"],
        "cbsa_title": ["Charlotte-Concord-Gastonia, NC-SC", "Birmingham, AL"],
        "is_pilot": [1, 0],
        "notes": ["pilot", ""],
    }).to_csv(paths["MSA_UNIVERSE"], index=False)
    return paths


@pytest.fixture
def delineation_xlsx(tmp_path):
    """A small synthetic file laid out like Census List 1: title rows, header, counties, footnotes."""
    book = Workbook()
    sheet = book.active
    sheet.append(["List 1. Core Based Statistical Areas (CBSAs), Metropolitan Divisions, "
                  "and Combined Statistical Areas (CSAs), July 2023"])
    sheet.append([])
    sheet.append(["CBSA Code", "Metropolitan Division Code", "CSA Code", "CBSA Title",
                  "Metropolitan/Micropolitan Statistical Area", "Metropolitan Division Title",
                  "CSA Title", "County/County Equivalent", "State Name", "FIPS State Code",
                  "FIPS County Code", "Central/Outlying County"])
    rows = [
        ["16740", None, "172", "Charlotte-Concord-Gastonia, NC-SC", "Metropolitan Statistical Area",
         None, "Test CSA", "Mecklenburg County", "North Carolina", "37", "119", "Central"],
        ["16740", None, "172", "Charlotte-Concord-Gastonia, NC-SC", "Metropolitan Statistical Area",
         None, "Test CSA", "York County", "South Carolina", "45", "091", "Central"],
        # Stored as numbers, the way Excel sometimes keeps codes: leading zeros lost
        [13820, None, 142, "Birmingham, AL", "Metropolitan Statistical Area",
         None, "Test CSA 2", "Jefferson County", "Alabama", 1, 73, "Central"],
        ["33100", "33124", "370", "Miami-Fort Lauderdale-West Palm Beach, FL", "Metropolitan Statistical Area",
         "Miami-Miami Beach-Kendall, FL", "Test CSA 3", "Miami-Dade County", "Florida", "12", "086", "Central"],
        ["99990", None, None, "Testville, NC", "Micropolitan Statistical Area",
         None, None, "Test County", "North Carolina", "37", "999", "Central"],
    ]
    for row in rows:
        sheet.append(row)
    sheet.append([])
    sheet.append(["Note: synthetic test file."])
    sheet.append(["Source: File prepared for tests, laid out like the Census Bureau's List 1."])
    path = tmp_path / "list1_test.xlsx"
    book.save(path)
    return path


@pytest.fixture
def crosswalk_csv(project, delineation_xlsx):
    from src.crosswalk import parse_delineation

    parse_delineation(delineation_xlsx).to_csv(project["COUNTY_CBSA_XWALK"], index=False)
    return project["COUNTY_CBSA_XWALK"]
