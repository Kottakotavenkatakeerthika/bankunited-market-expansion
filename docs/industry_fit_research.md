# Industry fit: research background

*Written by Jainesh for pull request 124 (industry fit exploration), kept here as the research and rationale behind
the original High / Medium / Low sector ratings. The integrated version is the industry share filter in
`src/scoring/fit.py` and `[fit.industries]` in `weights/baseline.toml` (see `src/scoring/README.md`, section 7c), which
keeps this document's calculation rules: the published CBP total as the denominator, a blank share when an
included sector is missing, and one CBP year for all metros. References below to commands, files and branches
describe the pull request as written and may not match the current repo.*

---

# Industry Fit: employment alignment by metro

Industry Fit measures how much of a metro's CBP-covered employment is in industries currently classified as High or Medium priority for BankUnited. It supports review of industry alignment alongside the separately defined population and adjacency criteria. It does not estimate loan demand, profitability, or similarity to BankUnited's observed loan portfolio.

## Files and implementation status

- Exploratory workbook (`docs/Industry_Fit_2023.xlsx` in pull request 124, not merged): 2023 snapshot, including research rationales, growth, specialization, comparisons, and coverage.
- Python module (`src/bankunited_fit.py` in pull request 124, not merged): reusable `industry_mix()` calculation and TOML priority loader.
- [Configuration](../weights/baseline.toml): `[industry_fit.priorities]`, editable independently of scoring weights.
- Read-only notebook (`notebooks/industry_fit_exploration.ipynb` in pull request 124, not merged): displays existing generated results; saved outputs are cleared.
- Tests (`tests/test_industry_mix.py` in pull request 124, not merged): year selection, release-date gating, missingness, validation, and configuration separation.

Industry Fit is generated alongside the command available in this branch:

```bash
python -m src.market_attractiveness --year 2024
```

This combines existing pillar exports and also rebuilds `outputs/industry_fit/industry_fit_report.xlsx` from parquet inputs and TOML priorities. **Industry Fit remains separate from the final score and does not change final rankings.** In this older branch, `--year` selects Industry Fit's scoring year; it does not rebuild or redate the existing four-pillar exports. The newer v0.3 `src.scoring.run` runner is not present in this checkout, so this integration does not claim to rebuild all pillar metrics.

To refresh only Industry Fit without rewriting final-score files:

```bash
python -m src.bankunited_fit --year 2024
```

Then open the read-only notebook and Run All. It reads the generated workbook's settings and worksheets, with no CSV bundle or metadata JSON. Its saved outputs remain cleared. The Excel in `docs/` is optional research background, not a live calculation input.

A clean checkout needs the source modules, processed CBP/metro parquet tables, county crosswalk, TOML priorities, and Python dependencies. Run one of the commands above before opening the report. Generated workbooks need not be committed because the generator reproduces them. The report validates source fingerprints and directs the user to regenerate after a configuration or data change.

## Calculation and interpretation

For metro `m` and selected industry-data year `y`:
 
```text
High share = employment in all High sectors / published total metro CBP employment
High+Medium share = employment in all High and Medium sectors / the same total
```

Shares are fractions between 0 and 1; display them as percentages. The module also returns Medium-only employment/share, partial observed sums, expected and observed sector counts, missing sector codes, readiness flags, and sector-to-total reconciliation.

The denominator is `msa_year.cbp_employment_count`, not the sum of available sector rows. Low and Exclude sectors do not enter either preferred-industry numerator; their covered activity remains represented in the published total. Exclude means excluded from this numerator, not a prohibited lending industry. Unknown-sector NAICS 99 is retained in the denominator.

Current settings require six sector observations for High and eleven for High+Medium. All included sectors must have employment observations; a missing row/value yields a missing share rather than zero. Partial sums are separately labeled diagnostics. Missing or nonpositive metro totals also yield missing shares. Complete sector observations do not prove complete county reporting.

Charlotte's 2023 snapshot has approximately **35.0% High** and **70.3% High+Medium** employment. The difference, approximately **35.3 percentage points**, is Medium-sector exposure, not employment growth or a new score. The report includes a descriptive employment-share rank, not a final Fit & Feasibility rank. The core industry_mix() function does not rank or apply eligibility thresholds.

## Rating sources, decisions, and rationale

The configuration preserves the existing project mapping. Its research references are the earlier industry-mapping workbook's `Step5_NAICS_Mapping`, `Step6_High_Subset`, `Step6_Notes`, and `Step7_OnePager`. That research workbook lives outside this repository in the local research workspace and is not a runtime dependency or included source artifact here.

The accompanying research note `bankunited_industry_mapping/docs/STEP5_NAICS_MAPPING.md` records a November 5, 2026 email clarification placing Finance/Insurance 52, Healthcare 62, and Utilities 22 at Medium.

| Rating | NAICS sectors | Recorded rationale / basis |
|---|---|---|
| High | 23, 31–33, 42, 48–49, 53, 54 | Existing research High subset: construction/CRE activity, manufacturing, wholesale, logistics, real estate, and professional services as commercial targets |
| Medium | 52, 62, 22 | Research note records the November 5 clarification; finance also carries a national/NDFI footprint caveat |
| Medium | 61, 44–45 | Existing mapping includes education and retail commercial exposure; public education is underrepresented in CBP |
| Low | 51, 56, 81, 72, 92 | Existing mapping treats these as lower-priority/context industries; Public Administration 92 is absent from this CBP panel |
| Low | 11, 21, 55 | Analyst classifications: outside the research High subset; mining is distinct from utilities, and holding-company employment is an indirect local-demand signal |
| Exclude | 71 | Existing mapping's default exclusion from preferred-industry numerators; classification basis requires source confirmation |
| Exclude | 99 | Analyst classification: industry is unclassified, so it is not a preferred-industry target |


Combined CBP sectors are stored as 31, 44, and 48 for ranges 31–33, 44–45, and 48–49. Ratings are not modified between the High and High+Medium inclusion scenarios. `in_high_subset` is derived from the rating rather than separately configured.

## Why employment share, and alternatives considered

Employment share is an interpretable measure of a preferred industry's local footprint. Normalizing by the metro total permits comparisons across market sizes without automatically rewarding the largest metros. It measures job composition, not the number or creditworthiness of potential borrowers; report absolute scale alongside it.

| Alternative | Benefit | Limitation / decision |
|---|---|---|
| Establishment share/count | Closer to the number of business locations | Locations are not independent borrowers; small and large establishments differ |
| Payroll share | Captures wage/economic scale | Influenced by wage levels and inflation rather than lending demand alone |
| Absolute employment | Shows market scale | Favors large metros; useful alongside shares rather than as the same signal |
| Location quotient | Shows specialization relative to a benchmark | Can be high in a small industry; benchmark coverage varies |
| Weighted High/Medium/Low score | Produces one sortable measure | Requires approved numerical weights; none are adopted here |
| QCEW employment shares | Alternative employment coverage and later years in the proposed release | Ownership, timing, suppression, and NAICS alignment require comparison; private-sector QCEW does not supply government coverage |
| Actual BankUnited portfolio similarity | Directly tests resemblance to the bank's business mix | Requires an agreed portfolio distribution and comparable local opportunity measures; the current notebook does not implement it |

## Year selection and historical availability

`industry_mix()` accepts `scoring_year` instead of hardcoding 2023. It selects the latest common CBP year at or before the scoring year with any observed employment in both input tables. Every metro uses that same year; missing metro/sector inputs are not filled from another year. This selection establishes year availability, not complete coverage.

Outputs report `scoring_year`, `industry_data_year`, and `data_year_lag`. With current inputs, scoring year 2024 uses CBP 2023. If no eligible common year exists, the function raises an error.

For historical runs, pass `as_of` and the release ledger. The module restricts CBP years using the earliest recorded `cbp/cbp_county` release date and disallows future data years. Without `as_of`, selection is by data year only, not a historical knowledge cutoff. Latest revised modeling values remain a limitation even when first-release timing is respected. All CBSA geometry is the project's harmonized geography, not a reconstruction of historical boundaries.

## Known issues and coverage

- The current snapshot contains 393 metro rows; six Puerto Rico metros have no CBP shares. High shares are available for 387 metros; High+Medium for 376. Eleven covered metros lack Utilities employment and retain missing High+Medium shares.
- A sector can exist while some county contributions are unavailable. County-reporting fractions are publication diagnostics, not estimates of the proportion of missing jobs. Counts can change over time, and unchanged counts can hide different contributing counties or suppression.
- Broad sectors cannot isolate all BankUnited specialties. CBP does not cover every job or every industry, including public administration, and largely excludes government establishments.
- Growth, specialization, and county coverage are supporting exploratory results. They are generated by `build_report()` in the same Python module; `industry_mix()` remains the core share calculation. The notebook only displays their generated values.


## Python interface and validation

From the repository root, the scoring runner can call:

```python
import pandas as pd
from src.bankunited_fit import industry_mix, load_fit_priorities

priorities = load_fit_priorities("weights/baseline.toml")
result = industry_mix(
    pd.read_parquet("data/processed/msa_naics_year.parquet"),
    pd.read_parquet("data/processed/msa_year.parquet"),
    scoring_year=2024,  # runner supplies its selected year
    priorities=priorities,
)
```

For a historical run, additionally pass `as_of="2024-12-31"` and `release_dates=pd.read_csv("data/reference/release_dates.csv")`. The runner owns writing results, recording run provenance, and regenerating the workbook consumed by the report. Passing a priority DataFrame allows the runner to use an explicitly selected TOML configuration rather than the module default.

Validation to date: the refactored core reproduces the prior notebook's 2023 employment sums/shares; all 21 migrated ratings and labels match the former CSV. Focused tests cover missing sectors, invalid totals, duplicate/unmapped inputs, year fallback, historical gating, and unchanged scoring-weight interpretation. The read-only report is validated without changing its inputs or result files and is saved with cleared outputs.


## Generated report contract

`generate_report()` reads `msa_naics_year.parquet`, `msa_year.parquet`, the county crosswalk, and priorities directly. It creates one workbook atomically with Settings, MSA industry fit, Evidence, Sector detail, Growth, Specialization, Metro footprint, Peer detail, Coverage, Coverage summary, Sensitivity, Reconciliation, and Sources worksheets. Sources records input hashes; Settings records the scoring year, actual CBP year, growth endpoints, historical cutoff, and whether the growth starting year was available.

`[industry_fit]` configures `growth_years` (default four) and `comparison_metros`. Priorities remain in `[industry_fit.priorities]`; no numerical rating weights are added. Evidence rationales use configured rationale text when supplied, otherwise refer to this methodology document. A different final-score scenario does not implicitly replace the industry mapping: use `--fit-priorities` with the Market Attractiveness command or `--priorities` with the standalone generator to select another TOML.

For release-aware Industry Fit only:

```bash
python -m src.bankunited_fit --year 2024 --as-of 2024-12-31
```

Historical workbooks are written under `outputs/as_of/<date>/industry_fit/industry_fit_report.xlsx`. Point the report's `WORKBOOK` setting at that path. The historical cutoff gates the supporting growth window before calculations. Missing/unavailable starting years yield missing CAGR; they are not silently replaced. This historical option does not rerun the older final scorer as of that date.
