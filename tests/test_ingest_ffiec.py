"""FFIEC ingest against fakes of FDIC's API: download, transform, build, and checks, no network needed."""
import json
import re
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from src import build_panel, checks, config, ingest_ffiec
from src.utils import read_manifest

# --------------------------------------------------------------- Call Reports
TODAY = date(2024, 3, 1)  # pinned: 2023-09-30 and 2023-12-31 count as recent; 2024-03-31 hasn't ended


def bank(repdte, cert, rssd, hc="0", hc_name="", name=None, **values):
    row = {"REPDTE": repdte, "CERT": cert, "RSSDID": rssd, "RSSDHCR": hc,
           "NAMEFULL": f"Bank {cert}" if name is None else name,
           "NAME": f"BANK {cert}", "NAMEHCR": hc_name, "STALP": "NC"}
    row.update({field: 10 for field in ingest_ffiec.CALL_FIELDS})  # FDIC returns every field it knows
    row.update(values)
    return row


BANKS = [
    # 2023-12-31: a bank with a holding company and a loss for the quarter
    bank("20231231", 3510, 480228, hc="1073757", hc_name="Holding A", ASSET=2_000_000, DEP=1_500_000,
         NETINCQ=-5_000, EQ=150_000, ROA=-0.25, LNLSDEPR=104.7, NUMEMP=1_200, IDT1CER=None),
    # No holding company (RSSDHCR 0) and no full name: falls back to its own ID and short name
    bank("20231231", 9999, 123, name="", ASSET=50_000, NETINCQ=400),
    # FDIC writes 0 when it has no RSSD ID: left out
    bank("20231231", 4444, 0),
    bank(20230930, 3510, 480228, hc="1073757", hc_name="Holding A", ASSET=1_900_000),  # numeric date
    bank("20230930", 9999, 123, ASSET=48_000),
    bank("20230630", 3510, 480228, hc="1073757", hc_name="Holding A", ASSET=1_800_000),
]
PUBLISHED = ["20230630", "20230930", "20231231"]  # other quarters from 2022 on aren't published in the fake


class FakeFinancials(BaseHTTPRequestHandler):
    rows = BANKS
    hits: list = []
    require_key = False
    status = 200

    def log_message(self, *args):
        pass

    def do_GET(self):
        query = {key: values[0] for key, values in parse_qs(urlparse(self.path).query).items()}
        type(self).hits.append(query)
        if self.require_key and not query.get("api_key"):
            self.send_response(403)
            self.end_headers()
            return
        if self.status != 200:
            self.send_response(self.status)
            self.end_headers()
            return
        stamp = re.fullmatch(r"REPDTE:(\d{8})", query.get("filters", "")).group(1)
        rows = [row for row in self.rows if str(row["REPDTE"]) == stamp]
        fields = query.get("fields", "").split(",")
        start = int(query.get("offset", 0))
        page = rows[start:start + int(query.get("limit", 10))]
        page = [{key: value for key, value in row.items() if key in fields} for row in page]  # unknown names dropped
        body = json.dumps({"meta": {"total": len(rows)}, "totals": {"count": len(rows)},
                           "data": [{"data": row, "score": 0} for row in page]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def fdic_api(project, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    FakeFinancials.rows = BANKS
    FakeFinancials.hits = []
    FakeFinancials.require_key = False
    FakeFinancials.status = 200
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeFinancials)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(ingest_ffiec, "API_URL", f"http://127.0.0.1:{server.server_address[1]}/banks/financials")
    monkeypatch.setattr(ingest_ffiec, "PAUSE_SECONDS", 0)
    monkeypatch.setattr(ingest_ffiec, "_today", lambda: TODAY)
    monkeypatch.setattr(config, "FDIC_API_KEY", "SECRET")
    yield FakeFinancials
    server.shutdown()


def test_quarter_ends_stop_before_a_quarter_that_hasnt_ended():
    ends = ingest_ffiec._quarter_ends(2023, date(2024, 3, 1))
    assert ends[0] == date(2023, 3, 31) and ends[-1] == date(2023, 12, 31) and len(ends) == 4
    assert ingest_ffiec._quarter_ends(2023, date(2023, 12, 31))[-1] == date(2023, 9, 30)


def test_every_column_has_a_unit_suffix():
    for column in ingest_ffiec.CALL_FIELDS.values():
        assert column.startswith("call_") and ingest_ffiec._unit(column)
    assert len(set(ingest_ffiec.CALL_FIELDS.values())) == len(ingest_ffiec.CALL_FIELDS)


def test_download_pulls_published_quarters_and_keeps_the_key_out_of_the_manifest(fdic_api, capsys):
    paths = ingest_ffiec.download_call([2022, 2023])
    assert sorted(p.relative_to(config.RAW).as_posix() for p in paths) == [f"call/{s}.json" for s in PUBLISHED]
    out = capsys.readouterr().out
    assert "skipping 2022-03-31: FDIC hasn't published" in out and "skipping 2023-03-31" in out
    manifest = read_manifest()
    assert len(manifest) == 3 and manifest["source"].eq("call").all()
    assert not manifest["url"].str.contains("SECRET").any()
    assert all(hit["api_key"] == "SECRET" for hit in fdic_api.hits)

    # Rerun: the June quarter is old enough to reuse; the two recent quarters are pulled again
    fdic_api.hits = []
    ingest_ffiec.download_call([2022, 2023])
    asked = {hit["filters"] for hit in fdic_api.hits}
    assert "REPDTE:20230630" not in asked
    pulls = [hit["filters"] for hit in fdic_api.hits if hit.get("limit") == str(ingest_ffiec.PAGE_SIZE)]
    assert sorted(pulls) == ["REPDTE:20230930", "REPDTE:20231231"]


def test_transform_builds_bank_quarter_and_passes_checks(fdic_api, capsys):
    ingest_ffiec.run(years=[2022, 2023])
    assert "1 bank-quarters have no RSSD ID" in capsys.readouterr().out

    table = pd.read_parquet(config.INTERIM / "bank_quarter" / "call.parquet")
    assert len(table) == 5
    rows = table.set_index(["rssd_id", "quarter_end"])
    a = rows.loc[("480228", pd.Timestamp("2023-12-31"))]
    assert a["call_total_assets_usd"] == 2_000_000_000  # $1,000s -> dollars
    assert a["call_quarter_net_income_usd_net"] == -5_000_000  # a loss stays negative
    assert a["call_equity_capital_usd_net"] == 150_000_000
    assert a["call_ytd_return_on_assets_ratio"] == pytest.approx(-0.25)  # ratios as published
    assert a["call_loans_to_deposits_ratio"] == pytest.approx(104.7)
    assert a["call_employees_count"] == 1_200
    assert pd.isna(a["call_cet1_ratio"])  # not reported stays empty
    assert (a["call_cert"], a["call_bank_name"], a["call_state"]) == ("3510", "Bank 3510", "NC")
    assert (a["call_top_holder_rssd_id"], a["call_top_holder_name"]) == ("1073757", "Holding A")
    b = rows.loc[("123", pd.Timestamp("2023-12-31"))]
    assert (b["call_bank_name"], b["call_top_holder_rssd_id"], b["call_top_holder_name"]) == ("BANK 9999", "123", "BANK 9999")
    assert rows.loc[("480228", pd.Timestamp("2023-09-30")), "call_total_assets_usd"] == 1_900_000_000

    build_panel.build_all()
    assert checks.run_checks()
    built = pd.read_parquet(config.PROCESSED / "bank_quarter.parquet")
    assert len(built) == 5 and str(built["quarter_end"].dtype).startswith("datetime64")


def test_a_saved_quarter_missing_banks_stops_the_build(fdic_api):
    paths = ingest_ffiec.download_call([2023])
    december = next(p for p in paths if p.name == "20231231.json")
    payload = json.loads(december.read_text())
    payload["data"] = payload["data"][:-1]
    december.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="holds 2 banks but FDIC counted 3"):
        ingest_ffiec.transform(paths, [2023])


def test_a_field_fdic_doesnt_know_stops_the_build(fdic_api, monkeypatch):
    monkeypatch.setitem(ingest_ffiec.CALL_FIELDS, "NOTAFIELD", "call_typo_usd")
    with pytest.raises(ValueError, match=r"FDIC returned no \['NOTAFIELD'\]"):
        ingest_ffiec.run(years=[2023])


def test_a_quarter_too_big_for_one_request_stops_the_pull(fdic_api, monkeypatch):
    monkeypatch.setattr(ingest_ffiec, "PAGE_SIZE", 2)
    with pytest.raises(ValueError, match="don't fit in one 2-row request"):
        ingest_ffiec.download_call([2023])
    assert not (config.RAW / "call" / "20231231.json").exists()


def test_a_refused_request_says_how_to_get_a_key(fdic_api, monkeypatch):
    monkeypatch.setattr(config, "FDIC_API_KEY", "")
    fdic_api.require_key = True
    with pytest.raises(RuntimeError, match="api.data.gov/signup"):
        ingest_ffiec.download_call([2023])


def test_other_errors_dont_blame_the_key(fdic_api):
    fdic_api.status = 500
    with pytest.raises(RuntimeError) as error:
        ingest_ffiec.download_call([2023])
    assert "500" in str(error.value) and "FDIC_API_KEY" not in str(error.value)


def test_bank_spot_checks_compare_with_published_figures(fdic_api):
    ingest_ffiec.run(years=[2023])
    build_panel.build_all()
    spec = {"rssd_id": ["480228"], "quarter_end": ["2023-12-31"], "column": ["call_total_assets_usd"],
            "rel_tolerance": [0.001], "source_note": ["UBPR page 1"]}
    pd.DataFrame({**spec, "expected": [2_000_500_000]}).to_csv(config.BANK_SPOT_CHECKS, index=False)
    assert checks.run_checks()
    pd.DataFrame({**spec, "expected": [2_100_000_000]}).to_csv(config.BANK_SPOT_CHECKS, index=False)
    assert not checks.run_checks()
