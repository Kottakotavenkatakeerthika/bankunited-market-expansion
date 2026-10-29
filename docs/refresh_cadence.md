# Refresh cadence

When each source publishes, what a refresh takes, and how often to run the pipeline (plan task T46). Release timing comes from `data/reference/release_dates.csv`; what's out now was checked on October 26, 2026. Owner: Austin.

## Recommendation: on-demand runs, on a release calendar

Run the pipeline by hand when a source publishes something the tables use, following the calendar below, rather than on a timer. BankUnited said on October 9 that it prefers on-demand runs, and that's how the pipeline already works:

- **Most sources change once a year.** Only the Call Reports (quarterly) and FRED (monthly) change more often, and the tables use FRED as yearly averages. A monthly job would find nothing new most months.
- **A timer wouldn't pick up most changes anyway.** `fetch()` reuses any file it has already downloaded, so files that change in place (BEA's all-years tables, a QCEW year going from preliminary to final, a revised FRED series) only come in with `--force-download`. A new year comes in only after someone moves `END_YEAR` and, for most sources, a `LATEST_AVAILABLE_YEAR` constant or PEP's vintage. The Call Report pull is the exception: every run adds any quarter FDIC has posted since the last run and pulls again any quarter that ended within the last 200 days.
- **Two steps need a person.** FFIEC refuses scripted downloads, so the CRA files are saved from a browser. And every rebuild goes through the checks, a pull request and a new data tag, so modelers can say which data a result used; an unattended job would skip that review.

If BankUnited later wants a scheduled job, the Call Reports are the natural candidate, since they're the only source whose new data comes in without a code change or `--force-download`: `python -m src.run_pipeline --sources ffiec` once a quarter, still followed by a reviewed pull request before anyone uses the tables.

## Sources

| Source | `--sources` | Publishes | First release in recent years | In the tables | Revisions | What a refresh takes |
|---|---|---|---|---|---|---|
| Call Reports, through FDIC BankFind `/financials` | `ffiec` | Quarterly | Due 30 days after the quarter ends (35 for banks with more than one foreign office); FDIC posts the quarter after that | 2015 Q1 to 2026 Q2 | Late filers and amendments, picked up by the 200-day re-pull | Run it. A run before FDIC posts a quarter skips that quarter. Key: `FDIC_API_KEY` |
| FDIC Summary of Deposits (SOD), BankFind `/sod` | `fdic` | Yearly, as of June 30 | Mid to late September, about 2.5 months after June 30 (September 20, 2024; September 18, 2026) | 2015–2024. 2025 and 2026 are out | A saved year is reused; `--force-download` pulls it again | A new year comes in when `END_YEAR` reaches it. Key: `FDIC_API_KEY` |
| FFIEC CRA aggregate files (`<YY>exp_aggr.zip`) | `cra` | Yearly | Mid-November to mid-December of the next year (November 13, 2025 for 2024) | 2015–2024 | FFIEC has posted revised files for some years; the pipeline keeps the originals | Save the file from a browser into `raw/cra/` and log it with `register_local_file()`, then move `CRA_LATEST_AVAILABLE_YEAR` in `src/ingest_cra.py` |
| FFIEC CRA by lender (`<YY>exp_discl.zip`, `<YY>exp_trans.zip`) | `ffiec` | Yearly, with the aggregate files | Same release | 2015–2024 | As above | Save both files from a browser into `raw/cra_bank/`; the run logs them in the manifest |
| BEA county personal income (CAINC1) and GDP (CAGDP2) | `bea_bls` | Yearly | Income in mid-November and GDP in early December of the next year, until 2024's came out together on February 5, 2026. 2025's is scheduled for December 2, 2026 | 2015–2024 | Each release can revise earlier years; the 2022 release revised 2017–2021 GDP | `--force-download`, since BEA's files hold every year and change in place. Key: `BEA_API_KEY` |
| BLS LAUS county averages | `bea_bls` | Yearly | Late April or early May of the next year | 2015–2024. 2025 is out | Revised each spring | `--force-download` for revisions; move `LAUS_LATEST_AVAILABLE_YEAR` in `src/ingest_bea_bls.py` for a new year |
| BLS QCEW county averages | `bea_bls`, read by `cre` too | Yearly, preliminary then final | Preliminary in early June, final in early September of the next year | 2015–2024. 2025 is out | The final averages replace the preliminary ones | `--force-download` after the final release; move `QCEW_LATEST_AVAILABLE_YEAR` for a new year |
| Census County Business Patterns (CBP) | `census`, then `cre` | Yearly | 16 to 18 months after the year ends (June 26, 2025 for 2023) | 2015–2023 | Rare: Census reposted 2021 in October 2023 | 2024 has no release date yet (below). When it's out, move `LATEST_AVAILABLE_YEAR` in `src/ingest_census.py` and `src/ingest_cre.py` |
| Census Population Estimates (PEP) | `pep` | Yearly, as a new vintage | Mid to late March of the next year (March 26, 2026 for Vintage 2025) | 2015–2024. 2025 is in the Vintage 2025 file already | Each vintage revises every year since the 2020 Census | Point `NEW_FILE`, `METRO_FILE` and their `2020-2025` folder in `src/ingest_pep.py` at the new vintage |
| FRED series in `data/reference/fred_series.csv` (the Charlotte unemployment rate) | `fred` | Monthly | December's value, which completes the year's average, in early February | 2015–2024 | BLS revises the months each spring | `--force-download`. Key: `FRED_API_KEY` |
| OMB metro delineation | none: `--rebuild-crosswalk` | Irregular | | July 2023 (Bulletin 23-01) | | Change `DELINEATION_VINTAGE` and `DELINEATION_URL` in `src/config.py`. A new delineation moves counties between metros in every table, so it calls for a new major data version, not a routine refresh |

A new year also needs `END_YEAR` to reach it (see the last section). `cre` downloads nothing: it reads the CBP and QCEW files, so run it after `census` or `bea_bls`. Census and BLS files need no API key.

**CBP 2024.** Census's CBP data page (last revised September 16, 2026) says 2023 is the latest year and that there is no planned release date for 2024. A Commerce Department administrative order prohibits noise infusion, which CBP has used since 2018 instead of withholding cells, and Census is evaluating other approaches. Until 2024 comes out, the `cbp_` columns stay empty for 2024 and the `cre_` columns use QCEW, as they already do.

## Calendar

| When | What's new | Run |
|---|---|---|
| Early February | Call Reports for Q4 (due January 30); FRED's December, completing last year | `--sources ffiec`; `--sources fred --force-download` |
| Mid to late March | PEP's new vintage | Point `src/ingest_pep.py` at it, then `--sources pep` |
| Late April or early May | LAUS averages for last year | `--sources bea_bls --force-download` |
| Early May | Call Reports for Q1 (due April 30) | `--sources ffiec` |
| Early June | QCEW preliminary averages for last year | `--sources bea_bls cre --force-download` |
| Early August | Call Reports for Q2 (due July 30) | `--sources ffiec` |
| Early September | QCEW final averages for last year | `--sources bea_bls cre --force-download` |
| Mid to late September | SOD as of June 30 | `--sources fdic`, once `END_YEAR` reaches that year |
| Early November | Call Reports for Q3 (due October 30) | `--sources ffiec` |
| Mid-November to mid-December | CRA for last year; BEA county income and GDP (December 2, 2026 for 2025) | Save the CRA files by hand, then `--sources cra ffiec`; `--sources bea_bls --force-download` |
| No date yet | CBP 2024; any new OMB delineation | See above |

The Call Report dates are filing deadlines; a run before FDIC posts the quarter skips it, and the next run picks it up. `--force-download` pulls every file of the sources named again, which for `bea_bls` includes ten years of QCEW files. To pull one file again instead, delete it from the raw folder and run without the flag.

## After every refresh

1. Read `data/processed/checks_report.md`: no failures, and an explanation for any new warning.
2. Add the first release of every new year or quarter to `data/reference/release_dates.csv` (see **Released** under Conventions in the data dictionary). `tests/test_release_dates.py` checks every panel year and counts the Call Report quarters (46, through 2026 Q2), so update it in the same pull request.
3. Open a pull request with the rebuilt tables. After it merges, tag it (`data-vX.Y`) and copy the raw folder to the Drive archive, as "Versioning the data" in the README describes.

## Rolling the panel to a new year

`END_YEAR` in `src/config.py` (2024) ends the yearly tables for every source at once; only the Call Reports run past it. As of October 26, 2026, 2025 is out for PEP, LAUS, QCEW, FRED and SOD, and SOD has 2026 too. BEA's 2025 is due December 2, 2026, and CRA's 2025 usually comes in November or December. Moving `END_YEAR` to 2025 makes sense once both are out. Until CBP catches up, its columns stay empty for the newest years.
