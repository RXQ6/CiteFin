"""F014 API for durable, integrity-checked workflow checkpoint recovery."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from citefin.api.analysis_runs import UserIdHeader
from citefin.api.dependencies import DatabaseSession
from citefin.services.checkpoints import CheckpointError, restore_checkpoint, save_checkpoint
from citefin.workflow import FinanceAgentState

router = APIRouter(prefix="/analysis-runs", tags=["checkpoints"])


class SaveCheckpointRequest(BaseModel):
    """State and optional LangGraph thread identity to persist."""

    state: FinanceAgentState
    thread_id: str | None = Field(default=None, min_length=1, max_length=64)


class CheckpointResponse(BaseModel):
    """Persisted checkpoint metadata and its validated control state."""

    checkpoint_id: str
    run_id: str
    thread_id: str
    node: str
    state_version: int
    state_uri: str
    state: FinanceAgentState
    created_at: datetime
    idempotent_replay: bool


def _utc_datetime(value: datetime) -> datetime:
    """Normalize SQLite's timezone-naive round-trip to a stable API value."""

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _response(result: object) -> CheckpointResponse:
    checkpoint = result.checkpoint  # type: ignore[attr-defined]
    return CheckpointResponse(
        checkpoint_id=checkpoint.checkpoint_id,
        run_id=checkpoint.run_id,
        thread_id=checkpoint.thread_id,
        node=checkpoint.node,
        state_version=checkpoint.state_version,
        state_uri=checkpoint.state_uri,
        state=result.state,  # type: ignore[attr-defined]
        created_at=_utc_datetime(checkpoint.created_at),
        idempotent_replay=result.idempotent_replay,  # type: ignore[attr-defined]
    )


@router.post(
    "/{run_id}/checkpoints",
    response_model=CheckpointResponse,
    status_code=status.HTTP_201_CREATED,
)
def save_checkpoint_endpoint(
    run_id: str,
    request: SaveCheckpointRequest,
    response: Response,
    user_id: UserIdHeader,
    session: DatabaseSession,
) -> CheckpointResponse:
    """Save a versioned state snapshot or replay the exact same version."""

    if request.state.run_id != run_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "run_id_mismatch", "message": "State run_id must match the path."},
        )
    try:
        result = save_checkpoint(
            session,
            request.state,
            user_id,
            thread_id=request.thread_id,
        )
    except CheckpointError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    if result.idempotent_replay:
        response.status_code = status.HTTP_200_OK
    return _response(result)


@router.post(
    "/{run_id}/checkpoints/{checkpoint_id}/restore",
    response_model=CheckpointResponse,
    status_code=status.HTTP_200_OK,
)
def restore_checkpoint_endpoint(
    run_id: str,
    checkpoint_id: str,
    response: Response,
    user_id: UserIdHeader,
    session: DatabaseSession,
) -> CheckpointResponse:
    """Validate and apply one owned checkpoint without repeating side effects."""

    try:
        result = restore_checkpoint(session, run_id, checkpoint_id, user_id)
    except CheckpointError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    if result.idempotent_replay:
        response.headers["X-Checkpoint-Replay"] = "true"
    return _response(result)
