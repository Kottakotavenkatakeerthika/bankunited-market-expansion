# Charlotte case study and the "Charlotte Test"

**Purpose:** Document the Charlotte market case and define a reproducible historical
back-test.

**Status:** First-release-timing back-test run for June 30, 2025. Because the data tables
contain latest-revised values, this is not an exact historical-vintage reconstruction.

**Gate:** Sponsor request recorded November 6, 2026: the demo must allow the back-test
date to be set.

## Executive summary

The Charlotte Test asks a focused question: **would the market-attractiveness model have
ranked Charlotte as an attractive expansion market using only information available
before BankUnited's entry announcement?**

Using `--as-of 2025-06-30`, Charlotte ranked **16th of 175 complete, size-eligible
metros**, with a score of **88.04/100**. That is a top-9.1% rank position among the
eligible set; pillar-weight sensitivity moved it between ranks 15 and 18. The cutoff is
before the July 2025 entry announcement, and the run correctly does not label Charlotte
as an existing BankUnited market.

The earlier Atlanta and Dallas-Fort Worth comparisons (April 2022 entry, 2021 analysis)
were described as approximately top-decile signals; their exact historical ranks have
not been rerun here. Miami's #2-of-387 result remains an early-run sanity check, not an
entry case.

New York is excluded from this test. BankUnited has had deposits there since 2015, so it
does not represent a clean new-market entry.

## Charlotte case study

Charlotte-Concord-Gastonia, NC-SC (CBSA **16740**) is the pilot market. BankUnited
announced its Charlotte entry in **July 2025**. The intended test compares the market's
pre-entry attractiveness with the model's other eligible U.S. metro areas.

| Item                    | Case definition                                                                                                                                |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Market                  | Charlotte-Concord-Gastonia, NC-SC (CBSA 16740)                                                                                                 |
| Event                   | BankUnited entry announced July 2025                                                                                                           |
| Decision date           | June 30, 2025 (`--as-of 2025-06-30`), selected as the last day before the announcement month because the exact announcement day is unconfirmed |
| Available-data result   | Rank 16 of 175 complete, eligible metros; score 88.04/100                                                                                      |
| Sensitivity             | Rank 15–18 when one pillar weight moves +/-25%                                                                                                 |
| Rank position           | 9.1% from the top of the eligible set                                                                                                          |
| Comparator sanity check | Miami: #2 of 387 in the early result                                                                                                           |
| Not a fair entry test   | New York: deposits predate the test period, present since 2015                                                                                 |

This result uses the 2025-06-30 run's complete-score ranks and the configured 250,000
population floor. The eligible set is therefore not all 387 metros: 175 rankable
metros are complete on all four pillars and meet the floor. The run has 387 total
metros; 112 complete metros are below the floor, and other metros lack a complete
four-pillar score. The result is a retrospective ranking, not evidence that the model
caused or would have caused the entry decision. It does not by itself assess
BankUnited-specific fit, execution, profitability, or post-entry performance.

Reproducible outputs:

- Final scores: [`market_attractiveness_scores.csv`](../outputs/as_of/2025-06-30/final_scores/market_attractiveness_scores.csv)
- Run report (date, available years, settings, and weights): [`market_attractiveness_run.json`](../outputs/as_of/2025-06-30/final_scores/market_attractiveness_run.json)
- Pillar scores and metric catalog: [`pillar_scores/`](../outputs/as_of/2025-06-30/pillar_scores/)

Command used:

```powershell
python -m src.scoring.run --as-of 2025-06-30 --group strategy
```

The decision date is settable with `--as-of YYYY-MM-DD`; this run also refreshed the
strategy scenarios into the same date-specific output tree.

## Historical comparison

| Market            | Entry timing        |        Back-test data basis | Rank signal                         | Interpretation                                         |
| ----------------- | ------------------- | --------------------------: | ----------------------------------- | ------------------------------------------------------ |
| Atlanta           | April 2022          |                        2021 | Approximately top 10%               | Historical comparison                                  |
| Dallas-Fort Worth | April 2022          |                        2021 | Approximately top 10%               | Historical comparison                                  |
| Charlotte         | Announced July 2025 | Data released by 2025-06-30 | #16 of 175 eligible complete metros | First-release-timing back-test; see vintage limitation |
| Miami             | Not an entry case   |          Early-run snapshot | #2 of 387                           | Sanity check only                                      |

The early result shared for this document does not include exact ranks for Atlanta or
Dallas-Fort Worth. Do not infer or publish exact positions from their top-decile
description.

## "Charlotte Test" back-test protocol

### Settable decision date

The back-test uses a date-valued **decision date** (not just a data year). It determines
what evidence was knowable when the decision was made. The scoring runner accepts a
user-settable date with `--as-of YYYY-MM-DD`. The actual announcement day in July 2025
has not been confirmed, so this run uses June 30, 2025, the last day before the
announcement month, as a conservative pre-entry cutoff.

For each selected decision date `D`:

1. Determine source/year availability from
   [`data/reference/release_dates.csv`](../data/reference/release_dates.csv). A source
   year is eligible only when its earliest recorded `release_date` is on or before `D`,
   following the rule documented in the [data dictionary](data_dictionary.md).
2. Apply that availability rule to the underlying inputs **before** calculating growth,
   volatility, metric percentiles, pillar scores, or the final rank. Filtering a
   completed score table after the fact is not sufficient: that table already contains
   metrics and peer percentiles that may depend on later-released data.
3. Keep unavailable values unavailable. Do not substitute later releases or silently
   carry a future year backward. Report data coverage and the number of complete metros
   alongside each result.
4. Recalculate the eligible peer universe and ranks for that date. State whether the
   reported rank is the complete four-pillar rank or an available-data score; do not
   compare ranks with different completeness without making that distinction explicit.
5. Hold scoring weights and other model choices constant across the target and
   comparison markets. Include the weights, selected date, eligible source years, and
   completeness rules in the run record so the test can be reproduced.

### Data available at the selected cutoff

The initial release dates explain which 2024 source years were available at this cutoff:

| Source/year input                   | First release date | Available by July 2025? |
| ----------------------------------- | -----------------: | ----------------------- |
| BLS county unemployment (`laucnty`) |         2025-04-29 | Yes                     |
| QCEW annual by area                 |         2025-06-04 | Yes                     |
| FRED Charlotte unemployment         |         2025-02-05 | Yes                     |
| Census population estimates         |         2025-03-13 | Yes                     |
| FDIC Summary of Deposits            |         2024-09-20 | Yes                     |
| BEA county GDP                      |         2026-02-05 | No                      |
| BEA personal income                 |         2026-02-05 | No                      |
| CRA aggregate data                  |         2025-11-13 | No                      |
| Bank CRA data                       |         2025-11-13 | No                      |

At the June 30 cutoff, the run uses 2024 SOD, QCEW, unemployment, and PEP data, but
2023 BEA GDP and personal income, 2023 CBP, and June 2024 Call Reports. The 2024 SOD
release date shown above is September 2024, so it was available by June 2025.

The release ledger supplies first-release timing, while modeling tables contain the
latest revised values. Therefore, this protocol is a **first-release-timing back-test**,
not a full vintage reconstruction of the exact values known on each date. Any
presentation should disclose this limitation.

### Required output for each date

For Charlotte and each comparison market, save and present:

- decision date and entry/event date;
- rank, score, peer-universe size, and percentile (with ties handled consistently);
- completeness status, available pillar/metric coverage, and any excluded inputs;
- eligible data years by source, plus the release-date rule used;
- model weights and a reference to the reproducible run output.

For the top-decile claim, report the exact rank and the number of metros eligible for
that same rank calculation. For example, “top 10%” is not adequately specified without
the denominator and completeness rule. Keep the Miami #2-of-387 result labeled as a
sanity check, not as evidence about entry selection.

## Demo readiness and acceptance criteria

The current scoring runner supports `--as-of`, rebuilds pillar metrics using the
release-date ledger, and writes runs under `outputs/as_of/<date>/` so they do not
overwrite current scores. The run report records the selected date and latest eligible
data years. The Charlotte result above is therefore an executed first-release-timing
back-test, not just the earlier 2024 snapshot.

The November 20, 2026 demo is ready to call the Charlotte Test reproducible when:

1. The user can set the decision date using `--as-of YYYY-MM-DD`.
2. The date gates source-year inputs using the release ledger before pillar metrics and
   rankings are recomputed.
3. No post-date source-year is used, including in growth windows, percentiles, or the
   peer universe.
4. The result shows Charlotte's exact rank and denominator, completeness, score, and
   the applicable data-availability disclosure.
5. Re-running with the same date, weights, and data produces the same result.

The date-controlled run is reproducible with the command above. It remains a
first-release-timing test: processed tables contain the latest revised values, not the
exact vintage published on June 30, 2025. Confirm the announcement day before using a
different cutoff as the precise decision date.
