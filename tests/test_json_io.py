"""Boundary and filesystem failure cases, independent of providers."""

import math

import pytest

from json_io import atomic_path, dumps_json, loads_json, write_json


@pytest.mark.parametrize(
    "text",
    [
        '{"node": "A", "node": "B"}',
        '{"routing": {"enabled": true, "enabled": false}}',
        '{"metric": NaN}',
        '{"metric": Infinity}',
        '{"metric": -Infinity}',
        '{"metric": 1e999}',
    ],
)
def test_ambiguous_or_nonstandard_json_is_rejected(text):
    with pytest.raises(ValueError):
        loads_json(text)


def test_nonfinite_output_does_not_destroy_existing_file(tmp_path):
    destination = tmp_path / "plan.json"
    destination.write_text('{"previous": true}\n', encoding="utf-8")
    with pytest.raises(ValueError):
        write_json(destination, {"invalid": math.nan})
    assert loads_json(destination.read_text()) == {"previous": True}
    assert list(tmp_path.iterdir()) == [destination]


def test_partial_write_is_removed_and_existing_output_is_preserved(tmp_path):
    destination = tmp_path / "plan.json"
    destination.write_text("original", encoding="utf-8")
    with pytest.raises(OSError, match="disk failure"):
        with atomic_path(destination) as temporary:
            temporary.write_text("partial", encoding="utf-8")
            raise OSError("disk failure")
    assert destination.read_text() == "original"
    assert list(tmp_path.iterdir()) == [destination]


def test_json_roundtrip_preserves_custom_nested_configuration(tmp_path):
    value = {"réseau": {"enabled": False, "routes": [], "custom": [None, 0, "é"]}}
    destination = tmp_path / "nested" / "plan.json"
    write_json(destination, value, indent=2)
    assert loads_json(destination.read_text(encoding="utf-8")) == value
    assert loads_json(dumps_json(value)) == value
