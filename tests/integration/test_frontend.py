"""F016 static UI contract tests."""

from fastapi.testclient import TestClient

from citefin.main import app


def test_frontend_shell_exposes_accessible_analysis_controls() -> None:
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'id="analysis-form"' in response.text
    assert 'id="report-file"' in response.text
    assert 'id="run-panel"' in response.text
    assert 'aria-live="polite"' in response.text
    assert "不执行交易" in response.text


def test_frontend_assets_use_real_progress_and_cursor_replay() -> None:
    with TestClient(app) as client:
        script = client.get("/assets/app.js")
        stylesheet = client.get("/assets/app.css")

    assert script.status_code == 200
    assert script.headers["content-type"].startswith("text/javascript")
    assert "/progress" in script.text
    assert "/events" in script.text
    assert "Last-Event-ID" not in script.text
    assert "setInterval" in script.text
    assert "模拟" not in script.text
    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert ":focus-visible" in stylesheet.text
    assert "@media" in stylesheet.text
