"""Concat-mode xlsx example: every tab merged into one table with a source_tab column."""

from pathlib import Path

from _helpers import parse_money  # type: ignore[import-not-found]

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "sales.xlsx"

definition = {
    "key": "sales_all",
    "kind": "xlsx",
    "path": str(FIXTURE),
    "mode": "concat",
    "table": "sales_all",
    "sheets": ["Jan", "Feb", "Mar"],
    "source_tab_column": "month",
    "columns": {
        "Order ID": {"name": "order_id", "type": "int"},
        "Order Date": "order_date",
        "Amount": {"name": "amount", "type": "float", "transform": parse_money},
        "Notes": "notes",
    },
}
