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
| Raw downloads, exactly as published | The pod's shared Drive folder, synced by Google Drive for desktop (set `RAW_DATA_DIR` in `.env`); otherwise `data/raw/<source>/` on your machine (gitignored) | Data engineering, only through `src/ingest_*.py` | No one |
| Cleaned per-source files | `data/interim/<table>/<source>.parquet` (gitignored), rebuilt every run | Data engineering | No one |
| Modeling tables | `data/processed/*.parquet` (committed and tagged) | Data engineering, by pull request | Modelers and the app |
| Crosswalk and lookup lists | `data/reference/` (committed) | Data engineering | Everyone |
| Pull log: URL, time, and SHA-256 of every raw file | `data/manifest.csv` (committed) | Written automatically by `fetch()` | Everyone |
| Column definitions | `docs/data_dictionary.md` | Data engineering | Everyone |

Nothing licensed or non-public goes in this repo.

## Setup

Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then add your API keys to .env
```

**Raw files on the shared Drive.** Install Google Drive for desktop and leave it on "Stream files", so raw files stay in the cloud until the pipeline reads them. If the pod's data folder was shared with you, add a shortcut to it in My Drive so it appears on your computer. Then set `RAW_DATA_DIR` in `.env` to its `raw` folder, for example `G:/My Drive/BankUnited Pod Data/raw` (forward slashes, since `.env` reads a backslash before `r` or `n` as a control character). Each source's folder has one owner, so two people never write the same files. Interim files stay on your machine because they're rebuilt on every run.

## Running the pipeline

```bash
python -m src.run_pipeline                   # crosswalk -> ingest -> build -> checks
python -m src.run_pipeline --sources fdic    # one source, then rebuild and check
python -m src.run_pipeline --skip-ingest     # rebuild processed tables from interim files
python -m pytest                             # tests for the pipeline code
```

The checks write `data/processed/checks_report.md` and exit with code 1 if anything fails.

## Using the data (modelers)

```python
import pandas as pd
msa = pd.read_parquet("data/processed/msa_year.parquet")

import duckdb
duckdb.sql("SELECT * FROM 'data/processed/msa_year.parquet' WHERE cbsa_code = '16740'").df()
```

Never edit files in `data/processed/`. Note the data version tag (e.g. `data-v0.1`) you used for each model run. Need a new variable? Ask data engineering to add it to the build rather than creating it in a notebook.

## Adding a data source

Each `src/ingest_<name>.py` has a `download()` and a `transform()` to fill in:

1. `download()` pulls raw files with `fetch(url, SOURCE)`, or logs a file you downloaded by hand with `register_local_file()`. Either way the file lands in the manifest.
2. `transform()` reads the raw files, maps counties to metros with `counties_to_cbsa()`, and saves with `write_interim(df, SOURCE, "msa_year")`. `write_interim()` rejects missing or repeated keys and badly named columns.
3. Name measure columns `<source>_<measure>` and end them with a unit suffix: `_count`, `_usd` (whole dollars), `_pct`, or `_share`. The checks use these suffixes.
4. Add every new column to `docs/data_dictionary.md`.

## Versioning the data

When a build passes its checks, commit `data/processed/` and `data/manifest.csv`, then tag it:

```bash
git tag data-v0.1
git push origin data-v0.1
```

Then copy the raw folder into an archive folder on the Drive named after the tag, since later pulls overwrite raw files in place.
