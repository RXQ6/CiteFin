"""Content-addressed immutable object storage adapters."""

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


class StorageIntegrityError(RuntimeError):
    """An existing content-addressed object does not match its digest."""


@dataclass(frozen=True)
class StoredObjectResult:
    """Stable address and whether this call created the physical object."""

    storage_uri: str
    created: bool


class LocalObjectStore:
    """Filesystem-backed immutable storage using SHA-256 object paths."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _put(self, content: bytes, sha256: str, suffix: str) -> StoredObjectResult:
        directory = self.root / sha256[:2]
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{sha256}.{suffix}"
        storage_uri = f"local://sha256/{sha256[:2]}/{sha256}.{suffix}"
        try:
            descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if target.stat().st_size != len(content) or self._hash_file(target) != sha256:
                raise StorageIntegrityError(
                    "Existing immutable object does not match its content address"
                ) from None
            return StoredObjectResult(storage_uri=storage_uri, created=False)

        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return StoredObjectResult(storage_uri=storage_uri, created=True)

    def put_pdf(self, content: bytes, sha256: str) -> StoredObjectResult:
        """Create a PDF exactly once or verify and reuse its existing object."""

        return self._put(content, sha256, "pdf")

    def put_json(self, content: bytes, sha256: str) -> StoredObjectResult:
        """Create one canonical JSON artifact or verify an identical existing object."""

        return self._put(content, sha256, "json")

    def read_pdf(self, sha256: str, storage_uri: str) -> bytes:
        """Read and verify a PDF from its canonical local content address."""

        expected_uri = f"local://sha256/{sha256[:2]}/{sha256}.pdf"
        if storage_uri != expected_uri:
            raise StorageIntegrityError("Stored PDF URI does not match its content address")
        path = self.root / sha256[:2] / f"{sha256}.pdf"
        try:
            content = path.read_bytes()
        except OSError as error:
            raise StorageIntegrityError("Stored PDF is unavailable") from error
        if hashlib.sha256(content).hexdigest() != sha256:
            raise StorageIntegrityError("Stored PDF failed content-address verification")
        return content
