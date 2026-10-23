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
    row.update({"LNCINUS": 0, "CALLFORM": 41})  # a domestic lender on the FFIEC 041; FDIC sends the form as a number
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
        echo = {key: query[key] for key in ("filters", "fields", "limit") if key in query}  # FDIC echoes the request
        body = json.dumps({"meta": {"total": len(rows), "parameters": echo}, "totals": {"count": len(rows)},
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


def call_reports_only(years):
    return ingest_ffiec.transform(ingest_ffiec.download_call(years), years)


def test_transform_builds_bank_quarter_and_passes_checks(fdic_api, capsys):
    call_reports_only([2022, 2023])
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
        call_reports_only([2023])


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
    call_reports_only([2023])
    build_panel.build_all()
    spec = {"rssd_id": ["480228"], "quarter_end": ["2023-12-31"], "column": ["call_total_assets_usd"],
            "rel_tolerance": [0.001], "source_note": ["UBPR page 1"]}
    pd.DataFrame({**spec, "expected": [2_000_500_000]}).to_csv(config.BANK_SPOT_CHECKS, index=False)
    assert checks.run_checks()
    pd.DataFrame({**spec, "expected": [2_100_000_000]}).to_csv(config.BANK_SPOT_CHECKS, index=False)
    assert not checks.run_checks()


SMALL = {"LNCI4": 0, "LNCI4N": 0, "LNRENR4": 0, "LNRENR4N": 0}  # how FDIC shows Part II when it isn't reported


def test_small_loans_are_left_empty_where_the_form_doesnt_report_them(fdic_api, capsys):
    fdic_api.rows = [
        # FFIEC 051 filer: no Part II in September (FDIC shows 0s); reported in December
        bank("20230930", 1, 501, CALLFORM=51, LNCI=500, LNCINUS=None, LNRENRES=300, **SMALL),
        bank("20231231", 1, 501, CALLFORM=51, LNCI=500, LNCINUS=None, LNRENRES=300,
             LNCI4=120, LNCI4N=30, LNRENR4=100, LNRENR4N=5),
        # An FFIEC 051 filer that reports Part II in September anyway keeps its values
        bank("20230930", 5, 505, CALLFORM=51, LNCI=100, LNCINUS=None, LNRENRES=0,
             LNCI4=40, LNCI4N=3, LNRENR4=0, LNRENR4N=0),
        # FFIEC 041 filers report every quarter, so a September 0 is a real 0
        bank("20230930", 2, 502, CALLFORM=41, LNCI=800, LNCINUS=50, LNRENRES=0, **SMALL),
        # FFIEC 002 filer (an insured branch of a foreign bank): no Part II and no deposit breakdown
        bank("20231231", 3, 503, CALLFORM=2, LNCI=900, LNCINUS=200, DEPNI=None, DEPNIDOM=None, **SMALL),
        # FFIEC 031 filer whose small CRE loans exceed its CRE loans: a filing inconsistency
        bank("20231231", 4, 504, CALLFORM=31, LNCI=1_000, LNCINUS=100, LNCI4=50, LNCI4N=4,
             LNRENRES=400, LNRENR4=450, LNRENR4N=9),
    ]
    call_reports_only([2023])
    out = capsys.readouterr().out
    assert "1 bank-quarters report more call_nonfarm_nonres_loans_1m_or_less_usd" in out
    assert "1 FFIEC 051 bank-quarters in March or September report Part II anyway" in out
    rows = pd.read_parquet(config.INTERIM / "bank_quarter" / "call.parquet").set_index(["rssd_id", "quarter_end"])
    small = ["call_ci_loans_1m_or_less_usd", "call_ci_loans_1m_or_less_count",
             "call_nonfarm_nonres_loans_1m_or_less_usd", "call_nonfarm_nonres_loans_1m_or_less_count"]
    over = ["call_ci_loans_over_1m_usd", "call_nonfarm_nonres_loans_over_1m_usd"]

    september_051 = rows.loc[("501", pd.Timestamp("2023-09-30"))]
    assert september_051["call_report_form"] == "051"
    assert september_051[small + over].isna().all()
    assert september_051["call_ci_loans_usd"] == 500_000  # the totals stay

    december_051 = rows.loc[("501", pd.Timestamp("2023-12-31"))]
    assert december_051["call_ci_loans_1m_or_less_count"] == 30
    assert december_051["call_ci_loans_over_1m_usd"] == 380_000  # no non-U.S. split on the 051: counts as 0
    assert december_051["call_nonfarm_nonres_loans_over_1m_usd"] == 200_000

    reported_anyway = rows.loc[("505", pd.Timestamp("2023-09-30"))]
    assert reported_anyway["call_ci_loans_1m_or_less_usd"] == 40_000
    assert reported_anyway["call_ci_loans_over_1m_usd"] == 60_000

    september_041 = rows.loc[("502", pd.Timestamp("2023-09-30"))]
    assert september_041["call_ci_loans_1m_or_less_usd"] == 0
    assert september_041["call_ci_loans_over_1m_usd"] == 750_000  # 800 - 50 to non-U.S. addressees - 0 small

    branch = rows.loc[("503", pd.Timestamp("2023-12-31"))]
    assert branch["call_report_form"] == "002"
    assert branch[small + over + ["call_noninterest_bearing_deposits_usd"]].isna().all()

    filer_031 = rows.loc[("504", pd.Timestamp("2023-12-31"))]
    assert filer_031["call_ci_loans_over_1m_usd"] == 850_000
    assert filer_031["call_nonfarm_nonres_loans_1m_or_less_usd"] == 450_000  # kept as published
    assert pd.isna(filer_031["call_nonfarm_nonres_loans_over_1m_usd"])  # would be negative

    build_panel.build_all()
    assert checks.run_checks()


def test_zeros_for_values_a_bank_doesnt_report_are_left_empty(fdic_api, capsys):
    fdic_api.rows = [
        # A community bank leverage ratio bank: FDIC shows 0 for its risk-based capital and ratios
        bank("20231231", 1, 601, CBLRIND=1, RBC=0, RBCRWAJ=0, IDT1CER=0, RBC1AAJ=11.2, DEPUNA=0, ASSET=400_000),
        # A bank on the risk-based rules keeps its values; LNNDEPD's 0 is a real 0
        bank("20231231", 2, 602, CBLRIND=0, RBC=150_000, RBCRWAJ=14.2, IDT1CER=12.5, DEPUNA=300_000,
             ASSET=1_500_000, LNNDEPD=0, ILNQ=-3),
        # FDIC leaves the flag empty before 2020: values are kept as published
        bank("20230930", 3, 603, CBLRIND=None, RBC=90_000, RBCRWAJ=13.1, IDT1CER=11.9, DEPUNA=25_000),
    ]
    call_reports_only([2023])
    out = capsys.readouterr().out
    assert "1 bank-quarters use the community bank leverage ratio" in out
    assert "1 bank-quarters show 0 for DEPUNA" in out
    rows = pd.read_parquet(config.INTERIM / "bank_quarter" / "call.parquet").set_index(["rssd_id", "quarter_end"])
    risk_based = ["call_total_risk_based_capital_usd_net", "call_total_risk_based_capital_ratio", "call_cet1_ratio"]

    cblr = rows.loc[("601", pd.Timestamp("2023-12-31"))]
    assert cblr[risk_based + ["call_uninsured_deposits_usd"]].isna().all()
    assert cblr["call_leverage_ratio"] == 11.2  # still reported under the leverage ratio framework

    large = rows.loc[("602", pd.Timestamp("2023-12-31"))]
    assert large["call_total_risk_based_capital_usd_net"] == 150_000_000
    assert large["call_total_risk_based_capital_ratio"] == 14.2
    assert large["call_cet1_ratio"] == 12.5
    assert large["call_uninsured_deposits_usd"] == 300_000_000
    assert large["call_nondepository_fi_loans_usd"] == 0
    assert large["call_quarter_loan_interest_income_usd_net"] == -3_000

    no_flag = rows.loc[("603", pd.Timestamp("2023-09-30"))]
    assert no_flag["call_total_risk_based_capital_usd_net"] == 90_000_000
    assert no_flag["call_cet1_ratio"] == 11.9
    assert no_flag["call_uninsured_deposits_usd"] == 25_000_000

    pulls = [hit for hit in fdic_api.hits if hit.get("limit") == str(ingest_ffiec.PAGE_SIZE)]
    assert pulls and all("CBLRIND" in hit["fields"].split(",") for hit in pulls)

    build_panel.build_all()
    assert checks.run_checks()


def test_a_saved_quarter_asked_without_a_new_field_is_pulled_again(fdic_api, monkeypatch, capsys):
    ingest_ffiec.download_call([2023])
    monkeypatch.setitem(ingest_ffiec.CALL_FIELDS, "NEWFLD", "call_new_field_usd")
    fdic_api.rows = [{**row, "NEWFLD": 5} for row in BANKS]
    fdic_api.hits = []
    ingest_ffiec.download_call([2023])
    pulls = [hit["filters"] for hit in fdic_api.hits if hit.get("limit") == str(ingest_ffiec.PAGE_SIZE)]
    assert "REPDTE:20230630" in pulls  # old enough to reuse, but saved before NEWFLD was asked for
    assert "2023-06-30: the saved copy wasn't asked for NEWFLD; pulling it again" in capsys.readouterr().out

    fdic_api.hits = []
    ingest_ffiec.download_call([2023])  # now it has been asked for: reused again
    assert "REPDTE:20230630" not in {hit["filters"] for hit in fdic_api.hits}


def test_fields_missing_from_uses_the_echoed_request_or_the_returned_fields(tmp_path):
    asked = ingest_ffiec._requested_fields()
    echoed = tmp_path / "echoed.json"
    echoed.write_text(json.dumps({"meta": {"total": 0, "parameters": {"fields": ",".join(asked)}}, "data": []}))
    assert ingest_ffiec._fields_missing_from(echoed) == []
    returned = tmp_path / "returned.json"
    row = {field: 1 for field in asked if field != "LNCI4"}
    returned.write_text(json.dumps({"meta": {"total": 1}, "data": [{"data": row}]}))
    assert ingest_ffiec._fields_missing_from(returned) == ["LNCI4"]
    broken = tmp_path / "broken.json"
    broken.write_text("not json")
    assert ingest_ffiec._fields_missing_from(broken) == asked


# --------------------------------------------------------------- small-business lending by bank
def disclosure_row(respondent, agency, year, state, county, level, counts=(0, 0, 0), amounts=(0, 0, 0),
                   revenue=(0, 0), table="D1-1", affiliate=(0, 0)):
    """One 145-character disclosure record, laid out field by field from FFIEC's spec."""
    numbers = [counts[0], amounts[0], counts[1], amounts[1], counts[2], amounts[2], *revenue, *affiliate]
    line = (f"{table:<5}{respondent:0>10}{agency:1}{year:4}" "41" f"{state:2}{county:3}" "16740" "0001" "NNL"
            f"{'':3}{level:>3}" + "".join(f"{n:010d}" for n in numbers))
    assert len(line) == 145
    return line


def transmittal_row(respondent, agency, year, name, rssd):
    line = (f"{respondent:0>10}{agency:1}{year:4}{name:<30}{'1 Main St':<40}{'Charlotte':<25}NC"
            f"{'28202':<10}{'12-3456789':<10}{rssd:0>10}{5_000_000:010d}")
    assert len(line) == 152
    return line


DISCLOSURE_2023 = [
    # Lender 12345 (OCC): county totals in Mecklenburg, York (level written "040"), Birmingham, and a micropolitan county
    disclosure_row("12345", "1", "2023", "37", "119", "40", (10, 5, 2), (500, 800, 1_500), (8, 400)),
    disclosure_row("12345", "1", "2023", "45", "091", "040", (4, 0, 0), (100, 0, 0), (4, 100)),
    disclosure_row("12345", "1", "2023", "01", "073", "40", (1, 1, 0), (50, 150, 0), (1, 50)),
    disclosure_row("12345", "1", "2023", "37", "999", "40", (3, 0, 0), (60, 0, 0), (3, 60)),
    # Rows that must not be counted: inside-AA subtotal, an income-group detail row, purchases, small farm,
    # and affiliate loans (only in the affiliate columns)
    disclosure_row("12345", "1", "2023", "37", "119", "50", (99, 0, 0), (9_999, 0, 0)),
    disclosure_row("12345", "1", "2023", "37", "119", "", (99, 0, 0), (9_999, 0, 0)),
    disclosure_row("12345", "1", "2023", "37", "119", "40", (99, 0, 0), (9_999, 0, 0), table="D1-2"),
    disclosure_row("12345", "1", "2023", "37", "119", "40", (99, 0, 0), (9_999, 0, 0), table="D2-1"),
    # A lender whose transmittal row has no RSSD ID: counts toward metro totals only
    disclosure_row("777", "3", "2023", "37", "119", "40", (6, 0, 0), (200, 0, 0), (6, 200), affiliate=(50, 5_000)),
    # Same Respondent ID as the first lender but a different agency: a different lender
    disclosure_row("12345", "2", "2023", "01", "073", "40", (0, 2, 1), (0, 400, 600), (1, 300)),
    "D3-0 " + "0" * 140,  # other tables share the file
]
TRANSMITTAL_2023 = [
    transmittal_row("12345", "1", "2023", "First Test Bank", "480228"),
    transmittal_row("777", "3", "2023", "No ID Bank", "0"),
    transmittal_row("12345", "2", "2023", "Fed Member Bank", "999"),
]
DISCLOSURE_2022 = [disclosure_row("12345", "1", "2022", "37", "119", "40", (5, 0, 0), (100, 0, 0), (5, 100))]
TRANSMITTAL_2022 = [transmittal_row("12345", "1", "2022", "First Test Bank", "480228")]


def zipped(lines, member):
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member, "\r\n".join(lines) + "\r\n")
    return buffer.getvalue()


CRA_FILES = {
    "23exp_discl.zip": zipped(DISCLOSURE_2023, "exp_discl.dat"),
    "23exp_trans.zip": zipped(TRANSMITTAL_2023, "TS.DAT"),
    "22exp_discl.zip": zipped(DISCLOSURE_2022, "exp_discl.dat"),
    "22exp_trans.zip": zipped(TRANSMITTAL_2022, "TS.DAT"),
}


class FakeFFIEC(BaseHTTPRequestHandler):
    refuse = False  # the real site answers scripted downloads with 403
    hits = 0

    def log_message(self, *args):
        pass

    def do_GET(self):
        type(self).hits += 1
        body = None if self.refuse else CRA_FILES.get(urlparse(self.path).path.rsplit("/", 1)[-1])
        self.send_response(403 if self.refuse else 200 if body else 404)
        self.end_headers()
        if body:
            self.wfile.write(body)


@pytest.fixture
def ffiec_site(project, crosswalk_csv, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    FakeFFIEC.refuse = False
    FakeFFIEC.hits = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeFFIEC)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(ingest_ffiec, "CRA_URL", f"http://127.0.0.1:{server.server_address[1]}/flat-files/")
    monkeypatch.setattr(ingest_ffiec, "CRA_LATEST_AVAILABLE_YEAR", 2023)
    yield FakeFFIEC
    server.shutdown()


def bhavanas_totals(amount_2023_charlotte=3_100_000):
    """What ingest_cra.py writes from the aggregate files: every lender combined, by metro."""
    from src.utils import write_interim

    write_interim(pd.DataFrame({
        "cbsa_code": ["16740", "13820", "16740"], "year": [2023, 2023, 2022],
        "cra_small_business_loan_count": [27, 5, 5],
        "cra_small_business_loan_amount_usd": [amount_2023_charlotte, 1_200_000, 100_000],
    }), "cra", "msa_year")


def test_cra_download_pulls_both_files_per_published_year(ffiec_site, capsys):
    paths = ingest_ffiec.download_cra_bank([2022, 2023, 2024])
    assert sorted(p.name for p in paths) == ["22exp_discl.zip", "22exp_trans.zip", "23exp_discl.zip", "23exp_trans.zip"]
    assert "skipping 2024" in capsys.readouterr().out
    manifest = read_manifest()
    assert len(manifest) == 4 and manifest["source"].eq("cra_bank").all()


def test_cra_lending_rolls_lenders_up_to_banks_by_metro(ffiec_site, capsys):
    bhavanas_totals()
    ingest_ffiec.transform(ingest_ffiec.download_cra_bank([2022, 2023]), [2022, 2023])
    out = capsys.readouterr().out
    assert "2023: 3 lenders, 95.4% of the dollars matched to an RSSD ID" in out  # 1 - 0.2M / 4.36M
    assert "within 2% for 3 of 3 metro-years; every year's total is within 0.00%" in out

    bank = pd.read_parquet(config.INTERIM / "bank_msa_year" / "cra_bank.parquet").set_index(["rssd_id", "cbsa_code", "year"])
    assert len(bank) == 4  # the lender without an RSSD ID and the micropolitan county are left out
    a = bank.loc[("480228", "16740", 2023)]
    assert a["cra_bank_small_business_loan_count"] == 21  # Mecklenburg 17 + York 4; subtotals and other tables ignored
    assert a["cra_bank_small_business_loan_amount_usd"] == 2_900_000  # $1,000s -> dollars
    assert (a["cra_bank_revenue_under_1m_loan_count"], a["cra_bank_revenue_under_1m_loan_amount_usd"]) == (12, 500_000)
    assert a["cra_bank_small_business_amount_share"] == pytest.approx(2.9 / 3.1)  # the unmatched lender is in the total
    assert a["cra_bank_lender_name"] == "First Test Bank"
    assert bank.loc[("480228", "13820", 2023), "cra_bank_small_business_amount_share"] == pytest.approx(1 / 6)
    fed = bank.loc[("999", "13820", 2023)]
    assert (fed["cra_bank_small_business_loan_count"], fed["cra_bank_lender_name"]) == (3, "Fed Member Bank")
    assert bank.loc[("480228", "16740", 2022), "cra_bank_small_business_amount_share"] == 1.0

    build_panel.build_all()
    assert checks.run_checks()


def test_cra_lending_that_doesnt_add_up_stops_the_build(ffiec_site):
    bhavanas_totals(amount_2023_charlotte=4_000_000)  # 1 of 3 metro-years off is far more than 1%
    with pytest.raises(RuntimeError, match="1 of 3 metro-years are more than 2% apart"):
        ingest_ffiec.transform(ingest_ffiec.download_cra_bank([2022, 2023]), [2022, 2023])


def test_an_isolated_gap_is_printed_not_fatal(ffiec_site, monkeypatch, capsys):
    # With hundreds of metros a single gap is a tiny share; loosen both limits to model that here
    monkeypatch.setattr(ingest_ffiec, "RECONCILE_MAX_OFF_SHARE", 0.5)
    monkeypatch.setattr(ingest_ffiec, "RECONCILE_YEAR_TOLERANCE", 0.5)
    bhavanas_totals(amount_2023_charlotte=3_300_000)
    ingest_ffiec.transform(ingest_ffiec.download_cra_bank([2022, 2023]), [2022, 2023])
    out = capsys.readouterr().out
    assert "warning: 16740 in 2023: lenders add up to 27 loans and $3,100,000, vs 27 and $3,300,000" in out
    assert "(+0.0% loans, -6.1% dollars)" in out
    assert "within 2% for 2 of 3 metro-years" in out
    assert (config.INTERIM / "bank_msa_year" / "cra_bank.parquet").exists()


def test_a_year_total_that_doesnt_add_up_stops_the_build(ffiec_site, monkeypatch):
    monkeypatch.setattr(ingest_ffiec, "RECONCILE_MAX_OFF_SHARE", 0.5)  # the metro gap alone would pass
    bhavanas_totals(amount_2023_charlotte=3_300_000)  # but 2023's total is 4.4% off
    with pytest.raises(RuntimeError, match=r"these years' totals are off: \{2023: '4.44%'\}"):
        ingest_ffiec.transform(ingest_ffiec.download_cra_bank([2022, 2023]), [2022, 2023])


def test_a_refused_download_explains_downloading_by_hand(ffiec_site):
    ffiec_site.refuse = True
    with pytest.raises(RuntimeError, match="403 .*FFIEC refuses scripted downloads"):
        ingest_ffiec.download_cra_bank([2023])


def test_files_downloaded_by_hand_are_logged_without_asking_ffiec(ffiec_site):
    ffiec_site.refuse = True  # any request would fail
    folder = config.RAW / "cra_bank"
    folder.mkdir(parents=True)
    for name, body in CRA_FILES.items():
        (folder / name).write_bytes(body)
    paths = ingest_ffiec.download_cra_bank([2022, 2023])
    assert len(paths) == 4 and ffiec_site.hits == 0
    manifest = read_manifest()
    assert len(manifest) == 4 and manifest["notes"].str.endswith("downloaded by hand").all()
    ingest_ffiec.download_cra_bank([2022, 2023])  # already logged: no second row per file
    assert len(read_manifest()) == 4


def test_cra_lending_without_bhavanas_totals_says_it_wasnt_reconciled(ffiec_site, capsys):
    ingest_ffiec.transform(ingest_ffiec.download_cra_bank([2023]), [2023])
    assert "not reconciled" in capsys.readouterr().out


def test_cra_needs_the_transmittal_for_rssd_ids(ffiec_site):
    paths = [p for p in ingest_ffiec.download_cra_bank([2023]) if "discl" in p.name]
    with pytest.raises(ValueError, match="no transmittal file for \\[2023\\]"):
        ingest_ffiec.transform(paths, [2023])


def test_full_ffiec_run_fills_both_bank_tables(fdic_api, ffiec_site):
    bhavanas_totals()
    outputs = ingest_ffiec.run(years=[2022, 2023])
    assert sorted(p.relative_to(config.INTERIM).as_posix() for p in outputs) == [
        "bank_msa_year/cra_bank.parquet", "bank_quarter/call.parquet"]
    build_panel.build_all()
    assert checks.run_checks()
