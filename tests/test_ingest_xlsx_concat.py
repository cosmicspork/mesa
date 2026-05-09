from pathlib import Path

import sqlite_utils

from mesa.ingest import run
from mesa.validator import ValidatedDefinition, XlsxConcatDefinition


def _vd(raw: dict) -> ValidatedDefinition:
    return ValidatedDefinition(
        source_path=Path("definitions/sales_all.py"),
        definition=XlsxConcatDefinition.model_validate(raw),
    )


def test_concat_merges_tabs_with_source_tab_column(xlsx_file: Path, tmp_path: Path) -> None:
    raw = {
        "key": "sales_all",
        "kind": "xlsx",
        "path": str(xlsx_file),
        "mode": "concat",
        "table": "sales_all",
        "sheets": ["Jan", "Feb"],
        "columns": {
            "Order ID": {"name": "order_id", "type": "int"},
            "Order Date": "order_date",
        },
    }
    db_path = tmp_path / "db.sqlite"
    results = run([_vd(raw)], db_path)
    assert results[0].status == "ok", results[0].message

    db = sqlite_utils.Database(db_path)
    rows = list(db["sales_all"].rows)
    assert len(rows) == 3  # 2 from Jan + 1 from Feb
    tabs = {r["source_tab"] for r in rows}
    assert tabs == {"Jan", "Feb"}
    jan_rows = [r for r in rows if r["source_tab"] == "Jan"]
    assert {r["order_id"] for r in jan_rows} == {101, 102}


def test_concat_custom_source_tab_column(xlsx_file: Path, tmp_path: Path) -> None:
    raw = {
        "key": "sales_all",
        "kind": "xlsx",
        "path": str(xlsx_file),
        "mode": "concat",
        "table": "sales_all",
        "source_tab_column": "tab_name",
        "sheets": ["Jan", "Feb"],
        "columns": {"Order ID": "order_id"},
    }
    db_path = tmp_path / "db.sqlite"
    run([_vd(raw)], db_path)
    db = sqlite_utils.Database(db_path)
    cols = [c.name for c in db["sales_all"].columns]
    assert "tab_name" in cols
    assert "source_tab" not in cols
