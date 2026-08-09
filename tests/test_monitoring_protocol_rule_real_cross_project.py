from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from services.api.app.eligibility_protocol_rules import (
    EligibilityProtocolProjectConfig,
    EligibilityProtocolRuleService,
)
from services.api.app.monitoring_protocol_rule_repository import (
    MonitoringProtocolRuleRepository,
)
from services.api.app.monitoring_protocol_rule_service import (
    MonitoringProtocolRuleService,
)
from services.api.app.monitoring_protocol_rules import (
    MonitoringRuleDefinition,
    ProtocolFact,
    ProtocolSourceVersion,
)


REAL_PROTOCOLS = (
    (
        "proj_rux_03_002",
        "RUX-03-002",
        "V1.3",
        "2024-08-14",
        Path(
            "/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/CFDI Inspection/"
            "RUX-03-002-自查文件包-20260107/10-临床试验重要文件/1-临床试验方案/"
            "V1.3版-2024.8.14/磷酸芦可替尼乳膏-AD3期临床研究方案V1.3-clean-20240814.docx"
        ),
    ),
    (
        "proj_my009_uc",
        "MY009-UC-2-01",
        "V3.0",
        "2025-09-26",
        Path(
            "/Users/smkzw/Documents/朗来项目资料/MY009治疗UC/方案及配套资料/3.0/"
            "MY009-UC-Ⅱa期-临床研究方案-V3.0 20250926-clean (1).docx"
        ),
    ),
    (
        "proj_d001",
        "CMS-D001",
        "V1.0",
        "2025-12-21",
        Path(
            "/Users/smkzw/Documents/康哲项目资料/AI/入排/test-D001项目/"
            "CMS-D001 银屑病2、3期临床方案 v1.0-2025.12.21.docx"
        ),
    ),
)


@pytest.mark.skipif(
    not all(path.exists() for *_, path in REAL_PROTOCOLS),
    reason="three real project protocols are required",
)
def test_generic_eligibility_continuity_rule_uses_three_real_protocols_without_project_thresholds(
    tmp_path: Path,
) -> None:
    configs = [
        EligibilityProtocolProjectConfig(
            project_id=project_id,
            aliases=(),
            protocol_path=path,
            source_entry=f"{project_id}_source",
            source_version=f"{version_label} / {version_date}",
        )
        for project_id, _, version_label, version_date, path in REAL_PROTOCOLS
    ]
    eligibility = EligibilityProtocolRuleService(configs)
    monitoring = MonitoringProtocolRuleService(
        MonitoringProtocolRuleRepository(tmp_path / "rules.sqlite3")
    )
    observed_source_texts: set[str] = set()

    for project_id, protocol_code, version_label, version_date, path in REAL_PROTOCOLS:
        content = path.read_bytes()
        version = ProtocolSourceVersion.create(
            project_id=project_id,
            protocol_code=protocol_code,
            version_label=version_label,
            version_date=version_date,
            source_entry_id=f"{project_id}_source",
            source_title=f"{protocol_code} 研究方案",
            content_sha256=sha256(content).hexdigest(),
        )
        extracted = eligibility.rules_for_project(project_id)
        criterion = extracted.inclusion.rules[0]
        fact = ProtocolFact.create(
            project_id=project_id,
            protocol_version_id=version.protocol_version_id,
            fact_key="eligibility.inclusion.in_01",
            fact_type="eligibility_inclusion",
            status="medically_confirmed",
            title="入选标准持续符合性",
            normalized_payload={
                "criterion_label": criterion.source_rule_label
                or criterion.review_rule_id,
                "criterion_text": criterion.text,
            },
            source_entry_id=version.source_entry_id,
            source_locator=criterion.source_locator,
            source_text=criterion.text,
        )
        rule = MonitoringRuleDefinition.create(
            project_id=project_id,
            protocol_version_id=version.protocol_version_id,
            rule_key="eligibility.continuity.in_01",
            rule_family="eligibility_continuity",
            status="enabled",
            title="入选标准持续符合性需复核",
            executor="field_predicate",
            required_domains=["DM"],
            preconditions={"exists": {"field": "SUBJID"}},
            trigger_expression={
                "eq": {
                    "field": "ELIGIBILITY_CONTINUITY_STATUS",
                    "value": "not_met",
                }
            },
            exclusions={"exists": {"field": "__RULE_EXCLUDED__"}},
            severity="high",
            confidence="deterministic",
            evidence_template="{SUBJID} 当前持续符合性：{ELIGIBILITY_CONTINUITY_STATUS}",
            fact_revision_ids=[fact.fact_revision_id],
            source_entry_id=fact.source_entry_id,
            source_locator=fact.source_locator,
            source_text=fact.source_text,
        )
        result = monitoring.evaluate_record(
            rule,
            {
                "SUBJID": "S01003",
                "ELIGIBILITY_CONTINUITY_STATUS": "not_met",
                "__source_locator__": (
                    f"listing:{project_id}:eligibility_continuity:row:1"
                ),
            },
            observed_domains=["DM"],
        )

        assert result.matched is True
        assert result.protocol_source["source_text"] == criterion.text
        assert result.rule_key == "eligibility.continuity.in_01"
        observed_source_texts.add(criterion.text)

    assert len(observed_source_texts) == 3
