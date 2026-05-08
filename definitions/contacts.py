"""CSV example showing all three column-spec forms (rename, dict, callable)."""

from pathlib import Path

from _helpers import digits_only  # type: ignore[import-not-found]

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "contacts.csv"

definition = {
    "key": "contacts",
    "kind": "csv",
    "path": str(FIXTURE),
    "table": "contacts",
    "columns": {
        "Email": "email",
        "First Name": {"name": "first_name", "type": "text"},
        "Phone": {"name": "phone", "type": "text", "transform": digits_only},
        "Joined": {"name": "joined", "type": "text"},
    },
}
