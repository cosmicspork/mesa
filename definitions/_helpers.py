"""Shared helper functions for definition files.

The leading underscore tells Mesa's loader to skip this file during discovery.
"""

from __future__ import annotations


def parse_money(v: object) -> float | None:
    if v is None or v == "":
        return None
    return float(str(v).replace("$", "").replace(",", "").strip())


def digits_only(v: object) -> str | None:
    if v is None or v == "":
        return None
    digits = "".join(c for c in str(v) if c.isdigit())
    return digits or None
