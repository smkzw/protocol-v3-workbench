from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from packages.contracts.workbench_contracts import (
    AiTaskArtifact,
    AiTaskRequest,
    AiTaskRun,
    AiTaskRunStatus,
    AiTaskSourceRef,
    ApprovalState,
    ProtocolDocument,
    ProtocolSection,
)
from services.api.app.ai_execution_policy import AiExecutionPolicyResolver
from services.api.app.ai_gateway import AiTaskType, validate_ai_output
from services.api.app.ai_task_runner import AiTaskRunner, AiTaskStore
from services.api.app.demo_repository import DemoRepository
from services.api.app.medical_writing_durable_jobs import DurableJobStore
from services.api.app.medical_writing_full_draft import (
    FULL_DRAFT_ARTIFACT_SCHEMA,
    FULL_DRAFT_PROMPT_VERSION,
    MedicalWritingFullDraftService,
    ProtocolFullDraftExecutor,
)
from services.api.app.sqlite_runtime_store import RuntimeStoreError, StaleRuntimeStateError


class _FakeRepo:
    def __init__(self):
        self.project_id = "proj_full_draft_fake"
        self.document = ProtocolDocument(
            document_id="doc_full_draft_fake",
            project_id=self.project_id,
            protocol_id="FAKE-001",
            version="0.1",
            sections=[
                ProtocolSection(
                    section_id="sec_1",
                    document_id="doc_full_draft_fake",
                    heading="研究背景",
                    section_number="1",
                    node_kind="section",
                    completion_status="blocked_missing_inputs",
                    content_blocks=[
                        {"block_id": "h1", "block_type": "heading", "text": "研究背景"},
                        {"block_id": "b1", "block_type": "paragraph", "text": "", "source_kind": "greenfield_scaffold"},
                    ],
                    drafting_status="actionable_blocker",
                    drafting_blocker_code="project_evidence_missing",
                    drafting_blocker_reason="需要正文",
                    drafting_missing_inputs=["研究事实"],
                    drafting_resolution_actions=["生成候选"],
                ),
                ProtocolSection(
                    section_id="sec_2",
                    document_id="doc_full_draft_fake",
                    heading="研究目的",
                    section_number="2",
                    node_kind="section",
                    completion_status="blocked_missing_inputs",
                    content_blocks=[
                        {"block_id": "h2", "block_type": "heading", "text": "研究目的"},
                        {"block_id": "b2", "block_type": "paragraph", "text": "", "source_kind": "greenfield_scaffold"},
                    ],
                    drafting_status="actionable_blocker",
                    drafting_blocker_code="project_evidence_missing",
                    drafting_blocker_reason="需要正文",
                    drafting_missing_inputs=["研究事实"],
                    drafting_resolution_actions=["生成候选"],
                ),
            ],
            source_study_definition_id="sd_fake",
            source_study_definition_revision=1,
            source_study_definition_sha256="a" * 64,
        )
        self.working = {
            "sec_1": SimpleNamespace(revision=0, content_blocks=[dict(x) for x in self.document.sections[0].content_blocks]),
            "sec_2": SimpleNamespace(revision=0, content_blocks=[dict(x) for x in self.document.sections[1].content_blocks]),
        }
        self.save_calls = []

    def protocol(self, project_id):
        assert project_id == self.project_id
        return self.document

    def working_copy(self, project_id, section_id):
        assert project_id == self.project_id
        return self.working[section_id]

    def authoritative_study_definition_binding(self, project_id):
        return "sd_fake", 1, "a" * 64

    def save_working_copy(self, project_id, section_id, request):
        current = self.working[section_id]
        if current.revision != request.expected_revision:
            raise StaleRuntimeStateError("stale fake working copy")
        current.revision += 1
        current.content_blocks = [dict(item) for item in request.content_blocks]
        self.save_calls.append((section_id, request.idempotency_key))
        return current


class _FakeFullDraftRunner:
    def __init__(self):
        self.calls = 0

    def submit_internal(self, project_id, request):
        self.calls += 1
        packet = request.allowed_sources[0]
        evidence_id = f"ev_{self.calls}"
        sections = []
        for section_id in request.task_context["section_ids"]:
            sections.append(
                {
                    "section_id": section_id,
                    "content_status": "complete",
                    "proposal_text": (
                        f"本章节围绕{section_id}说明研究对象、研究目的、执行边界和评价要求。"
                        "正文明确研究对象、主要评价路径和实施约束，并采用可直接审阅的连续监管中文。"
                        "关键医学依据通过证据说明单独呈现，正文不混入写作过程或系统操作提示。"
                    ),
                    "rationale": "依据已录入的适应症、分期和目标人群；请核对医学依据完整性。",
                    "evidence_span_ids": [evidence_id],
                    "decision_items": [],
                    "missing_source_classes": [],
                }
            )
        payload = {
            "task_id": f"run_{self.calls}",
            "task_type": AiTaskType.PROTOCOL_FULL_DRAFT.value,
            "provider": "buddy",
            "model": "deepseek-v4-pro",
            "prompt_version": FULL_DRAFT_PROMPT_VERSION,
            "input_source_ids": [source.source_id for source in request.allowed_sources],
            "forbidden_source_ids": [],
            "findings": [],
            "evidence_spans": [
                {"span_id": evidence_id, "source_id": packet.source_id, "locator": packet.locator, "quote": packet.text_preview[:30]}
            ],
            "uncertainties": [],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
            "full_draft": {"sections": sections},
        }
        now = datetime.now(timezone.utc)
        return AiTaskRun(
            run_id=f"run_{self.calls}",
            project_id=project_id,
            module="medical_writing",
            task_type=AiTaskType.PROTOCOL_FULL_DRAFT.value,
            purpose="full draft",
            status=AiTaskRunStatus.COMPLETED,
            provider="buddy",
            model_name="deepseek-v4-pro",
            ai_gateway_status="configured",
            request_origin="trusted_server_source",
            data_classification="confidential_clinical_document",
            deployment_profile="approved_private_documents",
            prompt_version=FULL_DRAFT_PROMPT_VERSION,
            artifacts=[AiTaskArtifact(artifact_id=f"artifact_{self.calls}", artifact_type="provider_output", payload=payload)],
            created_at=now,
            updated_at=now,
        )


class FullDraftServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.repo = _FakeRepo()
        self.runner = _FakeFullDraftRunner()
        self.policy = {
            "provider_name": "buddy",
            "model_name": "deepseek-v4-pro",
            "route_identity_hash": "b" * 64,
            "prompt_version": FULL_DRAFT_PROMPT_VERSION,
        }
        source = AiTaskSourceRef(
            source_id="study_definition_fake",
            source_type="current_project_study_definition",
            title="已确认研究事实",
            locator="study_definition:sd_fake:revision:1",
            text_preview="适应症：哮喘\n研究分期：II期\n目标研究人群：成年受试者",
            project_id=self.repo.project_id,
            module="medical_writing",
        )
        self.service = SimpleNamespace(
            repo=self.repo,
            ai_task_runner=self.runner,
            _policy_identity=lambda: dict(self.policy),
            _current_project_study_definition_source=lambda protocol, section: source,
            _company_corpus_sources=lambda *args: [],
            _shared_corpus_sources=lambda *args: [],
        )
        self.full = MedicalWritingFullDraftService(
            service_resolver=lambda project_id: self.service,
            artifact_root=Path(self.tmpdir.name) / "artifacts",
        )
        self.store = DurableJobStore(Path(self.tmpdir.name) / "durable.sqlite3")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_duplicate_request_reuses_job_and_adoption_is_idempotent(self):
        project = self.repo.project_id
        first, reused_first = self.full.submit_durable(project, self.store)
        second, reused_second = self.full.submit_durable(project, self.store)
        self.assertFalse(reused_first)
        self.assertTrue(reused_second)
        self.assertEqual(first, second)
        job = self.store.get(project, first)
        result = ProtocolFullDraftExecutor(self.full).execute(
            job,
            "claim",
            lambda: False,
            lambda progress: True,
        )
        self.assertEqual("", result.error)
        # Make the fake store row terminal as the real worker would.
        claim = self.store.claim(project, first)
        self.assertTrue(claim.claimed)
        result = ProtocolFullDraftExecutor(self.full).execute(
            claim.job,
            claim.claim_token,
            lambda: False,
            lambda progress: True,
        )
        self.assertEqual("", result.error)
        # The first execution already persisted the deterministic chunk
        # artifact; a worker restart/reclaim must reuse it rather than invoke
        # the model again.
        self.assertEqual(1, self.runner.calls)
        self.store.complete(
            project,
            first,
            claim.claim_token,
            output_hash=result.output_hash,
            artifact_locator=result.artifact_locator,
            provider=result.provider,
            model=result.model,
            final_progress=result.progress,
        )
        completed = self.store.get(project, first)
        adopted = self.full.adopt(project, completed)
        replay = self.full.adopt(project, completed)
        self.assertEqual(2, adopted["adopted_count"])
        self.assertEqual(2, replay["replayed_count"])
        self.assertEqual(2, len(self.repo.save_calls))

    def test_stale_manual_edit_blocks_adoption(self):
        project = self.repo.project_id
        job_id, _ = self.full.submit_durable(project, self.store)
        claim = self.store.claim(project, job_id)
        result = ProtocolFullDraftExecutor(self.full).execute(
            claim.job,
            claim.claim_token,
            lambda: False,
            lambda progress: True,
        )
        locator = json.loads(result.artifact_locator)
        self.assertNotIn(
            "required_review_section_ids",
            locator["coverage"],
        )
        self.assertLessEqual(len(result.artifact_locator), 2_000)
        self.store.complete(
            project,
            job_id,
            claim.claim_token,
            output_hash=result.output_hash,
            artifact_locator=result.artifact_locator,
            provider=result.provider,
            model=result.model,
            final_progress=result.progress,
        )
        self.repo.working["sec_1"].revision = 1
        self.repo.working["sec_1"].content_blocks[1]["text"] = "医学作者另行修改了正文。"
        with self.assertRaises(StaleRuntimeStateError):
            self.full.adopt(project, self.store.get(project, job_id))

    def test_adoption_rejects_legacy_candidate_with_internal_or_unresolved_markers(self):
        project = self.repo.project_id
        job_id, _ = self.full.submit_durable(project, self.store)
        claim = self.store.claim(project, job_id)
        result = ProtocolFullDraftExecutor(self.full).execute(
            claim.job,
            claim.claim_token,
            lambda: False,
            lambda progress: True,
        )
        self.store.complete(
            project,
            job_id,
            claim.claim_token,
            output_hash=result.output_hash,
            artifact_locator=result.artifact_locator,
            provider=result.provider,
            model=result.model,
            final_progress=result.progress,
        )
        artifact = self.full.read_artifact(project, self.store.get(project, job_id))
        artifact["sections"][0]["proposal_text"] = (
            "本章节包含足够长度的正文，但仍把fixture留在方案中，"
            "且主要终点尚待医学经理结合证据确认。"
        )
        with patch.object(self.full, "read_artifact", return_value=artifact):
            with self.assertRaisesRegex(RuntimeStoreError, "候选不具备实质内容"):
                self.full.adopt(project, self.store.get(project, job_id))

    def test_required_review_sections_must_be_confirmed_before_adoption(self):
        project = self.repo.project_id
        job_id, _ = self.full.submit_durable(project, self.store)
        claim = self.store.claim(project, job_id)
        result = ProtocolFullDraftExecutor(self.full).execute(
            claim.job,
            claim.claim_token,
            lambda: False,
            lambda progress: True,
        )
        self.store.complete(
            project,
            job_id,
            claim.claim_token,
            output_hash=result.output_hash,
            artifact_locator=result.artifact_locator,
            provider=result.provider,
            model=result.model,
            final_progress=result.progress,
        )
        completed = self.store.get(project, job_id)
        artifact = self.full.read_artifact(project, completed)
        artifact["sections"][0]["review_level"] = "required"
        with patch.object(self.full, "read_artifact", return_value=artifact):
            with self.assertRaisesRegex(RuntimeStoreError, "高影响章节未逐卡确认"):
                self.full.adopt(project, completed)
            adopted = self.full.adopt(
                project,
                completed,
                confirmed_section_ids=[artifact["sections"][0]["section_id"]],
            )
        self.assertEqual(2, adopted["adopted_count"])

    def test_decision_or_source_gap_blocks_adoption_before_any_write(self):
        project = self.repo.project_id
        job_id, _ = self.full.submit_durable(project, self.store)
        claim = self.store.claim(project, job_id)
        result = ProtocolFullDraftExecutor(self.full).execute(
            claim.job, claim.claim_token, lambda: False, lambda progress: True
        )
        self.store.complete(
            project, job_id, claim.claim_token,
            output_hash=result.output_hash,
            artifact_locator=result.artifact_locator,
            provider=result.provider,
            model=result.model,
            final_progress=result.progress,
        )
        completed = self.store.get(project, job_id)
        artifact = self.full.read_artifact(project, completed)
        artifact["sections"][0]["content_status"] = "source_gap"
        with patch.object(self.full, "read_artifact", return_value=artifact):
            with self.assertRaisesRegex(RuntimeStoreError, "待决定或来源缺口"):
                self.full.adopt(project, completed)

    def test_legacy_v3_candidate_remains_readable_but_cannot_be_adopted(self):
        project = self.repo.project_id
        job_id, _ = self.full.submit_durable(project, self.store)
        claim = self.store.claim(project, job_id)
        result = ProtocolFullDraftExecutor(self.full).execute(
            claim.job, claim.claim_token, lambda: False, lambda progress: True
        )
        self.store.complete(
            project, job_id, claim.claim_token,
            output_hash=result.output_hash,
            artifact_locator=result.artifact_locator,
            provider=result.provider,
            model=result.model,
            final_progress=result.progress,
        )
        completed = self.store.get(project, job_id)
        artifact = self.full.read_artifact(project, completed)
        artifact["schema_version"] = "protocol_full_draft_artifact_v3"
        reviewed = self.full._apply_review_policy(artifact)
        self.assertTrue(reviewed["coverage"]["legacy_read_only"])
        self.assertFalse(reviewed["coverage"]["adoption_ready"])
        with patch.object(self.full, "read_artifact", return_value=reviewed):
            with self.assertRaisesRegex(RuntimeStoreError, "旧版全文初稿候选仅供查阅"):
                self.full.adopt(project, completed)

    def test_review_metadata_marks_high_impact_and_corpus_conduct_sections(self):
        project_source = AiTaskSourceRef(
            source_id="project_fact",
            source_type="current_project_study_definition",
            title="项目事实",
            locator="study-definition:1",
            text_preview="主要终点为第16周PASI75。",
            project_id=self.repo.project_id,
            module="medical_writing",
        )
        corpus_source = AiTaskSourceRef(
            source_id="company_corpus",
            source_type="company_protocol_reference_corpus",
            title="公司方案语料",
            locator="corpus:1",
            text_preview="避孕方法和严重不良事件报告规则示例。",
            project_id=self.repo.project_id,
            module="medical_writing",
        )
        metadata = self.full._review_metadata(
            {
                "proposal_text": "主要终点为第16周PASI75，并规定严重不良事件报告要求。",
                "evidence_span_ids": ["ev_project", "ev_corpus"],
            },
            {
                "evidence_spans": [
                    {"span_id": "ev_project", "source_id": "project_fact"},
                    {"span_id": "ev_corpus", "source_id": "company_corpus"},
                ]
            },
            [project_source, corpus_source],
            {"heading": "主要终点与安全性报告"},
        )
        self.assertEqual("required", metadata["review_level"])
        self.assertEqual(1, metadata["evidence_summary"]["project_fact_spans"])
        self.assertEqual(1, metadata["evidence_summary"]["corpus_spans"])
        self.assertEqual(2, len(metadata["review_reasons"]))

    def test_review_metadata_marks_operational_safety_and_embedded_design_decisions(self):
        metadata = self.full._review_metadata(
            {
                "proposal_text": (
                    "本节说明妊娠事件的随访范围，并包含计划入组132例和主要终点的设计决定。"
                ),
                "evidence_span_ids": [],
            },
            {"evidence_spans": []},
            [],
            {"heading": "妊娠事件"},
        )
        self.assertEqual("required", metadata["review_level"])
        self.assertIn("妊娠事件", metadata["review_reasons"][0])
        self.assertTrue(any("计划入组" in item for item in metadata["review_advisories"]))

    def test_review_metadata_does_not_require_confirmation_for_incidental_design_mentions(self):
        metadata = self.full._review_metadata(
            {
                "proposal_text": (
                    "疾病背景部分说明主要终点采用第16周PASI75，并概述计划入组132例的研究背景。"
                ),
                "evidence_span_ids": [],
            },
            {"evidence_spans": []},
            [],
            {"heading": "疾病背景及治疗现状"},
        )
        self.assertEqual("standard", metadata["review_level"])
        self.assertTrue(any("重复提及" in item for item in metadata["review_advisories"]))


class FullDraftContractTests(unittest.TestCase):
    @staticmethod
    def _output(section):
        return {
            "task_id": "run",
            "task_type": AiTaskType.PROTOCOL_FULL_DRAFT.value,
            "provider": "buddy",
            "model": "deepseek-v4-pro",
            "prompt_version": FULL_DRAFT_PROMPT_VERSION,
            "input_source_ids": ["source"],
            "forbidden_source_ids": [],
            "findings": [],
            "evidence_spans": [{"span_id": "ev", "source_id": "source", "locator": "loc", "quote": "source"}],
            "uncertainties": [],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
            "full_draft": {"sections": [section]},
        }

    def test_gateway_accepts_explicit_source_gap_without_filler(self):
        output = self._output({
            "section_id": "sec",
            "content_status": "source_gap",
            "proposal_text": "",
            "rationale": "缺少本品既往临床研究资料。",
            "evidence_span_ids": [],
            "decision_items": [],
            "missing_source_classes": ["研究者手册", "既往临床研究报告"],
        })
        self.assertEqual([], validate_ai_output(output))

    def test_gateway_requires_one_recommendation_for_decision_item(self):
        output = self._output({
            "section_id": "sec",
            "content_status": "decision_required",
            "proposal_text": "本节保留已确认的双盲设计事实，并将具体盲态角色与揭盲程序留给项目决定。" * 3,
            "rationale": "StudyDefinition尚未明确盲态角色。",
            "evidence_span_ids": ["ev"],
            "decision_items": [{
                "question": "哪些角色应保持盲态？",
                "options": [
                    {"option_id": "a", "label": "核心角色", "summary": "受试者和研究者保持盲态。"},
                    {"option_id": "b", "label": "扩展角色", "summary": "增加监查与分析角色。"},
                ],
                "recommended_option_id": "missing",
                "rationale": "需结合运营可行性确定。",
                "blocking_section_id": "sec",
            }],
            "missing_source_classes": [],
        })
        self.assertTrue(any("exactly one listed recommendation" in item for item in validate_ai_output(output)))

    def test_gateway_rejects_heading_only_full_draft(self):
        output = {
            "task_id": "run",
            "task_type": AiTaskType.PROTOCOL_FULL_DRAFT.value,
            "provider": "buddy",
            "model": "deepseek-v4-pro",
            "prompt_version": FULL_DRAFT_PROMPT_VERSION,
            "input_source_ids": ["source"],
            "forbidden_source_ids": [],
            "findings": [],
            "evidence_spans": [{"span_id": "ev", "source_id": "source", "locator": "loc", "quote": "source"}],
            "uncertainties": [],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
            "full_draft": {"sections": [{"section_id": "sec", "proposal_text": "1 研究背景", "rationale": "x", "evidence_span_ids": ["ev"]}]},
        }
        errors = validate_ai_output(output)
        self.assertTrue(any("proposal_text" in error for error in errors))

    def test_ai_task_runner_rejects_drafting_process_language_in_prose(self):
        source = AiTaskSourceRef(
            source_id="source",
            source_type="current_project_study_definition",
            title="研究事实",
            locator="study-definition:1",
            text_preview="成年斑块状银屑病受试者，主要终点为第16周PASI75。",
            project_id="project",
            module="medical_writing",
        )
        output = {
            "evidence_spans": [{"span_id": "ev", "source_id": "source"}],
            "full_draft": {
                "sections": [{
                    "section_id": "sec_process",
                    "proposal_text": (
                        "当前项目已确认成年斑块状银屑病受试者作为研究对象，主要终点为第16周PASI75。"
                        "本节继续说明研究目的、疗效评价路径、受试者保护要求和研究实施边界，"
                        "并形成可供医学作者审阅的连续规范正文。"
                    ),
                    "rationale": "依据项目研究事实。",
                    "evidence_span_ids": ["ev"],
                }]
            },
        }
        errors = AiTaskRunner._validate_protocol_full_draft_output(
            None,
            output,
            [source],
            {"section_ids": ["sec_process"], "minimum_body_chars": 80},
        )
        self.assertTrue(any("drafting-process language" in error for error in errors))

    def test_ai_task_runner_rejects_internal_transport_tokens_in_prose(self):
        class Provider:
            provider_name = "buddy"
            model_name = "deepseek-v4-pro"

            def run(self, envelope):
                source = envelope.payload["allowed_sources"][0]
                evidence_id = "ev_internal_token"
                return {
                    "task_id": envelope.task_id,
                    "task_type": envelope.task_type.value,
                    "provider": self.provider_name,
                    "model": self.model_name,
                    "prompt_version": envelope.prompt_version,
                    "input_source_ids": [source["source_id"]],
                    "forbidden_source_ids": [],
                    "findings": [],
                    "evidence_spans": [{
                        "span_id": evidence_id,
                        "source_id": source["source_id"],
                        "locator": source["locator"],
                        "quote": source["text_preview"][:24],
                    }],
                    "uncertainties": [],
                    "needs_medical_confirmation": True,
                    "schema_version": "ai_task_output_v0_1",
                    "full_draft": {"sections": [{
                        "section_id": "sec_internal",
                        "proposal_text": (
                            "本章节基于当前项目已确认研究事实形成连续的规范正文，"
                            "但不应把fixture或ProtocolAssemblyPlan等内部实现词带入正式方案。"
                            "医学作者仍需核对研究对象、评价路径、实施边界和证据依据。"
                        ),
                        "rationale": "使用当前项目唯一允许来源。",
                        "evidence_span_ids": [evidence_id],
                    }]},
                }

        with tempfile.TemporaryDirectory() as root:
            repo = DemoRepository(Path(__file__).parents[1] / "demo_data" / "workbench_demo_v0_1.json")
            runner = AiTaskRunner(
                repo,
                AiTaskStore(Path(root) / "runs.jsonl"),
                provider_factory=lambda _resolution: Provider(),
                policy_resolver=AiExecutionPolicyResolver(
                    deployment_profile="local_private_clinical",
                    provider_name="buddy",
                    model_name="deepseek-v4-pro",
                    test_only_provider_injection=True,
                ),
            )
            source = AiTaskSourceRef(
                source_id="full_draft_packet_internal_token",
                source_type="protocol_full_draft_selection",
                title="章节包",
                locator="document:doc:full-draft:internal-token",
                text_preview="SECTION_ID=sec_internal\n研究背景与当前项目已确认事实",
                project_id="proj_mgk10_sar_demo",
                module="medical_writing",
            )
            run = runner.submit_internal(
                "proj_mgk10_sar_demo",
                AiTaskRequest(
                    module="medical_writing",
                    task_type=AiTaskType.PROTOCOL_FULL_DRAFT,
                    prompt_version=FULL_DRAFT_PROMPT_VERSION,
                    allowed_sources=[source],
                    task_context={
                        "draft_version": "c" * 64,
                        "section_ids": ["sec_internal"],
                        "marker_open": "SECTION_ID=",
                        "marker_close": "\n",
                        "minimum_body_chars": 80,
                    },
                ),
            )
            self.assertEqual(AiTaskRunStatus.FAILED, run.status)
            self.assertTrue(
                any("internal transport/test vocabulary" in error for error in run.validation_errors)
            )

    def test_ai_task_runner_rejects_unresolved_draft_markers_in_prose(self):
        class Provider:
            provider_name = "buddy"
            model_name = "deepseek-v4-pro"

            def run(self, envelope):
                source = envelope.payload["allowed_sources"][0]
                evidence_id = "ev_unresolved_marker"
                return {
                    "task_id": envelope.task_id,
                    "task_type": envelope.task_type.value,
                    "provider": self.provider_name,
                    "model": self.model_name,
                    "prompt_version": envelope.prompt_version,
                    "input_source_ids": [source["source_id"]],
                    "forbidden_source_ids": [],
                    "findings": [],
                    "evidence_spans": [{
                        "span_id": evidence_id,
                        "source_id": source["source_id"],
                        "locator": source["locator"],
                        "quote": source["text_preview"][:24],
                    }],
                    "uncertainties": [],
                    "needs_medical_confirmation": True,
                    "schema_version": "ai_task_output_v0_1",
                    "full_draft": {"sections": [{
                        "section_id": "sec_unresolved",
                        "proposal_text": (
                            "本章节已形成连续的规范正文，但主要终点尚待医学经理结合证据确认，"
                            "相关时间窗尚无直接证据来源支持。"
                        ),
                        "rationale": "使用当前项目唯一允许来源。",
                        "evidence_span_ids": [evidence_id],
                    }]},
                }

        with tempfile.TemporaryDirectory() as root:
            repo = DemoRepository(Path(__file__).parents[1] / "demo_data" / "workbench_demo_v0_1.json")
            runner = AiTaskRunner(
                repo,
                AiTaskStore(Path(root) / "runs.jsonl"),
                provider_factory=lambda _resolution: Provider(),
                policy_resolver=AiExecutionPolicyResolver(
                    deployment_profile="local_private_clinical",
                    provider_name="buddy",
                    model_name="deepseek-v4-pro",
                    test_only_provider_injection=True,
                ),
            )
            source = AiTaskSourceRef(
                source_id="full_draft_packet_unresolved",
                source_type="protocol_full_draft_selection",
                title="章节包",
                locator="document:doc:full-draft:unresolved",
                text_preview="SECTION_ID=sec_unresolved\n研究终点事实",
                project_id="proj_mgk10_sar_demo",
                module="medical_writing",
            )
            run = runner.submit_internal(
                "proj_mgk10_sar_demo",
                AiTaskRequest(
                    module="medical_writing",
                    task_type=AiTaskType.PROTOCOL_FULL_DRAFT,
                    prompt_version=FULL_DRAFT_PROMPT_VERSION,
                    allowed_sources=[source],
                    task_context={
                        "draft_version": "d" * 64,
                        "section_ids": ["sec_unresolved"],
                        "marker_open": "SECTION_ID=",
                        "marker_close": "\n",
                        "minimum_body_chars": 80,
                    },
                ),
            )
            self.assertEqual(AiTaskRunStatus.FAILED, run.status)
            self.assertTrue(
                any("unresolved drafting markers" in error for error in run.validation_errors)
            )

    def test_ai_task_runner_accepts_a_source_bound_full_draft(self):
        class Provider:
            provider_name = "buddy"
            model_name = "deepseek-v4-pro"

            def run(self, envelope):
                source = envelope.payload["allowed_sources"][0]
                section_id = envelope.payload["task_context"]["section_ids"][0]
                evidence_id = "ev_full_draft"
                return {
                    "task_id": envelope.task_id,
                    "task_type": envelope.task_type.value,
                    "provider": self.provider_name,
                    "model": self.model_name,
                    "prompt_version": envelope.prompt_version,
                    "input_source_ids": [source["source_id"]],
                    "forbidden_source_ids": list(envelope.payload["forbidden_source_ids"]),
                    "findings": [],
                    "evidence_spans": [{
                        "span_id": evidence_id,
                        "source_id": source["source_id"],
                        "locator": source["locator"],
                        "quote": source["text_preview"][:24],
                    }],
                    "uncertainties": [],
                    "needs_medical_confirmation": True,
                    "schema_version": "ai_task_output_v0_1",
                    "full_draft": {"sections": [{
                        "section_id": section_id,
                        "content_status": "complete",
                        "proposal_text": "本章节说明成年哮喘受试者的研究背景、研究目的、执行边界和评价要求。正文明确研究对象、主要评价路径和实施约束，并采用可直接审阅的连续监管中文。关键医学依据通过证据说明单独呈现，正文不混入写作过程或系统操作提示。",
                        "rationale": "使用当前项目唯一允许来源。",
                        "evidence_span_ids": [evidence_id],
                        "decision_items": [],
                        "missing_source_classes": [],
                    }]},
                }

        with tempfile.TemporaryDirectory() as root:
            repo = DemoRepository(Path(__file__).parents[1] / "demo_data" / "workbench_demo_v0_1.json")
            runner = AiTaskRunner(
                repo,
                AiTaskStore(Path(root) / "runs.jsonl"),
                provider_factory=lambda _resolution: Provider(),
                policy_resolver=AiExecutionPolicyResolver(
                    deployment_profile="local_private_clinical",
                    provider_name="buddy",
                    model_name="deepseek-v4-pro",
                    test_only_provider_injection=True,
                ),
            )
            source = AiTaskSourceRef(
                source_id="full_draft_packet",
                source_type="protocol_full_draft_selection",
                title="章节包",
                locator="document:doc:full-draft:1",
                text_preview="SECTION_ID=sec_a\n研究背景与当前项目已确认事实",
                project_id="proj_mgk10_sar_demo",
                module="medical_writing",
            )
            run = runner.submit_internal(
                "proj_mgk10_sar_demo",
                AiTaskRequest(
                    module="medical_writing",
                    task_type=AiTaskType.PROTOCOL_FULL_DRAFT,
                    prompt_version=FULL_DRAFT_PROMPT_VERSION,
                    allowed_sources=[source],
                    task_context={
                        "draft_version": "a" * 64,
                        "section_ids": ["sec_a"],
                        "marker_open": "SECTION_ID=",
                        "marker_close": "\n",
                        "minimum_body_chars": 80,
                    },
                ),
            )
            self.assertEqual(AiTaskRunStatus.COMPLETED, run.status)
            self.assertEqual([], run.validation_errors)
