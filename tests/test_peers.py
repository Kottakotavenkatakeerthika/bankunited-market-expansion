"""Peer organizations and bank identifiers (plan task T45)."""
import pandas as pd
import pytest

from src import checks, config, peers

REAL_LISTINGS = config.HOLDER_LISTINGS
REAL_PEERS = config.PEER_ORGANIZATIONS
TYPES = {"holding company", "bank, no holding company", "insured branch of a foreign bank", "foreign parent",
         "mutual holding company"}


def bank(rssd, holder, assets_b, cert, quarter="2026-06-30", name=None, holder_name=None):
    return {"rssd_id": rssd, "quarter_end": pd.Timestamp(quarter), "call_cert": cert,
            "call_bank_name": name or f"Bank {rssd}", "call_top_holder_rssd_id": holder,
            "call_top_holder_name": holder_name or f"Holder {holder}", "call_total_assets_usd": assets_b * 1e9}


BANKS = pd.DataFrame([
    bank("11", "100", 5.0, "901"), bank("12", "100", 6.0, "902"),  # two banks, $11B together: in the band
    bank("21", "200", 9.9, "903"),                                    # just under $10B: out
    bank("31", "300", 100.0, "904"),                                  # exactly $100B: in (the band includes its ends)
    bank("41", "400", 120.0, "905"),                                  # over $100B: out
    bank("51", "51", 20.0, "906", name="Solo Bank", holder_name="Solo Bank"),  # no holding company: its own holder
    bank("11", "100", 50.0, "901", quarter="2026-03-31"),             # another quarter: ignored
])


def test_organizations_are_top_holders_summed_over_their_banks():
    listings = pd.DataFrame({"top_holder_rssd_id": ["100", "51"], "organization_type": ["holding company", "bank, no holding company"],
                             "ticker": ["HLD", ""], "exchange": ["NYSE", ""], "sec_cik": ["123", ""], "sec_name": ["HOLDER 100 INC", ""],
                             "listing_note": ["", "Privately held"]})
    out = peers.peer_organizations(BANKS, "2026-06-30", listings)
    assert list(out["top_holder_rssd_id"]) == ["300", "51", "100"]  # largest first
    assert set(out["as_of"]) == {"2026-06-30"}
    holder = out.set_index("top_holder_rssd_id").loc["100"]
    assert holder["total_assets_usd"] == pytest.approx(11e9) and holder["bank_count"] == 2
    assert (holder["bank_rssd_ids"], holder["fdic_certs"]) == ("12;11", "902;901")  # largest bank first
    assert holder["largest_bank_name"] == "Bank 12" and holder["ticker"] == "HLD"
    assert pd.isna(out.set_index("top_holder_rssd_id").loc["300", "ticker"])  # no listing row yet


def test_build_writes_the_file_and_names_holders_without_a_listing(project, capsys):
    BANKS.to_parquet(project["PROCESSED"] / "bank_quarter.parquet", index=False)
    pd.DataFrame({"top_holder_rssd_id": ["100"], "top_holder_name": ["Holder 100"], "organization_type": ["holding company"],
                  "ticker": ["HLD"], "exchange": ["NYSE"], "sec_cik": ["123"], "sec_name": ["HOLDER 100 INC"],
                  "listing_note": [""], "checked": ["2026-10-26"]}).to_csv(project["HOLDER_LISTINGS"], index=False)

    path = peers.build()  # the latest quarter by default
    out = capsys.readouterr().out
    assert "3 organizations with $10B-$100B at 2026-06-30 (4 banks, 1 with a ticker)" in out
    assert "300 Holder 300 is in the peer band but has no row in holder_listings.csv" in out
    assert "51 Solo Bank is in the peer band" in out
    written = pd.read_csv(path, dtype=str)
    assert list(written["top_holder_rssd_id"]) == ["300", "51", "100"]


def test_the_committed_listings_cover_every_committed_peer_organization():
    listings = pd.read_csv(REAL_LISTINGS, dtype=str, keep_default_na=False)
    peer_file = pd.read_csv(REAL_PEERS, dtype=str, keep_default_na=False)
    assert listings["top_holder_rssd_id"].is_unique
    assert set(peer_file["top_holder_rssd_id"]) <= set(listings["top_holder_rssd_id"])
    assert set(listings["organization_type"]) <= TYPES
    # Every holder either has a ticker or says why not, and every CIK comes with a ticker
    assert ((listings["ticker"] != "") | (listings["listing_note"] != "")).all()
    assert (listings.loc[listings["sec_cik"] != "", "ticker"] != "").all()
    if set(peer_file["as_of"]) == {"2026-06-30"}:
        assert len(peer_file) == 126  # the plan's peer band at 6/30/26, confirmed by the sponsor 10/19


def calls(*rows):
    return pd.DataFrame([{"rssd_id": r, "quarter_end": pd.Timestamp(q), "call_cert": c} for r, q, c in rows])


def test_a_cert_shared_by_two_banks_in_one_quarter_fails():
    bank_quarter = calls(("1", "2023-06-30", "901"), ("2", "2023-06-30", "901"), ("1", "2023-09-30", "901"))
    result = next(r for r in checks.identifier_checks(bank_quarter, pd.DataFrame({"rssd_id": [], "year": []}))
                  if r.check == "each FDIC cert belongs to one RSSD ID per quarter")
    assert not result.passed and result.level == "error"
    assert result.detail == "1 cert-quarters, e.g. cert 901 on 2023-06-30"


def test_gaps_between_sources_are_warnings_with_counts():
    bank_quarter = calls(("1", "2023-06-30", "901"), ("2", "2023-06-30", "902"), ("2", "2022-12-31", "902"))
    bank_msa_year = pd.DataFrame({
        "rssd_id": ["1", "1", "2", "3", "2", "4"],
        "cbsa_code": ["16740", "13820", "16740", "16740", "16740", "16740"],
        "year": [2023, 2023, 2023, 2023, 2022, 2021],
        "sod_cert": ["901", "999", "902", "903", None, None],  # 999 isn't bank 1's June cert; bank 3 files no Call Report
        "cra_bank_small_business_loan_count": [None, None, None, None, 4, 2],  # bank 4 filed none in 2021
    })
    results = {r.check: r for r in checks.identifier_checks(bank_quarter, bank_msa_year)}
    assert results["each FDIC cert belongs to one RSSD ID per quarter"].passed
    cert = results["SOD certs match the bank's June 30 Call Report cert"]
    assert (cert.passed, cert.level, cert.detail) == (False, "warning", "1 bank-metro-years, e.g. RSSD 1 2023")
    assert results["every SOD bank has a June 30 Call Report"].detail == "1 bank-years, e.g. RSSD 3 2023"
    assert results["every CRA lender filed a Call Report that year"].detail == "1 lender-years, e.g. RSSD 4 2021"
    assert all(r.level == "warning" for name, r in results.items() if name.startswith(("SOD", "every SOD", "every CRA")))
