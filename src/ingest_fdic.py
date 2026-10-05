"""FDIC Summary of Deposits (SOD): every FDIC-insured office's deposits, as of June 30. Owner: Austin.

Outputs:
  data/interim/msa_year/sod.parquet        keys: cbsa_code, year            measures: sod_*
  data/interim/bank_msa_year/sod.parquet   keys: rssd_id, cbsa_code, year   measures: sod_*

bank_msa_year is the bridge that connects bank-level Call Report data to metros.

Source (checked 2026-10-04):
  - FDIC BankFind Suite API, SOD endpoint: https://api.fdic.gov/banks/sod
    Field definitions: https://api.fdic.gov/banks/docs//sod_variables_definitions.csv
  - The API returns at most 10,000 rows per request, so each year is pulled one
    state at a time (raw/sod/<year>/<state>.json). No state comes close to
    10,000 offices; if one ever does, download() stops and says so. Each year's
    rows are checked against the API's national count for that year.
  - API key: FDIC's docs call it optional, but current API clients report that
    requests without one are refused. Get a free key at https://api.data.gov/signup/
    and set FDIC_API_KEY in .env. fetch() keeps it out of the manifest.
  - Fields: YEAR, CERT, RSSDID, RSSDHCR (top regulatory holding company, 0 = none),
    NAMEFULL, NAMEHCR, BRNUM, UNINUMBR, BKMO (1 = main office), BRSERTYP (service
    type: 11 = full-service brick and mortar, 12 = full-service retail office),
    STALPBR, STCNTYBR (branch state + county FIPS), DEPSUMBR (branch deposits,
    in $1,000s: converted to whole dollars), MSABR (FDIC's own metro code, used
    only as a cross-check on our crosswalk).

Known issue, flagged for the modeling sub-pod: banks report deposits where they
are booked, and large banks book non-local deposits (big commercial accounts,
online accounts) at their main office. Headquarters metros look far bigger and
far more concentrated than they are; Charlotte is the extreme case. The
as-reported columns match FDIC's published figures, and sod_main_office_deposits_usd
isolates the booked-at-headquarters part so an adjustment can be chosen later.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pandas as pd

from src import config
from src.crosswalk import load_crosswalk
from src.utils import fetch, normalize_code, redact_url, write_interim

SOURCE = "sod"
API_URL = "https://api.fdic.gov/banks/sod"
PAGE_SIZE = 10_000  # the API's maximum rows per request
PAUSE_SECONDS = 0.5  # between live requests, to stay well under FDIC's rate limits

FIELDS = [
    "YEAR", "CERT", "RSSDID", "RSSDHCR", "NAMEFULL", "NAMEHCR", "BRNUM", "UNINUMBR",
    "BKMO", "BRSERTYP", "STALPBR", "STCNTYBR", "DEPSUMBR", "MSABR",
]
REQUIRED_FIELDS = ["YEAR", "CERT", "RSSDID", "BRNUM", "BKMO", "STCNTYBR", "DEPSUMBR"]

# 50 states, DC, and the territories SOD covers. Rows in any other code show up
# as a gap against the national count.
STATE_CODES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL",
    "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE",
    "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD",
    "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "PR", "VI", "GU", "AS", "MP", "FM", "MH", "PW",
]

FULL_SERVICE_BRANCH_TYPES = [11, 12]  # brick and mortar, retail office

KEY_HINT = ("FDIC's API may be refusing requests without a key: get a free one at "
            "https://api.data.gov/signup/ and set FDIC_API_KEY in .env")


# --------------------------------------------------------------- download
def _base_params() -> dict:
    params = {"format": "json"}
    if config.FDIC_API_KEY:
        params["api_key"] = config.FDIC_API_KEY
    return params


def _with_hint(error: Exception) -> Exception:
    """Add advice about the API key, but only when FDIC refused the request (401 or 403)."""
    if not re.match(r"\[(fetch|sod)\] (401|403) ", str(error)):
        return error
    hint = KEY_HINT if not config.FDIC_API_KEY else "check FDIC_API_KEY in .env"
    return RuntimeError(f"{error} ({hint})")


def _read_page(path: Path) -> tuple[list[dict], int]:
    """Rows and the API's total count from one saved response."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        rows = [item.get("data", item) for item in payload["data"]]
        meta = payload.get("meta") or {}
        total = meta.get("total", (payload.get("totals") or {}).get("count"))
        return rows, int(total)
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError(f"{path.name} isn't a valid SOD API response ({type(error).__name__}: {error})") from None


def _national_total(year: int) -> int:
    """How many SOD rows FDIC has for this year, from a one-row request that isn't saved."""
    import requests

    params = {**_base_params(), "filters": f"YEAR:{year}", "limit": 1}
    try:
        response = requests.get(API_URL, params=params, timeout=60,
                                headers={"User-Agent": config.HTTP_USER_AGENT})
    except requests.RequestException as error:
        raise _with_hint(RuntimeError(f"[sod] {type(error).__name__} for {redact_url(API_URL)}")) from None
    if not response.ok:
        raise _with_hint(RuntimeError(f"[sod] {response.status_code} {response.reason} "
                                      f"for {redact_url(response.url)}"))
    try:
        payload = response.json()
        meta = payload.get("meta") or {}
        return int(meta.get("total", (payload.get("totals") or {}).get("count")))
    except (ValueError, TypeError, AttributeError):
        raise RuntimeError(f"[sod] unexpected response for {year}: {response.text[:200]!r}") from None


def _pull_state(year: int, state: str, force: bool) -> Path:
    filename = f"{year}/{state}.json"
    cached = (config.RAW / SOURCE / filename).exists() and not force
    # Quoted, because Oregon's code OR is also an operator in the API's filter syntax
    params = {**_base_params(), "filters": f'YEAR:{year} AND STALPBR:"{state}"',
              "fields": ",".join(FIELDS), "limit": PAGE_SIZE, "offset": 0}
    try:
        path = fetch(API_URL, SOURCE, filename=filename, params=params, force=force,
                     notes=f"FDIC Summary of Deposits {year}, offices in {state}")
    except RuntimeError as error:
        raise _with_hint(error) from None
    if not cached:
        time.sleep(PAUSE_SECONDS)
    try:
        rows, total = _read_page(path)
    except ValueError:
        path.unlink(missing_ok=True)  # so the next run pulls it again instead of reusing it
        raise
    if total > len(rows):
        raise ValueError(f"[sod] {year} {state}: {total:,} offices don't fit in one {PAGE_SIZE:,}-row "
                         "request; split this state's pull (e.g. by county) before rerunning")
    return path


def download(years: list[int], force: bool = False) -> list[Path]:
    """Pull each year's offices, one state per request, into data/raw/sod/<year>/<state>.json."""
    paths = []
    for year in years:
        folder = config.RAW / SOURCE / str(year)
        complete = all((folder / f"{state}.json").exists() for state in STATE_CODES)
        if complete and not force:
            print(f"[sod] {year}: all {len(STATE_CODES)} state files already downloaded (force=True to pull again)")
            paths += [folder / f"{state}.json" for state in STATE_CODES]
            continue

        expected = _national_total(year)
        if expected == 0:
            print(f"[sod] skipping {year}: FDIC hasn't published the June 30, {year} survey")
            continue
        year_paths = [_pull_state(year, state, force) for state in STATE_CODES]
        pulled = sum(_read_page(path)[1] for path in year_paths)
        if pulled != expected:
            print(f"[sod] WARNING {year}: pulled {pulled:,} offices but FDIC reports {expected:,}; "
                  "the rest are in a state code missing from STATE_CODES")
        else:
            print(f"[sod] {year}: {pulled:,} offices pulled, matching FDIC's national count")
        paths += year_paths

    if not paths:
        raise RuntimeError(f"[sod] FDIC returned no rows for any of {years}; check the API before rerunning")
    return paths


# --------------------------------------------------------------- transform
def _read_offices(paths: list[Path]) -> pd.DataFrame:
    """One row per office per year, with codes as strings and deposits in whole dollars."""
    frames = [frame for frame in (pd.DataFrame(_read_page(path)[0]) for path in paths) if len(frame)]
    if not frames:
        raise ValueError("sod: the raw files hold no offices")
    raw = pd.concat(frames, ignore_index=True)
    missing = [field for field in REQUIRED_FIELDS if field not in raw.columns]
    if missing:
        raise ValueError(f"sod: API responses are missing fields {missing}; has FDIC renamed them?")
    for optional in ("RSSDHCR", "NAMEFULL", "NAMEHCR", "BRSERTYP", "MSABR"):
        if optional not in raw.columns:
            raw[optional] = pd.NA

    def no_zero(codes: pd.Series) -> pd.Series:  # FDIC writes 0 for "none"
        return codes.mask(codes.eq("0").fillna(False))

    def text(values: pd.Series) -> pd.Series:
        out = values.astype("string").str.strip()
        return out.mask(out.eq("").fillna(False))

    offices = pd.DataFrame({
        "year": pd.to_numeric(raw["YEAR"]).astype("int64"),
        "cert": no_zero(normalize_code(raw["CERT"])),
        "brnum": normalize_code(raw["BRNUM"]),
        "rssd_id": no_zero(normalize_code(raw["RSSDID"])),
        "hc_rssd_id": no_zero(normalize_code(raw["RSSDHCR"])),
        "bank_name": text(raw["NAMEFULL"]),
        "hc_name": text(raw["NAMEHCR"]),
        "main_office": pd.to_numeric(raw["BKMO"], errors="coerce").eq(1).fillna(False).astype(bool),
        "service_type": pd.to_numeric(raw["BRSERTYP"], errors="coerce"),
        "county_fips": normalize_code(raw["STCNTYBR"], 5),
        "deposits_usd": pd.to_numeric(raw["DEPSUMBR"], errors="coerce") * 1000,
        "fdic_cbsa": normalize_code(raw["MSABR"], 5).replace("00000", pd.NA),  # 0 = not in a metro
    })
    unreadable = int((offices["deposits_usd"].isna() & raw["DEPSUMBR"].notna()).sum())
    if unreadable:
        print(f"[sod] {unreadable:,} offices have a deposit value that isn't a number; left empty")

    exact = offices.duplicated(keep="first")
    if exact.any():
        print(f"[sod] dropped {int(exact.sum()):,} exact duplicate rows")
        offices = offices.loc[~exact]
    clash = offices.duplicated(["year", "cert", "brnum"], keep=False)
    if clash.any():
        example = offices.loc[clash, ["year", "cert", "brnum"]].head(3).to_dict("records")
        raise ValueError(f"sod: {int(clash.sum())} rows share year + CERT + BRNUM with different values, e.g. {example}")
    return offices.reset_index(drop=True)


def _to_metros(offices: pd.DataFrame) -> pd.DataFrame:
    """Attach each office's metro through the crosswalk, report what falls outside, keep metro offices."""
    xwalk = load_crosswalk(metro_only=True)[["county_fips", "cbsa_code"]]
    all_counties = set(load_crosswalk(metro_only=False)["county_fips"])
    mapped = offices.merge(xwalk, on="county_fips", how="left", validate="many_to_one")

    for year, group in mapped.groupby("year"):
        in_metro = group["cbsa_code"].notna()
        both = group.dropna(subset=["cbsa_code", "fdic_cbsa"])
        agree = f"{(both['cbsa_code'] == both['fdic_cbsa']).mean():.1%}" if len(both) else "n/a"
        line = (f"[sod] {year}: {len(group):,} offices, {int(in_metro.sum()):,} in metros "
                f"({group.loc[in_metro, 'deposits_usd'].sum() / max(group['deposits_usd'].sum(), 1):.1%} of deposits); "
                f"FDIC's own metro code agrees for {agree}")
        connecticut = group["county_fips"].str.startswith("09", na=False) & ~group["county_fips"].isin(all_counties)
        if connecticut.any():
            line += (f"; {int(connecticut.sum()):,} Connecticut offices use pre-2022 county codes "
                     "the crosswalk doesn't have and are left out (known limitation)")
        print(line)
    return mapped.dropna(subset=["cbsa_code"]).reset_index(drop=True)


def _summarize(data: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Deposit and office measures shared by both outputs, one row per key."""
    grouped = data.groupby(keys)
    return pd.DataFrame({
        "sod_deposits_usd": grouped["deposits_usd"].sum(min_count=1),  # all empty stays empty
        "sod_main_office_deposits_usd": grouped["main_office_deposits_usd"].sum(),
        "sod_offices_count": grouped.size(),
        "sod_branches_count": grouped["full_service"].sum(),
    })


def build_tables(offices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Office rows (with cbsa_code) -> (msa_year, bank_msa_year)."""
    data = offices.assign(
        main_office_deposits_usd=offices["deposits_usd"].where(offices["main_office"], 0),
        full_service=offices["service_type"].isin(FULL_SERVICE_BRANCH_TYPES),
    )

    metro = _summarize(data, ["cbsa_code", "year"])
    metro["sod_institutions_count"] = data.groupby(["cbsa_code", "year"])["cert"].nunique()
    metro = metro.reset_index()

    no_id = data["rssd_id"].isna()
    if no_id.any():
        print(f"[sod] {int(no_id.sum()):,} metro offices have no RSSD ID: counted in metro totals, "
              "left out of bank_msa_year")
    banked = data.loc[~no_id]
    keys = ["rssd_id", "cbsa_code", "year"]
    names = banked.groupby(keys)[["cert", "bank_name", "hc_rssd_id", "hc_name"]].first()  # first non-empty value
    bank = _summarize(banked, keys).join(names).reset_index()
    bank["sod_cert"] = bank.pop("cert").astype("string")
    bank["sod_bank_name"] = bank.pop("bank_name").astype("string")
    # A bank with no holding company is its own top holder, so grouping by this column never drops a bank
    bank["sod_top_holder_rssd_id"] = bank.pop("hc_rssd_id").fillna(bank["rssd_id"]).astype("string")
    bank["sod_top_holder_name"] = bank.pop("hc_name").fillna(bank["sod_bank_name"]).astype("string")

    # Share of everything deposited in the metro, including offices without an RSSD ID
    totals = metro[["cbsa_code", "year", "sod_deposits_usd"]].rename(columns={"sod_deposits_usd": "metro_usd"})
    bank = bank.merge(totals, on=["cbsa_code", "year"], how="left", validate="many_to_one")
    bank["sod_deposit_share"] = (bank["sod_deposits_usd"] / bank.pop("metro_usd").where(lambda s: s > 0)).astype("float64")

    count_columns = ["sod_offices_count", "sod_branches_count"]
    metro[count_columns + ["sod_institutions_count"]] = metro[count_columns + ["sod_institutions_count"]].astype("int64")
    bank[count_columns] = bank[count_columns].astype("int64")
    bank_columns = keys + ["sod_cert", "sod_bank_name", "sod_top_holder_rssd_id", "sod_top_holder_name",
                           "sod_deposits_usd", "sod_main_office_deposits_usd", "sod_offices_count",
                           "sod_branches_count", "sod_deposit_share"]
    return metro, bank[bank_columns]


def transform(paths: list[Path], years: list[int]) -> list[Path]:
    """Office rows -> metro x year and bank x metro x year; save both with write_interim()."""
    if not paths:
        raise ValueError("sod: no raw files to transform; did download() run first?")
    offices = _read_offices(paths)
    offices = offices.loc[offices["year"].isin(years)]
    metro, bank = build_tables(_to_metros(offices))
    return [write_interim(metro, SOURCE, "msa_year"), write_interim(bank, SOURCE, "bank_msa_year")]


def run(years: list[int] | None = None, force: bool = False) -> list[Path]:
    years = list(years or config.YEARS)
    return transform(download(years, force=force), years)


if __name__ == "__main__":
    run()
