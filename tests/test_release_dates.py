"""Checks on data/reference/release_dates.csv, the first-release date of every source, dataset and year."""
import csv
from datetime import date, timedelta
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "data" / "reference" / "release_dates.csv"
COLUMNS = ["source", "dataset", "year", "quarter_end", "release_type", "release_date", "link", "note"]


@pytest.fixture(scope="module")
def rows():
    with open(PATH, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == COLUMNS
        return list(reader)


def test_one_row_per_key(rows):
    keys = [(r["source"], r["dataset"], r["year"], r["quarter_end"], r["release_type"]) for r in rows]
    assert len(keys) == len(set(keys))


def test_values_are_well_formed(rows):
    for r in rows:
        assert r["release_type"] in {"initial", "revised", "final"}, r
        assert bool(r["quarter_end"]) == (r["source"] == "call"), r
        if r["release_date"]:
            date.fromisoformat(r["release_date"])
            assert r["link"].startswith("https://"), r
        else:
            assert r["note"].startswith("not found"), r


def test_nothing_is_released_before_its_period_ends(rows):
    for r in rows:
        if not r["release_date"]:
            continue
        released, year = date.fromisoformat(r["release_date"]), int(r["year"])
        if r["source"] == "call":
            period_end = date.fromisoformat(r["quarter_end"])
        elif r["source"] == "sod":
            period_end = date(year, 6, 30)  # the survey is as of June 30
        else:
            period_end = date(year, 12, 31)
        assert released > period_end, r


def test_call_reports_follow_the_35_day_rule(rows):
    calls = [r for r in rows if r["source"] == "call"]
    assert len(calls) == 46  # 2015 Q1 through 2026 Q2
    for r in calls:
        q = date.fromisoformat(r["quarter_end"])
        assert (q + timedelta(days=1)).day == 1 and q.month in (3, 6, 9, 12), r
        assert date.fromisoformat(r["release_date"]) == q + timedelta(days=35), r


@pytest.mark.parametrize("source, dataset, last_year", [
    ("bea", "cagdp2", 2024), ("bea", "cainc1", 2024), ("bls", "laucnty", 2024),
    ("bls", "qcew_annual_by_area", 2024), ("cbp", "cbp_county", 2023), ("cra", "exp_aggr", 2024),
    ("cra_bank", "exp_discl", 2024), ("cra_bank", "exp_trans", 2024), ("fred", "CHAR737URN", 2024),
    ("sod", "bankfind_sod", 2024),
])
def test_every_panel_year_has_a_first_release(rows, source, dataset, last_year):
    years = {int(r["year"]) for r in rows
             if (r["source"], r["dataset"], r["release_type"]) == (source, dataset, "initial") and r["release_date"]}
    assert years >= set(range(2015, last_year + 1))


@pytest.mark.parametrize("dataset", ["cagdp2", "cainc1"])
def test_every_bea_history_year_has_a_first_release(rows, dataset):
    years = {int(r["year"]) for r in rows
             if (r["source"], r["dataset"], r["release_type"]) == ("bea", dataset, "initial") and r["release_date"]}
    assert years >= set(range(2010, 2015))  # msa_year_history


def test_every_pep_year_has_a_first_release(rows):
    years = {int(r["year"]) for r in rows if r["source"] == "pep" and r["release_type"] == "initial" and r["release_date"]}
    assert years >= set(range(2015, 2025))
