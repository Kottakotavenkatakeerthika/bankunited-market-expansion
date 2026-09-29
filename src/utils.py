"""Shared helpers for every ingest script.

- fetch(), save_raw(), register_local_file(): put raw files in data/raw/<source>/
  and log each one in data/manifest.csv (URL, pull time, SHA-256, size).
- normalize_code(), standardize_keys(): keep codes as zero-padded strings.
- write_interim(): validate and save one source's cleaned output.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import pandas as pd

from src import config

MANIFEST_COLUMNS = ["source", "file", "url", "pulled_at_utc", "sha256", "bytes", "notes"]

# Code columns and their fixed widths. Identifiers are kept as unpadded strings.
CODE_WIDTHS = {"cbsa_code": 5, "county_fips": 5, "metro_division_code": 5, "state_fips": 2}
ID_COLUMNS = ("rssd_id",)

# Query parameters that carry credentials. Never written to the manifest.
SECRET_PARAMS = {"api_key", "apikey", "key", "userid", "registrationkey", "token", "access_token"}


def ensure_dirs() -> None:
    for folder in (config.RAW, config.INTERIM, config.PROCESSED, config.REFERENCE):
        folder.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------- codes and keys
def normalize_code(values, width: int | None = None) -> pd.Series:
    """Codes as strings with leading zeros kept: 1073, "1073", 1073.0 -> "01073" (width=5)."""

    def fix(value):
        if value is None or (not isinstance(value, str) and pd.isna(value)):
            return pd.NA
        text = str(value).strip()
        if text.endswith(".0") and text[:-2].isdigit():
            text = text[:-2]
        if text == "" or text.lower() in {"nan", "none", "<na>"}:
            return pd.NA
        if width and text.isdigit():
            text = text.zfill(width)
        return text

    series = values if isinstance(values, pd.Series) else pd.Series(values)
    return series.map(fix).astype("string")


def standardize_keys(df: pd.DataFrame) -> pd.DataFrame:
    """Give key columns one type everywhere, so joins can't silently miss."""
    out = df.copy()
    for column, width in CODE_WIDTHS.items():
        if column in out.columns:
            out[column] = normalize_code(out[column], width)
    for column in ID_COLUMNS:
        if column in out.columns:
            out[column] = normalize_code(out[column])
    if "year" in out.columns:
        out["year"] = pd.to_numeric(out["year"]).astype("int64")
    if "quarter_end" in out.columns:
        out["quarter_end"] = pd.to_datetime(out["quarter_end"]).dt.normalize()
    return out


# --------------------------------------------------------------- manifest
def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def redact_url(url: str) -> str:
    """Remove credentials from a URL's query string before it is printed or logged."""
    parts = urlparse(url)
    query = [
        (key, "REDACTED" if key.lower() in SECRET_PARAMS else value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunparse(parts._replace(query=urlencode(query)))


def read_manifest() -> pd.DataFrame:
    if config.MANIFEST.exists() and config.MANIFEST.stat().st_size > 0:
        return pd.read_csv(config.MANIFEST, dtype=str, keep_default_na=False)
    return pd.DataFrame(columns=MANIFEST_COLUMNS)


def record_in_manifest(source: str, path, url: str = "", notes: str = "") -> dict:
    """Add or update this file's row in data/manifest.csv, and flag it if its contents changed."""
    path = Path(path).resolve()
    try:
        relative = path.relative_to(config.RAW.resolve()).as_posix()
    except ValueError:
        raise ValueError(f"{path} is not inside {config.RAW}; raw files must live there.") from None
    entry = {
        "source": source,
        "file": relative,
        "url": redact_url(url) if url else "",
        "pulled_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sha256": sha256_file(path),
        "bytes": str(path.stat().st_size),
        "notes": notes,
    }
    manifest = read_manifest()
    same_file = (manifest["source"] == source) & (manifest["file"] == relative)
    if same_file.any():
        previous = manifest.loc[same_file].iloc[0]
        if previous["sha256"] and previous["sha256"] != entry["sha256"]:
            change = f"revised since {previous['pulled_at_utc']} (was sha256 {previous['sha256'][:12]})"
            print(f"[manifest] {relative}: contents changed, {change}")
            entry["notes"] = "; ".join(part for part in (notes, change) if part)
        manifest = manifest.loc[~same_file]
    new_row = pd.DataFrame([entry], columns=MANIFEST_COLUMNS)
    manifest = pd.concat([manifest, new_row], ignore_index=True) if len(manifest) else new_row
    manifest = manifest[MANIFEST_COLUMNS].sort_values(["source", "file"])
    config.MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    manifest.to_csv(config.MANIFEST, index=False)
    return entry


# --------------------------------------------------------------- raw files
def fetch(url: str, source: str, filename: str | None = None, *, params=None, headers=None,
          force: bool = False, notes: str = "", timeout: int = 120) -> Path:
    """Download url into data/raw/<source>/<filename> and log it in the manifest.

    Reuses the file if it's already there; pass force=True to pull it again.
    API keys passed in params are redacted from the manifest.
    """
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    name = filename or Path(urlparse(url).path).name or "download"
    dest = config.RAW / source / name
    if dest.exists() and not force:
        print(f"[fetch] {source}/{name} already downloaded (force=True to pull again)")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    retries = Retry(total=4, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504))
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))
    request_headers = {"User-Agent": config.HTTP_USER_AGENT, **(headers or {})}

    print(f"[fetch] {redact_url(url)} -> {source}/{name}")
    tmp_path = None
    try:
        with session.get(url, params=params, headers=request_headers, stream=True,
                         timeout=timeout) as response:
            if not response.ok:  # message built from the redacted URL so keys never show up
                raise RuntimeError(f"[fetch] {response.status_code} {response.reason} for {redact_url(response.url)}")
            handle, tmp_name = tempfile.mkstemp(dir=dest.parent, suffix=".part")
            tmp_path = Path(tmp_name)
            with os.fdopen(handle, "wb") as out:
                for chunk in response.iter_content(chunk_size=1 << 20):
                    out.write(chunk)
            final_url = response.url
        tmp_path.replace(dest)
        tmp_path = None
    except requests.RequestException as error:  # default messages include the full URL and key
        raise RuntimeError(f"[fetch] {type(error).__name__} for {redact_url(url)}; "
                           "check the URL and your connection") from None
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()
    record_in_manifest(source, dest, url=final_url, notes=notes)
    return dest


def save_raw(content, source: str, filename: str, url: str = "", notes: str = "") -> Path:
    """Save a response you fetched another way (e.g. an API that needs a POST) and log it."""
    dest = config.RAW / source / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    record_in_manifest(source, dest, url=url, notes=notes)
    return dest


def register_local_file(path, source: str, url: str = "", notes: str = "") -> dict:
    """Log a file you downloaded by hand (e.g. from a web form). Put it in data/raw/<source>/ first."""
    path = Path(path).resolve()
    folder = (config.RAW / source).resolve()
    if folder not in path.parents:
        raise ValueError(f"Move {path.name} into {folder} before registering it.")
    return record_in_manifest(source, path, url=url, notes=notes or "downloaded by hand")


# --------------------------------------------------------------- interim and processed
def write_interim(df: pd.DataFrame, source: str, table: str) -> Path:
    """Validate one source's cleaned output and save it to data/interim/<table>/<source>.parquet.

    Rules: every key column present and filled, one row per key, and every other
    column named <source>_<measure>, so columns from different sources never collide.
    """
    if table not in config.TABLES:
        raise ValueError(f"Unknown table {table!r}; expected one of {list(config.TABLES)}")
    keys = config.TABLES[table]
    missing = [key for key in keys if key not in df.columns]
    if missing:
        raise ValueError(f"{source}: missing key columns {missing} for {table}")
    null_keys = [key for key in keys if df[key].isna().any()]
    if null_keys:
        raise ValueError(f"{source}: null values in key columns {null_keys}")
    misnamed = [col for col in df.columns if col not in keys and not col.startswith(f"{source}_")]
    if misnamed:
        raise ValueError(f"{source}: measure columns must start with '{source}_': {misnamed}")
    out = standardize_keys(df)
    dupes = out.duplicated(keys, keep=False)
    if dupes.any():
        example = out.loc[dupes, keys].head(3).to_dict("records")
        raise ValueError(f"{source}: {int(dupes.sum())} rows share a key in {table}, e.g. {example}")
    path = config.INTERIM / table / f"{source}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    out.sort_values(keys).reset_index(drop=True).to_parquet(path, index=False)
    print(f"[interim] {table}/{source}.parquet: {len(out):,} rows, {out.shape[1] - len(keys)} measures")
    return path


def read_processed(table: str) -> pd.DataFrame:
    """Load a processed table, e.g. read_processed("msa_year")."""
    return pd.read_parquet(config.PROCESSED / f"{table}.parquet")
