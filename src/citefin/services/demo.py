"""Immutable synthetic demo projection for the public product experience."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from io import BytesIO
from typing import Any

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

DEMO_SOURCE_ID = "demo_g001_annual_report"


def _snapshot_hash(dataset: dict[str, Any]) -> str:
    payload = json.dumps(dataset, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _demo_visualization(
    chart_key: str,
    chart_type: str,
    title: str,
    question: str,
    dataset: dict[str, Any],
    encoding: dict[str, Any],
    evidence_ids: list[str],
    limitations: list[str],
) -> dict[str, Any]:
    return {
        "visualization_id": f"demo-viz-{chart_key}",
        "chart_key": chart_key,
        "spec_version": "financial-chart-v1",
        "chart_type": chart_type,
        "title": title,
        "question": question,
        "dataset": dataset,
        "encoding": encoding,
        "evidence_ids": evidence_ids,
        "limitations": limitations,
        "data_snapshot_hash": _snapshot_hash(dataset),
        "renderer_version": "echarts-svg-v1",
        "status": "validated",
    }


def get_demo_workspace() -> dict[str, Any]:
    """Return a versioned, database-free view derived from golden case G001."""

    metrics = [
        ("revenue_growth", "营业收入增长率", "增长", "20.0%", 20.0, "同比"),
        ("net_profit_growth", "净利润增长率", "增长", "20.0%", 20.0, "同比"),
        ("gross_margin", "毛利率", "盈利", "35.0%", 35.0, "收入占比"),
        ("net_margin", "净利率", "盈利", "10.0%", 10.0, "收入占比"),
        ("roa", "总资产收益率", "盈利", "8.6%", 8.57, "平均资产"),
        ("roe", "净资产收益率", "盈利", "16.0%", 16.0, "平均权益"),
        ("debt_to_assets", "资产负债率", "偿债", "46.7%", 46.67, "资产占比"),
        ("current_ratio", "流动比率", "偿债", "1.71×", 1.71, "倍"),
        ("quick_ratio", "速动比率", "偿债", "1.20×", 1.2, "倍"),
        ("interest_coverage", "利息保障倍数", "偿债", "7.20×", 7.2, "倍"),
        ("cash_to_short_debt", "现金短债比", "偿债", "1.10×", 1.1, "倍"),
        ("ocf_to_net_profit", "经营现金流 / 净利润", "现金流", "1.25×", 1.25, "倍"),
        ("free_cash_flow", "自由现金流", "现金流", "0.90 亿元", 0.9, "亿元"),
        ("accounts_receivable_growth", "应收账款增长率", "经营质量", "33.3%", 33.33, "同比"),
        ("inventory_growth", "存货增长率", "经营质量", "20.0%", 20.0, "同比"),
    ]
    metric_items = [
        {
            "code": code,
            "label": label,
            "category": category,
            "display_value": display_value,
            "chart_value": chart_value,
            "unit_label": unit_label,
            "status": "calculated",
        }
        for code, label, category, display_value, chart_value, unit_label in metrics
    ]
    growth_rows = [
        {
            "label": label,
            "value": f"{chart_value / 100:g}",
            "metric_id": f"demo-metric-{code}",
            "period_end": "2025-12-31",
        }
        for code, label, _category, _display, chart_value, _unit in metrics
        if code in {"revenue_growth", "net_profit_growth", "gross_margin", "net_margin", "roe"}
    ]
    visualizations = [
        _demo_visualization(
            "growth_profitability",
            "bar",
            "增长与盈利指标",
            "本报告期的增长与盈利指标处于什么水平？",
            {
                "dimensions": ["label", "period_end"],
                "measures": ["value"],
                "rows": growth_rows,
                "source_refs": [
                    {"entity_type": "metric", "entity_id": row["metric_id"]} for row in growth_rows
                ],
            },
            {
                "x_field": "label",
                "y_field": "value",
                "series_field": None,
                "unit": "ratio",
                "value_format": "percent",
                "display_scale": "1",
            },
            ["demo-claim-growth"],
            [],
        ),
        _demo_visualization(
            "cash_profit_quality",
            "grouped_bar",
            "净利润与经营现金流对比",
            "经营现金流是否覆盖净利润？",
            {
                "dimensions": ["period_end", "measure"],
                "measures": ["value"],
                "rows": [
                    {
                        "period_end": "2025-12-31",
                        "measure": "净利润",
                        "value": "120000000",
                        "fact_id": "demo-fact-net-profit",
                    },
                    {
                        "period_end": "2025-12-31",
                        "measure": "经营现金流",
                        "value": "150000000",
                        "fact_id": "demo-fact-operating-cash-flow",
                    },
                ],
                "source_refs": [
                    {
                        "entity_type": "fact",
                        "entity_id": "demo-fact-net-profit",
                        "source_id": DEMO_SOURCE_ID,
                        "page_number": 2,
                    },
                    {
                        "entity_type": "fact",
                        "entity_id": "demo-fact-operating-cash-flow",
                        "source_id": DEMO_SOURCE_ID,
                        "page_number": 3,
                    },
                ],
            },
            {
                "x_field": "period_end",
                "y_field": "value",
                "series_field": "measure",
                "unit": "CNY",
                "value_format": "currency_100m",
                "display_scale": "100000000",
            },
            ["demo-claim-cashflow"],
            [],
        ),
        _demo_visualization(
            "risk_distribution",
            "bar",
            "风险发现分布",
            "当前证据支持的风险发现按严重程度如何分布？",
            {
                "dimensions": ["severity"],
                "measures": ["value"],
                "rows": [
                    {
                        "severity": "观察",
                        "value": "1",
                        "risk_ids": ["demo-risk-receivables"],
                    }
                ],
                "source_refs": [{"entity_type": "risk", "entity_id": "demo-risk-receivables"}],
            },
            {
                "x_field": "severity",
                "y_field": "value",
                "series_field": None,
                "unit": "count",
                "value_format": "integer",
                "display_scale": "1",
            },
            ["demo-claim-receivables"],
            ["风险数量反映规则命中，不代表发生概率或投资评级。"],
        ),
    ]
    return {
        "schema_version": "public-demo-v1",
        "case_id": "G001_standard_profitable",
        "synthetic": True,
        "notice": "以下内容来自合成黄金案例，仅用于展示产品能力，不代表真实公司或真实年报准确率。",
        "company": {
            "name": "华岳制造股份有限公司",
            "security_code": "600001",
            "report_period_end": "2025-12-31",
            "status": "synthetic_verified",
        },
        "summary": {
            "headline": "收入与利润同步增长，现金流覆盖盈利，整体偿债结构保持稳健。",
            "revenue": "12.00 亿元",
            "net_profit": "1.20 亿元",
            "operating_cash_flow": "1.50 亿元",
            "total_assets": "15.00 亿元",
            "high_risk_count": 0,
            "evidence_coverage": "100%",
        },
        "metrics": metric_items,
        "visualizations": visualizations,
        "risks": [
            {
                "severity": "watch",
                "title": "应收账款增速高于收入增速",
                "description": "应收账款同比增长 33.3%，高于营业收入 20.0% 的增幅，建议持续观察回款质量。",  # noqa: E501
                "basis": "应收账款增长率 33.3%；营业收入增长率 20.0%",
                "limitations": ["单年度合成数据不能代表长期趋势", "未触发高等级确定性风险规则"],
                "evidence_claim_id": "demo-claim-receivables",
            }
        ],
        "claims": [
            {
                "claim_id": "demo-claim-growth",
                "type": "calculation",
                "text": "2025 年营业收入与净利润均同比增长 20%。",
                "evidence": [
                    {
                        "page": 2,
                        "section": "合并利润表",
                        "snippet": "营业收入 1,200,000；净利润 120,000（千元）",
                    }
                ],
            },
            {
                "claim_id": "demo-claim-cashflow",
                "type": "inference",
                "text": "经营现金流覆盖净利润，经营现金流 / 净利润为 1.25。",
                "evidence": [
                    {
                        "page": 3,
                        "section": "合并现金流量表",
                        "snippet": "经营活动产生的现金流量净额 150,000（千元）",
                    }
                ],
            },
            {
                "claim_id": "demo-claim-assets",
                "type": "fact",
                "text": "2025 年末资产总额为 15 亿元。",
                "evidence": [
                    {
                        "page": 1,
                        "section": "合并资产负债表",
                        "snippet": "资产总计 1,500,000（千元）",
                    }
                ],
            },
            {
                "claim_id": "demo-claim-receivables",
                "type": "limitation",
                "text": "应收账款增速高于收入增速，需要持续观察回款质量。",
                "evidence": [
                    {
                        "page": 1,
                        "section": "合并资产负债表",
                        "snippet": "应收账款：2025 年 240,000；2024 年 180,000（千元）",
                    }
                ],
            },
        ],
        "report": {
            "sections": [
                {
                    "title": "核心结论",
                    "paragraphs": [
                        "公司在合成报告期内实现收入与利润同步增长，盈利能力稳定。",
                        "经营现金流高于净利润，现金实现质量良好。",
                    ],
                },
                {
                    "title": "盈利与增长",
                    "paragraphs": [
                        "营业收入为 12 亿元，同比增长 20%；净利润为 1.2 亿元，"
                        "同比增长 20%。毛利率 35%，净利率 10%。"
                    ],
                },
                {
                    "title": "偿债与现金流",
                    "paragraphs": [
                        "资产负债率 46.7%，流动比率 1.71，现金短债比 1.10。自由现金流为 0.9 亿元。"
                    ],
                },
                {
                    "title": "限制与风险提示",
                    "paragraphs": [
                        "应收账款增速快于收入，需结合账龄和回款情况进一步判断。本报告为合成案例，不构成投资建议。"
                    ],
                },
            ]
        },
        "evidence_document": {
            "source_id": DEMO_SOURCE_ID,
            "file_name": "G001_合成年度报告.pdf",
            "page_count": 3,
            "content_url": f"/api/v1/demo/evidence/{DEMO_SOURCE_ID}/content",
        },
        "audit": {
            "facts": 23,
            "metrics": 15,
            "major_claim_evidence_coverage": "100%",
            "evaluator": "合成黄金门禁通过",
            "goal_gate": "仅合成案例已验证",
        },
    }


@lru_cache(maxsize=1)
def get_demo_pdf() -> bytes:
    """Build a deterministic searchable three-page PDF used only by the demo."""

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
        "G001 Synthetic Consolidated Balance Sheet - page 1",
        "G001 Synthetic Consolidated Income Statement - page 2",
        "G001 Synthetic Consolidated Cash Flow Statement - page 3",
    )
    for title in titles:
        page = writer.add_blank_page(width=595, height=842)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 760 Td ({title}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
