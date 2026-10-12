"""FFIEC bank-level data: Call Reports and each bank's small-business lending by metro. Owner: Austin.

Outputs:
  data/interim/bank_quarter/call.parquet        keys: rssd_id, quarter_end       measures: call_*
  data/interim/bank_msa_year/cra_bank.parquet   keys: rssd_id, cbsa_code, year   measures: cra_bank_*
                                                (not built yet: only Call Reports run so far)

Call Reports (checked 2026-10-12):
  - FDIC BankFind Suite API, financials endpoint: https://api.fdic.gov/banks/financials
    Field definitions: https://api.fdic.gov/banks/risview_properties.yaml
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
    row in docs/data_dictionary.md.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date
from pathlib import Path

import pandas as pd

from src import config
from src.ingest_fdic import KEY_HINT
from src.utils import fetch, normalize_code, redact_url, write_interim

SOURCE_CALL = "call"
SOURCE_CRA_BANK = "cra_bank"

# --------------------------------------------------------------- Call Reports
API_URL = "https://api.fdic.gov/banks/financials"
PAGE_SIZE = 10_000  # the API's maximum rows per request
PAUSE_SECONDS = 0.5  # between live requests, to stay well under FDIC's rate limits
RECENT_DAYS = 200  # quarters that ended this recently are pulled again on every run

ID_FIELDS = ["CERT", "REPDTE", "RSSDID", "RSSDHCR", "NAMEFULL", "NAME", "NAMEHCR", "STALP"]
REQUIRED_FIELDS = ["CERT", "REPDTE", "RSSDID"]

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
    "LNAG": "call_agricultural_loans_usd",
    "LNCON": "call_consumer_loans_usd",
    "SC": "call_securities_usd",
    "NCLNLS": "call_noncurrent_loans_usd",
    "EQ": "call_equity_capital_usd_net",
    # Income for the quarter alone
    "NIMQ": "call_quarter_net_interest_income_usd_net",
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


def _pull_quarter(stamp: str) -> Path:
    """Download one quarter (replacing any earlier copy) and make sure it holds every bank FDIC counts."""
    params = {**_base_params(), "filters": f"REPDTE:{stamp}",
              "fields": ",".join(ID_FIELDS + list(CALL_FIELDS)),
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
            paths.append(path)  # checked against FDIC's count when it was pulled
            continue
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
    for optional in ID_FIELDS:
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


def transform_call(paths: list[Path], years: list[int]) -> Path:
    """Saved quarters -> data/interim/bank_quarter/call.parquet."""
    banks = build_bank_quarter(_read_banks(paths))
    banks = banks.loc[banks["quarter_end"].dt.year >= min(years)]
    per_quarter = banks.groupby("quarter_end").size()
    print(f"[call] {len(per_quarter)} quarters, {per_quarter.index.min():%Y-%m-%d} to "
          f"{per_quarter.index.max():%Y-%m-%d}; {per_quarter.iloc[-1]:,} banks in the latest")
    return write_interim(banks, SOURCE_CALL, "bank_quarter")


# --------------------------------------------------------------- interface
def download(years: list[int], force: bool = False) -> list[Path]:
    """Pull Call Report quarters into data/raw/call/. Small-business lending isn't built yet."""
    return download_call(years, force=force)


def transform(paths: list[Path], years: list[int]) -> list[Path]:
    """Save bank_quarter with write_interim(df, SOURCE_CALL, ...)."""
    call_paths = [Path(path) for path in paths if Path(path).parent.name == SOURCE_CALL]
    if not call_paths:
        raise ValueError("ffiec: no raw files to transform; did download() run first?")
    return [transform_call(call_paths, years)]


def run(years: list[int] | None = None, force: bool = False) -> list[Path]:
    years = list(years or config.YEARS)
    return transform(download(years, force=force), years)


if __name__ == "__main__":
    run()
