"""End-to-end CLI tests: build a tmp project on disk, run mesa, assert."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import sqlite_utils


def _project(
    tmp_path: Path, *, active: list[str], extra_files: dict[str, str] | None = None
) -> Path:
    """Build a config.py + definitions/ + db/ tree in tmp_path."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "definitions").mkdir()
    (tmp_path / "db").mkdir()
    (tmp_path / "config.py").write_text(
        "from pathlib import Path\n"
        "REPO_ROOT = Path(__file__).resolve().parent\n"
        "DB_PATH = REPO_ROOT / 'db' / 'mesa.sqlite'\n"
        "DEFINITIONS_DIR = REPO_ROOT / 'definitions'\n"
        f"ACTIVE = {active!r}\n"
    )
    for name, body in (extra_files or {}).items():
        (tmp_path / name).write_text(body)
    return tmp_path


def _run_mesa(cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    repo = Path(__file__).resolve().parent.parent
    env["PYTHONPATH"] = str(repo) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "mesa"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )


def test_clean_run_csv_produces_db(csv_file: Path, tmp_path: Path) -> None:
    proj = _project(
        tmp_path / "proj",
        active=["contacts"],
        extra_files={
            "definitions/contacts.py": (
                f"definition = {{\n"
                f"    'key': 'contacts',\n"
                f"    'kind': 'csv',\n"
                f"    'path': r'{csv_file}',\n"
                f"    'table': 'contacts',\n"
                f"    'columns': {{'Email': 'email'}},\n"
                f"}}\n"
            ),
        },
    )
    result = _run_mesa(proj)
    assert result.returncode == 0, result.stdout + result.stderr
    db = sqlite_utils.Database(proj / "db" / "mesa.sqlite")
    assert "contacts" in db.table_names()
    assert db["contacts"].count == 2


def test_broken_definition_skipped_others_continue(csv_file: Path, tmp_path: Path) -> None:
    proj = _project(
        tmp_path / "proj",
        active=["contacts"],
        extra_files={
            "definitions/broken.py": "raise RuntimeError('boom')\n",
            "definitions/contacts.py": (
                f"definition = {{\n"
                f"    'key': 'contacts',\n"
                f"    'kind': 'csv',\n"
                f"    'path': r'{csv_file}',\n"
                f"    'table': 'contacts',\n"
                f"    'columns': {{'Email': 'email'}},\n"
                f"}}\n"
            ),
        },
    )
    result = _run_mesa(proj)
    assert result.returncode == 1, result.stdout
    assert "[load] broken.py" in result.stdout
    db = sqlite_utils.Database(proj / "db" / "mesa.sqlite")
    assert db["contacts"].count == 2


def test_missing_path_aborts_with_exit_2(tmp_path: Path) -> None:
    proj = _project(
        tmp_path / "proj",
        active=["contacts"],
        extra_files={
            "definitions/contacts.py": (
                "definition = {\n"
                "    'key': 'contacts',\n"
                "    'kind': 'csv',\n"
                "    'path': '/no/such/file.csv',\n"
                "    'table': 'contacts',\n"
                "    'columns': {'Email': 'email'},\n"
                "}\n"
            ),
        },
    )
    result = _run_mesa(proj)
    assert result.returncode == 2, result.stdout
    assert "source files not found" in result.stdout


def test_inactive_definition_table_persists_across_runs(csv_file: Path, tmp_path: Path) -> None:
    proj_dir = tmp_path / "proj"
    proj = _project(
        proj_dir,
        active=["contacts"],
        extra_files={
            "definitions/contacts.py": (
                f"definition = {{\n"
                f"    'key': 'contacts',\n"
                f"    'kind': 'csv',\n"
                f"    'path': r'{csv_file}',\n"
                f"    'table': 'contacts',\n"
                f"    'columns': {{'Email': 'email'}},\n"
                f"}}\n"
            ),
        },
    )
    r1 = _run_mesa(proj)
    assert r1.returncode == 0, r1.stdout

    (proj / "config.py").write_text(
        "from pathlib import Path\n"
        "REPO_ROOT = Path(__file__).resolve().parent\n"
        "DB_PATH = REPO_ROOT / 'db' / 'mesa.sqlite'\n"
        "DEFINITIONS_DIR = REPO_ROOT / 'definitions'\n"
        "ACTIVE = []\n"
    )
    r2 = _run_mesa(proj)
    assert r2.returncode == 0, r2.stdout

    db = sqlite_utils.Database(proj / "db" / "mesa.sqlite")
    assert "contacts" in db.table_names()
    assert db["contacts"].count == 2


def test_active_key_missing_returns_1(tmp_path: Path) -> None:
    proj = _project(tmp_path / "proj", active=["ghost"])
    result = _run_mesa(proj)
    assert result.returncode == 1, result.stdout
    assert "ghost" in result.stdout
