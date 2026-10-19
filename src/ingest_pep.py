"""Census Population Estimates Program (PEP): county population and components of change.

Output:  data/interim/msa_year/pep.parquet    keys: cbsa_code, year    measures: pep_*

Starting points (verify before relying on them):
  - County files (all years in one CSV, one column per year and measure):
    https://www2.census.gov/programs-surveys/popest/datasets/2010-2020/counties/totals/co-est2020-alldata.csv
    https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/counties/totals/co-est2025-alldata.csv
  - Intercensal county file (one row per county and YEAR code), used for 2015-2019 population:
    https://www2.census.gov/programs-surveys/popest/datasets/2010-2020/intercensal/county/asrh/cc-est2020int-agesex-all.csv
    Layout: https://www2.census.gov/programs-surveys/popest/technical-documentation/file-layouts/2010-2020/intercensal/county/CC-EST2020INT-AGESEX.pdf
  - Metro file, only used to take published figures for spot checks:
    https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/metro/totals/cbsa-est2025-alldata.csv

Reading the numbers:
  - Population is the July 1 estimate. Flows (natural change and migration) are for
    the year ending June 30 of that year.
  - Population: 2015-2019 comes from the 2010-2020 intercensal county file (YEAR 7 to 11 =
    July 1 of 2015 to 2019; YEAR 12 is the April 1, 2020 Census count and is ignored);
    2020 onward comes from Vintage 2025. Both are on the 2020 Census base, so population is
    continuous across 2019 to 2020. pep_population_source says which file a row used.
  - Flows: 2015-2019 come from Vintage 2020 (2010 Census base); 2021 onward from Vintage
    2025 (2020 Census base), so the flows break between 2019 and 2020 and do not sum
    exactly to the change in the intercensal population.
  - The Vintage 2025 file's 2020 flows cover only April to June 2020, so 2020 keeps
    its population but its four flow columns stay blank.
  - The 2015-2019 files (Vintage 2020 and the intercensal file, both on 2020 boundaries)
    report Connecticut under the old county codes (09001-09015), which the crosswalk does
    not map, so Connecticut metros are missing for 2015-2019.
  - pep_vintage_year is the vintage of the flow columns: 2020 for 2015-2019, 2025 from 2020 on.
  - The _net columns can be negative. Missing values are never filled with 0.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src import config
from src.crosswalk import counties_to_cbsa, load_crosswalk
from src.utils import fetch, normalize_code, write_interim

SOURCE = "pep"

BASE_URL = "https://www2.census.gov/programs-surveys/popest/datasets"
OLD_FILE = "co-est2020-alldata.csv"   # Vintage 2020: 2010-2020
NEW_FILE = "co-est2025-alldata.csv"   # Vintage 2025: 2020-2025
INTERCENSAL_FILE = "cc-est2020int-agesex-all.csv"  # intercensal 2010-2020: population for 2015-2019
METRO_FILE = "cbsa-est2025-alldata.csv"
URLS = {
    OLD_FILE: f"{BASE_URL}/2010-2020/counties/totals/{OLD_FILE}",
    NEW_FILE: f"{BASE_URL}/2020-2025/counties/totals/{NEW_FILE}",
    INTERCENSAL_FILE: f"{BASE_URL}/2010-2020/intercensal/county/asrh/{INTERCENSAL_FILE}",
    METRO_FILE: f"{BASE_URL}/2020-2025/metro/totals/{METRO_FILE}",
}
NOTES = {
    OLD_FILE: "PEP county totals and components, vintage 2020 (2010-2020)",
    NEW_FILE: "PEP county totals and components, vintage 2025 (2020-2025)",
    INTERCENSAL_FILE: "PEP intercensal county estimates by age and sex, 2010-2020; used for 2015-2019 total population",
    METRO_FILE: "PEP metro (CBSA) file, vintage 2025, used for spot checks",
}

# Which file each year is read from, and what that file calls natural change.
OLD_YEARS = range(2015, 2020)
NEW_YEARS = range(2020, 2025)
VINTAGE_YEAR = {OLD_FILE: 2020, NEW_FILE: 2025}  # the vintage of each file's flows
POPULATION_SOURCE = {OLD_FILE: "Intercensal 2010-2020", NEW_FILE: "Vintage 2025"}  # where population comes from
INTERCENSAL_YEAR_CODE = {year: year - 2008 for year in OLD_YEARS}  # YEAR 7 = July 1, 2015 ... 11 = July 1, 2019
LATEST_YEAR = 2024
NATURAL_PREFIX = {OLD_FILE: "NATURALINC", NEW_FILE: "NATURALCHG"}
# 2020 in the new file: population only (its flows cover April-June 2020).
NO_FLOWS_YEARS = {2020}

VALUE_COLUMNS = [
    "pep_population_count",
    "pep_natural_change_net",
    "pep_domestic_migration_net",
    "pep_international_migration_net",
    "pep_migration_net",
    "pep_counties_reported_count",
]


def download(years: list[int], force: bool = False) -> list[Path]:
    """Pull the county files, the intercensal file and the metro spot-check file into RAW/pep/ with fetch()."""
    return [fetch(URLS[name], SOURCE, filename=name, force=force, notes=NOTES[name])
            for name in (OLD_FILE, NEW_FILE, INTERCENSAL_FILE, METRO_FILE)]


def _read_county_file(path: Path, years: list[int]) -> pd.DataFrame:
    """One row per county and year for the given years, county rows only (no state rows)."""
    raw = pd.read_csv(path, encoding="latin-1", dtype={"STATE": str, "COUNTY": str})
    raw.columns = [c.strip().upper() for c in raw.columns]
    natural = NATURAL_PREFIX[path.name]
    required = ["STATE", "COUNTY"]
    for year in years:
        required.append(f"POPESTIMATE{year}")
        if year not in NO_FLOWS_YEARS:
            required += [f"{prefix}{year}" for prefix in (natural, "DOMESTICMIG", "INTERNATIONALMIG", "NETMIG")]
    missing = [c for c in required if c not in raw.columns]
    if missing:
        raise ValueError(f"{path.name}: missing expected columns {missing}")

    state = normalize_code(raw["STATE"], 2)
    county = normalize_code(raw["COUNTY"], 3)
    counties = raw.loc[county != "000"]
    county_fips = (state + county).loc[counties.index]

    def number(column):
        return pd.to_numeric(counties[column], errors="coerce")

    frames = []
    for year in years:
        has_flows = year not in NO_FLOWS_YEARS
        frames.append(pd.DataFrame({
            "county_fips": county_fips,
            "year": year,
            "pep_population_count": number(f"POPESTIMATE{year}"),
            "pep_natural_change_net": number(f"{natural}{year}") if has_flows else float("nan"),
            "pep_domestic_migration_net": number(f"DOMESTICMIG{year}") if has_flows else float("nan"),
            "pep_international_migration_net": number(f"INTERNATIONALMIG{year}") if has_flows else float("nan"),
            "pep_migration_net": number(f"NETMIG{year}") if has_flows else float("nan"),
        }))
    return pd.concat(frames, ignore_index=True)


def _read_intercensal(path: Path, years: list[int]) -> pd.DataFrame:
    """July 1 population for the given years from the intercensal file (YEAR 7 to 11); YEAR 12 is never used."""
    raw = pd.read_csv(path, encoding="latin-1", dtype={"STATE": str, "COUNTY": str},
                      usecols=lambda c: c.strip().upper() in {"STATE", "COUNTY", "YEAR", "POPESTIMATE"})
    raw.columns = [c.strip().upper() for c in raw.columns]
    missing = [c for c in ("STATE", "COUNTY", "YEAR", "POPESTIMATE") if c not in raw.columns]
    if missing:
        raise ValueError(f"{path.name}: missing expected columns {missing}")
    code_to_year = {INTERCENSAL_YEAR_CODE[year]: year for year in years}
    rows = raw.loc[pd.to_numeric(raw["YEAR"], errors="coerce").isin(code_to_year)]
    county = normalize_code(rows["COUNTY"], 3)
    rows = rows.loc[county != "000"]
    return pd.DataFrame({
        "county_fips": normalize_code(rows["STATE"], 2) + normalize_code(rows["COUNTY"], 3),
        "year": pd.to_numeric(rows["YEAR"]).map(code_to_year).astype("int64"),
        "pep_population_count": pd.to_numeric(rows["POPESTIMATE"], errors="coerce"),
    }).reset_index(drop=True)


def _report_gaps(county_level: pd.DataFrame, years: list[int]) -> None:
    """Print what the county-to-metro join leaves out, so gaps are visible and not silent."""
    xwalk = load_crosswalk(metro_only=True)["county_fips"]
    mapped = county_level["county_fips"].isin(xwalk)
    is_ct = county_level["county_fips"].str.startswith("09")
    for year in years:
        in_year = county_level["year"] == year
        dropped = int((in_year & ~mapped).sum())
        dropped_ct = int((in_year & ~mapped & is_ct).sum())
        print(f"[pep] {year}: {dropped} county rows not in the crosswalk (not in a metro, "
              f"or old Connecticut codes: {dropped_ct})")
    present = set(zip(county_level.loc[mapped, "county_fips"], county_level.loc[mapped, "year"]))
    absent = sum(1 for fips in xwalk for year in years if (fips, year) not in present)
    no_population = int((mapped & county_level["pep_population_count"].isna()).sum())
    print(f"[pep] county-years missing: {absent} crosswalk counties absent from the files, "
          f"{no_population} present without a population")


def transform(paths: list[Path], years: list[int]) -> list[Path]:
    """County rows -> metro-year with counties_to_cbsa(); save with write_interim(df, SOURCE, "msa_year")."""
    by_name = {Path(p).name: Path(p) for p in paths}
    missing = [name for name in (OLD_FILE, NEW_FILE) if name not in by_name]
    if missing:
        raise ValueError(f"pep: no raw files to transform: {missing}; did download() run first?")
    if any(y in OLD_YEARS for y in years) and INTERCENSAL_FILE not in by_name:
        raise ValueError(f"pep: {INTERCENSAL_FILE} is needed for 2015-2019 population; did download() run first?")

    wanted = [y for y in years if y <= LATEST_YEAR]
    for year in sorted(set(years) - set(wanted)):
        print(f"[pep] skipping {year}: this build stops at {LATEST_YEAR}")
    parts = []
    vintage_by_year = {}
    population_source_by_year = {}
    for name, span in ((OLD_FILE, OLD_YEARS), (NEW_FILE, NEW_YEARS)):
        file_years = [y for y in wanted if y in span]
        if file_years:
            frame = _read_county_file(by_name[name], file_years)
            if name == OLD_FILE:  # flows stay on Vintage 2020; population comes from the intercensal file
                intercensal = _read_intercensal(by_name[INTERCENSAL_FILE], file_years)
                frame = frame.drop(columns="pep_population_count").merge(
                    intercensal, on=["county_fips", "year"], how="outer")
            parts.append(frame)
            vintage_by_year.update({year: VINTAGE_YEAR[name] for year in file_years})
            population_source_by_year.update({year: POPULATION_SOURCE[name] for year in file_years})
    if not parts:
        raise ValueError(f"pep: none of the years {years} are covered by the PEP files")
    county_level = pd.concat(parts, ignore_index=True)
    county_level["pep_counties_reported_count"] = county_level["pep_population_count"].notna().astype(int)

    _report_gaps(county_level, sorted(county_level["year"].unique()))
    metro_level = counties_to_cbsa(
        county_level,
        value_cols=VALUE_COLUMNS,
        county_col="county_fips",
        by=("year",),
        metro_only=True,
    )
    # Set from the file each year came from, not summed across counties.
    metro_level["pep_vintage_year"] = metro_level["year"].map(vintage_by_year).astype("int64")
    metro_level["pep_population_source"] = metro_level["year"].map(population_source_by_year).astype("string")
    return [write_interim(metro_level, SOURCE, "msa_year")]


def run(years: list[int] | None = None, force: bool = False) -> list[Path]:
    years = list(years or config.YEARS)
    return transform(download(years, force=force), years)


if __name__ == "__main__":
    run()
