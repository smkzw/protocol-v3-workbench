from __future__ import annotations

from packages.contracts.workbench_contracts import ProtocolSection
from services.api.app.medical_writing import scope_competitor_protocol_evidence


def section(node_id: str, heading: str) -> ProtocolSection:
    return ProtocolSection(
        section_id=f"section_{node_id}",
        document_id="document_test",
        heading=heading,
        template_node_id=node_id,
    )


def test_inclusion_scope_excludes_exclusion_criteria_and_regional_preface():
    text = """5.2 入选标准：有关欧盟国家的特殊要求见附录。

只有当所有下列标准均得到满足时，受试者方可纳入本临床试验：

1. 年龄为18至75周岁。
2. 中强效TCS为欧盟II至IV级、美国I至V级。

5.3 排除标准

1. 既往使用生物制剂或接受NB-UVB、PUVA。
"""
    scoped, scope_id = scope_competitor_protocol_evidence(
        text,
        section("ich_m11_5_2", "入选标准"),
    )

    assert scope_id == "ich_m11_5_2"
    assert scoped.startswith("只有当所有下列标准")
    assert "II至IV级" in scoped
    assert "生物制剂" not in scoped
    assert "NB-UVB" not in scoped
    assert "欧盟国家的特殊要求" not in scoped


def test_primary_objective_scope_returns_only_primary_objective_cell():
    text = """3 试验目的、估计目标及终点

| 研究目的 | 终点指标 |
| 主要目的 | |
| 旨在比较试验药物的4种给药方案与安慰剂的疗效。 | 第16周EASI变化百分比。 |
| 次要目的 | |
| 比较试验药物与安慰剂的安全性。 | TEAE。 |
"""
    scoped, scope_id = scope_competitor_protocol_evidence(
        text,
        section("ich_m11_3_1_1", "主要目的"),
    )

    assert scope_id == "ich_m11_3_1_1"
    assert scoped == "旨在比较试验药物的4种给药方案与安慰剂的疗效。"
    assert "第16周" not in scoped
    assert "安全性" not in scoped


def test_unknown_section_keeps_full_approved_text():
    text = "8.1 安全性评估\n记录所有治疗期间出现的不良事件。"
    scoped, scope_id = scope_competitor_protocol_evidence(
        text,
        section("ich_m11_8_1", "安全性评估"),
    )

    assert scope_id == ""
    assert scoped == text
