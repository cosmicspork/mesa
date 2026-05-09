from pathlib import Path

from mesa.loader import discover


def _write(p: Path, content: str) -> None:
    p.write_text(content)


def test_discover_returns_valid_definitions(tmp_path: Path) -> None:
    _write(
        tmp_path / "good.py",
        'definition = {"key": "good", "kind": "csv", "path": "x.csv", '
        '"table": "good", "columns": {"A": "a"}}\n',
    )
    loaded, errors = discover(tmp_path)
    assert errors == []
    assert len(loaded) == 1
    assert loaded[0].key == "good"
    assert loaded[0].source_path == tmp_path / "good.py"


def test_discover_skips_underscore_prefixed_files(tmp_path: Path) -> None:
    _write(tmp_path / "_helpers.py", "x = 1\n")
    _write(tmp_path / "good.py", 'definition = {"key": "good"}\n')
    loaded, errors = discover(tmp_path)
    assert [d.source_path.name for d in loaded] == ["good.py"]
    assert errors == []


def test_discover_isolates_broken_file(tmp_path: Path) -> None:
    _write(tmp_path / "broken.py", "raise RuntimeError('boom')\n")
    _write(tmp_path / "good.py", 'definition = {"key": "good"}\n')
    loaded, errors = discover(tmp_path)
    assert [d.key for d in loaded] == ["good"]
    assert len(errors) == 1
    assert errors[0].source_path.name == "broken.py"
    assert "RuntimeError" in errors[0].message
    assert "boom" in errors[0].traceback


def test_discover_reports_missing_definition_attr(tmp_path: Path) -> None:
    _write(tmp_path / "bare.py", "x = 1\n")
    loaded, errors = discover(tmp_path)
    assert loaded == []
    assert len(errors) == 1
    assert "missing top-level `definition`" in errors[0].message


def test_discover_reports_non_dict_definition(tmp_path: Path) -> None:
    _write(tmp_path / "wrong.py", "definition = 42\n")
    loaded, errors = discover(tmp_path)
    assert loaded == []
    assert len(errors) == 1
    assert "must be a dict" in errors[0].message


def test_discover_empty_dir(tmp_path: Path) -> None:
    loaded, errors = discover(tmp_path)
    assert loaded == []
    assert errors == []
