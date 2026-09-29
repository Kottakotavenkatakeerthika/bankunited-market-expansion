import pandas as pd

from src.crosswalk import counties_to_cbsa, load_crosswalk, parse_delineation, to_parent_cbsa


def test_parse_delineation_pads_codes_and_drops_footnotes(delineation_xlsx):
    xwalk = parse_delineation(delineation_xlsx)
    assert len(xwalk) == 5
    jefferson = xwalk.loc[xwalk["county_name"] == "Jefferson County"].iloc[0]
    assert (jefferson["county_fips"], jefferson["cbsa_code"]) == ("01073", "13820")
    assert xwalk.loc[xwalk["county_fips"] == "45091", "cbsa_code"].item() == "16740"  # York County, SC


def test_metro_only_and_division_mapping(crosswalk_csv):
    assert "37999" not in load_crosswalk(metro_only=True)["county_fips"].tolist()
    assert "37999" in load_crosswalk(metro_only=False)["county_fips"].tolist()
    parents = to_parent_cbsa(pd.Series(["33124", "16740", None]))
    assert parents.iloc[:2].tolist() == ["33100", "16740"] and pd.isna(parents.iloc[2])


def test_counties_to_cbsa_sums_and_keeps_missing_as_missing(crosswalk_csv):
    counties = pd.DataFrame({
        "county_fips": ["37119", "45091", "1073", "37999", "37998", "37119", "45091"],
        "year": [2022, 2022, 2022, 2022, 2022, 2023, 2023],
        "cbp_establishments_count": [10, 5, 7, 100, 50, None, None],
    })
    out = counties_to_cbsa(counties, ["cbp_establishments_count"])
    values = out.set_index(["cbsa_code", "year"])["cbp_establishments_count"]
    assert values[("16740", 2022)] == 15      # Mecklenburg + York
    assert values[("13820", 2022)] == 7       # "1073" padded to 01073
    assert pd.isna(values[("16740", 2023)])   # all-missing stays missing, not 0
    assert "99990" not in out["cbsa_code"].tolist()  # micropolitan left out
