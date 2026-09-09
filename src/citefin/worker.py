"""Redis-backed automatic analysis worker entry point."""

from typing import cast

from redis import Redis

from citefin.config import get_settings
from citefin.services.execution import process_execution_by_id


def run_once(timeout: int = 30) -> bool:
    """Consume at most one queued execution, making worker behavior testable."""

    settings = get_settings()
    if not settings.redis_url:
        raise RuntimeError("CITEFIN_REDIS_URL is required for the analysis worker")
    queue = Redis.from_url(settings.redis_url)
    item = cast(
        list[bytes] | None,
        queue.blpop([settings.analysis_queue_name], timeout=timeout),
    )
    if item is None:
        return False
    process_execution_by_id(settings, item[1].decode())
    return True


def main() -> None:
    while True:  # pragma: no cover - process lifecycle wrapper
        run_once()


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
