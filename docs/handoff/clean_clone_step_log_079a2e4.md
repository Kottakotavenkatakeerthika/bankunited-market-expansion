# Clean-clone rerun: step log (T63) - steps 1-12 done (12 on 11/19); counts confirmed 11/19; second review by Austin 11/19, fixes applied

Tester: Bhavana Vasireddy
Commit tested: `079a2e4` (full hash 079a2e4782634635939219ab6dfd2cc026f4f08c) (merge of PR #120, main on Wed 11/18). The release tag name was not confirmed when I started (Matt said commit 079a2e4, open to any tag name, Keerthika to confirm). I cloned by commit number.
Machine: Windows 10.0.26300.9974, fresh folder `C:\t63_rerun`, Python 3.14.5
Date: 11/18/2026 (clone 6:09 PM, rebuild started 6:22 PM)
Rule followed: the README only. Exceptions: I reused my own FDIC, FRED and BEA keys and name/email from my earlier `.env` (RAW_DATA_DIR cleared), and the 30 CRA files came from the Drive folder `BankUnited Pod Data/archive/data-v0.5`, as the README describes.

## Result against the criteria

| # | Criterion | Expected | Result |
|---|---|---|---|
| 1 | The environment installs from the documented requirements | no errors | PASS |
| 2 | Tests | 298 passed | PASS: 298 passed in 57.58 s before the rebuild; 298 passed in 88.27 s again after the rebuild and scoring (11/19, step 12) |
| 3 | Checks (before and after the full rebuild) | 167 passed, 0 failed, 16 warnings | PASS both times: 167 / 0 / 16 |
| 4 | Full rebuild from raw data | finishes, checks pass | PASS: about 33 minutes (6:22 PM to 6:55 PM; end time read from the checks_report.md file time) |
| 5 | Scoring reproduces the committed outputs | only run_date changes | PASS: no scores file changed; 17 `*_run.json` files changed by 1 line each (run_date 2026-11-16 to 2026-11-18) |
| 6 | Charlotte rank | #19, 88.4 | Confirmed from `outputs/final_scores/market_attractiveness_scores.csv` (387 rows): 190 ranked (max rank 190); Charlotte-Concord-Gastonia rank 19, score 88.43. In the same file the +/-25% pillar-weight sensitivity range is #16 to #21. Strategy scenarios (`outputs/final_scores/strategy/scenario_summary_strategy.csv` and the dashboard Scenarios page): #16 to #19. The robustness checks are in `outputs/final_scores/scenario/scenario_summary.csv` |
| 7 | Dashboard opens | v0.9 not on main at this commit | Not applicable to this commit. Dashboard v0.9 was tested separately (U1 to U10) from a clone at commit 7254f1a (PR #129, not yet merged); it opened and loaded all 12 pages |

## Step log

| # | Step | Result |
|---|---|---|
| 1 | Made an empty folder `C:\t63_rerun`, `git clone` the repo, `git switch --detach 079a2e4` | HEAD at 079a2e4 "Merge pull request #120 from ...release-dates-followup"; main was also at 079a2e4 |
| 2 | `python -m venv .venv`, `.venv\Scripts\activate`, `pip install -r requirements.txt`, `copy .env.example .env` | OK, no errors (pip only said a newer pip exists) |
| 3 | `python -m pytest` | 298 passed in 57.58 s |
| 4 | `python -m src.checks` (committed tables, before any rebuild) | 167 passed, 0 failed, 16 warnings |
| 5 | Copied my own `.env` over `.env.example` copy; cleared RAW_DATA_DIR; left HTTP_USER_AGENT | OK |
| 6 | Downloaded `cra` and `cra_bank` from Drive (`data-v0.5`), extracted with `tar`, copied into `data\raw\cra` (10 files) and `data\raw\cra_bank` (20 files) | OK; counts 10 and 20 |
| 7 | `python -m src.run_pipeline` (full rebuild) | Finished; started 6:22 PM, checks_report.md written 6:55 PM, so about 33 minutes. Call Reports pulled to 2026-06-30 (46 quarters, 4,313 banks in the latest). CRA lenders matched 100% of dollars every year 2015-2024. Final line: 167 passed, 0 failed, 16 warnings |
| 8 | `git status --short` and `git diff --stat` after the rebuild | Changed: data/manifest.csv (pull times), data/processed/checks_report.md, data/processed/bank_quarter.parquet (47,525,063 to 47,526,241 bytes). No other processed table changed |
| 9 | Compared the new bank_quarter.parquet with the committed one | Same shape (240,330 rows, 62 columns), no columns added or dropped. 1,720 rows (0.7%) have a real numeric difference in 34 Call Report columns, 304 banks. Rows by quarter: 2022-09-30 (190), 2022-12-31 (206), 2023-03-31 (79), 2023-06-30 (43), 2023-09-30 (47), 2026-06-30 (57), plus smaller counts in other quarters. Cause confirmed by Austin 11/19: FDIC published a revised version on 11/16 (no new quarter); the committed table came from the 10/28 pull of FDIC's 8/19 version. 1,671 of the 1,720 rows differ only in FDIC's domestic office count. No downstream table or score changed |
| 10 | `python -m src.scoring.run` | Finished. Baseline top 5: Austin, Raleigh, Nashville, Phoenix, Indianapolis. Charlotte baseline #19; scenarios 18, 18, 16, 16, 16. BankUnited markets that rank (12 of the 13; Sebastian-Vero Beach is below the floor): North Port 8, Cape Coral 12, Atlanta 13, Naples 17, Tampa 18, Charlotte 19, Orlando 20, Dallas 21, Miami 34, Port St. Lucie 48, Houston 59, New York 151 |
| 11 | `git status --short` and `git diff --stat -- outputs` after scoring | No `*_scores.csv` or other output table changed. 17 `*_run.json` files, 1 line each (17 insertions, 17 deletions); the baseline file diff is only `run_date` 2026-11-16 to 2026-11-18 |
| 12 | `python -m pytest` again, after the full rebuild and scoring (11/19, 10:38 AM, same folder) | 298 passed in 88.27 s (1 min 28 s), same count as before the rebuild |

## Findings for the team

1. `bank_quarter.parquet` is not identical after a fresh pull: 1,720 rows differ from the committed file (mostly the 2022-09 to 2023-09 quarters, plus 57 rows in the 2026-06-30 quarter). The tables built from it, and all scores, did not change. Status: Explained. FDIC revised past quarters on 11/16; expected, no action (Austin, 11/19; he reproduced all 1,720 rows from the archived 10/28 files).
2. An untracked file named "Your registered API key is ... .txt" appeared in the repo root during the run. I did not open it or commit it. File date 11/18/2026 6:16 PM, 61 bytes, only in my rerun folder, not created by project code. Most likely saved there by a manual download during setup. Suggestion (goes in Austin's README PR for gaps 1 and 6): the README should tell people to keep downloaded key files outside the repo folder.
3. Rebuild time on this machine: about 33 minutes (the earlier log said about 20 minutes, an untimed estimate).

## README gaps from the 11/12 log, checked against 079a2e4 (11/19)

- Gap 1 (no scoring-run or dashboard steps, no link to dashboard/README.md): STILL OPEN. The only README line that mentions scoring is line 96 (a git status note); the word "dashboard" does not appear.
- Gap 6 (no Jupyter packages in requirements.txt): STILL OPEN. A search for "jupyter" and "notebook" in requirements.txt finds nothing.
- Gap 7 (dashboard/README.md): STILL OPEN. Line 11 names ..._v0.7.pbix; line 33 says scores come from branch final-score-gate (11/4/2026); line 82 tells people to download BankUnited_Market_Opportunity_Engine.pbix, which does not match the file name.
- Gaps 2 to 5: merged (PR #127, 11/16), per team.

## Second review

Austin Edwards, 11/19 (PR #132). He checked the committed scores, strategy ranks, the 17 run files, and the 298 tests and 167/0/16 checks on 079a2e4 against his own runs. Results hold. Not rerun by him: the Windows install and the 33-minute rebuild. He will approve once this log is updated and the PR is marked ready.

Tag: `integrated-v0.3` is pushed and points to 079a2e4.
