from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from packages.contracts.workbench_contracts import (  # noqa: E402
    AiTaskOutputValidationStatus,
    AiTaskRun,
    AiTaskRunStatus,
    ApprovalAction,
    ApprovalActionRequest,
    ApprovalState,
    MonitoringMedicalJudgments,
    MonitoringRiskDispositionKind,
    RiskCase,
    RuxRiskDispositionAction,
    RuxRiskDispositionActionRequest,
    RuxRiskDispositionRecord,
    SourceRegistryEntry,
    RiskSeverity,
    RiskStatus,
    WorkbenchItem,
    WorkbenchItemAction,
    WorkbenchItemActionRequest,
)
from services.api.app.demo_repository import DemoRepository  # noqa: E402
from services.api.app.medical_risk_repository import MedicalRiskRepository  # noqa: E402
from services.api.app.workbench_inbox import (  # noqa: E402
    RUX_PROJECT_ID,
    RuxRiskDispositionStore,
    WorkbenchInboxService,
    WorkbenchInboxStore,
    _dedupe_items,
)


PROJECT_ID = "proj_mgk10_sar_demo"


class FakeAiRunner:
    def list_runs(self, project_id: str):
        now = datetime(2026, 7, 8, 9, 0, tzinfo=timezone.utc)
        return [
            AiTaskRun(
                run_id="airun_blocked_001",
                project_id=project_id,
                module="evidence_design",
                task_type="picos_design_coach",
                purpose="PICOS design",
                status=AiTaskRunStatus.BLOCKED,
                provider="openai_compatible",
                model_name="not_configured",
                ai_gateway_status="not_configured",
                codex_runtime_dependency=False,
                prompt_version="picos_design_v0_1",
                output_validation_status=AiTaskOutputValidationStatus.BLOCKED,
                error_message="WORKBENCH_AI_BASE_URL is not configured",
                needs_medical_confirmation=True,
                created_at=now,
                updated_at=now,
            )
        ]


class FakePicosWorkflow:
    def workflow(self, project_id: str):
        now = datetime(2026, 7, 8, 9, 5, tzinfo=timezone.utc)
        return SimpleNamespace(
            project_id=project_id,
            package_id="crswnp_competitive_evidence",
            generated_at=now,
            steps=[
                SimpleNamespace(
                    question_id="picos_endpoint",
                    picos_domain="终点",
                    decision_status="待补医学理由",
                    selected_option_id="",
                    writing_target_section="研究目的与终点",
                    audit_trail=[],
                ),
                SimpleNamespace(
                    question_id="picos_population",
                    picos_domain="人群",
                    decision_status="写作候选",
                    selected_option_id="picos_population:option:1",
                    writing_target_section="入排标准",
                    audit_trail=[],
                ),
            ],
        )


class FakeTflHandoff:
    def citation_manifest(self, project_id: str):
        now = datetime(2026, 7, 8, 9, 10, tzinfo=timezone.utc)
        return SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    candidate_id="tfl_citation_001",
                    package_label="RUX-03-002 ADaM/SDTM 与 SAR/TFL交付包",
                    output_display_id="Table 14.3.1 AE Summary",
                    output_id="rux_03_002:tfl:ae_summary",
                    recommended_writing_sections=["安全性结果", "M2.7.4临床安全性总结"],
                    review_record_id="tfl_review_001",
                    review_created_at=now,
                )
            ]
        )


class FakeSafetyHandoff:
    def handoff_candidates(self, project_id: str):
        now = datetime(2026, 7, 8, 9, 12, tzinfo=timezone.utc)
        return SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    candidate_id="safety_handoff_001",
                    signal_id="my009_uc_s1:signal:ae_medical_review",
                    signal_label="AE医学复核",
                    title="AE医学评估一致性待PV确认",
                    severity=RiskSeverity.HIGH,
                    recommended_handoff_sections=["PV协同确认", "DSUR安全更新"],
                    review_record_id="safety_review_001",
                    review_created_at=now,
                )
            ]
        )


class FakeWritingManifest:
    def build_manifest(self, project_id: str):
        now = datetime(2026, 7, 8, 9, 14, tzinfo=timezone.utc)
        return SimpleNamespace(
            generated_at=now,
            packages=[
                SimpleNamespace(
                    package_id="cms_d001_protocol_writing",
                    package_label="CMS-D001研究方案写作资料包",
                    quality_gates=[
                        SimpleNamespace(
                            gate_id="cms_d001_approval_export",
                            status="blocked",
                            detail="富文本导出与医学批准流程仍需确认。",
                        )
                    ],
                )
            ],
        )


class FakeSourceRegistry:
    def __init__(self, entries=None, store=None, raise_on_list=False):
        self._entries = entries or []
        self.store = store
        self.raise_on_list = raise_on_list

    def list_entries(self, project_id: str):
        if self.raise_on_list:
            raise ValueError("corrupt source registry")
        return [entry for entry in self._entries if entry.project_id == project_id]


class FakeEligibilityAdapter:
    def __init__(self):
        self.generated_at = datetime(2026, 7, 8, 9, 20, tzinfo=timezone.utc)
        self.subjects = ["31001", "31002"]

    def eligibility_dataset(self, project_id: str, subject_id=None, phase_id=None):
        selected_subject = subject_id or self.subjects[0]
        selected_phase = phase_id or "baseline_randomization"
        action_item = SimpleNamespace(
            item_id=f"{selected_subject}_{selected_phase}_IN_05_missing_information",
            rule_id="IN-05",
            item_type="missing_information",
            severity=RiskSeverity.MEDIUM,
            title="IN-05 需补充资料",
            detail="历史诊断资料不足。",
            recommended_action="补充中心源文件/报告后复核。",
        )
        candidate = SimpleNamespace(
            source_project_code="MG-K10-SAR-III",
            subject_id=selected_subject,
            missing_information=[action_item],
            medical_confirmation_items=[],
            rule_reviews=[
                SimpleNamespace(
                    rule_id="IN-05",
                    verdict=SimpleNamespace(value="pass_verify"),
                    rationale="需要回看源文件确认诊断持续时间。",
                    criterion_text="诊断持续时间满足入组要求。",
                ),
                SimpleNamespace(
                    rule_id="EX-07",
                    verdict=SimpleNamespace(value="fail"),
                    rationale="筛选期存在排除标准相关风险。",
                    criterion_text="排除活动性感染等情况。",
                ),
            ],
        )
        rows = [SimpleNamespace(subject_id=item) for item in self.subjects]
        return SimpleNamespace(
            active_phase_id="baseline_randomization",
            generated_at=self.generated_at,
            review_phases=[
                SimpleNamespace(phase_id="screening_run_in"),
                SimpleNamespace(phase_id="baseline_randomization"),
            ],
            subject_rows=rows,
            selected_candidate=candidate,
        )


class FakeRuxMonitoringService:
    def __init__(self, source_revision: str = "rux-source-revision-1"):
        self.current_source_revision = source_revision

    def source_revision(self):
        return self.current_source_revision

    def risk_profile_revision(self):
        return "rux-rules-v1"

    def risk_engine_version(self):
        return "rux-engine-v1"

    def subject_ids(self):
        return ["S01017", "S01003", "S03040"]

    def evaluate_subject_risks(self, project_id: str, subject_id: str):
        if subject_id != "S01017":
            return []
        now = datetime(2026, 7, 8, 9, 40, tzinfo=timezone.utc)
        return [
            RiskCase(
                risk_id="rux_s01017_alt_ast_5xuln",
                project_id=project_id,
                module="medical_monitoring",
                risk_type="lab_ae_chain",
                primary_category="safety_lab_abnormality",
                tags=["safety_pv"],
                title="S01017 ALT/AST >5xULN",
                subject_id=subject_id,
                site_id="01",
                severity=RiskSeverity.HIGH,
                status=RiskStatus.ACTION_REQUIRED,
                source_batch_id="rux_listing_20250612",
                rule_id="RUX-LAB-ALT-AST",
                evidence_span_ids=["protocol:table7", "listing:LBCHEM:S01017:ALT"],
                rationale="ALT/AST 连续升高并需要医学复核是否触发AE/停药/方案偏离链路。",
                recommended_action="核对实验室、AE、ECB试验药物变更和中心说明，必要时形成Query草稿。",
                created_at=now,
            )
        ]


class FakeRuxMonitoringServiceWithTerminalRisks(FakeRuxMonitoringService):
    def evaluate_subject_risks(self, project_id: str, subject_id: str):
        active = super().evaluate_subject_risks(project_id, subject_id)
        if not active:
            return []
        source = active[0]
        terminal = []
        for suffix, status in (
            ("resolved", RiskStatus.RESOLVED),
            ("closed", RiskStatus.CLOSED),
            ("superseded", RiskStatus.SUPERSEDED),
        ):
            terminal.append(
                source.model_copy(
                    update={
                        "risk_id": f"rux_s01017_{suffix}",
                        "risk_key": f"riskkey_{suffix}",
                        "risk_instance_id": f"riskinst_{suffix}",
                        "title": f"终态风险-{suffix}",
                        "status": status,
                        "batch_delta": "resolved_by_data" if status == RiskStatus.RESOLVED else "persisting",
                    }
                )
            )
        return [source, *terminal]


class FakeMy009MonitoringAdapter:
    def __init__(self, source_revision: str = "my009-source-revision-1"):
        self.current_source_revision = source_revision

    def source_revision(self):
        return self.current_source_revision

    def risk_profile_revision(self):
        return "my009-rules-v1"

    def risk_engine_version(self):
        return "my009-engine-v1"

    def inbox_subject_ids(self):
        return ["S01003"]

    def evaluate_subject_risks(self, subject_id: str):
        now = datetime(2026, 7, 10, 9, 40, tzinfo=timezone.utc)
        return [
            RiskCase(
                risk_id="my009_s01003_adherence_review",
                project_id="proj_my009_uc",
                module="medical_monitoring",
                risk_type="study_drug_adherence_review",
                primary_category="study_treatment_adherence",
                tags=["source_domain:ex2"],
                title="S01003 试验药物服用记录需核对",
                subject_id=subject_id,
                site_id="1",
                severity=RiskSeverity.HIGH,
                status=RiskStatus.ACTION_REQUIRED,
                source_batch_id="my009_uc_listing_20260408",
                rule_id="MY009-UC-IP-ADHERENCE-001",
                evidence_span_ids=[
                    "listing:MY009-UC-MM-Listing:sheet:EX3:row:2",
                    "docx:paragraph:1609",
                ],
                rationale="原始试验药物服用记录需复核。",
                recommended_action="核对依从性、AE和方案偏离记录。",
                created_at=now,
            )
        ]


class ThrowingProjectionAdapter(FakeRuxMonitoringService):
    def __init__(
        self,
        source_revision: str = "rux-source-revision-1",
        rule_revision: str = "rux-rules-v1",
        engine_version: str = "rux-engine-v1",
    ):
        super().__init__(source_revision=source_revision)
        self._rule_revision = rule_revision
        self._engine_version = engine_version

    def risk_profile_revision(self):
        return self._rule_revision

    def risk_engine_version(self):
        return self._engine_version

    def subject_ids(self):
        raise AssertionError("read-only inbox must not enumerate subjects")

    def inbox_subject_ids(self):
        raise AssertionError("read-only inbox must not enumerate subjects")

    def evaluate_subject_risks(self, *args, **kwargs):
        raise AssertionError("read-only inbox must not evaluate risks")


class WorkbenchInboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime_dir = Path(self.tmp.name) / "runtime"
        self.demo_data_path = Path(self.tmp.name) / "demo_data" / "workbench_demo_v0_1.json"
        self.demo_data_path.parent.mkdir(parents=True, exist_ok=True)
        self.demo_data_path.write_text(
            (PROJECT_ROOT / "demo_data" / "workbench_demo_v0_1.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        repo = DemoRepository(self.demo_data_path)
        self.store = WorkbenchInboxStore(self.runtime_dir / "workbench_inbox_actions.jsonl")
        self.rux_disposition_store = RuxRiskDispositionStore(self.runtime_dir / "rux_risk_disposition_actions.jsonl")
        self._risk_repository_sequence = 0
        now = datetime(2026, 7, 8, 9, 18, tzinfo=timezone.utc)
        source_entries = [
            SourceRegistryEntry(
                entry_id="src_trial_design",
                project_id=PROJECT_ID,
                module="evidence_design",
                source_kind="listing_file",
                public_title="Trial_Design.csv",
                content_hash="hash_trial_design",
                size_bytes=100,
                parser_status="parsed",
                span_count=1,
                metadata={"filename": "Trial_Design.csv"},
                server_path="/Users/should/not/leak/Trial_Design.csv",
                created_at=now,
            ),
            SourceRegistryEntry(
                entry_id="src_trial_design",
                project_id=PROJECT_ID,
                module="evidence_design",
                source_kind="listing_file",
                public_title="Trial_Design.csv",
                content_hash="hash_trial_design",
                size_bytes=100,
                parser_status="parsed",
                span_count=1,
                metadata={"filename": "Trial_Design.csv"},
                server_path="/Users/should/not/leak/Trial_Design.csv",
                created_at=now,
            ),
            SourceRegistryEntry(
                entry_id="src_raw_bundle",
                project_id=PROJECT_ID,
                module="eligibility_review",
                source_kind="raw_subject_bundle_inventory",
                public_title="raw_subject_bundle_demo",
                content_hash="hash_raw_bundle",
                size_bytes=200,
                parser_status="inventory_only",
                span_count=3,
                metadata={"total_files": 4, "needs_ocr_vlm_count": 2},
                server_path="/Users/should/not/leak/raw",
                created_at=now,
            ),
        ]
        self.service = WorkbenchInboxService(
            repo,
            FakeAiRunner(),
            FakePicosWorkflow(),
            FakeTflHandoff(),
            FakeSafetyHandoff(),
            FakeWritingManifest(),
            FakeSourceRegistry(source_entries),
            FakeEligibilityAdapter(),
            self.store,
            rux_disposition_store=self.rux_disposition_store,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _rux_service(self, repo=None, monitoring_service=None):
        monitoring_service = monitoring_service or FakeRuxMonitoringService()
        return WorkbenchInboxService(
            repo or self.service.repo,
            FakeAiRunner(),
            FakePicosWorkflow(),
            FakeTflHandoff(),
            FakeSafetyHandoff(),
            FakeWritingManifest(),
            FakeSourceRegistry(),
            FakeEligibilityAdapter(),
            self.store,
            rux_disposition_store=self.rux_disposition_store,
            rux_monitoring_service=monitoring_service,
            medical_risk_repository=self._snapshot_repository(
                RUX_PROJECT_ID,
                monitoring_service,
            ),
        )

    def _my009_service(
        self,
        repo=None,
        monitoring_service=None,
        *,
        internal_approval_required=True,
    ):
        monitoring_service = monitoring_service or FakeMy009MonitoringAdapter()
        return WorkbenchInboxService(
            repo or self.service.repo,
            FakeAiRunner(),
            FakePicosWorkflow(),
            FakeTflHandoff(),
            FakeSafetyHandoff(),
            FakeWritingManifest(),
            FakeSourceRegistry(),
            FakeEligibilityAdapter(),
            self.store,
            rux_disposition_store=self.rux_disposition_store,
            monitoring_services={"proj_my009_uc": monitoring_service},
            medical_risk_repository=self._snapshot_repository(
                "proj_my009_uc",
                monitoring_service,
            ),
            monitoring_query_workflow_policies={
                "proj_my009_uc": {
                    "internal_approval_required": internal_approval_required,
                    "formal_send_managed_outside_monitoring": True,
                }
            },
        )

    def _snapshot_repository(self, project_id: str, adapter) -> MedicalRiskRepository:
        self._risk_repository_sequence += 1
        repository = MedicalRiskRepository(
            self.runtime_dir / f"medical_risks_{self._risk_repository_sequence}.sqlite3"
        )
        if hasattr(adapter, "inbox_subject_ids"):
            subject_ids = adapter.inbox_subject_ids()
            risk_groups = [
                adapter.evaluate_subject_risks(subject_id)
                for subject_id in subject_ids
            ]
        else:
            subject_ids = adapter.subject_ids()
            risk_groups = [
                adapter.evaluate_subject_risks(project_id, subject_id)
                for subject_id in subject_ids
            ]
        repository.save_snapshot(
            project_id=project_id,
            source_revision=adapter.source_revision(),
            rule_profile_revision=(
                adapter.risk_profile_revision()
                if hasattr(adapter, "risk_profile_revision")
                else ""
            ),
            engine_version=(
                adapter.risk_engine_version()
                if hasattr(adapter, "risk_engine_version")
                else ""
            ),
            evaluated_subject_count=len(subject_ids),
            risks=[risk for group in risk_groups for risk in group],
        )
        return repository

    def _projection_service(
        self,
        adapter,
        medical_risk_repository: MedicalRiskRepository,
    ) -> WorkbenchInboxService:
        return WorkbenchInboxService(
            self.service.repo,
            FakeAiRunner(),
            FakePicosWorkflow(),
            FakeTflHandoff(),
            FakeSafetyHandoff(),
            FakeWritingManifest(),
            FakeSourceRegistry(),
            FakeEligibilityAdapter(),
            self.store,
            rux_disposition_store=self.rux_disposition_store,
            rux_monitoring_service=adapter,
            medical_risk_repository=medical_risk_repository,
        )

    def _submit_rux_internal_approval(self, service):
        target = next(item for item in service.inbox(RUX_PROJECT_ID).items if item.title == "S01017 ALT/AST >5xULN")
        service.apply_rux_risk_disposition(
            RUX_PROJECT_ID,
            target.item_id,
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.REVIEWED,
                medical_judgments=MonitoringMedicalJudgments(review_completed=True),
                actor="medical_manager",
                comment="已核对ALT/AST、AE与ECB链路。",
                expected_source_version=target.source_version,
            ),
        )
        service.apply_rux_risk_disposition(
            RUX_PROJECT_ID,
            target.item_id,
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.QUERY_DRAFT,
                actor="medical_manager",
                comment="请中心确认ALT/AST升高是否已记录AE，并说明试验药物暂停/恢复依据。",
                query_draft_text="请中心确认ALT/AST升高是否已记录AE，并说明试验药物暂停/恢复依据。",
                expected_source_version=target.source_version,
            ),
        )
        service.apply_rux_risk_disposition(
            RUX_PROJECT_ID,
            target.item_id,
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.SUBMITTED_FOR_APPROVAL,
                actor="medical_manager",
                comment="提交内部Query草稿/处置建议审批，不代表对外Query已执行。",
                expected_source_version=target.source_version,
            ),
        )
        approval_ref = self.rux_disposition_store.records(RUX_PROJECT_ID)[-1].approval_ref
        return target, approval_ref

    def test_inbox_projects_cross_module_work_items_without_forbidden_surface(self):
        inbox = self.service.inbox(PROJECT_ID)
        serialized = json.dumps(inbox.model_dump(mode="json"), ensure_ascii=False)
        item_types = {item.item_type for item in inbox.items}
        modules = {item.module for item in inbox.items}

        self.assertIn("risk", item_types)
        self.assertIn("approval", item_types)
        self.assertIn("ai_review", item_types)
        self.assertIn("picos_decision", item_types)
        self.assertIn("handoff", item_types)
        self.assertIn("quality_gate", item_types)
        self.assertIn("source_ready", item_types)
        self.assertIn("data_health", item_types)
        self.assertIn("eligibility_action", item_types)
        self.assertIn("data_analysis_tfl", modules)
        self.assertIn("safety_pv", modules)
        self.assertIn("evidence_design", modules)
        self.assertIn("medical_writing", modules)
        self.assertIn("eligibility_review", modules)
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn("server_path", serialized)
        self.assertNotIn("hash_trial_design", serialized)
        self.assertNotIn("hash_raw_bundle", serialized)
        self.assertIn("来源重复登记待确认", serialized)
        self.assertIn("来源待解析", serialized)
        self.assertIn("入排审核待补充资料", serialized)
        self.assertIn("入排审核待溯源验证", serialized)
        self.assertIn("入排审核不符合/筛败待确认", serialized)
        self.assertIn("screening_run_in", serialized)
        self.assertIn("baseline_randomization", serialized)
        for forbidden in ("第1环节", "第4环节", "第5环节", "EDC构建", "中心启动", "受试者招募"):
            self.assertNotIn(forbidden, serialized)
        self.assertGreaterEqual(inbox.unread_count, 1)
        self.assertGreaterEqual(inbox.handoff_count, 2)

    def test_limited_inbox_preserves_cross_module_visibility_when_eligibility_dominates(self):
        inbox = self.service.inbox(PROJECT_ID, limit=20)
        item_types = {item.item_type for item in inbox.items}

        self.assertEqual(20, len(inbox.items))
        self.assertGreater(inbox.total_open_count, len(inbox.items))
        self.assertIn("eligibility_action", item_types)
        self.assertIn("source_ready", item_types)
        self.assertIn("data_health", item_types)
        self.assertIn("handoff", item_types)

    def test_dedupe_items_preserves_duplicate_ids_with_stable_suffix(self):
        now = datetime(2026, 7, 8, 9, 30, tzinfo=timezone.utc)
        base = {
            "item_id": "risk:duplicate",
            "project_id": PROJECT_ID,
            "module": "medical_monitoring",
            "module_label": "医学监查",
            "item_type": "risk",
            "source_type": "risk_case",
            "source_id": "risk_a",
            "title": "重复风险 A",
            "summary": "同一 item_id 的第一条风险。",
            "priority": "high",
            "status": "action_required",
            "source_version": "v1",
            "updated_at": now,
        }
        duplicate = WorkbenchItem(**{**base, "source_id": "risk_b", "title": "重复风险 B"})
        original = WorkbenchItem(**base)

        with self.assertLogs("services.api.app.workbench_inbox", level="WARNING") as logs:
            items = _dedupe_items([original, duplicate])

        self.assertEqual(2, len(items))
        self.assertEqual("risk:duplicate", items[0].item_id)
        self.assertEqual("risk:duplicate#dup2", items[1].item_id)
        self.assertEqual("risk_b", items[1].source_id)
        self.assertIn("duplicate workbench inbox item_id", logs.output[0])

    def test_mark_read_persists_without_deleting_item(self):
        before = self.service.inbox(PROJECT_ID)
        target = next(item for item in before.items if item.unread)
        after = self.service.apply_action(
            PROJECT_ID,
            target.item_id,
            WorkbenchItemActionRequest(action=WorkbenchItemAction.MARK_READ, actor="medical_manager", comment="opened", expected_source_version=target.source_version),
        )
        same_item = next(item for item in after.items if item.item_id == target.item_id)

        self.assertFalse(same_item.unread)
        self.assertEqual(before.total_open_count, after.total_open_count)
        records = self.store.records(PROJECT_ID)
        self.assertEqual(1, len(records))
        self.assertEqual(target.source_version, records[0].source_version)

    def test_mark_read_rejects_stale_source_version_without_mutating_read_state(self):
        before = self.service.inbox(PROJECT_ID)
        target = next(item for item in before.items if item.unread)

        with self.assertRaisesRegex(ValueError, "stale_source"):
            self.service.apply_action(
                PROJECT_ID,
                target.item_id,
                WorkbenchItemActionRequest(
                    action=WorkbenchItemAction.MARK_READ,
                    actor="medical_manager",
                    comment="stale browser tab",
                    expected_source_version="stale-source-version",
                ),
            )

        self.assertEqual([], self.store.records(PROJECT_ID))
        unchanged = next(item for item in self.service.inbox(PROJECT_ID).items if item.item_id == target.item_id)
        self.assertTrue(unchanged.unread)

    def test_real_monitoring_source_revision_invalidates_read_and_disposition_tokens(self):
        adapter = FakeMy009MonitoringAdapter()
        service = self._my009_service(monitoring_service=adapter)
        before = service.inbox("proj_my009_uc")
        target = next(item for item in before.items if item.item_type == "risk")

        adapter.current_source_revision = "my009-source-revision-2"
        current_risks = [
            item
            for item in service.inbox("proj_my009_uc").items
            if item.item_type == "risk"
        ]
        self.assertEqual([], current_risks)
        with self.assertRaises(KeyError):
            service.apply_action(
                "proj_my009_uc",
                target.item_id,
                WorkbenchItemActionRequest(
                    action=WorkbenchItemAction.MARK_READ,
                    actor="medical_manager",
                    comment="stale source revision",
                    expected_source_version=target.source_version,
                ),
            )
        with self.assertRaises(KeyError):
            service.apply_monitoring_risk_disposition(
                "proj_my009_uc",
                target.item_id,
                RuxRiskDispositionActionRequest(
                    action=RuxRiskDispositionAction.REVIEWED,
                    medical_judgments=MonitoringMedicalJudgments(review_completed=True),
                    actor="medical_manager",
                    comment="不得沿用旧来源版本的医学复核。",
                    expected_source_version=target.source_version,
                ),
            )

        self.assertEqual([], self.store.records("proj_my009_uc"))
        self.assertEqual([], self.rux_disposition_store.records("proj_my009_uc"))

    def test_real_monitoring_source_revision_invalidates_pending_internal_approval(self):
        project_id = "proj_my009_uc"
        adapter = FakeMy009MonitoringAdapter()
        service = self._my009_service(monitoring_service=adapter)
        target = next(item for item in service.inbox(project_id).items if item.item_type == "risk")
        reviewed = service.apply_monitoring_risk_disposition(
            project_id,
            target.item_id,
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.REVIEWED,
                medical_judgments=MonitoringMedicalJudgments(review_completed=True),
                actor="medical_manager",
                comment="已完成当前来源版本医学复核。",
                expected_source_version=target.source_version,
            ),
        )
        reviewed_target = next(item for item in reviewed.items if item.item_id == target.item_id)
        drafted = service.apply_monitoring_risk_disposition(
            project_id,
            target.item_id,
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.QUERY_DRAFT,
                actor="medical_manager",
                comment="形成内部Query草稿。",
                query_draft_text="请核对当前来源版本中的试验药物记录。",
                expected_source_version=reviewed_target.source_version,
            ),
        )
        drafted_target = next(item for item in drafted.items if item.item_id == target.item_id)
        service.apply_monitoring_risk_disposition(
            project_id,
            target.item_id,
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.SUBMITTED_FOR_APPROVAL,
                actor="medical_manager",
                comment="提交内部医学批准。",
                expected_source_version=drafted_target.source_version,
            ),
        )
        approval = service.repo.approvals(project_id)[0]
        service.require_current_monitoring_approval_source(project_id, approval.approval_id)

        adapter.current_source_revision = "my009-source-revision-2"
        with self.assertRaisesRegex(ValueError, "stale_source"):
            service.require_current_monitoring_approval_source(project_id, approval.approval_id)

    def test_rux_risk_disposition_state_machine_is_separate_from_read_state(self):
        service = self._rux_service()
        before = service.inbox(RUX_PROJECT_ID)
        target = next(item for item in before.items if item.title == "S01017 ALT/AST >5xULN")

        self.assertEqual("待医学复核", target.status)
        self.assertTrue(target.unread)
        self.assertTrue(target.needs_action)
        self.assertEqual("标记医学复核", target.action_label)

        read_only = service.apply_action(
            RUX_PROJECT_ID,
            target.item_id,
            WorkbenchItemActionRequest(action=WorkbenchItemAction.MARK_READ, actor="medical_manager", comment="opened only", expected_source_version=target.source_version),
        )
        read_item = next(item for item in read_only.items if item.item_id == target.item_id)
        self.assertFalse(read_item.unread)
        self.assertEqual("待医学复核", read_item.status)
        self.assertEqual("标记医学复核", read_item.action_label)

        reviewed = service.apply_rux_risk_disposition(
            RUX_PROJECT_ID,
            target.item_id,
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.REVIEWED,
                medical_judgments=MonitoringMedicalJudgments(review_completed=True),
                actor="medical_manager",
                comment="已核对ALT/AST、AE与ECB链路。",
                expected_source_version=target.source_version,
            ),
        )
        reviewed_item = next(item for item in reviewed.items if item.item_id == target.item_id)
        self.assertEqual("已医学复核", reviewed_item.status)
        self.assertTrue(reviewed_item.medical_judgments.review_completed)
        self.assertEqual("记录Query草稿", reviewed_item.action_label)
        self.assertTrue(reviewed_item.needs_action)
        self.assertFalse(reviewed_item.unread)

        drafted = service.apply_rux_risk_disposition(
            RUX_PROJECT_ID,
            target.item_id,
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.QUERY_DRAFT,
                actor="medical_manager",
                comment="请中心确认ALT/AST升高是否已记录AE，并说明试验药物暂停/恢复依据。",
                query_draft_text="请中心确认ALT/AST升高是否已记录AE，并说明试验药物暂停/恢复依据。",
                expected_source_version=target.source_version,
            ),
        )
        drafted_item = next(item for item in drafted.items if item.item_id == target.item_id)
        self.assertEqual("Query草稿", drafted_item.status)
        self.assertEqual("提交内部审批", drafted_item.action_label)
        self.assertTrue(drafted_item.needs_action)

        submitted = service.apply_rux_risk_disposition(
            RUX_PROJECT_ID,
            target.item_id,
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.SUBMITTED_FOR_APPROVAL,
                actor="medical_manager",
                comment="提交医学经理审批后再发中心Query。",
                expected_source_version=target.source_version,
            ),
        )
        submitted_item = next(item for item in submitted.items if item.item_id == target.item_id)
        self.assertEqual("已提交内部审批", submitted_item.status)
        self.assertEqual("查看内部审批状态", submitted_item.action_label)
        self.assertFalse(submitted_item.needs_action)
        self.assertEqual(before.total_open_count, submitted.total_open_count)
        approvals = service.repo.approvals(RUX_PROJECT_ID)
        self.assertEqual(1, len(approvals))
        approval = approvals[0]
        latest_disposition = self.rux_disposition_store.records(RUX_PROJECT_ID)[-1]
        self.assertEqual(approval.approval_id, latest_disposition.approval_ref)
        self.assertEqual(target.risk_key, latest_disposition.risk_key)
        self.assertEqual(target.risk_instance_id, latest_disposition.risk_instance_id)
        self.assertEqual(target.snapshot_id, latest_disposition.snapshot_id)
        self.assertTrue(approval.approval_id.startswith(f"approval_rux_disposition_{target.source_id}_"))
        self.assertEqual("medical_monitoring_risk_disposition", approval.target_type)
        self.assertEqual(target.source_id, approval.target_id)
        self.assertEqual(ApprovalState.IN_MEDICAL_REVIEW, approval.state)
        self.assertEqual("medical_manager", approval.requested_by)
        self.assertIn("内部Query草稿/处置建议审批", approval.review_comments or "")
        self.assertIn("S01017", approval.review_comments or "")
        self.assertNotIn(target.source_version, approval.review_comments or "")
        self.assertNotIn(target.item_id, approval.review_comments or "")
        self.assertNotIn("已发中心", approval.review_comments or "")
        self.assertNotIn("正式批准", approval.review_comments or "")

        read_actions = [record.action for record in self.store.records(RUX_PROJECT_ID)]
        self.assertEqual(
            [
                WorkbenchItemAction.MARK_READ,
            ],
            read_actions,
        )
        disposition_actions = [record.action for record in self.rux_disposition_store.records(RUX_PROJECT_ID)]
        self.assertEqual(
            [
                RuxRiskDispositionAction.REVIEWED,
                RuxRiskDispositionAction.QUERY_DRAFT,
                RuxRiskDispositionAction.SUBMITTED_FOR_APPROVAL,
            ],
            disposition_actions,
        )
        serialized = json.dumps(submitted.model_dump(mode="json"), ensure_ascii=False)
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn("server_path", serialized)
        self.assertNotIn("content_hash", serialized)
        self.assertNotRegex(serialized, r"第[一二三四五六七八九0-9]+环节|阶段[0-9一二三四五六七八九]|正式批准|自动关闭|已发中心")

    def test_my009_risk_disposition_reuses_the_audited_internal_state_machine(self):
        project_id = "proj_my009_uc"
        service = self._my009_service()
        before = service.inbox(project_id)
        target = before.items[0]

        self.assertEqual("待医学复核", target.status)
        self.assertEqual("monitoring_risk", target.source_type)
        self.assertTrue(any(ref.locator.startswith("listing:") for ref in target.source_refs))
        self.assertTrue(any(ref.locator.startswith("docx:") for ref in target.source_refs))

        reviewed = service.apply_monitoring_risk_disposition(
            project_id,
            target.item_id,
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.REVIEWED,
                medical_judgments=MonitoringMedicalJudgments(review_completed=True),
                actor="medical_manager",
                comment="已核对试验药物服用记录与方案依从性要求。",
                expected_source_version=target.source_version,
            ),
        )
        reviewed_item = next(item for item in reviewed.items if item.item_id == target.item_id)
        self.assertEqual("已医学复核", reviewed_item.status)

        drafted = service.apply_monitoring_risk_disposition(
            project_id,
            target.item_id,
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.QUERY_DRAFT,
                actor="medical_manager",
                comment="请核对漏服记录、依从性计算及PD记录。",
                query_draft_text="请核对漏服记录、依从性计算及PD记录。",
                expected_source_version=target.source_version,
            ),
        )
        drafted_item = next(item for item in drafted.items if item.item_id == target.item_id)
        self.assertEqual("Query草稿", drafted_item.status)

        submitted = service.apply_monitoring_risk_disposition(
            project_id,
            target.item_id,
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.SUBMITTED_FOR_APPROVAL,
                actor="medical_manager",
                comment="提交内部审批，批准后再决定是否对中心发出Query。",
                expected_source_version=target.source_version,
            ),
        )
        submitted_item = next(item for item in submitted.items if item.item_id == target.item_id)
        self.assertEqual("已提交内部审批", submitted_item.status)
        self.assertFalse(submitted_item.needs_action)

        approvals = service.repo.approvals(project_id)
        self.assertEqual(1, len(approvals))
        self.assertTrue(approvals[0].approval_id.startswith("approval_monitoring_disposition_"))
        self.assertIn("MY009-UC内部Query草稿/处置建议审批", approvals[0].review_comments)
        self.assertNotIn("RUX-03-002", approvals[0].review_comments)
        records = self.rux_disposition_store.records(project_id)
        self.assertEqual(
            [
                RuxRiskDispositionAction.REVIEWED,
                RuxRiskDispositionAction.QUERY_DRAFT,
                RuxRiskDispositionAction.SUBMITTED_FOR_APPROVAL,
            ],
            [record.action for record in records],
        )

    def test_project_policy_can_finish_query_draft_without_internal_approval(self):
        project_id = "proj_my009_uc"
        service = self._my009_service(internal_approval_required=False)
        target = next(
            item for item in service.inbox(project_id).items if item.item_type == "risk"
        )
        service.apply_monitoring_risk_disposition(
            project_id,
            target.item_id,
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.REVIEWED,
                medical_judgments=MonitoringMedicalJudgments(review_completed=True),
                actor="medical_manager",
                comment="已完成医学复核。",
                expected_source_version=target.source_version,
            ),
        )
        drafted = service.apply_monitoring_risk_disposition(
            project_id,
            target.item_id,
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.QUERY_DRAFT,
                actor="medical_manager",
                comment="请中心补充原始记录和医学解释。",
                query_draft_text="请中心补充原始记录和医学解释。",
                expected_source_version=target.source_version,
            ),
        )
        drafted_item = next(
            item for item in drafted.items if item.item_id == target.item_id
        )
        self.assertEqual("Query草稿", drafted_item.status)
        self.assertEqual("查看Query草稿", drafted_item.action_label)
        self.assertFalse(drafted_item.needs_action)
        with self.assertRaisesRegex(ValueError, "internal approval is disabled"):
            service.apply_monitoring_risk_disposition(
                project_id,
                target.item_id,
                RuxRiskDispositionActionRequest(
                    action=RuxRiskDispositionAction.SUBMITTED_FOR_APPROVAL,
                    actor="medical_manager",
                    comment="不应进入内部审批。",
                    expected_source_version=target.source_version,
                ),
            )
        self.assertEqual([], service.repo.approvals(project_id))

    def test_rux_non_query_disposition_completes_without_query_or_approval(self):
        service = self._rux_service()
        target = next(item for item in service.inbox(RUX_PROJECT_ID).items if item.item_type == "risk")

        completed = service.apply_rux_risk_disposition(
            RUX_PROJECT_ID,
            target.item_id,
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.REVIEWED,
                disposition_kind=MonitoringRiskDispositionKind.EXPLAINED_NO_EXTERNAL_ACTION,
                medical_judgments=MonitoringMedicalJudgments(review_completed=True),
                actor="medical_manager",
                comment="已核对方案、listing与个例证据，现有解释充分，无需对中心采取外部动作。",
                expected_source_version=target.source_version,
            ),
        )
        completed_item = next(item for item in completed.items if item.item_id == target.item_id)

        self.assertEqual("已说明，无需外部动作", completed_item.status)
        self.assertEqual("查看医学处置记录", completed_item.action_label)
        self.assertFalse(completed_item.needs_action)
        self.assertEqual([], service.repo.approvals(RUX_PROJECT_ID))
        self.assertEqual("explained_no_external_action", self.rux_disposition_store.records(RUX_PROJECT_ID)[-1].new_state)

    def test_terminal_monitoring_disposition_can_be_reopened_with_audited_reason(self):
        service = self._rux_service()
        target = next(
            item for item in service.inbox(RUX_PROJECT_ID).items if item.item_type == "risk"
        )
        service.apply_rux_risk_disposition(
            RUX_PROJECT_ID,
            target.item_id,
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.REVIEWED,
                disposition_kind=MonitoringRiskDispositionKind.EXPLAINED_NO_EXTERNAL_ACTION,
                medical_judgments=MonitoringMedicalJudgments(review_completed=True),
                actor="medical_manager",
                comment="已有解释充分。",
                expected_source_version=target.source_version,
            ),
        )

        reopened = service.apply_rux_risk_disposition(
            RUX_PROJECT_ID,
            target.item_id,
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.REOPEN,
                actor="medical_manager",
                comment="收到新的实验室复测结果，需要重新判断。",
                expected_source_version=target.source_version,
                expected_disposition_state="explained_no_external_action",
            ),
        )

        reopened_item = next(
            item for item in reopened.items if item.item_id == target.item_id
        )
        self.assertEqual("待医学复核", reopened_item.status)
        self.assertTrue(reopened_item.needs_action)
        records = self.rux_disposition_store.records(RUX_PROJECT_ID)
        self.assertEqual(RuxRiskDispositionAction.REOPEN, records[-1].action)
        self.assertEqual("explained_no_external_action", records[-1].previous_state)
        self.assertEqual("pending_review", records[-1].new_state)
        self.assertIsNone(records[-1].medical_judgments)
        self.assertIsNone(records[-1].disposition_kind)
        with self.assertRaisesRegex(ValueError, "only a terminal"):
            service.apply_rux_risk_disposition(
                RUX_PROJECT_ID,
                target.item_id,
                RuxRiskDispositionActionRequest(
                    action=RuxRiskDispositionAction.REOPEN,
                    actor="medical_manager",
                    comment="重复重开。",
                    expected_source_version=target.source_version,
                    expected_disposition_state="pending_review",
                ),
            )

    def test_previous_instance_disposition_can_only_be_used_as_an_audited_reassessment_basis(self):
        service = self._rux_service()
        target = next(
            item for item in service.inbox(RUX_PROJECT_ID).items if item.item_type == "risk"
        )
        historical = RuxRiskDispositionRecord(
            record_id="historical_disposition_001",
            project_id=RUX_PROJECT_ID,
            item_id="rux-risk:riskinst_previous",
            risk_id=target.source_id,
            risk_key=target.risk_key,
            risk_instance_id="riskinst_previous",
            snapshot_id="risksnap_previous",
            subject_id=target.target_id,
            rule_id="RUX-LAB-ALT-AST",
            action=RuxRiskDispositionAction.REVIEWED,
            disposition_kind=MonitoringRiskDispositionKind.EXPLAINED_NO_EXTERNAL_ACTION,
            previous_state="pending_review",
            new_state="explained_no_external_action",
            actor="medical_manager",
            comment="上一批次已有解释，未发起中心Query。",
            source_version="historical-source-version",
            medical_judgments=MonitoringMedicalJudgments(
                review_completed=True,
            ),
            created_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
        )
        self.rux_disposition_store.append(historical)

        service.apply_rux_risk_disposition(
            RUX_PROJECT_ID,
            target.item_id,
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.REVIEWED,
                disposition_kind=MonitoringRiskDispositionKind.EXPLAINED_NO_EXTERNAL_ACTION,
                medical_judgments=MonitoringMedicalJudgments(review_completed=True),
                actor="medical_manager",
                comment="本批次复核后仍有充分解释。",
                expected_source_version=target.source_version,
                basis_disposition_record_id=historical.record_id,
                reassessment_change_reason="本批次新增复测结果，重新核对后结论不变。",
            ),
        )

        committed = self.rux_disposition_store.records(RUX_PROJECT_ID)[-1]
        self.assertEqual(historical.record_id, committed.basis_disposition_record_id)
        self.assertEqual(
            "本批次新增复测结果，重新核对后结论不变。",
            committed.reassessment_change_reason,
        )

        other_risk_basis = historical.model_copy(
            update={
                "record_id": "historical_disposition_other_risk",
                "risk_key": "riskkey_other",
                "risk_instance_id": "riskinst_other",
            }
        )
        self.rux_disposition_store.append(other_risk_basis)
        other_service = self._rux_service(
            monitoring_service=FakeRuxMonitoringService(source_revision="rux-source-revision-2")
        )
        other_target = next(
            item for item in other_service.inbox(RUX_PROJECT_ID).items if item.item_type == "risk"
        )
        with self.assertRaisesRegex(ValueError, "belongs to another risk"):
            other_service.apply_rux_risk_disposition(
                RUX_PROJECT_ID,
                other_target.item_id,
                RuxRiskDispositionActionRequest(
                    action=RuxRiskDispositionAction.REVIEWED,
                    medical_judgments=MonitoringMedicalJudgments(review_completed=True),
                    actor="medical_manager",
                    comment="不应引用另一风险的历史处置。",
                    expected_source_version=other_target.source_version,
                    basis_disposition_record_id=other_risk_basis.record_id,
                    reassessment_change_reason="来源版本发生变化。",
                ),
            )

    def test_my009_safety_pv_collaboration_completes_medical_manager_action(self):
        project_id = "proj_my009_uc"
        adapter = FakeMy009MonitoringAdapter()
        service = self._my009_service(monitoring_service=adapter)
        target = next(item for item in service.inbox(project_id).items if item.item_type == "risk")

        completed = service.apply_monitoring_risk_disposition(
            project_id,
            target.item_id,
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.REVIEWED,
                disposition_kind=MonitoringRiskDispositionKind.SAFETY_PV_COLLABORATION,
                medical_judgments=MonitoringMedicalJudgments(review_completed=True),
                actor="medical_manager",
                comment="已完成医学复核并转Safety/PV协作；不生成中心Query或第二套风险状态。",
                expected_source_version=target.source_version,
            ),
        )
        completed_item = next(item for item in completed.items if item.item_id == target.item_id)

        self.assertEqual("已转Safety/PV协作", completed_item.status)
        self.assertEqual("查看Safety/PV协作记录", completed_item.action_label)
        self.assertFalse(completed_item.needs_action)
        self.assertEqual([], service.repo.approvals(project_id))
        self.assertEqual("safety_pv_collaboration", self.rux_disposition_store.records(project_id)[-1].new_state)

        handoffs = service.safety_monitoring_collaboration_handoffs(project_id)
        self.assertEqual(1, len(handoffs))
        handoff = handoffs[0]
        self.assertTrue(handoff.is_current)
        self.assertEqual(completed_item.risk_key, handoff.risk_key)
        self.assertEqual(completed_item.risk_instance_id, handoff.risk_instance_id)
        self.assertEqual(completed_item.snapshot_id, handoff.snapshot_id)
        self.assertEqual(completed_item.source_version, handoff.source_version)

        adapter.current_source_revision = "my009-source-revision-2"
        stale_handoff = service.safety_monitoring_collaboration_handoffs(project_id)[0]
        self.assertFalse(stale_handoff.is_current)
        self.assertIn("不在当前医学监查快照中", stale_handoff.stale_reason)

    def test_rux_stale_internal_approval_does_not_create_approval_gate(self):
        service = self._rux_service()
        target = next(item for item in service.inbox(RUX_PROJECT_ID).items if item.title == "S01017 ALT/AST >5xULN")

        with self.assertRaisesRegex(ValueError, "stale_source"):
            service.apply_rux_risk_disposition(
                RUX_PROJECT_ID,
                target.item_id,
                RuxRiskDispositionActionRequest(
                    action=RuxRiskDispositionAction.SUBMITTED_FOR_APPROVAL,
                    actor="medical_manager",
                    comment="过期资料不应创建审批。",
                    expected_source_version="stale-source-version",
                ),
            )

        self.assertEqual([], service.repo.approvals(RUX_PROJECT_ID))
        self.assertEqual([], self.rux_disposition_store.records(RUX_PROJECT_ID))

    def test_medical_review_requires_explicit_completed_judgment_snapshot(self):
        service = self._rux_service()
        target = next(item for item in service.inbox(RUX_PROJECT_ID).items if item.title == "S01017 ALT/AST >5xULN")

        with self.assertRaisesRegex(ValueError, "four medical judgments"):
            service.apply_rux_risk_disposition(
                RUX_PROJECT_ID,
                target.item_id,
                RuxRiskDispositionActionRequest(
                    action=RuxRiskDispositionAction.REVIEWED,
                    actor="medical_manager",
                    comment="未完成结构化医学判断，不应进入已复核状态。",
                    expected_source_version=target.source_version,
                ),
            )

        unchanged = next(item for item in service.inbox(RUX_PROJECT_ID).items if item.item_id == target.item_id)
        self.assertEqual("待医学复核", unchanged.status)
        self.assertIsNone(unchanged.medical_judgments)

    def test_all_modern_disposition_actions_reject_a_stale_client_state(self):
        service = self._rux_service()
        target = next(
            item for item in service.inbox(RUX_PROJECT_ID).items if item.item_type == "risk"
        )

        with self.assertRaisesRegex(ValueError, "stale_disposition"):
            service.apply_rux_risk_disposition(
                RUX_PROJECT_ID,
                target.item_id,
                RuxRiskDispositionActionRequest(
                    action=RuxRiskDispositionAction.REVIEWED,
                    medical_judgments=MonitoringMedicalJudgments(review_completed=True),
                    actor="medical_manager",
                    comment="客户端仍以为该风险已复核，不得覆盖当前状态。",
                    expected_source_version=target.source_version,
                    expected_disposition_state="reviewed",
                ),
            )

        self.assertEqual([], self.rux_disposition_store.records(RUX_PROJECT_ID))

    def test_rux_internal_approval_gate_recovers_after_repository_restart(self):
        service = self._rux_service()
        target, approval_id = self._submit_rux_internal_approval(service)

        restarted_repo = DemoRepository(self.demo_data_path)
        try:
            recovered = restarted_repo.approval(RUX_PROJECT_ID, approval_id)
        except KeyError as exc:
            self.fail(f"RUX internal approval should recover after repository restart: {exc}")

        self.assertEqual(approval_id, recovered.approval_id)
        self.assertEqual("medical_monitoring_risk_disposition", recovered.target_type)
        self.assertEqual(target.source_id, recovered.target_id)
        self.assertEqual(ApprovalState.IN_MEDICAL_REVIEW, recovered.state)
        self.assertEqual("medical_manager", recovered.requested_by)
        self.assertIn("内部Query草稿/处置建议审批", recovered.review_comments)
        self.assertIn("不代表对外Query已执行、风险关闭或归档", recovered.review_comments)
        self.assertNotIn(target.source_version, recovered.review_comments)
        self.assertNotIn(target.item_id, recovered.review_comments)

        restarted_service = self._rux_service(repo=restarted_repo)
        recovered_item = next(item for item in restarted_service.inbox(RUX_PROJECT_ID).items if item.item_id == target.item_id)
        self.assertEqual("已提交内部审批", recovered_item.status)
        self.assertEqual("查看内部审批状态", recovered_item.action_label)
        self.assertFalse(recovered_item.needs_action)

        serialized = json.dumps(recovered.model_dump(mode="json"), ensure_ascii=False)
        self.assertNotIn("/Users/", serialized)
        self.assertNotRegex(serialized, r"已发中心|风险已关闭|正式批准|自动关闭|可直接归档|监管归档完成|电子签名已完成")

    def test_rux_approved_internal_approval_recovers_after_repository_restart_without_pending_dashboard(self):
        service = self._rux_service()
        target, approval_id = self._submit_rux_internal_approval(service)

        result = service.repo.record_approval_action(
            RUX_PROJECT_ID,
            approval_id,
            ApprovalActionRequest(
                action=ApprovalAction.APPROVE,
                actor="medical_manager",
                comment="仅批准内部Query草稿/处置建议；不代表对外Query已执行、风险关闭或归档。",
            ),
        )
        self.assertEqual(ApprovalState.MEDICALLY_APPROVED, result.approval.state)

        restarted_repo = DemoRepository(self.demo_data_path)
        try:
            recovered = restarted_repo.approval(RUX_PROJECT_ID, approval_id)
        except KeyError as exc:
            self.fail(f"approved RUX internal approval should recover after repository restart: {exc}")
        self.assertEqual(ApprovalState.MEDICALLY_APPROVED, recovered.state)
        self.assertEqual("medical_manager", recovered.approved_by)
        self.assertIn("内部Query草稿/处置建议", recovered.review_comments)
        self.assertNotIn("已发中心", recovered.review_comments)
        self.assertEqual([], [approval for approval in restarted_repo.approvals(RUX_PROJECT_ID) if approval.state == ApprovalState.IN_MEDICAL_REVIEW])

        decisions = [
            item
            for item in restarted_repo.data.get("approval_decisions", [])
            if item["project_id"] == RUX_PROJECT_ID and item["approval_id"] == approval_id
        ]
        audit_events = [
            item
            for item in restarted_repo.data.get("audit_events", [])
            if item["project_id"] == RUX_PROJECT_ID and item["target_id"] == approval_id
        ]
        self.assertEqual(1, len(decisions))
        self.assertEqual(1, len(audit_events))
        self.assertEqual(ApprovalAction.APPROVE.value, decisions[0]["action"])
        self.assertEqual("approval.approve", audit_events[0]["action"])

        restarted_service = self._rux_service(repo=restarted_repo)
        recovered_item = next(item for item in restarted_service.inbox(RUX_PROJECT_ID).items if item.item_id == target.item_id)
        self.assertEqual("已提交内部审批", recovered_item.status)
        self.assertNotRegex(
            json.dumps(restarted_service.inbox(RUX_PROJECT_ID).model_dump(mode="json"), ensure_ascii=False),
            r"已发中心|风险已关闭|正式批准|自动关闭|可直接归档|监管归档完成|电子签名已完成",
        )

    def test_rux_risk_disposition_rejects_invalid_transitions(self):
        service = self._rux_service()
        target = next(item for item in service.inbox(RUX_PROJECT_ID).items if item.title == "S01017 ALT/AST >5xULN")

        with self.assertRaisesRegex(ValueError, "must mark reviewed before query draft"):
            service.apply_rux_risk_disposition(
                RUX_PROJECT_ID,
                target.item_id,
                RuxRiskDispositionActionRequest(
                    action=RuxRiskDispositionAction.QUERY_DRAFT,
                    actor="medical_manager",
                    comment="premature query",
                    query_draft_text="premature query",
                    expected_source_version=target.source_version,
                ),
            )
        with self.assertRaisesRegex(ValueError, "must create query draft before submit"):
            service.apply_rux_risk_disposition(
                RUX_PROJECT_ID,
                target.item_id,
                RuxRiskDispositionActionRequest(
                    action=RuxRiskDispositionAction.SUBMITTED_FOR_APPROVAL,
                    actor="medical_manager",
                    comment="premature submit",
                    expected_source_version=target.source_version,
                ),
            )
        service.apply_rux_risk_disposition(
            RUX_PROJECT_ID,
            target.item_id,
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.REVIEWED,
                medical_judgments=MonitoringMedicalJudgments(review_completed=True),
                actor="medical_manager",
                comment="已完成医学复核。",
                expected_source_version=target.source_version,
            ),
        )
        with self.assertRaisesRegex(ValueError, "comment is required"):
            service.apply_rux_risk_disposition(
                RUX_PROJECT_ID,
                target.item_id,
                RuxRiskDispositionActionRequest(
                    action=RuxRiskDispositionAction.QUERY_DRAFT,
                    actor="medical_manager",
                    comment="",
                    expected_source_version=target.source_version,
                ),
            )
        with self.assertRaisesRegex(ValueError, "stale_source"):
            service.apply_rux_risk_disposition(
                RUX_PROJECT_ID,
                target.item_id,
                RuxRiskDispositionActionRequest(
                    action=RuxRiskDispositionAction.QUERY_DRAFT,
                    actor="medical_manager",
                    comment="stale query",
                    query_draft_text="stale query",
                    expected_source_version="old-source-version",
                ),
            )
        self.assertEqual(1, len(self.rux_disposition_store.records(RUX_PROJECT_ID)))

    def test_corrupt_source_registry_degrades_to_data_health_item(self):
        path = Path(self.tmp.name) / "sources.jsonl"
        path.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "entry": {
                                "entry_id": "src_good",
                                "project_id": PROJECT_ID,
                                "module": "medical_monitoring",
                                "source_kind": "listing_file",
                                "public_title": "EDC listing.xlsx",
                                "content_hash": "hash_edc",
                                "size_bytes": 10,
                                "parser_status": "parsed",
                                "span_count": 1,
                                "metadata": {},
                                "storage_key": "",
                                "created_at": "2026-07-08T09:00:00Z",
                            },
                            "spans": [],
                        },
                        ensure_ascii=False,
                    ),
                    "{bad json",
                ]
            ),
            encoding="utf-8",
        )
        self.service.source_registry_service = FakeSourceRegistry(
            store=SimpleNamespace(jsonl_path=path),
            raise_on_list=True,
        )
        inbox = self.service.inbox(PROJECT_ID)
        serialized = json.dumps(inbox.model_dump(mode="json"), ensure_ascii=False)

        self.assertIn("来源登记运行态存在无法解析记录", serialized)
        self.assertIn("来源已接入：EDC listing.xlsx", serialized)
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn("hash_edc", serialized)

    def test_read_only_inbox_without_snapshot_never_evaluates_risks(self):
        repository = MedicalRiskRepository(
            self.runtime_dir / "medical_risks_missing_snapshot.sqlite3"
        )
        service = self._projection_service(
            ThrowingProjectionAdapter(),
            repository,
        )

        self.assertEqual([], service.monitoring_risk_items(RUX_PROJECT_ID))
        inbox = service.inbox(RUX_PROJECT_ID)
        self.assertEqual(0, inbox.total_open_count)
        self.assertEqual([], [item for item in inbox.items if item.item_type == "risk"])
        self.assertEqual(
            [],
            service.safety_monitoring_collaboration_handoffs(RUX_PROJECT_ID),
        )

    def test_read_only_inbox_projects_matching_persisted_snapshot(self):
        producer = FakeRuxMonitoringService()
        risk = producer.evaluate_subject_risks(RUX_PROJECT_ID, "S01017")[0]
        repository = MedicalRiskRepository(
            self.runtime_dir / "medical_risks_matching_snapshot.sqlite3"
        )
        snapshot = repository.save_snapshot(
            project_id=RUX_PROJECT_ID,
            source_revision=producer.source_revision(),
            rule_profile_revision=producer.risk_profile_revision(),
            engine_version=producer.risk_engine_version(),
            evaluated_subject_count=3,
            risks=[risk],
        )
        service = self._projection_service(
            ThrowingProjectionAdapter(),
            repository,
        )

        items = service.monitoring_risk_items(RUX_PROJECT_ID)

        self.assertEqual(1, len(items))
        self.assertEqual(snapshot.snapshot_id, items[0].snapshot_id)
        self.assertTrue(items[0].unread)
        self.assertEqual("待医学复核", items[0].status)
        self.assertEqual("标记医学复核", items[0].action_label)
        self.assertEqual("rux_monitoring_risk", items[0].source_type)
        self.assertIn("Safety/PV关注", items[0].boundary_note)
        self.assertEqual(
            ["protocol_rule", "source_locator", "listing_data_row"],
            [source.source_type for source in items[0].source_refs],
        )

    def test_read_only_inbox_rejects_stale_snapshot_identities_without_evaluation(self):
        producer = FakeRuxMonitoringService()
        risk = producer.evaluate_subject_risks(RUX_PROJECT_ID, "S01017")[0]
        mismatches = (
            ("source", "rux-source-revision-2", "rux-rules-v1", "rux-engine-v1"),
            ("rule", "rux-source-revision-1", "rux-rules-v2", "rux-engine-v1"),
            ("engine", "rux-source-revision-1", "rux-rules-v1", "rux-engine-v2"),
        )
        for label, source_revision, rule_revision, engine_version in mismatches:
            with self.subTest(identity=label):
                repository = MedicalRiskRepository(
                    self.runtime_dir / f"medical_risks_stale_{label}.sqlite3"
                )
                repository.save_snapshot(
                    project_id=RUX_PROJECT_ID,
                    source_revision=producer.source_revision(),
                    rule_profile_revision=producer.risk_profile_revision(),
                    engine_version=producer.risk_engine_version(),
                    evaluated_subject_count=3,
                    risks=[risk],
                )
                service = self._projection_service(
                    ThrowingProjectionAdapter(
                        source_revision=source_revision,
                        rule_revision=rule_revision,
                        engine_version=engine_version,
                    ),
                    repository,
                )

                self.assertEqual([], service.monitoring_risk_items(RUX_PROJECT_ID))
                self.assertEqual(
                    [],
                    [
                        item
                        for item in service.inbox(RUX_PROJECT_ID).items
                        if item.item_type == "risk"
                    ],
                )

    def test_terminal_monitoring_risks_do_not_reenter_active_inbox(self):
        service = self._rux_service(
            monitoring_service=FakeRuxMonitoringServiceWithTerminalRisks()
        )

        items = service.monitoring_risk_items(RUX_PROJECT_ID)

        self.assertEqual(["S01017 ALT/AST >5xULN"], [item.title for item in items])

    def test_cross_module_handoff_manifest_always_checks_monitoring_collaborations(self):
        class HandoffGate:
            def __init__(self, ready: bool):
                self.ready = ready
                self.calls = 0

            def has_handoff_candidate_records(self, project_id: str) -> bool:
                return self.ready

            def citation_manifest(self, project_id: str):
                self.calls += 1
                return SimpleNamespace(candidates=[])

            def handoff_candidates(self, project_id: str):
                self.calls += 1
                return SimpleNamespace(candidates=[], monitoring_collaborations=[])

        tfl_blocked = HandoffGate(False)
        safety_blocked = HandoffGate(False)
        self.service.tfl_writing_handoff_service = tfl_blocked
        self.service.safety_review_workbench_service = safety_blocked
        self.assertEqual([], self.service._tfl_handoff_items(PROJECT_ID))
        self.assertEqual([], self.service._safety_handoff_items(PROJECT_ID))
        self.assertEqual((0, 1), (tfl_blocked.calls, safety_blocked.calls))

        tfl_ready = HandoffGate(True)
        safety_ready = HandoffGate(True)
        self.service.tfl_writing_handoff_service = tfl_ready
        self.service.safety_review_workbench_service = safety_ready
        self.assertEqual([], self.service._tfl_handoff_items(PROJECT_ID))
        self.assertEqual([], self.service._safety_handoff_items(PROJECT_ID))
        self.assertEqual((1, 1), (tfl_ready.calls, safety_ready.calls))


if __name__ == "__main__":
    unittest.main()
