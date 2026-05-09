"""Per-tab xlsx example: one SQLite table per spreadsheet tab."""

from pathlib import Path

from _helpers import parse_money  # type: ignore[import-not-found]

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "sales.xlsx"

definition = {
    "key": "sales",
    "kind": "xlsx",
    "path": str(FIXTURE),
    "mode": "per_tab",
    "sheets": {
        "Jan": {
            "table": "sales_jan",
            "columns": {
                "Order ID": {"name": "order_id", "type": "int"},
                "Order Date": "order_date",
                "Amount": {"name": "amount", "type": "float", "transform": parse_money},
                "Notes": "notes",
            },
        },
        "Feb": {
            "table": "sales_feb",
            "columns": {
                "Order ID": {"name": "order_id", "type": "int"},
                "Order Date": "order_date",
                "Amount": {"name": "amount", "type": "float", "transform": parse_money},
                "Notes": "notes",
            },
        },
    },
}
