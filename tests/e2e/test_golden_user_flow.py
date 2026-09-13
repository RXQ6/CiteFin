"""F018 synthetic golden-flow acceptance tests through the public HTTP API."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from citefin.api.dependencies import get_database_session
from citefin.config import Settings, get_settings
from citefin.db.base import Base
from citefin.db.models import (
    AnalysisRun,
    AuditEvent,
    CalculatedMetric,
    Claim,
    Evaluation,
    FinancialFact,
    GoalGateDecision,
    Report,
    SourceDocument,
)
from citefin.db.session import build_engine
from citefin.main import create_app
from citefin.workflow import WORKFLOW_VERSION

ROOT = Path(__file__).parents[2]
GOLDEN = json.loads(
    (ROOT / "tests/golden/cases/G001_standard_profitable/expected.json").read_text(encoding="utf-8")
)
USER_ID = "f018_acceptance_user"
PERIOD_END = "2025-12-31"


@pytest.fixture
def acceptance_harness(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    """Provide isolated persistence and object storage for the full flow."""

    database_url = f"sqlite+pysqlite:///{(tmp_path / 'f018.db').as_posix()}"
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        object_storage_root=tmp_path / "objects",
        max_upload_bytes=1024 * 1024,
        min_pdf_text_characters=20,
    )

    def override_session() -> Iterator[Session]:
        with sessions() as session:
            yield session

    application = create_app()
    application.dependency_overrides[get_database_session] = override_session
    application.dependency_overrides[get_settings] = lambda: settings
    with TestClient(application) as client:
        yield client, sessions
    engine.dispose()


def _synthetic_pdf() -> bytes:
    """Build a deterministic searchable three-page annual-report-shaped fixture."""

    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    titles = (
        "Consolidated Balance Sheet synthetic acceptance fixture 2025 and 2024",
        "Consolidated Income Statement synthetic acceptance fixture 2025 and 2024",
        "Consolidated Cash Flow Statement synthetic acceptance fixture 2025",
    )
    for title in titles:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({title}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _headers() -> dict[str, str]:
    return {"X-User-ID": USER_ID}


def _create_run(client: TestClient, key: str) -> dict[str, Any]:
    payload = {
        "company_name": GOLDEN["company"]["name"],
        "security_code": GOLDEN["company"]["security_code"],
        "report_period_end": PERIOD_END,
        "as_of": GOLDEN["as_of"],
    }
    headers = _headers() | {"Idempotency-Key": key}
    first = client.post("/api/v1/analysis-runs", headers=headers, json=payload)
    replay = client.post("/api/v1/analysis-runs", headers=headers, json=payload)
    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["run_id"] == first.json()["run_id"]
    assert replay.json()["idempotent_replay"] is True
    return first.json()


def _fact_payload(row: dict[str, Any]) -> dict[str, Any]:
    sections = {
        "balance_sheet": "合并资产负债表",
        "income_statement": "合并利润表",
        "cashflow_statement": "合并现金流量表",
    }
    return {
        "statement_type": row["statement_type"],
        "raw_label": row["row_label"],
        "raw_value": row["raw_value"],
        "period_start": row.get("period_start"),
        "period_end": row["period_end"],
        "period_type": row["period_type"],
        "scope": "consolidated",
        "currency": "CNY",
        "display_unit": "thousand_yuan",
        "page_number": row["page_number"],
        "section": sections[row["statement_type"]],
        "table_id": f"synthetic_table_{row['page_number']}",
        "row_label": row["row_label"],
        "column_label": row["column_label"],
        "extraction_method": "manual",
        "confidence": "1",
    }


def _post_replay(
    client: TestClient, endpoint: str, payload: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    first = client.post(endpoint, headers=_headers(), json=payload)
    replay = client.post(endpoint, headers=_headers(), json=payload)
    assert first.status_code == 201, first.text
    assert replay.status_code == 200, replay.text
    assert replay.json()["idempotent_replay"] is True
    return first.json(), replay.json()


def test_one_click_execution_stops_at_explicit_review(
    acceptance_harness: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = acceptance_harness
    run = _create_run(client, "automatic-review-key")
    run_id = run["run_id"]
    upload = client.post(
        f"/api/v1/analysis-runs/{run_id}/documents",
        headers=_headers(),
        files={"file": ("synthetic.pdf", _synthetic_pdf(), "application/pdf")},
    )
    assert upload.status_code == 201

    started = client.post(f"/api/v1/analysis-runs/{run_id}/execute", headers=_headers())
    assert started.status_code == 202
    replay = client.post(f"/api/v1/analysis-runs/{run_id}/execute", headers=_headers())
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True

    review = client.get(f"/api/v1/analysis-runs/{run_id}/review-items", headers=_headers())
    assert review.status_code == 200
    assert [item["item_type"] for item in review.json()] == ["financial_facts"]
    item_id = review.json()[0]["item_id"]
    invalid = client.post(
        f"/api/v1/analysis-runs/{run_id}/review-items/{item_id}/resolve",
        headers=_headers(),
        json={"action": "select", "candidate_index": 0},
    )
    assert invalid.status_code == 422
    rejected = client.post(
        f"/api/v1/analysis-runs/{run_id}/review-items/{item_id}/resolve",
        headers=_headers(),
        json={"action": "reject"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    hidden = client.get(
        f"/api/v1/analysis-runs/{run_id}/review-items",
        headers={"X-User-ID": "another-user"},
    )
    assert hidden.status_code == 404


def test_confirmed_facts_resume_and_finish_the_persisted_workflow(
    acceptance_harness: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """Prove the real execution path resumes after human fact confirmation."""

    client, sessions = acceptance_harness
    run = _create_run(client, "automatic-resume-key")
    run_id = run["run_id"]
    pdf = _synthetic_pdf()
    upload = client.post(
        f"/api/v1/analysis-runs/{run_id}/documents",
        headers=_headers(),
        files={"file": ("synthetic-annual-report.pdf", pdf, "application/pdf")},
    )
    assert upload.status_code == 201
    source_id = upload.json()["source_id"]

    started = client.post(f"/api/v1/analysis-runs/{run_id}/execute", headers=_headers())
    assert started.status_code == 202
    review = client.get(f"/api/v1/analysis-runs/{run_id}/review-items", headers=_headers())
    assert review.status_code == 200
    fact_review = review.json()[0]
    assert fact_review["item_type"] == "financial_facts"

    premature = client.post(
        f"/api/v1/analysis-runs/{run_id}/review-items/{fact_review['item_id']}/resolve",
        headers=_headers(),
        json={"action": "confirm"},
    )
    assert premature.status_code == 409
    assert premature.json()["detail"]["code"] == "financial_facts_required"

    fact_path = f"/api/v1/analysis-runs/{run_id}/documents/{source_id}/facts/normalize"
    for row in GOLDEN["expected_facts"]:
        response = client.post(fact_path, headers=_headers(), json=_fact_payload(row))
        assert response.status_code == 201, response.text

    confirmed = client.post(
        f"/api/v1/analysis-runs/{run_id}/review-items/{fact_review['item_id']}/resolve",
        headers=_headers(),
        json={"action": "confirm"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "resolved"

    progress = client.get(f"/api/v1/analysis-runs/{run_id}/progress", headers=_headers())
    assert progress.status_code == 200
    assert progress.json()["status"] == "verified"
    assert progress.json()["current_node"] == "finalize"

    workspace = client.get(f"/api/v1/analysis-runs/{run_id}/workspace", headers=_headers()).json()
    assert len(workspace["metrics"]) == 15
    assert workspace["reports"][0]["status"] == "verified"
    assert workspace["evaluations"][0]["status"] == "passed"
    assert workspace["gate_decisions"][0]["decision"] == "verified"
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Report)) == 1


def test_synthetic_golden_flow_is_replayable_evidenced_and_verified(
    acceptance_harness: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """Exercise F001-F017 and prove F013 is the only completion path."""

    client, sessions = acceptance_harness
    run = _create_run(client, "f018-success-key")
    run_id = run["run_id"]

    upload_path = f"/api/v1/analysis-runs/{run_id}/documents"
    pdf = _synthetic_pdf()
    uploaded = client.post(
        upload_path,
        headers=_headers(),
        files={"file": ("synthetic-annual-report.pdf", pdf, "application/pdf")},
    )
    upload_replay = client.post(
        upload_path,
        headers=_headers(),
        files={"file": ("renamed.pdf", pdf, "application/pdf")},
    )
    assert uploaded.status_code == 201
    assert upload_replay.status_code == 200
    assert upload_replay.json()["source_id"] == uploaded.json()["source_id"]
    source_id = uploaded.json()["source_id"]

    parse_path = f"{upload_path}/{source_id}/parse"
    parsed, parsed_replay = _post_replay(client, parse_path, {})
    assert parsed["page_count"] == 3
    assert parsed_replay["source_id"] == source_id

    statements_path = f"{upload_path}/{source_id}/statements"
    statements, _ = _post_replay(client, statements_path, {})
    assert len(statements["statements"]) == 3

    fact_path = f"{upload_path}/{source_id}/facts/normalize"
    fact_ids: list[str] = []
    for row in GOLDEN["expected_facts"]:
        response = client.post(fact_path, headers=_headers(), json=_fact_payload(row))
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["concept"] == row["concept"]
        assert Decimal(body["normalized_value"]) == Decimal(row["normalized_value"])
        fact_ids.append(body["fact_id"])
    fact_replay = client.post(
        fact_path,
        headers=_headers(),
        json=_fact_payload(GOLDEN["expected_facts"][0]),
    )
    assert fact_replay.status_code == 200
    assert fact_replay.json()["fact_id"] == fact_ids[0]

    checkpoint_state = {
        "run_id": run_id,
        "thread_id": run["thread_id"],
        "task_id": run["task_id"],
        "source_ids": [source_id],
        "fact_ids": fact_ids,
        "current_node": "request_guard",
        "status": "validating",
        "workflow_version": WORKFLOW_VERSION,
        "state_version": 2,
        "as_of": GOLDEN["as_of"],
    }
    checkpoint_path = f"/api/v1/analysis-runs/{run_id}/checkpoints"
    checkpoint, _ = _post_replay(client, checkpoint_path, {"state": checkpoint_state})
    restore_path = f"{checkpoint_path}/{checkpoint['checkpoint_id']}/restore"
    restored = client.post(restore_path, headers=_headers())
    restored_replay = client.post(restore_path, headers=_headers())
    assert restored.status_code == 200
    assert restored_replay.status_code == 200
    assert restored_replay.headers["X-Checkpoint-Replay"] == "true"

    metrics_path = f"/api/v1/analysis-runs/{run_id}/metrics/calculate"
    metrics, metrics_replay = _post_replay(client, metrics_path, {"period_end": PERIOD_END})
    actual_metrics = {item["metric_code"]: item for item in metrics["metrics"]}
    assert len(actual_metrics) == 15
    assert {item["metric_id"] for item in metrics_replay["metrics"]} == {
        item["metric_id"] for item in metrics["metrics"]
    }
    for expected in GOLDEN["expected_metrics"]:
        actual = actual_metrics[expected["metric_code"]]
        assert actual["status"] == expected["status"]
        assert actual["unit"] == expected["unit"]
        assert abs(Decimal(actual["value"]) - Decimal(expected["value"])) <= Decimal("1e-14")
        assert actual["input_fact_ids"]

    analysis, analysis_replay = _post_replay(
        client,
        f"/api/v1/analysis-runs/{run_id}/financial-analysis",
        {"period_end": PERIOD_END},
    )
    assert analysis["claims"]
    assert {item["claim_id"] for item in analysis_replay["claims"]} == {
        item["claim_id"] for item in analysis["claims"]
    }

    risks, risks_replay = _post_replay(
        client,
        f"/api/v1/analysis-runs/{run_id}/risk-detection",
        {"period_end": PERIOD_END},
    )
    assert {item["risk_id"] for item in risks_replay["findings"]} == {
        item["risk_id"] for item in risks["findings"]
    }

    report, report_replay = _post_replay(
        client,
        f"/api/v1/analysis-runs/{run_id}/reports",
        {"period_end": PERIOD_END},
    )
    assert report["status"] == "candidate"
    assert report_replay["report_id"] == report["report_id"]

    evidence_response = client.get(
        f"/api/v1/analysis-runs/{run_id}/evidence-view",
        headers=_headers(),
        params={"report_id": report["report_id"]},
    )
    assert evidence_response.status_code == 200
    evidence_view = evidence_response.json()
    major_claims = [claim for claim in evidence_view["claims"] if claim["materiality"] == "major"]
    major_with_pages = [
        claim
        for claim in major_claims
        if any(
            page["status"] == "available"
            for evidence in claim["evidence"]
            for page in evidence["source_pages"]
        )
    ]
    assert major_claims
    assert len(major_with_pages) / len(major_claims) == 1
    content_url = major_with_pages[0]["evidence"][0]["source_pages"][0]["content_url"]
    pdf_response = client.get(content_url, headers=_headers())
    assert pdf_response.status_code == 200
    assert pdf_response.content == pdf

    evaluation, evaluation_replay = _post_replay(
        client,
        f"/api/v1/analysis-runs/{run_id}/evaluations",
        {"report_id": report["report_id"]},
    )
    assert evaluation["status"] == "passed"
    assert len(evaluation["checks"]) == 8
    visualization_check = next(
        check for check in evaluation["checks"] if check["code"] == "visualization_integrity"
    )
    assert visualization_check["result"] == "passed"
    assert all(check["result"] == "passed" for check in evaluation["checks"])
    assert evaluation_replay["evaluation_id"] == evaluation["evaluation_id"]

    gate, gate_replay = _post_replay(
        client,
        f"/api/v1/analysis-runs/{run_id}/goal-gate",
        {"report_id": report["report_id"]},
    )
    assert gate["decision"] == "verified"
    assert gate_replay["gate_id"] == gate["gate_id"]
    progress = client.get(f"/api/v1/analysis-runs/{run_id}/progress", headers=_headers())
    assert progress.status_code == 200
    assert progress.json()["status"] == "verified"
    assert progress.json()["current_node"] == "finalize"
    assert progress.json()["completed_at"] is not None

    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(SourceDocument)) == 1
        assert session.scalar(select(func.count()).select_from(FinancialFact)) == 23
        assert session.scalar(select(func.count()).select_from(CalculatedMetric)) == 15
        assert session.scalar(select(func.count()).select_from(Report)) == 1
        assert session.scalar(select(func.count()).select_from(Evaluation)) == 1
        assert session.scalar(select(func.count()).select_from(GoalGateDecision)) == 1
        for event_type in ("checkpoint_saved", "checkpoint_restored"):
            count = session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.run_id == run_id, AuditEvent.event_type == event_type)
            )
            assert count == 1


def test_failed_goal_gate_never_exposes_completed_progress(
    acceptance_harness: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """Prove a failed independent evaluation cannot mark a run complete."""

    client, sessions = acceptance_harness
    run = _create_run(client, "f018-failed-key")
    run_id = run["run_id"]
    report_id = "report_f018_invalid"
    claim_id = "claim_f018_unsupported_major"
    now = datetime.now(UTC)
    with sessions() as session:
        session.add(
            Claim(
                claim_id=claim_id,
                run_id=run_id,
                claim_type="inference",
                text="缺少证据的重大结论。",
                materiality="major",
                status="supported",
                evidence_ids=[],
                created_by="f018-negative-fixture",
                created_at=now,
            )
        )
        session.add(
            Report(
                report_id=report_id,
                run_id=run_id,
                version=1,
                status="candidate",
                schema_version="financial-report-v1",
                content={
                    "schema_version": "financial-report-v1",
                    "run": {"run_id": run_id},
                    "facts": [],
                    "calculations": {"metrics": [], "claims": []},
                    "inferences": [],
                    "risks": [],
                    "limitations": {"claims": [], "risk_limitations": []},
                    "evidence": {},
                },
                claim_ids=[claim_id],
                generated_by="f018-negative-fixture",
                created_at=now,
            )
        )
        session.add(
            AuditEvent(
                event_id="event_f018_invalid_report",
                run_id=run_id,
                trace_id="trace_f018_invalid_report",
                node="write_report",
                event_type="report_candidate_generated",
                status="success",
                payload={"report_id": report_id},
                created_at=now,
            )
        )
        session.commit()

    evaluation = client.post(
        f"/api/v1/analysis-runs/{run_id}/evaluations",
        headers=_headers(),
        json={"report_id": report_id},
    )
    assert evaluation.status_code == 201
    assert evaluation.json()["status"] == "failed"
    gate = client.post(
        f"/api/v1/analysis-runs/{run_id}/goal-gate",
        headers=_headers(),
        json={"report_id": report_id},
    )
    assert gate.status_code == 201
    assert gate.json()["decision"] == "revision_required"
    progress = client.get(f"/api/v1/analysis-runs/{run_id}/progress", headers=_headers())
    assert progress.status_code == 200
    assert progress.json()["status"] == "revision_required"
    assert progress.json()["current_node"] == "build_evidence_map"
    assert progress.json()["completed_at"] is None
    with sessions() as session:
        db_run = session.get(AnalysisRun, run_id)
        db_report = session.get(Report, report_id)
        assert db_run is not None and db_run.status != "verified"
        assert db_report is not None and db_report.status == "candidate"
