"""F014 durable checkpoint save, integrity validation, and recovery tests."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from citefin.api.dependencies import get_database_session
from citefin.db.base import Base
from citefin.db.models import (
    AnalysisRun,
    AuditEvent,
    SourceDocument,
    StoredObject,
    WorkflowCheckpoint,
)
from citefin.db.session import build_engine
from citefin.main import create_app
from citefin.workflow import WORKFLOW_VERSION


def _harness(tmp_path: Path) -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'checkpoints.db').as_posix()}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session() -> Iterator[Session]:
        with sessions() as session:
            yield session

    application = create_app()
    application.dependency_overrides[get_database_session] = override_session
    application.dependency_overrides[get_database_session] = override_session
    with TestClient(application) as client:
        yield client, sessions
    engine.dispose()


@pytest.fixture
def checkpoint_harness(tmp_path: Path) -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    yield from _harness(tmp_path)


def _create_run(client: TestClient, user_id: str = "checkpoint_user") -> dict[str, str]:
    response = client.post(
        "/api/v1/analysis-runs",
        headers={"X-User-ID": user_id, "Idempotency-Key": f"checkpoint-key-{user_id}"},
        json={
            "company_name": "Checkpoint 示例股份有限公司",
            "security_code": "600001",
            "report_period_end": "2025-12-31",
            "as_of": "2026-04-11T00:00:00Z",
        },
    )
    assert response.status_code == 201
    return response.json()


def _state(
    run: dict[str, str], *, version: int = 2, node: str = "request_guard"
) -> dict[str, object]:
    return {
        "run_id": run["run_id"],
        "thread_id": run["thread_id"],
        "task_id": run["task_id"],
        "current_node": node,
        "status": "validating" if node == "request_guard" else "running",
        "workflow_version": WORKFLOW_VERSION,
        "state_version": version,
        "as_of": "2026-04-11T00:00:00Z",
    }


def _headers(user_id: str = "checkpoint_user") -> dict[str, str]:
    return {"X-User-ID": user_id}


def test_checkpoint_save_replay_and_restore_are_idempotent(
    checkpoint_harness: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = checkpoint_harness
    run = _create_run(client)
    payload = {"state": _state(run)}

    first = client.post(
        f"/api/v1/analysis-runs/{run['run_id']}/checkpoints",
        headers=_headers(),
        json=payload,
    )
    replay = client.post(
        f"/api/v1/analysis-runs/{run['run_id']}/checkpoints",
        headers=_headers(),
        json=payload,
    )
    assert first.status_code == 201
    assert replay.status_code == 200
    assert first.json()["checkpoint_id"] == replay.json()["checkpoint_id"]
    assert replay.json()["idempotent_replay"] is True
    checkpoint_id = first.json()["checkpoint_id"]

    restored = client.post(
        f"/api/v1/analysis-runs/{run['run_id']}/checkpoints/{checkpoint_id}/restore",
        headers=_headers(),
    )
    restored_replay = client.post(
        f"/api/v1/analysis-runs/{run['run_id']}/checkpoints/{checkpoint_id}/restore",
        headers=_headers(),
    )
    assert restored.status_code == 200
    assert restored.json()["state"]["state_version"] == 2
    assert restored_replay.status_code == 200
    assert restored_replay.headers["X-Checkpoint-Replay"] == "true"
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(WorkflowCheckpoint)) == 2
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.event_type == "checkpoint_saved")
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.event_type == "checkpoint_restored")
            )
            == 1
        )
        db_run = session.get(AnalysisRun, run["run_id"])
        assert db_run is not None and db_run.current_node == "request_guard"


def test_checkpoint_version_conflict_and_regression_are_rejected(
    checkpoint_harness: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = checkpoint_harness
    run = _create_run(client)
    path = f"/api/v1/analysis-runs/{run['run_id']}/checkpoints"
    assert client.post(path, headers=_headers(), json={"state": _state(run)}).status_code == 201
    conflict_state = _state(run) | {"current_node": "document_parse", "status": "running"}
    conflict = client.post(path, headers=_headers(), json={"state": conflict_state})
    regression = client.post(
        path,
        headers=_headers(),
        json={"state": _state(run, version=1, node="create_run")},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "checkpoint_version_conflict"
    assert regression.status_code == 409
    assert regression.json()["detail"]["code"] == "checkpoint_version_conflict"


def test_checkpoint_rejects_workflow_mismatch_and_cross_user_access(
    checkpoint_harness: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = checkpoint_harness
    run = _create_run(client)
    path = f"/api/v1/analysis-runs/{run['run_id']}/checkpoints"
    mismatched = _state(run) | {"workflow_version": "0.9.0"}
    response = client.post(path, headers=_headers(), json={"state": mismatched})
    foreign = client.post(path, headers=_headers("other_user"), json={"state": _state(run)})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "workflow_version_mismatch"
    assert foreign.status_code == 404
    assert foreign.json()["detail"]["code"] == "analysis_run_not_found"


def _add_source(sessions: sessionmaker[Session], run_id: str) -> tuple[str, str]:
    source_id = "src_checkpoint"
    digest = "a" * 64
    with sessions() as session:
        session.add(
            StoredObject(
                sha256=digest,
                storage_uri=f"local://sha256/{digest}",
                media_type="application/pdf",
                byte_size=100,
                created_at=datetime.now(UTC),
            )
        )
        session.add(
            SourceDocument(
                source_id=source_id,
                run_id=run_id,
                document_type="annual_report",
                file_name="report.pdf",
                media_type="application/pdf",
                sha256=digest,
                storage_uri=f"local://sha256/{digest}",
                language="zh-CN",
                page_count=1,
                text_extractable=True,
                parser_version="test",
                ingested_at=datetime.now(UTC),
            )
        )
        session.commit()
    return source_id, digest


def test_checkpoint_captures_source_hash_and_blocks_hash_drift(
    checkpoint_harness: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = checkpoint_harness
    run = _create_run(client)
    source_id, digest = _add_source(sessions, run["run_id"])
    state = _state(run) | {"source_ids": [source_id]}
    path = f"/api/v1/analysis-runs/{run['run_id']}/checkpoints"
    saved = client.post(path, headers=_headers(), json={"state": state})
    assert saved.status_code == 201
    assert saved.json()["state"]["source_hashes"] == {source_id: digest}
    bad_hash = state | {"source_hashes": {source_id: "b" * 64}}
    rejected = client.post(path, headers=_headers(), json={"state": bad_hash})
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "source_hash_mismatch"

    with sessions() as session:
        source = session.get(SourceDocument, source_id)
        assert source is not None
        source.sha256 = "b" * 64
        session.commit()
    restored = client.post(
        f"{path}/{saved.json()['checkpoint_id']}/restore",
        headers=_headers(),
    )
    assert restored.status_code == 409
    assert restored.json()["detail"]["code"] == "source_hash_mismatch"


def test_checkpoint_restore_rejects_tampered_state_and_wrong_owner(
    checkpoint_harness: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = checkpoint_harness
    run = _create_run(client)
    initial_checkpoint = run["checkpoint_id"]
    wrong_owner = client.post(
        f"/api/v1/analysis-runs/{run['run_id']}/checkpoints/{initial_checkpoint}/restore",
        headers=_headers("other_user"),
    )
    assert wrong_owner.status_code == 404
    assert wrong_owner.json()["detail"]["code"] == "analysis_run_not_found"

    with sessions() as session:
        checkpoint = session.get(WorkflowCheckpoint, initial_checkpoint)
        assert checkpoint is not None
        checkpoint.state_data = checkpoint.state_data | {"unexpected": "tampered"}
        session.commit()
    tampered = client.post(
        f"/api/v1/analysis-runs/{run['run_id']}/checkpoints/{initial_checkpoint}/restore",
        headers=_headers(),
    )
    assert tampered.status_code == 409
    assert tampered.json()["detail"]["code"] == "invalid_checkpoint_state"
