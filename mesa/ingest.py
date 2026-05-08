"""Reads source files, applies column specs, and writes SQLite tables."""

from __future__ import annotations

import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import sqlite_utils
from sqlite_utils.db import Table

from mesa.validator import ValidatedDefinition

TYPE_MAP: dict[str, type] = {
    "int": int,
    "float": float,
    "text": str,
    "bool": int,
    "date": str,
    "datetime": str,
}


@dataclass
class IngestResult:
    key: str
    status: str  # "ok" | "error"
    tables: list[str] = field(default_factory=list)
    rows_written: int = 0
    message: str | None = None
    traceback: str | None = None


class IngestError(Exception):
    pass


def precheck_paths(active: list[ValidatedDefinition]) -> list[tuple[str, Path]]:
    """Return [(key, path)] for any source files that don't exist."""
    missing: list[tuple[str, Path]] = []
    for d in active:
        p = Path(d.raw["path"])
        if not p.is_file():
            missing.append((d.key, p))
    return missing


def run(active: list[ValidatedDefinition], db_path: Path) -> list[IngestResult]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite_utils.Database(db_path)
    results: list[IngestResult] = []
    for d in active:
        results.append(_ingest_one(d, db))
    return results


def _ingest_one(d: ValidatedDefinition, db: sqlite_utils.Database) -> IngestResult:
    try:
        if d.raw["kind"] == "csv":
            return _ingest_csv(d, db)
        if d.raw["kind"] == "xlsx":
            mode = d.raw.get("mode", "per_tab")
            if mode == "per_tab":
                return _ingest_xlsx_per_tab(d, db)
            return _ingest_xlsx_concat(d, db)
        raise IngestError(f"unknown kind {d.raw['kind']!r}")
    except Exception as e:
        return IngestResult(
            key=d.key,
            status="error",
            message=f"{type(e).__name__}: {e}",
            traceback=traceback.format_exc(),
        )


def _ingest_csv(d: ValidatedDefinition, db: sqlite_utils.Database) -> IngestResult:
    raw = d.raw
    df = pd.read_csv(
        raw["path"],
        header=raw.get("header_row", 0),
        encoding=raw.get("encoding", "utf-8"),
        sep=raw.get("delimiter", ","),
    )
    final_df, final_types = _apply_columns(df, raw["columns"])
    rows = _write(db, raw["table"], final_df, final_types)
    return IngestResult(key=d.key, status="ok", tables=[raw["table"]], rows_written=rows)


def _ingest_xlsx_per_tab(d: ValidatedDefinition, db: sqlite_utils.Database) -> IngestResult:
    raw = d.raw
    tables: list[str] = []
    total_rows = 0
    for tab_name, sheet_cfg in raw["sheets"].items():
        df = pd.read_excel(
            raw["path"],
            sheet_name=tab_name,
            header=sheet_cfg.get("header_row", 0),
        )
        final_df, final_types = _apply_columns(df, sheet_cfg["columns"])
        rows = _write(db, sheet_cfg["table"], final_df, final_types)
        tables.append(sheet_cfg["table"])
        total_rows += rows
    return IngestResult(key=d.key, status="ok", tables=tables, rows_written=total_rows)


def _ingest_xlsx_concat(d: ValidatedDefinition, db: sqlite_utils.Database) -> IngestResult:
    raw = d.raw
    source_tab_column = raw.get("source_tab_column", "source_tab")
    header_row = raw.get("header_row", 0)
    frames: list[pd.DataFrame] = []
    final_types: dict[str, type] = {}
    for tab_name in raw["sheets"]:
        df = pd.read_excel(raw["path"], sheet_name=tab_name, header=header_row)
        final_df, final_types = _apply_columns(df, raw["columns"])
        final_df[source_tab_column] = tab_name
        frames.append(final_df)
    full = pd.concat(frames, ignore_index=True)
    rows = _write(db, raw["table"], full, final_types)
    return IngestResult(key=d.key, status="ok", tables=[raw["table"]], rows_written=rows)


def _apply_columns(df: pd.DataFrame, spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, type]]:
    """Apply rename / transform / type per the polymorphic spec.

    Returns a new dataframe with only the spec'd columns, renamed to their final names,
    and a mapping of final_name -> sqlite_utils column type.
    """
    missing = [src for src in spec if src not in df.columns]
    if missing:
        raise IngestError(f"source columns not found: {missing}")

    rename_map: dict[str, str] = {}
    transforms: list[tuple[str, Callable[[Any], Any]]] = []
    final_types: dict[str, type] = {}

    for src, col_spec in spec.items():
        final_name = _final_name(src, col_spec)
        rename_map[src] = final_name
        if isinstance(col_spec, dict):
            if "transform" in col_spec:
                transforms.append((src, col_spec["transform"]))
            if "type" in col_spec:
                final_types[final_name] = TYPE_MAP[col_spec["type"]]
        elif callable(col_spec):
            transforms.append((src, col_spec))

    out = df[list(spec.keys())].copy()
    for src, fn in transforms:
        out[src] = out[src].map(fn)
    out = out.rename(columns=rename_map)
    return out, final_types


def _final_name(src: str, col_spec: Any) -> str:
    if isinstance(col_spec, str):
        return col_spec
    if isinstance(col_spec, dict):
        return str(col_spec["name"])
    return src


def _write(
    db: sqlite_utils.Database,
    table: str,
    df: pd.DataFrame,
    final_types: dict[str, type],
) -> int:
    t = db.table(table)
    assert isinstance(t, Table)
    t.drop(ignore=True)
    records = df.to_dict(orient="records")
    if not records:
        t.create({col: final_types.get(col, str) for col in df.columns})
        return 0
    t.insert_all(records, columns=final_types or None)
    return len(records)
