"""Discovers and imports definition files from definitions/."""

from __future__ import annotations

import importlib.util
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LoadedDefinition:
    source_path: Path
    raw: dict[str, Any]

    @property
    def key(self) -> str:
        k = self.raw.get("key")
        return k if isinstance(k, str) else ""


@dataclass(frozen=True)
class LoadError:
    source_path: Path
    message: str
    traceback: str


def discover(definitions_dir: Path) -> tuple[list[LoadedDefinition], list[LoadError]]:
    loaded: list[LoadedDefinition] = []
    errors: list[LoadError] = []

    # Make underscore-prefixed helper modules (e.g. _helpers.py) importable by name
    # from definition files. Helpers are skipped by discovery but visible to imports.
    dir_str = str(definitions_dir.resolve())
    if dir_str not in sys.path:
        sys.path.insert(0, dir_str)

    for path in sorted(definitions_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        result = _load_one(path)
        if isinstance(result, LoadError):
            errors.append(result)
        else:
            loaded.append(result)
    return loaded, errors


def _load_one(path: Path) -> LoadedDefinition | LoadError:
    module_name = f"mesa_def_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        return LoadError(path, "could not create import spec", "")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        return LoadError(path, f"{type(e).__name__}: {e}", traceback.format_exc())

    raw = getattr(module, "definition", None)
    if raw is None:
        return LoadError(path, "module is missing top-level `definition` dict", "")
    if not isinstance(raw, dict):
        return LoadError(path, f"`definition` must be a dict, got {type(raw).__name__}", "")
    return LoadedDefinition(source_path=path, raw=raw)
