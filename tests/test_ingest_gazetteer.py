import re
import zipfile

import pandas as pd
import pytest

from src import build_panel, checks, config
from src.ingest_gazetteer import VALUE_COLUMNS, read_points, transform

LAT, LON = VALUE_COLUMNS
# Real rows from the 2026 file: two metros, a micro area (left out) and a name that needs UTF-8.
PIPE_ROWS = [
    "CSAFP|GEOID|GEOIDFQ|NAME|CBSA_TYPE|ALAND|AWATER|ALAND_SQMI|AWATER_SQMI|INTPTLAT|INTPTLONG",
    "172|16740|310M700US16740|Charlotte-Concord-Gastonia, NC-SC Metro Area|1|14497321603|301901647|5597.447|116.565|35.166342|-80.797285",
    "142|13820|310M700US13820|Birmingham, AL Metro Area|1|13674988517|232656766|5279.943|89.829|33.462372|-86.814338",
    "|45000|310M700US45000|Susanville, CA Micro Area|2|11762097226|462944401|4541.371|178.744|40.707982|-120.608589",
    "490|41980|310M700US41980|San Juan-Bayamón-Caguas, PR Metro Area|1|3723785867|1459085922|1437.762|563.356|18.294595|-66.036952",
]


def write_zip(path, lines):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(path.stem + ".txt", ("\n".join(lines) + "\n").encode("utf-8"))
    return path


@pytest.fixture
def pipe_file(tmp_path):
    """Laid out like the 2025 and later files: pipe-delimited, with GEOIDFQ."""
    return write_zip(tmp_path / "2026_Gaz_cbsa_national.zip", PIPE_ROWS)


@pytest.fixture
def tab_file(tmp_path):
    """Laid out like the 2024 and earlier files: tab-delimited, no GEOIDFQ, padded with trailing spaces."""
    lines = []
    for row in PIPE_ROWS:
        cells = row.split("|")
        del cells[2]  # GEOIDFQ
        lines.append("\t".join(cells) + " " * 40)
    return write_zip(tmp_path / "2024_Gaz_cbsa_national.zip", lines)


def test_reads_metro_points_and_leaves_out_micro_areas(pipe_file):
    points = read_points(pipe_file).set_index("cbsa_code")
    assert sorted(points.index) == ["13820", "16740", "41980"]
    assert points.loc["16740", LAT] == 35.166342
    assert points.loc["16740", LON] == -80.797285
    assert points.loc["41980", LON] == -66.036952


def test_reads_the_older_tab_layout_the_same_way(pipe_file, tab_file):
    pd.testing.assert_frame_equal(read_points(tab_file), read_points(pipe_file))


def test_transform_repeats_each_point_for_every_year_and_the_checks_pass(project, pipe_file):
    transform([pipe_file], [2022, 2023])
    interim = pd.read_parquet(project["INTERIM"] / "msa_year" / "gazetteer.parquet")
    assert len(interim) == 6  # 3 metros x 2 years; the build keeps the universe's 2
    build_panel.build_all()
    panel = pd.read_parquet(project["PROCESSED"] / "msa_year.parquet")
    charlotte = panel[panel["cbsa_code"] == "16740"]
    assert charlotte[LAT].tolist() == [35.166342, 35.166342]
    assert charlotte[LON].tolist() == [-80.797285, -80.797285]
    assert checks.run_checks()
    report = (project["PROCESSED"] / "checks_report.md").read_text(encoding="utf-8")
    assert f"| msa_year | {LAT} within 17 to 72 | pass |" in report
    assert f"| msa_year | {LON} filled in every row | pass |" in report


def test_a_universe_metro_without_a_point_stops_the_ingest(project, tmp_path):
    no_birmingham = write_zip(tmp_path / "2026_Gaz_cbsa_national.zip", [r for r in PIPE_ROWS if "|13820|" not in r])
    with pytest.raises(ValueError, match=r"1 metros in msa_universe.csv have no point.*13820"):
        transform([no_birmingham], [2022, 2023])


def test_a_point_that_doesnt_read_as_a_number_stops_the_ingest(tmp_path):
    rows = [r.replace("|35.166342|", "||") for r in PIPE_ROWS]
    with pytest.raises(ValueError, match="without a readable point"):
        read_points(write_zip(tmp_path / "2026_Gaz_cbsa_national.zip", rows))


def test_the_dictionary_documents_both_columns_with_a_dated_release():
    rows = {row.column: row for row in checks.read_dictionary()["msa_year"]}
    lines = config.DATA_DICTIONARY.read_text(encoding="utf-8").splitlines()
    for column in VALUE_COLUMNS:
        assert rows[column].type == "numeric"
        released = [cell.strip() for cell in lines[rows[column].line - 1].strip().strip("|").split("|")][5]
        assert re.search(r"\d{4}", released), released


def test_the_download_url_matches_the_year():
    assert config.GAZETTEER_URL.endswith(f"/{config.GAZETTEER_YEAR}_Gazetteer/{config.GAZETTEER_YEAR}_Gaz_cbsa_national.zip")
