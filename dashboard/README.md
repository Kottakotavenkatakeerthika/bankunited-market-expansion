# BankUnited Market Opportunity Engine – Power BI Dashboard

Interactive Power BI dashboard for the BankUnited market-expansion project (DSBA 6390 Project Practicum, UNC Charlotte). It ranks U.S. metropolitan areas on **Market Attractiveness** for a commercial-first bank like BankUnited, and shows how every score is built from public data.

**Status:** MVP for the November 6, 2026 MVP Gate. Market Attractiveness only; the Fit & Feasibility score is not yet applied.

## Files

| File | What it is |
| --- | --- |
| `BankUnited_Market_Opportunity_Engine_v0.7.pbix` | The Power BI report with its data. Open in Power BI Desktop. |
| `README.md` | This file. |

## Objectives

1. Rank U.S. metros on how attractive they are for a commercial-first bank expansion.
2. Make every score explainable: each rank can be traced to the pillar scores and measures behind it.
3. Test how stable the ranking is under different strategy weights.
4. Run a pre-entry check on Charlotte: using data through 2024, would the engine have flagged Charlotte before BankUnited entered it in July 2025?

## Dataset

All public data, from the team's data release **data-v0.5** (data through 2024):

- FDIC Summary of Deposits (branch deposits, June 2024)
- FFIEC Call Reports (bank loans and deposits)
- U.S. Census Bureau: County Business Patterns and Population Estimates
- BEA: GDP and personal income
- BLS: QCEW wages and LAUS unemployment

Unit of analysis: metropolitan statistical areas (OMB 2023 delineation), 387 metros in the 50 states and DC. No BankUnited internal data is used.

**Scores:** the final-score output v0.2 (`outputs/final_scores/market_attractiveness_scores.csv` and the strategy scenario files, branch `final-score-gate`, 11/4/2026).
**Measure detail:** the four pillar notebooks (11/4/2026 versions).

## How the score works

1. Each of 27 measures is converted to a percentile (0–100) among metros, oriented so higher is always more attractive.
2. Each pillar score is the weighted average of its measures' percentiles.
3. Each pillar score is converted to a percentile among metros.
4. The Attractiveness Score is the weighted average of the four pillar percentiles (25% each at baseline).

A metro is ranked only when all four pillars are complete: **287 ranked**, 100 not ranked. Of those 100, 95 have no published Census industry mix and 5 Connecticut metros lack base-year data. No missing value is filled with zero. In Pillar 1, local-lender growth is set to the 50th percentile for the 61 metros with no local lender.

Deposits exclude bookings at main offices and home-banking offices, so headquarters deposits don't inflate a market (for example, Bank of America and Truist in Charlotte).

| Pillar | Question | Measures | Owner |
| --- | --- | --- | --- |
| P1 Commercial Lending Opportunity | Is there enough business borrowing demand to build a commercial loan book? | 6 | Matt D'Allaird |
| P2 Deposit & Treasury Opportunity | Is there a business deposit and treasury pool BankUnited could realistically win? | 8 | Matt D'Allaird |
| P3 Competition & Entry Window | How hard is it to win deposit share, and is there an opening? | 5 | Jainesh Lad |
| P4 Market Quality & Durability | Will the market hold up through a cycle? | 8 | Evan de Guzman |

## Dashboard pages

| Page | What it shows |
| --- | --- |
| Summary | Full ranking, Charlotte's rank and score, BankUnited's markets, and pillar-weight sliders that re-rank metros live |
| Market Profile | For any metro: score, rank, scenario range, how the score adds up, and all 27 measures |
| P1–P4 | One page per pillar: pillar ranking, the selected metro's measures, data notes, owner |
| Strategic Scenarios | Ranks under five strategy weight sets (Balanced, C&I-led, CRE-led, Deposit-led, Emerging market) |
| Method & Status | Method, data sources, pillar owners and open decisions |

## Key insights

- **Charlotte ranks 16th of 287** (score 88.4). It stays 14th–16th across the five strategy scenarios and 14th–19th when any single measure weight moves ±25%.
- Charlotte's strongest pillar is **Market Quality** (13th of 287), driven by net migration and population growth. Its weakest is **Competition** (80th of 382): deposits are concentrated in a few holding companies, although the leaders lost share from 2021 to 2024.
- **Eight of BankUnited's 13 current markets rank in the top 20**, including Sarasota (8th), Cape Coral (11th), Atlanta (12th) and Naples (14th).
- Top five at baseline: Austin, Raleigh, Phoenix, Nashville, Indianapolis.
- Unranked metros are mostly small: 81 of the 100 have fewer than 250,000 people.

## Limitations

- Market Attractiveness only; Fit & Feasibility (fit with BankUnited's lending mix, verticals and talent) is not built yet.
- Weights are starting hypotheses, not fitted to outcomes; approved ranges are a sponsor decision.
- "Lower competition is better" in Pillar 3 is a working assumption to be confirmed with BankUnited.
- The Charlotte result is a pre-entry ranking test, not proof that the entry will succeed.

## How to open

1. Install Power BI Desktop (Windows, free).
2. Download `BankUnited_Market_Opportunity_Engine.pbix` and open it. The data is included; no connection or sign-in is needed.
3. Start on the Summary page. Use the sliders to change pillar weights, and the metro selector on Market Profile to explore any metro.

## Team

DSBA 6390 Project Practicum, UNC Charlotte, with sponsor BankUnited.
Dashboard and integration: Sonia Gabriela Chavelas Gonzalez. Pillar models: Matt D'Allaird (P1, P2), Jainesh Lad (P3), Evan de Guzman (P4).
