"""Reads source files, applies column specs, and writes SQLite tables."""

from __future__ import annotations

import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import polars as pl
import sqlite_utils
from sqlite_utils.db import Table

from mesa.validator import (
    ColumnDictSpec,
    ColumnSpec,
    CsvDefinition,
    ValidatedDefinition,
    XlsxConcatDefinition,
    XlsxPerTabDefinition,
)

TYPE_MAP: dict[str, type] = {
    "int": int,
    "float": float,
    "text": str,
    "bool": int,
    "date": str,
    "datetime": str,
}

_POLARS_DTYPE: dict[type, pl.DataType] = {
    int: pl.Int64(),
    float: pl.Float64(),
    str: pl.Utf8(),
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
        p = Path(d.definition.path)
        if not p.is_file():
            missing.append((d.key, p))
    return missing


def run(active: list[ValidatedDefinition], db_path: Path) -> list[IngestResult]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite_utils.Database(db_path)
    return [_ingest_one(d, db) for d in active]


def _ingest_one(d: ValidatedDefinition, db: sqlite_utils.Database) -> IngestResult:
    try:
        defn = d.definition
        if isinstance(defn, CsvDefinition):
            return _ingest_csv(d.key, defn, db)
        if isinstance(defn, XlsxPerTabDefinition):
            return _ingest_xlsx_per_tab(d.key, defn, db)
        if isinstance(defn, XlsxConcatDefinition):
            return _ingest_xlsx_concat(d.key, defn, db)
        raise IngestError(f"unknown definition type {type(defn).__name__}")
    except Exception as e:
        return IngestResult(
            key=d.key,
            status="error",
            message=f"{type(e).__name__}: {e}",
            traceback=traceback.format_exc(),
        )


def _ingest_csv(key: str, defn: CsvDefinition, db: sqlite_utils.Database) -> IngestResult:
    df = pl.read_csv(
        defn.path,
        skip_rows=defn.header_row,
        encoding=defn.encoding,
        separator=defn.delimiter,
        infer_schema_length=0,
    )
    final_df, final_types = _apply_columns(df, defn.columns)
    rows = _write(db, defn.table, final_df, final_types)
    return IngestResult(key=key, status="ok", tables=[defn.table], rows_written=rows)


def _ingest_xlsx_per_tab(
    key: str, defn: XlsxPerTabDefinition, db: sqlite_utils.Database
) -> IngestResult:
    tables: list[str] = []
    total_rows = 0
    for tab_name, sheet_cfg in defn.sheets.items():
        df = _read_xlsx_sheet(defn.path, tab_name, sheet_cfg.header_row)
        final_df, final_types = _apply_columns(df, sheet_cfg.columns)
        rows = _write(db, sheet_cfg.table, final_df, final_types)
        tables.append(sheet_cfg.table)
        total_rows += rows
    return IngestResult(key=key, status="ok", tables=tables, rows_written=total_rows)


def _ingest_xlsx_concat(
    key: str, defn: XlsxConcatDefinition, db: sqlite_utils.Database
) -> IngestResult:
    frames: list[pl.DataFrame] = []
    final_types: dict[str, type] = {}
    for tab_name in defn.sheets:
        df = _read_xlsx_sheet(defn.path, tab_name, defn.header_row)
        final_df, final_types = _apply_columns(df, defn.columns)
        final_df = final_df.with_columns(pl.lit(tab_name).alias(defn.source_tab_column))
        frames.append(final_df)
    full = pl.concat(frames, how="vertical_relaxed")
    final_types[defn.source_tab_column] = str
    rows = _write(db, defn.table, full, final_types)
    return IngestResult(key=key, status="ok", tables=[defn.table], rows_written=rows)


def _read_xlsx_sheet(path: str, tab: str, header_row: int) -> pl.DataFrame:
    return pl.read_excel(
        path,
        sheet_name=tab,
        engine="calamine",
        read_options={"header_row": header_row},
    )


def _apply_columns(
    df: pl.DataFrame, spec: dict[str, ColumnSpec]
) -> tuple[pl.DataFrame, dict[str, type]]:
    """Apply rename / transform / type per the polymorphic spec.

    Returns a new dataframe with only the spec'd columns, renamed to their final
    names, and a mapping of final_name -> sqlite_utils column type.
    """
    missing = [src for src in spec if src not in df.columns]
    if missing:
        raise IngestError(f"source columns not found: {missing}")

    rename_map: dict[str, str] = {}
    transforms: list[tuple[str, Callable[[Any], Any], type | None]] = []
    final_types: dict[str, type] = {}

    for src, col_spec in spec.items():
        rename_map[src] = _final_name(src, col_spec)
        if isinstance(col_spec, ColumnDictSpec):
            sql_type = TYPE_MAP[col_spec.type] if col_spec.type else None
            if sql_type is not None:
                final_types[rename_map[src]] = sql_type
            if col_spec.transform is not None:
                transforms.append((src, col_spec.transform, sql_type))
        elif callable(col_spec):
            transforms.append((src, col_spec, None))

    out = df.select(list(spec.keys()))
    for src, fn, sql_type in transforms:
        return_dtype = _POLARS_DTYPE.get(sql_type) if sql_type else pl.Object()
        out = out.with_columns(
            pl.col(src).map_elements(fn, return_dtype=return_dtype).alias(src)
        )
    return out.rename(rename_map), final_types


def _final_name(src: str, col_spec: ColumnSpec) -> str:
    if isinstance(col_spec, str):
        return col_spec
    if isinstance(col_spec, ColumnDictSpec):
        return col_spec.name
    return src


def _write(
    db: sqlite_utils.Database,
    table: str,
    df: pl.DataFrame,
    final_types: dict[str, type],
) -> int:
    t = cast(Table, db.table(table))
    t.drop(ignore=True)
    records = df.to_dicts()
    if not records:
        t.create({col: final_types.get(col, str) for col in df.columns})
        return 0
    t.insert_all(records, columns=final_types or None)
    return len(records)
