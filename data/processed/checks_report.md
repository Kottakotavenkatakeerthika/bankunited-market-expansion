# Data checks

Run 2026-10-28 12:09 UTC on commit `b753452`

| Table | Check | Result | Detail |
|---|---|---|---|
| msa_year | key columns present | pass |  |
| msa_year | no empty keys | pass |  |
| msa_year | one row per key | pass |  |
| msa_year | cbsa_code is 5 digits | pass |  |
| msa_year | every universe metro has every year | pass |  |
| msa_year | bankunited_sod_offices_count >= 0 | pass |  |
| msa_year | bankunited_sod_deposits_usd >= 0 | pass |  |
| msa_year | bankunited_cra_small_business_loan_count >= 0 | pass |  |
| msa_year | bankunited_cra_small_business_loan_amount_usd >= 0 | pass |  |
| msa_year | bea_personal_income_usd >= 0 | pass |  |
| msa_year | bea_gdp_usd >= 0 | pass |  |
| msa_year | bls_labor_force_count >= 0 | pass |  |
| msa_year | bls_employed_count >= 0 | pass |  |
| msa_year | bls_unemployed_count >= 0 | pass |  |
| msa_year | bls_unemployment_rate_pct within 0-100 | pass |  |
| msa_year | bls_qcew_employment_count >= 0 | pass |  |
| msa_year | bls_qcew_total_wages_usd >= 0 | pass |  |
| msa_year | cbp_establishments_count >= 0 | pass |  |
| msa_year | cbp_employment_count >= 0 | pass |  |
| msa_year | cbp_first_quarter_payroll_usd >= 0 | pass |  |
| msa_year | cbp_annual_payroll_usd >= 0 | pass |  |
| msa_year | cbp_establishments_20plus_count >= 0 | pass |  |
| msa_year | cbp_establishments_20_249_count >= 0 | pass |  |
| msa_year | cra_small_business_loan_count >= 0 | pass |  |
| msa_year | cra_small_business_loan_amount_usd >= 0 | pass |  |
| msa_year | cre_real_estate_establishments_count >= 0 | pass |  |
| msa_year | cre_real_estate_employment_count >= 0 | pass |  |
| msa_year | cre_real_estate_payroll_usd >= 0 | pass |  |
| msa_year | cre_real_estate_counties_reported_count >= 0 | pass |  |
| msa_year | cre_real_estate_qcew_fallback_counties_count >= 0 | pass |  |
| msa_year | cre_nonres_construction_establishments_count >= 0 | pass |  |
| msa_year | cre_nonres_construction_employment_count >= 0 | pass |  |
| msa_year | cre_nonres_construction_payroll_usd >= 0 | pass |  |
| msa_year | cre_nonres_construction_counties_reported_count >= 0 | pass |  |
| msa_year | cre_nonres_construction_qcew_fallback_counties_count >= 0 | pass |  |
| msa_year | fred_unemployment_rate_pct within 0-100 | pass |  |
| msa_year | pep_population_count >= 0 | pass |  |
| msa_year | pep_counties_reported_count >= 0 | pass |  |
| msa_year | sod_deposits_usd >= 0 | pass |  |
| msa_year | sod_main_office_deposits_usd >= 0 | pass |  |
| msa_year | sod_home_banking_office_deposits_usd >= 0 | pass |  |
| msa_year | sod_offices_count >= 0 | pass |  |
| msa_year | sod_branches_count >= 0 | pass |  |
| msa_year | sod_institutions_count >= 0 | pass |  |
| msa_year | sod_deposit_hhi within 0-10,000 | pass |  |
| msa_year | sod_deposit_ex_main_office_hhi within 0-10,000 | pass |  |
| msa_year | sod_top3_deposit_share within 0-1 | pass |  |
| msa_year | sod_top3_deposit_ex_main_office_share within 0-1 | pass |  |
| msa_year | sod_top3_deposit_share_3y_change_net within -1 to 1 | pass |  |
| msa_year | sod_top3_deposit_ex_main_office_share_3y_change_net within -1 to 1 | pass |  |
| msa_year | fred_unemployment_rate_pct mostly filled | warning | 100% empty |
| msa_year | every column has a dictionary row | pass |  |
| msa_year | no column has two dictionary rows | pass |  |
| msa_year | every dictionary Type is known | pass |  |
| msa_year | values fit their dictionary Type | pass |  |
| msa_year | spot check: cbp_establishments_count for 16740 in 2023 | pass | built 71,411.00 vs published 71,411.00 Census County Business Patterns, 2023 MSA-level file cbp23msa.zip (https://www2.census.gov/programs-surveys/cbp/datasets/2023/cbp23msa.zip), row msa=16740 naics=------ (all-industry total), field EST=71411. This file uses the 2023 OMB delineation (includes Anson County, 37007); the 2021 file (cbp21msa.zip, EST=67674) does not and falls short by exactly Anson's 380 establishments, so use 2022 or later. Retrieved 2026-10-01. |
| msa_year | spot check: bea_gdp_usd for 16740 in 2023 | pass | built 259,146,518,000.00 vs published 255,666,417,000.00 BEA current-dollar GDP by metro area, as republished on FRED series NGMP16740 (https://fred.stlouisfed.org/series/NGMP16740, Total Gross Domestic Product for Charlotte-Concord-Gastonia, NC-SC (MSA), millions of dollars), observation 2023-01-01 value=255666.417 (x1,000,000). Series is discontinued, last updated 2024-12-04 (BEA December 2024 vintage); our pull is a later BEA revision, hence the 2% tolerance. The gap is a vintage difference, not a pipeline error: summing Charlotte's 11 counties from the same December 2024 release (lagdp1224.xlsx) gives $206.53B vs FRED's $206.55B metro figure (within 0.007%), and Mecklenburg alone was revised from $139.16B to $141.41B (+1.6%), matching the size of the overall gap. Both checks were done on real GDP (chained 2017 dollars), since that release only publishes real GDP by county; current-dollar revisions are assumed to be similar. Retrieved 2026-09-30. |
| msa_year | spot check: bls_qcew_employment_count for 16740 in 2024 | pass | built 1,339,734.00 vs published 1,339,736.00 BLS QCEW 2024 annual-by-area file 2024_annual_by_area.zip (https://www.bls.gov/cew/data/files/2024/csv/2024_annual_by_area.zip), inner file '2024.annual C1674 Charlotte-Concord-Gastonia, NC-SC MSA.csv', row own_code=0 industry_code=10 (all ownerships, all industries), field annual_avg_emplvl=1339736. QCEW MSA files before 2024 use the pre-2023 delineation (no Anson County), so use 2024 or later. Retrieved 2026-09-30. |
| msa_year | spot check: fred_unemployment_rate_pct for 16740 in 2024 | pass | built 3.70 vs published 3.70 FRED series CHAR737URN (https://fred.stlouisfed.org/series/CHAR737URN), annual average computed by FRED (API series/observations with frequency=a, aggregation_method=avg), observation 2024-01-01 value=3.7. FRED rounds to one decimal, so tolerance allows +/-0.05 points. Retrieved 2026-09-30. |
| msa_year | spot check: cra_small_business_loan_count for 16740 in 2023 | pass | built 76,874.00 vs published 76,874.00 FFIEC CRA 2023 aggregate flat file 23exp_aggr.zip (https://www.ffiec.gov/sites/default/files/data/cra/flat-files/23exp_aggr.zip, downloaded by hand), Table A1-1 (Small Business Loans by County - Originations): FFIEC's own MSA/MD Total row (Report Level 210, MSA/MD 16740 in columns 17-21), independent of our county-to-metro rollup. Sum of the three loan-count fields: <$100k 72961 + $100k-$250k 2031 + $250k-$1M 1882 = 76874. This file already assigns Anson County (37007) to MSA/MD 16740, so it matches the 2023 OMB delineation. Retrieved 2026-10-01. |
| msa_year | spot check: cra_small_business_loan_amount_usd for 16740 in 2023 | pass | built 2,374,875,000.00 vs published 2,374,875,000.00 FFIEC CRA 2023 aggregate flat file 23exp_aggr.zip (https://www.ffiec.gov/sites/default/files/data/cra/flat-files/23exp_aggr.zip, downloaded by hand), Table A1-1 (Small Business Loans by County - Originations): FFIEC's own MSA/MD Total row (Report Level 210, MSA/MD 16740 in columns 17-21), independent of our county-to-metro rollup. Sum of the three loan-amount fields ($1,000s): <$100k 1008611 + $100k-$250k 343722 + $250k-$1M 1022542 = 2374875, x1,000 = 2374875000. This file already assigns Anson County (37007) to MSA/MD 16740, so it matches the 2023 OMB delineation. Retrieved 2026-10-01. |
| msa_year | spot check: sod_deposits_usd for 16740 in 2024 | pass | built 457,313,881,000.00 vs published 457,314,000,000.00 FDIC State Profile, North Carolina, Fourth Quarter 2024 (https://www.fdic.gov/analysis/state-profiles/atlanta/nc.pdf), table 'Largest Deposit Markets (from 2024 Summary of Deposits)', row Charlotte-Concord-Gastonia, NC-SC: 50 institutions, deposits $457,314 million (x1,000,000). The South Carolina Q4 2024 profile lists the same row. FDIC rounds to the nearest $1 million, well inside the tolerance. The profile URL is replaced each quarter, so confirm against FDIC's Deposit Market Share report for MSA 16740, June 30, 2024 (BankFind Suite, Summary of Deposits). Retrieved 2026-10-04. |
| msa_year | spot check: sod_institutions_count for 16740 in 2024 | pass | built 50.00 vs published 50.00 FDIC State Profile, North Carolina, Fourth Quarter 2024 (https://www.fdic.gov/analysis/state-profiles/atlanta/nc.pdf), table 'Largest Deposit Markets (from 2024 Summary of Deposits)', row Charlotte-Concord-Gastonia, NC-SC: 50 institutions. Same table and row as the sod_deposits_usd check. A count, so it must match exactly (tolerance 0). The profile URL is replaced each quarter, so confirm against FDIC's Deposit Market Share report for MSA 16740, June 30, 2024 (BankFind Suite, Summary of Deposits). Retrieved 2026-10-04. |
| msa_year | spot check: pep_population_count for 16740 in 2024 | pass | built 2,884,708.00 vs published 2,884,708.00 Census Population Estimates, Vintage 2025 metro file cbsa-est2025-alldata.csv (https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/metro/totals/cbsa-est2025-alldata.csv), row CBSA=16740 LSAD=Metropolitan Statistical Area, field POPESTIMATE2024. Retrieved 2026-10-07. |
| msa_year | spot check: pep_migration_net for 16740 in 2024 | pass | built 55,969.00 vs published 55,969.00 Census Population Estimates, Vintage 2025 metro file cbsa-est2025-alldata.csv (https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/metro/totals/cbsa-est2025-alldata.csv), row CBSA=16740 LSAD=Metropolitan Statistical Area, field NETMIG2024. Retrieved 2026-10-07. |
| msa_year | spot check: pep_population_count for 16740 in 2019 | pass | built 2,626,934.00 vs published 2,626,934.00 Census Population Estimates, 2010-2020 intercensal county file cc-est2020int-agesex-all.csv (https://www2.census.gov/programs-surveys/popest/datasets/2010-2020/intercensal/county/asrh/cc-est2020int-agesex-all.csv), YEAR 11 = July 1, 2019, field POPESTIMATE, summed over Charlotte's 11 counties (37007, 37025, 37071, 37097, 37109, 37119, 37159, 37179, 45023, 45057, 45091). Census publishes no intercensal metro total for this vintage, so this check compares our rollup with the sum of Census's own county values. Retrieved 2026-10-14. |
| msa_year | spot check: cre_real_estate_establishments_count for 16740 in 2023 | pass | built 4,479.00 vs published 4,479.00 Census County Business Patterns, 2023 MSA-level file cbp23msa.zip, row msa=16740 naics=531/// (real estate), field EST=4479. Same 2023 OMB delineation as the county sums. https://www2.census.gov/programs-surveys/cbp/datasets/2023/cbp23msa.zip. Retrieved 2026-10-07. |
| msa_year | spot check: cre_real_estate_employment_count for 16740 in 2023 | pass | built 16,536.00 vs published 16,536.00 Same file and row, field EMP=16536. https://www2.census.gov/programs-surveys/cbp/datasets/2023/cbp23msa.zip. Retrieved 2026-10-07. |
| msa_year | spot check: cre_real_estate_payroll_usd for 16740 in 2023 | pass | built 1,163,068,000.00 vs published 1,163,068,000.00 Same file and row, field AP=1,163,068 ($1,000s), converted to whole dollars. https://www2.census.gov/programs-surveys/cbp/datasets/2023/cbp23msa.zip. Retrieved 2026-10-07. |
| msa_year | spot check: cre_nonres_construction_establishments_count for 16740 in 2023 | pass | built 376.00 vs published 367.00 Census County Business Patterns, 2023 MSA-level file cbp23msa.zip (https://www2.census.gov/programs-surveys/cbp/datasets/2023/cbp23msa.zip), row msa=16740 naics=2362//, field EST=367. Tolerance is 3%: Lancaster County, SC has no 2362 row in the CBP county file, so its establishments come from BLS QCEW, while Census's own metro total implies about 2 there (367 minus the other counties' 365). QCEW counts establishments differently from CBP, so the two sources do not tie exactly (built 376 vs 367, about 2.5%). See cre_nonres_construction_qcew_fallback_counties_count (1 in 2023). Retrieved 2026-10-07. |
| msa_year | spot check: cre_real_estate_establishments_count for 16740 in 2024 | pass | built 5,006.00 vs published 5,005.00 BLS QCEW 2024 annual-by-area file 2024_annual_by_area.zip (https://www.bls.gov/cew/data/files/2024/csv/2024_annual_by_area.zip), inner file '2024.annual C1674 Charlotte-Concord-Gastonia, NC-SC MSA.csv', row own_code=5 industry_code=531 (private ownership, real estate), field annual_avg_estabs_count=5005. CBP has no 2024 file, so 2024 comes from QCEW; the row's disclosure_code is N, which suppresses employment and wages but not the establishment count. QCEW MSA files before 2024 use the pre-2023 delineation (no Anson County), so use 2024 or later. Retrieved 2026-10-08. |
| msa_year | spot check: cbp_establishments_20plus_count for 16740 in 2023 | pass | built 11,309.00 vs published 11,309.00 Census County Business Patterns, 2023 MSA-level file cbp23msa.zip (https://www2.census.gov/programs-surveys/cbp/datasets/2023/cbp23msa.zip), row msa=16740 naics=------ (all-industry total), fields EST=71411 minus N<5=39615, N5_9=11663 and N10_19=8824 (establishments with 20 or more employees). Retrieved 2026-10-19. |
| msa_year | spot check: cbp_establishments_20_249_count for 16740 in 2023 | pass | built 10,737.00 vs published 10,737.00 Census County Business Patterns, 2023 MSA-level file cbp23msa.zip (https://www2.census.gov/programs-surveys/cbp/datasets/2023/cbp23msa.zip), row msa=16740 naics=------ (all-industry total), fields N20_49=7113 plus N50_99=2364 and N100_249=1260 (establishments with 20 to 249 employees). Retrieved 2026-10-19. |
| bank_quarter | key columns present | pass |  |
| bank_quarter | no empty keys | pass |  |
| bank_quarter | one row per key | pass |  |
| bank_quarter | call_total_assets_usd >= 0 | pass |  |
| bank_quarter | call_total_deposits_usd >= 0 | pass |  |
| bank_quarter | call_domestic_deposits_usd >= 0 | pass |  |
| bank_quarter | call_core_deposits_usd >= 0 | pass |  |
| bank_quarter | call_brokered_deposits_usd >= 0 | pass |  |
| bank_quarter | call_noninterest_bearing_deposits_usd >= 0 | pass |  |
| bank_quarter | call_domestic_noninterest_bearing_deposits_usd >= 0 | pass |  |
| bank_quarter | call_uninsured_deposits_usd >= 0 | pass |  |
| bank_quarter | call_total_loans_usd >= 0 | pass |  |
| bank_quarter | call_net_loans_usd >= 0 | pass |  |
| bank_quarter | call_real_estate_loans_usd >= 0 | pass |  |
| bank_quarter | call_construction_loans_usd >= 0 | pass |  |
| bank_quarter | call_nonfarm_nonres_loans_usd >= 0 | pass |  |
| bank_quarter | call_owner_occupied_nonres_loans_usd >= 0 | pass |  |
| bank_quarter | call_other_nonres_loans_usd >= 0 | pass |  |
| bank_quarter | call_multifamily_loans_usd >= 0 | pass |  |
| bank_quarter | call_residential_1_4_family_loans_usd >= 0 | pass |  |
| bank_quarter | call_farmland_loans_usd >= 0 | pass |  |
| bank_quarter | call_ci_loans_usd >= 0 | pass |  |
| bank_quarter | call_ci_loans_non_us_addressees_usd >= 0 | pass |  |
| bank_quarter | call_agricultural_loans_usd >= 0 | pass |  |
| bank_quarter | call_consumer_loans_usd >= 0 | pass |  |
| bank_quarter | call_nondepository_fi_loans_usd >= 0 | pass |  |
| bank_quarter | call_securities_usd >= 0 | pass |  |
| bank_quarter | call_noncurrent_loans_usd >= 0 | pass |  |
| bank_quarter | call_ci_loans_1m_or_less_usd >= 0 | pass |  |
| bank_quarter | call_ci_loans_1m_or_less_count >= 0 | pass |  |
| bank_quarter | call_nonfarm_nonres_loans_1m_or_less_usd >= 0 | pass |  |
| bank_quarter | call_nonfarm_nonres_loans_1m_or_less_count >= 0 | pass |  |
| bank_quarter | call_employees_count >= 0 | pass |  |
| bank_quarter | call_domestic_offices_count >= 0 | pass |  |
| bank_quarter | call_ci_loans_over_1m_usd >= 0 | pass |  |
| bank_quarter | call_nonfarm_nonres_loans_over_1m_usd >= 0 | pass |  |
| bank_quarter | call_uninsured_deposits_usd mostly filled | warning | 84% empty |
| bank_quarter | call_ci_loans_non_us_addressees_usd mostly filled | warning | 77% empty |
| bank_quarter | every column has a dictionary row | pass |  |
| bank_quarter | no column has two dictionary rows | pass |  |
| bank_quarter | every dictionary Type is known | pass |  |
| bank_quarter | values fit their dictionary Type | pass |  |
| bank_quarter | spot check: call_total_assets_usd for RSSD 3938186 on 2026-06-30 | pass | built 34,864,976,000.00 vs published 34,864,976,000.00 FDIC BankFind API /financials, BankUnited N.A. (CERT 58979), REPDTE 20260630, ASSET 34864976 ($000s), retrieved 2026-10-12 |
| bank_quarter | spot check: call_leverage_ratio for RSSD 3938186 on 2026-06-30 | pass | built 9.43 vs published 9.43 FDIC BankFind API /financials, BankUnited N.A. (CERT 58979), REPDTE 20260630, RBC1AAJ 9.4266, retrieved 2026-10-12 |
| bank_quarter | spot check: call_noninterest_bearing_deposits_usd for RSSD 3938186 on 2026-06-30 | pass | built 10,145,045,000.00 vs published 10,145,045,000.00 FDIC BankFind API /financials, BankUnited N.A. (CERT 58979), REPDTE 20260630, DEPNI 10145045 ($000s), retrieved 2026-10-15 |
| bank_quarter | spot check: call_ci_loans_over_1m_usd for RSSD 3938186 on 2026-06-30 | pass | built 4,490,674,000.00 vs published 4,490,674,000.00 FDIC BankFind API /financials, BankUnited N.A. (CERT 58979), REPDTE 20260630: LNCI 4702937 - LNCINUS 2980 - LNCI4 209283 = 4490674 ($000s), retrieved 2026-10-15 |
| bank_quarter | spot check: call_nonfarm_nonres_loans_over_1m_usd for RSSD 3938186 on 2026-06-30 | pass | built 6,670,334,000.00 vs published 6,670,334,000.00 FDIC BankFind API /financials, BankUnited N.A. (CERT 58979), REPDTE 20260630: LNRENRES 6879810 - LNRENR4 209476 = 6670334 ($000s), retrieved 2026-10-15 |
| bank_quarter | spot check: call_ci_loans_1m_or_less_usd for RSSD 470032 on 2026-06-30 | pass | built 20,093,000.00 vs published 20,093,000.00 FDIC BankFind API /financials, Community Spirit Bank (CERT 50), an FFIEC 051 filer, REPDTE 20260630, LNCI4 20093 ($000s), retrieved 2026-10-15. Checks that June values from semiannual Part II reporters are kept |
| bank_msa_year | key columns present | pass |  |
| bank_msa_year | no empty keys | pass |  |
| bank_msa_year | one row per key | pass |  |
| bank_msa_year | cbsa_code is 5 digits | pass |  |
| bank_msa_year | cra_bank_small_business_loan_count >= 0 | pass |  |
| bank_msa_year | cra_bank_small_business_loan_amount_usd >= 0 | pass |  |
| bank_msa_year | cra_bank_revenue_under_1m_loan_count >= 0 | pass |  |
| bank_msa_year | cra_bank_revenue_under_1m_loan_amount_usd >= 0 | pass |  |
| bank_msa_year | cra_bank_small_business_amount_share within 0-1 | pass |  |
| bank_msa_year | sod_deposits_usd >= 0 | pass |  |
| bank_msa_year | sod_main_office_deposits_usd >= 0 | pass |  |
| bank_msa_year | sod_home_banking_office_deposits_usd >= 0 | pass |  |
| bank_msa_year | sod_offices_count >= 0 | pass |  |
| bank_msa_year | sod_branches_count >= 0 | pass |  |
| bank_msa_year | sod_deposit_share within 0-1 | pass |  |
| bank_msa_year | sod_cert mostly filled | warning | 72% empty |
| bank_msa_year | sod_bank_name mostly filled | warning | 72% empty |
| bank_msa_year | sod_top_holder_rssd_id mostly filled | warning | 72% empty |
| bank_msa_year | sod_top_holder_name mostly filled | warning | 72% empty |
| bank_msa_year | sod_deposits_usd mostly filled | warning | 72% empty |
| bank_msa_year | sod_main_office_deposits_usd mostly filled | warning | 72% empty |
| bank_msa_year | sod_home_banking_office_deposits_usd mostly filled | warning | 72% empty |
| bank_msa_year | sod_offices_count mostly filled | warning | 72% empty |
| bank_msa_year | sod_branches_count mostly filled | warning | 72% empty |
| bank_msa_year | sod_deposit_share mostly filled | warning | 72% empty |
| bank_msa_year | every column has a dictionary row | pass |  |
| bank_msa_year | no column has two dictionary rows | pass |  |
| bank_msa_year | every dictionary Type is known | pass |  |
| bank_msa_year | values fit their dictionary Type | pass |  |
| msa_naics_year | key columns present | pass |  |
| msa_naics_year | no empty keys | pass |  |
| msa_naics_year | one row per key | pass |  |
| msa_naics_year | cbsa_code is 5 digits | pass |  |
| msa_naics_year | naics_code is 2 digits | pass |  |
| msa_naics_year | cbp_establishments_count >= 0 | pass |  |
| msa_naics_year | cbp_employment_count >= 0 | pass |  |
| msa_naics_year | cbp_annual_payroll_usd >= 0 | pass |  |
| msa_naics_year | cbp_counties_reported_count >= 0 | pass |  |
| msa_naics_year | every column has a dictionary row | pass |  |
| msa_naics_year | no column has two dictionary rows | pass |  |
| msa_naics_year | every dictionary Type is known | pass |  |
| msa_naics_year | values fit their dictionary Type | pass |  |
| msa_year_history | key columns present | pass |  |
| msa_year_history | no empty keys | pass |  |
| msa_year_history | one row per key | pass |  |
| msa_year_history | cbsa_code is 5 digits | pass |  |
| msa_year_history | every universe metro has every year | pass |  |
| msa_year_history | bea_personal_income_usd >= 0 | pass |  |
| msa_year_history | bea_gdp_usd >= 0 | pass |  |
| msa_year_history | every column has a dictionary row | pass |  |
| msa_year_history | no column has two dictionary rows | pass |  |
| msa_year_history | every dictionary Type is known | pass |  |
| msa_year_history | values fit their dictionary Type | pass |  |
