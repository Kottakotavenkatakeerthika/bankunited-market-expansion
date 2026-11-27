# How Our Data Works: passages changed for scoring v0.4 (November 17, 2026)

These replace the matching passages in How Our Data Works (data-v0.6, November 16). Scoring v0.4 is PR #128, merged into main on November 16 as commit 4145dfa. The data is unchanged: still data-v0.6, with 167 checks passed, 0 failed and 16 warnings. Everything not listed here stays as it is.

Decision-log entries are given whole, so each one can replace the old entry in full.

## Data decision log for T65 (intro)

These are the 15 rules the data layer applies before any score is computed, in T65's format. Figures are from data-v0.6 (main at commit 231281b) unless a date says otherwise, and score figures are from scoring v0.4 (main at 4145dfa, November 17); the fact-check section at the end shows how each was checked. Pillar weights, metric choices, the size floor and the Fit filters belong in the ML pod's entries.

## D2 Missing stays missing

**Rule:** A value the source doesn't report stays empty, never 0. Zeros a source uses to mean "not reported" are emptied too.

**Why:** A 0 reads as no activity and would drag a metro's or a bank's score down.

**Decided by:** Data engineering rule in the data dictionary; the last zero fixes shipped in data-v0.5 on 10/28 (B14).

**Alternatives:** Filling with 0, or estimating gaps in the data. Estimating is left to the scoring, which counts a missing local-lender growth as the 50th percentile. Since scoring v0.4 it also leaves a sector Census doesn't publish out of the industry HHI. The tables keep those cells empty; within that one measure, leaving a sector out works like counting it as 0.

**If it changed:** Zero-filling would score metros with gaps, such as Connecticut's, as weak instead of leaving them unranked.

**Limitation:** Every model has to handle blanks on purpose; 6 metros have a partial score in scoring v0.4: Connecticut's 5 and Eagle Pass, TX. Examples: Connecticut's BEA values before 2024, uninsured deposits at banks under $1 billion.

## D4 Withheld and unpublished cells

**Rule:** Cells Census or BLS withhold are left out of sums, not counted as 0. Exceptions: a withheld size class counts as 0 in the 20-to-249-employee count, and two withheld county-years in Kahului-Wailuku (2015 and 2016) read as 0.

**Why:** A withheld cell hides a real value, and 0 would understate it.

**Decided by:** Bhavana in the CBP and CRE builds (PRs #2 and #13), with Austin's reviews; the QCEW rule in PR #122, agreed 11/12.

**Alternatives:** Counting withheld cells as 0; estimating the hidden value.

**If it changed:** The 20-to-249 count runs short by up to 2 per withheld cell. Sector jobs and payroll for 2015 to 2017 run low where a county withheld them.

**Limitation:** From 2017, CBP omits county-sector rows under 3 establishments. In 2023, 95 metros lack at least one sector (mining in 69). Since scoring v0.4 (#128), their industry HHI uses the sectors Census publishes, which hold all but at most about 1% of their jobs; setting `[options] industry_hhi_missing_sectors` to `"blank"` restores the old rule.

## D14 A map point for every metro

**Rule:** Each metro's Census Gazetteer internal point (2026 file), the same in every year.

**Why:** One free file covers all 393 metros for the Fit & Feasibility distance filter.

**Decided by:** Built by Austin at Matt's and Akayiah's request, 11/12 (T80, data-v0.6); the ML pod accepted internal points on 11/14.

**Alternatives:** 2020 population centers, which can't be matched to Connecticut's new regions.

**If it changed:** Points sit a median 6.7 miles from population centers, over 50 for 7 metros. Two metros that would otherwise rank sit just outside ML's 500-mile filter: Detroit (503 miles) and El Paso (508).

**Limitation:** A geographic center, not where people live; distances are straight-line. The distance filter is in main since #128 (11/16): off in the baseline, 500 miles in the Adjacency scenario.

## D15 BankUnited's own footprint

**Rule:** The `bankunited_` columns come from the SOD offices and CRA loans of BankUnited, N.A. (RSSD 3938186).

**Why:** Both are public by metro and year from 2015.

**Decided by:** Austin (PR #91, data-v0.5).

**Alternatives:** BankUnited's own announcements, which the back-test needs for entry dates anyway.

**If it changed:** The Fit filters (#128) count 13 BankUnited markets: the 10 branch markets in the 2024 deposit survey plus the office-only Atlanta, Charlotte and Houston, added by hand. An as-of run leaves out Atlanta before 4/7/2022 and Charlotte before 7/17/2025.

**Limitation:** An office with no deposits or few CRA loans doesn't show: the Atlanta corporate banking office, opened April 2022, isn't in SOD through June 2024.

## Known limits: the first item

- **190 of the 393 metros are ranked.** A metro is ranked only when all four pillars, the groups of measures the score averages, are complete and it has at least 250,000 people. That floor is the default BankUnited chose at the November 6 gate, and 0 turns it off. 381 metros are complete, and 191 of them fall under the floor. Connecticut's 5 (explained next) and Eagle Pass, Texas, have partial scores, and Puerto Rico's 6 aren't scored, since BEA, County Business Patterns and the population estimates don't cover them. Where Census leaves out an industry sector (95 metros, mining in 69), the industry-concentration measure uses the sectors it publishes. Charlotte ranks 19th of 190.

## How we know it's right: the tests item

- **Tests, 297 of them.** These are small programs that run the code on known inputs and confirm the output. They cover each source's download step, the schema checks, the release dates and the scoring.

## Glossary: Test

- **Test:** a small program that runs part of the code on known inputs and confirms the output. There are 297.

## Fact-check: the opening line and the changed rows

Every figure in this doc was checked against main at commit 231281b (data-v0.6) on November 16; the score figures, the test count and the rows marked November 17 were rechecked against main at 4145dfa (scoring v0.4) on November 17.

| Figure | Value | How checked |
|:--|:--|:--|
| Tests | 297 passed | Ran: pytest on main at 4145dfa, November 17, Python 3.13.18 with the pinned packages |
| Data checks | 167 passed, 0 failed, 16 warnings | Ran: the checks on the committed tables, without rewriting the report; rerun on 4145dfa on November 17 with the same result |
| Ranks | 190 ranked; 381 complete, 191 of them under 250,000; 6 partial; Puerto Rico's 6 not scored; Charlotte 19th | Ran: `python -m src.scoring.run` on main at 4145dfa, November 17, which reproduces the committed scores; with the old blank rule the same code reproduces the pre-#128 scores (176 ranked, Charlotte 17th) |
| Industry sectors missing | 95 metros (mining 69, agriculture 25, utilities 11, management of companies 4); the sectors left out hold at most 1.02% of a metro's jobs (median 0.07%) | Ran: `msa_naics_year` for 2023 against `msa_year`'s all-industry totals, November 17 |
| ML's 500-mile filter | Detroit 503.1 miles (from New York), El Paso 508.1 (from Dallas); 69 metros kept from ranking | Ran: a separate distance calculation on the Gazetteer points, matching the Adjacency output on main at 4145dfa, November 17 |
| BankUnited markets in the Fit filters | 13: the 10 branch markets in SOD 2024 plus the Atlanta, Charlotte and Houston offices | Ran: `msa_year` for 2024; Read: `src/market_attractiveness.py` for the offices and their entry dates, November 17 |
