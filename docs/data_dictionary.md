# Data Dictionary

Every column in `data/processed/` gets a row here, in the same pull request that adds it.

## Conventions

- **Keys.** `cbsa_code` and `county_fips` are 5-character strings with leading zeros kept (`01073`, not `1073`). `year` is the year a measure describes, not the year it was released. `quarter_end` is the last day of the quarter. `rssd_id` is the FFIEC RSSD ID, stored as a string.
- **Geography.** Every year uses one OMB delineation vintage (`DELINEATION_VINTAGE` in `src/config.py`). Counties map to metros through `data/reference/county_cbsa_xwalk.csv`.
- **Column names.** `<source>_<measure>` in snake_case, e.g. `cbp_establishments_count`, `sod_deposits_usd`.
- **Units go in the suffix**, and the automatic checks rely on them:
  - `_count`: a count, must be 0 or more
  - `_usd`: whole dollars (convert from thousands at ingest), must be 0 or more
  - `_pct`: a percentage from 0 to 100
  - `_share`: a fraction from 0 to 1
- **Missing means missing.** Leave a value empty when the source doesn't report it. Never fill with 0.
- **Released** is when the source published the value. The Charlotte back-test can only use values released before the decision date it simulates.

## msa_year: one row per metro per year

| Column | Type | Unit | Definition | Source and field | Released | Transformation |
|---|---|---|---|---|---|---|
| `cbsa_code` | string(5) | | Metro (CBSA) code | OMB delineation, List 1 | | |
| `cbsa_title` | string | | Metro name | `data/reference/msa_universe.csv` | | |
| `year` | int | | Year the measures describe | | | |
| `cbp_establishments_count` | int | count | Number of business establishments, all industries, in the county/metro | Census County Business Patterns, county file field `EST` | | Summed from county to metro via crosswalk |
| `cbp_employment_count` | int | count | Paid employment for the pay period including March 12, all industries | Census County Business Patterns, county file field `EMP` | | Summed from county to metro via crosswalk |
| `cbp_first_quarter_payroll_usd` | numeric | usd | First-quarter payroll, all industries | Census County Business Patterns, county file field `QP1` (reported in $1,000s) | | Converted from thousands to whole dollars (×1,000), then summed county to metro via crosswalk |
| `cbp_annual_payroll_usd` | numeric | usd | Annual payroll, all industries | Census County Business Patterns, county file field `AP` (reported in $1,000s) | | Converted from thousands to whole dollars (×1,000), then summed county to metro via crosswalk |
| `cre_real_estate_establishments_count` | numeric | count | Establishments in real estate (NAICS 531) in the county/metro. Missing if no county published a row | Census County Business Patterns, county file field `EST`, NAICS `531///` | 2023 data: June 26, 2025 (latest release) | Summed county to metro via crosswalk; counties with no row are left out of the sum, never counted as 0 |
| `cre_real_estate_employment_count` | numeric | count | Paid employment in real estate (NAICS 531). Missing where withheld | Census County Business Patterns, county file field `EMP`, NAICS `531///` | 2023 data: June 26, 2025 (latest release) | 2015-2017 withheld cells (flag D or S, value 0) set to missing; from 2018 Census adds noise instead of withholding. Summed county to metro via crosswalk |
| `cre_real_estate_payroll_usd` | numeric | usd | Annual payroll in real estate (NAICS 531). Missing where withheld | Census County Business Patterns, county file field `AP` (reported in $1,000s), NAICS `531///` | 2023 data: June 26, 2025 (latest release) | Converted from thousands to whole dollars (x1,000); withheld cells set to missing; summed county to metro via crosswalk |
| `cre_real_estate_counties_reported_count` | int | count | Counties in the metro with establishments, employment and payroll all published for NAICS 531 | Derived from the Census County Business Patterns county file | | Count of reporting counties; a metro total built from fewer counties than the metro has is an undercount |
| `cre_nonres_construction_establishments_count` | numeric | count | Establishments in nonresidential building construction (NAICS 2362) in the county/metro. Missing if no county published a row | Census County Business Patterns, county file field `EST`, NAICS `2362//` | 2023 data: June 26, 2025 (latest release) | Summed county to metro via crosswalk; counties with no row are left out of the sum, never counted as 0 |
| `cre_nonres_construction_employment_count` | numeric | count | Paid employment in nonresidential building construction (NAICS 2362). Missing where withheld | Census County Business Patterns, county file field `EMP`, NAICS `2362//` | 2023 data: June 26, 2025 (latest release) | 2015-2017 withheld cells (flag D or S, value 0) set to missing; from 2018 Census adds noise instead of withholding. Summed county to metro via crosswalk |
| `cre_nonres_construction_payroll_usd` | numeric | usd | Annual payroll in nonresidential building construction (NAICS 2362). Missing where withheld | Census County Business Patterns, county file field `AP` (reported in $1,000s), NAICS `2362//` | 2023 data: June 26, 2025 (latest release) | Converted from thousands to whole dollars (x1,000); withheld cells set to missing; summed county to metro via crosswalk |
| `cre_nonres_construction_counties_reported_count` | int | count | Counties in the metro with establishments, employment and payroll all published for NAICS 2362 | Derived from the Census County Business Patterns county file | | Count of reporting counties; a metro total built from fewer counties than the metro has is an undercount (Charlotte 2023: 10 of 11, Lancaster County has no row) |
| `bea_personal_income_usd` | numeric | usd | Total personal income of residents, current dollars (wages, proprietors' income, dividends, interest, rent, and transfer receipts) | BEA Regional API, table CAINC1 line 1 "Personal income", county field `DataValue` (reported in $1,000s) | | Converted from thousands to whole dollars (×1,000), then summed county to metro via crosswalk |
| `bea_gdp_usd` | numeric | usd | Gross domestic product, all industries, current dollars (not inflation-adjusted) | BEA Regional API, table CAGDP2 line 1 "Gross Domestic Product (GDP): All industry total", county field `DataValue` (reported in $1,000s) | | Converted from thousands to whole dollars (×1,000), then summed county to metro via crosswalk |
| `bls_labor_force_count` | int | count | Civilian labor force (employed + unemployed), annual average, by place of residence | BLS LAUS county annual averages file `laucntyYY.xlsx`, column `Labor Force` | | Summed county to metro via crosswalk |
| `bls_employed_count` | int | count | Employed residents, annual average | BLS LAUS county annual averages file `laucntyYY.xlsx`, column `Employed` | | Summed county to metro via crosswalk |
| `bls_unemployed_count` | int | count | Unemployed residents, annual average | BLS LAUS county annual averages file `laucntyYY.xlsx`, column `Unemployed` | | Summed county to metro via crosswalk |
| `bls_unemployment_rate_pct` | numeric | pct | Unemployment rate: unemployed as a percent of the labor force | Derived from BLS LAUS county columns `Unemployed` and `Labor Force` | | Computed after aggregation as `bls_unemployed_count / bls_labor_force_count × 100`; county rates are never averaged |
| `bls_qcew_employment_count` | int | count | Annual average employment covered by unemployment insurance, all ownerships, all industries, by place of work | BLS QCEW annual-by-area bulk file `YYYY_annual_by_area.zip`, county CSVs, field `annual_avg_emplvl` where `own_code` = 0 and `industry_code` = 10 | | Summed county to metro via crosswalk |
| `bls_qcew_total_wages_usd` | numeric | usd | Total wages paid in covered employment during the year, all ownerships, all industries | BLS QCEW annual-by-area bulk file `YYYY_annual_by_area.zip`, county CSVs, field `total_annual_wages` where `own_code` = 0 and `industry_code` = 10 (reported in whole dollars) | | Summed county to metro via crosswalk (no unit conversion needed) |
| `fred_unemployment_rate_pct` | numeric | pct | Metro unemployment rate, monthly and not seasonally adjusted, averaged over the calendar year. Only filled for metros that have a row in `data/reference/fred_series.csv` (currently 16740 only) | FRED API `series/observations`, field `value`, for the series listed in `data/reference/fred_series.csv` (currently CHAR737URN, originally from BLS LAUS) | | Annual mean of monthly observations (`annualize` = `mean` in `fred_series.csv`); FRED's `.` missing-value placeholder dropped; Metropolitan Division codes mapped to parent CBSA |
| `cra_small_business_loan_count` | int | count | Number of small business loan originations reported by CRA filers (loans under $1M), all lenders combined | FFIEC CRA aggregate flat file `<YY>exp_aggr.zip`, Table A1-1 (Small Business Loans by County - Originations), County Total rows (Report Level 200), loan-count fields for the three size buckets: under $100k, $100k-$250k, $250k-$1M | | Summed across the three loan-size buckets, then summed county to metro via crosswalk |
| `cra_small_business_loan_amount_usd` | numeric | usd | Dollar amount of small business loan originations reported by CRA filers (loans under $1M), all lenders combined | FFIEC CRA aggregate flat file `<YY>exp_aggr.zip`, Table A1-1, County Total rows (Report Level 200), loan-amount fields for the three size buckets (reported in $1,000s) | | Summed across the three loan-size buckets, converted from thousands to whole dollars (×1,000), then summed county to metro via crosswalk |

**Known limitation: Connecticut before 2022.** In 2022 Connecticut replaced its 8 counties with 9 planning regions as county-equivalents, with new FIPS codes (09001-09015 became 09110-09190). The crosswalk maps only the new planning-region codes, so any source that reports Connecticut under the old county codes is silently dropped in the county-to-metro join; no error is raised. Confirmed in CRA: the 2015-2023 files use the old codes and the 2024 file uses the new ones, so all 5 Connecticut metros (14860, 25540, 35300, 35980, 47930) are missing for 2015-2023 and present for 2024. Not yet checked whether this affects CBP, BEA, or BLS for the same years. Doesn't affect Charlotte (16740), the only back-test metro in `data/reference/msa_universe.csv`. Owner: Austin (crosswalk). Flagged 2026-10-01.

## bank_quarter: one row per bank per quarter

| Column | Type | Unit | Definition | Source and field | Released | Transformation |
|---|---|---|---|---|---|---|
| `rssd_id` | string | | FFIEC RSSD ID | Call Report `IDRSSD` | | |
| `quarter_end` | date | | Last day of the report quarter | | | |

## bank_msa_year: one row per bank per metro per year

| Column | Type | Unit | Definition | Source and field | Released | Transformation |
|---|---|---|---|---|---|---|
| `rssd_id` | string | | FFIEC RSSD ID | SOD `RSSDID` | | |
| `cbsa_code` | string(5) | | Metro (CBSA) code | Branch county via crosswalk | | |
| `year` | int | | SOD survey year (deposits as of June 30) | | | |
