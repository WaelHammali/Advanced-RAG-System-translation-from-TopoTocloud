"""Strict JSON boundaries and atomic file replacement; no architecture validation."""

from __future__ import annotations

import json
import math
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-finite number is not valid JSON: {value}")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("JSON number exceeds the supported finite floating-point range.")
    return number


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def loads_json(text: str) -> Any:
    """Reject ambiguous duplicate keys and nonstandard NaN/Infinity constants."""
    return json.loads(
        text,
        parse_constant=_reject_constant,
        parse_float=_finite_float,
        object_pairs_hook=_unique_object,
    )


def dumps_json(value: Any, *, indent: int | None = None, sort_keys: bool = False) -> str:
    """Serialize JSON without silently emitting Python's nonstandard NaN values."""
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, indent=indent, sort_keys=sort_keys
    )


@contextmanager
def atomic_path(destination: Path) -> Iterator[Path]:
    """Replace a destination only after writing succeeds; clean up on failure."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent, prefix=".net2cloud-", delete=False
    ) as file:
        temporary = Path(file.name)
    try:
        yield temporary
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(destination: Path, value: Any, *, indent: int | None = None) -> None:
    """Leave an existing file intact if serialization or writing fails."""
    serialized = dumps_json(value, indent=indent) + "\n"
    with atomic_path(destination) as temporary:
        temporary.write_text(serialized, encoding="utf-8")
