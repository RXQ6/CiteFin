"""F015 API for owned run progress and replayable lifecycle events."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from citefin.api.analysis_runs import UserIdHeader
from citefin.api.dependencies import DatabaseSession
from citefin.services.progress import (
    ProgressError,
    get_run_progress,
    list_lifecycle_events,
    safe_event_payload,
)

router = APIRouter(prefix="/analysis-runs", tags=["progress"])


class TaskProgressResponse(BaseModel):
    """Safe task state for the progress view."""

    task_id: str
    feature_id: str
    task_type: str
    title: str
    status: str
    attempt_count: int
    blocked_by: list[str]
    error_code: str | None
    started_at: datetime | None
    finished_at: datetime | None


class ProgressErrorResponse(BaseModel):
    """Redacted recent lifecycle error."""

    event_id: str
    node: str
    event_type: str
    status: str
    code: str
    created_at: datetime


class RunProgressResponse(BaseModel):
    """Owned run status without internal prompts or error bodies."""

    run_id: str
    status: str
    current_node: str | None
    workflow_version: str
    failure_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    tasks: list[TaskProgressResponse]
    recent_errors: list[ProgressErrorResponse]


def _utc_datetime(value: datetime) -> datetime:
    """Normalize SQLite's timezone-naive round-trip to a stable API value."""

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@router.get("/{run_id}/progress", response_model=RunProgressResponse)
def get_progress_endpoint(
    run_id: str,
    user_id: UserIdHeader,
    session: DatabaseSession,
    error_limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> RunProgressResponse:
    """Return owned run state, task summaries, and recent redacted errors."""

    try:
        progress = get_run_progress(session, run_id, user_id, error_limit=error_limit)
    except ProgressError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    run = progress.run
    return RunProgressResponse(
        run_id=run.run_id,
        status=run.status,
        current_node=run.current_node,
        workflow_version=run.workflow_version,
        failure_code=run.failure_code,
        created_at=_utc_datetime(run.created_at),
        updated_at=_utc_datetime(run.updated_at),
        completed_at=_utc_datetime(run.completed_at) if run.completed_at else None,
        tasks=[TaskProgressResponse.model_validate(task.__dict__) for task in progress.tasks],
        recent_errors=[
            ProgressErrorResponse.model_validate(error.__dict__) for error in progress.recent_errors
        ],
    )


def _event_frame(event: object) -> str:
    event_id = event.event_id  # type: ignore[attr-defined]
    data = {
        "event_id": event_id,
        "run_id": event.run_id,  # type: ignore[attr-defined]
        "trace_id": event.trace_id,  # type: ignore[attr-defined]
        "node": event.node,  # type: ignore[attr-defined]
        "event_type": event.event_type,  # type: ignore[attr-defined]
        "status": event.status,  # type: ignore[attr-defined]
        "created_at": _utc_datetime(event.created_at).isoformat(),  # type: ignore[attr-defined]
        "payload": safe_event_payload(event.payload),  # type: ignore[attr-defined]
    }
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event_id}\nevent: lifecycle\ndata: {body}\n\n"


@router.get("/{run_id}/events")
def stream_events_endpoint(
    run_id: str,
    user_id: UserIdHeader,
    session: DatabaseSession,
    after: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> StreamingResponse:
    """Stream a finite ordered snapshot; reconnect with the last event ID."""

    try:
        page = list_lifecycle_events(
            session,
            run_id,
            user_id,
            after_event_id=after or last_event_id,
            limit=limit,
        )
    except ProgressError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error

    def generate() -> Iterator[str]:
        for event in page.events:
            yield _event_frame(event)

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "X-Events-More": "true" if page.has_more else "false",
    }
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers=headers,
        status_code=status.HTTP_200_OK,
    )
