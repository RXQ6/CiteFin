"""Public synthetic demo API contract tests."""

from fastapi.testclient import TestClient

from citefin.main import app


def test_demo_workspace_is_public_versioned_and_explicitly_synthetic() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/demo/workspace")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "public-demo-v1"
    assert body["synthetic"] is True
    assert body["case_id"] == "G001_standard_profitable"
    assert len(body["metrics"]) == 15
    assert body["audit"]["major_claim_evidence_coverage"] == "100%"
    assert "不代表真实公司" in body["notice"]


def test_demo_evidence_is_allowlisted_and_searchable_pdf() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/demo/evidence/demo_g001_annual_report/content")
        missing = client.get("/api/v1/demo/evidence/../../private/content")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
    assert missing.status_code == 404
