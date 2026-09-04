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

    def put_pdf(self, content: bytes, sha256: str) -> StoredObjectResult:
        """Create a PDF exactly once or verify and reuse its existing object."""

        directory = self.root / sha256[:2]
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{sha256}.pdf"
        storage_uri = f"local://sha256/{sha256[:2]}/{sha256}.pdf"
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
