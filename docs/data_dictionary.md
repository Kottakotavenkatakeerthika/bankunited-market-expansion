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
