"""FFIEC bank-level data: Call Reports and each bank's small-business lending by metro. Owner: Austin.

Outputs:
  data/interim/bank_quarter/call.parquet        keys: rssd_id, quarter_end       measures: call_*
  data/interim/bank_msa_year/cra_bank.parquet   keys: rssd_id, cbsa_code, year   measures: cra_bank_*

Starting points (verify before relying on them):
  - Call Reports: CDR bulk data, one file per quarter, rows keyed by IDRSSD. The
    bulk page is a web form that's awkward to script, so downloading by hand is
    fine: save into data/raw/call/ and log it with register_local_file().
    Record every MDRM field code you keep in docs/data_dictionary.md.
  - CRA lender-level (disclosure) files report each lender's small-business
    lending by county. Match each lender to its RSSD ID so it lines up with SOD
    and Call Reports, then roll counties up with
    counties_to_cbsa(df, cols, by=("rssd_id", "year")).
  - County totals for the lending pool are Bhavana's, in src/ingest_cra.py.
"""
from __future__ import annotations

from pathlib import Path

from src import config
from src.crosswalk import counties_to_cbsa  # noqa: F401
from src.utils import fetch, register_local_file, write_interim  # noqa: F401

SOURCE_CALL = "call"
SOURCE_CRA_BANK = "cra_bank"


def download(years: list[int], force: bool = False) -> list[Path]:
    """Pull or register Call Report files in data/raw/call/ and CRA lender files in data/raw/cra_bank/."""
    raise NotImplementedError("download")


def transform(paths: list[Path], years: list[int]) -> list[Path]:
    """Save bank_quarter with write_interim(df, SOURCE_CALL, ...) and bank_msa_year with SOURCE_CRA_BANK."""
    raise NotImplementedError("transform")


def run(years: list[int] | None = None, force: bool = False) -> list[Path]:
    years = list(years or config.YEARS)
    return transform(download(years, force=force), years)
