"""F007 claim and source-locator evidence API tests."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from citefin.api.dependencies import get_database_session
from citefin.config import Settings, get_settings
from citefin.db.base import Base
from citefin.db.models import AnalysisRun, DocumentPage, SourceDocument, StoredObject
from citefin.db.session import build_engine
from citefin.main import create_app


def _harness(tmp_path: Path) -> tuple[TestClient, sessionmaker[Session]]:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'evidence.db').as_posix()}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
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
    return TestClient(application), sessions


def _run_with_page(client: TestClient, sessions: sessionmaker[Session]) -> str:
    response = client.post(
        "/api/v1/analysis-runs",
        headers={"X-User-ID": "evidence_user", "Idempotency-Key": "evidence-key-1234"},
        json={
            "company_name": "证据示例股份有限公司",
            "security_code": "600001",
            "report_period_end": "2025-12-31",
            "as_of": "2026-04-11T00:00:00Z",
        },
    )
    assert response.status_code == 201
    run_id = response.json()["run_id"]
    now = datetime.now(UTC)
    with sessions() as session:
        session.add(
            StoredObject(
                sha256="b" * 64,
                storage_uri="object://" + "b" * 64,
                media_type="application/pdf",
                byte_size=1,
                created_at=now,
            )
        )
        source = SourceDocument(
            source_id="src_evidence",
            run_id=run_id,
            document_type="annual_report",
            file_name="evidence.pdf",
            media_type="application/pdf",
            sha256="b" * 64,
            storage_uri="object://" + "b" * 64,
            language="zh-CN",
            page_count=1,
            text_extractable=True,
            parser_version="test",
            ingested_at=now,
        )
        session.add(source)
        session.add(
            DocumentPage(
                source_id="src_evidence",
                page_number=1,
                text="合并资产负债表\n资产总计 100",
                text_sha256="c" * 64,
                parser_version="test",
                parse_status="parsed",
                created_at=now,
            )
        )
        session.commit()
    return run_id


def test_claim_and_source_locator_evidence_are_persisted(tmp_path: Path) -> None:
    client, sessions = _harness(tmp_path)
    run_id = _run_with_page(client, sessions)
    claim = client.post(
        f"/api/v1/analysis-runs/{run_id}/claims",
        headers={"X-User-ID": "evidence_user"},
        json={
            "claim_type": "fact",
            "text": "报告期末资产总额为100元。",
            "materiality": "major",
        },
    )
    assert claim.status_code == 201
    claim_id = claim.json()["claim_id"]
    evidence = client.post(
        f"/api/v1/analysis-runs/{run_id}/claims/{claim_id}/evidence",
        headers={"X-User-ID": "evidence_user"},
        json={
            "evidence_type": "source_locator",
            "supports": "supports",
            "source_id": "src_evidence",
            "page_number": 1,
            "locator": {"section": "合并资产负债表", "row": "资产总计"},
            "excerpt": "资产总计 100",
        },
    )
    assert evidence.status_code == 201
    assert evidence.json()["source_id"] == "src_evidence"
    with sessions() as session:
        stored_claim = session.scalar(select(AnalysisRun).where(AnalysisRun.run_id == run_id))
        assert stored_claim is not None


def test_evidence_requires_one_matching_target(tmp_path: Path) -> None:
    client, _ = _harness(tmp_path)
    response = client.post(
        "/api/v1/analysis-runs/run_missing/claims/claim_missing/evidence",
        headers={"X-User-ID": "evidence_user"},
        json={"evidence_type": "fact", "supports": "supports", "fact_id": "fact_missing"},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "run_not_found"
