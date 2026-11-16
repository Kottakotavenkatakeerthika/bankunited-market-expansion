# Clean-clone test: step log (T75, feeds T69)

Tester: Bhavana Vasireddy
Release tested: tag `integrated-v0.2` (per Austin, on the PR #100 merge commit 3c48fd5)
Machine: fresh Windows folder `C:\clean_clone_test`, Python 3.14.5, git 2.55.0.windows.5
Dates: 11/10/2026 (first run), 11/11/2026 (full rebuild), 11/12/2026 (dashboard)
Rule followed: the README only; no files from my own project folder and no data copied in, except the 30 CRA files and my own keys as Austin's 11/10 email described.

## Result against the four pass criteria

| # | Criterion | Result |
|---|---|---|
| 1 | The environment installs from the documented requirements | PASS |
| 2 | The data build finishes with all checks passing | PASS (full rebuild from raw data: 163 passed, 0 failed, 16 warnings; no processed table changed) |
| 3 | The scoring run reproduces the v0.2 scores | PASS (Charlotte #16 of 287, score 88.4; the rewritten scores file is identical to the committed one) |
| 4 | The dashboard opens and shows Charlotte at #16 of 287 (88.4) | PASS |

## Step log

| # | Step | Result |
|---|---|---|
| 1 | Made an empty folder `C:\clean_clone_test` and cloned the tag: `git clone --branch integrated-v0.2 ...` | OK |
| 2 | `git describe --tags` | prints `integrated-v0.2` |
| 3 | Listed the clone: README.md, requirements.txt, .env.example, pytest.ini, folders app, dashboard, data, docs, notebooks, outputs, plan, src, tests, weights | OK |
| 4 | `python --version`, `git --version` | Python 3.14.5, git 2.55.0.windows.5 (README says "Python 3.11 or newer") |
| 5 | Read README.md (5,571 bytes) | OK; gaps noted below |
| 6 | `python -m venv .venv` and `.venv\Scripts\activate` | OK |
| 7 | `pip install -r requirements.txt` | OK, no errors (pandas, numpy, pyarrow, duckdb, scikit-learn, requests, openpyxl, python-dotenv, pytest) |
| 8 | `copy .env.example .env` (README says `cp`, which is not a Windows command) | OK with the Windows command |
| 9 | `python -m pytest` | 222 passed in 28 s |
| 10 | `python -m src.checks` on the committed tables | 163 passed, 0 failed, 16 warnings |
| 11 | Looked for scoring and dashboard steps in README, src, docs, notebooks, dashboard and outputs | Not in the main README; the run commands are in comments at the top of src/market_attractiveness.py and src/compare_scenarios.py; dashboard/README.md exists but is not linked |
| 12 | `python -m src.market_attractiveness --show-weights` | OK: 27 measures, 25% per pillar |
| 13 | Copied the committed scores file, then ran `python -m src.market_attractiveness` | OK: 287 of 393 MSAs scored; Charlotte rank 16, score 88.4 (range 14 to 19); top 5 Austin, Raleigh, Phoenix, Nashville, Indianapolis |
| 14 | `fc` of the rewritten scores file against the committed copy | no differences encountered |
| 15 | Keys (11/11): reused my FDIC, FRED and BEA keys, signed up for a BLS key (arrived by email), set HTTP_USER_AGENT to my name and email, left RAW_DATA_DIR empty | `.env` is not shown by `git status` (ignored) |
| 16 | Copied the cra (10 files) and cra_bank (20 files) folders from the Drive archive data-v0.5 into data/raw/cra and data/raw/cra_bank | OK (Drive gives a timestamped zip with the real folder one level down) |
| 17 | `python -m src.run_pipeline` (full rebuild) | Finished; about 20 minutes (my estimate, not timed) |
| 18 | `python -m src.checks` after the rebuild | 163 passed, 0 failed, 16 warnings |
| 19 | `python -m pytest` after the rebuild | 222 passed in 33 s |
| 20 | `git status --short` and `git diff --stat` after the rebuild | No data/processed parquet file changed. Only data/manifest.csv (new pull times; 679 insertions, 674 deletions), data/processed/checks_report.md and outputs/final_scores/market_attractiveness_run.json changed, which a normal run rewrites |
| 21 | Installed Power BI Desktop from the Microsoft Store (free, no sign-in) | OK |
| 22 | Opened dashboard/BankUnited_Market_Opportunity_Engine_v0.7.pbix | Opens with 8 pages (Summary, Market Profile, P1 Lending, P2 Deposits, P3 Competition, P4 Market Quality, Scenarios, Method & Status) |
| 23 | Summary page | Charlotte #16 of 287, Attractiveness Score 88.4, #14 to #16 across the 5 strategy scenarios, 287 metros ranked; row 16 of the ranking table is Charlotte-Concord-Gastonia (88.4) |

File opened for criterion 4: `dashboard/BankUnited_Market_Opportunity_Engine_v0.7.pbix`. The dashboard README names `BankUnited_Market_Opportunity_Engine.pbix` (gap 7).

## README gaps found (for T76)

1. The main README has no steps for the scoring run or the dashboard, and does not link dashboard/README.md.
2. `cp .env.example .env` does not work in Windows Command Prompt (use `copy`).
3. API keys: the README does not say which keys are required. Only FDIC has a signup link; FRED, BEA and BLS do not. HTTP_USER_AGENT needs a name and email.
4. The raw data folder is not explained for a fresh machine, and the README suggests pointing RAW_DATA_DIR at the shared Drive folder, which would write into the shared folder.
5. `--skip-ingest` cannot work on a fresh clone, because the interim files are not committed.
6. requirements.txt has no Jupyter packages, so the pillar notebooks cannot be opened on a fresh install, and Power BI Desktop is not mentioned.
7. dashboard/README.md says to download BankUnited_Market_Opportunity_Engine.pbix, but the file is named ..._v0.7.pbix, and it says the scores came from the branch final-score-gate, not from the tag.
8. At this tag, docs/methodology.md, docs/technical_handoff.md, notebooks 01_ to 03_, src/bankunited_fit.py and src/entry_scenarios.py are empty files.
9. outputs/pillar_scores has no pillar4_run.json, while pillars 1 to 3 each have one.

Notes from the rerun for the README fixes: Drive packs each folder as a timestamped zip with the real folder one level down; a normal run rewrites manifest.csv, checks_report.md and market_attractiveness_run.json, so git status is never clean after a run; the four keys are separate signups and the BLS key arrives by email.
