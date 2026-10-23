"""FFIEC bank-level data: Call Reports and each bank's small-business lending by metro. Owner: Austin.

Outputs:
  data/interim/bank_quarter/call.parquet        keys: rssd_id, quarter_end       measures: call_*
  data/interim/bank_msa_year/cra_bank.parquet   keys: rssd_id, cbsa_code, year   measures: cra_bank_*

Call Reports (checked 2026-10-12):
  - FDIC BankFind Suite API, financials endpoint: https://api.fdic.gov/banks/financials
    Field definitions: https://api.fdic.gov/banks/docs/risview_properties.yaml
  - FDIC posts every insured institution's Call Report with the FFIEC 031, 041
    and 051 forms already lined up, so this uses the API instead of the CDR bulk
    files an earlier draft of this file suggested: no hand downloads, the monthly
    refresh can run unattended, and the key is the same FDIC_API_KEY SOD uses.
  - One request per quarter (filter REPDTE:<YYYYMMDD>), saved as
    raw/call/<YYYYMMDD>.json. Each file must hold as many banks as the API counts
    for that quarter, or the build stops. FDIC drops field names it doesn't
    know without saying so, so a field missing from every quarter stops it too.
  - Quarters run from the first panel year through the latest quarter FDIC has
    published, past END_YEAR, because peer benchmarking needs current figures.
    A quarter FDIC hasn't published yet is skipped. Quarters that ended within
    RECENT_DAYS are pulled again on every run, since FDIC adds late filers and
    amendments after a quarter's first release.
  - Dollar amounts come in $1,000s and are converted to whole dollars. Income,
    expense and charge-off amounts are the quarter's own figures (FDIC's ...Q
    fields), except the credit loss provision, which FDIC only publishes year to
    date. Ratios are FDIC's own, in percent; the ytd_ ones are year to date.
  - CALL_FIELDS lists every field we keep. To add one, add a line there and a
    row in docs/data_dictionary.md. The next run pulls again any saved quarter
    that was requested without it (FDIC echoes the requested fields in each
    response), so nothing needs moving aside by hand.
  - Loans over $1M (checked 2026-10-15): Schedule RC-C Part II reports C&I and
    nonfarm nonresidential loans with original amounts of $1M or less (FDIC's
    LNCI4 and LNRENR4, counts in LNCI4N and LNRENR4N). The total minus that part
    is the balance of loans over $1M. Part II counts C&I loans to U.S.
    addressees only (Part I item 4.a), so C&I to non-U.S. addressees (LNCINUS)
    comes out of the total first; FDIC leaves LNCINUS empty for banks whose form
    doesn't split C&I that way (all FFIEC 051 filers), and their Part II covers
    all their C&I, so it counts as 0 there. CALLFORM says which form a bank filed:
    FFIEC 051 filers have to report Part II only for June and December, and
    FDIC shows 0 for those that skip March and September (3,239 banks with loans
    in 2026 Q1); 214 bank-quarters from 2017 to 2023 reported anyway and are
    kept. FFIEC 002 filers (insured U.S. branches of foreign banks) don't report
    it at all, yet FDIC shows 0 in June and December. Those zeros mean "not
    reported", so they are left empty, as are the over-$1M amounts built on
    them. FFIEC 031 filers report Part II for domestic offices while their C&I
    total includes foreign offices, so their C&I over $1M includes any C&I to
    U.S. addressees booked in foreign offices.
  - Fields for the ML pod's peer measures (checked 2026-10-23 against every bank
    in 2015 Q2 and 2025 Q2): RBC is total risk-based capital (3792): it equals
    tier 1 plus tier 2 (RBCT1 + RBCT2), and RBCRWAJ is 100 x RBC / RWAJT. It is
    negative for a few insolvent banks, so its column is _usd_net. Since
    2020, banks that elect the community bank leverage ratio (CBLRIND = 1; 1,717
    banks in 2025 Q2) report no risk-based capital, and FDIC shows 0 for RBC,
    RBCRWAJ and IDT1CER; those are left empty. DEPUNA is the estimated uninsured
    deposits (RCON5597), which only banks with $1 billion or more in total
    assets report; FDIC shows 0 for the rest (99.5% of smaller banks in 2015 Q2),
    so a 0 is left empty. LNNDEPD is loans to nondepository financial
    institutions in domestic offices (J454), filled for every form since 2015;
    the consolidated version (LNNDEPC) starts later, so it isn't used. ILNQ is
    the quarter's own interest and fee income on loans (RIAD4010); banks report
    year to date, so a quarter's figure can be negative.

Small-business lending by bank (checked 2026-10-12 against FFIEC's 2015 and 2024
Disclosure and Transmittal specs, <YY>FlatDiscSpecs.pdf and <YY>FlatTransSpecs.pdf
in the folder below; the layouts are the same in both years):
  - Download: https://www.ffiec.gov/sites/default/files/data/cra/flat-files/
    <YY>exp_discl.zip (each lender's lending by county) and <YY>exp_trans.zip
    (each lender's name and RSSD ID). The original files, not the revised ones
    FFIEC posted later, so they match the aggregate files src/ingest_cra.py uses.
    FFIEC answers scripted downloads with 403 Forbidden, so download the files in
    a browser and save them in raw/cra_bank/. The next run logs any file it
    finds there that the manifest doesn't list yet.
  - Disclosure: fixed width, 145 characters, Table ID in columns 1-5. We use
    Table D1-1 (Small Business Loans by County - Originations), County Total rows
    (Report Level 40). Columns used (1-indexed, inclusive): Respondent ID 6-15,
    Agency Code 16, Activity Year 17-20, State 23-24, County 25-27, Report Level
    43-45, then count/amount pairs: under $100k (46-55/56-65), $100k-$250k
    (66-75/76-85), $250k-$1M (86-95/96-105), and loans to businesses with revenues
    under $1M (106-115/116-125). Amounts are in $1,000s. Affiliate loans
    (126-145) are left out, as the aggregate tables leave them out.
  - Transmittal: 152 characters. Respondent ID 1-10, Agency Code 11, Activity
    Year 12-15, Respondent Name 16-45, ID_RSSD 133-142.
  - Each lender gets its RSSD ID from the transmittal (Respondent ID + Agency
    Code + year), so it lines up with SOD and Call Reports. Lending by a lender
    without one still counts in metro totals and shares.
  - Every lender's lending, summed by metro, is checked against Bhavana's
    all-lender totals in data/interim/msa_year/cra.parquet (when that file
    exists). A misread column or report level would throw off most metros and
    every year's total, so the build stops if more than RECONCILE_MAX_OFF_SHARE
    of metro-years are more than RECONCILE_TOLERANCE apart, or if any year's
    total across all metros is more than RECONCILE_YEAR_TOLERANCE apart.
    Isolated gaps are printed instead. FFIEC's own 2015 files have two: Oklahoma
    City (36420) and Tulsa (46140) add up 4-6% below the aggregate totals.
  - Only CRA reporters are in these files: banks above the CRA small-bank asset
    threshold, which rises with inflation each year. Smaller banks are missing,
    not 0.
"""
from __future__ import annotations

import json
import re
import time
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd

from src import config
from src.crosswalk import counties_to_cbsa
from src.ingest_cra import CRA_LATEST_AVAILABLE_YEAR
from src.ingest_fdic import KEY_HINT
from src.utils import (fetch, normalize_code, read_manifest, redact_url, register_local_file, standardize_keys,
                       write_interim)

SOURCE_CALL = "call"
SOURCE_CRA_BANK = "cra_bank"

# --------------------------------------------------------------- Call Reports
API_URL = "https://api.fdic.gov/banks/financials"
PAGE_SIZE = 10_000  # the API's maximum rows per request
PAUSE_SECONDS = 0.5  # between live requests, to stay well under FDIC's rate limits
RECENT_DAYS = 200  # quarters that ended this recently are pulled again on every run

ID_FIELDS = ["CERT", "REPDTE", "RSSDID", "RSSDHCR", "NAMEFULL", "NAME", "NAMEHCR", "STALP", "CALLFORM"]
REQUIRED_FIELDS = ["CERT", "REPDTE", "RSSDID"]
CBLR_FLAG = "CBLRIND"  # 1 = the bank uses the community bank leverage ratio (from 2020); used, not kept
FLAG_FIELDS = [CBLR_FLAG]

# FDIC field -> our column. The column's suffix sets the unit:
#   _usd       reported in $1,000s, converted to whole dollars, never negative
#   _usd_net   the same, but can be negative (net income, equity, charge-offs net of recoveries,
#              and three fields FDIC publishes negative values for: see the dictionary)
#   _ratio     a percent exactly as FDIC publishes it; can be negative or above 100
#   _count     a count
CALL_FIELDS = {
    # Balance sheet at quarter end
    "ASSET": "call_total_assets_usd",
    "DEP": "call_total_deposits_usd",
    "DEPDOM": "call_domestic_deposits_usd",
    "DEPINS": "call_insured_deposits_usd_net",
    "COREDEP": "call_core_deposits_usd",
    "BRO": "call_brokered_deposits_usd",
    "DEPNI": "call_noninterest_bearing_deposits_usd",
    "DEPNIDOM": "call_domestic_noninterest_bearing_deposits_usd",
    "DEPUNA": "call_uninsured_deposits_usd",
    "LNLSGR": "call_total_loans_usd",
    "LNLSNET": "call_net_loans_usd",
    "LNATRES": "call_loan_loss_allowance_usd_net",
    "LNRE": "call_real_estate_loans_usd",
    "LNRECONS": "call_construction_loans_usd",
    "LNRENRES": "call_nonfarm_nonres_loans_usd",
    "LNRENROW": "call_owner_occupied_nonres_loans_usd",
    "LNRENROT": "call_other_nonres_loans_usd",
    "LNREMULT": "call_multifamily_loans_usd",
    "LNRERES": "call_residential_1_4_family_loans_usd",
    "LNREAG": "call_farmland_loans_usd",
    "LNCI": "call_ci_loans_usd",
    "LNCINUS": "call_ci_loans_non_us_addressees_usd",
    "LNAG": "call_agricultural_loans_usd",
    "LNCON": "call_consumer_loans_usd",
    "LNNDEPD": "call_nondepository_fi_loans_usd",
    "SC": "call_securities_usd",
    "NCLNLS": "call_noncurrent_loans_usd",
    "EQ": "call_equity_capital_usd_net",
    "RBC": "call_total_risk_based_capital_usd_net",
    # Loans to small businesses (Schedule RC-C Part II): original amounts of $1M or less
    "LNCI4": "call_ci_loans_1m_or_less_usd",
    "LNCI4N": "call_ci_loans_1m_or_less_count",
    "LNRENR4": "call_nonfarm_nonres_loans_1m_or_less_usd",
    "LNRENR4N": "call_nonfarm_nonres_loans_1m_or_less_count",
    # Income for the quarter alone
    "NIMQ": "call_quarter_net_interest_income_usd_net",
    "ILNQ": "call_quarter_loan_interest_income_usd_net",
    "NONIIQ": "call_quarter_noninterest_income_usd_net",
    "NONIXQ": "call_quarter_noninterest_expense_usd_net",
    "NETINCQ": "call_quarter_net_income_usd_net",
    "NTLNLSQ": "call_quarter_net_charge_offs_usd_net",
    # Year to date (FDIC has no quarterly version)
    "ELNATR": "call_ytd_credit_loss_provision_usd_net",
    # Counts at quarter end
    "NUMEMP": "call_employees_count",
    "OFFDOM": "call_domestic_offices_count",
    # Ratios: year to date, annualized by FDIC
    "ROA": "call_ytd_return_on_assets_ratio",
    "ROE": "call_ytd_return_on_equity_ratio",
    "NIMY": "call_ytd_net_interest_margin_ratio",
    "EEFFR": "call_ytd_efficiency_ratio",
    "NTLNLSR": "call_ytd_net_charge_off_ratio",
    # Ratios at quarter end
    "RBC1AAJ": "call_leverage_ratio",
    "IDT1CER": "call_cet1_ratio",
    "RBCRWAJ": "call_total_risk_based_capital_ratio",
    "LNLSDEPR": "call_loans_to_deposits_ratio",
    "NCLNLSR": "call_noncurrent_loans_ratio",
}
UNIT_SUFFIXES = ("_usd_net", "_usd", "_ratio", "_count")  # longest first: _usd_net also ends in _net

# Schedule RC-C Part II, by form (see the docstring)
SMALL_LOAN_FIELDS = ["LNCI4", "LNCI4N", "LNRENR4", "LNRENR4N"]
SEMIANNUAL_PART_II_FORM = "051"  # reports Part II for June and December only
NO_PART_II_FORM = "002"  # insured U.S. branches of foreign banks: no Part II at all
# Loans over $1M. Column -> (total, the part of the total outside Part II's scope or None,
# Part II's loans of $1M or less)
OVER_1M = {
    "call_ci_loans_over_1m_usd": (
        "call_ci_loans_usd", "call_ci_loans_non_us_addressees_usd", "call_ci_loans_1m_or_less_usd"),
    "call_nonfarm_nonres_loans_over_1m_usd": (
        "call_nonfarm_nonres_loans_usd", None, "call_nonfarm_nonres_loans_1m_or_less_usd"),
}
# Fields FDIC shows as 0 for banks that don't report them (see the docstring)
RISK_BASED_FIELDS = ["RBC", "IDT1CER", "RBCRWAJ"]  # not reported by community bank leverage ratio banks
LARGE_BANK_ONLY_FIELDS = ["DEPUNA"]  # reported only by banks with $1 billion or more in total assets


def _unit(column: str) -> str:
    unit = next((suffix for suffix in UNIT_SUFFIXES if column.endswith(suffix)), None)
    if unit is None:
        raise ValueError(f"{column} needs a unit suffix, one of {UNIT_SUFFIXES}")
    return unit


def _today() -> date:  # one place to pin the date in tests
    return date.today()


def _quarter_ends(first_year: int, through: date) -> list[date]:
    """Every quarter end from January of first_year up to (not including) through."""
    ends = [date(year, month, day) for year in range(first_year, through.year + 1)
            for month, day in ((3, 31), (6, 30), (9, 30), (12, 31))]
    return [end for end in ends if end < through]


def _base_params() -> dict:
    params = {"format": "json"}
    if config.FDIC_API_KEY:
        params["api_key"] = config.FDIC_API_KEY
    return params


def _with_hint(error: Exception) -> Exception:
    """Add advice about the API key, but only when FDIC refused the request (401 or 403)."""
    if not re.match(r"\[(fetch|call)\] (401|403) ", str(error)):
        return error
    hint = KEY_HINT if not config.FDIC_API_KEY else "check FDIC_API_KEY in .env"
    return RuntimeError(f"{error} ({hint})")


def _read_page(path: Path) -> tuple[list[dict], int]:
    """Rows and the API's count from one saved response."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        rows = [item.get("data", item) for item in payload["data"]]
        meta = payload.get("meta") or {}
        total = meta.get("total", (payload.get("totals") or {}).get("count"))
        return rows, int(total)
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError(f"{Path(path).name} isn't a valid FDIC financials response "
                         f"({type(error).__name__}: {error})") from None


def _published_count(stamp: str) -> int:
    """How many banks FDIC has for this quarter, from a one-row request that isn't saved."""
    import requests

    params = {**_base_params(), "filters": f"REPDTE:{stamp}", "fields": "CERT", "limit": 1}
    try:
        response = requests.get(API_URL, params=params, timeout=60,
                                headers={"User-Agent": config.HTTP_USER_AGENT})
    except requests.RequestException as error:
        raise _with_hint(RuntimeError(f"[call] {type(error).__name__} for {redact_url(API_URL)}")) from None
    if not response.ok:
        raise _with_hint(RuntimeError(f"[call] {response.status_code} {response.reason} "
                                      f"for {redact_url(response.url)}"))
    try:
        payload = response.json()
        meta = payload.get("meta") or {}
        return int(meta.get("total", (payload.get("totals") or {}).get("count")))
    except (ValueError, TypeError, AttributeError):
        raise RuntimeError(f"[call] unexpected response for {stamp}: {response.text[:200]!r}") from None


def _requested_fields() -> list[str]:
    return ID_FIELDS + FLAG_FIELDS + list(CALL_FIELDS)


def _fields_missing_from(path: Path) -> list[str]:
    """Fields we ask for now that weren't asked for when this quarter was saved.

    FDIC echoes the request in meta.parameters.fields. A response without that echo
    is judged by the fields it returned instead; one that can't be read counts as
    missing everything, so it's pulled again.
    """
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        asked = ((payload.get("meta") or {}).get("parameters") or {}).get("fields")
        if asked:
            had = set(str(asked).split(","))
        else:
            had = set().union(*(set(item.get("data", item)) for item in payload.get("data") or []))
    except (ValueError, TypeError, AttributeError):
        return _requested_fields()
    return [field for field in _requested_fields() if field not in had]


def _pull_quarter(stamp: str) -> Path:
    """Download one quarter (replacing any earlier copy) and make sure it holds every bank FDIC counts."""
    params = {**_base_params(), "filters": f"REPDTE:{stamp}",
              "fields": ",".join(_requested_fields()),
              "limit": PAGE_SIZE, "offset": 0, "sort_by": "CERT", "sort_order": "ASC"}
    quarter = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
    try:
        path = fetch(API_URL, SOURCE_CALL, filename=f"{stamp}.json", params=params, force=True,
                     notes=f"FDIC Call Report data (BankFind financials), quarter ending {quarter}")
    except RuntimeError as error:
        raise _with_hint(error) from None
    time.sleep(PAUSE_SECONDS)
    try:
        rows, total = _read_page(path)
    except ValueError:
        path.unlink(missing_ok=True)  # so the next run pulls it again instead of reusing it
        raise
    if total > len(rows):
        path.unlink(missing_ok=True)
        raise ValueError(f"[call] {quarter}: {total:,} banks don't fit in one {PAGE_SIZE:,}-row request; "
                         "page through the quarter (offset) before rerunning")
    return path


def download_call(years: list[int], force: bool = False) -> list[Path]:
    """Pull each published quarter from the first year on into data/raw/call/<YYYYMMDD>.json."""
    through = _today()
    paths = []
    for quarter in _quarter_ends(min(years), through):
        stamp = quarter.strftime("%Y%m%d")
        path = config.RAW / SOURCE_CALL / f"{stamp}.json"
        recent = (through - quarter).days <= RECENT_DAYS
        if path.exists() and not force and not recent:
            missing = _fields_missing_from(path)
            if not missing:
                paths.append(path)  # checked against FDIC's count when it was pulled
                continue
            print(f"[call] {quarter}: the saved copy wasn't asked for {', '.join(missing)}; pulling it again")
        if _published_count(stamp) == 0:
            if path.exists():
                print(f"[call] FDIC returned no banks for {quarter} this time; keeping the copy pulled earlier")
                paths.append(path)
            else:
                print(f"[call] skipping {quarter}: FDIC hasn't published that quarter yet")
            continue
        paths.append(_pull_quarter(stamp))
    if not paths:
        raise RuntimeError(f"[call] FDIC returned no quarters from {min(years)} on; check the API before rerunning")
    return paths


def _read_banks(paths: list[Path]) -> pd.DataFrame:
    frames = []
    for path in sorted(paths):
        rows, total = _read_page(path)
        if len(rows) != total:
            raise ValueError(f"call: {path.name} holds {len(rows):,} banks but FDIC counted {total:,}; "
                             "delete the file and rerun to pull it again")
        if rows:
            frames.append(pd.DataFrame(rows))
    if not frames:
        raise ValueError("call: the raw files hold no banks")
    raw = pd.concat(frames, ignore_index=True)
    missing = [field for field in REQUIRED_FIELDS if field not in raw.columns]
    if missing:
        raise ValueError(f"call: API responses are missing fields {missing}; has FDIC renamed them?")
    unknown = [field for field in CALL_FIELDS if field not in raw.columns]
    if unknown:
        raise ValueError(f"call: FDIC returned no {unknown} in any quarter. It drops field names it doesn't "
                         "know, so check them against https://api.fdic.gov/banks/docs/ and fix CALL_FIELDS")
    for optional in ID_FIELDS + FLAG_FIELDS:
        if optional not in raw.columns:
            raw[optional] = pd.NA
    return raw


def build_bank_quarter(raw: pd.DataFrame) -> pd.DataFrame:
    """FDIC rows -> one row per bank per quarter, codes as strings, amounts in whole dollars."""

    def no_zero(codes: pd.Series) -> pd.Series:  # FDIC writes 0 for "none"
        return codes.mask(codes.eq("0").fillna(False))

    def text(values: pd.Series) -> pd.Series:
        out = values.astype("string").str.strip()
        return out.mask(out.eq("").fillna(False))

    quarter_end = pd.to_datetime(normalize_code(raw["REPDTE"]), format="%Y%m%d", errors="coerce")
    if quarter_end.isna().any():
        bad = raw.loc[quarter_end.isna(), "REPDTE"].head(3).tolist()
        raise ValueError(f"call: report dates that aren't YYYYMMDD, e.g. {bad}")
    banks = pd.DataFrame({
        "rssd_id": no_zero(normalize_code(raw["RSSDID"])),
        "quarter_end": quarter_end,
        "call_cert": no_zero(normalize_code(raw["CERT"])),
        "call_bank_name": text(raw["NAMEFULL"]).fillna(text(raw["NAME"])),
        "call_state": text(raw["STALP"]),
        "call_report_form": normalize_code(raw["CALLFORM"], width=3),  # FFIEC 031, 041, 051 or 002
    })
    # A bank with no holding company is its own top holder, so grouping by this column never drops a bank
    banks["call_top_holder_rssd_id"] = no_zero(normalize_code(raw["RSSDHCR"])).fillna(banks["rssd_id"])
    banks["call_top_holder_name"] = text(raw["NAMEHCR"]).fillna(banks["call_bank_name"])

    for field, column in CALL_FIELDS.items():
        values = pd.to_numeric(raw[field], errors="coerce")
        unreadable = int((values.isna() & raw[field].notna()).sum())
        if unreadable:
            print(f"[call] {unreadable:,} values of {field} aren't numbers; left empty")
        unit = _unit(column)
        if unit in ("_usd", "_usd_net"):
            values = values * 1000
        elif unit == "_count":
            try:
                values = values.astype("Int64")
            except (TypeError, ValueError):  # a fractional count: keep it as published
                pass
        banks[column] = values
    banks = _blank_not_reported(banks, raw[CBLR_FLAG])
    banks = _add_over_1m(_blank_unreported_small_loans(banks))

    no_id = banks["rssd_id"].isna()
    if no_id.any():
        print(f"[call] {int(no_id.sum()):,} bank-quarters have no RSSD ID and are left out")
        banks = banks.loc[~no_id]
    exact = banks.duplicated(keep="first")
    if exact.any():
        print(f"[call] dropped {int(exact.sum()):,} exact duplicate rows")
        banks = banks.loc[~exact]
    clash = banks.duplicated(["rssd_id", "quarter_end"], keep=False)
    if clash.any():
        example = banks.loc[clash, ["rssd_id", "quarter_end"]].head(3).astype(str).to_dict("records")
        raise ValueError(f"call: {int(clash.sum())} rows share RSSD ID + quarter with different values, e.g. {example}")
    return banks.reset_index(drop=True)


def _blank_unreported_small_loans(banks: pd.DataFrame) -> pd.DataFrame:
    """Empty the Part II columns where the bank didn't report Part II that quarter.

    FDIC shows 0 there, which would read as "no small loans" and put every loan over $1M.
    An FFIEC 051 filer that reported in March or September anyway keeps its values.
    """
    columns = [CALL_FIELDS[field] for field in SMALL_LOAN_FIELDS]
    form = banks["call_report_form"]
    off_quarter = form.eq(SEMIANNUAL_PART_II_FORM).fillna(False) & banks["quarter_end"].dt.month.isin([3, 9])
    reported = banks[columns].fillna(0).ne(0).any(axis=1)
    unexpected = off_quarter & reported
    if unexpected.any():
        print(f"[call] {int(unexpected.sum()):,} FFIEC 051 bank-quarters in March or September report Part II "
              "anyway (it's required only for June and December); kept")
    blank = form.eq(NO_PART_II_FORM).fillna(False) | (off_quarter & ~reported)
    for column in columns:
        banks[column] = banks[column].mask(blank)
    return banks


def _blank_not_reported(banks: pd.DataFrame, cblr_flag: pd.Series) -> pd.DataFrame:
    """Empty the values FDIC shows as 0 for banks that don't report them.

    A community bank leverage ratio bank reports no risk-based capital, and a bank under
    $1 billion doesn't report uninsured deposits. A 0 there would read as "no capital"
    or "no uninsured deposits" and pull any average toward 0.
    """
    cblr = pd.to_numeric(cblr_flag, errors="coerce").eq(1).fillna(False)
    if cblr.any():
        print(f"[call] {int(cblr.sum()):,} bank-quarters use the community bank leverage ratio; "
              "their risk-based capital columns are left empty")
    for field in RISK_BASED_FIELDS:
        column = CALL_FIELDS[field]
        banks[column] = banks[column].mask(cblr)
    for field in LARGE_BANK_ONLY_FIELDS:
        column = CALL_FIELDS[field]
        zero = banks[column].eq(0).fillna(False)
        if zero.any():
            print(f"[call] {int(zero.sum()):,} bank-quarters show 0 for {field}, which banks under "
                  f"$1 billion don't report; {column} left empty there")
        banks[column] = banks[column].mask(zero)
    return banks


def _add_over_1m(banks: pd.DataFrame) -> pd.DataFrame:
    """Loans over $1M: the total, less any part outside Part II's scope, less Part II's $1M or less."""
    for column, (total, outside, small) in OVER_1M.items():
        in_scope = banks[total] - (banks[outside].fillna(0) if outside else 0)  # empty = form doesn't split it
        over = in_scope - banks[small]
        negative = over < 0
        if negative.any():
            print(f"[call] {int(negative.sum()):,} bank-quarters report more {small} than the loans it's part "
                  f"of; {column} left empty there")
        banks[column] = over.mask(negative)
    return banks


def transform_call(paths: list[Path], years: list[int]) -> Path:
    """Saved quarters -> data/interim/bank_quarter/call.parquet."""
    banks = build_bank_quarter(_read_banks(paths))
    banks = banks.loc[banks["quarter_end"].dt.year >= min(years)]
    per_quarter = banks.groupby("quarter_end").size()
    print(f"[call] {len(per_quarter)} quarters, {per_quarter.index.min():%Y-%m-%d} to "
          f"{per_quarter.index.max():%Y-%m-%d}; {per_quarter.iloc[-1]:,} banks in the latest")
    return write_interim(banks, SOURCE_CALL, "bank_quarter")


# --------------------------------------------------------------- small-business lending by bank
CRA_URL = "https://www.ffiec.gov/sites/default/files/data/cra/flat-files/"
SMALL_BUSINESS_ORIGINATIONS = "D1-1"  # Small Business Loans by County - Originations
COUNTY_TOTAL = 40  # Report Level of a lender's total in one county
RECONCILE_TOLERANCE = 0.02  # a metro-year this far from ingest_cra.py's total counts as off
RECONCILE_MAX_OFF_SHARE = 0.01  # the build stops if more than this share of metro-years is off
RECONCILE_YEAR_TOLERANCE = 0.005  # ...or if any year's total across all metros is this far off

# 1-indexed, inclusive positions from FFIEC's specs, as 0-indexed Python slices
DISCLOSURE = {
    "table_id": (0, 5),
    "respondent_id": (5, 15),
    "agency_code": (15, 16),
    "year": (16, 20),
    "state": (22, 24),
    "county": (24, 27),
    "report_level": (42, 45),
    "count_under_100k": (45, 55),
    "amount_under_100k": (55, 65),
    "count_100k_250k": (65, 75),
    "amount_100k_250k": (75, 85),
    "count_250k_1m": (85, 95),
    "amount_250k_1m": (95, 105),
    "count_revenue_under_1m": (105, 115),
    "amount_revenue_under_1m": (115, 125),
}
TRANSMITTAL = {
    "respondent_id": (0, 10),
    "agency_code": (10, 11),
    "year": (11, 15),
    "lender_name": (15, 45),
    "rssd_id": (132, 142),
}
MEASURES = ["loan_count", "loan_amount_usd", "revenue_under_1m_loan_count", "revenue_under_1m_loan_amount_usd"]
LENDER = ["respondent_id", "agency_code", "year"]


def _in_manifest(path: Path, source: str) -> bool:
    relative = Path(path).resolve().relative_to(config.RAW.resolve()).as_posix()
    manifest = read_manifest()
    return bool(((manifest["source"] == source) & (manifest["file"] == relative)).any())


def download_cra_bank(years: list[int], force: bool = False) -> list[Path]:
    """Pull each year's disclosure and transmittal files into data/raw/cra_bank/.

    FFIEC refuses scripted downloads (403), so the files usually arrive by hand.
    A file already in raw/cra_bank/ that the manifest doesn't list is logged as
    downloaded by hand.
    """
    paths = []
    for year in years:
        if year > CRA_LATEST_AVAILABLE_YEAR:
            print(f"[cra_bank] skipping {year}: CRA hasn't published past {CRA_LATEST_AVAILABLE_YEAR} yet")
            continue
        yy = f"{year % 100:02d}"
        for kind, what in (("discl", "disclosure flat file (each lender's lending by county)"),
                           ("trans", "transmittal sheet (lender names and RSSD IDs)")):
            filename = f"{yy}exp_{kind}.zip"
            url, notes = CRA_URL + filename, f"FFIEC CRA {what}, {year}"
            path = config.RAW / SOURCE_CRA_BANK / filename
            if path.exists() and not force and not _in_manifest(path, SOURCE_CRA_BANK):
                register_local_file(path, SOURCE_CRA_BANK, url=url, notes=f"{notes}, downloaded by hand")
            try:
                paths.append(fetch(url, SOURCE_CRA_BANK, filename=filename, force=force, notes=notes))
            except RuntimeError as error:
                if not re.match(r"\[fetch\] 403 ", str(error)):
                    raise
                raise RuntimeError(
                    f"{error}. FFIEC refuses scripted downloads: open that link (and the other "
                    "<YY>exp_discl.zip and <YY>exp_trans.zip files you need) in a browser, save the files in "
                    f"{config.RAW / SOURCE_CRA_BANK}, and rerun. The run logs them in the manifest.") from None
    return paths


def _file_year(path: Path, kind: str) -> int:
    match = re.fullmatch(rf"(\d{{2}})exp_{kind}\.zip", Path(path).name)
    if not match:
        raise ValueError(f"Can't tell what year {Path(path).name} is for; expected <YY>exp_{kind}.zip")
    return 2000 + int(match.group(1))


def _lines(path: Path):
    """Every line of every file inside a zip, as bytes without the line ending."""
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if not name.endswith("/")]
        if not members:
            raise ValueError(f"No file found inside {Path(path).name}")
        for member in members:
            with archive.open(member) as handle:
                for line in handle:
                    yield line.rstrip(b"\r\n")


def _cut(line: str, layout: dict, name: str) -> str:
    start, end = layout[name]
    return line[start:end]


def _respondent(text: str) -> str:
    """Respondent IDs are zero-padded in both files; compare them without the padding."""
    return text.strip().lstrip("0") or "0"


def _read_disclosure(path: Path) -> pd.DataFrame:
    """County Total rows of Table D1-1: each lender's small-business originations, county by county."""
    year = _file_year(path, "discl")
    prefix = SMALL_BUSINESS_ORIGINATIONS.encode()
    rows, unplaced = [], 0
    for raw in _lines(path):
        if not raw.startswith(prefix):  # cheap filter first: most of the file is other tables
            continue
        line = raw.decode("latin-1")
        if _cut(line, DISCLOSURE, "table_id").strip() != SMALL_BUSINESS_ORIGINATIONS:
            continue
        level = _cut(line, DISCLOSURE, "report_level").strip()
        if not level.isdigit() or int(level) != COUNTY_TOTAL:  # blank = a detail row, not a total
            continue
        if len(line) < DISCLOSURE["amount_revenue_under_1m"][1]:
            raise ValueError(f"{path.name}: a D1-1 row is only {len(line)} characters; has the layout changed?")
        if _cut(line, DISCLOSURE, "year") != str(year):
            raise ValueError(f"{path.name} holds rows for {_cut(line, DISCLOSURE, 'year')!r}; expected {year}")
        state, county = _cut(line, DISCLOSURE, "state").strip(), _cut(line, DISCLOSURE, "county").strip()
        if not (state.isdigit() and county.isdigit()):
            unplaced += 1
            continue

        def number(name: str) -> int:
            try:
                return int(_cut(line, DISCLOSURE, name))
            except ValueError:
                raise ValueError(f"{path.name}: {name} isn't a number in row {line[:45]!r}") from None

        rows.append({
            "respondent_id": _respondent(_cut(line, DISCLOSURE, "respondent_id")),
            "agency_code": _cut(line, DISCLOSURE, "agency_code").strip(),
            "year": year,
            "county_fips": state.zfill(2) + county.zfill(3),
            "loan_count": number("count_under_100k") + number("count_100k_250k") + number("count_250k_1m"),
            "loan_amount_usd": 1000 * (number("amount_under_100k") + number("amount_100k_250k")
                                       + number("amount_250k_1m")),
            "revenue_under_1m_loan_count": number("count_revenue_under_1m"),
            "revenue_under_1m_loan_amount_usd": 1000 * number("amount_revenue_under_1m"),
        })
    if not rows:
        raise ValueError(f"{path.name}: no County Total rows (Report Level {COUNTY_TOTAL}) in table "
                         f"{SMALL_BUSINESS_ORIGINATIONS}; has the file layout changed?")
    if unplaced:
        print(f"[cra_bank] {year}: left out {unplaced:,} county totals that have no state and county code")
    return pd.DataFrame(rows)


def _read_transmittal(path: Path) -> pd.DataFrame:
    """Each lender's name and RSSD ID that year, one row per Respondent ID + Agency Code."""
    year = _file_year(path, "trans")
    rows = []
    for raw in _lines(path):
        line = raw.decode("latin-1")
        if not line.strip():
            continue
        if len(line) < TRANSMITTAL["rssd_id"][1]:
            raise ValueError(f"{path.name}: a row is only {len(line)} characters, too short to hold ID_RSSD; "
                             "has the layout changed?")
        if _cut(line, TRANSMITTAL, "year") != str(year):
            raise ValueError(f"{path.name} holds rows for {_cut(line, TRANSMITTAL, 'year')!r}; expected {year}")
        rssd = _cut(line, TRANSMITTAL, "rssd_id").strip()
        rows.append({
            "respondent_id": _respondent(_cut(line, TRANSMITTAL, "respondent_id")),
            "agency_code": _cut(line, TRANSMITTAL, "agency_code").strip(),
            "year": year,
            "lender_name": _cut(line, TRANSMITTAL, "lender_name").strip() or pd.NA,
            "rssd_id": str(int(rssd)) if rssd.isdigit() and int(rssd) > 0 else pd.NA,
        })
    lenders = pd.DataFrame(rows).drop_duplicates()
    repeated = lenders.duplicated(LENDER, keep=False)
    if repeated.any():
        example = lenders.loc[repeated, LENDER].head(3).to_dict("records")
        raise ValueError(f"{path.name}: lenders listed twice with different details, e.g. {example}")
    return lenders


def build_cra_bank_tables(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Lender x county rows (rssd_id may be empty) -> (every lender by metro, bank_msa_year)."""
    for year, group in data.groupby("year"):
        unmatched = group.loc[group["rssd_id"].isna(), "loan_amount_usd"].sum()
        print(f"[cra_bank] {year}: {len(group[LENDER].drop_duplicates()):,} lenders, "
              f"{1 - unmatched / max(group['loan_amount_usd'].sum(), 1):.1%} of the dollars matched to an RSSD ID")
    metro_all = counties_to_cbsa(data, MEASURES, by=("year",))  # every lender, matched or not

    banked = data.dropna(subset=["rssd_id"])
    bank = counties_to_cbsa(banked, MEASURES, by=("rssd_id", "year"))
    names = banked.groupby(["rssd_id", "year"], as_index=False)["lender_name"].first()  # first non-empty
    bank = bank.merge(names, on=["rssd_id", "year"], how="left", validate="many_to_one")
    totals = metro_all[["cbsa_code", "year", "loan_amount_usd"]].rename(columns={"loan_amount_usd": "metro_usd"})
    bank = bank.merge(totals, on=["cbsa_code", "year"], how="left", validate="many_to_one")
    bank["share"] = (bank["loan_amount_usd"] / bank.pop("metro_usd").where(lambda s: s > 0)).astype("float64")

    bank = bank.rename(columns={
        "lender_name": "cra_bank_lender_name",
        "loan_count": "cra_bank_small_business_loan_count",
        "loan_amount_usd": "cra_bank_small_business_loan_amount_usd",
        "revenue_under_1m_loan_count": "cra_bank_revenue_under_1m_loan_count",
        "revenue_under_1m_loan_amount_usd": "cra_bank_revenue_under_1m_loan_amount_usd",
        "share": "cra_bank_small_business_amount_share",
    })
    for column in ("cra_bank_small_business_loan_count", "cra_bank_revenue_under_1m_loan_count"):
        bank[column] = bank[column].astype("int64")
    bank["cra_bank_lender_name"] = bank["cra_bank_lender_name"].astype("string")
    columns = ["rssd_id", "cbsa_code", "year", "cra_bank_lender_name", "cra_bank_small_business_loan_count",
               "cra_bank_small_business_loan_amount_usd", "cra_bank_revenue_under_1m_loan_count",
               "cra_bank_revenue_under_1m_loan_amount_usd", "cra_bank_small_business_amount_share"]
    return metro_all, bank[columns]


def _reconcile(metro_all: pd.DataFrame) -> None:
    """Check every lender's lending, summed by metro, against ingest_cra.py's all-lender totals."""
    path = config.INTERIM / "msa_year" / "cra.parquet"
    pairs = {"loan_count": "cra_small_business_loan_count",
             "loan_amount_usd": "cra_small_business_loan_amount_usd"}
    if not path.exists():
        print("[cra_bank] not reconciled: data/interim/msa_year/cra.parquet isn't built yet "
              "(run the cra source first)")
        return
    theirs = standardize_keys(pd.read_parquet(path))
    if not set(pairs.values()) <= set(theirs.columns):
        print(f"[cra_bank] not reconciled: cra.parquet no longer has {sorted(pairs.values())}; update _reconcile()")
        return
    theirs = theirs.loc[theirs["year"].isin(metro_all["year"].unique()), ["cbsa_code", "year", *pairs.values()]]
    both = metro_all[["cbsa_code", "year", *pairs]].merge(theirs, on=["cbsa_code", "year"], how="outer")
    both = both.fillna({column: 0 for column in [*pairs, *pairs.values()]})

    def gaps(frame: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({ours: ((frame[ours] - frame[published]) / frame[published].abs().clip(lower=1))
                             .astype("float64") for ours, published in pairs.items()})

    metro_gaps = gaps(both)
    off = both.join(metro_gaps.add_suffix("_gap")).loc[metro_gaps.abs().max(axis=1) > RECONCILE_TOLERANCE]
    year_gaps = gaps(both.groupby("year")[[*pairs, *pairs.values()]].sum()).abs().max(axis=1)
    bad_years = {int(year): f"{gap:.2%}" for year, gap in year_gaps.items() if gap > RECONCILE_YEAR_TOLERANCE}
    if len(off) > RECONCILE_MAX_OFF_SHARE * len(both) or bad_years:
        example = off[["cbsa_code", "year", *pairs, *pairs.values()]].head(3).to_dict("records")
        raise RuntimeError(
            f"[cra_bank] lenders' lending doesn't add up to ingest_cra.py's metro totals: {len(off):,} of "
            f"{len(both):,} metro-years are more than {RECONCILE_TOLERANCE:.0%} apart (e.g. {example})"
            + (f", and these years' totals are off: {bad_years}" if bad_years else "")
            + ". Gaps this widespread point to a misread column, so the build stops. Check that both read "
              f"the same FFIEC release and that table {SMALL_BUSINESS_ORIGINATIONS} and Report Level "
              f"{COUNTY_TOTAL} still mean what the docstring says.")
    for row in off.itertuples():
        print(f"[cra_bank] warning: {row.cbsa_code} in {row.year}: lenders add up to "
              f"{row.loan_count:,.0f} loans and ${row.loan_amount_usd:,.0f}, vs {row.cra_small_business_loan_count:,.0f} "
              f"and ${row.cra_small_business_loan_amount_usd:,.0f} in ingest_cra.py's totals "
              f"({row.loan_count_gap:+.1%} loans, {row.loan_amount_usd_gap:+.1%} dollars)")
    print(f"[cra_bank] lenders add up to ingest_cra.py's totals within {RECONCILE_TOLERANCE:.0%} for "
          f"{len(both) - len(off):,} of {len(both):,} metro-years; every year's total is within {year_gaps.max():.2%}")


def transform_cra_bank(paths: list[Path], years: list[int]) -> Path:
    """Lender x county rows -> bank x metro x year; save bank_msa_year with write_interim()."""
    disclosures = sorted(p for p in paths if p.name.endswith("exp_discl.zip") and _file_year(p, "discl") in years)
    transmittals = {_file_year(p, "trans"): p for p in paths if p.name.endswith("exp_trans.zip")}
    if not disclosures:
        raise ValueError("cra_bank: no disclosure files to transform; did download() run first?")
    missing = sorted({_file_year(p, "discl") for p in disclosures} - set(transmittals))
    if missing:
        raise ValueError(f"cra_bank: no transmittal file for {missing}, so those lenders can't get RSSD IDs")

    lending = pd.concat([_read_disclosure(path) for path in disclosures], ignore_index=True)
    lenders = pd.concat([_read_transmittal(transmittals[year]) for year in sorted(lending["year"].unique())],
                        ignore_index=True)
    data = lending.merge(lenders, on=LENDER, how="left", validate="many_to_one")
    metro_all, bank = build_cra_bank_tables(data)
    _reconcile(metro_all)
    return write_interim(bank, SOURCE_CRA_BANK, "bank_msa_year")


# --------------------------------------------------------------- interface
def download(years: list[int], force: bool = False) -> list[Path]:
    """Pull Call Report quarters into data/raw/call/ and CRA lender files into data/raw/cra_bank/."""
    return download_call(years, force=force) + download_cra_bank(years, force=force)


def transform(paths: list[Path], years: list[int]) -> list[Path]:
    """Save bank_quarter (SOURCE_CALL) and bank_msa_year (SOURCE_CRA_BANK) with write_interim()."""
    paths = [Path(path) for path in paths]
    call_paths = [path for path in paths if path.parent.name == SOURCE_CALL]
    cra_paths = [path for path in paths if path.parent.name == SOURCE_CRA_BANK]
    if not call_paths and not cra_paths:
        raise ValueError("ffiec: no raw files to transform; did download() run first?")
    outputs = []
    if call_paths:
        outputs.append(transform_call(call_paths, years))
    if cra_paths:
        outputs.append(transform_cra_bank(cra_paths, years))
    return outputs


def run(years: list[int] | None = None, force: bool = False) -> list[Path]:
    years = list(years or config.YEARS)
    return transform(download(years, force=force), years)


if __name__ == "__main__":
    run()
