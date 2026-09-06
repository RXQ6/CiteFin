"""Contract tests for the authoritative product feature catalog."""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[2]

EXPECTED_FEATURES = {
    "F001": ("项目初始化与健康检查", []),
    "F002": ("财报上传与文件存储", ["F001"]),
    "F003": ("PDF文本与表格解析", ["F002"]),
    "F004": ("三张财务报表识别", ["F003"]),
    "F005": ("财务字段标准化", ["F004"]),
    "F006": ("核心金融指标计算", ["F005"]),
    "F007": ("Evidence数据模型", ["F003"]),
    "F008": ("LangGraph运行状态", ["F001"]),
    "F009": ("财务分析节点", ["F006", "F008"]),
    "F010": ("风险识别节点", ["F006", "F008"]),
    "F011": ("报告生成", ["F007", "F009", "F010"]),
    "F012": ("独立Evaluator", ["F011"]),
    "F013": ("Goal Gate", ["F012"]),
    "F014": ("Checkpoint恢复", ["F008"]),
    "F015": ("运行进度接口", ["F008"]),
    "F016": ("最小前端", ["F002", "F015"]),
    "F017": ("证据查看界面", ["F007", "F016"]),
    "F018": ("端到端验收", ["F013", "F014", "F017"]),
}


def test_feature_catalog_matches_authoritative_product_plan() -> None:
    catalog = json.loads((PROJECT_ROOT / "FEATURES.json").read_text(encoding="utf-8"))
    features = catalog["features"]

    actual = {feature["id"]: (feature["title"], feature["blocked_by"]) for feature in features}

    assert actual == EXPECTED_FEATURES
    assert [feature["id"] for feature in features if feature["status"] == "verified"] == [
        "F001",
        "F002",
        "F003",
    ]
    in_progress = [feature for feature in features if feature["status"] == "in_progress"]
    assert len(in_progress) <= 1
    if in_progress:
        assert in_progress[0]["id"] == "F004"
        assert in_progress[0]["owner"] == "codex"
    candidate_complete = [
        feature for feature in features if feature["status"] == "candidate_complete"
    ]
    assert len(candidate_complete) <= 1
    if candidate_complete:
        assert candidate_complete[0]["id"] == "F004"
        assert candidate_complete[0]["owner"] == "codex"


def test_feature_catalog_dependencies_and_evidence_are_well_formed() -> None:
    catalog = json.loads((PROJECT_ROOT / "FEATURES.json").read_text(encoding="utf-8"))
    features = catalog["features"]
    known_ids = {feature["id"] for feature in features}

    for feature in features:
        assert set(feature["blocked_by"]) <= known_ids
        assert feature["verification"]["command"] == (
            f"make verify-feature FEATURE={feature['id']}"
        )
        if feature["status"] == "verified":
            assert feature["verification"]["evidence"]
