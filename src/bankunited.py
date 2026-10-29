"""BankUnited's own footprint by metro and year, for the back-test. Owner: Austin.

Output:
  data/interim/msa_year/bankunited.parquet   keys: cbsa_code, year   measures: bankunited_*

build_panel.build_all() writes this before it joins the tables. Nothing is downloaded:
it filters the bank_msa_year interim files from the SOD and CRA lender ingests to
BankUnited, N.A. (config.BANKUNITED_RSSD_ID), one row per metro and year.

  - Each source's columns cover the metro-years that source has data for: every
    metro-year with an SOD office, and every metro-year with CRA lending. Inside that
    coverage, a metro-year where BankUnited has no office, or made no loans, gets 0.
    Outside it the value stays empty, since the source says nothing there (Connecticut's
    metros before 2023 in SOD, for example). A value BankUnited's own row leaves empty
    stays empty too; a real 0, such as its Dallas office's deposits in 2022, stays 0.
  - If only one of the two files exists, that source's columns are left out and a line
    says so.

Known gap, flagged for the modeling sub-pod (checked 2026-10-23): SOD and CRA see offices
and small business loans, not every way a bank enters a market. BankUnited's Atlanta
corporate banking office, opened April 7, 2022, isn't in SOD through June 30, 2024, and its
Atlanta CRA lending stays under a dozen loans a year, so neither source shows that entry.
Its Dallas office shows up in SOD from June 30, 2022. Charlotte, the back-test metro, has no
BankUnited office in any year and CRA loans only in 2015 (1), 2017 (1) and 2020 (3).
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
    """BankUnited's values in every metro-year the file covers: 0 where it has no row, its row's values where it does.

    bank_msa_year has one row per bank, metro and year, so BankUnited has at most one row in a
    metro-year and nothing is summed: an empty value in its row stays empty. The merge's
    validate="one_to_one" stops the build if that ever stops being true.
    """
    banks = pd.read_parquet(path, columns=["rssd_id", *KEYS, *measures])
    ours = banks.loc[banks["rssd_id"].astype("string").eq(config.BANKUNITED_RSSD_ID).fillna(False), [*KEYS, *measures]]
    out = banks[KEYS].drop_duplicates().merge(ours, on=KEYS, how="left", indicator=True, validate="one_to_one")
    absent = out.pop("_merge").eq("left_only")
    for column in measures:
        out[column] = out[column].mask(absent, 0)
    return out.rename(columns=measures)


def build_presence() -> Path | None:
    """Write data/interim/msa_year/bankunited.parquet from the bank_msa_year interim files, if any exist."""
    parts, missing = [], []
    for source, measures in MEASURES.items():
        path = config.INTERIM / "bank_msa_year" / f"{source}.parquet"
        if path.exists():
            parts.append(_footprint(path, measures))
        else:
            missing.append((source, measures))
    if not parts:
        return None
    for source, measures in missing:  # one source built without the other: say which columns are left out
        print(f"[bankunited] data/interim/bank_msa_year/{source}.parquet isn't built yet, so msa_year has no "
              f"{', '.join(measures.values())}")
    out = parts[0]
    for part in parts[1:]:
        out = out.merge(part, on=KEYS, how="outer", validate="one_to_one")
    return write_interim(out, SOURCE, "msa_year")


if __name__ == "__main__":
    build_presence()
