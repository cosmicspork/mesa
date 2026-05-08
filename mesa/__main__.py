"""Mesa CLI entry point: load config, discover, validate, ingest."""

from __future__ import annotations

import sys

from mesa import __version__, ingest, loader, validator
from mesa.config import Config, ConfigError, load_config


def main() -> int:
    print(f"mesa {__version__}")
    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 2

    print(f"  db:          {cfg.db_path}")
    print(f"  definitions: {cfg.definitions_dir}")
    print(f"  active:      {cfg.active or '(none)'}")
    print()

    if not cfg.definitions_dir.is_dir():
        print(f"ERROR: definitions directory not found: {cfg.definitions_dir}")
        return 2

    return _run(cfg)


def _run(cfg: Config) -> int:
    loaded, load_errors = loader.discover(cfg.definitions_dir)
    for le in load_errors:
        print(f"[load] {le.source_path.name}: {le.message}")

    valid, validation_errors = validator.validate_all(loaded, cfg.active)
    for ve in validation_errors:
        print(f"[validate] {ve}")

    active_defs = [v for v in valid if v.key in cfg.active]
    print(f"\nFound {len(loaded)} definition(s); {len(valid)} valid; {len(active_defs)} active.")

    if not active_defs:
        print("Nothing to ingest.")
        return 1 if (load_errors or validation_errors) else 0

    missing = ingest.precheck_paths(active_defs)
    if missing:
        print("\nERROR: source files not found, aborting before ingest:")
        for key, path in missing:
            print(f"  [{key}] {path}")
        return 2

    print()
    results = ingest.run(active_defs, cfg.db_path)
    _print_summary(results)

    any_error = bool(load_errors or validation_errors) or any(r.status == "error" for r in results)
    return 1 if any_error else 0


def _print_summary(results: list[ingest.IngestResult]) -> None:
    print("Ingest results:")
    for r in results:
        if r.status == "ok":
            tables = ", ".join(r.tables)
            print(f"  ok    [{r.key}] {r.rows_written} rows -> {tables}")
        else:
            print(f"  ERROR [{r.key}] {r.message}")


if __name__ == "__main__":
    sys.exit(main())
