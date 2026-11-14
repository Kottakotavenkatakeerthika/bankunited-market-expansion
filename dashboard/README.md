# BankUnited Market Opportunity Engine – Power BI Dashboard

Interactive Power BI dashboard for the BankUnited market-expansion project (DSBA 6390 Project Practicum, UNC Charlotte). It ranks U.S. metropolitan areas on **Market Attractiveness** for a commercial-first bank like BankUnited, and shows how every score is built from public data.

**Status:** v0.8, built for the November 20, 2026 Full Functionality Demo on scoring v0.3. Market Attractiveness only; the Fit & Feasibility score is not yet applied.

## Files

| File | What it is |
| --- | --- |
| `BankUnited_Market_Opportunity_Engine_v0.8.pbix` | The Power BI report with its data. Open in Power BI Desktop. |
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

**Scores:** scoring v0.3 by Matt D'Allaird (PR #119, run 11/12/2026): `outputs/final_scores/market_attractiveness_scores.csv`, the strategy scenario files in `outputs/final_scores/strategy/`, and `scenario_bankunited_ranks_strategy.csv`.
**Measure detail:** `pillar1_scores.csv` to `pillar4_scores.csv` and `metric_catalog.csv` from the same run.

## How the score works

1. Each of 27 measures is converted to a percentile (0–100) among metros, oriented so higher is always more attractive.
2. Each pillar score is the weighted average of its measures' percentiles.
3. Each pillar score is converted to a percentile among metros.
4. The Attractiveness Score is the weighted average of the four pillar percentiles (25% each at baseline).

A metro is ranked only when all four pillars are complete **and** its population is at least 250,000 (the size floor in scoring v0.3): **176 ranked**. 111 metros have complete data but are below the floor; they keep their score but are not ranked. 100 metros have incomplete data, all of them in Pillar 4. No missing value is filled with zero. Percentiles are calculated across all metros before the floor is applied, so the floor changes ranks, not scores. In Pillar 1, local-lender growth is set to the 50th percentile for the 61 metros with no local lender.

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
| Summary | Full ranking, Charlotte's rank and score, BankUnited's markets, pillar-weight sliders and the size floor setting, which re-rank metros live |
| Market Profile | For any metro: score, rank, scenario range, how the score adds up, all 27 measures, and the top 5 drivers up and down |
| P1–P4 | One page per pillar: pillar ranking, the selected metro's measures, data notes, owner |
| Scenarios | Ranks under five strategy weight sets (Balanced, C&I-led, CRE-led, Deposit-led, Emerging market) |
| Compare Metros | Two or more metros side by side: rank, score, pillar percentiles and all 27 measures |
| Rank by Measure | All metros ranked on any one of the 27 measures, with BankUnited's markets |
| Size Floor | Minimum population setting (default 250,000, "Off" ranks every complete metro); shows which metros and BankUnited markets drop out |
| Method & Status | Method, data sources, pillar owners and open decisions |

## Key insights

- **Charlotte ranks 17th of 176** (score 88.2). It stays 14th–18th across the five strategy scenarios and 15th–19th when any one pillar weight moves ±25%.
- Charlotte's strongest pillar is **Market Quality** (13th of 287). Its weakest is **Competition** (82nd of 382): deposits are concentrated in a few holding companies, although the leaders lost share from 2021 to 2024.
- **Eight of BankUnited's 13 current markets rank in the top 20**, including Sarasota (8th), Cape Coral (11th), Atlanta (12th) and Naples (14th).
- Top five at baseline: Austin, Raleigh, Phoenix, Nashville, Indianapolis.
- Sebastian–Vero Beach (population 171,560) is the one BankUnited market below the 250,000 floor, so it is scored but not ranked.

## Limitations

- Market Attractiveness only; Fit & Feasibility (fit with BankUnited's lending mix, verticals and talent) is not built yet.
- Weights are starting hypotheses, not fitted to outcomes; approved ranges are a sponsor decision.
- "Lower competition is better" in Pillar 3 is a working assumption to be confirmed with BankUnited.
- The Charlotte result is a pre-entry ranking test, not proof that the entry will succeed.

## How to open

1. Install Power BI Desktop (Windows, free).
2. Download `BankUnited_Market_Opportunity_Engine_v0.8.pbix` and open it. The data is included; no connection or sign-in is needed.
3. Start on the Summary page. Use the sliders to change pillar weights, the size floor to change which metros are ranked, and the metro selector on Market Profile to explore any metro.

## Team

DSBA 6390 Project Practicum, UNC Charlotte, with sponsor BankUnited.
Dashboard and integration: Sonia Gabriela Chavelas Gonzalez. Pillar models: Matt D'Allaird (P1, P2), Jainesh Lad (P3), Evan de Guzman (P4).
