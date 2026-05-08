# Mesa

A lightweight local ETL framework. Drop a Python file per spreadsheet into `definitions/`, double-click `run.bat` (or `./run.sh`), and Mesa rebuilds a SQLite database from xlsx and csv files on a mounted team drive — queryable from DataGrip.

## Install

Requires [uv](https://github.com/astral-sh/uv) and Python 3.13.

```bash
uv sync --extra dev
```

## Run

```bash
uv run mesa             # run the pipeline
uv run pytest           # tests
uv run ruff check .     # lint
uv run mypy mesa/       # type check
```

The `run.bat` and `run.sh` wrappers exist so the analyst can double-click rather than open a terminal.

## What the analyst touches

| File / folder | Purpose |
|---|---|
| `config.py` | The `ACTIVE` list of definition keys, plus `DB_PATH` |
| `definitions/*.py` | One file per spreadsheet source |
| `run.bat` / `run.sh` | Double-click to run |

## Architecture

- `mesa/` — framework. Auto-discovers `definitions/*.py`, validates each, ingests the active ones into SQLite via pandas + sqlite-utils. Written once.
- `definitions/` — one file per source. Each exposes a `definition = {...}` dict. Files starting with `_` are skipped by discovery but importable as modules (use them for shared helpers).
- `config.py` — lists active keys and the database path. Lives at the repo root, never inside the package.

Each run drops and rewrites only the tables belonging to active definitions. Tables from definitions that are commented out of `ACTIVE` are left alone.

## The Definition Contract

Each `definitions/*.py` defines a single top-level `definition` dict.

### xlsx, one table per tab

```python
definition = {
    "key": "sales",
    "kind": "xlsx",
    "path": r"\\team-drive\finance\sales.xlsx",
    "mode": "per_tab",
    "sheets": {
        "Jan": {
            "table": "sales_jan",
            "columns": {
                "Order ID":   {"name": "order_id", "type": "int"},
                "Order Date": "order_date",
                "Amount":     {"name": "amount", "type": "float", "transform": parse_money},
                "Notes":      "notes",
            },
        },
        "Feb": {"table": "sales_feb", "columns": {...}},
    },
}
```

### xlsx, concat mode

Same-schema tabs merged into one table with an auto-added `source_tab` column:

```python
definition = {
    "key": "sales_all",
    "kind": "xlsx",
    "path": r"\\team-drive\finance\sales.xlsx",
    "mode": "concat",
    "table": "sales_all",
    "sheets": ["Jan", "Feb", "Mar"],
    "source_tab_column": "month",          # optional, default "source_tab"
    "columns": {                           # one shared spec for all tabs
        "Order ID":   {"name": "order_id", "type": "int"},
        "Amount":     {"name": "amount", "type": "float"},
    },
}
```

### csv

```python
definition = {
    "key": "contacts",
    "kind": "csv",
    "path": r"\\team-drive\crm\contacts.csv",
    "table": "contacts",
    "encoding": "utf-8",                   # optional, default "utf-8"
    "delimiter": ",",                      # optional, default ","
    "columns": {
        "Email": "email",
        "First Name": {"name": "first_name", "type": "text"},
    },
}
```

## Columns spec cheat sheet

Each entry in `columns` maps a source column name to one of three forms:

| Form | Meaning | Example |
|---|---|---|
| `str` | rename only; type inferred | `"Email": "email"` |
| `dict` | rename + optional type/transform | `"Amount": {"name": "amount", "type": "float", "transform": parse_money}` |
| `callable` | transform; source name preserved (must be snake_case) | `"already_clean": lambda v: v.strip()` |

Dict keys: `name` (required), `type` (`int|float|text|bool|date|datetime`), `nullable` (default True), `transform` (callable).

Source columns not listed in `columns` are dropped — opt in explicitly.

## config.py

```python
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
DB_PATH = REPO_ROOT / "db" / "mesa.sqlite"
DEFINITIONS_DIR = REPO_ROOT / "definitions"

ACTIVE = [
    "sales",
    "contacts",
    # "sales_all",   ← commented out = disabled
]
```

To swap database versions: `DB_PATH = REPO_ROOT / "db" / "mesa_v2.sqlite"`. The old database is left untouched.

## Errors and exit codes

Mesa isolates failures so one bad definition doesn't stop the rest:

- **Load error** (broken Python file) — reported, file skipped, others continue.
- **Validation error** — reported, definition excluded, others continue.
- **Missing source path** — reports all missing paths and aborts before any database write.
- **Ingest error** — reported, definition's tables left in whatever state the failure produced; other definitions continue.

| Exit code | Meaning |
|---|---|
| 0 | All active definitions ingested cleanly |
| 1 | Ran, but at least one load/validation/ingest error |
| 2 | Aborted before ingest (config invalid, definitions dir missing, source paths missing) |

## Folder layout

```
mesa/
├── mesa/                  # framework code (rarely touched)
├── definitions/           # one .py per source; _-prefixed files are helpers
├── tests/
│   └── fixtures/          # sample xlsx/csv that ship with the example definitions
├── db/                    # SQLite output (.gitkeep)
├── config.py
├── pyproject.toml
├── run.bat
├── run.sh
└── README.md
```
