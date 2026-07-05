"""Copy this to config.py and edit. config.py is gitignored (it names your
active definitions and points at your database path)."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

DB_PATH = REPO_ROOT / "db" / "mesa.sqlite"
DEFINITIONS_DIR = REPO_ROOT / "definitions"  # one .py per spreadsheet source (gitignored)

# Keys of the definitions to ingest.
ACTIVE: list[str] = [
    # "contacts",
]
