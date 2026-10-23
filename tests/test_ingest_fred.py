import json

import pandas as pd
import pytest

from src import config, ingest_fred


def series_row(series_id, cbsa_code, column, annualize="mean"):
    return {"series_id": series_id, "cbsa_code": cbsa_code, "column": column, "units": "percent",
            "frequency": "M", "annualize": annualize, "notes": ""}


def write_series_list(project, rows):
    """The fred_series.csv the module reads (the project fixture points config.FRED_SERIES at the temp folder)."""
    pd.DataFrame(rows).to_csv(project["FRED_SERIES"], index=False)


def write_observations(project, series_id, observations):
    """A fake FRED response in the temporary raw folder. observations: (date, value) pairs; values are strings."""
    folder = project["RAW"] / "fred"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{series_id}.json"
    payload = {"observations": [{"date": date, "value": value} for date, value in observations]}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def monthly(year, values):
    return [(f"{year}-{month:02d}-01", str(value)) for month, value in enumerate(values, start=1)]


def result(project):
    out = pd.read_parquet(project["INTERIM"] / "msa_year" / "fred.parquet")
    return out.set_index(["cbsa_code", "year"])


def test_annual_value_is_the_mean_of_the_monthly_values(project, crosswalk_csv):
    write_series_list(project, [series_row("S1", "16740", "fred_unemployment_rate_pct")])
    path = write_observations(project, "S1", monthly(2023, range(1, 13)))
    ingest_fred.transform([path], [2023])
    assert result(project).loc[("16740", 2023), "fred_unemployment_rate_pct"] == pytest.approx(6.5)


def test_missing_observations_marked_with_a_dot_are_dropped_not_counted_as_zero(project, crosswalk_csv):
    write_series_list(project, [series_row("S1", "16740", "fred_unemployment_rate_pct")])
    path = write_observations(project, "S1", monthly(2023, ["4.0"] * 11 + ["."]))
    ingest_fred.transform([path], [2023])
    assert result(project).loc[("16740", 2023), "fred_unemployment_rate_pct"] == pytest.approx(4.0)  # not 44/12


def test_sum_and_last_annualization(project, crosswalk_csv):
    write_series_list(project, [
        series_row("SUMS", "16740", "fred_total_test", annualize="sum"),
        series_row("LASTS", "13820", "fred_latest_test", annualize="last"),
    ])
    paths = [write_observations(project, "SUMS", monthly(2023, [1, 2, 3])),
             write_observations(project, "LASTS", monthly(2023, [1, 2, 3]))]
    ingest_fred.transform(paths, [2023])
    out = result(project)
    assert out.loc[("16740", 2023), "fred_total_test"] == 6
    assert out.loc[("13820", 2023), "fred_latest_test"] == 3


def test_a_series_listed_at_a_metropolitan_division_lands_on_its_parent_metro(project, crosswalk_csv):
    write_series_list(project, [series_row("MIAMI", "33124", "fred_unemployment_rate_pct")])  # Miami division
    path = write_observations(project, "MIAMI", monthly(2023, [5] * 12))
    ingest_fred.transform([path], [2023])
    out = result(project)
    assert ("33100", 2023) in out.index          # the Miami-Fort Lauderdale metro
    assert ("33124", 2023) not in out.index


def test_bad_annualize_value_and_missing_download_are_rejected_clearly(project, crosswalk_csv):
    write_series_list(project, [series_row("S1", "16740", "fred_unemployment_rate_pct", annualize="median")])
    with pytest.raises(ValueError, match="unrecognized"):
        ingest_fred.transform([], [2023])

    write_series_list(project, [series_row("S1", "16740", "fred_unemployment_rate_pct")])
    with pytest.raises(ValueError, match="no downloaded file for series S1"):
        ingest_fred.transform([], [2023])


def test_download_asks_the_observations_endpoint_once_per_series(project, monkeypatch):
    calls = []

    def fake_fetch(url, source, filename=None, *, params=None, force=False, notes=""):
        calls.append({"url": url, "source": source, "filename": filename, "params": params})
        return project["RAW"] / source / filename

    monkeypatch.setattr(ingest_fred, "fetch", fake_fetch)
    monkeypatch.setattr(config, "FRED_API_KEY", "not-a-real-key")
    write_series_list(project, [series_row("AAA", "16740", "fred_a"), series_row("BBB", "13820", "fred_b"),
                                series_row("AAA", "16740", "fred_c")])  # AAA listed twice
    paths = ingest_fred.download([2023])

    assert [call["filename"] for call in calls] == ["AAA.json", "BBB.json"]
    assert [path.name for path in paths] == ["AAA.json", "BBB.json"]
    assert all(call["url"] == "https://api.stlouisfed.org/fred/series/observations" for call in calls)
    assert all(call["source"] == "fred" for call in calls)
    assert calls[0]["params"] == {"series_id": "AAA", "api_key": "not-a-real-key", "file_type": "json"}


def test_documents_that_a_series_with_no_observation_in_the_years_fails_with_a_bare_keyerror(project, crosswalk_csv):
    write_series_list(project, [series_row("S1", "16740", "fred_unemployment_rate_pct")])
    path = write_observations(project, "S1", monthly(2019, [4] * 12))   # nothing in 2023
    with pytest.raises(KeyError):                                        # not a clear message: documents today's behavior
        ingest_fred.transform([path], [2023])


def test_documents_that_a_partial_year_is_averaged_over_the_months_present(project, crosswalk_csv):
    write_series_list(project, [series_row("S1", "16740", "fred_unemployment_rate_pct")])
    path = write_observations(project, "S1", monthly(2023, [2, 4, 6]))   # only January to March
    ingest_fred.transform([path], [2023])
    assert result(project).loc[("16740", 2023), "fred_unemployment_rate_pct"] == pytest.approx(4.0)  # no warning


def test_documents_that_last_means_the_last_row_in_the_file_not_the_latest_date(project, crosswalk_csv):
    write_series_list(project, [series_row("S1", "16740", "fred_latest_test", annualize="last")])
    path = write_observations(project, "S1", [("2023-12-01", "9"), ("2023-01-01", "1")])  # file not in date order
    ingest_fred.transform([path], [2023])
    assert result(project).loc[("16740", 2023), "fred_latest_test"] == 1   # December's 9 would be the right answer
