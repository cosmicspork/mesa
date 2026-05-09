from pathlib import Path
from typing import Any

from mesa.loader import LoadedDefinition
from mesa.validator import validate_all


def _ld(name: str, raw: dict[str, Any]) -> LoadedDefinition:
    return LoadedDefinition(source_path=Path(f"definitions/{name}.py"), raw=raw)


def _csv(key: str = "things", **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "key": key,
        "kind": "csv",
        "path": "x.csv",
        "table": key,
        "columns": {"A": "a"},
    }
    base.update(overrides)
    return base


def _xlsx_per_tab(key: str = "sales", **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "key": key,
        "kind": "xlsx",
        "path": "x.xlsx",
        "sheets": {"Jan": {"table": f"{key}_jan", "columns": {"A": "a"}}},
    }
    base.update(overrides)
    return base


def _xlsx_concat(key: str = "sales_all", **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "key": key,
        "kind": "xlsx",
        "path": "x.xlsx",
        "mode": "concat",
        "table": key,
        "sheets": ["Jan", "Feb"],
        "columns": {"A": "a"},
    }
    base.update(overrides)
    return base


def test_valid_csv() -> None:
    valid, errors = validate_all([_ld("things", _csv())], active=["things"])
    assert errors == []
    assert [v.key for v in valid] == ["things"]
    assert valid[0].tables == ["things"]


def test_valid_xlsx_per_tab() -> None:
    valid, errors = validate_all([_ld("sales", _xlsx_per_tab())], active=["sales"])
    assert errors == []
    assert valid[0].tables == ["sales_jan"]


def test_valid_xlsx_concat() -> None:
    valid, errors = validate_all([_ld("sales", _xlsx_concat())], active=["sales_all"])
    assert errors == []
    assert valid[0].tables == ["sales_all"]


def test_polymorphic_columns_all_three_forms() -> None:
    raw = _csv(
        columns={
            "Plain": "plain",
            "Typed": {"name": "typed", "type": "float"},
            "already_clean": lambda v: v,
            "Both": {"name": "both", "type": "text", "transform": lambda v: v},
        }
    )
    _, errors = validate_all([_ld("things", raw)], active=["things"])
    assert errors == []


def test_invalid_key_regex() -> None:
    _, errors = validate_all([_ld("bad", _csv(key="Bad-Key"))], active=[])
    assert any("key" in str(e) and "should match pattern" in str(e) for e in errors)


def test_kebab_case_key_rejected() -> None:
    _, errors = validate_all([_ld("kebab", _csv(key="monthly-invoices"))], active=[])
    assert any("key" in str(e) and "should match pattern" in str(e) for e in errors)


def test_csv_must_not_have_sheets() -> None:
    raw = _csv(sheets={"Jan": {}})
    _, errors = validate_all([_ld("things", raw)], active=["things"])
    assert any("sheets" in str(e) and "Extra inputs are not permitted" in str(e) for e in errors)


def test_xlsx_per_tab_with_top_level_table_rejected() -> None:
    raw = _xlsx_per_tab(table="x")
    _, errors = validate_all([_ld("sales", raw)], active=["sales"])
    assert any("table" in str(e) and "Extra inputs are not permitted" in str(e) for e in errors)


def test_xlsx_concat_requires_sheets_list() -> None:
    raw = _xlsx_concat(sheets={"Jan": {}})
    _, errors = validate_all([_ld("sales", raw)], active=["sales_all"])
    assert any("sheets" in str(e) and "valid list" in str(e) for e in errors)


def test_dict_spec_missing_name() -> None:
    raw = _csv(columns={"Amount": {"type": "float"}})
    _, errors = validate_all([_ld("things", raw)], active=["things"])
    assert any("name" in str(e) and "Field required" in str(e) for e in errors)


def test_dict_spec_unknown_key_rejected() -> None:
    raw = _csv(columns={"Amount": {"name": "amount", "weird": True}})
    _, errors = validate_all([_ld("things", raw)], active=["things"])
    assert any("weird" in str(e) and "Extra inputs are not permitted" in str(e) for e in errors)


def test_dict_spec_bad_type_rejected() -> None:
    raw = _csv(columns={"Amount": {"name": "amount", "type": "bigint"}})
    _, errors = validate_all([_ld("things", raw)], active=["things"])
    assert any("type" in str(e) and "should be" in str(e) and "'int'" in str(e) for e in errors)


def test_callable_spec_with_bad_source_name_rejected() -> None:
    raw = _csv(columns={"Bad Name": lambda v: v})
    _, errors = validate_all([_ld("things", raw)], active=["things"])
    assert any("callable preserves source name" in str(e) for e in errors)


def test_final_column_name_collision() -> None:
    raw = _csv(columns={"A": "x", "B": "x"})
    _, errors = validate_all([_ld("things", raw)], active=["things"])
    assert any("collides" in str(e) for e in errors)


def test_duplicate_keys_across_files() -> None:
    a = _ld("a", _csv(key="things"))
    b = _ld("b", _csv(key="things", table="other"))
    _, errors = validate_all([a, b], active=["things"])
    assert any("duplicate key" in str(e) for e in errors)


def test_table_collision_across_active_definitions() -> None:
    a = _ld("a", _csv(key="alpha", table="shared"))
    b = _ld("b", _csv(key="beta", table="shared"))
    _, errors = validate_all([a, b], active=["alpha", "beta"])
    assert any("also produced by" in str(e) for e in errors)


def test_table_collision_only_among_active() -> None:
    """Dormant collision should NOT error: inactive defs are ignored."""
    a = _ld("a", _csv(key="alpha", table="shared"))
    b = _ld("b", _csv(key="beta", table="shared"))
    _, errors = validate_all([a, b], active=["alpha"])
    assert not any("also produced by" in str(e) for e in errors)


def test_active_key_missing_reported() -> None:
    _, errors = validate_all([_ld("a", _csv(key="alpha"))], active=["alpha", "ghost"])
    assert any("ghost" in str(e) and "ACTIVE key" in str(e) for e in errors)


def test_active_key_with_failed_validation_reported_as_missing() -> None:
    _, errors = validate_all([_ld("bad", _csv(key="Bad-Name"))], active=["Bad-Name"])
    msgs = [str(e) for e in errors]
    assert any("key" in m and "should match pattern" in m for m in msgs)
    assert any("ACTIVE key 'Bad-Name'" in m for m in msgs)
