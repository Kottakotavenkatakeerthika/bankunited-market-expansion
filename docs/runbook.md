# Operation and maintenance runbook

How to run, refresh, check and maintain the BankUnited market expansion data pipeline and scores (plan task T68). Written for whoever runs it at BankUnited after the handoff, and for the pod until then.

**Status:** final, reviewed November 24–26, 2026 by Bhavana Vasireddy (sections 2, 4, 6 and 7), Akayiah Bell (section 10) and Matt D'Allaird (section 5). Written against **data-v0.7** (main at `4597975`, November 23, 2026): seven processed tables, 313 tests, and checks at 198 passed, 0 failed, 18 warnings. Owner: Austin Edwards, with Bhavana Vasireddy and Venkata Keerthika Kottakota.

This runbook gives the order of operations and what to do when something goes wrong. The details it points to:

| For | Read |
|---|---|
| Setup, keys, raw files, commands | [README](../README.md) |
| When each source publishes and what a refresh of it takes | [Refresh cadence](refresh_cadence.md) |
| Every table, column, key and source note | [Data dictionary](data_dictionary.md) |
| How the scores are built and how to change them | [Scoring](../src/scoring/README.md) |
| The Power BI dashboard | [Dashboard](../dashboard/README.md) |

## 1. What runs

```
public sources ──> python -m src.run_pipeline ──> data/processed/*.parquet ──> python -m src.scoring.run ──> outputs/ ──> dashboard (rebuilt by its owner)
                   crosswalk, ingest, build, checks   (7 tables + checks_report.md)   (scores and scenarios)
```

- **On demand, by hand.** There is no scheduled job. BankUnited said on October 9 that it prefers on-demand runs: someone runs a source when it publishes something the tables use (section 4).
- **Two steps always need a person.** FFIEC blocks scripted downloads, so its CRA files are saved from a browser. And every rebuild is reviewed before anyone uses it: checks, a pull request, a reviewer, a data tag.
- **No BankUnited data goes in.** Every source is public, and nothing is sent out.

The seven tables at data-v0.7:

| Table | One row per | Rows x columns |
|---|---|---|
| `msa_year` | metro and year, 2015–2024 | 3,930 x 58 |
| `msa_year_history` | metro and year, 2010–2014 | 1,965 x 5 |
| `msa_naics_year` | metro, industry and year (CBP) | 67,487 x 7 |
| `msa_industry_year` | metro, industry and year (QCEW) | 121,744 x 9 |
| `us_industry_year` | industry and year, U.S. (QCEW) | 320 x 6 |
| `bank_quarter` | bank and quarter, 2015 Q1 to 2026 Q2 | 240,330 x 62 |
| `bank_msa_year` | bank, metro and year, 2015–2024 | 331,879 x 21 |

## 2. Setting up a machine

1. **Get the code.** BankUnited receives it as a ZIP of the repository: the pod sends it to Elliot Leibowitz and BankUnited InfoSec on November 30, 2026, and InfoSec scans it (plan blocker B2, now closed). A ZIP has no git history. Put the folder under version control before the first run, so you can see what a run changed and undo it:

   ```bash
   git init
   git add -A
   git commit -m "As received"
   ```

2. **Install.** Python 3.11 or newer, then the environment and packages from the README's [Setup](../README.md#setup) (`.venv\Scripts\activate` and `copy` on Windows, `source .venv/bin/activate` and `cp` elsewhere). The package versions are pinned in `requirements.txt`.
3. **Check the install.** `python -m pytest` and `python -m src.checks` run on the committed tables with no keys and no raw files. Expect 313 tests passed and 198 passed, 0 failed, 18 warnings.
4. **Keys:** section 3. Only needed to rebuild the tables.
5. **Raw files.** Leave `RAW_DATA_DIR` empty for raw files to go to `data/raw/` (which git ignores), or point it at a folder outside the repository that you keep (use forward slashes in `.env`). A full run downloads about 2 GB by itself. The 30 FFIEC CRA files can't be downloaded by a script, so save them from a browser first, as the README's [Raw data](../README.md#raw-data) section lists: `15exp_aggr.zip` to `24exp_aggr.zip` in `cra/`, and the `<YY>exp_discl.zip` and `<YY>exp_trans.zip` files for 2015–2024 in `cra_bank/`, each from `https://www.ffiec.gov/sites/default/files/data/cra/flat-files/<file name>`.
6. **First full run:** `python -m src.run_pipeline`. Allow 30 to 40 minutes (the pod's clean-clone rerun took 33 minutes on Windows). Then read `data/processed/checks_report.md` (section 6).

**Run the full pipeline once on a machine before using `--sources` or `--skip-ingest`.** Both rebuild every table from the interim files in `data/interim/`, which aren't committed. On a fresh copy they overwrite `msa_year.parquet` and `msa_year_history.parquet` with tables missing most of their columns, and the checks fail. `git restore data/processed data/manifest.csv` puts the committed files back.

## 3. API keys and secrets

| Variable | Needed to rebuild? | Used for | Where to get it |
|---|---|---|---|
| `FDIC_API_KEY` | Yes | Summary of Deposits and Call Reports (`fdic`, `ffiec`) | https://api.data.gov/signup/ |
| `FRED_API_KEY` | Yes | FRED series (`fred`) | https://fred.stlouisfed.org/docs/api/api_key.html |
| `BEA_API_KEY` | Yes | BEA county income and GDP (`bea_bls`) | https://apps.bea.gov/API/signup/ |
| `HTTP_USER_AGENT` | Yes | A name and email sent with every download | Nothing to sign up for |
| `BLS_API_KEY`, `CENSUS_API_KEY` | No | Nothing reads them: BLS and Census data come as public files | |

**How the code reads them.** `src/config.py` reads each value from an environment variable, after loading a `.env` file in the repository folder if there is one. A variable that is already set in the environment wins over `.env`, and `.env` fills in the rest. The download log (`data/manifest.csv`) never records a key: `fetch()` replaces it with `REDACTED`.

- **On a laptop:** put the values in `.env`. Git ignores it, and it's the only file in the repository that holds keys. Keep any file a sign-up gives you outside the repository folder.
- **At BankUnited:** keep the four values as one JSON secret in AWS Secrets Manager, which BankUnited confirmed in November is its secrets manager, for example:

  ```json
  {"FDIC_API_KEY": "...", "FRED_API_KEY": "...", "BEA_API_KEY": "...", "HTTP_USER_AGENT": "Name email@bankunited.com"}
  ```

  Before a run, set each field as an environment variable. Nothing in the code needs to change, and no `.env` file is needed. One way, with `<secret name>` filled in:

  ```powershell
  # PowerShell
  $secret = aws secretsmanager get-secret-value --secret-id <secret name> --query SecretString --output text | ConvertFrom-Json
  foreach ($name in "FDIC_API_KEY", "FRED_API_KEY", "BEA_API_KEY", "HTTP_USER_AGENT") { Set-Item "env:$name" $secret.$name }
  ```

  ```bash
  # bash
  eval "$(aws secretsmanager get-secret-value --secret-id <secret name> --query SecretString --output text \
    | python -c 'import json, shlex, sys; [print(f"export {k}={shlex.quote(v)}") for k, v in json.load(sys.stdin).items()]')"
  ```

- **Changing a key:** replace it in `.env` or in the secret. Nothing in the repository changes.

## 4. When to run

Run a source when it publishes something the tables use. The full table of sources, revisions and commands is in [Refresh cadence](refresh_cadence.md). The year in short:

| When | What's new | Run |
|---|---|---|
| Early February, May, August and November | Call Reports for the quarter before | `--sources ffiec` |
| Early February | FRED's December, completing last year | `--sources fred --force-download` |
| Mid to late March | Census population estimates (PEP), a new vintage | Point `src/ingest_pep.py` at it, then `--sources pep` |
| Late April or early May | BLS LAUS unemployment for last year | `--sources bea_bls --force-download` |
| Early June, early September | BLS QCEW for last year, preliminary then final | `--sources bea_bls qcew cre --force-download` |
| Mid to late September | FDIC Summary of Deposits as of June 30 | `--sources fdic`, once `END_YEAR` reaches that year |
| Mid-November to mid-December | FFIEC CRA for last year; BEA county income and GDP | Save the CRA files by hand, then `--sources cra ffiec`; `--sources bea_bls --force-download` |
| No date | County Business Patterns (CBP) 2024; a new OMB metro delineation | See [Refresh cadence](refresh_cadence.md) |

Coming up, as of November 23, 2026:

- **2026 Q3 Call Reports.** They were due October 30 (November 4 for banks with more than one foreign office). FDIC's current version, from November 16, doesn't have them yet; the next `--sources ffiec` run after FDIC posts them adds the quarter (section 5, step 4).
- **CRA 2025** came out November 5, 2026, and **BEA's 2025** county data is scheduled for December 2, 2026. Once both are out, the tables can move to 2025 (section 7).

## 5. A routine refresh

1. **Start clean.** Get the latest code (`git pull`) and check that `git status` shows nothing changed.
2. **Run the source**, after one full run on that machine (section 2):

   ```bash
   python -m src.run_pipeline --sources <name>       # pulls that source, rebuilds every table, runs the checks
   ```

   `--force-download` pulls a source's files again even if they're already saved, for the sources that change files in place (BEA, FRED, QCEW's final release). **Never use it with `cra` or `ffiec`, and never on a full run:** it also asks FFIEC for the CRA files, FFIEC refuses (403), and the run stops there. To pull every Call Report quarter again (FDIC revises past quarters; see the note in the data dictionary), run instead:

   ```bash
   python -c "from src import config, ingest_ffiec; ingest_ffiec.download_call(config.YEARS, force=True)"
   python -m src.run_pipeline --sources ffiec
   ```

3. **Read `data/processed/checks_report.md`.** No failures, and every warning on the standing list in section 6. A new warning needs an explanation in the pull request.
4. **Date the new data.** Add the first release of every new year or quarter to `data/reference/release_dates.csv`, as **Released** under Conventions in the data dictionary describes. For a new Call Report quarter, the release date is the quarter end plus 35 days, and `tests/test_release_dates.py` counts the quarters (46, through 2026 Q2), so raise that count in the same pull request.
5. **After a new Call Report quarter**, run `python -m src.peers` to update the peer set (`data/reference/peer_organizations.csv`). If it prints a holder with no row in `holder_listings.csv`, add the row by hand, as the script's docstring describes.
6. **Run the tests:** `python -m pytest` (about a minute).
7. **Look at what changed:** `git status` and `git diff --stat`. Only the tables you expected should change. Every run also rewrites `checks_report.md` and the download times in `data/manifest.csv`; that alone isn't a change to the data.
8. **Review and release.** Commit `data/processed/`, `data/manifest.csv` and any `data/reference/` changes on a branch, open a pull request with a reviewer, and merge it. Tag the merge commit (`data-v0.8`, then `data-v0.9`, and so on, continuing from data-v0.7), write release notes like the earlier ones, and copy the raw folder to an archive folder named after the tag. Sources change files in place, so the archive is the only way to rebuild a tagged release exactly.
9. **Scores and dashboard.** If the data the scores read changed, run `python -m src.scoring.run` (under a minute; it writes `outputs/`) and review it the same way. The Power BI file stores its data, so it doesn't change with the scores: its owner rebuilds it from the new score files. The scores read fixed years and quarters from `config/settings.toml` (data through 2024, County Business Patterns through 2023, and the June 30, 2024 Call Report quarter), so a refresh doesn't move them unless those settings change.

## 6. When a check fails

The pipeline writes the processed tables, then runs the checks. If any check fails, `python -m src.run_pipeline` (and `python -m src.checks`) exits with code 1, and `checks_report.md` lists every check as pass, FAIL or warning. The tables in `data/processed/` have already been rewritten by then, so don't commit them: fix the cause, or put the committed files back with `git restore data/processed data/manifest.csv`.

| Check in the report | What it usually means | What to do |
|---|---|---|
| every column has a dictionary row; no column has two dictionary rows; values fit their dictionary Type | A source added, renamed or retyped a column, or a new column wasn't documented | Add or fix the column's row in `docs/data_dictionary.md` in the same pull request |
| key columns present; no empty keys; one row per key; `<code>` is N digits | A source changed its format, or codes lost their leading zeros | Compare the raw file with the source's file layout, then fix the ingest |
| every universe metro has every year | `END_YEAR` or `msa_universe.csv` changed without a full rebuild | Run the full pipeline. Moving `END_YEAR` to 2025 without one fails here with 393 metros missing 2025 |
| `<column>` >= 0, within 0-100, within 0-1, within 0-10,000, within -1 to 1; coordinates in range and filled | A unit or sign changed at the source (thousands of dollars instead of dollars, a percent instead of a share) | Check the source's documentation for that field and fix the ingest's conversion |
| spot check: `<column>` for a metro or a bank ("built X vs published Y") | The source revised a figure the check compares against (`data/reference/spot_checks.csv` for metros, `bank_spot_checks.csv` for banks), or the build drifted | Look up the source's current figure. If the source revised it, update that row, with its date, in the same pull request |
| each FDIC cert belongs to one RSSD ID per quarter | A merger moved a certificate in a way that puts it on two banks in one quarter | See "Bank identifiers and the peer set" in the data dictionary |
| industry codes are among the 32 allowed; a metro's establishments never exceed the U.S. figure; supersectors add up to the private total | BLS changed its QCEW files or codes | Compare the QCEW files with BLS's layout (https://www.bls.gov/cew/) |

Some problems stop the run before the checks, with a message that says what to do:

- **FFIEC 403:** FFIEC refuses scripted downloads. Save the files named in the message from a browser, and don't use `--force-download` with `cra` or `ffiec` (section 5).
- **FDIC 401 or 403:** `FDIC_API_KEY` is missing or wrong.
- **SOD:** each year's state files must add up to FDIC's national office count, or the build stops. Run it again later; if it keeps stopping, pull SOD again with `--sources fdic --force-download`, which pulls every year.
- **Call Reports:** a saved quarter must hold as many banks as FDIC counts, and FDIC must still use the field names in `CALL_FIELDS` (`src/ingest_ffiec.py`), or the build stops. "FDIC hasn't published that quarter yet" is normal: the run skips the quarter and the next run picks it up.
- **CRA lending by bank:** the build stops if more than 1% of metro-years are more than 2% off the CRA county totals, or if any year's total is more than 0.5% off. Check that each year's files are the originals the README lists (`<YY>exp_aggr.zip`, `<YY>exp_discl.zip`, `<YY>exp_trans.zip`): FFIEC has posted revised files for some years, and the pipeline uses the originals.
- **Metro coordinates:** the build stops if a metro in `msa_universe.csv` has no point in the Gazetteer file, which happens after a new OMB delineation (see [Refresh cadence](refresh_cadence.md)).

**The 18 standing warnings at data-v0.7.** All 18 are expected; a warning that isn't on this list needs an explanation.

| Table | Warning | Why it's there |
|---|---|---|
| `msa_year` | `fred_unemployment_rate_pct` mostly empty | `data/reference/fred_series.csv` lists one series, Charlotte's unemployment rate, so every other metro is empty |
| `bank_quarter` | `call_uninsured_deposits_usd` mostly empty | Only banks with $1 billion or more report uninsured deposits; every 0 is left empty |
| `bank_quarter` | `call_ci_loans_non_us_addressees_usd` mostly empty | Empty when a bank's form doesn't split C&I loans this way (every FFIEC 051 filer and some smaller 041 filers) |
| `bank_msa_year` | ten `sod_` columns mostly empty | A row exists when SOD or CRA has the bank in that metro, and most rows are CRA lenders with no office there |
| `bank_quarter` + `bank_msa_year` | SOD certificates don't match the June 30 Call Report (15 bank-metro-years) | New York Community Bank and Flagstar, 2022 |
| `bank_quarter` + `bank_msa_year` | an SOD bank has no June 30 Call Report (11 bank-years) | Bank of China's certificate 33652, every year, and Park State Bank, 2021 |
| `bank_quarter` + `bank_msa_year` | a CRA lender filed no Call Report that year (4 lender-years) | Banks merged early in the year after their last Call Report |
| `msa_industry_year` | supersectors don't add up to the private total where a county is suppressed (employment, wages) | BLS withholds a suppressed county's figures, so the supersectors fall short |

The identifier cases are described in "Bank identifiers and the peer set" in the data dictionary.

## 7. Adding a new data year

Moving the tables from 2024 to 2025 is likely the first maintenance job after the handoff. As of November 23, 2026, 2025 is out for LAUS, QCEW, PEP, FRED, SOD and CRA (November 5); BEA's is scheduled for December 2, 2026; CBP has no date for 2024. Move once BEA's is out.

1. **Year settings:**
   - `src/config.py`: `END_YEAR = 2025`.
   - `src/ingest_cra.py`: `CRA_LATEST_AVAILABLE_YEAR = 2025`. It also governs CRA lending by bank.
   - `src/ingest_pep.py`: `NEW_YEARS = range(2020, 2026)` and `LATEST_YEAR = 2025`. The Vintage 2025 file it already reads includes 2025. A later vintage also needs `NEW_FILE`, `METRO_FILE` and their folder (see [Refresh cadence](refresh_cadence.md)).
   - `src/ingest_bea_bls.py`: `LAUS_LATEST_AVAILABLE_YEAR` and `QCEW_LATEST_AVAILABLE_YEAR` are already 2025. `BEA_LATEST_AVAILABLE_YEAR` (2024) isn't read by anything; set it to 2025 to keep it accurate.
   - Leave `LATEST_AVAILABLE_YEAR = 2023` in `src/ingest_census.py` and `src/ingest_cre.py` until Census publishes CBP 2024. The `cbp_` columns stay empty for the newest years, and the CRE measures use QCEW, as they already do for 2024.
   - SOD and FRED have no year setting of their own: `END_YEAR` covers them.
2. **The CRA files, by browser:** `25exp_aggr.zip` into the raw folder's `cra/`, and `25exp_discl.zip` and `25exp_trans.zip` into `cra_bank/`. The run logs the two `cra_bank` files in the manifest. Log the aggregate file yourself:

   ```bash
   python -c "from src import config; from src.utils import register_local_file; register_local_file(config.RAW / 'cra' / '25exp_aggr.zip', 'cra', url='https://www.ffiec.gov/sites/default/files/data/cra/flat-files/25exp_aggr.zip', notes='FFIEC CRA aggregate flat file, 2025, downloaded by hand')"
   ```

3. **Rebuild:** a full run downloads the new year's files, then BEA and FRED are pulled again because they change in place:

   ```bash
   python -m src.run_pipeline
   python -m src.run_pipeline --sources bea_bls fred --force-download
   ```

4. **Release dates:** add each source's first release of 2025 to `data/reference/release_dates.csv` (BEA's two datasets, LAUS, QCEW, the three CRA files, FRED, SOD and PEP), and update the **Released** cells in the data dictionary. Then, in `tests/test_release_dates.py`, raise those sources' last year from 2024 to 2025 (CBP stays at 2023) and change the PEP test's `range(2015, 2025)` to `range(2015, 2026)`. Moving `END_YEAR` doesn't make any test fail, so this is the step that makes the tests check the new year.
5. **Checks and tests:** expect the same 18 standing warnings; explain any new one. Then the review, tag and release steps in section 5, noting in the release notes that every table gained a year.
6. **Scores:** they stay on 2024 until the scoring owners move the years in `config/settings.toml` (Pillar 3's `score_year`, the quarters and year ranges in Pillars 1, 2 and 4, and the Fit settings). That's a modeling decision. After it: `python -m src.scoring.run`, a reviewed pull request, and a rebuilt dashboard.

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Checks fail on a fresh copy after `--sources` or `--skip-ingest` | No full run on that machine yet | `git restore data/processed data/manifest.csv`, then `python -m src.run_pipeline` |
| `git status` shows changed files after a run, but no table changed | The run rewrote `checks_report.md` and the download times in `data/manifest.csv`; a scoring run rewrites the date in the `*_run.json` files | `git restore data/manifest.csv data/processed/checks_report.md` (and `outputs/` for a scoring run) |
| "403 Forbidden" from ffiec.gov | FFIEC refuses scripted downloads | Save the files from a browser; never `--force-download` with `cra` or `ffiec` |
| `bank_quarter` differs after a fresh pull, though nothing else changed | FDIC posts revised versions of past quarters | Expected. Each raw Call Report file records FDIC's version (the `index` name). See the FDIC note under `bank_quarter` in the data dictionary |
| A path in `.env` doesn't work on Windows | A backslash before `r` or `n` becomes a control character | Use forward slashes: `RAW_DATA_DIR="D:/data/raw data"` |
| A folder copied from Google Drive has an extra level | Drive downloads a folder as a zip with the real folder inside | Copy the inner folder |
| `MemoryError`, or Python crashes, during `python -m pytest` on a small laptop | The full suite needs about 1 GB of memory, mostly for the scoring tests | Close other programs, or run test files one at a time (`python -m pytest tests/test_scoring.py`) |
| The dashboard doesn't show new scores | The Power BI file stores its data | The dashboard owner rebuilds the file from the new score files |
| The dashboard's map is blank | The Map page needs an internet connection | Connect, then reopen the page |

## 9. Known limitations

These come from what the public sources publish. The gaps stay visible instead of being filled in. The data dictionary explains each one, and the pod's [How Our Data Works](https://docs.google.com/document/d/1pPsBflgYu8Cs7uapiIwX2BE7WNs3mnlcVieZ7EziC_Y) has the longer version.

- **Manual steps:** the FFIEC CRA files are saved by hand, and every rebuild is reviewed by a person. Runs are on demand; nothing is scheduled.
- **County Business Patterns runs a year behind:** CBP's latest year is 2023, so its columns are empty for 2024, and Census has no release date for 2024. The CRE measures use QCEW for 2024.
- **Connecticut's early years are missing:** Connecticut replaced its counties with planning regions, and several sources kept the old counties for a while. Its five metros lack the base years their growth measures need, so they have partial scores, and `msa_industry_year` has them only for 2024.
- **QCEW suppression:** where BLS suppresses a county, a metro's employment and wages are undercounts (25,422 of the 121,744 rows in `msa_industry_year`).
- **CRA covers only the larger banks:** only banks above the asset threshold ($1.564 billion in 2024) report, about 77.6% of small business loans outstanding by FFIEC's estimate. Smaller banks' loans are missing, not zero.
- **Larger business loans aren't published by place:** Call Reports give each bank's totals for the whole bank, so the scoring estimates a metro's commercial lending from where each bank holds its deposits.
- **Commercial real estate is measured indirectly,** through real estate and construction businesses, jobs and payroll.
- **Only banks are competitors:** SOD covers FDIC-insured institutions, not credit unions or nonbank lenders.
- **Fresh pulls differ from tagged releases:** FDIC revises past quarters (its November 16, 2026 version changes 1,720 of the 240,330 bank-quarters), and BEA, FRED and QCEW revise their files in place. Rebuilding a tagged release exactly needs its archived raw folder.
- **Scores use fixed years** (data through 2024) set in `config/settings.toml` until the scoring owners change them, and the dashboard holds its own copy of the scores.
- **Puerto Rico's six metros aren't scored,** since the BEA, CBP and population files the pipeline reads don't include them.

## 10. Who to contact

**Until the handoff,** the pod:

| Area | Who |
|---|---|
| Bank sources (FDIC Summary of Deposits, Call Reports, CRA lending by bank, the peer set, metro coordinates) and the shared pipeline (crosswalk, checks, data releases) | Austin Edwards |
| Economic sources (County Business Patterns, population estimates, BEA, BLS LAUS and QCEW, FRED, CRA county totals, the CRE measures) | Bhavana Vasireddy |
| Scoring: Pillars 1 and 2 / Pillar 3 / Pillar 4 | Matt D'Allaird / Jainesh Lad / Evan De Guzman |
| Dashboard | Sonia Chavelas Gonzalez |
| Repository, integration and final release | Venkata Keerthika Kottakota |
| Documentation | Varun Sawant |
| Project manager | Akayiah Bell |

**After the handoff:** BankUnited's owners for the pipeline and this runbook are Elliot Leibowitz and Amandeep Kohli. The repository ZIP also goes to BankUnited InfoSec (section 2).

**The sources:**

| Source | Where to look |
|---|---|
| FDIC BankFind API (SOD, Call Reports) | https://api.fdic.gov/banks/docs/ |
| FFIEC CRA flat files | https://www.ffiec.gov/data/cra/flat-files |
| BEA county data | https://www.bea.gov/data/by-place-county-metro-local |
| BLS QCEW and LAUS | https://www.bls.gov/cew/ and https://www.bls.gov/lau/ |
| Census County Business Patterns | https://www.census.gov/programs-surveys/cbp.html |
| Census population estimates | https://www2.census.gov/programs-surveys/popest/datasets |
| Census Gazetteer | https://www2.census.gov/geo/docs/maps-data/data/gazetteer/ |
| FRED | https://fred.stlouisfed.org/docs/api/api_key.html |

## Commands at a glance

| To | Run |
|---|---|
| Check an install | `python -m pytest` and `python -m src.checks` |
| Rebuild everything | `python -m src.run_pipeline` |
| Refresh one source | `python -m src.run_pipeline --sources <name>` |
| Pull a source's files again | `python -m src.run_pipeline --sources <name> --force-download` (not `cra` or `ffiec`) |
| Pull every Call Report quarter again | `python -c "from src import config, ingest_ffiec; ingest_ffiec.download_call(config.YEARS, force=True)"`, then `--sources ffiec` |
| Update the peer set after a new quarter | `python -m src.peers` |
| Rerun the scores | `python -m src.scoring.run` |
| Undo a run's changes to the tables | `git restore data/processed data/manifest.csv` |
