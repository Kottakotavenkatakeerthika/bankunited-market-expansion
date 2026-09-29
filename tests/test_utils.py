import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from src import utils


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def file_server(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    served = tmp_path / "served"
    served.mkdir()
    (served / "sample.csv").write_text("a,b\n1,2\n")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(served)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", served
    server.shutdown()


def test_normalize_code_keeps_leading_zeros():
    out = utils.normalize_code([1073, "1073", 1073.0, " 01073 ", None, float("nan"), ""], 5)
    assert out.iloc[:4].tolist() == ["01073"] * 4
    assert out.iloc[4:].isna().all()


def test_redact_url_hides_credentials():
    url = "https://api.example.gov/obs?series_id=ABC&api_key=SECRET123&UserID=ME"
    query = parse_qs(urlparse(utils.redact_url(url)).query)
    assert query["series_id"] == ["ABC"]
    assert query["api_key"] == ["REDACTED"] and query["UserID"] == ["REDACTED"]


def test_fetch_downloads_once_logs_and_flags_revisions(project, file_server):
    base, served = file_server
    path = utils.fetch(f"{base}/sample.csv", "demo", params={"api_key": "SECRET"})
    assert path.read_text() == "a,b\n1,2\n"
    row = utils.read_manifest().iloc[0]
    assert (row["source"], row["file"]) == ("demo", "demo/sample.csv")
    assert "SECRET" not in row["url"]
    assert row["sha256"] == utils.sha256_file(path)

    (served / "sample.csv").write_text("revised\n")
    assert utils.fetch(f"{base}/sample.csv", "demo").read_text() == "a,b\n1,2\n"  # reused, not re-pulled
    utils.fetch(f"{base}/sample.csv", "demo", force=True)
    manifest = utils.read_manifest()
    assert len(manifest) == 1
    assert "revised since" in manifest.iloc[0]["notes"]


def test_register_local_file_requires_raw_folder(project, tmp_path):
    outside = tmp_path / "elsewhere.zip"
    outside.write_bytes(b"x")
    with pytest.raises(ValueError, match="Move"):
        utils.register_local_file(outside, "call")
    inside = project["RAW"] / "call" / "bulk.zip"
    inside.parent.mkdir()
    inside.write_bytes(b"zip")
    entry = utils.register_local_file(inside, "call", url="https://cdr.ffiec.gov/public/")
    assert entry["file"] == "call/bulk.zip" and entry["notes"] == "downloaded by hand"


def test_write_interim_enforces_the_contract(project):
    good = pd.DataFrame({"cbsa_code": [16740, 13820], "year": ["2022", "2022"],
                         "cbp_establishments_count": [10, 20]})
    saved = pd.read_parquet(utils.write_interim(good, "cbp", "msa_year"))
    assert saved["cbsa_code"].tolist() == ["13820", "16740"]
    assert saved["year"].dtype == "int64"
    with pytest.raises(ValueError, match="must start with"):
        utils.write_interim(good.rename(columns={"cbp_establishments_count": "establishments"}), "cbp", "msa_year")
    with pytest.raises(ValueError, match="share a key"):
        utils.write_interim(pd.concat([good, good]), "cbp", "msa_year")
    with pytest.raises(ValueError, match="null"):
        utils.write_interim(good.assign(year=[2022, None]), "cbp", "msa_year")


def test_failed_download_does_not_leak_the_key(project, file_server):
    base, _ = file_server
    with pytest.raises(RuntimeError) as failure:
        utils.fetch(f"{base}/missing.csv", "demo", params={"api_key": "SECRET"})
    assert "404" in str(failure.value) and "SECRET" not in str(failure.value)
    assert not list((project["RAW"] / "demo").glob("*"))  # no partial file left behind


def test_raw_folder_can_live_on_the_shared_drive(tmp_path, monkeypatch):
    import importlib

    from src import config

    drive_raw = tmp_path / "Drive" / "BankUnited Pod Data" / "raw"
    monkeypatch.setenv("RAW_DATA_DIR", str(drive_raw))
    try:
        importlib.reload(config)
        assert config.RAW == drive_raw
    finally:
        monkeypatch.delenv("RAW_DATA_DIR")
        importlib.reload(config)
