from pathlib import Path

import sqlite_utils

from mesa.ingest import precheck_paths, run
from mesa.validator import ValidatedDefinition


def _digits(v: object) -> str | None:
    if v is None:
        return None
    digits = "".join(c for c in str(v) if c.isdigit())
    return digits or None


def _vd(raw: dict) -> ValidatedDefinition:
    return ValidatedDefinition(
        source_path=Path("definitions/contacts.py"),
        key=raw["key"],
        raw=raw,
        tables=[raw["table"]],
    )


def test_csv_rename_dict_callable_and_transform(csv_file: Path, tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    raw = {
        "key": "contacts",
        "kind": "csv",
        "path": str(csv_file),
        "table": "contacts",
        "columns": {
            "Email": "email",
            "First Name": {"name": "first_name", "type": "text"},
            "Phone": {"name": "phone", "type": "text", "transform": _digits},
            "Joined": {"name": "joined", "type": "text"},
        },
    }
    results = run([_vd(raw)], db_path)
    assert len(results) == 1
    assert results[0].status == "ok", results[0].message
    assert results[0].rows_written == 2

    db = sqlite_utils.Database(db_path)
    rows = list(db["contacts"].rows)
    assert rows[0] == {
        "email": "a@x.com",
        "first_name": "Alice",
        "phone": "5551112222",
        "joined": "2024-01-15",
    }
    assert rows[1]["phone"] == "5553334444"


def test_csv_drops_unmentioned_source_columns(csv_file: Path, tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    raw = {
        "key": "contacts",
        "kind": "csv",
        "path": str(csv_file),
        "table": "contacts",
        "columns": {"Email": "email"},
    }
    run([_vd(raw)], db_path)
    db = sqlite_utils.Database(db_path)
    assert [c.name for c in db["contacts"].columns] == ["email"]


def test_csv_missing_source_column_isolated(tmp_path: Path) -> None:
    csv_path = tmp_path / "x.csv"
    csv_path.write_text("A,B\n1,2\n", encoding="utf-8")
    raw = {
        "key": "things",
        "kind": "csv",
        "path": str(csv_path),
        "table": "things",
        "columns": {"A": "a", "Missing": "missing"},
    }
    db_path = tmp_path / "db.sqlite"
    results = run([_vd(raw)], db_path)
    assert results[0].status == "error"
    assert "Missing" in (results[0].message or "")


def test_precheck_reports_missing_paths(tmp_path: Path) -> None:
    raw = {
        "key": "things",
        "kind": "csv",
        "path": str(tmp_path / "nope.csv"),
        "table": "things",
        "columns": {"A": "a"},
    }
    missing = precheck_paths([_vd(raw)])
    assert missing == [("things", tmp_path / "nope.csv")]


def test_csv_dropped_table_does_not_persist_old_rows(csv_file: Path, tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    raw = {
        "key": "contacts",
        "kind": "csv",
        "path": str(csv_file),
        "table": "contacts",
        "columns": {"Email": "email"},
    }
    run([_vd(raw)], db_path)
    run([_vd(raw)], db_path)
    db = sqlite_utils.Database(db_path)
    assert db["contacts"].count == 2
