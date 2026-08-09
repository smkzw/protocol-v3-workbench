from __future__ import annotations

import csv
from datetime import datetime, timezone
from io import BytesIO, StringIO
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from zipfile import ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from packages.contracts.workbench_contracts import (
    RiskCase,
    RiskSeverity,
    RiskStatus,
)
from packages.contracts.workbench_contracts.models import (
    RiskEvidenceFragmentSnapshot,
)
from services.api.app.medical_monitoring_router import (
    create_medical_monitoring_router,
)
from services.api.app.medical_risk_repository import MedicalRiskRepository


PROJECT_ID = "proj_export_test"
NOW = datetime(2026, 7, 30, tzinfo=timezone.utc)


class _ManifestService:
    def canonical_project_id(self, project_id: str) -> str:
        if project_id in {PROJECT_ID, "project-alias"}:
            return PROJECT_ID
        raise KeyError(project_id)

    def module_binding(self, project_id: str, module: str):
        if project_id != PROJECT_ID or module != "medical_monitoring":
            raise KeyError((project_id, module))
        return SimpleNamespace(
            route_project_id=PROJECT_ID,
            implementation_status="available",
            primary_source_ids=["listing"],
            supplemental_source_ids=["protocol"],
            display_batch_label="2026-07-30 EDC Listing",
            display_extract_date="2026-07-30",
        )


def _risk(
    suffix: str,
    *,
    subject_id: str,
    severity: RiskSeverity,
    category: str,
    title: str,
    evidence_snapshots: list[RiskEvidenceFragmentSnapshot] | None = None,
) -> RiskCase:
    source_domain = {
        "ae_missing_report": "AE",
        "study_treatment_adherence": "EX",
    }.get(category, "")
    tags = [f"source_domain:{source_domain.lower()}"] if source_domain else []
    if category == "ae_missing_report":
        tags.append("safety_pv")
    return RiskCase(
        risk_id=f"risk_{suffix}",
        risk_key=f"riskkey_{suffix}",
        risk_instance_id=f"riskinst_{suffix}",
        project_id=PROJECT_ID,
        module="medical_monitoring",
        risk_type=category,
        primary_category=category,
        tags=tags,
        title=title,
        subject_id=subject_id,
        site_id=subject_id[1:3],
        severity=severity,
        status=RiskStatus.IN_REVIEW,
        source_batch_id="batch_export",
        source_revision="source_export_v1",
        rule_profile_revision="rules_export_v1",
        engine_version="engine_export_v1",
        rule_id=f"RULE_{suffix}",
        evidence_span_ids=[item.locator for item in evidence_snapshots or []],
        evidence_snapshots=evidence_snapshots or [],
        rationale=f"{title}的确定性规则命中理由。",
        recommended_action="核对原始事实后完成医学处置。",
        created_at=NOW,
    )


def _snapshot(
    locator: str,
    fragment: dict,
) -> RiskEvidenceFragmentSnapshot:
    return RiskEvidenceFragmentSnapshot(
        locator=locator,
        source_revision="source_export_v1",
        captured_at=NOW,
        fragment=fragment,
    )


def _app(repository: MedicalRiskRepository) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_medical_monitoring_router(
            risk_repository=repository,
            project_source_manifest_service=_ManifestService(),
            require_server_principal=False,
        )
    )
    return TestClient(app)


def _row_counts(db_path: Path) -> tuple[int, int]:
    with sqlite3.connect(db_path) as connection:
        snapshots = connection.execute(
            "SELECT COUNT(*) FROM medical_risk_snapshots"
        ).fetchone()[0]
        instances = connection.execute(
            "SELECT COUNT(*) FROM medical_risk_instances"
        ).fetchone()[0]
    return snapshots, instances


def _csv_rows(payload: bytes) -> tuple[list[str], list[dict[str, str]]]:
    text = payload.decode("utf-8-sig")
    reader = csv.DictReader(StringIO(text))
    return list(reader.fieldnames or []), list(reader)


@pytest.mark.parametrize("value", ["true", "false", 1, 0, None])
def test_evidence_snapshot_available_rejects_non_boolean_values(value) -> None:
    with pytest.raises(ValueError):
        RiskEvidenceFragmentSnapshot(
            locator="listing:source:sheet:AE:row:1",
            source_revision="source_export_v1",
            captured_at=NOW,
            available=value,
        )


def test_filtered_export_contains_exact_checklist_columns_and_readable_evidence() -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        listing = _snapshot(
            "listing:AE:row:7",
            {
                "source_type": "listing",
                "display_locator": "AE · 第 7 条解析数据记录",
                "primary_summary": (
                    "2026-07-28 V4D29 ALT 313 U/L，参考范围 7–41 U/L，↑，"
                    "需复核AE漏报风险"
                ),
                "fields": [
                    {"field": "ALT", "value": "313 U/L"},
                    {"field": "job_id", "value": "job_private_001"},
                ],
            },
        )
        protocol = _snapshot(
            "docx:paragraph:88",
            {
                "source_type": "protocol",
                "display_locator": "/Users/example/private/protocol.docx",
                "text": "方案规定ALT超过3×ULN时应复核因果关系并评估暂停给药。",
            },
        )
        repository.save_snapshot(
            project_id=PROJECT_ID,
            source_revision="source_export_v1",
            rule_profile_revision="rules_export_v1",
            engine_version="engine_export_v1",
            evaluated_subject_count=3,
            risks=[
                _risk(
                    "001",
                    subject_id="S001",
                    severity=RiskSeverity.HIGH,
                    category="ae_missing_report",
                    title="ALT异常但AE未记录",
                    evidence_snapshots=[protocol, listing],
                ),
                _risk(
                    "002",
                    subject_id="S002",
                    severity=RiskSeverity.HIGH,
                    category="study_treatment_adherence",
                    title="试验药物依从性需复核",
                ),
                _risk(
                    "003",
                    subject_id="S003",
                    severity=RiskSeverity.LOW,
                    category="data_quality",
                    title="数据字段需核对",
                ),
            ],
        )
        before = _row_counts(repository.db_path)

        response = _app(repository).get(
            (
                f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/"
                "risk-snapshots/current/export"
            ),
            params={
                "severity": "high",
                "sort_by": "subject_id",
                "sort_direction": "asc",
            },
        )

        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("application/zip")
        assert response.headers["x-risk-export-count"] == "2"
        assert _row_counts(repository.db_path) == before
        with ZipFile(BytesIO(response.content)) as archive:
            assert archive.namelist() == [
                "risk-checklist.csv",
                "risk-evidence.csv",
            ]
            checklist_headers, checklist = _csv_rows(
                archive.read("risk-checklist.csv")
            )
            evidence_headers, evidence = _csv_rows(
                archive.read("risk-evidence.csv")
            )

        assert checklist_headers == [
            "受试者编号",
            "中心编号",
            "风险级别",
            "风险类别",
            "具体风险项",
            "当前处置",
            "更新时间",
        ]
        assert [row["受试者编号"] for row in checklist] == ["S001", "S002"]
        assert checklist[0]["风险级别"] == "高"
        assert checklist[0]["风险类别"] == "AE漏报；Safety/PV"
        assert checklist[0]["当前处置"] == "待医学复核"
        assert checklist[0]["更新时间"] == "2026-07-30 08:00:00"
        assert "原始事实或依据" in evidence_headers
        assert "次级定位" in evidence_headers
        first_risk_evidence = [
            row for row in evidence if row["风险清单行号"] == "1"
        ]
        assert [row["证据类型"] for row in first_risk_evidence] == [
            "原始数据",
            "方案依据",
            "系统规则与判断",
        ]
        assert "ALT 313 U/L" in first_risk_evidence[0]["原始事实或依据"]
        assert first_risk_evidence[0]["次级定位"] == "AE · 第 7 条解析数据记录"
        assert "方案规定ALT超过3×ULN" in first_risk_evidence[1]["原始事实或依据"]
        assert "[本地路径已隐藏]" in first_risk_evidence[1]["次级定位"]
        exported_text = "\n".join(
            "|".join(row.values()) for row in [*checklist, *evidence]
        )
        assert "job_private_001" not in exported_text
        assert "riskinst_" not in exported_text
        assert "/Users/" not in exported_text


def test_export_rejects_unknown_query_fields_without_mutation() -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        client = _app(repository)
        before = _row_counts(repository.db_path)

        response = client.get(
            (
                f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/"
                "risk-snapshots/current/export"
            ),
            params={"page_size": 200},
        )

        assert response.status_code == 422
        assert (
            response.json()["detail"]["code"]
            == "unknown_risk_export_query_field"
        )
        assert _row_counts(repository.db_path) == before
