# BankUnited TR-03 repository verification — 2026-11-05

**Assessment: RELEASE CANDIDATE / NOT YET ACCEPTED.** This is a review of the uploaded GitHub main-branch ZIP, not an independent successful clean-machine build.

## Verified package contents
- 156 files (including 15 zero-byte placeholders), Python source, test suite, `requirements.txt`, `README.md`.
- Processed Parquet tables, reference CSVs, data manifest, quality-check report, and data dictionary.
- 30 files in `outputs/final_scores/`, including scenario CSVs and JSON run records.
- Power BI `.pbix` dashboard and its README.

## Reproducibility gaps
1. No raw data in the ZIP. The repository README points to Google Drive raw files and credentials in `.env`; self-contained rebuilding is not established.
2. `docs/technical_handoff.md` and `docs/methodology.md` are empty.
3. `src/bankunited_fit.py` and `src/entry_scenarios.py` are empty; do not claim those modules implement the corresponding capabilities.
4. `app/app.py` and both application components are empty; Power BI may be the intended demo surface, but its runtime was not validated.
5. A GitHub branch ZIP does not include `.git` commit metadata. Obtain exact commit SHA and immutable release tag.
6. The first local `python -m pytest -q --disable-warnings --maxfail=1` test failed on missing `pyarrow` under local Python 3.13. This is a missing environment dependency, **not a verified code failure**. No full test pass is claimed.
7. The processed data and scenario outputs are present, but have not been independently recomputed or compared against their run records.

## Recommended acceptance sequence
1. Pin the exact commit SHA and create a versioned release tag.
2. Build a clean Python 3.11 or 3.12 environment, install `requirements.txt`, and record `pip freeze`.
3. Run `python -m pytest`; archive complete output and exit code.
4. Re-run documented quality checks against the packaged data.
5. Run baseline/scenario scoring from a clean clone and compare output hashes.
6. Resolve raw-data accessibility: package permitted inputs or document an independently executable, credential-safe download process.
7. Populate technical handoff and methodology documents; document limitations and scope exclusions.
8. Validate Power BI opening and data refresh in the recipient environment.
9. Obtain Data, ML, AI, Integration, Documentation and sponsor acceptance.

## Suggested owner routing
- Data Engineering: Austin Edwards and Bhavana Vasireddy.
- ML: Matt D’Allaird, Jainesh Lad and Evan de Guzman.
- AI: Sonia G Chavelas Gonzalez.
- Integration: Kottakota Venkata.
- Documentation: Varun Sawant.
- Sponsor sign-off: Kort Brown and Elliot Leibowitz.

Ownership assignments are suggested from the established team roles, **not formal sign-offs**.
