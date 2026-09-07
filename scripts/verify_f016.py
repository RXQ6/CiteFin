"""Verify the repository-level F016 frontend contract."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    catalog = json.loads((ROOT / "FEATURES.json").read_text(encoding="utf-8"))
    feature = next(item for item in catalog["features"] if item["id"] == "F016")
    assert feature["status"] == "candidate_complete"
    assert feature["owner"] == "codex"
    assert feature["verification"]["evidence"]

    index = (ROOT / "src" / "citefin" / "static" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "src" / "citefin" / "static" / "assets" / "app.js").read_text(
        encoding="utf-8"
    )
    stylesheet = (ROOT / "src" / "citefin" / "static" / "assets" / "app.css").read_text(
        encoding="utf-8"
    )

    for required_control in ("analysis-form", "report-file", "run-panel", "aria-live"):
        assert required_control in index
    for service_contract in ("/analysis-runs", "/documents", "/progress", "/events"):
        assert service_contract in script
    assert "setInterval" in script
    assert "模拟" not in index + script
    assert ":focus-visible" in stylesheet
    assert "@media" in stylesheet
    print("F016 verification passed: static UI, service-backed progress, and accessible responsive controls.")


if __name__ == "__main__":
    main()
