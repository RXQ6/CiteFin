"""Redis worker consumption tests without a network dependency."""

import pytest

from citefin import worker
from citefin.config import Settings


class FakeQueue:
    def __init__(self, item: list[bytes] | None) -> None:
        self.item = item

    def blpop(self, keys: list[str], timeout: int) -> list[bytes] | None:
        assert keys == ["test-queue"]
        assert timeout == 1
        return self.item


def test_worker_consumes_one_item_or_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        _env_file=None,
        redis_url="redis://example.invalid/0",
        analysis_queue_name="test-queue",
    )
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    consumed: list[str] = []
    monkeypatch.setattr(
        worker, "process_execution_by_id", lambda _settings, item: consumed.append(item)
    )
    queues = iter([FakeQueue([b"test-queue", b"execution_1"]), FakeQueue(None)])
    monkeypatch.setattr(
        worker.Redis,
        "from_url",
        lambda *_args, **_kwargs: next(queues),
    )

    assert worker.run_once(timeout=1) is True
    assert consumed == ["execution_1"]
    assert worker.run_once(timeout=1) is False


def test_worker_requires_redis_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker, "get_settings", lambda: Settings(_env_file=None))
    with pytest.raises(RuntimeError, match="CITEFIN_REDIS_URL"):
        worker.run_once(timeout=1)
