"""Focused queue and review boundary tests."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from citefin.config import Settings
from citefin.db.base import Base
from citefin.db.models import (
    AnalysisRun,
    ReviewItem,
    SourceDocument,
    StatementIdentification,
    StoredObject,
)
from citefin.db.session import build_engine
from citefin.services import execution as execution_service
from citefin.services.execution import (
    ExecutionError,
    enqueue_execution,
    list_review_items,
    process_execution,
    resolve_review_item,
)


def _run(run_id: str = "run_execution") -> AnalysisRun:
    now = datetime.now(UTC)
    return AnalysisRun(
        run_id=run_id,
        idempotency_key=run_id,
        user_id="owner",
        company_name="合成公司",
        security_code="600001",
        report_period_end=date(2025, 12, 31),
        as_of=now,
        analysis_focus=["comprehensive"],
        status="created",
        current_node="create_run",
        model_profile="deterministic",
        workflow_version="1",
        created_at=now,
        updated_at=now,
        completed_at=None,
        failure_code=None,
    )


def test_queue_idempotency_and_review_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings = Settings(_env_file=None, object_storage_root=tmp_path / "objects")
    with Session(engine, expire_on_commit=False) as session:
        session.add(_run())
        session.commit()
        with pytest.raises(ExecutionError, match="队列尚未配置"):
            enqueue_execution(
                session,
                Settings(_env_file=None, analysis_queue_mode="redis"),
                "run_execution",
                "owner",
            )
        with pytest.raises(ExecutionError, match="请先上传"):
            enqueue_execution(session, settings, "run_execution", "owner")
        with pytest.raises(ExecutionError, match="不存在"):
            enqueue_execution(session, settings, "missing", "owner")

        now = datetime.now(UTC)
        stored = StoredObject(
            sha256="a" * 64,
            storage_uri="sha256/aa/source.pdf",
            media_type="application/pdf",
            byte_size=100,
            created_at=now,
        )
        source = SourceDocument(
            source_id="source_execution",
            run_id="run_execution",
            document_type="annual_report",
            file_name="source.pdf",
            media_type="application/pdf",
            sha256=stored.sha256,
            storage_uri=stored.storage_uri,
            company_name="合成公司",
            security_code="600001",
            period_end=date(2025, 12, 31),
            published_at=None,
            language="zh-CN",
            page_count=1,
            text_extractable=True,
            parser_version="ingestion-v1",
            ingested_at=now,
        )
        session.add_all([stored, source])
        session.commit()
        queued, replay = enqueue_execution(session, settings, "run_execution", "owner")
        assert queued.status == "queued" and replay is False
        assert enqueue_execution(session, settings, "run_execution", "owner")[1] is True
        process_execution(session, settings, queued.execution_id)
        assert queued.status == "failed"
        assert queued.error_code == "DocumentParsingError"

        item = ReviewItem(
            item_id="review_execution",
            run_id="run_execution",
            item_type="financial_facts",
            checkpoint_node="field_normalization",
            status="pending",
            title="确认事实",
            prompt="请确认",
            candidates=[],
            resolution=None,
            created_at=now,
            resolved_at=None,
        )
        session.add(item)
        session.commit()
        assert len(list_review_items(session, "run_execution", "owner")) == 1
        with pytest.raises(ExecutionError, match="不存在"):
            list_review_items(session, "run_execution", "intruder")
        with pytest.raises(ExecutionError, match="有效候选"):
            resolve_review_item(session, "run_execution", item.item_id, "owner", "select", 0)
        resolved, resume = resolve_review_item(
            session, "run_execution", item.item_id, "owner", "reject", None
        )
        assert resolved.status == "rejected"
        assert resume is None
        replayed, replay_resume = resolve_review_item(
            session, "run_execution", item.item_id, "owner", "reject", None
        )
        assert replayed is resolved and replay_resume is None
        with pytest.raises(ExecutionError, match="待确认项不存在"):
            resolve_review_item(session, "run_execution", "missing", "owner", "reject", None)

        statement = StatementIdentification(
            statement_id="statement_execution",
            source_id=source.source_id,
            statement_type="balance_sheet",
            status="ambiguous",
            title=None,
            scope="unknown",
            period_end=None,
            page_number=None,
            table_id=None,
            locator=None,
            candidate_count=1,
            candidates=[],
            reason={"code": "multiple_candidates"},
            algorithm_version="statement-identification-v1",
            created_at=now,
            updated_at=now,
        )
        selection = ReviewItem(
            item_id="review_statement",
            run_id="run_execution",
            item_type="statement:balance_sheet",
            checkpoint_node="statement_extract",
            status="pending",
            title="确认报表",
            prompt="请选择",
            candidates=[
                {
                    "title": "合并资产负债表",
                    "page_number": 12,
                    "table_id": "table_12",
                    "locator": {"page": 12},
                    "period_end": "2025-12-31",
                }
            ],
            resolution=None,
            created_at=now,
            resolved_at=None,
        )
        session.add_all([statement, selection])
        session.commit()
        selected, resume_id = resolve_review_item(
            session, "run_execution", selection.item_id, "owner", "select", 0
        )
        assert selected.status == "resolved"
        assert resume_id == queued.execution_id
        assert statement.status == "located"
        assert statement.page_number == 12
        assert queued.status == "queued"

        run_two = _run("run_redis")
        source_two = SourceDocument(
            source_id="source_redis",
            run_id=run_two.run_id,
            document_type=source.document_type,
            file_name=source.file_name,
            media_type=source.media_type,
            sha256=stored.sha256,
            storage_uri=stored.storage_uri,
            company_name=source.company_name,
            security_code=source.security_code,
            period_end=source.period_end,
            published_at=None,
            language=source.language,
            page_count=source.page_count,
            text_extractable=True,
            parser_version=source.parser_version,
            ingested_at=now,
        )
        session.add_all([run_two, source_two])
        session.commit()
        pushed: list[tuple[str, str]] = []

        class FakeRedis:
            def rpush(self, queue: str, item_id: str) -> None:
                pushed.append((queue, item_id))

        monkeypatch.setattr(
            execution_service.Redis,
            "from_url",
            lambda *_args, **_kwargs: FakeRedis(),
        )
        redis_settings = Settings(
            _env_file=None,
            redis_url="redis://example.invalid/0",
            analysis_queue_mode="redis",
            analysis_queue_name="test-analysis",
        )
        redis_execution, redis_replay = enqueue_execution(
            session, redis_settings, run_two.run_id, "owner"
        )
        assert redis_replay is False
        assert pushed == [("test-analysis", redis_execution.execution_id)]
        assert enqueue_execution(session, redis_settings, run_two.run_id, "owner")[1] is True
        assert len(pushed) == 2
    engine.dispose()
