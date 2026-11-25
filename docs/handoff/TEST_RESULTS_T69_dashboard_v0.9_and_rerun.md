# Test results: dashboard v0.9 user test (U1 to U10) and clean-clone rerun (T63)

DRAFT for the 12/4 handoff package (T69). Prepared by Bhavana Vasireddy, 11/19/2026.
Items in [square brackets] are still to be confirmed or filled in.

Release tested: scoring v0.4 + dashboard v0.9 on data-v0.6. Charlotte-Concord-Gastonia is #19 of 190 ranked metros, score 88.4.

---

## Part 1. User test of dashboard v0.9 (U1 to U10)

Each task is something a Corporate Treasury user would do, traced to a sponsor request or Work Order requirement.

- Tester: Bhavana Vasireddy
- Tool: Power BI Desktop, file `BankUnited_Market_Opportunity_Engine_v0.9.pbix`, branch dashboard-v0.9 (PR #129)
- First run: 11/18/2026, commit `0508ebe` ("Add Power BI dashboard v0.9")
- Retest after Sonia's fixes: 11/18/2026, commit `7254f1a` ("Rank by Measure note; update Method open decisions")
- Data and scoring: data-v0.6, scoring v0.4

### 1a. Task results (first run on 0508ebe)

| # | User task | Request / requirement | Page | Expected | What I saw | Pass / fail |
|---|---|---|---|---|---|---|
| U1 | Find Charlotte's rank and the measures helping and hurting it | Charlotte case (T33); explainability (T35) | Market Profile | Charlotte #19 of 190, score 88.4, scenario range #16 to #19; measure points add up to 88.4 | #19 of 190, 88.4; range #16 to #19; points add up to 88.4 | Pass |
| U2 | Compare two or more metros side by side | Kort Brown, 11/6 gate (T71) | Compare | Selected metros show the same scores as the Overview | Atlanta, Tampa, Charlotte and Dallas side by side; scores match the Overview | Pass |
| U3 | Rank every metro on a single measure | Kort Brown, 11/6 gate (T72) | Rank by Measure | Every metro ranked on the chosen measure, with Charlotte's rank and percentile shown | Charlotte #21 on middle-market establishments (percentile 94.8). Base question: see items log, item 4 | Pass |
| U4 | Change pillar weights and watch ranks move | Kort Brown (T73); sponsor 11/17 (sliders open 0 to 100) | Weight sliders | Ranks update when a weight changes; reset returns Charlotte to #19 at 88.4 | Lending 50 gave shares 40/20/20/20 and Charlotte #20 (88.0); reset to 25 gave #19 (88.4) | Pass for the Lending slider only. Deposits, Competition and Market Quality sliders not yet tested |
| U5 | Set the minimum population floor; 0 turns it off | Sponsor 11/6 (B16, T74) | Filters | 250,000 gives 190 ranked; 0 gives 381 ranked | 190 ranked, Charlotte #19; floor 0 gave 381 ranked, Charlotte #19 of 381 | Pass |
| U6 | Limit to metros within a distance of a BankUnited market | Fit & Feasibility (T70) | Filters | 500 miles matches the Adjacency scenario (121 ranked, Charlotte #16); 0 gives 190 | 121 ranked, Charlotte #16 of 121; 0 gave 190 | Pass |
| U7 | Filter by industry share; exclude current markets | Fit & Feasibility (T70); 13 BankUnited markets (B23) | Filters | The list shrinks as the filter is set. Excluding current markets removes the BankUnited markets that are in the 190 | Share 70%: 126 ranked, Charlotte #7. Share 72%: Charlotte unranked (86 ranked). Exclude current markets: 178 ranked, Charlotte unranked (12 markets leave the 190; Sebastian-Vero Beach is below the floor) | Pass |
| U8 | See metros on a map with BankUnited's 13 markets highlighted | Work Order TR-02 (T83) | Map (Azure Maps, needs internet) | Map loads; clicking a dot shows that metro's rank and score | Charlotte rank 19, score 88.4, shown as in market; clicking a dot fills the side panel | Pass on my laptop. Demo machine not yet checked |
| U9 | Switch scenarios and check rank robustness | Scenario design (T34) | Scenarios | Charlotte's rank in each scenario matches the scenario summary file | Six scenarios: #19, #18, #18, #16, #16, #16 | Pass |
| U10 | Move between all pages without help | Usability | Navigation bar | All pages open with no errors or blank visuals | All 12 pages opened, no errors or blank visuals | Pass |

Checked 11/19 against the scores file in the rerun folder (`outputs/final_scores/market_attractiveness_scores.csv`, 387 rows): 190 ranked; Charlotte rank 19, score 88.43. `outputs/final_scores/strategy/scenario_summary_strategy.csv` and the dashboard Scenarios page agree (the robustness checks are in `outputs/final_scores/scenario/scenario_summary.csv`): baseline 19, C&I-led 18, CRE-led 18, Deposit-led 16, Adjacency 16, Emerging market 16.

### 1b. Items found, fix commit and status

None of these changed a rank or score.

| # | Item | Fix commit | Status | Retest (7254f1a) |
|---|---|---|---|---|
| 1 | Map tooltip showed "Population" twice; the dot-size value is now labelled "Dot size" | 109e8bd (Sonia) | Fixed | Rechecked: OK |
| 2 | Lending score showed 65.7 on one page and 65.6 on others (rounded twice); now 65.6 everywhere | e6b9bc2 (Sonia) | Fixed | Rechecked: OK |
| 3 | BankUnited markets showed 0 miles on Map and Compare; now show "In market" | e6b9bc2 (Sonia) | Fixed | Rechecked: OK |
| 4 | Rank by Measure showed "#21 of 195". This is intended: 190 ranked plus Connecticut's 5 metros. The percentile compares all 387 metros with data. A "How to read this page" box was added | 7254f1a (Sonia, text only) | Resolved | Rechecked: OK |
| 5 | "Exclude current markets" gives 178, not 177 or 190. Correct: 12 of the 13 BankUnited markets are in the 190; Sebastian-Vero Beach is below the 250,000 floor | None needed | Explained | n/a |
| 6 | Floor 0: Charlotte stays #19 of 381; confirm no metro under 250,000 scores above it | None yet | Open (owner: Matt) | n/a |
| 7 | Pillar sliders for Deposits, Competition and Market Quality not yet tested | None | Open | n/a |
| 8 | Map on the demo machine not yet checked (needs internet; BankUnited IT confirming Azure Maps is enabled) | None | Open | n/a |
| 9 | Rerun finding: `bank_quarter.parquet` differs after a fresh FDIC pull. 1,720 of 240,330 rows differ (0.7%) in 34 Call Report columns, 300 banks by FDIC certificate or RSSD ID (304 counts bank names). Shape is the same. No downstream table and no score changed. Cause confirmed by Austin 11/19: FDIC published revised data on 11/16 (no new quarter); 1,671 of the 1,720 rows differ only in FDIC's domestic office count | None. Austin adds a note to the data dictionary | Explained: FDIC revised past quarters on 11/16; expected, no action | n/a |

### 1c. Later results (to be filled in without changing the format)

| Tester | Date | Commit | U1 | U2 | U3 | U4 | U5 | U6 | U7 | U8 | U9 | U10 | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Keerthika | [ ] | [ ] | | | | | | | | | | | |
| BankUnited user 1 (sponsor test 11/30 to 12/2) | [ ] | [ ] | | | | | | | | | | | |
| BankUnited user 2 | [ ] | [ ] | | | | | | | | | | | |
| BankUnited user 3 | [ ] | [ ] | | | | | | | | | | | |

---

## Part 2. Clean-clone rerun (T63)

A new person followed only the README on a fresh copy of the repository.

- Tester: Bhavana Vasireddy
- Date: 11/18/2026 (clone 6:09 PM; full rebuild started 6:22 PM)
- Commit: `079a2e4782634635939219ab6dfd2cc026f4f08c` (merge of PR #120; main on 11/18). Short form: `079a2e4`
- Tag: `integrated-v0.3` on 079a2e4 (pushed)
- Folder: fresh Windows folder `C:\t63_rerun`, cloned and then `git switch --detach 079a2e4`
- Environment: Microsoft Windows [Version 10.0.26300.9974], Python 3.14.5, git 2.55.0.windows.5, virtual environment `.venv`, packages installed from the pinned versions in `requirements.txt` at this commit
- Exceptions to "README only": I reused my own FDIC, FRED and BEA keys and my name and email from an earlier `.env` (RAW_DATA_DIR cleared); the 30 CRA files came from the Drive folder `BankUnited Pod Data/archive/data-v0.5`, as the README describes.

### 2a. Result against the criteria

| # | Criterion | Expected | Result |
|---|---|---|---|
| 1 | Environment installs from the documented requirements | No errors | Pass |
| 2 | Automated tests | 298 passed | Pass: 298 passed in 57.58 s before the rebuild; 298 passed in 88.27 s again after the rebuild and scoring (11/19) |
| 3 | Data checks, before and after the full rebuild | 167 passed, 0 failed, 16 warnings | Pass both times: 167 / 0 / 16 |
| 4 | Full rebuild from raw data | Finishes; checks pass | Pass: about 33 minutes (6:22 PM to 6:55 PM) |
| 5 | Scoring reproduces the committed outputs | Only run_date changes | Pass: no scores file changed; 17 `*_run.json` files changed by one line each (run_date 2026-11-16 to 2026-11-18) |
| 6 | Charlotte rank | #19, 88.4, 190 ranked | Pass: 190 ranked, Charlotte-Concord-Gastonia #19, score 88.43 |
| 7 | Dashboard | v0.9 is not on main at 079a2e4 | Not applicable to this commit. v0.9 was tested separately in Part 1 |

If PR #122 (QCEW) is merged and rebuilt as data-v0.7, the expected counts are 198 passed, 0 failed, 18 warnings.

### 2b. Step log

The full step log is `docs/handoff/clean_clone_step_log_079a2e4.md` (same PR). Commands in order: `git clone`, `git switch --detach 079a2e4`, `python -m venv .venv`, `.venv\Scripts\activate`, `pip install -r requirements.txt`, `copy .env.example .env`, `python -m pytest`, `python -m src.checks`, `python -m src.run_pipeline`, `python -m src.scoring.run`, then `python -m pytest` again.

### 2c. README gaps still open at 079a2e4 (checked 11/19)

| Gap | Status |
|---|---|
| 1. No scoring-run or dashboard steps in the README, and no link to `dashboard/README.md` | Open. The only README line that mentions scoring is a git status note; "dashboard" does not appear |
| 2 to 5 (Windows `copy`, API keys, raw data folder, `--skip-ingest`) | Merged (PR #127, 11/16) |
| 6. `requirements.txt` has no Jupyter packages | Open |
| 7. `dashboard/README.md` names the wrong file and the wrong score source | Open. It names `..._v0.7.pbix` and the branch `final-score-gate`, and tells users to download `BankUnited_Market_Opportunity_Engine.pbix` |

### 2d. Other notes from the rerun

- An untracked file named "Your registered API key is ....txt" was in the repo folder, dated 11/18/2026 6:16 PM, 61 bytes. It came from a manual download during setup, not from project code. I did not open or commit it. Suggestion: the README should say to keep downloaded key files outside the repository folder.
- A normal run rewrites `data/manifest.csv`, `data/processed/checks_report.md` and the `*_run.json` files, so `git status` is never clean after a run.

### 2e. Second reviewer

| Reviewer | Date | Result |
|---|---|---|
| Austin Edwards | 11/19/2026 | Results hold. He checked the committed scores, strategy ranks, run files, and the 298 tests and 167/0/16 checks on 079a2e4 against his own runs. Not rerun by him: the Windows install and the 33-minute rebuild |
