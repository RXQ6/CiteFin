"""Durable automatic execution queue with explicit human-review stops."""

from datetime import UTC, date, datetime

from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.orm import Session

from citefin.config import Settings
from citefin.db.models import (
    AnalysisExecution,
    AnalysisRun,
    AuditEvent,
    FinancialFact,
    ReviewItem,
    SourceDocument,
    StatementIdentification,
)
from citefin.db.session import get_session_factory
from citefin.ids import new_prefixed_id
from citefin.services.document_parsing import parse_annual_report
from citefin.services.statement_identification import identify_statements
from citefin.storage import LocalObjectStore


class ExecutionError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def enqueue_execution(
    session: Session, settings: Settings, run_id: str, user_id: str
) -> tuple[AnalysisExecution, bool]:
    run = session.scalar(
        select(AnalysisRun).where(AnalysisRun.run_id == run_id, AnalysisRun.user_id == user_id)
    )
    if run is None:
        raise ExecutionError("analysis_run_not_found", "分析任务不存在。", 404)
    if settings.analysis_queue_mode == "redis" and not settings.redis_url:
        raise ExecutionError("redis_not_configured", "自动分析队列尚未配置。", 503)
    source = session.scalar(select(SourceDocument).where(SourceDocument.run_id == run_id))
    if source is None:
        raise ExecutionError("source_document_required", "请先上传年度报告。", 409)
    existing = session.scalar(select(AnalysisExecution).where(AnalysisExecution.run_id == run_id))
    if existing:
        if settings.analysis_queue_mode == "redis" and existing.status == "queued":
            assert settings.redis_url is not None
            Redis.from_url(settings.redis_url).rpush(
                settings.analysis_queue_name, existing.execution_id
            )
        return existing, True
    now = datetime.now(UTC)
    execution = AnalysisExecution(
        execution_id=new_prefixed_id("execution"),
        run_id=run_id,
        status="queued",
        current_node="document_parse",
        attempt_count=0,
        error_code=None,
        created_at=now,
        updated_at=now,
    )
    run.status = "queued"
    run.current_node = "document_parse"
    run.updated_at = now
    session.add_all(
        [
            execution,
            AuditEvent(
                event_id=new_prefixed_id("event"),
                run_id=run_id,
                trace_id=new_prefixed_id("trace"),
                node="execute",
                event_type="analysis_enqueued",
                status="queued",
                payload={"execution_id": execution.execution_id},
                created_at=now,
            ),
        ]
    )
    session.commit()
    if settings.analysis_queue_mode == "redis":
        assert settings.redis_url is not None
        try:
            Redis.from_url(settings.redis_url).rpush(
                settings.analysis_queue_name, execution.execution_id
            )
        except RedisError as error:
            raise ExecutionError("queue_unavailable", "自动分析队列暂不可用。", 503) from error
    return execution, False


def _stop_for_review(
    session: Session,
    run: AnalysisRun,
    execution: AnalysisExecution,
    statements: list[StatementIdentification],
) -> None:
    now = datetime.now(UTC)
    for statement in statements:
        if statement.status == "located":
            continue
        item_type = f"statement:{statement.statement_type}"
        exists = session.scalar(
            select(ReviewItem).where(
                ReviewItem.run_id == run.run_id, ReviewItem.item_type == item_type
            )
        )
        if not exists:
            session.add(
                ReviewItem(
                    item_id=new_prefixed_id("review"),
                    run_id=run.run_id,
                    item_type=item_type,
                    checkpoint_node="statement_extract",
                    status="pending",
                    title="确认财务报表位置",
                    prompt="系统无法唯一确认该合并财务报表，请选择正确候选或拒绝。",
                    candidates=statement.candidates,
                    resolution=None,
                    created_at=now,
                    resolved_at=None,
                )
            )
    execution.status = run.status = "awaiting_review"
    execution.current_node = run.current_node = "statement_extract"
    execution.updated_at = run.updated_at = now
    session.add(
        AuditEvent(
            event_id=new_prefixed_id("event"),
            run_id=run.run_id,
            trace_id=new_prefixed_id("trace"),
            node="statement_extract",
            event_type="review_required",
            status="awaiting_review",
            payload={"execution_id": execution.execution_id},
            created_at=now,
        )
    )
    session.commit()


def _add_fact_review(session: Session, run_id: str) -> None:
    exists = session.scalar(
        select(ReviewItem).where(
            ReviewItem.run_id == run_id, ReviewItem.item_type == "financial_facts"
        )
    )
    if not exists:
        session.add(
            ReviewItem(
                item_id=new_prefixed_id("review"),
                run_id=run_id,
                item_type="financial_facts",
                checkpoint_node="field_normalization",
                status="pending",
                title="确认抽取事实",
                prompt="未产生同时满足唯一行名、期间列、单位与合并口径的自动事实。",
                candidates=[],
                resolution=None,
                created_at=datetime.now(UTC),
                resolved_at=None,
            )
        )
        session.commit()


def process_execution(session: Session, settings: Settings, execution_id: str) -> None:
    execution = session.get(AnalysisExecution, execution_id)
    if execution is None or execution.status not in {"queued", "running"}:
        return
    run = session.get(AnalysisRun, execution.run_id)
    source = session.scalar(select(SourceDocument).where(SourceDocument.run_id == execution.run_id))
    if run is None or source is None:
        return
    now = datetime.now(UTC)
    execution.status = run.status = "running"
    execution.attempt_count += 1
    execution.updated_at = run.updated_at = now
    session.commit()
    try:
        store = LocalObjectStore(settings.object_storage_root)
        execution.current_node = run.current_node = "document_parse"
        session.commit()
        parse_annual_report(
            session,
            store,
            run_id=run.run_id,
            source_id=source.source_id,
            user_id=run.user_id,
            max_pages=settings.max_pdf_pages,
        )
        execution.current_node = run.current_node = "statement_extract"
        session.commit()
        statements, _, overall = identify_statements(
            session,
            store,
            run_id=run.run_id,
            source_id=source.source_id,
            user_id=run.user_id,
        )
        if overall != "located":
            _stop_for_review(session, run, execution, statements)
            return
        if not session.scalar(select(FinancialFact).where(FinancialFact.run_id == run.run_id)):
            _stop_for_review(session, run, execution, [])
            _add_fact_review(session, run.run_id)
            return
        execution.status = run.status = "candidate_complete"
        execution.current_node = run.current_node = "field_normalization"
        execution.updated_at = run.updated_at = datetime.now(UTC)
        session.commit()
    except Exception as error:
        session.rollback()
        execution = session.get(AnalysisExecution, execution_id)
        run = session.get(AnalysisRun, execution.run_id) if execution else None
        if execution:
            execution.status = "failed"
            execution.error_code = type(error).__name__
            execution.updated_at = datetime.now(UTC)
        if run:
            run.status = "failed"
            run.failure_code = type(error).__name__
            run.updated_at = datetime.now(UTC)
        session.commit()


def process_execution_by_id(settings: Settings, execution_id: str) -> None:
    if settings.database_url:
        with get_session_factory(settings.database_url)() as session:
            process_execution(session, settings, execution_id)


def list_review_items(session: Session, run_id: str, user_id: str) -> list[ReviewItem]:
    owned = session.scalar(
        select(AnalysisRun).where(AnalysisRun.run_id == run_id, AnalysisRun.user_id == user_id)
    )
    if not owned:
        raise ExecutionError("analysis_run_not_found", "分析任务不存在。", 404)
    return list(
        session.scalars(
            select(ReviewItem).where(ReviewItem.run_id == run_id).order_by(ReviewItem.created_at)
        )
    )


def resolve_review_item(
    session: Session,
    run_id: str,
    item_id: str,
    user_id: str,
    action: str,
    candidate_index: int | None,
) -> tuple[ReviewItem, str | None]:
    item = next(
        (
            candidate
            for candidate in list_review_items(session, run_id, user_id)
            if candidate.item_id == item_id
        ),
        None,
    )
    if item is None:
        raise ExecutionError("review_item_not_found", "待确认项不存在。", 404)
    if item.status != "pending":
        return item, None
    if action == "select" and (candidate_index is None or candidate_index >= len(item.candidates)):
        raise ExecutionError("invalid_candidate", "请选择有效候选项。", 422)
    if action not in {"select", "reject"}:
        raise ExecutionError("invalid_resolution", "确认操作无效。", 422)
    if action == "select" and item.item_type.startswith("statement:"):
        chosen = item.candidates[candidate_index or 0]
        statement_type = item.item_type.removeprefix("statement:")
        statement = session.scalar(
            select(StatementIdentification)
            .join(SourceDocument)
            .where(
                SourceDocument.run_id == run_id,
                StatementIdentification.statement_type == statement_type,
            )
        )
        if statement:
            statement.status = "located"
            statement.title = chosen.get("title")
            statement.scope = "consolidated"
            statement.page_number = chosen.get("page_number")
            statement.table_id = chosen.get("table_id")
            statement.locator = chosen.get("locator")
            if chosen.get("period_end"):
                statement.period_end = date.fromisoformat(str(chosen["period_end"]))
    item.status = "resolved" if action == "select" else "rejected"
    item.resolution = {"action": action, "candidate_index": candidate_index}
    item.resolved_at = datetime.now(UTC)
    session.commit()
    pending = session.scalar(
        select(ReviewItem).where(ReviewItem.run_id == run_id, ReviewItem.status == "pending")
    )
    execution = session.scalar(select(AnalysisExecution).where(AnalysisExecution.run_id == run_id))
    if action == "select" and pending is None and execution:
        execution.status = "queued"
        execution.updated_at = datetime.now(UTC)
        run = session.get(AnalysisRun, run_id)
        if run:
            run.status = "queued"
            run.updated_at = execution.updated_at
        session.commit()
        return item, execution.execution_id
    return item, None
