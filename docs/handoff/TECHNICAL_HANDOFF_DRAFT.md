# Technical handoff — DRAFT, requires technical owner validation

This draft is a documentation starting point, **not** proof of successful execution. Copy into `docs/technical_handoff.md` only after technical owner review and a recorded independent run.

## Scope and source
BankUnited MSA-level market expansion prototype. Delivered Power BI v0.7 is a **Market Attractiveness MVP**, not an implemented Fit & Feasibility application. Source: repository `README.md`, `dashboard/README.md`, `requirements.txt`, `data/` and `outputs/final_scores/`.

## Environment and setup (from repository README)
Python 3.11 or newer per repository; validate actual supported Python version before acceptance.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m pytest -q
```

On Windows use `.venv\Scripts\activate`. Configure `.env` locally without committing credentials. Raw source files are not in the ZIP; README describes `RAW_DATA_DIR` pointing to authorized shared Drive or local `data/raw/`.

## Included artifacts
- `data/processed/*.parquet` — modeling tables
- `data/reference/` and `data/manifest.csv` — lookup and source inventory
- `outputs/final_scores/` — baseline/scenario score CSVs and JSON run records
- `dashboard/BankUnited_Market_Opportunity_Engine_v0.7.pbix` — Power BI report
- `tests/` — automated tests

## Verification tasks before approval
1. Confirm `integrated-v0.2` resolves to the supplied SHA and log full environment/dependency versions.
2. Obtain authorized raw data; run exact pipeline and scoring commands documented by technical leads; compare output hashes and explain expected differences.
3. Run full pytest suite, record exit code and warnings; do not confuse the historical 161 data checks with 222 team-reported pytest tests.
4. Open and refresh PBIX in recipient environment; verify expected market counts and sample result lineage.
5. Demonstrate normal and missing-data exception cases; capture input, intermediate scores, output and source references.
6. Document reviewer, date, outstanding exceptions and sponsor access confirmation.

## Known limitations
- Fit & Feasibility and entry scenario modules are placeholders.
- 287 ranked / 100 unranked metros in dashboard README; five Connecticut metros lack comparable 2021 baseline after planning-region changes.
- External raw-data access and source publication delays must be addressed before declaring independent reproducibility.
