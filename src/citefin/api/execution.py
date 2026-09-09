"""Automatic analysis execution and explicit conflict review API."""

from datetime import datetime
from typing import NoReturn

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response, status
from pydantic import BaseModel, Field
from redis import Redis

from citefin.api.analysis_runs import UserIdHeader
from citefin.api.dependencies import DatabaseSession, SettingsDependency
from citefin.services.execution import (
    ExecutionError,
    enqueue_execution,
    list_review_items,
    process_execution_by_id,
    resolve_review_item,
)

router = APIRouter(prefix="/analysis-runs", tags=["automatic-analysis"])


class ExecutionResponse(BaseModel):
    execution_id: str
    run_id: str
    status: str
    current_node: str | None
    attempt_count: int
    error_code: str | None
    idempotent_replay: bool


class ReviewItemResponse(BaseModel):
    item_id: str
    item_type: str
    checkpoint_node: str
    status: str
    title: str
    prompt: str
    candidates: list[dict[str, object]]
    resolution: dict[str, object] | None
    created_at: datetime
    resolved_at: datetime | None


class ReviewResolution(BaseModel):
    action: str = Field(pattern="^(select|reject)$")
    candidate_index: int | None = Field(default=None, ge=0)


def _raise_execution(error: ExecutionError) -> NoReturn:
    raise HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.message},
    ) from error


@router.post(
    "/{run_id}/execute",
    response_model=ExecutionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def execute_run(
    run_id: str,
    response: Response,
    background_tasks: BackgroundTasks,
    user_id: UserIdHeader,
    session: DatabaseSession,
    settings: SettingsDependency,
) -> ExecutionResponse:
    try:
        execution, replay = enqueue_execution(session, settings, run_id, user_id)
    except ExecutionError as error:
        _raise_execution(error)
    if replay:
        response.status_code = status.HTTP_200_OK
    elif settings.analysis_queue_mode == "inline":
        background_tasks.add_task(process_execution_by_id, settings, execution.execution_id)
    return ExecutionResponse(
        execution_id=execution.execution_id,
        run_id=execution.run_id,
        status=execution.status,
        current_node=execution.current_node,
        attempt_count=execution.attempt_count,
        error_code=execution.error_code,
        idempotent_replay=replay,
    )


@router.get("/{run_id}/review-items", response_model=list[ReviewItemResponse])
def get_review_items(
    run_id: str, user_id: UserIdHeader, session: DatabaseSession
) -> list[ReviewItemResponse]:
    try:
        items = list_review_items(session, run_id, user_id)
    except ExecutionError as error:
        _raise_execution(error)
    return [ReviewItemResponse.model_validate(item.__dict__) for item in items]


@router.post("/{run_id}/review-items/{item_id}/resolve", response_model=ReviewItemResponse)
def resolve_item(
    run_id: str,
    item_id: str,
    payload: ReviewResolution,
    user_id: UserIdHeader,
    session: DatabaseSession,
    settings: SettingsDependency,
    background_tasks: BackgroundTasks,
) -> ReviewItemResponse:
    try:
        item, resume_execution_id = resolve_review_item(
            session,
            run_id,
            item_id,
            user_id,
            payload.action,
            payload.candidate_index,
        )
    except ExecutionError as error:
        _raise_execution(error)
    if resume_execution_id:
        if settings.analysis_queue_mode == "inline":
            background_tasks.add_task(process_execution_by_id, settings, resume_execution_id)
        elif settings.redis_url:
            Redis.from_url(settings.redis_url).rpush(
                settings.analysis_queue_name, resume_execution_id
            )
    return ReviewItemResponse.model_validate(item.__dict__)
