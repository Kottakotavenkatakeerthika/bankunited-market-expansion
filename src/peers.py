"""The peer set's organizations and their identifiers (plan task T45). Owner: Austin.

    python -m src.peers                       # the latest quarter in bank_quarter
    python -m src.peers --quarter 2026-06-30

Writes data/reference/peer_organizations.csv: one row per organization whose banks' total
assets add up to the peer band (config.PEER_ASSETS_USD, $10B-$100B, confirmed by the sponsor
10/19) at one quarter end. An organization is a bank's top holding company
(call_top_holder_rssd_id in bank_quarter), or the bank itself if it has none, the same grouping
as everywhere else in the pipeline. Each row lists the organization's banks with their Federal
Reserve RSSD IDs and FDIC certificate numbers, largest bank first, so the identifier systems
line up in one place.

Tickers and SEC CIKs come from data/reference/holder_listings.csv, one row per top holder,
checked by hand against SEC's company ticker list
(https://www.sec.gov/files/company_tickers_exchange.json) and each company's SEC filings: the
SEC's business address state matches FDIC's holding company state, and the SEC industry code is
a financial one. The ticker is the listed common stock (or ADR), never a listed note or preferred
issue that SEC files under the same CIK. Its listing_note says why a holder has no ticker
(privately held, mutual, or a foreign parent without a U.S. listing), or whose ticker it is when
the listed company isn't the top holder itself (a non-bank parent, or a listed company the top
holder controls). ticker_owner says the same in one word for filtering: holding company, bank,
nonbank parent, foreign parent or controlled company. organization_type separates the six
insured U.S. branches of foreign banks (FFIEC 002 filers), which aren't stand-alone banks, from
the holding companies and banks.

After a new quarter, a holder that enters the band without a row in holder_listings.csv is
printed, so a row can be added before the file is used.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src import config

LISTING_COLUMNS = ["organization_type", "ticker", "ticker_owner", "exchange", "sec_cik", "sec_name", "listing_note"]
TICKER_OWNERS = {"holding company", "bank", "nonbank parent", "foreign parent", "controlled company"}


def peer_organizations(bank_quarter: pd.DataFrame, quarter_end, listings: pd.DataFrame | None = None) -> pd.DataFrame:
    """Organizations in the peer band at quarter_end, with their banks' IDs and their listing."""
    quarter_end = pd.Timestamp(quarter_end)
    banks = bank_quarter.loc[pd.to_datetime(bank_quarter["quarter_end"]) == quarter_end]
    if banks.empty:
        raise ValueError(f"peers: bank_quarter has no rows for {quarter_end:%Y-%m-%d}")
    banks = banks.sort_values(["call_total_assets_usd", "rssd_id"], ascending=[False, True])
    grouped = banks.groupby("call_top_holder_rssd_id", sort=False)
    out = pd.DataFrame({
        "top_holder_name": grouped["call_top_holder_name"].first(),
        "total_assets_usd": grouped["call_total_assets_usd"].sum(min_count=1),
        "bank_count": grouped["rssd_id"].nunique(),
        "largest_bank_name": grouped["call_bank_name"].first(),
        "bank_rssd_ids": grouped["rssd_id"].agg(";".join),
        "fdic_certs": grouped["call_cert"].agg(lambda certs: ";".join(certs.fillna(""))),
    })
    low, high = config.PEER_ASSETS_USD
    out = out.loc[out["total_assets_usd"].between(low, high)].rename_axis("top_holder_rssd_id").reset_index()
    if listings is not None:
        listings = listings.astype({"top_holder_rssd_id": "string"})[["top_holder_rssd_id", *LISTING_COLUMNS]]
        out = out.merge(listings, on="top_holder_rssd_id", how="left", validate="one_to_one")
    out.insert(0, "as_of", quarter_end.date().isoformat())
    return out.sort_values("total_assets_usd", ascending=False, ignore_index=True)


def read_listings(path: Path | None = None) -> pd.DataFrame:
    return pd.read_csv(path or config.HOLDER_LISTINGS, dtype=str, keep_default_na=False)


def build(quarter_end=None) -> Path:
    """Write data/reference/peer_organizations.csv from the processed bank_quarter table."""
    bank_quarter = pd.read_parquet(config.PROCESSED / "bank_quarter.parquet")
    quarter_end = pd.Timestamp(quarter_end) if quarter_end else pd.to_datetime(bank_quarter["quarter_end"]).max()
    listings = read_listings()
    peers = peer_organizations(bank_quarter, quarter_end, listings)
    unlisted = peers.loc[~peers["top_holder_rssd_id"].isin(listings["top_holder_rssd_id"])]
    for row in unlisted.itertuples():
        print(f"[peers] {row.top_holder_rssd_id} {row.top_holder_name} is in the peer band but has no row in "
              f"{config.HOLDER_LISTINGS.name}: add its listing")
    peers.to_csv(config.PEER_ORGANIZATIONS, index=False)
    print(f"[peers] {len(peers)} organizations with ${config.PEER_ASSETS_USD[0] / 1e9:,.0f}B-"
          f"${config.PEER_ASSETS_USD[1] / 1e9:,.0f}B at {quarter_end:%Y-%m-%d} "
          f"({int(peers['bank_count'].sum())} banks, {int((peers['ticker'].fillna('') != '').sum())} with a ticker)")
    return config.PEER_ORGANIZATIONS


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quarter", help="quarter end, YYYY-MM-DD (default: the latest in bank_quarter)")
    build(parser.parse_args().quarter)
