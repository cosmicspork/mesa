from pathlib import Path

import sqlite_utils

from mesa.ingest import run
from mesa.validator import ValidatedDefinition, XlsxPerTabDefinition


def _money(v: object) -> float | None:
    if v is None or v == "":
        return None
    return float(str(v).replace("$", "").replace(",", "").strip())


def _vd(raw: dict, tables: list[str]) -> ValidatedDefinition:
    del tables  # tables now derived from the parsed pydantic model
    return ValidatedDefinition(
        source_path=Path("definitions/sales.py"),
        definition=XlsxPerTabDefinition.model_validate(raw),
    )


def test_per_tab_creates_one_table_per_sheet(xlsx_file: Path, tmp_path: Path) -> None:
    raw = {
        "key": "sales",
        "kind": "xlsx",
        "path": str(xlsx_file),
        "mode": "per_tab",
        "sheets": {
            "Jan": {
                "table": "sales_jan",
                "columns": {
                    "Order ID": {"name": "order_id", "type": "int"},
                    "Order Date": "order_date",
                    "Amount": {"name": "amount", "type": "float", "transform": _money},
                    "Notes": "notes",
                },
            },
            "Feb": {
                "table": "sales_feb",
                "columns": {
                    "Order ID": {"name": "order_id", "type": "int"},
                    "Order Date": "order_date",
                    "Amount": {"name": "amount", "type": "float", "transform": _money},
                    "Notes": "notes",
                },
            },
        },
    }
    db_path = tmp_path / "db.sqlite"
    results = run([_vd(raw, ["sales_jan", "sales_feb"])], db_path)
    assert results[0].status == "ok", results[0].message
    assert sorted(results[0].tables) == ["sales_feb", "sales_jan"]

    db = sqlite_utils.Database(db_path)
    jan_rows = list(db["sales_jan"].rows)
    assert len(jan_rows) == 2
    assert jan_rows[0]["order_id"] == 101
    assert jan_rows[0]["amount"] == 1234.50
    feb_rows = list(db["sales_feb"].rows)
    assert len(feb_rows) == 1
    assert feb_rows[0]["amount"] == 99.99


def test_per_tab_dict_type_creates_typed_columns(xlsx_file: Path, tmp_path: Path) -> None:
    raw = {
        "key": "sales",
        "kind": "xlsx",
        "path": str(xlsx_file),
        "sheets": {
            "Jan": {
                "table": "sales_jan",
                "columns": {"Order ID": {"name": "order_id", "type": "int"}},
            },
        },
    }
    db_path = tmp_path / "db.sqlite"
    run([_vd(raw, ["sales_jan"])], db_path)
    db = sqlite_utils.Database(db_path)
    cols = {c.name: c.type for c in db["sales_jan"].columns}
    assert cols["order_id"] == "INTEGER"
