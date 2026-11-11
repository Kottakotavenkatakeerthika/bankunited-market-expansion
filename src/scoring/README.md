# Scoring: Market Attractiveness

This folder (`src/scoring/`) holds the scoring pipeline: one script per pillar that builds its metrics, the
engine that turns them into scores, and the one command that runs everything. The final combination and the
scenario comparisons are in `src/market_attractiveness.py` and `src/compare_scenarios.py`; the read-only
pillar reports are in `notebooks/`. This README covers the whole scoring section: how to run it, how it works,
how to change it, and what comes out.

Market Attractiveness answers *"is this a good commercial banking market?"* It does not yet answer *"is it a
good market for BankUnited?"*: the Fit & Feasibility gate (`src/bankunited_fit.py`) is still to be built.

---

## 1. Quick start

From the repo root, with the project environment active:

```bash
python -m src.scoring.run                      # build every metric, then score the baseline and all scenarios
python -m pytest -q                            # check everything still lines up
```

That one command does everything: it builds the metrics from `data/processed/`, writes the pillar files, and
runs the baseline plus every scenario, writing results to `outputs/`. It takes about a minute.

Other ways to run it:

```bash
python -m src.scoring.run --group strategy     # baseline + the strategy scenarios only
python -m src.scoring.run --pillars-only       # metrics and pillar files only, no final scores
python -m src.scoring.run --as-of 2025-06-30   # point in time: only data released by that date (section 8)

python -m src.market_attractiveness                                       # baseline final score only
python -m src.market_attractiveness --weights weights/strategy/cre_led.toml
python -m src.market_attractiveness --show-weights                        # print effective weights and stop
python -m src.market_attractiveness --min-population 250000               # try a size floor without editing files
python -m src.market_attractiveness --normalize none                      # average raw pillar scores (method check)
```

To look at a pillar, open its report in `notebooks/` and run all cells.

---

## 2. Where things are

| Path | What it holds | Edit it to… |
|---|---|---|
| `src/scoring/pillar1.py` … `pillar4.py` | Each pillar's metrics: how every raw value is built, its direction (higher or lower is better), its label, period and source | add, remove or redefine a metric |
| `src/scoring/common.py` | Shared pieces: the metric definition, the percentile rule, growth and ratio helpers, the 387-metro universe | rarely; it must stay identical for all pillars |
| `src/scoring/engine.py` | Pillar scores, the pillar files and the metric catalog | rarely |
| `src/scoring/asof.py` | Point-in-time settings for `--as-of` | rarely |
| `src/scoring/run.py` | The one command; also builds the composite metric (competition × growth) | rarely |
| `src/market_attractiveness.py` | Combines the pillars into the final score and ranks metros | rarely |
| `src/compare_scenarios.py` | Runs every scenario and writes the comparison tables | rarely |
| `config/settings.toml` | **How metrics are built**: years, windows, thresholds, the HQ-deposit treatment, the competition × growth corners | change a year, window, threshold or corner |
| `weights/baseline.toml` | **How much each metric and pillar counts**, the size floor, gap filling | change a weight or the size floor |
| `weights/strategy/*.toml` | The six Phase 1 strategy scenarios | change or add a strategy scenario |
| `weights/scenarios/*.toml` | Sensitivity tests | change or add a sensitivity test |
| `notebooks/pillar*.ipynb` | Read-only reports, one per pillar | nothing; they only display results |
| `outputs/pillar_scores/` | Pillar files and the metric catalog (written by each run) | nothing |
| `outputs/final_scores/` | The baseline final score (written by each run) | nothing |
| `outputs/final_scores/strategy/`, `scenario/` | Each strategy and sensitivity scenario, and that group's comparison tables | nothing |
| `outputs/as_of/<date>/` | Point-in-time runs, same layout (written by `--as-of`; not committed) | nothing |

**Rule of thumb:** *how a metric is built* lives in the pillar script and `config/settings.toml`; *how much it
counts* lives in the weights files. A metric with weight 0 is still built and shown everywhere, just not
scored.

---

## 3. How a score is built

```
data/processed/  ──►  pillar scripts  ──►  raw metric values (every metric, 387 metros)
                                                │
                       composite metrics  ◄─────┘   competition × growth uses Pillars 1, 2 and 4
                                                │
                       metric percentiles   0–100, oriented so 100 is always the most attractive
                                                │
                       pillar scores         weighted mean of the pillar's metric percentiles
                                                │
                       pillar percentiles    each pillar score ranked 0–100 among the metros
                                                │
                       final score           weighted mean of the four pillar percentiles
                                                │
                       rank                  complete metros at or above the size floor only
```

**Step by step:**

1. **Universe.** Every pillar uses the same 387 metros: the metropolitan areas in the 50 states and DC. Puerto
   Rico is not scored.
2. **Metric percentiles.** Each metric is ranked among the metros that have a value:
   `100 × (average rank − 1) / (count − 1)`. "Lower is better" metrics are ranked in reverse, so 100 is always
   the most attractive end.
3. **Pillar score.** The weighted mean of the pillar's metric percentiles. The **complete** score needs every
   weighted metric; the **available-data** score rescales the weights over the metrics a metro has.
4. **Gap filling.** Metrics listed under `[fill]` in the weights file count as the 50th percentile where a
   metro has no value. In the baseline, these are Pillar 1's two local-lender metrics, filled for the 61 metros
   with no local lender.
5. **Pillar percentile.** Each pillar score becomes a percentile among the metros that have it, so a 25%
   weight gives a pillar 25% of the influence, whatever the spread of its scores. A pillar's complete score is
   used where it exists, otherwise its available-data score if that covers at least half the pillar's weight.
6. **Final score.** The weighted mean of the four pillar percentiles. The four `pillarN_points` columns add up
   to it.
7. **Rank.** Only metros complete on all four pillars, and at or above the size floor, are ranked.
8. **Rank range.** `best_rank` and `worst_rank` are the best and worst rank when one pillar weight at a time
   moves up or down by a quarter (25% → 18.75% or 31.25%).

**Booked deposits.** Deposits booked at main offices and home-banking offices don't reflect local business
(for example, BofA's and Truist's national deposits booked in Charlotte), so they're removed from every
deposit amount used in scoring. The one deliberate exception: Pillar 1 decides whether a bank is a *local
lender* using deposits as reported, because a community bank's headquarters does hold local deposits. Branch
counts are not adjusted for home-banking offices; SOD doesn't flag them.

---

## 4. The metrics

Weights are within the pillar. Each pillar is 25% of the final score in the baseline, so a metric's share of
the final score is a quarter of its pillar weight. All 31 metrics, with coverage, are in
`outputs/pillar_scores/metric_catalog.csv`.

### Pillar 1: Commercial lending

| Metric | Weight | Direction | What it is |
|---|---|---|---|
| `allocated_loan_growth` | 20% | Higher | Every bank's C&I + CRE, spread to metros by its share of deposits not booked at main or home-banking offices; growth June 2019–June 2024 |
| `mm_establishments` | 20% | Higher | Establishments with 20–249 employees, CBP 2023 |
| `mm_growth` | 20% | Higher | Growth in that count, 2018–2023 |
| `cre_payroll_growth` | 20% | Higher | Payroll growth in real estate (NAICS 531) plus nonresidential construction, 2018–2023 |
| `local_ci_growth` | 10% | Higher | C&I growth at banks with at least 50% of their deposits in the metro, 2019–2024; each bank capped at 25% a year |
| `local_cre_growth` | 10% | Higher | The same, for CRE |
| `local_loans_to_deposits` | 0% | Higher | Local lenders' commercial loans ÷ deposits (computed, not scored) |
| `mm_share` | 0% | Higher | Middle-market share of establishments (computed, not scored) |

### Pillar 2: Deposits and treasury

| Metric | Weight | Direction | What it is |
|---|---|---|---|
| `deposits_per_capita` | 12.5% | Higher | SOD deposits without booked offices, per resident, June 2024 |
| `deposit_growth` | 12.5% | Higher | Their growth, 2019–2024 |
| `deposits_per_branch` | 12.5% | Higher | Those deposits per branch (main offices left out of the branch count) |
| `wage_bill` | 12.5% | Higher | QCEW total wages, 2024 |
| `wage_bill_growth` | 12.5% | Higher | Its growth, 2019–2024 |
| `payroll_per_establishment` | 12.5% | Higher | CBP payroll ÷ establishments, 2023 |
| `income_per_capita` | 12.5% | Higher | BEA personal income per resident, 2024 |
| `income_growth` | 12.5% | Higher | Its growth, 2019–2024 |
| `incumbent_nib_share` | 0% | Higher | Incumbent banks' bank-wide non-interest-bearing share, weighted by local deposits (not scored) |
| `incumbent_uninsured_share` | 0% | Higher | The same, for uninsured deposits (not scored) |

### Pillar 3: Competition and entry windows

| Metric | Weight | Direction | What it is |
|---|---|---|---|
| `deposit_hhi` (P3-01) | 20% | Lower | Deposit concentration across holding companies |
| `top3_share` (P3-02) | 20% | Lower | Share of the three largest holding companies |
| `competitors_per_billion` (P3-03) | 20% | Lower | Holding companies per $1B of local deposits |
| `branches_per_billion` (P3-04) | 20% | Lower | Branches per $1B of local deposits |
| `leader_share_change` (P3-07) | 20% | Lower | Change in the deposit share of the three banks that led three years earlier; falling share signals an opening |
| `competition_growth` (P3-08) | 0% | Higher | Competition × growth: few competitors pay off only where the market grows (section 5) |

These are main's Pillar 3 weights. Competition × growth is built on every run but only weighted in the
`pillar3_competition_growth` scenario (80%, with leader share change at 20%).

### Pillar 4: Market quality and durability

| Metric | Weight | Direction | What it is |
|---|---|---|---|
| `gdp_growth` | 12.5% | Higher | BEA GDP growth, 2019–2024 |
| `gdp_volatility` | 12.5% | Lower | Standard deviation of annual GDP growth, 2016–2024 |
| `unemployment_level` | 12.5% | Lower | Unemployment rate, 2024 |
| `unemployment_volatility` | 12.5% | Lower | Standard deviation of the unemployment rate, 2015–2024 |
| `industry_hhi` | 12.5% | Lower | Concentration of employment across 10 sector groups, CBP 2023 |
| `establishment_growth` | 12.5% | Higher | CBP establishments, 2018–2023 |
| `population_growth` | 12.5% | Higher | Census PEP, 2019–2024 |
| `net_migration_rate` | 12.5% | Higher | 2024 net migration per 1,000 residents |

Industry HHI is blank for 95 metros, because one of the 19 CBP sectors is suppressed there (mostly mining).
Those metros can't get a complete score, which is most of the 100 metros left unranked. The
`no_industry_hhi` scenario ranks them.

---

## 5. Competition × growth (scenario `pillar3_competition_growth`)

This metric is built on every run and shown in the Pillar 3 file and report, but it has weight 0 in the baseline.
The `pillar3_competition_growth` scenario uses it at 80% of Pillar 3; in that scenario Charlotte ranks 10th
(9th–11th), against 17th in the baseline.

How attractive "few competitors" is depends on whether the market is growing. Few competitors in a growing
market is an opening; few competitors in a stable market means entrenched incumbents.

- **Fewness** = the deposit HHI percentile, where 100 means a few banks hold most deposits.
- **Growth** = the average percentile of non-HQ deposit growth (Pillar 2), middle-market growth (Pillar 1) and
  GDP growth (Pillar 4).

Each metro gets a blend of four corner values, set in `config/settings.toml`:

| | Few competitors | Many competitors |
|---|---|---|
| **Growing** | `few_growing` = 100 | `many_growing` = 50 |
| **Stable** | `few_stable` = 0 | `many_stable` = 50 |

With `c` = fewness ÷ 100 and `g` = growth ÷ 100:

```
score = few_growing·c·g + many_growing·(1−c)·g + few_stable·c·(1−g) + many_stable·(1−c)·(1−g)
```

The four weights in the formula always add to 1, so a metro only gets a corner value exactly if it sits on
that corner. Example: Miami (fewness 8, growth 70) scores 51.6; Charlotte (83, 62) scores 59.6.

With the current corners, growth makes no difference in a crowded market (both "many" corners are 50). To
let growth help crowded markets too, raise `many_growing`, for example to 65. Pillar 3's report shows which
corner every metro sits in.

---

## 6. Weights files

```toml
[universe]
min_population = 0          # size floor (section 7); 0 = off

[pillars]
pillar1 = 25
pillar2 = 25
pillar3 = 25
pillar4 = 25

[pillar1]                   # one table per pillar: metric = weight
mm_establishments = 20
...

[fill]                      # missing values for these metrics count as the 50th percentile
pillar1 = ["local_ci_growth", "local_cre_growth"]
```

- **Weights are relative.** They're rescaled to 100%, so they don't have to add up. 0 leaves a metric or pillar
  out.
- **A metric not listed counts 0.** A name that isn't a metric of that pillar stops the run with an error.
- **Every pillar with weight above 0 needs a `[pillarN]` table.**
- **Scenario files** have the same layout. A scenario file without a `[universe]` table uses the baseline's
  size floor, so the floor only needs changing in one place.

### Scenarios

| Group | Folder | Scenarios |
|---|---|---|
| Strategy (Phase 1 methodology) | `weights/strategy/` | `ci_led`, `cre_led`, `deposit_led`, `talent_led`, `adjacency`, `emerging_market`; the baseline is Balanced franchise |
| Sensitivity | `weights/scenarios/` | `fill_local_lender`, `lending_led`, `no_industry_hhi`, `no_local_lender`, `no_scale_metrics`, `pillar3_competition_growth`, `pillar3_off` |

Talent-led and Adjacency differ from the baseline only in Fit & Feasibility, so until that exists they give
the baseline ranking (the summary flags them as `same_as_baseline`). Emerging Market's "growth over levels"
tilt is not applied yet; only its pillar weights differ. `fill_local_lender` now matches the baseline, which
already fills.

File names must be unique across both folders, because outputs are named after them.

---

## 7. Size floor

Set `min_population` under `[universe]` in `weights/baseline.toml`. Metros below it keep their scores in
`available_score`, but get no rank and the status "Below size floor (250,000)". Other metros' scores don't
change; their ranks close up. Population is Census PEP for the score year.

| Floor | Metros ranked | Charlotte | BankUnited markets ranked |
|---|---|---|---|
| 0 (off, current) | 287 | 17th | 13 of 13 |
| 100,000 | 282 | 17th | 13 of 13 |
| 250,000 | 176 | 17th | 12 of 13 |
| 500,000 | 106 | 16th | 11 of 13 |
| 1,000,000 | 54 | 8th | 8 of 13 |

---

## 8. Point-in-time runs (`--as-of`)

```bash
python -m src.scoring.run --as-of 2025-06-30
```

This rebuilds every pillar from what was public on that date. For each source it uses the latest year whose
first release (from `data/reference/release_dates.csv`) came out by the date and that `data/processed` holds.
Every window keeps the length set in `config/settings.toml` and ends at that year. Results go to
`outputs/as_of/<date>/` (with the same `final_scores/`, `strategy/` and `scenario/` layout), so a back-test
never overwrites the current results.

- **Earliest date: 2019-12-12**, when BEA first published county GDP. An earlier date stops with an error naming
  the missing source.
- **Windows can shorten.** If a window would start before the data does, it's shortened, and the run file lists
  every shortening under `as_of`. BEA GDP and income go back to 2010 (`msa_year_history` is stacked on
  automatically); the other sources start in 2015, so runs before about 2023 have shorter growth and
  volatility windows than today's.
- **Pandemic years.** Runs from 2020–2022 have the 2020–21 deposit surge inside their deposit-growth windows,
  which moves the ranking a lot (Charlotte: 42nd as of mid-2021, 28th six months later).
- **Market labels move with the date.** BankUnited's markets are labelled as of the date: a mid-2025 run doesn't
  count Charlotte (entered July 2025), and a run before April 2022 doesn't count Atlanta.
- **Values are the latest vintage.** `data/processed` holds each source's latest revision, so an as-of run shows
  what was *available*, not the exact numbers published at the time.
- **Today reproduces the settings file.** A run as of today uses exactly the years in `config/settings.toml`;
  a test enforces this.

Charlotte as of 2025-06-30, just before BankUnited entered: 16th (15–18) in the baseline, using 2023 county GDP
and income (the 2024 release came out in February 2026).

In a report notebook, set `AS_OF = "2025-06-30"` in the first cell to see that pillar as of the date.

---

## 9. Outputs

All are rewritten by every run.

| File | One row per | Contents |
|---|---|---|
| `outputs/final_scores/market_attractiveness_scores.csv` | metro (387) | the baseline; load this into the dashboard |
| `outputs/final_scores/market_attractiveness_run.json` | run | the baseline's weights, settings, size floor, as-of choices, warnings |
| `outputs/final_scores/strategy/market_attractiveness_<scenario>_scores.csv` (and `_run.json`) | metro | each strategy scenario, plus `baseline_rank` and `rank_change` |
| `outputs/final_scores/strategy/scenario_summary_strategy.csv` | scenario | pillar weights, size floor, rank correlation with the baseline, metros moved 10+ places, correlation with population, Charlotte's rank and range, BankUnited markets' median rank, top 5 |
| `outputs/final_scores/strategy/scenario_bankunited_ranks_strategy.csv` | BankUnited market | its rank in each strategy scenario |
| `outputs/final_scores/scenario/` | | the same three kinds of file for the sensitivity scenarios (`scenario_summary.csv`, `scenario_bankunited_ranks.csv`) |
| `outputs/pillar_scores/pillarN_scores.csv` | metro | the pillar score under the baseline weights, `raw_` and `pct_` values for *every* metric, and the pillar's diagnostics |
| `outputs/pillar_scores/pillarN_run.json` | pillar | settings, effective weights, coverage |
| `outputs/pillar_scores/metric_catalog.csv` | metric (31) | pillar, label, direction, period, source, coverage, baseline weight |

**Columns in the final score files:**

| Column | Meaning |
|---|---|
| `complete_score`, `rank` | the score and rank; blank for partial metros and metros below the size floor |
| `available_score` | the score from the pillars a metro has (filled for every metro with data) |
| `best_rank`, `worst_rank` | the rank range under ±25% pillar weight changes |
| `coverage_status`, `missing_or_partial_pillars` | why a metro isn't ranked |
| `population`, `below_size_floor` | the size floor test |
| `filled_metrics` | metrics set to the 50th percentile for that metro |
| `pillarN_score`, `pillarN_percentile`, `pillarN_points` | each pillar's score, its percentile, and its points in the final score |
| `bankunited_market` | "branch market", or the office-only label (Atlanta, Charlotte, Houston) |

**Diagnostics in the pillar files:**
- **Pillar 3:** `competition_fewness`, `market_growth` (where a metro sits on the competition × growth grid),
  `hq_booked_share` and `hq_distortion` (the share of reported deposits booked at main or home-banking offices,
  flagged at 50%).
- **Pillar 4:** `published_classified_sectors`, `missing_naics_sectors` and `classified_to_all_industry_ratio`,
  which explain the blank industry HHI values.

---

## 10. The reports

Each report notebook (`pillar1_commercial_lending_1.ipynb`, `pillar2_deposits_treasury.ipynb`,
`pillar3_competition.ipynb`, `pillar4_market_quality_durability.ipynb`) shows:

1. the metric dictionary: every metric, its direction, period, coverage and weight;
2. the settings used;
3. the scores: the top 25 and BankUnited's markets;
4. a Charlotte breakdown with a chart (change `EXAMPLE` for another metro);
5. checks: highly correlated metric pairs, and each metro's rank range under ±25% metric weight changes;
6. Pillars 3 and 4 only: where metros sit on the competition × growth grid / the industry HHI gaps;
7. the pillar's percentile and points in the final score.

They build nothing of their own and write no files. Use a kernel from the project environment; matplotlib is
needed for the chart, and the report still runs without it.

---

## 11. Common tasks

**Change a weight.** Edit `weights/baseline.toml` (or a scenario file), then `python -m src.scoring.run`.

**Change a year, window or threshold.** Edit `config/settings.toml`, then `python -m src.scoring.run`.

**Change a competition × growth corner.** Edit `corners` under `[pillar3.competition_growth]` in
`config/settings.toml`, then `python -m src.scoring.run`. It affects the `pillar3_competition_growth` scenario
(and the baseline only if you give `competition_growth` a weight there).

**Set a size floor.** Set `min_population` under `[universe]` in `weights/baseline.toml`. To try one first:
`python -m src.market_attractiveness --min-population 250000`.

**Add a scenario.** Copy a file in `weights/strategy/` or `weights/scenarios/`, give it a new name, edit it, then
`python -m src.scoring.run`. Its results go to `outputs/final_scores/strategy/` or `outputs/final_scores/scenario/`
and it appears in that group's summary.

**Drop a metric.** Set its weight to 0 in every weights file that lists it. It stays computed and visible.

**Add a metric.**
1. In the pillar's script, add a `Metric(...)` entry to `METRICS` (key, label, direction, period, source), and
   compute its raw values in `build()` as a new column, `m["my_metric"] = ...`. Raw values only: no
   percentiles, no direction flipping.
2. Give it a weight in `weights/baseline.toml`, and in any scenario file that should use it.
3. Run `python -m src.scoring.run`, then `python -m pytest -q`.

If the metric needs data that isn't in `data/processed`, ask data engineering to add it to the build.

**Run a back-test.** `python -m src.scoring.run --as-of YYYY-MM-DD`; results go to `outputs/as_of/<date>/`.

---

## 12. Tests

`python -m pytest -q` runs the whole suite. The scoring tests (`tests/test_scoring.py`) check that:

- **Universe:** every pillar uses the same 387 metros.
- **Weights files:** every one names only metrics that exist.
- **Committed outputs:** the baseline and every scenario match them to 1e-9, and so do the pillar files.
- **Size floor:** it ranks only metros above it, and leaves everyone else's scores unchanged.
- **As-of:** today reproduces the settings file; mid-2025 uses only data released by then; dates before the data
  are rejected.
- **Competition × growth:** it hits each corner, and is blank exactly where its inputs are.

**After any deliberate change** (a weight, setting, metric or corner), rerun `python -m src.scoring.run` and
commit the new outputs with the change. The output tests fail until you do. That's intended: results can't
change without the outputs that show it.

---

## 13. Troubleshooting

| Message | Cause | Fix |
|---|---|---|
| `pillarN: ['x'] are not metrics of this pillar` | A weights file names a metric that doesn't exist (often a typo) | Check the name against `metric_catalog.csv` |
| `pillarN: the weights file needs a [pillarN] table` | A pillar with weight above 0 has no metric weights | Add the table, or set the pillar weight to 0 |
| `[fill] lists ... which are not metrics of this pillar` | `[fill]` names a metric that doesn't exist | Fix the name |
| `x.toml is in both weights/scenarios/ and weights/strategy/` | Two scenario files share a name | Rename one |
| `as of ...: no released data held for ...; pick a later date` | The date is before the data starts | Use a later date |
| Output tests fail after a change | The committed outputs are from before the change | `python -m src.scoring.run`, then commit the outputs |
| `PermissionError` writing a CSV | The file is open in Excel, or being synced | Close it, or pause syncing, and rerun |

---

## 14. Known limits

- **Fit & Feasibility isn't applied.** These are Market Attractiveness ranks only.
- **Middle market is 20–249 employees,** not the design's 20–499: CBP's 250–499 band isn't in `data/processed`.
- **CRE is 30% of Pillar 1** (CRE payroll growth and local-lender CRE growth). There's no public loan-level
  source for office, retail or industrial CRE lending.
- **Size and growth.** The baseline correlates 0.60 with population (see `no_scale_metrics`), and growth
  appears in several pillars.
- **Back-tests use the latest vintage** of each source, not the values first published.
- **Unvalidated weights.** Neither the weights nor the competition × growth corners have been validated against
  outcomes yet; the 2016–2021 peer-entry back-test is the planned check.
