"""Loads the user-facing config.py from the repo root (cwd)."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    db_path: Path
    definitions_dir: Path
    active: list[str]


def _import_config_module(config_path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("mesa_user_config", config_path)
    if spec is None or spec.loader is None:
        raise ConfigError(f"could not import config from {config_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_config(start: Path | None = None) -> Config:
    """Find and import config.py, walking up from `start` (default cwd)."""
    here = (start or Path.cwd()).resolve()
    for candidate in [here, *here.parents]:
        cfg_path = candidate / "config.py"
        if cfg_path.is_file():
            return _build_config(cfg_path)
    raise ConfigError(f"config.py not found in {here} or any parent directory")


def _build_config(config_path: Path) -> Config:
    module = _import_config_module(config_path)

    missing = [
        name for name in ("DB_PATH", "DEFINITIONS_DIR", "ACTIVE") if not hasattr(module, name)
    ]
    if missing:
        raise ConfigError(f"{config_path} is missing required attributes: {', '.join(missing)}")

    db_path = Path(module.DB_PATH)
    definitions_dir = Path(module.DEFINITIONS_DIR)
    active = list(module.ACTIVE)

    if not all(isinstance(k, str) for k in active):
        raise ConfigError(f"{config_path}: ACTIVE must be a list of strings")

    return Config(db_path=db_path, definitions_dir=definitions_dir, active=active)
