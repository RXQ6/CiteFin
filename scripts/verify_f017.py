"""Verify the repository-level F017 evidence-viewer contract."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    catalog = json.loads((ROOT / "FEATURES.json").read_text(encoding="utf-8"))
    feature = next(item for item in catalog["features"] if item["id"] == "F017")
    assert feature["status"] == "candidate_complete"
    assert feature["owner"] == "codex"
    assert feature["verification"]["evidence"]

    index = (ROOT / "src" / "citefin" / "static" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "src" / "citefin" / "static" / "assets" / "app.js").read_text(
        encoding="utf-8"
    )
    service = (ROOT / "src" / "citefin" / "services" / "evidence_viewer.py").read_text(
        encoding="utf-8"
    )
    assert "evidence-panel" in index
    assert "claim-list" in index
    assert "pdf-frame" in index
    assert "/evidence-view" in script
    assert "#page=" in script
    assert "X-User-ID" in script
    for reason in ("claim_has_no_evidence", "page_not_parsed", "page_out_of_range"):
        assert reason in service
    print("F017 verification passed: claim evidence, bounded excerpts, and owned PDF page navigation.")


if __name__ == "__main__":
    main()
