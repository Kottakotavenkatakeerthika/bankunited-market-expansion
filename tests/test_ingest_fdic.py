"""SOD ingest against a fake FDIC API: download, transform, build, and checks, no network needed."""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from src import build_panel, checks, config, ingest_fdic
from src.utils import read_manifest


def office(year, cert, rssd, brnum, state, county, deposits, main=0, service=11, hc=0, hc_name="", msa=0, name=None):
    return {"YEAR": year, "CERT": cert, "RSSDID": rssd, "RSSDHCR": hc, "NAMEFULL": name or f"Bank {cert}",
            "NAMEHCR": hc_name, "BRNUM": brnum, "UNINUMBR": cert * 1000 + brnum, "BKMO": main,
            "BRSERTYP": service, "STALPBR": state, "STCNTYBR": county, "DEPSUMBR": deposits, "MSABR": msa}


OFFICES = [
    # 2023. Bank 3510: main office plus two branches in Charlotte (Mecklenburg 37119, York 45091)
    office(2023, 3510, 480228, 0, "NC", "37119", 300_000, main=1, hc=1073757, hc_name="Holding A", msa=16740),
    office(2023, 3510, 480228, 1, "NC", "37119", 20_000, hc=1073757, hc_name="Holding A", msa=16740),
    office(2023, 3510, 480228, 2, "SC", "45091", 10_000, service=12, hc=1073757, hc_name="Holding A", msa=16740),
    # Bank 3511: main office in Birmingham, county code as a number that lost its leading zero
    office(2023, 3511, 451965, 0, "AL", 1073, 50_000, main=1, hc=1120754, hc_name="Holding B", msa=13820),
    office(2023, 3511, 451965, 5, "NC", "37119", 70_000, hc=1120754, hc_name="Holding B", msa=16740),
    # Bank 9999: no holding company; main office in a micropolitan county; a drive-through
    # in York whose deposits are reported at another office (empty)
    office(2023, 9999, 123, 0, "NC", "37999", 5_000, main=1),
    office(2023, 9999, 123, 1, "SC", "45091", None, service=23, msa=16740),
    # Connecticut office still on a pre-2022 county code the 2023 crosswalk doesn't have
    office(2023, 777, 777777, 0, "CT", "09001", 1_000, main=1),
    # Oregon: its code OR is a query word in the API's filter syntax, so it must be quoted
    office(2023, 888, 888888, 0, "OR", "41051", 2_000, main=1, msa=38900),
    # 2022
    office(2022, 3510, 480228, 0, "NC", "37119", 250_000, main=1, hc=1073757, hc_name="Holding A", msa=16740),
    office(2022, 3511, 451965, 5, "NC", "37119", 60_000, hc=1120754, hc_name="Holding B", msa=16740),
    office(2022, 3511, 451965, 0, "AL", "01073", 40_000, main=1, hc=1120754, hc_name="Holding B", msa=13820),
]
STATES = ["NC", "SC", "AL", "CT", "OR"]


class FakeFDIC(BaseHTTPRequestHandler):
    offices = OFFICES
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
        filters = query.get("filters", "")
        if self.status != 200 or re.search(r"STALPBR:(AND|OR|NOT)\b", filters):  # unquoted query word
            self.send_response(self.status if self.status != 200 else 400)
            self.end_headers()
            return
        year = int(re.search(r"YEAR:(\d{4})", filters).group(1))
        state = re.search(r'STALPBR:"?([A-Z]{2})"?', filters)
        rows = [r for r in self.offices if r["YEAR"] == year and (not state or r["STALPBR"] == state.group(1))]
        fields = query.get("fields", "").split(",") if query.get("fields") else None
        page = rows[int(query.get("offset", 0)):][: int(query.get("limit", 10))]
        if fields:
            page = [{key: value for key, value in row.items() if key in fields} for row in page]
        body = json.dumps({"meta": {"total": len(rows)}, "totals": {"count": len(rows)},
                           "data": [{"data": row, "score": 0} for row in page]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def fdic_api(project, crosswalk_csv, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    FakeFDIC.hits = []
    FakeFDIC.require_key = False
    FakeFDIC.status = 200
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeFDIC)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(ingest_fdic, "API_URL", f"http://127.0.0.1:{server.server_address[1]}/banks/sod")
    monkeypatch.setattr(ingest_fdic, "STATE_CODES", STATES)
    monkeypatch.setattr(ingest_fdic, "PAUSE_SECONDS", 0)
    monkeypatch.setattr(config, "FDIC_API_KEY", "SECRET")
    yield FakeFDIC
    server.shutdown()


def test_download_pulls_each_state_once_and_keeps_the_key_out_of_the_manifest(fdic_api, capsys):
    paths = ingest_fdic.download([2022, 2023])
    assert sorted(p.relative_to(config.RAW).as_posix() for p in paths) == sorted(
        f"sod/{year}/{state}.json" for year in (2022, 2023) for state in STATES)
    assert "matching FDIC's national count" in capsys.readouterr().out
    manifest = read_manifest()
    assert len(manifest) == 10 and manifest["source"].eq("sod").all()
    assert any(hit.get("filters", "").endswith('STALPBR:"OR"') for hit in fdic_api.hits)
    assert not manifest["url"].str.contains("SECRET").any()
    assert all(hit["api_key"] == "SECRET" for hit in fdic_api.hits)

    assert all((config.RAW / "sod" / str(year) / ingest_fdic.NATIONAL_CHECK_FILE).exists() for year in (2022, 2023))

    calls = len(fdic_api.hits)
    ingest_fdic.download([2022, 2023])  # everything cached and checked: no requests at all
    assert len(fdic_api.hits) == calls


def test_unpublished_years_are_skipped(fdic_api, capsys):
    paths = ingest_fdic.download([2022, 2024])
    assert "skipping 2024" in capsys.readouterr().out
    assert paths and all("/2022/" in p.as_posix() for p in paths)


def test_a_national_count_mismatch_stops_the_build_even_on_a_rerun(fdic_api, monkeypatch):
    monkeypatch.setattr(ingest_fdic, "STATE_CODES", ["NC", "SC", "AL"])  # CT and OR left out
    for _ in range(2):  # the rerun finds the state files already downloaded and must still stop
        with pytest.raises(RuntimeError, match="hold 7 offices but FDIC reports 9"):
            ingest_fdic.download([2023])
    assert not (config.RAW / "sod" / "2023" / ingest_fdic.NATIONAL_CHECK_FILE).exists()


def test_transform_builds_metro_and_bank_tables(fdic_api, capsys):
    ingest_fdic.run(years=[2022, 2023])
    out = capsys.readouterr().out
    assert "1 Connecticut offices use pre-2022 county codes" in out
    assert "2 metro-years have no deposits outside main offices" in out  # Birmingham, both years

    metro = pd.read_parquet(config.INTERIM / "msa_year" / "sod.parquet").set_index(["cbsa_code", "year"])
    charlotte = metro.loc[("16740", 2023)]
    assert charlotte["sod_deposits_usd"] == 400_000_000  # $1,000s -> dollars; empty deposits skipped
    assert charlotte["sod_main_office_deposits_usd"] == 300_000_000
    # Branches: 3510's main office is full-service, so it counts; 9999's drive-through doesn't
    assert (charlotte["sod_offices_count"], charlotte["sod_branches_count"], charlotte["sod_institutions_count"]) == (5, 4, 3)
    assert metro.loc[("13820", 2023), "sod_deposits_usd"] == 50_000_000  # code 1073 read as county 01073
    assert metro.loc[("16740", 2022), "sod_deposits_usd"] == 310_000_000
    assert set(metro.index.get_level_values("cbsa_code")) == {"16740", "13820"}  # micropolitan and CT left out

    # Concentration among organizations: Holding A has 330 of Charlotte's 400, Holding B 70, bank 9999 nothing
    assert charlotte["sod_deposit_hhi"] == pytest.approx(82.5 ** 2 + 17.5 ** 2)  # 7,112.5
    assert charlotte["sod_top3_deposit_share"] == 1.0  # three organizations or fewer: exactly 1
    # Without main offices A keeps its two branches (30) and B its branch (70); B's main office is in Birmingham
    assert charlotte["sod_deposit_ex_main_office_hhi"] == pytest.approx(30 ** 2 + 70 ** 2)  # 5,800
    assert metro.loc[("16740", 2022), "sod_deposit_ex_main_office_hhi"] == 10_000  # A has only its main office
    birmingham = metro.loc[("13820", 2023)]
    assert birmingham["sod_deposit_hhi"] == 10_000 and pd.isna(birmingham["sod_deposit_ex_main_office_hhi"])
    assert metro["sod_top3_deposit_share_3y_change_net"].isna().all()  # no year three years earlier

    bank = pd.read_parquet(config.INTERIM / "bank_msa_year" / "sod.parquet").set_index(["rssd_id", "cbsa_code", "year"])
    a = bank.loc[("480228", "16740", 2023)]
    assert a["sod_deposits_usd"] == 330_000_000 and a["sod_main_office_deposits_usd"] == 300_000_000
    assert a["sod_deposit_share"] == pytest.approx(0.825)
    assert (a["sod_top_holder_rssd_id"], a["sod_top_holder_name"], a["sod_cert"]) == ("1073757", "Holding A", "3510")
    c = bank.loc[("123", "16740", 2023)]
    assert pd.isna(c["sod_deposits_usd"]) and pd.isna(c["sod_deposit_share"])  # missing stays missing
    assert c["sod_main_office_deposits_usd"] == 0 and c["sod_branches_count"] == 0  # drive-through isn't a branch
    assert (c["sod_top_holder_rssd_id"], c["sod_top_holder_name"]) == ("123", "Bank 9999")  # its own top holder
    shares = bank.xs(("16740", 2023), level=("cbsa_code", "year"))["sod_deposit_share"]
    assert shares.sum() == pytest.approx(1.0)

    build_panel.build_all()
    assert checks.run_checks()
    panel = pd.read_parquet(config.PROCESSED / "msa_year.parquet")
    assert {"sod_deposits_usd", "sod_institutions_count"} <= set(panel.columns)
    assert len(pd.read_parquet(config.PROCESSED / "bank_msa_year.parquet")) == 7  # 4 bank-metros in 2023, 3 in 2022


def test_concentration_counts_organizations_and_compares_with_three_years_earlier():
    def row(cbsa, year, rssd, deposits, hc=None, main=False, cert=None):
        return {"cbsa_code": cbsa, "year": year, "cert": cert or f"c{rssd}", "rssd_id": rssd,
                "hc_rssd_id": hc, "deposits_usd": deposits, "main_office": main}

    data = pd.DataFrame([
        # 2019: banks 1 and 2 share holding company 100, so they count as one organization (60)
        row("11111", 2019, "1", 40.0, hc="100", main=True), row("11111", 2019, "2", 20.0, hc="100"),
        row("11111", 2019, "3", 25.0), row("11111", 2019, "4", 10.0), row("11111", 2019, "5", 5.0),
        # 2022: three organizations
        row("11111", 2022, "1", 50.0, hc="100", main=True), row("11111", 2022, "3", 30.0),
        row("11111", 2022, "4", 20.0),
        # An office with no RSSD ID counts with its institution; a metro with no deposits gets empty measures
        row("22222", 2022, None, 30.0, cert="77"), row("22222", 2022, "9", 70.0),
        row("33333", 2022, "8", 0.0), row("33333", 2022, "6", None),
    ]).astype({"cbsa_code": "string", "cert": "string", "rssd_id": "string", "hc_rssd_id": "string"})

    out = ingest_fdic._concentration(data)
    early, late = out.loc[("11111", 2019)], out.loc[("11111", 2022)]
    assert early["sod_deposit_hhi"] == pytest.approx(60 ** 2 + 25 ** 2 + 10 ** 2 + 5 ** 2)  # 4,350
    assert early["sod_top3_deposit_share"] == pytest.approx(0.95)
    # Without main offices, holding company 100 keeps only bank 2's 20, of 60
    assert early["sod_deposit_ex_main_office_hhi"] == pytest.approx(10_000 * (20 ** 2 + 25 ** 2 + 10 ** 2 + 5 ** 2) / 60 ** 2)
    assert early["sod_top3_deposit_ex_main_office_share"] == pytest.approx(55 / 60)
    assert pd.isna(early["sod_top3_deposit_share_3y_change_net"])  # 2016 isn't in the data
    assert late["sod_deposit_hhi"] == pytest.approx(50 ** 2 + 30 ** 2 + 20 ** 2)  # 3,800
    assert late["sod_top3_deposit_share_3y_change_net"] == pytest.approx(1 - 0.95)
    assert late["sod_deposit_ex_main_office_hhi"] == pytest.approx(60 ** 2 + 40 ** 2)  # 5,200
    assert late["sod_top3_deposit_ex_main_office_share_3y_change_net"] == pytest.approx(1 - 55 / 60)
    assert out.loc[("22222", 2022), "sod_deposit_hhi"] == pytest.approx(30 ** 2 + 70 ** 2)  # not 4,900 or 10,000
    assert out.loc[("33333", 2022)].isna().all()


def test_a_state_too_big_for_one_request_stops_the_pull(fdic_api, monkeypatch):
    monkeypatch.setattr(ingest_fdic, "PAGE_SIZE", 2)
    with pytest.raises(ValueError, match="don't fit in one 2-row request"):
        ingest_fdic.download([2023])


def test_a_refused_request_says_how_to_get_a_key(fdic_api, monkeypatch):
    monkeypatch.setattr(config, "FDIC_API_KEY", "")
    fdic_api.require_key = True
    with pytest.raises(RuntimeError, match="api.data.gov/signup"):
        ingest_fdic.download([2023])


def test_other_errors_dont_blame_the_key(fdic_api):
    fdic_api.status = 400
    with pytest.raises(RuntimeError) as error:
        ingest_fdic.download([2023])
    assert "400" in str(error.value) and "FDIC_API_KEY" not in str(error.value)
