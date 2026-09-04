"""Identifier contract tests."""

from uuid import UUID

from citefin.ids import new_prefixed_id


def test_prefixed_id_contains_uuid7() -> None:
    value = new_prefixed_id("run")

    prefix, raw_uuid = value.split("_", maxsplit=1)
    assert prefix == "run"
    assert UUID(raw_uuid).version == 7
