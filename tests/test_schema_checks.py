import pandas as pd
import pytest

from src import checks, config
from src.checks import DictionaryRow

SMALL_DICTIONARY = """# Data Dictionary

## Conventions

- **Keys.** `cbsa_code` is a 5-character string.

## Tables and keys

| Table | One row per | Key |
|---|---|---|
| `msa_year` | metro and year | `cbsa_code`, `year` |

## msa_year: one row per metro per year

| Column | Type | Unit | Definition |
|---|---|---|---|
| `cbsa_code` | string(5) | | Metro code |
| `year` | int | | Year |

**Known limitation.** A paragraph between tables isn't a row.

## bank_quarter: one row per bank per quarter

| Column | Type | Unit | Definition |
|---|---|---|---|
| `quarter_end` | date | | Last day of the quarter |
"""

ROWS = [DictionaryRow("cbsa_code", "string(5)", 1), DictionaryRow("year", "int", 2),
        DictionaryRow("cbp_establishments_count", "int", 3), DictionaryRow("sod_deposits_usd", "numeric", 4),
        DictionaryRow("sod_bank_name", "string", 5), DictionaryRow("quarter_end", "date", 6)]


def table(**columns):
    df = pd.DataFrame({
        "cbsa_code": ["16740", "13820"],
        "year": [2023, 2023],
        "cbp_establishments_count": [100.0, None],  # whole numbers stored as decimals still pass as int
        "sod_deposits_usd": [5e9, 2.5e9],
        "sod_bank_name": ["Bank A", None],
        "quarter_end": pd.to_datetime(["2023-06-30", "2023-06-30"]),
    })
    for name, values in columns.items():
        df[name] = values
    return df


def failed(results):
    return {r.check: r.detail for r in results if not r.passed and r.level == "error"}


def test_read_dictionary_takes_rows_only_from_table_sections(tmp_path):
    path = tmp_path / "dictionary.md"
    path.write_text(SMALL_DICTIONARY, encoding="utf-8")
    tables = checks.read_dictionary(path)
    assert set(tables) == {"msa_year", "bank_quarter"}  # Tables and keys has rows but isn't a table section
    assert [(r.column, r.type) for r in tables["msa_year"]] == [("cbsa_code", "string(5)"), ("year", "int")]
    assert tables["bank_quarter"][0].type == "date"
    assert tables["msa_year"][1].line == SMALL_DICTIONARY.splitlines().index("| `year` | int | | Year |") + 1


def test_a_table_that_matches_its_dictionary_rows_passes():
    results = checks.schema_checks("msa_year", table(), ROWS)
    assert failed(results) == {}
    assert not [r for r in results if not r.passed]  # every row is built, so no warning either


def test_an_undocumented_column_fails():
    results = checks.schema_checks("msa_year", table(cbp_new_count=[1, 2]), ROWS)
    assert "cbp_new_count" in failed(results)["every column has a dictionary row"]


def test_a_column_documented_twice_fails():
    rows = ROWS + [DictionaryRow("year", "int", 9)]
    assert failed(checks.schema_checks("msa_year", table(), rows))["no column has two dictionary rows"] == \
        "year on lines [2, 9]"


def test_an_unknown_type_fails():
    rows = [r if r.column != "year" else DictionaryRow("year", "integer", 2) for r in ROWS]
    assert "'integer'" in failed(checks.schema_checks("msa_year", table(), rows))["every dictionary Type is known"]


@pytest.mark.parametrize("column, values, problem", [
    ("cbp_establishments_count", [1.5, 2.0], "aren't whole numbers"),
    ("cbsa_code", ["1674", "13820"], "aren't 5 characters long"),
    ("cbsa_code", [16740, 13820], "not text"),
    ("sod_bank_name", [1, 2], "not text"),
    ("sod_deposits_usd", ["5e9", "2e9"], "not numbers"),
    ("year", [True, False], "not numbers"),
    ("quarter_end", ["2023-06-30", "2023-06-30"], "not dates"),
])
def test_values_that_dont_fit_their_type_fail(column, values, problem):
    detail = failed(checks.schema_checks("msa_year", table(**{column: values}), ROWS))["values fit their dictionary Type"]
    assert detail.startswith(column) and problem in detail


def test_missing_values_are_never_checked():
    empty = table(sod_bank_name=[None, None], cbp_establishments_count=[None, None])
    assert failed(checks.schema_checks("msa_year", empty, ROWS)) == {}
    assert failed(checks.schema_checks("msa_year", table(cbp_establishments_count=pd.array([1, None], dtype="Int64")), ROWS)) == {}


def test_a_documented_column_that_isnt_built_only_warns():
    results = checks.schema_checks("msa_year", table().drop(columns=["sod_bank_name"]), ROWS)
    assert failed(results) == {}
    warning = [r for r in results if not r.passed]
    assert len(warning) == 1 and warning[0].level == "warning" and "sod_bank_name" in warning[0].detail


def test_a_table_with_no_dictionary_section_fails():
    assert "no section headed '## msa_year: ...'" in failed(checks.schema_checks("msa_year", table(), []))[
        "every column has a dictionary row"]


def test_the_build_fails_on_an_undocumented_column_until_it_is_documented(project, document):
    pd.DataFrame({
        "cbsa_code": ["16740", "16740", "13820", "13820"],
        "year": [2022, 2023, 2022, 2023],
        "cbsa_title": ["Charlotte", "Charlotte", "Birmingham", "Birmingham"],
        "cbp_new_count": [1, 2, 3, 4],
    }).to_parquet(project["PROCESSED"] / "msa_year.parquet", index=False)
    assert not checks.run_checks()
    assert "cbp_new_count" in (project["PROCESSED"] / "checks_report.md").read_text(encoding="utf-8")
    document("msa_year", "cbp_new_count", "int")
    assert checks.run_checks()


def test_the_repo_dictionary_has_a_section_per_table_and_clean_rows():
    tables = checks.read_dictionary(config.DATA_DICTIONARY)
    for name in config.TABLES:
        rows = tables[name]
        names = [r.column for r in rows]
        assert len(names) == len(set(names)), f"{name} documents a column twice"
        assert all(checks.DICTIONARY_TYPES.fullmatch(r.type) for r in rows), name
        assert set(config.TABLES[name]) <= set(names), f"{name} doesn't document all its keys"


def test_the_committed_tables_fit_the_repo_dictionary():
    tables = checks.read_dictionary(config.DATA_DICTIONARY)
    built = [name for name in config.TABLES if (config.PROCESSED / f"{name}.parquet").exists()]
    if not built:
        pytest.skip("no processed tables in this checkout")
    for name in built:
        df = pd.read_parquet(config.PROCESSED / f"{name}.parquet")
        assert failed(checks.schema_checks(name, df, tables[name])) == {}, name
