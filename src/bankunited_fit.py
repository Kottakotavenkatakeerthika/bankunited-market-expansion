"""Exploratory industry alignment from CBP employment, without scoring side effects.

``industry_mix`` provides the calculation interface for the scoring runner. It accepts the
scoring year, selects the latest common CBP year no later than that year, and
reports both years. Pass ``as_of`` and a release ledger for historical gating;
latest revised input values are not an exact historical-vintage reconstruction.
Priorities can be supplied by the caller (including a future TOML adapter).
Priorities default to weights/baseline.toml. The utilities-only helper is retained
for compatibility.
"""
from __future__ import annotations

from pathlib import Path
import tomllib

import pandas as pd

from src import config

PRIORITIES_PATH = config.ROOT / "weights" / "baseline.toml"
DEFAULT_YEAR = 2023


def industry_mix(
    msa_naics_year: pd.DataFrame,
    msa_year: pd.DataFrame,
    scoring_year: int,
    priorities: pd.DataFrame | None = None,
    *,
    as_of=None,
    release_dates: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return High/Medium CBP footprints and coverage, one row per metro.

    Denominator: published ``msa_year.cbp_employment_count`` for the chosen
    industry year. Numerators require every sector in the inclusion group;
    missing sectors never become zero. Partial sums are separate diagnostics.
    No ranking, imputation, eligibility filter, or production integration occurs.

    Select one common year for all metros, not different fallback years per
    metro. The latest year with any reported employment in both input tables,
    <= scoring_year (and <= as_of.year when supplied), is used. With as_of,
    require a ledger and gate CBP years by their earliest recorded release.
    Raise ValueError if no eligible common year exists.
    """
    def prepare(frame, keys):
        frame = frame.copy()
        if frame[keys].isna().any().any():
            raise ValueError(f"Missing identifiers in {keys}")
        frame["cbsa_code"] = frame.cbsa_code.astype(str).str.strip().str.zfill(5)
        frame["year"] = pd.to_numeric(frame.year, errors="raise")
        if not frame.year.mod(1).eq(0).all():
            raise ValueError("Years must be integers")
        frame["year"] = frame.year.astype(int)
        if "naics_code" in keys:
            frame["naics_code"] = frame.naics_code.astype(str).str.strip()
            if not frame.naics_code.str.fullmatch(r"\d{2}").all():
                raise ValueError("Expected non-overlapping two-digit sector codes")
        if frame.duplicated(keys).any():
            raise ValueError(f"Duplicate keys: {keys}")
        frame["cbp_employment_count"] = pd.to_numeric(
            frame.cbp_employment_count, errors="raise"
        )
        observed = frame.cbp_employment_count.dropna()
        if (observed.lt(0) | observed.isin([float("inf"), -float("inf")])).any():
            raise ValueError("Employment must be finite and nonnegative")
        return frame

    if isinstance(scoring_year, bool) or int(scoring_year) != scoring_year:
        raise ValueError("scoring_year must be an integer")
    scoring_year = int(scoring_year)
    sectors = prepare(msa_naics_year, ["cbsa_code", "year", "naics_code"])
    metros = prepare(msa_year, ["cbsa_code", "year"])
    mapping = (load_fit_priorities() if priorities is None else priorities).copy()
    if mapping[["naics_2digit", "fit_priority"]].isna().any().any():
        raise ValueError("Missing industry priority identifiers or labels")
    mapping["naics_2digit"] = mapping.naics_2digit.astype(str).str.strip().str.zfill(2)
    if (not mapping.naics_2digit.str.fullmatch(r"\d{2}").all()
            or mapping.naics_2digit.duplicated().any()):
        raise ValueError("Priority codes must be unique two-digit sectors")
    if not mapping.fit_priority.isin(["High", "Medium", "Low", "Exclude"]).all():
        raise ValueError("Invalid industry priority")
    if not mapping.fit_priority.eq("High").any() or not mapping.fit_priority.eq("Medium").any():
        raise ValueError("Mapping must contain High and Medium industries")

    eligible = (set(sectors.loc[sectors.cbp_employment_count.notna(), "year"])
                & set(metros.loc[metros.cbp_employment_count.notna(), "year"]))
    eligible = {y for y in eligible if y <= scoring_year}
    cutoff = None
    first_release = None
    if as_of is not None:
        cutoff = pd.Timestamp(as_of)
        if pd.isna(cutoff):
            raise ValueError("as_of must be a valid date")
        if release_dates is None:
            raise ValueError("Historical runs require release_dates")
        ledger = release_dates.loc[
            release_dates.source.eq("cbp") & release_dates.dataset.eq("cbp_county")
        ].copy()
        ledger["year"] = pd.to_numeric(ledger.year, errors="raise").astype(int)
        ledger["release_date"] = pd.to_datetime(ledger.release_date, errors="raise")
        first_release = ledger.groupby("year").release_date.min()
        eligible &= set(first_release.loc[first_release.le(cutoff)].index)
        eligible = {y for y in eligible if y <= cutoff.year}
    if not eligible:
        raise ValueError("No common CBP year eligible for the requested scoring year/date")
    year = max(eligible)
    snap = sectors.loc[sectors.year.eq(year)]
    unmapped = set(snap.naics_code) - set(mapping.naics_2digit)
    if unmapped:
        raise ValueError(f"Unmapped sectors: {sorted(unmapped)}")
    base = metros.loc[metros.year.eq(year)].copy().set_index("cbsa_code")
    if not set(snap.cbsa_code).issubset(base.index):
        raise ValueError("Sector metros missing from the published metro totals table")
    columns = ["cbp_employment_count"]
    if "cbsa_title" in base:
        columns.insert(0, "cbsa_title")
    out = base[columns].rename(columns={"cbp_employment_count": "all_emp"})
    out["scoring_year"] = scoring_year
    out["industry_data_year"] = year
    out["data_year_lag"] = scoring_year - year
    out["source"] = "CBP"
    out["as_of_date"] = cutoff.isoformat() if cutoff is not None else None
    out["source_release_date"] = first_release.loc[year] if first_release is not None else pd.NaT
    out["denominator_valid"] = out.all_emp.gt(0)
    wide = snap.pivot(index="cbsa_code", columns="naics_code", values="cbp_employment_count")
    denominator = out.all_emp.where(out.denominator_valid)
    for name, labels in [("high", ["High"]), ("medium", ["Medium"]),
                         ("high_med", ["High", "Medium"])]:
        codes = mapping.loc[mapping.fit_priority.isin(labels), "naics_2digit"].tolist()
        values = wide.reindex(index=out.index, columns=codes)
        complete = values.notna().all(axis=1)
        out[f"{name}_expected_sectors"] = len(codes)
        out[f"{name}_observed_sectors"] = values.notna().sum(axis=1)
        out[f"{name}_missing_sectors"] = values.apply(
            lambda row: "; ".join(row.index[row.isna()]), axis=1
        )
        out[f"{name}_complete"] = complete
        out[f"{name}_partial_emp"] = values.sum(axis=1, min_count=1)
        out[f"{name}_emp"] = values.sum(axis=1, min_count=len(codes))
        out[f"{name}_share"] = out[f"{name}_emp"] / denominator
        out[f"{name}_share_ready"] = complete & out.denominator_valid
        if out[f"{name}_share"].dropna().gt(1 + 1e-6).any():
            raise ValueError(f"{name} employment exceeds the published metro total")
    out["published_sector_emp"] = snap.groupby("cbsa_code").cbp_employment_count.sum(min_count=1)
    out["sector_to_total_ratio"] = out.published_sector_emp / denominator
    return out.reset_index().sort_values("cbsa_code", ignore_index=True)


def load_fit_priorities(path: Path | None = None) -> pd.DataFrame:
    """Read [industry_fit.priorities] from an existing weights TOML.

    Each quoted two-digit NAICS key contains label and fit_priority. Derive
    in_high_subset from the rating so two editable values cannot disagree.
    This configuration does not itself change any scoring weights.
    """
    with open(path or PRIORITIES_PATH, "rb") as handle:
        cfg = tomllib.load(handle)
    priorities = cfg.get("industry_fit", {}).get("priorities", {})
    if not priorities:
        raise ValueError("TOML must contain [industry_fit.priorities] entries")
    rows = []
    for code, entry in priorities.items():
        if len(code) != 2 or not code.isdigit():
            raise ValueError(f"Industry priority key must be a two-digit NAICS code: {code!r}")
        if not isinstance(entry, dict):
            raise ValueError(f"Priority {code} must contain label and fit_priority")
        label, priority = entry.get("label"), entry.get("fit_priority")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"Priority {code} requires a nonempty label")
        if priority not in ("High", "Medium", "Low", "Exclude"):
            raise ValueError(f"Invalid industry priority for {code}: {priority!r}")
        row = {"naics_2digit": code, "label": label,
               "fit_priority": priority, "in_high_subset": priority == "High"}
        if "rationale" in entry:
            if not isinstance(entry["rationale"], str):
                raise ValueError(f"Priority {code} rationale must be text")
            row["rationale"] = entry["rationale"]
        rows.append(row)
    frame = pd.DataFrame(rows)
    return frame


def utilities_fit(msa_naics_year: pd.DataFrame, year: int = DEFAULT_YEAR) -> pd.DataFrame:
    """Metro employment / establishments for NAICS 22 (Medium Fit) in `year`.

    Returns one row per CBSA with utilities employment share of metro total
    (total = sum of all 2-digit sectors present for that metro-year).
    """
    naics = msa_naics_year.copy()
    naics["cbsa_code"] = naics["cbsa_code"].astype(str).str.zfill(5)
    naics["naics_code"] = naics["naics_code"].astype(str).str.strip()
    snap = naics[naics["year"] == int(year)].copy()
    if snap.empty:
        return pd.DataFrame(columns=[
            "cbsa_code", "year", "naics_code", "fit_priority",
            "cbp_establishments_count", "cbp_employment_count",
            "metro_employment_count", "utilities_emp_share",
        ])

    totals = (
        snap.groupby("cbsa_code", as_index=False)["cbp_employment_count"]
        .sum()
        .rename(columns={"cbp_employment_count": "metro_employment_count"})
    )
    util = snap[snap["naics_code"].eq("22")].copy()
    out = totals.merge(
        util[["cbsa_code", "cbp_establishments_count", "cbp_employment_count"]],
        on="cbsa_code",
        how="left",
    )
    out["year"] = int(year)
    out["naics_code"] = "22"
    out["fit_priority"] = fit_priority_for("22")
    out["utilities_emp_share"] = (
        out["cbp_employment_count"] / out["metro_employment_count"]
    ).where(out["metro_employment_count"] > 0)
    return out.sort_values("cbsa_code", ignore_index=True)


def fit_priority_for(naics_2digit: str, priorities: pd.DataFrame | None = None) -> str | None:
    priorities = load_fit_priorities() if priorities is None else priorities
    code = str(naics_2digit).zfill(2)[:2]
    hit = priorities.loc[priorities["naics_2digit"] == code, "fit_priority"]
    return None if hit.empty else str(hit.iloc[0])


def build_report(
    msa_naics_year: pd.DataFrame,
    msa_year: pd.DataFrame,
    county_crosswalk: pd.DataFrame,
    scoring_year: int,
    priorities: pd.DataFrame | None = None,
    *,
    growth_years: int = 4,
    comparison_metros: list[str] | None = None,
    as_of=None,
    release_dates: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Build every report table from source data, never from exploratory exports.

    Growth is an endpoint CAGR over growth_years ending in the selected CBP
    year. Missing/zero endpoints yield missing growth. Specialization uses an
    available-metro employment-weighted benchmark, not a national total.
    """
    import numpy as np

    if isinstance(growth_years, bool) or int(growth_years) != growth_years or growth_years <= 0:
        raise ValueError("growth_years must be a positive integer")
    mapping = (load_fit_priorities() if priorities is None else priorities).copy()
    mapping["naics_2digit"] = mapping.naics_2digit.astype(str).str.zfill(2)
    result = industry_mix(msa_naics_year, msa_year, scoring_year, mapping,
                          as_of=as_of, release_dates=release_dates)
    year = int(result.industry_data_year.iloc[0])
    base_year = year - int(growth_years)
    sectors = msa_naics_year.copy()
    metros = msa_year.copy()
    xwalk = county_crosswalk.copy()
    for frame in [sectors, metros, xwalk]:
        frame["cbsa_code"] = frame.cbsa_code.astype(str).str.zfill(5)
    sectors["naics_code"] = sectors.naics_code.astype(str).str.strip()
    sectors["year"] = pd.to_numeric(sectors.year).astype(int)
    metros["year"] = pd.to_numeric(metros.year).astype(int)
    expected = xwalk.groupby("cbsa_code").county_fips.nunique().rename("expected_counties")
    names = metros.loc[metros.year.eq(year), ["cbsa_code", "cbsa_title"]]
    peers = list(dict.fromkeys(str(v).zfill(5) for v in (
        comparison_metros if comparison_metros is not None
        else ["16740", "12060", "39580", "34980", "45300", "19100"])))
    # The historical window is gated before supporting tables are built.
    eligible_years = {y for y in sectors.year.unique() if base_year <= y <= year}
    if as_of is not None:
        ledger = release_dates.loc[
            release_dates.source.eq("cbp") & release_dates.dataset.eq("cbp_county")
        ].copy()
        ledger["release_date"] = pd.to_datetime(ledger.release_date)
        first = ledger.groupby("year").release_date.min()
        eligible_years &= set(first.loc[first.le(pd.Timestamp(as_of))].index)
    window = sectors.loc[sectors.year.isin(eligible_years)].copy()
    snap = window.loc[window.year.eq(year)].copy()
    mapping = mapping.rename(columns={"naics_2digit": "naics_code"})
    detail = snap.merge(mapping, on="naics_code", how="left", validate="many_to_one")
    detail = detail.merge(names, on="cbsa_code", how="left", validate="many_to_one")
    detail = detail.join(expected, on="cbsa_code")
    detail["county_coverage_fraction"] = detail.cbp_counties_reported_count / detail.expected_counties.where(detail.expected_counties.gt(0))
    detail = detail.merge(result[["cbsa_code", "all_emp"]], on="cbsa_code", validate="many_to_one")
    detail["employment_share"] = detail.cbp_employment_count / detail.all_emp.where(detail.all_emp.gt(0))

    measures = {"cbp_employment_count": "employment", "cbp_establishments_count": "establishment",
                "cbp_annual_payroll_usd": "payroll"}
    for column in measures:
        values = pd.to_numeric(window[column], errors="raise").dropna()
        if values.lt(0).any() or values.isin([np.inf, -np.inf]).any():
            raise ValueError(f"Invalid source values in {column}")
    keys = ["cbsa_code", "naics_code"]
    cols = [*keys, *measures, "cbp_counties_reported_count"]
    start = window.loc[window.year.eq(base_year), cols]
    end = window.loc[window.year.eq(year), cols]
    growth = start.merge(end, on=keys, how="outer", suffixes=("_start", "_end"), validate="one_to_one")
    for column, label in measures.items():
        a, b = growth[column + "_start"], growth[column + "_end"]
        ok = a.gt(0) & b.gt(0)
        growth[label + "_cagr"] = (b.where(ok) / a.where(ok)) ** (1 / growth_years) - 1
    known = growth.cbp_counties_reported_count_start.notna() & growth.cbp_counties_reported_count_end.notna()
    growth["endpoint_coverage_note"] = np.select(
        [~known, growth.cbp_counties_reported_count_start.ne(growth.cbp_counties_reported_count_end)],
        ["Missing endpoint county count", "County count changed"], default="Same count; identities not verified")
    growth = growth.merge(mapping, on="naics_code", how="left", validate="many_to_one")
    growth["growth_start_year"], growth["growth_end_year"] = base_year, year

    valid = detail.loc[detail.cbp_employment_count.notna() & detail.all_emp.gt(0)]
    benchmark = valid.groupby("naics_code").agg(
        benchmark_sector_jobs=("cbp_employment_count", lambda s: s.sum(min_count=1)),
        benchmark_total_jobs=("all_emp", lambda s: s.sum(min_count=1)),
        benchmark_metros=("cbsa_code", "nunique"))
    benchmark["benchmark_share"] = benchmark.benchmark_sector_jobs / benchmark.benchmark_total_jobs
    specialization = detail.merge(benchmark, on="naics_code", how="left", validate="many_to_one")
    specialization["location_quotient"] = specialization.employment_share / specialization.benchmark_share.where(specialization.benchmark_share.gt(0))
    high_coverage = detail.loc[detail.fit_priority.eq("High")].groupby("cbsa_code").county_coverage_fraction.min()
    result["high_min_county_coverage"] = result.cbsa_code.map(high_coverage)
    # Preserve historical report aliases without altering the actual core shares.
    result["year"] = year
    result["rank_high_share"] = result.high_share.rank(ascending=False, method="min").astype("Int64")
    result["high_employment"] = result.high_emp
    result["high_employment_share"] = result.high_share
    result["all_high_sectors_have_employment"] = result.high_complete
    peer_detail = specialization.loc[specialization.cbsa_code.isin(peers)].merge(
        growth[[*keys, "employment_cagr", "endpoint_coverage_note"]], on=keys, how="left", validate="one_to_one")

    # All mapped CBP sectors except public administration (not covered by CBP).
    expected_codes = sorted(set(mapping.naics_code) - {"92"})
    grid = pd.MultiIndex.from_product([peers, sorted(eligible_years), expected_codes],
                                     names=["cbsa_code", "year", "naics_code"]).to_frame(index=False)
    coverage = grid.merge(window, on=[*keys, "year"], how="left", validate="one_to_one", indicator=True)
    coverage["row_present"] = coverage.pop("_merge").eq("both")
    coverage["absent_row"] = ~coverage.row_present
    coverage = coverage.join(expected, on="cbsa_code")
    coverage["county_coverage_fraction"] = coverage.cbp_counties_reported_count / coverage.expected_counties.where(coverage.expected_counties.gt(0))
    for label, column in [("employment", "cbp_employment_count"), ("payroll", "cbp_annual_payroll_usd"),
                          ("establishments", "cbp_establishments_count"), ("county_counts", "cbp_counties_reported_count")]:
        coverage[label + "_missing"] = coverage[column].isna()
    groups = {"high": ["High"], "high_med": ["High", "Medium"]}
    for key, labels in groups.items():
        codes = set(mapping.loc[mapping.fit_priority.isin(labels), "naics_code"])
        coverage[key + "_sectors_missing_employment"] = coverage.naics_code.isin(codes) & coverage.employment_missing
    coverage["below_full_county_coverage"] = coverage.row_present & coverage.county_coverage_fraction.lt(1)
    agg = {"expected_sector_rows": ("naics_code", "size"), "published_rows": ("row_present", "sum"),
           "absent_sector_rows": ("absent_row", "sum"),
           "sectors_below_full_county_coverage": ("below_full_county_coverage", "sum")}
    for label in ["employment", "payroll", "establishments", "county_counts"]:
        agg["missing_" + label] = (label + "_missing", "sum")
    for key in groups:
        agg[key + "_sectors_missing_employment"] = (key + "_sectors_missing_employment", "sum")
    coverage_summary = coverage.groupby(["cbsa_code", "year"], as_index=False).agg(**agg)
    coverage_summary = coverage_summary.merge(
        metros[["cbsa_code", "year", "cbp_employment_count"]].rename(columns={"cbp_employment_count": "all_industry_employment"}),
        on=["cbsa_code", "year"], how="left", validate="one_to_one")
    coverage_summary["metro_total_valid"] = coverage_summary.all_industry_employment.gt(0)
    for key, labels in groups.items():
        codes = set(mapping.loc[mapping.fit_priority.isin(labels), "naics_code"])
        coverage_summary[key + "_share_ready"] = (
            coverage_summary[key + "_sectors_missing_employment"].eq(0)
            & coverage_summary.metro_total_valid & codes.issubset(expected_codes))
    coverage_summary = coverage_summary.merge(names, on="cbsa_code", how="left", validate="many_to_one")
    parts = []
    for key, label in [("high", "High only"), ("high_med", "High + Medium")]:
        part = result[["cbsa_code", "cbsa_title", "all_emp", key + "_emp", key + "_partial_emp",
                       key + "_share", key + "_expected_sectors", key + "_observed_sectors", key + "_complete"]].copy()
        part.columns = ["cbsa_code", "cbsa_title", "all_industry_employment", "included_employment",
                        "partial_included_employment", "employment_share", "expected_sector_count",
                        "observed_sector_count", "complete_sector_observations"]
        part["scenario"] = label
        parts.append(part)
    reconciliation = result[["cbsa_code", "cbsa_title", "all_emp", "published_sector_emp", "sector_to_total_ratio"]].rename(
        columns={"all_emp": "all_industry_employment", "published_sector_emp": "published_sector_employment",
                 "sector_to_total_ratio": "sector_to_all_industry_ratio"})
    evidence = mapping.rename(columns={"naics_code": "naics_2digit"}).copy()
    if "rationale" not in evidence:
        evidence["rationale"] = "Current configured priority; source and rationale documented in docs/Industry_fit.md"
    else:
        evidence["rationale"] = evidence.rationale.fillna(
            "Current configured priority; source and rationale documented in docs/Industry_fit.md")
    settings = pd.DataFrame([{"scoring_year": scoring_year, "industry_data_year": year,
                              "growth_start_year": base_year, "growth_end_year": year,
                              "as_of": str(as_of) if as_of is not None else "",
                              "growth_start_available": base_year in eligible_years}])
    return {"Settings": settings, "MSA industry fit": result, "Evidence": evidence,
            "Sector detail": detail, "Growth": growth, "Specialization": specialization,
            "Metro footprint": result.copy(), "Peer detail": peer_detail, "Coverage": coverage,
            "Coverage summary": coverage_summary, "Sensitivity": pd.concat(parts, ignore_index=True),
            "Reconciliation": reconciliation}


def generate_report(root=None, scoring_year=None, *, priorities_file=None, as_of=None,
                    output_path=None) -> Path:
    """Regenerate one report workbook directly from parquet and TOML inputs.

    A custom priorities file must contain [industry_fit.priorities]. Historical
    workbooks go under outputs/as_of/<date>/industry_fit/ by default. No final
    market-attractiveness score or historical pillar export is modified here.
    """
    import hashlib
    import tempfile

    root = Path(root or config.ROOT)
    scoring_year = config.END_YEAR if scoring_year is None else scoring_year
    priorities_file = Path(priorities_file or root / "weights/baseline.toml")
    with priorities_file.open("rb") as handle:
        fit_cfg = tomllib.load(handle).get("industry_fit", {})
    processed = root / "data/processed"
    paths = {"sector_panel": processed / "msa_naics_year.parquet",
             "metro_panel": processed / "msa_year.parquet",
             "county_crosswalk": root / "data/reference/county_cbsa_xwalk.csv",
             "priorities": priorities_file}
    release_dates = None
    if as_of is not None:
        paths["release_dates"] = root / "data/reference/release_dates.csv"
        release_dates = pd.read_csv(paths["release_dates"])
    tables = build_report(
        pd.read_parquet(paths["sector_panel"]), pd.read_parquet(paths["metro_panel"]),
        pd.read_csv(paths["county_crosswalk"], dtype={"cbsa_code": str, "county_fips": str}),
        scoring_year, load_fit_priorities(priorities_file),
        growth_years=fit_cfg.get("growth_years", 4),
        comparison_metros=fit_cfg.get("comparison_metros"), as_of=as_of, release_dates=release_dates)
    tables["Sources"] = pd.DataFrame([
        {"input": key, "path": str(path.resolve().relative_to(root.resolve()))
         if path.resolve().is_relative_to(root.resolve()) else str(path.resolve()),
         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for key, path in paths.items()])
    folder = root / "outputs/industry_fit"
    if as_of is not None:
        folder = root / "outputs/as_of" / str(pd.Timestamp(as_of).date()) / "industry_fit"
    target = Path(output_path) if output_path is not None else folder / "industry_fit_report.xlsx"
    target.parent.mkdir(parents=True, exist_ok=True)
    # Do not leave a partially written report if workbook creation fails.
    with tempfile.NamedTemporaryFile(suffix=".xlsx", dir=target.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with pd.ExcelWriter(temporary_path, engine="openpyxl") as writer:
            for name, table in tables.items():
                table.to_excel(writer, sheet_name=name, index=False)
        temporary_path.replace(target)
    finally:
        temporary_path.unlink(missing_ok=True)
    return target


def main(argv=None) -> int:
    """Regenerate only Industry Fit without running the four-pillar score."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate the Industry Fit report from source data and TOML.")
    parser.add_argument("--year", type=int, default=config.END_YEAR, help="Scoring year; uses latest eligible CBP year")
    parser.add_argument("--priorities", type=Path, help="TOML containing industry_fit.priorities")
    parser.add_argument("--as-of", help="Historical availability cutoff; applies to Industry Fit only")
    parser.add_argument("--output", type=Path, help="Generated workbook destination")
    args = parser.parse_args(argv)
    path = generate_report(scoring_year=args.year, priorities_file=args.priorities,
                           as_of=args.as_of, output_path=args.output)
    print(f"Industry Fit: wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
