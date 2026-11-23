# BankUnited MSA-Level Market Expansion Prototype

**Course:** DSBA 6390 Data Science Practicum (UNC Charlotte)
**Faculty Lead:** Dr. Ilieva Ageenko
**BankUnited Sponsors:** Kort Brown, Elliot Leibowitz
**Student Coordinators:** Akayiah, Ilieva Ageenko

## Project Overview
This repository contains an analytical framework and prototype to evaluate future commercial banking expansion opportunities across Southeast and Mid-Atlantic MSAs, using Charlotte as the pilot case.

## Core Analytical Architecture
* **Market Attractiveness Score:** Economic momentum, lending pool, deposit pool, and competitive disruption.
* **BankUnited Fit & Feasibility:** Target industry alignment, physical presence requirements, and minimum viable franchise scenarios.

## Data layout

| Data | Where it lives | Written by | Read by |
|---|---|---|---|
| Raw downloads, exactly as published | `data/raw/<source>/` on your machine (gitignored). The data engineers who refresh a source keep theirs in the pod's shared Drive folder instead, by setting `RAW_DATA_DIR` in `.env` (see [Raw data](#raw-data)) | Data engineering, only through `src/ingest_*.py` | No one |
| Cleaned per-source files | `data/interim/<table>/<source>.parquet` (gitignored), rebuilt every run | Data engineering | No one |
| Modeling tables | `data/processed/*.parquet` (committed and tagged) | Data engineering, by pull request | Modelers and the app |
| Crosswalk and lookup lists | `data/reference/` (committed) | Data engineering | Everyone |
| Pull log: URL, time, and SHA-256 of every raw file | `data/manifest.csv` (committed) | Written automatically by `fetch()` | Everyone |
| Column definitions | `docs/data_dictionary.md` | Data engineering | Everyone |

Nothing licensed or non-public goes in this repo.

## Setup

Python 3.11 or newer.

macOS or Linux:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Windows, in Command Prompt or PowerShell:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

That's enough to use the data. The modeling tables in `data/processed/` are committed, so `python -m pytest` and `python -m src.checks` run right after the install, with `.env` left as copied. The keys and raw files below are only needed to rebuild the tables from the sources.

### API keys

Set these in `.env`, which is never committed:

| Variable | Needed to rebuild? | What it's for | Where to get it |
|---|---|---|---|
| `FDIC_API_KEY` | Yes | Summary of Deposits and Call Reports (`fdic`, `ffiec`). FDIC's docs call the key optional, but requests without one have been refused | https://api.data.gov/signup/ |
| `FRED_API_KEY` | Yes | FRED series (`fred`) | Sign in to a FRED account, then request a key: https://fred.stlouisfed.org/docs/api/api_key.html |
| `BEA_API_KEY` | Yes | BEA county income and GDP (`bea_bls`) | https://apps.bea.gov/API/signup/ |
| `HTTP_USER_AGENT` | Yes | Your name and email, sent as the User-Agent with every download. Replace the placeholder | Nothing to sign up for |
| `BLS_API_KEY`, `CENSUS_API_KEY` | No | No source reads them today: the BLS and Census data come as public files. Leave them empty | |

The three keys are separate sign-ups, each free.

Keep any key file you download or save (for example the page or text file a sign-up gives you) outside the repository folder, such as in `Documents`. The only file in the repository that holds keys is `.env`, and git ignores it. Never commit a key file.

### Raw data

Leave `RAW_DATA_DIR` empty. Raw files then go to `data/raw/<source>/` in your clone, which git ignores. A full run downloads them itself, about 2 GB, most of it BLS's QCEW files. The exception is 30 CRA files: FFIEC refuses scripted downloads, so they have to be in place before the first run.

| Folder | Files, one set per year from 2015 to 2024 | Count |
|---|---|---|
| `data/raw/cra/` | `<YY>exp_aggr.zip` (`15exp_aggr.zip` to `24exp_aggr.zip`) | 10 |
| `data/raw/cra_bank/` | `<YY>exp_discl.zip` and `<YY>exp_trans.zip` | 20 |

Get them either way:

- Save each file from a browser: `https://www.ffiec.gov/sites/default/files/data/cra/flat-files/<file name>`.
- If you have the pod's Drive, copy the `cra` and `cra_bank` folders from `BankUnited Pod Data/archive/data-v0.5`. Drive downloads a folder as a zip with the real folder one level down, so copy the inner `cra` and `cra_bank` folders.

The pipeline reuses a raw file that is already in place and downloads the rest.

**`RAW_DATA_DIR` is only for the data engineers who refresh a source.** A run writes into the raw folder: it pulls the Call Report quarters of the last 200 days again every time, and downloads any file that isn't there yet. So don't point it at the pod's shared Drive folder, or at an archive folder, to test or review a build. To refresh a source you own, install Google Drive for desktop and leave it on "Stream files", so raw files stay in the cloud until the pipeline reads them. If the pod's data folder was shared with you, add a shortcut to it in My Drive so it appears on your computer. Then set `RAW_DATA_DIR` in `.env` to its `raw data` folder, for example `G:/My Drive/BankUnited Pod Data/raw data` (forward slashes, since `.env` reads a backslash before `r` or `n` as a control character). Each source's folder has one owner, so two people never write the same files. Interim files stay on your machine because they're rebuilt on every run.

## Running the pipeline

```bash
python -m src.run_pipeline                   # crosswalk -> ingest -> build -> checks
python -m src.run_pipeline --sources fdic    # one source, then rebuild and check
python -m src.run_pipeline --skip-ingest     # rebuild processed tables from interim files
python -m src.peers                          # the peer set and its identifiers, after a new quarter
python -m pytest                             # tests for the pipeline code
```

**Run the full pipeline once on a new machine before using `--sources` or `--skip-ingest`.** Both rebuild every table from the interim files in `data/interim/`, which aren't committed. On a fresh clone they overwrite `msa_year.parquet` and `msa_year_history.parquet` with tables that are missing most of their columns, and the checks fail. If that happens, `git restore data/processed data/manifest.csv` puts the committed files back. The first full run took about 33 minutes in the pod's clean-clone rerun on Windows (T63, 11/18/2026); allow 30 to 40 minutes.

The checks write `data/processed/checks_report.md` and exit with code 1 if anything fails. Every run rewrites that report with a new run time, and a run that downloads anything updates the pull times in `data/manifest.csv`, so `git status` shows changes after a run even when no table changed. A scoring run does the same to the `_run.json` files under `outputs/`. `git restore data/manifest.csv data/processed/checks_report.md` drops the first two.

Each source publishes on its own schedule. [Refresh cadence](docs/refresh_cadence.md) says when to rerun each one and what a refresh takes.

## Scoring

The Market Attractiveness scores are built from the committed tables in `data/processed/`, so a fresh clone can run them without rebuilding the data first. From the repository root, with the environment active:

```bash
python -m src.scoring.run                    # every metric, pillar file, the baseline score and all scenarios (about a minute)
python -m pytest                             # check that everything still lines up
```

Results go to `outputs/`: the baseline scores in `outputs/final_scores/market_attractiveness_scores.csv`, the strategy scenarios in `outputs/final_scores/strategy/`, the robustness checks in `outputs/final_scores/scenario/`, and each pillar's metrics in `outputs/pillar_scores/`. A scoring run rewrites the date inside the `*_run.json` files, so `git status` shows them as changed even when no score changed. How the score works, how to change weights and filters, and the full list of commands are in [Scoring](src/scoring/README.md).

## Dashboard

The Power BI dashboard is in `dashboard/`. To look at it, install Power BI Desktop (Windows, free) and open `dashboard/BankUnited_Market_Opportunity_Engine_v0.9.pbix`. The scores are saved inside that file, so it does not read the repository and does not change when you rerun the scoring: after a new scoring run, the dashboard owner has to rebuild the file. The Map page needs an internet connection. Pages, how the score is built and the known limits are in [dashboard/README.md](dashboard/README.md).

## Notebooks

The pillar notebooks in `notebooks/` need Jupyter and matplotlib, which `requirements.txt` installs. Start Jupyter from the repository root, with the environment active, so the notebooks can import `src`:

```bash
jupyter lab
```

## Using the data (modelers)

```python
import pandas as pd
msa = pd.read_parquet("data/processed/msa_year.parquet")

import duckdb
duckdb.sql("SELECT * FROM 'data/processed/msa_year.parquet' WHERE cbsa_code = '16740'").df()
```

Each table's grain, key and joins are under [Tables and keys](docs/data_dictionary.md#tables-and-keys) in the data dictionary, which defines every column.

Two tables hold BLS QCEW private employment, wages and establishments by industry: `msa_industry_year` (metro, industry and year; the private total, 11 supersectors and 20 two-digit sectors) and `us_industry_year` (the same for the whole U.S., so a location quotient can be computed). Both are built by `src/ingest_qcew.py` from the QCEW files that `src/ingest_bea_bls.py` downloads. See their sections in the [data dictionary](docs/data_dictionary.md#msa_industry_year-one-row-per-metro-per-industry-per-year).

The peer set, every organization with $10B–$100B in total assets, is in `data/reference/peer_organizations.csv`, with each organization's RSSD IDs, FDIC certificates, ticker and SEC CIK. See [Bank identifiers and the peer set](docs/data_dictionary.md#bank-identifiers-and-the-peer-set).

Never edit files in `data/processed/`. Note the data version tag (e.g. `data-v0.1`) you used for each model run. Need a new variable? Ask data engineering to add it to the build rather than creating it in a notebook.

## Adding a data source

Each `src/ingest_<name>.py` has a `download()` and a `transform()` to fill in:

1. `download()` pulls raw files with `fetch(url, SOURCE)`, or logs a file you downloaded by hand with `register_local_file()`. Either way the file lands in the manifest.
2. `transform()` reads the raw files, maps counties to metros with `counties_to_cbsa()`, and saves with `write_interim(df, SOURCE, "msa_year")`. `write_interim()` rejects missing or repeated keys and badly named columns.
3. Name measure columns `<source>_<measure>` and end them with a unit suffix: `_count`, `_usd` (whole dollars), `_pct`, or `_share`. The checks use these suffixes. Two more aren't range-checked: `_ratio` for a percent kept as published that can be negative or above 100, and `_usd_net` for dollars that can be negative. Coordinates end in `_latitude` and `_longitude` (decimal degrees); they must fall within the U.S. and Puerto Rico and are never empty.
4. Add every new column to `docs/data_dictionary.md`, with its Type. The checks fail the build if a processed column has no row, has two, or holds values that don't fit its Type.

## Versioning the data

When a build passes its checks, commit `data/processed/` and `data/manifest.csv`, then tag it:

```bash
git tag data-v0.1
git push origin data-v0.1
```

Then copy the raw folder into an archive folder on the Drive named after the tag, since later pulls overwrite raw files in place.
