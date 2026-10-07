"""Project settings: paths, years, geography vintage, and API keys.

Every script reads paths from here instead of hard-coding them, so the pipeline
runs the same way on any machine (Work Order TR-01 and TR-04).
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Settings that differ per person (API keys, where raw files live) come from .env,
# which is never committed.
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:  # python-dotenv not installed: use real environment variables
    pass

# --- Where data lives (see README, "Data layout") ---------------------------
DATA = ROOT / "data"
# Raw downloads, exactly as published: the pod's shared Drive folder if RAW_DATA_DIR
# is set in .env (synced by Google Drive for desktop), otherwise data/raw/ (gitignored).
RAW = Path(os.getenv("RAW_DATA_DIR") or DATA / "raw").expanduser()
INTERIM = DATA / "interim"      # cleaned per source (gitignored)
PROCESSED = DATA / "processed"  # modeling tables (committed and tagged)
REFERENCE = DATA / "reference"  # crosswalk and lookup lists (committed)
MANIFEST = DATA / "manifest.csv"

COUNTY_CBSA_XWALK = REFERENCE / "county_cbsa_xwalk.csv"
MSA_UNIVERSE = REFERENCE / "msa_universe.csv"
FRED_SERIES = REFERENCE / "fred_series.csv"
SPOT_CHECKS = REFERENCE / "spot_checks.csv"

# --- Decisions to confirm with the pod --------------------------------------
# Panel years. The Charlotte back-test needs years from before BankUnited entered.
# Every economic source logged so far covers 2001-2023 (CBP ends at 2023; BEA county GDP starts at 2001).
START_YEAR = 2015
END_YEAR = 2024
YEARS = list(range(START_YEAR, END_YEAR + 1))

# One OMB delineation vintage for every source and every year.
# July 2023 = OMB Bulletin 23-01; check census.gov's delineation-files page for a newer one.
DELINEATION_VINTAGE = "2023"
DELINEATION_URL = (
    "https://www2.census.gov/programs-surveys/metro-micro/geographies/"
    "reference-files/2023/delineation-files/list1_2023.xlsx"
)

# Ingest modules run by run_pipeline, in this order: src/ingest_<name>.py
SOURCES = ["census", "cre", "bea_bls", "cra", "fred", "fdic", "ffiec"]  # Bhavana's four, then Austin's two

# Processed tables and their keys. build_panel joins every
# data/interim/<table>/<source>.parquet into data/processed/<table>.parquet.
TABLES = {
    "msa_year": ["cbsa_code", "year"],
    "bank_quarter": ["rssd_id", "quarter_end"],
    "bank_msa_year": ["rssd_id", "cbsa_code", "year"],
}

# --- Secrets ----------------------------------------------------------------

FRED_API_KEY = os.getenv("FRED_API_KEY", "")
BEA_API_KEY = os.getenv("BEA_API_KEY", "")
BLS_API_KEY = os.getenv("BLS_API_KEY", "")
CENSUS_API_KEY = os.getenv("CENSUS_API_KEY", "")
# SEC EDGAR refuses requests without a descriptive User-Agent (name and email).
HTTP_USER_AGENT = os.getenv("HTTP_USER_AGENT", "BankUnited Pod, DSBA 6390, UNC Charlotte")
