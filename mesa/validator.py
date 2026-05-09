"""Validates definition contracts and runs cross-definition checks.

The per-definition contract is expressed as pydantic models (CsvDefinition,
XlsxPerTabDefinition, XlsxConcatDefinition). Cross-definition checks
(duplicate keys, table-name collisions, missing ACTIVE keys) need the full
set and live in `_cross_definition_checks` below.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, model_validator
from pydantic import ValidationError as PydanticValidationError

from mesa.loader import LoadedDefinition

NAME_PATTERN = r"^[a-z][a-z0-9_]*$"
_NAME_RE = re.compile(NAME_PATTERN)

SnakeCaseName = Annotated[str, Field(pattern=NAME_PATTERN)]
ColumnType = Literal["int", "float", "text", "bool", "date", "datetime"]


class ColumnDictSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: SnakeCaseName
    type: ColumnType | None = None
    nullable: bool = True
    transform: Callable[[Any], Any] | None = None


# A column spec is one of:
#   - a snake_case rename string ("Email" -> "email")
#   - a ColumnDictSpec for rename + type + transform
#   - a bare callable (transform; preserves the source column name, which
#     must already be snake_case)
def _column_spec_kind(v: Any) -> str | None:
    if isinstance(v, str):
        return "str"
    if isinstance(v, dict | ColumnDictSpec):
        return "dict"
    if callable(v):
        return "callable"
    return None


ColumnSpec = Annotated[
    Annotated[SnakeCaseName, Tag("str")] | Annotated[ColumnDictSpec, Tag("dict")] | Annotated[Callable[[Any], Any], Tag("callable")],
    Discriminator(_column_spec_kind),
]


def _validate_columns(columns: dict[str, Any]) -> dict[str, Any]:
    """Shared model_validator body for any model that has a `columns` dict.

    Enforces:
      - source name for callable specs must be snake_case (preserved as-is)
      - final column names don't collide
    """
    seen_final: set[str] = set()
    for src, spec in columns.items():
        if callable(spec) and not isinstance(spec, ColumnDictSpec):
            if not _NAME_RE.match(src):
                raise ValueError(
                    f"columns[{src!r}]: callable preserves source name, "
                    f"which must match {NAME_PATTERN}"
                )
            final = src
        elif isinstance(spec, ColumnDictSpec):
            final = spec.name
        elif isinstance(spec, str):
            final = spec
        else:
            continue
        if final in seen_final:
            raise ValueError(
                f"columns[{src!r}]: final column name {final!r} collides with another column"
            )
        seen_final.add(final)
    return columns


class _DefinitionBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: SnakeCaseName
    path: str = Field(min_length=1)


class CsvDefinition(_DefinitionBase):
    kind: Literal["csv"]
    table: SnakeCaseName
    columns: dict[str, ColumnSpec] = Field(min_length=1)
    encoding: str = "utf-8"
    delimiter: str = ","
    header_row: int = 0

    @model_validator(mode="after")
    def _check_columns(self) -> CsvDefinition:
        _validate_columns(self.columns)
        return self

    @property
    def tables(self) -> list[str]:
        return [self.table]


class XlsxPerTabSheet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table: SnakeCaseName
    columns: dict[str, ColumnSpec] = Field(min_length=1)
    header_row: int = 0

    @model_validator(mode="after")
    def _check_columns(self) -> XlsxPerTabSheet:
        _validate_columns(self.columns)
        return self


class XlsxPerTabDefinition(_DefinitionBase):
    kind: Literal["xlsx"]
    mode: Literal["per_tab"] = "per_tab"
    sheets: dict[str, XlsxPerTabSheet] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_table_names(self) -> XlsxPerTabDefinition:
        seen: set[str] = set()
        for tab, cfg in self.sheets.items():
            if cfg.table in seen:
                raise ValueError(
                    f"sheets[{tab!r}].table {cfg.table!r} duplicates another sheet"
                )
            seen.add(cfg.table)
        return self

    @property
    def tables(self) -> list[str]:
        return [s.table for s in self.sheets.values()]


class XlsxConcatDefinition(_DefinitionBase):
    kind: Literal["xlsx"]
    mode: Literal["concat"]
    table: SnakeCaseName
    sheets: list[str] = Field(min_length=1)
    columns: dict[str, ColumnSpec] = Field(min_length=1)
    source_tab_column: SnakeCaseName = "source_tab"
    header_row: int = 0

    @model_validator(mode="after")
    def _sheet_names_nonempty(self) -> XlsxConcatDefinition:
        if not all(isinstance(s, str) and s for s in self.sheets):
            raise ValueError("`sheets` must contain only non-empty strings")
        _validate_columns(self.columns)
        return self

    @property
    def tables(self) -> list[str]:
        return [self.table]


Definition = CsvDefinition | XlsxPerTabDefinition | XlsxConcatDefinition


@dataclass(frozen=True)
class ValidationError:
    source_path: Path | None
    key: str | None
    message: str

    def __str__(self) -> str:
        loc = self.source_path.name if self.source_path else "<config>"
        tag = f"{loc}:{self.key}" if self.key else loc
        return f"[{tag}] {self.message}"


@dataclass(frozen=True)
class ValidatedDefinition:
    source_path: Path
    definition: Definition

    @property
    def key(self) -> str:
        return self.definition.key

    @property
    def tables(self) -> list[str]:
        return self.definition.tables


def validate_all(
    loaded: list[LoadedDefinition], active: list[str]
) -> tuple[list[ValidatedDefinition], list[ValidationError]]:
    """Validate every loaded definition; report cross-def collisions."""
    valid: list[ValidatedDefinition] = []
    errors: list[ValidationError] = []

    for d in loaded:
        result = _parse_one(d.source_path, d.raw)
        if isinstance(result, list):
            errors.extend(result)
        else:
            valid.append(ValidatedDefinition(source_path=d.source_path, definition=result))

    errors.extend(_cross_definition_checks(valid, active))
    return valid, errors


def _parse_one(
    source_path: Path, raw: dict[str, Any]
) -> Definition | list[ValidationError]:
    raw_key = raw.get("key")
    key = raw_key if isinstance(raw_key, str) else None
    kind = raw.get("kind")

    try:
        if kind == "csv":
            return CsvDefinition.model_validate(raw)
        if kind == "xlsx":
            mode = raw.get("mode", "per_tab")
            if mode == "per_tab":
                return XlsxPerTabDefinition.model_validate(raw)
            if mode == "concat":
                return XlsxConcatDefinition.model_validate(raw)
            return [
                ValidationError(
                    source_path,
                    key,
                    f"`mode` must be one of ['concat', 'per_tab']; got {mode!r}",
                )
            ]
        return [
            ValidationError(
                source_path, key, f"`kind` must be one of ['csv', 'xlsx']; got {kind!r}"
            )
        ]
    except PydanticValidationError as exc:
        return _convert_pydantic_errors(exc, source_path, key)


def _convert_pydantic_errors(
    exc: PydanticValidationError, source_path: Path, key: str | None
) -> list[ValidationError]:
    out: list[ValidationError] = []
    for err in exc.errors():
        loc_parts = [str(p) for p in err["loc"] if p != "function-after"]
        loc = ".".join(loc_parts)
        # Pydantic prefixes custom ValueError messages with "Value error, ".
        msg = err["msg"].removeprefix("Value error, ")
        out.append(ValidationError(source_path, key, f"{loc}: {msg}" if loc else msg))
    return out


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
