"""BankUnited's own footprint by metro and year, for the back-test. Owner: Austin.

Output:
  data/interim/msa_year/bankunited.parquet   keys: cbsa_code, year   measures: bankunited_*

build_panel.build_all() writes this before it joins the tables. Nothing is downloaded:
it filters the bank_msa_year interim files from the SOD and CRA lender ingests to
BankUnited, N.A. (config.BANKUNITED_RSSD_ID) and sums them by metro and year.

  - Each source's columns cover the metro-years that source has data for: every
    metro-year with an SOD office, and every metro-year with CRA lending. Inside that
    coverage, a metro-year where BankUnited has no office, or made no loans, gets 0.
    Outside it the value stays empty, since the source says nothing there (Connecticut's
    metros before 2023 in SOD, for example). A value BankUnited's own rows leave empty,
    such as deposits at offices that report none, stays empty too.

Known gap, flagged for the modeling sub-pod (checked 2026-10-23): SOD and CRA see offices
and small business loans, not every way a bank enters a market. BankUnited's Atlanta
corporate banking office, opened April 7, 2022, isn't in SOD through June 30, 2024, and its
Atlanta CRA lending stays under a dozen loans a year, so neither source shows that entry.
Its Dallas office shows up in SOD from June 30, 2022.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src import config
from src.utils import write_interim

SOURCE = "bankunited"
KEYS = ["cbsa_code", "year"]
MEASURES = {
    "sod": {"sod_offices_count": "bankunited_sod_offices_count",
            "sod_deposits_usd": "bankunited_sod_deposits_usd"},
    "cra_bank": {"cra_bank_small_business_loan_count": "bankunited_cra_small_business_loan_count",
                 "cra_bank_small_business_loan_amount_usd": "bankunited_cra_small_business_loan_amount_usd"},
}


def _footprint(path: Path, measures: dict[str, str]) -> pd.DataFrame:
    """BankUnited's values in every metro-year the file covers: 0 where it has no row, its own sum where it does."""
    banks = pd.read_parquet(path, columns=["rssd_id", *KEYS, *measures])
    ours = banks.loc[banks["rssd_id"].astype("string").eq(config.BANKUNITED_RSSD_ID).fillna(False)]
    ours = ours.groupby(KEYS)[list(measures)].sum(min_count=1).reset_index()  # all empty stays empty
    out = banks[KEYS].drop_duplicates().merge(ours, on=KEYS, how="left", indicator=True, validate="one_to_one")
    absent = out.pop("_merge").eq("left_only")
    for column in measures:
        out[column] = out[column].mask(absent, 0)
    return out.rename(columns=measures)


def build_presence() -> Path | None:
    """Write data/interim/msa_year/bankunited.parquet from the bank_msa_year interim files, if any exist."""
    parts = [_footprint(path, measures) for source, measures in MEASURES.items()
             if (path := config.INTERIM / "bank_msa_year" / f"{source}.parquet").exists()]
    if not parts:
        return None
    out = parts[0]
    for part in parts[1:]:
        out = out.merge(part, on=KEYS, how="outer", validate="one_to_one")
    return write_interim(out, SOURCE, "msa_year")


if __name__ == "__main__":
    build_presence()
