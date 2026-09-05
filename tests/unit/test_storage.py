"""Integrity tests for immutable PDF reads and derived JSON writes."""

import hashlib
from pathlib import Path

import pytest

from citefin.storage import LocalObjectStore, StorageIntegrityError


def test_read_pdf_requires_canonical_uri_and_matching_content(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    content = b"%PDF-1.4\nimmutable"
    digest = hashlib.sha256(content).hexdigest()
    stored = store.put_pdf(content, digest)

    assert store.read_pdf(digest, stored.storage_uri) == content
    with pytest.raises(StorageIntegrityError, match="URI"):
        store.read_pdf(digest, "local://sha256/not-canonical.pdf")

    path = tmp_path / digest[:2] / f"{digest}.pdf"
    path.write_bytes(b"tampered")
    with pytest.raises(StorageIntegrityError, match="verification"):
        store.read_pdf(digest, stored.storage_uri)


def test_json_artifact_is_reused_only_when_content_matches(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    content = b'{"schema_version":"bbox-index-v1"}'
    digest = hashlib.sha256(content).hexdigest()

    first = store.put_json(content, digest)
    replay = store.put_json(content, digest)

    assert first.created is True
    assert replay.created is False
    path = tmp_path / digest[:2] / f"{digest}.json"
    path.write_bytes(b"different")
    with pytest.raises(StorageIntegrityError, match="does not match"):
        store.put_json(content, digest)
