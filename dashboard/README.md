# BankUnited Market Opportunity Engine – Power BI Dashboard

Interactive Power BI dashboard for the BankUnited market-expansion project (DSBA 6390 Project Practicum, UNC Charlotte). It ranks U.S. metropolitan areas on **Market Attractiveness** for a commercial-first bank like BankUnited, and shows how every score is built from public data.

**Status:** v1.0, the final release for the BankUnited handoff (November 2026), on scoring v0.5 (PR #140, merged to `main`) and data-v0.7. Market Attractiveness score with filters for population, distance and industry fit; a combined Fit score is not built.

## Files

| File | What it is |
| --- | --- |
| `BankUnited_Market_Opportunity_Engine_v1.0.pbix` | The Power BI report with its data. Open in Power BI Desktop. |
| `README.md` | This file. |

## Objectives

1. Rank U.S. metros on how attractive they are for a commercial-first bank expansion.
2. Make every score explainable: each rank can be traced to the pillar scores and measures behind it.
3. Test how stable the ranking is under different strategy weights.
4. Run a pre-entry check on Charlotte: using data through 2024, would the engine have flagged Charlotte before BankUnited entered it in July 2025?

## Dataset

All public data, from the team's data release **data-v0.7** (data through 2024; v0.7 adds two BLS QCEW industry tables, and the tables the scores use are unchanged from v0.6):

- FDIC Summary of Deposits (branch deposits, June 2024)
- FFIEC Call Reports (bank loans and deposits)
- U.S. Census Bureau: County Business Patterns and Population Estimates
- BEA: GDP and personal income
- BLS: QCEW wages and LAUS unemployment
- Census Gazetteer: metro coordinates (distance filter and map)

Unit of analysis: metropolitan statistical areas (OMB 2023 delineation), 387 metros in the 50 states and DC. No BankUnited internal data is used.

**Scores:** scoring v0.5 by Matt D'Allaird (PR #140, run 11/24/2026; local-lender growth cap set to 191%, the fifth-highest observed value, as decided with BankUnited): `outputs/final_scores/market_attractiveness_scores.csv`, the strategy files in `outputs/final_scores/strategy/` and the robustness checks in `outputs/final_scores/scenario/`.
**Measure detail:** `outputs/pillar_scores/pillar1_scores.csv` to `pillar4_scores.csv` and `metric_catalog.csv` from the same run.

**Verification:** the data inside the dashboard was compared with these output files on `main` after PR #140 merged (11/25/2026), and every file matched exactly.

## How the score works

1. Each of 27 measures is converted to a percentile (0–100) among metros, oriented so higher is always more attractive.
2. Each pillar score is the weighted average of its measures' percentiles.
3. Each pillar score is converted to a percentile among metros.
4. The Attractiveness Score is the weighted average of the four pillar percentiles (25% each at baseline).

A metro is ranked only when all four pillars are complete and its population is at least 250,000 (the size floor): **190 ranked**. 191 metros have complete data but are below the floor; they keep their score but are not ranked. 6 metros have incomplete data (5 Connecticut metros and Eagle Pass, TX). The filters for distance to BankUnited's markets, industry fit and excluding current markets work the same way and are off by default. Industry fit is each metro's share of jobs in 11 commercial-banking industries, filtered as a percentile (0–100, the default filter) or, as an option, as the raw percent of jobs. No missing value is filled with zero. Percentiles are calculated across all metros before the floor is applied, so the floor changes ranks, not scores. In Pillar 1, local-lender growth is set to the 50th percentile for the 61 metros with no local-lender growth figure (55 have no local lender).

Deposits exclude bookings at main offices and home-banking offices, so headquarters deposits don't inflate a market (for example, Bank of America and Truist in Charlotte).

| Pillar | Question | Measures | Owner |
| --- | --- | --- | --- |
| P1 Commercial Lending Opportunity | Is there enough business borrowing demand to build a commercial loan book? | 6 | Matt D'Allaird |
| P2 Deposit & Treasury Opportunity | Is there a business deposit and treasury pool BankUnited could realistically win? | 8 | Matt D'Allaird |
| P3 Competition & Entry Window | How hard is it to win deposit share, and is there an opening? | 5 | Jainesh Lad |
| P4 Market Quality & Durability | Will the market hold up through a cycle? | 8 | Evan De Guzman |

## Dashboard pages

| Page | What it shows |
| --- | --- |
| Overview | Full ranking with green-to-red colors, the selected metro's rank, score and scenario range, BankUnited's markets, the filters in use, and pillar-weight sliders (0–100) that re-rank metros live. The weights entered are rescaled to 100%: the header shows their total, and four cards show each pillar's share of the score. |
| Map | Every metro on an Azure Map (needs internet): color = score, size = population, BankUnited's markets in navy; click a metro for its details. |
| Market Profile | For any metro: score, rank, scenario range, distance to BankUnited, industry-fit jobs, how the score adds up, all 27 measures, strongest and weakest measures. Metros with partial data are labeled "Partial data" and are not ranked. |
| Compare | Two or more metros side by side: rank, score, pillar percentiles, distance, industry-fit jobs (% and percentile) and all 27 measures. |
| Rank by Measure | All metros ranked on any one of the 27 measures, with BankUnited's markets. The rank counts metros that pass the current filters and have data for that measure (at the defaults, the 190 ranked plus the 5 Connecticut metros); percentiles compare all metros of every size. |
| Lending, Deposits, Competition, Market Quality | One page per pillar: pillar ranking, the selected metro's measures, key terms, data notes, owner, and measure-weight sliders that re-score that pillar on its page. |
| Scenarios | Ranks under the strategy scenarios (Balanced, C&I-led, CRE-led, Deposit-led, Adjacency within 500 miles, Emerging market) and the robustness checks. |
| Filters | Population minimum (default 250,000), distance to BankUnited's markets, industry fit (percentile, default 0; raw percent of jobs as an option) and excluding current markets; shows which metros and BankUnited markets drop out and why. These filters also apply on Overview, Map and Rank by Measure. |
| Method | How the engine works, the four pillars, filters, coverage, key modeling choices and limitations. |
| Pillar Guide | For each pillar: definition, lending segments (C&I, CRE, middle market), measures and weights, how it is scored and its data sources. |

## Key insights

- **Charlotte ranks 18th of 190** (score 88.8). It stays 15th–18th across the five weight scenarios (15th under Emerging market, 16th under Adjacency's 500-mile filter) and 16th–19th when any one pillar weight moves ±25%.
- Charlotte's strongest pillar is **Market Quality** (13th of 382). Its weakest is **Competition** (82nd of 382): deposits are concentrated in a few holding companies, although the leaders lost share from 2021 to 2024.
- **Seven of BankUnited's 13 current markets rank in the top 20**: Sarasota (7th), Cape Coral (12th), Atlanta (13th), Orlando (15th), Tampa (17th), Charlotte (18th) and Naples (19th).
- Top five at baseline: Austin, Raleigh, Nashville, Phoenix, Indianapolis.
- **New York (151st) and Chicago (96th) rank lower than their size suggests.** The score rewards growth, stability and room to compete, not size alone: only 2 of the 27 measures (middle-market establishments and total wage bill) measure scale, and both metros score near the top on them. New York is held back by slow commercial loan and middle-market growth (Lending: 314th of 381) and by volatile unemployment (Market Quality: 279th of 382). Chicago's weakest pillar is Market Quality (324th of 382): high and volatile unemployment, and slow population and GDP growth.
- Sebastian–Vero Beach (population 171,560) is the one BankUnited market below the 250,000 floor, so it is scored but not ranked.

## Limitations

- Fit & Feasibility is available as filters (distance, industry fit); a combined Fit score is not built.
- Measure weights on a pillar page change that page only; the overall ranking uses the official measure weights.
- Pillar-weight sliders cannot adjust one another; the weights entered are rescaled to 100%, the same rule as the scoring code.
- The Map uses Azure Maps, which needs internet and a Power BI sign-in, and can be turned off by an organization's Power BI settings.
- Weights are not fitted to outcomes. BankUnited asked for open 0–100 weights with no guardrails (11/17), and the six scenario weight sets are starting points.
- The Charlotte result is a pre-entry ranking test, not proof that the entry will succeed.

## How to open

1. Install Power BI Desktop (Windows, free).
2. Download BankUnited_Market_Opportunity_Engine_v1.0.pbix and open it. The data is included, so no data connection is needed. The Map page needs internet and a Power BI sign-in (it uses Azure Maps); every other page works without signing in. The file opens at the baseline: pillar weights 25 each, population minimum 250,000, all other filters off.
3. Start on the Overview page and use the navigation bar at the top (in Power BI Desktop, hold Ctrl and click). Pick a metro in any "Selected metro" dropdown (type to search) and the other pages follow. Change pillar weights on Overview (they also update the Map and Filters) and the filters on the Filters page (they also update Overview, the Map and Rank by Measure). Market Profile, Compare, the pillar pages and Scenarios show the official baseline.
4. To reset, set all four weights to 25 and the Filters page back to its defaults, or close the file without saving and reopen it.

## Project Team and Contributions

DSBA 6390 Project Practicum, University of North Carolina at Charlotte, with project sponsor BankUnited.

| Team Member | Project Role |
| --- | --- |
| Akayiah Bell | PM Liaison |
| Venkata Keerthika Kottakota | Technical Integration Lead |
| Sonia G. Chavelas Gonzalez | Dashboard & Analytics Engineer |
| Bhavana Vasireddy | Data Engineer |
| Austin Edwards | Data Engineer |
| Matt D'Allaird | Machine Learning |
| Jainesh Lad | Machine Learning |
| Evan De Guzman | Machine Learning |
| Varun Sawant | Documentation Lead |
