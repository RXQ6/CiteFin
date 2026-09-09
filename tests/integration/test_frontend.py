"""F016/F017 and complete workbench static UI contract tests."""

from fastapi.testclient import TestClient

from citefin.main import app


def test_frontend_shell_exposes_accessible_workbench_controls() -> None:
    with TestClient(app) as client:
        response = client.get("/")
        legacy = client.get("/legacy")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'id="root"' in response.text
    assert "/app-assets/assets/" in response.text
    assert legacy.status_code == 200
    assert 'id="identity-form"' in legacy.text
    assert 'id="analysis-form"' in legacy.text
    assert 'id="workspace-view"' in legacy.text
    assert 'id="metric-grid"' in legacy.text
    assert 'id="pdf-frame"' in legacy.text
    assert "不执行交易" in legacy.text


def test_frontend_assets_use_real_workspace_progress_and_cursor_replay() -> None:
    with TestClient(app) as client:
        script = client.get("/assets/app.js")
        stylesheet = client.get("/assets/app.css")

    assert script.status_code == 200
    assert script.headers["content-type"].startswith(("text/javascript", "application/javascript"))
    assert "/workspace" in script.text
    assert "/progress" in script.text
    assert "/events" in script.text
    assert "/evidence-view" in script.text
    assert "#page=" in script.text
    assert "Last-Event-ID" not in script.text
    assert "setInterval" in script.text
    assert "模拟" not in script.text
    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert ":focus-visible" in stylesheet.text
    assert "@media" in stylesheet.text


def test_workbench_actions_call_existing_backend_capabilities() -> None:
    with TestClient(app) as client:
        script = client.get("/assets/app.js").text

    for contract in (
        "/parse",
        "/statements",
        "/facts/normalize",
        "/metrics/calculate",
        "/financial-analysis",
        "/risk-detection",
        "/reports",
        "/evaluations",
        "/goal-gate",
        "/checkpoints/",
    ):
        assert contract in script
    assert "innerHTML" not in script
