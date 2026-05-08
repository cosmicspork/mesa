"""Validates definition contracts and runs cross-definition checks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mesa.loader import LoadedDefinition

NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
ALLOWED_TYPES = {"int", "float", "text", "bool", "date", "datetime"}
ALLOWED_KINDS = {"xlsx", "csv"}
ALLOWED_XLSX_MODES = {"per_tab", "concat"}
ALLOWED_DICT_KEYS = {"name", "type", "nullable", "transform"}


@dataclass(frozen=True)
class ValidationError:
    source_path: Path | None
    key: str | None
    message: str

    def __str__(self) -> str:
        loc = self.source_path.name if self.source_path else "<config>"
        tag = f"{loc}:{self.key}" if self.key else loc
        return f"[{tag}] {self.message}"


@dataclass
class ValidatedDefinition:
    source_path: Path
    key: str
    raw: dict[str, Any]
    tables: list[str] = field(default_factory=list)


def validate_all(
    loaded: list[LoadedDefinition], active: list[str]
) -> tuple[list[ValidatedDefinition], list[ValidationError]]:
    """Validate every loaded definition; report cross-def collisions."""
    valid: list[ValidatedDefinition] = []
    errors: list[ValidationError] = []

    for d in loaded:
        per_def_errors = _validate_one(d.source_path, d.raw)
        if per_def_errors:
            errors.extend(per_def_errors)
            continue
        valid.append(
            ValidatedDefinition(
                source_path=d.source_path,
                key=d.raw["key"],
                raw=d.raw,
                tables=_final_tables(d.raw),
            )
        )

    errors.extend(_cross_definition_checks(valid, active))

    valid_keys = {v.key for v in valid}
    surviving = [v for v in valid if v.key in valid_keys]
    return surviving, errors


def _validate_one(source_path: Path, raw: dict[str, Any]) -> list[ValidationError]:
    errors: list[ValidationError] = []
    key = raw.get("key")

    if not isinstance(key, str) or not NAME_RE.match(key):
        errors.append(
            ValidationError(source_path, None, f"`key` must match {NAME_RE.pattern}; got {key!r}")
        )
        return errors

    kind = raw.get("kind")
    if kind not in ALLOWED_KINDS:
        errors.append(
            ValidationError(
                source_path, key, f"`kind` must be one of {sorted(ALLOWED_KINDS)}; got {kind!r}"
            )
        )
        return errors

    path = raw.get("path")
    if not isinstance(path, str) or not path:
        errors.append(ValidationError(source_path, key, "`path` must be a non-empty string"))

    if kind == "csv":
        errors.extend(_validate_csv(source_path, key, raw))
    elif kind == "xlsx":
        errors.extend(_validate_xlsx(source_path, key, raw))

    return errors


def _validate_csv(source_path: Path, key: str, raw: dict[str, Any]) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if "sheets" in raw or "mode" in raw:
        errors.append(
            ValidationError(source_path, key, "csv definition must not include `sheets` or `mode`")
        )
    table = raw.get("table")
    if not isinstance(table, str) or not NAME_RE.match(table):
        errors.append(
            ValidationError(
                source_path, key, f"`table` must match {NAME_RE.pattern}; got {table!r}"
            )
        )
    columns = raw.get("columns")
    errors.extend(_validate_columns(source_path, key, columns))
    return errors


def _validate_xlsx(source_path: Path, key: str, raw: dict[str, Any]) -> list[ValidationError]:
    errors: list[ValidationError] = []
    mode = raw.get("mode", "per_tab")
    if mode not in ALLOWED_XLSX_MODES:
        return [
            ValidationError(
                source_path,
                key,
                f"`mode` must be one of {sorted(ALLOWED_XLSX_MODES)}; got {mode!r}",
            )
        ]

    if mode == "per_tab":
        errors.extend(_validate_xlsx_per_tab(source_path, key, raw))
    else:
        errors.extend(_validate_xlsx_concat(source_path, key, raw))
    return errors


def _validate_xlsx_per_tab(
    source_path: Path, key: str, raw: dict[str, Any]
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if "table" in raw or "columns" in raw:
        errors.append(
            ValidationError(
                source_path,
                key,
                "per_tab xlsx must not have top-level `table` or `columns`; specify per-sheet",
            )
        )
    sheets = raw.get("sheets")
    if not isinstance(sheets, dict) or not sheets:
        errors.append(
            ValidationError(source_path, key, "`sheets` must be a non-empty dict for per_tab mode")
        )
        return errors

    seen_tables: set[str] = set()
    for tab_name, sheet_cfg in sheets.items():
        if not isinstance(tab_name, str) or not tab_name:
            errors.append(
                ValidationError(
                    source_path, key, f"sheet tab name must be a non-empty string; got {tab_name!r}"
                )
            )
            continue
        if not isinstance(sheet_cfg, dict):
            errors.append(ValidationError(source_path, key, f"sheets[{tab_name!r}] must be a dict"))
            continue
        table = sheet_cfg.get("table")
        if not isinstance(table, str) or not NAME_RE.match(table):
            errors.append(
                ValidationError(
                    source_path,
                    key,
                    f"sheets[{tab_name!r}].table must match {NAME_RE.pattern}; got {table!r}",
                )
            )
        elif table in seen_tables:
            errors.append(
                ValidationError(
                    source_path,
                    key,
                    f"sheets[{tab_name!r}].table {table!r} duplicates another sheet in this definition",
                )
            )
        else:
            seen_tables.add(table)
        errors.extend(
            _validate_columns(
                source_path, key, sheet_cfg.get("columns"), where=f"sheets[{tab_name!r}]"
            )
        )
        if "header_row" in sheet_cfg and not isinstance(sheet_cfg["header_row"], int):
            errors.append(
                ValidationError(source_path, key, f"sheets[{tab_name!r}].header_row must be an int")
            )
    return errors


def _validate_xlsx_concat(
    source_path: Path, key: str, raw: dict[str, Any]
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    table = raw.get("table")
    if not isinstance(table, str) or not NAME_RE.match(table):
        errors.append(
            ValidationError(
                source_path,
                key,
                f"concat mode requires `table` matching {NAME_RE.pattern}; got {table!r}",
            )
        )
    sheets = raw.get("sheets")
    if not isinstance(sheets, list) or not sheets:
        errors.append(
            ValidationError(
                source_path, key, "concat mode requires `sheets` as a non-empty list of tab names"
            )
        )
    elif not all(isinstance(s, str) and s for s in sheets):
        errors.append(
            ValidationError(source_path, key, "concat `sheets` must contain only non-empty strings")
        )
    if "source_tab_column" in raw:
        stc = raw["source_tab_column"]
        if not isinstance(stc, str) or not NAME_RE.match(stc):
            errors.append(
                ValidationError(
                    source_path,
                    key,
                    f"`source_tab_column` must match {NAME_RE.pattern}; got {stc!r}",
                )
            )
    errors.extend(_validate_columns(source_path, key, raw.get("columns")))
    return errors


def _validate_columns(
    source_path: Path,
    key: str,
    columns: Any,
    where: str = "columns",
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if not isinstance(columns, dict) or not columns:
        return [ValidationError(source_path, key, f"`{where}` must be a non-empty dict")]
    seen_final: set[str] = set()
    for src, spec in columns.items():
        if not isinstance(src, str) or not src:
            errors.append(
                ValidationError(
                    source_path, key, f"{where}: source column name must be a non-empty string"
                )
            )
            continue
        final_name = _final_name(spec)
        if isinstance(spec, str):
            if not NAME_RE.match(spec):
                errors.append(
                    ValidationError(
                        source_path,
                        key,
                        f"{where}[{src!r}]: rename {spec!r} must match {NAME_RE.pattern}",
                    )
                )
        elif isinstance(spec, dict):
            errors.extend(_validate_dict_spec(source_path, key, src, spec, where))
        elif callable(spec):
            if not NAME_RE.match(src):
                errors.append(
                    ValidationError(
                        source_path,
                        key,
                        f"{where}[{src!r}]: callable preserves source name, which must match {NAME_RE.pattern}",
                    )
                )
        else:
            errors.append(
                ValidationError(
                    source_path,
                    key,
                    f"{where}[{src!r}]: spec must be str, dict, or callable; got {type(spec).__name__}",
                )
            )
            continue
        if final_name and final_name in seen_final:
            errors.append(
                ValidationError(
                    source_path,
                    key,
                    f"{where}[{src!r}]: final column name {final_name!r} collides with another column",
                )
            )
        elif final_name:
            seen_final.add(final_name)
    return errors


def _validate_dict_spec(
    source_path: Path,
    key: str,
    src: str,
    spec: dict[str, Any],
    where: str,
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    unknown = set(spec) - ALLOWED_DICT_KEYS
    if unknown:
        errors.append(
            ValidationError(
                source_path,
                key,
                f"{where}[{src!r}]: unknown keys {sorted(unknown)} (allowed: {sorted(ALLOWED_DICT_KEYS)})",
            )
        )
    name = spec.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        errors.append(
            ValidationError(
                source_path,
                key,
                f"{where}[{src!r}]: dict spec requires `name` matching {NAME_RE.pattern}",
            )
        )
    if "type" in spec and spec["type"] not in ALLOWED_TYPES:
        errors.append(
            ValidationError(
                source_path,
                key,
                f"{where}[{src!r}]: type must be one of {sorted(ALLOWED_TYPES)}; got {spec['type']!r}",
            )
        )
    if "nullable" in spec and not isinstance(spec["nullable"], bool):
        errors.append(
            ValidationError(source_path, key, f"{where}[{src!r}]: `nullable` must be bool")
        )
    if "transform" in spec and not callable(spec["transform"]):
        errors.append(
            ValidationError(source_path, key, f"{where}[{src!r}]: `transform` must be callable")
        )
    return errors


def _final_name(spec: Any) -> str | None:
    if isinstance(spec, str):
        return spec
    if isinstance(spec, dict):
        n = spec.get("name")
        return n if isinstance(n, str) else None
    return None


def _final_tables(raw: dict[str, Any]) -> list[str]:
    kind = raw.get("kind")
    if kind == "csv":
        t = raw.get("table")
        return [t] if isinstance(t, str) else []
    if kind == "xlsx":
        mode = raw.get("mode", "per_tab")
        if mode == "concat":
            t = raw.get("table")
            return [t] if isinstance(t, str) else []
        sheets = raw.get("sheets") or {}
        if isinstance(sheets, dict):
            return [
                cfg["table"]
                for cfg in sheets.values()
                if isinstance(cfg, dict) and isinstance(cfg.get("table"), str)
            ]
    return []


def _cross_definition_checks(
    valid: list[ValidatedDefinition], active: list[str]
) -> list[ValidationError]:
    errors: list[ValidationError] = []

    seen_keys: dict[str, Path] = {}
    for v in valid:
        if v.key in seen_keys:
            errors.append(
                ValidationError(
                    v.source_path,
                    v.key,
                    f"duplicate key {v.key!r}; first defined in {seen_keys[v.key].name}",
                )
            )
        else:
            seen_keys[v.key] = v.source_path

    active_set = set(active)
    table_owner: dict[str, tuple[Path, str]] = {}
    for v in valid:
        if v.key not in active_set:
            continue
        for t in v.tables:
            if t in table_owner:
                prev_path, prev_key = table_owner[t]
                errors.append(
                    ValidationError(
                        v.source_path,
                        v.key,
                        f"table {t!r} also produced by {prev_path.name}:{prev_key}",
                    )
                )
            else:
                table_owner[t] = (v.source_path, v.key)

    valid_keys = {v.key for v in valid}
    for k in active:
        if k not in valid_keys:
            errors.append(
                ValidationError(None, k, f"ACTIVE key {k!r} is not defined or failed validation")
            )

    return errors
