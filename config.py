from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

DB_PATH = REPO_ROOT / "db" / "mesa.sqlite"
DEFINITIONS_DIR = REPO_ROOT / "definitions"

ACTIVE: list[str] = []
