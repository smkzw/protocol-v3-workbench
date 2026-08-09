from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from packages.contracts.workbench_contracts import (
    RiskCase,
    RiskSeverity,
    RiskStatus,
)
from services.api.app.medical_risk_repository import MedicalRiskRepository
from services.api.app.monitoring_ai_risk_packet import (
    MonitoringAiRiskPacketResolver,
)


class _FakeAdapter:
    def __init__(self) -> None:
        self.current_source_revision = "source-revision-1"
        self.fragments = {
            "docx:paragraph:42": {
                "source_type": "protocol",
                "locator_kind": "paragraph",
                "locator": "docx:paragraph:42",
                "display_locator": "方案段落 43",
                "text": "随机前应停用方案规定的禁用药物。",
                "primary_summary": "方案原文：随机前应停用方案规定的禁用药物。",
                "fields": [],
            },
            "listing:demo.xlsx:sheet:CM:row:3": {
                "source_type": "listing",
                "locator_kind": "sheet_row",
                "locator": "listing:demo.xlsx:sheet:CM:row:3",
                "display_locator": "CM · 第 3 条解析数据记录",
                "text": "",
                "primary_summary": (
                    "2026-06-01 非试验用合并用药 布洛芬 200mg QD"
                ),
                "fields": [
                    {"field": "USUBJID", "value": "S01003"},
                    {"field": "SITEID", "value": "S01"},
                    {"field": "CMTRT", "value": "布洛芬"},
                    {"field": "CMDOSE", "value": "200"},
                ],
            },
        }

    def source_revision(self) -> str:
        return self.current_source_revision

    def risk_profile_revision(self) -> str:
        return "rule-profile-v1"

    def risk_engine_version(self) -> str:
        return "risk-engine-v1"

    def resolve_source_fragment(self, locator: str):
        return self.fragments[locator]


class _FakeRegistry:
    def __init__(self, adapter: _FakeAdapter) -> None:
        self.adapter = adapter

    def get(self, project_id: str):
        if project_id != "project-alpha":
            raise KeyError(project_id)
        return self.adapter


def _repository(tmp_path: Path) -> MedicalRiskRepository:
    repository = MedicalRiskRepository(tmp_path / "risks.sqlite3")
    repository.save_snapshot(
        project_id="project-alpha",
        source_revision="source-revision-1",
        rule_profile_revision="rule-profile-v1",
        engine_version="risk-engine-v1",
        evaluated_subject_count=1,
        risks=[
            RiskCase(
                risk_id="risk-1",
                risk_key="risk-key-1",
                risk_instance_id="risk-instance-1",
                project_id="project-alpha",
                module="medical_monitoring",
                risk_type="prohibited_medication",
                primary_category="用药依从性",
                title="S01003 禁用药使用线索",
                subject_id="S01003",
                site_id="S01",
                scope_type="subject",
                scope_id="S01003",
                severity=RiskSeverity.HIGH,
                status=RiskStatus.ACTION_REQUIRED,
                source_revision="source-revision-1",
                rule_profile_revision="rule-profile-v1",
                engine_version="risk-engine-v1",
                rule_id="RULE-CM-001",
                evidence_span_ids=[
                    "docx:paragraph:42",
                    "listing:demo.xlsx:sheet:CM:row:3",
                ],
                rationale="原始合并用药记录与方案禁用药条款存在时间重叠。",
                recommended_action="核对适应证、实际使用时间和方案例外。",
                created_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
            )
        ],
    )
    return repository


def test_risk_packet_is_current_ordered_redacted_and_stable(
    tmp_path: Path,
) -> None:
    adapter = _FakeAdapter()
    resolver = MonitoringAiRiskPacketResolver(
        _repository(tmp_path),
        _FakeRegistry(adapter),
    )

    first = resolver.resolve("project-alpha", "risk-instance-1")
    second = resolver.resolve("project-alpha", "risk-instance-1")

    assert first == second
    assert first.input_revision.risk_snapshot_revision.startswith("risksnap_")
    assert first.input_revision.rule_pack_revision == "rule-profile-v1"
    assert len(first.input_revision.sources) == 1
    assert [item["raw_fields"]["evidence_kind"] for item in first.evidence_packet] == [
        "original_data",
        "protocol_basis",
        "system_rule",
    ]
    listing_fields = first.evidence_packet[0]["raw_fields"]["fields"]
    assert {"field": "USUBJID", "value": "<subject-ref>"} in listing_fields
    assert {"field": "SITEID", "value": "<site-ref>"} in listing_fields
    assert {"field": "CMTRT", "value": "布洛芬"} in listing_fields
    assert first.risk_context["title"].startswith("<subject-ref>")
    assert first.evidence_packet[-1]["raw_fields"]["risk_title"].startswith(
        "<subject-ref>"
    )
    serialized = str(first)
    assert "S01003" not in serialized
    assert "S01" not in serialized


def test_risk_packet_rejects_stale_snapshot_and_unknown_instance(
    tmp_path: Path,
) -> None:
    adapter = _FakeAdapter()
    resolver = MonitoringAiRiskPacketResolver(
        _repository(tmp_path),
        _FakeRegistry(adapter),
    )

    with pytest.raises(KeyError, match="unavailable"):
        resolver.resolve("project-alpha", "missing-risk")

    adapter.current_source_revision = "source-revision-2"
    with pytest.raises(ValueError, match="stale"):
        resolver.resolve("project-alpha", "risk-instance-1")
