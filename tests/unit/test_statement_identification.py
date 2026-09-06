"""Unit tests for deterministic F004 matching and outcome rules."""

import hashlib
import json
from datetime import date
from types import SimpleNamespace

import pytest

from citefin.services.statement_identification import (
    _load_locator,
    _normalise,
    _outcome,
    _page_candidates,
    _period_candidates,
    _period_for_page,
    _scope,
)
from citefin.storage import LocalObjectStore

EXPECTED_PERIOD = date(2025, 12, 31)


def _page(text: str, *, parsed: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        parse_status="parsed" if parsed else "failed",
        text=text,
        page_number=1,
        text_sha256="text-hash",
        bbox_index_uri=None,
        bbox_index_sha256=None,
    )


def test_text_normalisation_and_scope_markers() -> None:
    assert _normalise(" 合并\u3000资产\n负债表 ") == "合并 资产 负债表"
    assert _scope("Consolidated Balance Sheet") == "consolidated"
    assert _scope("母公司资产负债表") == "parent"
    assert _scope("Balance Sheet") == "unknown"
    assert _scope("合并及母公司资产负债表") == "unknown"


def test_period_matching_handles_exact_year_conflict_and_missing() -> None:
    assert _period_candidates("2025-12-31 2024年12月31日") == [
        date(2025, 12, 31),
        date(2024, 12, 31),
    ]
    assert _period_for_page("2025-12-31", EXPECTED_PERIOD) == (
        EXPECTED_PERIOD,
        "document_and_user_input",
        False,
    )
    assert _period_for_page("2024-12-31", EXPECTED_PERIOD) == (
        date(2024, 12, 31),
        "document",
        True,
    )
    assert _period_for_page("2025年度", EXPECTED_PERIOD) == (
        EXPECTED_PERIOD,
        "document_year_and_user_input",
        False,
    )
    assert _period_for_page("2024-12-31 2023-12-31", EXPECTED_PERIOD)[1] == (
        "multiple_document_periods"
    )
    assert _period_for_page("2026年度", EXPECTED_PERIOD)[1] == "period_not_confirmed"
    assert _period_for_page("no period", EXPECTED_PERIOD)[1] == "user_input"


def test_page_candidates_preserve_parent_and_skip_contents(tmp_path) -> None:
    store = LocalObjectStore(tmp_path)
    assert (
        _page_candidates(
            store, _page("page failure", parsed=False), "balance_sheet", EXPECTED_PERIOD
        )
        == []
    )
    assert (
        _page_candidates(
            store,
            _page("目录 Consolidated Balance Sheet 2025-12-31"),
            "balance_sheet",
            EXPECTED_PERIOD,
        )
        == []
    )
    candidates = _page_candidates(
        store,
        _page("Parent Company Balance Sheet 2025-12-31"),
        "balance_sheet",
        EXPECTED_PERIOD,
    )
    assert candidates[0]["scope"] == "parent"
    assert candidates[0]["locator"]["locator_type"] == "page"
    assert (
        _page_candidates(
            store,
            _page("合并资产负债表 2025年12月31日"),
            "balance_sheet",
            EXPECTED_PERIOD,
        )[0]["scope"]
        == "consolidated"
    )
    assert (
        _page_candidates(
            store,
            _page("合并利润表 2025年12月31日"),
            "income_statement",
            EXPECTED_PERIOD,
        )[0]["scope"]
        == "consolidated"
    )
    assert (
        _page_candidates(
            store,
            _page("合并现金流量表 2025年12月31日"),
            "cashflow_statement",
            EXPECTED_PERIOD,
        )[0]["scope"]
        == "consolidated"
    )


def test_locator_index_is_verified_and_page_mismatch_is_rejected(tmp_path) -> None:
    store = LocalObjectStore(tmp_path)
    raw = json.dumps(
        {
            "page_number": 1,
            "table_regions": [{"table_id": "table_candidate_1", "bbox": [1, 2, 3, 4]}],
        }
    ).encode()
    digest = hashlib.sha256(raw).hexdigest()
    stored = store.put_json(raw, digest)
    page = _page("Consolidated Balance Sheet 2025-12-31")
    page.bbox_index_uri = stored.storage_uri
    page.bbox_index_sha256 = digest
    table_id, bbox, locator = _load_locator(store, page)
    assert (table_id, bbox) == ("table_candidate_1", [1, 2, 3, 4])
    assert locator["bbox_index_sha256"] == digest
    page.page_number = 2
    with pytest.raises(ValueError, match="locator"):
        _load_locator(store, page)


def _candidate(scope: str, *, period_conflict: bool = False, page_number: int = 1) -> dict:
    return {
        "page_number": page_number,
        "title": "Consolidated Balance Sheet 2025-12-31",
        "scope": scope,
        "period_end": "2025-12-31",
        "period_source": "document_and_user_input",
        "period_conflict": period_conflict,
        "table_id": "table_candidate_1",
        "bbox": [1, 2, 3, 4],
        "page_text_sha256": "text-hash",
        "bbox_index_sha256": "bbox-hash",
        "locator": {"page_number": page_number},
    }


def test_outcome_rules_preserve_ambiguity_and_missing_reasons() -> None:
    located = _outcome("balance_sheet", [_candidate("consolidated")], EXPECTED_PERIOD)
    assert located["status"] == "located"
    conflict = _outcome(
        "balance_sheet", [_candidate("consolidated", period_conflict=True)], EXPECTED_PERIOD
    )
    assert conflict["reason"]["code"] == "period_conflict"
    multiple = _outcome(
        "balance_sheet",
        [_candidate("consolidated"), _candidate("consolidated", page_number=2)],
        EXPECTED_PERIOD,
    )
    assert multiple["status"] == "ambiguous"
    parent = _outcome("balance_sheet", [_candidate("parent")], EXPECTED_PERIOD)
    assert parent["reason"]["code"] == "only_parent_statement_found"
    unknown = _outcome("balance_sheet", [_candidate("unknown")], EXPECTED_PERIOD)
    assert unknown["status"] == "ambiguous"
    missing = _outcome("balance_sheet", [], EXPECTED_PERIOD)
    assert missing["reason"]["code"] == "statement_title_not_found"
