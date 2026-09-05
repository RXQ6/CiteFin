"""Focused tests for F003 coordinate transforms and table candidates."""

import pytest

from citefin.services.document_parsing import _table_regions, _transformed_origin


def test_transformed_origin_applies_pdf_current_transformation_matrix() -> None:
    assert _transformed_origin(
        [1, 0, 0, 1, 10, 20],
        [1, 0, 0, 1, 3, 4],
    ) == (13.0, 24.0)

    with pytest.raises(ValueError, match="matrix is incomplete"):
        _transformed_origin([1, 0], [1, 0, 0, 1, 3, 4])


def test_table_regions_require_repeated_label_value_rows() -> None:
    assert _table_regions([]) == []
    assert (
        _table_regions(
            [
                {"block_id": "text_1", "text": "Annual report", "bbox": [10, 90, 80, 100]},
                {"block_id": "text_2", "text": "Narrative only", "bbox": [10, 70, 80, 80]},
            ]
        )
        == []
    )

    regions = _table_regions(
        [
            {"block_id": "text_1", "text": "Revenue", "bbox": [10, 90, 60, 100]},
            {"block_id": "text_2", "text": "100", "bbox": [200, 90, 230, 100]},
            {"block_id": "text_3", "text": "Cost", "bbox": [10, 70, 50, 80]},
            {"block_id": "text_4", "text": "60", "bbox": [200, 70, 220, 80]},
        ]
    )

    assert regions[0]["row_count"] == 2
    assert regions[0]["column_count"] == 2
    assert regions[0]["block_ids"] == [["text_1", "text_2"], ["text_3", "text_4"]]
