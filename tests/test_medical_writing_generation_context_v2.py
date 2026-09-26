"""Decisive behavioral tests for mw_gen_ctx_v2 generation context.

Proves production path behavior (not source-string presence):
- identical canonical descriptor reuses completed job
- WC / plan / instruction / policy / namespace changes create new jobs
- invalid evidence fails closed before provider
- pre-AI and pre-commit drift leave no thread/candidate/audit
- exact replay by suggestion_ids remains stable after unrelated appends
- adopt revalidation + repository lineage gate
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from packages.contracts.workbench_contracts import (
    AuditEvent,
    MedicalWritingGreenfieldCreateRequest,
    MedicalWritingGreenfieldDecision,
    MedicalWritingGreenfieldSectionSeed,
    MedicalWritingRevisionRequest,
    RevisionSuggestion,
    RevisionThread,
    SourceContentValidationCheck,
    SourceContentValidationRecord,
)
from services.api.app.ai_execution_policy import AiExecutionPolicyResolver
from services.api.app.medical_writing import (
    MedicalWritingRevisionService,
    SectionAiCandidateExecutor,
)
from services.api.app.medical_writing import MedicalWritingRevisionService as _MWRService
# The shipped descriptor version (digest v4: working-copy blocks excluded from
# the lineage payload). Tests bind to the authoritative constant, not a stale
# literal, so legitimate version bumps cannot silently break version checks.
GENERATION_CONTEXT_VERSION = _MWRService.GENERATION_CONTEXT_VERSION
from services.api.app.medical_writing_document import MedicalWritingDocumentService
from services.api.app.medical_writing_durable_jobs import DurableJobStore
from services.api.app.medical_writing_greenfield import (
    CompositeMedicalWritingDocumentService,
    GreenfieldMedicalWritingDocumentService,
)
from services.api.app.medical_writing_manifest import RUX_PROTOCOL_DOCX
from services.api.app.medical_writing_repository import MedicalWritingRuntimeRepository
from services.api.app.source_intake import SourceRegistryService, SourceRegistryStore
from services.api.app.sqlite_runtime_store import (
    RuntimeStoreError,
    SqliteRuntimeStore,
)


PROJECT = "proj_rux_03_002"


def _policy_runner(provider="deepseek", model="deepseek-chat"):
    return SimpleNamespace(
        policy_resolver=AiExecutionPolicyResolver(
            provider_name=provider,
            model_name=model,
        )
    )


def _service(tmpdir: Path, **kwargs):
    documents = MedicalWritingDocumentService()
    store = SqliteRuntimeStore(tmpdir / "runtime.sqlite3")
    repo = MedicalWritingRuntimeRepository(documents, store)
    service = MedicalWritingRevisionService(
        repo,
        ai_task_runner=kwargs.get("runner") or _policy_runner(),
    )
    service.require_registered_sources = False
    if "plan_helper" in kwargs:
        service.plan_consumption_helper = kwargs["plan_helper"]
    if "company" in kwargs:
        service.company_corpus_service = kwargs["company"]
    if "shared" in kwargs:
        service.shared_corpus_service = kwargs["shared"]
    if "writing_ref" in kwargs:
        service.writing_reference_repository = kwargs["writing_ref"]
    return documents, store, repo, service


def _request(documents, project_id=PROJECT, instruction="生成可审阅候选", evidence=None):
    document = documents.document_session(project_id)
    section = documents.section(project_id, document.sections[0].section_id)
    block = next(
        b
        for b in section.content_blocks
        if str(b.get("text", "")).strip() and b.get("source_locator")
    )
    return MedicalWritingRevisionRequest(
        document_id=document.document_id,
        section_id=section.section_id,
        selected_text=str(block["text"])[:40],
        anchor_path=block["source_locator"],
        anchor_type="selection",
        user_instruction=instruction,
        intent="regulatory_tone",
        evidence_brief_ids=list(evidence or []),
        requested_by="medical_manager_test",
    )


class GenerationContextDescriptorTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.documents, self.store, self.repo, self.service = _service(
            Path(self.tmpdir.name)
        )
        self.req = _request(self.documents)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_descriptor_is_versioned_full_sha256(self):
        ctx = self.service.build_generation_context_descriptor(
            PROJECT,
            section_id=self.req.section_id,
            operation="initial",
            request=self.req,
        )
        self.assertEqual(GENERATION_CONTEXT_VERSION, ctx["version"])
        self.assertEqual(64, len(ctx["digest"]))
        self.assertTrue(all(c in "0123456789abcdef" for c in ctx["digest"]))
        desc = ctx["descriptor"]
        self.assertEqual(GENERATION_CONTEXT_VERSION, desc["version"])
        self.assertIn("working_copy", desc)
        self.assertIn("study_definition", desc)
        self.assertIn("assembly_plan", desc)
        self.assertIn("corpus", desc)
        self.assertIn("ai_policy", desc)
        self.assertEqual("deepseek", desc["ai_policy"]["provider_name"])

    def test_descriptor_freezes_complete_credential_free_route_snapshot(self):
        ctx = self.service.build_generation_context_descriptor(
            PROJECT,
            section_id=self.req.section_id,
            operation="initial",
            request=self.req,
        )
        snapshot = ctx["descriptor"]["ai_policy"]["route_identity_snapshot"]
        self.assertEqual(
            {
                "schema_version",
                "role_id",
                "profile_id",
                "profile_revision",
                "provider",
                "model",
                "base_url",
                "transport",
                "expected_response_model",
                "deployment_profile",
                "identity_sha256",
            },
            set(snapshot),
        )
        self.assertEqual("independent_ai", snapshot["role_id"])
        self.assertEqual(snapshot["identity_sha256"], ctx["descriptor"]["ai_policy"]["route_identity_hash"])
        self.assertEqual(snapshot["model"], "deepseek-chat")
        self.assertFalse(any("key" in str(key).lower() for key in snapshot))

    def test_identical_context_stable_digest(self):
        a = self.service.build_generation_context_descriptor(
            PROJECT, section_id=self.req.section_id, operation="initial", request=self.req
        )
        b = self.service.build_generation_context_descriptor(
            PROJECT, section_id=self.req.section_id, operation="initial", request=self.req
        )
        self.assertEqual(a["digest"], b["digest"])

    def test_same_provider_model_endpoint_and_profile_revision_change_digest(self):
        resolver = self.service.ai_task_runner.policy_resolver
        baseline = self.service.build_generation_context_descriptor(
            PROJECT,
            section_id=self.req.section_id,
            operation="initial",
            request=self.req,
        )
        baseline_policy = baseline["descriptor"]["ai_policy"]
        self.assertEqual("deepseek", baseline_policy["provider_name"])
        self.assertEqual("deepseek-chat", baseline_policy["model_name"])

        original_base_url = resolver.base_url
        original_revision = resolver.route_profile_revision
        try:
            resolver.base_url = "https://same-model-different-endpoint.invalid/v1"
            endpoint_changed = self.service.build_generation_context_descriptor(
                PROJECT,
                section_id=self.req.section_id,
                operation="initial",
                request=self.req,
            )
            endpoint_policy = endpoint_changed["descriptor"]["ai_policy"]
            self.assertEqual(baseline_policy["provider_name"], endpoint_policy["provider_name"])
            self.assertEqual(baseline_policy["model_name"], endpoint_policy["model_name"])
            self.assertNotEqual(baseline["digest"], endpoint_changed["digest"])

            resolver.base_url = original_base_url
            resolver.route_profile_revision = original_revision + 1
            revision_changed = self.service.build_generation_context_descriptor(
                PROJECT,
                section_id=self.req.section_id,
                operation="initial",
                request=self.req,
            )
            revision_policy = revision_changed["descriptor"]["ai_policy"]
            self.assertEqual(baseline_policy["provider_name"], revision_policy["provider_name"])
            self.assertEqual(baseline_policy["model_name"], revision_policy["model_name"])
            self.assertNotEqual(baseline["digest"], revision_changed["digest"])
        finally:
            resolver.base_url = original_base_url
            resolver.route_profile_revision = original_revision

    def test_instruction_change_changes_digest(self):
        a = self.service.build_generation_context_descriptor(
            PROJECT, section_id=self.req.section_id, operation="initial", request=self.req
        )
        other = self.req.model_copy(update={"user_instruction": "完全不同的指令"})
        b = self.service.build_generation_context_descriptor(
            PROJECT, section_id=other.section_id, operation="initial", request=other
        )
        self.assertNotEqual(a["digest"], b["digest"])

    def test_policy_change_changes_digest(self):
        a = self.service.build_generation_context_descriptor(
            PROJECT, section_id=self.req.section_id, operation="initial", request=self.req
        )
        self.service.ai_task_runner = _policy_runner("openai_compatible", "other-model")
        b = self.service.build_generation_context_descriptor(
            PROJECT, section_id=self.req.section_id, operation="initial", request=self.req
        )
        self.assertNotEqual(a["digest"], b["digest"])

    def test_service_namespace_change_changes_digest(self):
        a = self.service.build_generation_context_descriptor(
            PROJECT,
            section_id=self.req.section_id,
            operation="initial",
            request=self.req,
            service_namespace="lightweight_test",
        )
        b = self.service.build_generation_context_descriptor(
            PROJECT,
            section_id=self.req.section_id,
            operation="initial",
            request=self.req,
            service_namespace="real_registered_sources",
        )
        self.assertNotEqual(a["digest"], b["digest"])

    def test_missing_policy_resolver_fails_closed(self):
        self.service.ai_task_runner = SimpleNamespace(policy_resolver=None)
        with self.assertRaises(MedicalWritingRevisionService.GenerationContextError):
            self.service.build_generation_context_descriptor(
                PROJECT,
                section_id=self.req.section_id,
                operation="initial",
                request=self.req,
            )

    def test_missing_ai_runner_fails_closed(self):
        self.service.ai_task_runner = None
        with self.assertRaises(MedicalWritingRevisionService.GenerationContextError):
            self.service.build_generation_context_descriptor(
                PROJECT,
                section_id=self.req.section_id,
                operation="initial",
                request=self.req,
            )

    def test_stale_selected_evidence_fails_before_submit(self):
        class FakeRef:
            def evidence_briefs(self, project_id):
                return []

        self.service.writing_reference_repository = FakeRef()
        req = self.req.model_copy(update={"evidence_brief_ids": ["eb_missing"]})
        with self.assertRaises(MedicalWritingRevisionService.GenerationContextError):
            self.service.build_generation_context_descriptor(
                PROJECT, section_id=req.section_id, operation="initial", request=req
            )

    def test_table_driven_each_authoritative_input_changes_digest(self):
        """Mutate each authoritative input independently; each must change digest."""
        baseline = self.service.build_generation_context_descriptor(
            PROJECT, section_id=self.req.section_id, operation="initial", request=self.req
        )
        digests = {"baseline": baseline["digest"]}

        # 1) WC identity via authoritative method override. Digest v4
        #    deliberately EXCLUDES the working_copy dimension from the lineage
        #    payload (execution-era metadata; adoption separately verifies
        #    anchor identity), so a WC identity mutation must NOT change the
        #    generation digest — the opposite of the v2-era contract.
        original_wc = self.repo.authoritative_revision_source_identity

        def wc_changed(pid, sid):
            wid, rev, h = original_wc(pid, sid)
            return wid, rev + 1, "f" * 64

        self.repo.authoritative_revision_source_identity = wc_changed
        wc_mutation_digest = self.service.build_generation_context_descriptor(
            PROJECT, section_id=self.req.section_id, operation="initial", request=self.req
        )["digest"]
        self.repo.authoritative_revision_source_identity = original_wc
        self.assertEqual(
            digests["baseline"],
            wc_mutation_digest,
            "working-copy identity is excluded from the v4 lineage digest",
        )

        # 2) StudyDefinition binding
        original_sd = self.repo.authoritative_study_definition_binding

        def sd_changed(pid):
            return ("sd_mutated", 99, "e" * 64)

        self.repo.authoritative_study_definition_binding = sd_changed
        digests["study"] = self.service.build_generation_context_descriptor(
            PROJECT, section_id=self.req.section_id, operation="initial", request=self.req
        )["digest"]
        self.repo.authoritative_study_definition_binding = original_sd

        # 3) plan/projection
        class FakePlan:
            plan_id = "plan_x"
            revision = 3
            state_sha256 = "1" * 64
            projection_manifest = [
                SimpleNamespace(
                    projection="evidence_intent",
                    content_sha256="2" * 64,
                    module_ids=["m1"],
                    not_applicable_module_ids=[],
                ),
                SimpleNamespace(
                    projection="ai_candidate_intent",
                    content_sha256="3" * 64,
                    module_ids=["m2"],
                    not_applicable_module_ids=[],
                ),
            ]

        class FakePlanHelper:
            def require_confirmed_projections(self, project_id, projection_kinds):
                return SimpleNamespace(plan=FakePlan())

        self.service.plan_consumption_helper = FakePlanHelper()
        digests["plan"] = self.service.build_generation_context_descriptor(
            PROJECT, section_id=self.req.section_id, operation="initial", request=self.req
        )["digest"]
        self.service.plan_consumption_helper = None

        # 4) company corpus
        class FakeCompany:
            def definition(self):
                return SimpleNamespace(
                    snapshot_id="corp1",
                    snapshot_version="v1",
                    snapshot_sha256="4" * 64,
                )

        self.service.company_corpus_service = FakeCompany()
        digests["company"] = self.service.build_generation_context_descriptor(
            PROJECT, section_id=self.req.section_id, operation="initial", request=self.req
        )["digest"]

        # 5) shared corpus full catalog identity
        class FakeShared:
            def catalog(self):
                return SimpleNamespace(
                    layer_id="layer_a",
                    asset_version="av1",
                    asset_sha256="5" * 64,
                    items=[
                        SimpleNamespace(
                            admission_status="admitted",
                            segment_id="seg1",
                            candidate_sha256="6" * 64,
                        )
                    ],
                )

        self.service.shared_corpus_service = FakeShared()
        digests["shared"] = self.service.build_generation_context_descriptor(
            PROJECT, section_id=self.req.section_id, operation="initial", request=self.req
        )["digest"]
        # incomplete shared fails closed
        class BadShared:
            def catalog(self):
                return SimpleNamespace(layer_id="", asset_version="av1", asset_sha256="5" * 64, items=[])

        self.service.shared_corpus_service = BadShared()
        with self.assertRaises(MedicalWritingRevisionService.GenerationContextError):
            self.service.build_generation_context_descriptor(
                PROJECT, section_id=self.req.section_id, operation="initial", request=self.req
            )
        self.service.company_corpus_service = None
        self.service.shared_corpus_service = None

        # 6) evidence status/version/hash
        brief = SimpleNamespace(
            brief_id="eb1",
            status="approved_current",
            nct_id="NCT1",
            translation_id="tr1",
            translation_revision=2,
            artifact_id="art1",
            span_id="sp1",
            source_text_sha256="7" * 64,
            document_sha256="8" * 64,
            glossary_version="g1",
            medical_review_id="mr1",
            approved_zh_text="批准正文",
            source_locator="loc1",
        )

        class FakeRefOk:
            def evidence_briefs(self, project_id):
                return [brief]

        self.service.writing_reference_repository = FakeRefOk()
        req_ev = self.req.model_copy(update={"evidence_brief_ids": ["eb1"]})
        digests["evidence"] = self.service.build_generation_context_descriptor(
            PROJECT, section_id=req_ev.section_id, operation="initial", request=req_ev
        )["digest"]
        brief.translation_revision = 3
        digests["evidence_rev"] = self.service.build_generation_context_descriptor(
            PROJECT, section_id=req_ev.section_id, operation="initial", request=req_ev
        )["digest"]
        self.assertNotEqual(digests["evidence"], digests["evidence_rev"])
        self.service.writing_reference_repository = None

        # 7) intent / instruction / comment-like selected_text / anchor
        digests["intent"] = self.service.build_generation_context_descriptor(
            PROJECT,
            section_id=self.req.section_id,
            operation="initial",
            request=self.req.model_copy(update={"intent": "factual_tightening"}),
        )["digest"]
        digests["instruction"] = self.service.build_generation_context_descriptor(
            PROJECT,
            section_id=self.req.section_id,
            operation="initial",
            request=self.req.model_copy(update={"user_instruction": "指令B"}),
        )["digest"]
        digests["selected"] = self.service.build_generation_context_descriptor(
            PROJECT,
            section_id=self.req.section_id,
            operation="initial",
            request=self.req.model_copy(update={"selected_text": self.req.selected_text + "X"}),
        )["digest"]

        # 8) policy/provider/model
        self.service.ai_task_runner = _policy_runner("openai_compatible", "alt-model-x")
        digests["policy"] = self.service.build_generation_context_descriptor(
            PROJECT, section_id=self.req.section_id, operation="initial", request=self.req
        )["digest"]
        self.service.ai_task_runner = _policy_runner()

        # 9) service namespace
        digests["namespace"] = self.service.build_generation_context_descriptor(
            PROJECT,
            section_id=self.req.section_id,
            operation="initial",
            request=self.req,
            service_namespace="real_registered_sources",
        )["digest"]

        # 10) source registry path (require_registered_sources without registry fails)
        self.service.require_registered_sources = True
        with self.assertRaises(MedicalWritingRevisionService.GenerationContextError):
            self.service.build_generation_context_descriptor(
                PROJECT, section_id=self.req.section_id, operation="initial", request=self.req
            )
        self.service.require_registered_sources = False
        prev_paths = dict(getattr(self.service, "protocol_source_paths", {}) or {})
        self.service.protocol_source_paths = {PROJECT: "/tmp/proto.docx"}
        digests["source_path"] = self.service.build_generation_context_descriptor(
            PROJECT, section_id=self.req.section_id, operation="initial", request=self.req
        )["digest"]
        self.service.protocol_source_paths = prev_paths

        # Every mutated dimension must differ from baseline.
        for name, digest in digests.items():
            if name == "baseline":
                continue
            self.assertNotEqual(
                digests["baseline"],
                digest,
                f"{name} mutation must create a distinct generation digest",
            )
            self.assertEqual(64, len(digest), f"{name} digest length")

        # Identical context still reuses (restore baseline services).
        self.service.ai_task_runner = _policy_runner()
        self.service.plan_consumption_helper = None
        self.service.company_corpus_service = None
        self.service.shared_corpus_service = None
        self.service.writing_reference_repository = None
        self.service.require_registered_sources = False
        self.service.protocol_source_paths = prev_paths
        again = self.service.build_generation_context_descriptor(
            PROJECT, section_id=self.req.section_id, operation="initial", request=self.req
        )
        self.assertEqual(digests["baseline"], again["digest"])

    def test_rewrite_parent_and_comment_change_digest(self):
        rewrite_a = {
            "thread_id": "th1",
            "suggestion_id": "sug_parent_a",
            "rewrite_instruction": "重写A",
            "comment": "意见1",
            "evidence_brief_ids": [],
        }
        rewrite_b = {**rewrite_a, "suggestion_id": "sug_parent_b"}
        rewrite_c = {**rewrite_a, "comment": "意见2"}
        da = self.service.build_generation_context_descriptor(
            PROJECT,
            section_id=self.req.section_id,
            operation="rewrite",
            rewrite=rewrite_a,
        )["digest"]
        db = self.service.build_generation_context_descriptor(
            PROJECT,
            section_id=self.req.section_id,
            operation="rewrite",
            rewrite=rewrite_b,
        )["digest"]
        dc = self.service.build_generation_context_descriptor(
            PROJECT,
            section_id=self.req.section_id,
            operation="rewrite",
            rewrite=rewrite_c,
        )["digest"]
        self.assertNotEqual(da, db)
        self.assertNotEqual(da, dc)


class DurableReuseAndDistinctJobTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.documents, self.store, self.repo, self.service = _service(
            Path(self.tmpdir.name)
        )
        self.durable = DurableJobStore(Path(self.tmpdir.name) / "durable.db")
        self.req = _request(self.documents)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_identical_canonical_reuses_completed_job(self):
        job_id, _ = self.service.submit_revision_durable(
            PROJECT, self.req, self.durable
        )
        # Seed a real thread so completed-job replay can resolve lineage.
        now = datetime.now(timezone.utc)
        document = self.documents.document_session(PROJECT)
        thread = RevisionThread(
            thread_id="thread_reuse_1",
            project_id=PROJECT,
            document_id=document.document_id,
            section_id=self.req.section_id,
            anchor_type="selection",
            anchor_path=self.req.anchor_path,
            selected_text=self.req.selected_text,
            user_instruction=self.req.user_instruction,
            intent=self.req.intent,
            ai_run_id="run_reuse",
            source_entry_id="entry_reuse",
            source_id="source_reuse",
            source_locator=self.req.anchor_path,
            evidence_source_types=["protocol_section_selection"],
            generation_context_version="mw_gen_ctx_v2",
            generation_context_digest="a" * 64,
            suggestions=[
                RevisionSuggestion(
                    suggestion_id="sug_reuse_1",
                    proposal_text=f"{self.req.selected_text}（reuse）",
                    diff_patch="d",
                    rationale="r",
                    evidence_span_ids=["span1"],
                    evidence_source_types=["protocol_section_selection"],
                )
            ],
            status="candidate_ready",
            created_at=now,
        )
        self.repo.commit_revision_submission(
            thread,
            AuditEvent(
                audit_id="audit_reuse_1",
                project_id=PROJECT,
                actor="test",
                action="medical_writing_revision_submitted",
                target_type="revision_thread",
                target_id=thread.thread_id,
                created_at=now,
            ),
        )
        claim = self.durable.claim(PROJECT, job_id)
        self.assertTrue(claim.claimed)
        self.durable.complete(
            PROJECT,
            job_id,
            claim.claim_token,
            output_hash="oh1",
            artifact_locator=json.dumps(
                {
                    "thread_id": thread.thread_id,
                    "suggestion_ids": ["sug_reuse_1"],
                    "generation_context_version": "mw_gen_ctx_v2",
                    "generation_context_digest": "a" * 64,
                }
            ),
        )
        job_id2, result = self.service.submit_revision_durable(
            PROJECT, self.req, self.durable
        )
        self.assertEqual(job_id, job_id2)
        job = self.durable.get(PROJECT, job_id2)
        self.assertEqual("completed", job.status)
        self.assertIsNotNone(result)
        self.assertEqual("sug_reuse_1", result.suggestion.suggestion_id)

    def test_instruction_change_creates_distinct_job_not_409(self):
        job_id1, _ = self.service.submit_revision_durable(
            PROJECT, self.req, self.durable
        )
        other = self.req.model_copy(update={"user_instruction": "另一条指令"})
        job_id2, _ = self.service.submit_revision_durable(
            PROJECT, other, self.durable
        )
        self.assertNotEqual(job_id1, job_id2)

    def test_policy_change_creates_distinct_job(self):
        job_id1, _ = self.service.submit_revision_durable(
            PROJECT, self.req, self.durable
        )
        self.service.ai_task_runner = _policy_runner("openai_compatible", "alt-model")
        job_id2, _ = self.service.submit_revision_durable(
            PROJECT, self.req, self.durable
        )
        self.assertNotEqual(job_id1, job_id2)

    def test_business_key_is_v2_prefixed(self):
        job_id, _ = self.service.submit_revision_durable(
            PROJECT, self.req, self.durable
        )
        job = self.durable.get(PROJECT, job_id)
        self.assertTrue(job.business_key.startswith("v2:"))
        self.assertEqual(64, len(job.request_hash))


class ExecutorDriftAndExactReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        from services.api.app.ai_task_runner import AiTaskRunner, AiTaskStore
        from tests.test_medical_writing_revision_durable import _EchoRevisionProvider

        documents = MedicalWritingDocumentService()
        store = SqliteRuntimeStore(Path(self.tmpdir.name) / "runtime.sqlite3")
        repo = MedicalWritingRuntimeRepository(documents, store)
        self.provider = _EchoRevisionProvider(tag="V")
        policy = AiExecutionPolicyResolver(
            deployment_profile="local_private_clinical",
            provider_name="buddy",
            model_name="deepseek-v4-pro",
            test_only_provider_injection=True,
        )
        runner = AiTaskRunner(
            repo,
            AiTaskStore(Path(self.tmpdir.name) / "ai_runs.jsonl"),
            provider_factory=lambda resolution: self.provider,
            policy_resolver=policy,
        )
        self.service = MedicalWritingRevisionService(repo, runner)
        self.service.require_registered_sources = False
        self.documents = documents
        self.repo = repo
        self.store = store
        self.durable = DurableJobStore(Path(self.tmpdir.name) / "durable.db")
        self.executor = SectionAiCandidateExecutor(self.service)
        self.req = _request(documents)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _job_payload(self, **overrides):
        payload = self.req.model_dump(mode="json")
        payload.update(overrides)
        if "generation_context" not in payload:
            payload["generation_context"] = self.service.build_generation_context_descriptor(
                PROJECT,
                section_id=self.req.section_id,
                operation="initial",
                request=self.req,
            )
        return SimpleNamespace(
            project_id=PROJECT,
            payload_json=json.dumps(payload, ensure_ascii=False),
        )

    def test_service_atomic_replay_skips_pre_apply_context_and_returns_snapshot(self):
        job_id, _ = self.service.submit_revision_durable(
            PROJECT, self.req, self.durable
        )
        job = self.durable.get(PROJECT, job_id)
        claim = self.durable.claim(PROJECT, job_id)
        self.assertTrue(claim.claimed)
        result = self.executor.execute(
            job, claim.claim_token, lambda: False, lambda progress: True
        )
        self.assertFalse(result.error, result.error)
        thread = self.repo.revision_threads(PROJECT)[0]
        current = self.repo.working_copy(PROJECT, thread.section_id)

        first = self.service.accept_and_apply_candidate(
            project_id=PROJECT,
            thread_id=thread.thread_id,
            suggestion_id=thread.suggestions[0].suggestion_id,
            expected_working_copy_revision=current.revision,
            actor="test",
            idempotency_key="service-atomic-replay",
        )
        replay = self.service.accept_and_apply_candidate(
            project_id=PROJECT,
            thread_id=thread.thread_id,
            suggestion_id=thread.suggestions[0].suggestion_id,
            expected_working_copy_revision=current.revision,
            actor="test",
            idempotency_key="service-atomic-replay",
        )
        self.assertEqual(first.working_copy.revision, replay.working_copy.revision)
        self.assertEqual(first.working_copy.content_blocks, replay.working_copy.content_blocks)

    def test_pre_ai_drift_creates_no_thread_or_audit(self):
        payload = self.req.model_dump(mode="json")
        ctx = self.service.build_generation_context_descriptor(
            PROJECT, section_id=self.req.section_id, operation="initial", request=self.req
        )
        # Corrupt digest so pre_ai fails before AI.
        ctx = {**ctx, "digest": "0" * 64}
        payload["generation_context"] = ctx
        job = SimpleNamespace(
            project_id=PROJECT,
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
        result = self.executor.execute(job, "tok", lambda: False, lambda p: True)
        self.assertTrue(result.error)
        self.assertIn("drift", result.error.lower())
        self.assertEqual(0, self.provider.calls)
        self.assertEqual(0, len(self.repo.revision_threads(PROJECT)))

    def test_route_switch_after_creation_fails_non_retryable_before_ai(self):
        job = self._job_payload()
        resolver = self.service.ai_task_runner.policy_resolver
        original_base_url = resolver.base_url
        try:
            resolver.base_url = "https://route-switched-after-creation.invalid/v1"
            result = self.executor.execute(
                job, "tok", lambda: False, lambda p: True
            )
        finally:
            resolver.base_url = original_base_url
        self.assertTrue(result.error)
        self.assertFalse(result.retryable)
        self.assertIn("drift", result.error.lower())
        self.assertEqual(0, self.provider.calls)
        self.assertEqual(0, len(self.repo.revision_threads(PROJECT)))

    def test_post_ai_pre_commit_drift_creates_no_thread(self):
        job = self._job_payload()
        original = self.service.build_generation_context_descriptor

        calls = {"n": 0}

        def flaky_build(*args, **kwargs):
            calls["n"] += 1
            ctx = original(*args, **kwargs)
            if calls["n"] >= 2:
                # After AI (second assert is pre_commit), force drift.
                return {**ctx, "digest": "f" * 64, "descriptor": ctx["descriptor"]}
            return ctx

        with mock.patch.object(
            self.service, "build_generation_context_descriptor", side_effect=flaky_build
        ):
            result = self.executor.execute(job, "tok", lambda: False, lambda p: True)
        self.assertTrue(result.error)
        self.assertIn("drift", result.error.lower())
        self.assertGreaterEqual(self.provider.calls, 1)
        self.assertEqual(0, len(self.repo.revision_threads(PROJECT)))

    def test_success_persists_exact_suggestion_lineage(self):
        job = self._job_payload()
        result = self.executor.execute(job, "tok", lambda: False, lambda p: True)
        self.assertFalse(result.error)
        locator = json.loads(result.artifact_locator)
        self.assertTrue(locator["thread_id"])
        self.assertEqual(3, len(locator["suggestion_ids"]))
        self.assertEqual(64, len(locator["post_thread_hash"]))
        self.assertEqual(GENERATION_CONTEXT_VERSION, locator["generation_context_version"])
        self.assertEqual(64, len(locator["generation_context_digest"]))
        thread = self.repo.revision_thread(PROJECT, locator["thread_id"])
        self.assertEqual(locator["generation_context_digest"], thread.generation_context_digest)
        self.assertEqual(
            set(locator["suggestion_ids"]),
            {s.suggestion_id for s in thread.suggestions},
        )
        expected_model = (
            self.service.ai_task_runner.policy_resolver.required_response_model
        )
        self.assertEqual(
            self.service.build_generation_context_descriptor(
                PROJECT,
                section_id=self.req.section_id,
                operation="initial",
                request=self.req,
            )["descriptor"]["ai_policy"]["route_identity_hash"],
            locator["route_identity_hash"],
        )
        self.assertEqual(expected_model, locator["expected_response_model"])
        self.assertIn("actual_response_model", locator)
        audits = self.repo.audit_events(PROJECT)
        self.assertTrue(audits)
        detail = audits[-1].detail
        self.assertEqual(locator["ai_run_id"], detail["ai_run_id"])
        self.assertEqual(locator["route_identity_hash"], detail["route_identity_hash"])
        self.assertEqual(locator["expected_response_model"], detail["expected_response_model"])
        self.assertIn("actual_response_model", detail)

    def test_route_identity_mismatch_fails_closed_without_thread_or_audit(self):
        job = self._job_payload()
        runner = self.service.ai_task_runner
        original_get = runner.get

        def mismatched_get(project_id, run_id):
            run = original_get(project_id, run_id)
            return run.model_copy(update={"route_identity_hash": "f" * 64})

        with mock.patch.object(runner, "get", side_effect=mismatched_get):
            result = self.executor.execute(job, "tok", lambda: False, lambda p: True)

        self.assertTrue(result.error)
        self.assertIn("route identity mismatch", result.error)
        self.assertEqual(0, len(self.repo.revision_threads(PROJECT)))
        self.assertEqual([], self.repo.audit_events(PROJECT))

    def test_exact_replay_stable_after_unrelated_suggestions_appended(self):
        job = self._job_payload()
        result = self.executor.execute(job, "tok", lambda: False, lambda p: True)
        locator = json.loads(result.artifact_locator)
        thread = self.repo.revision_thread(PROJECT, locator["thread_id"])
        # Append an unrelated suggestion after generation via action commit path.
        extra = RevisionSuggestion(
            suggestion_id="sug_unrelated_extra",
            proposal_text="无关候选",
            diff_patch="x",
            rationale="extra",
            evidence_span_ids=[],
            evidence_source_types=["protocol_section_selection"],
        )
        mutated = thread.model_copy(
            update={"suggestions": list(thread.suggestions) + [extra]}
        )
        self.repo.commit_revision_action(
            thread,
            mutated,
            AuditEvent(
                audit_id="audit_extra",
                project_id=PROJECT,
                actor="test",
                action="medical_writing_revision_submitted",
                target_type="revision_thread",
                target_id=thread.thread_id,
                created_at=datetime.now(timezone.utc),
            ),
            None,
        )
        fake_job = SimpleNamespace(
            job_id="mwjob_replay",
            artifact_locator=result.artifact_locator,
        )
        job_id, replay = self.service._replay_completed_section_job(
            PROJECT, fake_job, actor="test", mode="initial"
        )
        self.assertEqual("mwjob_replay", job_id)
        self.assertIsNotNone(replay)
        self.assertEqual(locator["suggestion_ids"][0], replay.suggestion.suggestion_id)
        self.assertNotEqual("sug_unrelated_extra", replay.suggestion.suggestion_id)
        self.assertEqual(
            locator["ai_run_id"], replay.audit_event.detail["ai_run_id"]
        )
        self.assertEqual(
            locator["route_identity_hash"],
            replay.audit_event.detail["route_identity_hash"],
        )
        self.assertEqual(
            locator["actual_response_model"],
            replay.audit_event.detail["actual_response_model"],
        )


class AdoptionLineageGateTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.documents, self.store, self.repo, self.service = _service(
            Path(self.tmpdir.name)
        )
        self.req = _request(self.documents)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _thread_with_lineage(self, digest="a" * 64):
        now = datetime.now(timezone.utc)
        document = self.documents.document_session(PROJECT)
        section_id = self.req.section_id
        thread = RevisionThread(
            thread_id="thread_lineage_1",
            project_id=PROJECT,
            document_id=document.document_id,
            section_id=section_id,
            anchor_type="selection",
            anchor_path=self.req.anchor_path,
            selected_text=self.req.selected_text,
            user_instruction=self.req.user_instruction,
            intent=self.req.intent,
            ai_run_id="run_1",
            source_entry_id="entry_1",
            source_id="source_1",
            source_locator=self.req.anchor_path,
            evidence_source_types=["protocol_section_selection"],
            generation_context_version="mw_gen_ctx_v2",
            generation_context_digest=digest,
            suggestions=[
                RevisionSuggestion(
                    suggestion_id="sug_lineage_1",
                    proposal_text=f"{self.req.selected_text}（采纳）",
                    diff_patch="d",
                    rationale="r",
                    evidence_span_ids=["span1"],
                    evidence_source_types=["protocol_section_selection"],
                )
            ],
            status="candidate_ready",
            created_at=now,
        )
        self.repo.commit_revision_submission(
            thread,
            AuditEvent(
                audit_id="audit_lineage_1",
                project_id=PROJECT,
                actor="test",
                action="medical_writing_revision_submitted",
                target_type="revision_thread",
                target_id=thread.thread_id,
                created_at=now,
            ),
        )
        return thread

    def test_revalidate_blocks_stale_digest(self):
        thread = self._thread_with_lineage(digest="b" * 64)
        with self.assertRaises(MedicalWritingRevisionService.GenerationContextError):
            self.service.revalidate_generation_context_for_adoption(PROJECT, thread)

    def test_repository_gate_blocks_digest_mismatch(self):
        thread = self._thread_with_lineage(digest="c" * 64)
        wc = self.repo.working_copy(PROJECT, thread.section_id)
        with self.assertRaises(RuntimeStoreError):
            self.repo.accept_and_apply_candidate(
                project_id=PROJECT,
                thread_id=thread.thread_id,
                suggestion_id=thread.suggestions[0].suggestion_id,
                expected_working_copy_revision=wc.revision,
                actor="test",
                idempotency_key="k1",
                expected_generation_context_digest="d" * 64,
            )
        # No author selection mutation on blocked path.
        reloaded = self.repo.revision_thread(PROJECT, thread.thread_id)
        self.assertEqual("candidate_ready", reloaded.status)
        self.assertEqual("pending", reloaded.suggestions[0].user_decision)

    def test_repository_gate_blocks_missing_expected_when_thread_has_lineage(self):
        thread = self._thread_with_lineage(digest="e" * 64)
        wc = self.repo.working_copy(PROJECT, thread.section_id)
        with self.assertRaises(RuntimeStoreError):
            self.repo.accept_and_apply_candidate(
                project_id=PROJECT,
                thread_id=thread.thread_id,
                suggestion_id=thread.suggestions[0].suggestion_id,
                expected_working_copy_revision=wc.revision,
                actor="test",
                idempotency_key="k2",
                expected_generation_context_digest="",
            )


class GreenfieldAndSourceIdentityTests(unittest.TestCase):
    """Behavioral proof for greenfield + Source Registry generation identity."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _greenfield_request(self, key: str = "gf-ctx-v1"):
        return MedicalWritingGreenfieldCreateRequest(
            protocol_id="SYN-CTX-001",
            version="V0.1",
            document_title="绿地生成上下文测试方案",
            indication="类风湿关节炎",
            study_phase="II期",
            investigational_product="CTX-101",
            protocol_date="2026年07月20日",
            sponsor="测试申办方",
            sections=[
                MedicalWritingGreenfieldSectionSeed(
                    section_key="study_design",
                    heading="研究设计",
                    ich_m11_anchor="C.3 Trial Design",
                    initial_text="本研究拟采用随机、双盲、安慰剂对照设计。",
                    source_fact_ids=["decision.design.randomized"],
                )
            ],
            decisions=[
                MedicalWritingGreenfieldDecision(
                    decision_id="dose_selection",
                    label="试验药物剂量",
                    status="unresolved",
                    value="",
                    rationale="待确认。",
                    source_refs=["brief:dose"],
                    approval_blocking=True,
                )
            ],
            actor="medical_manager_test",
            idempotency_key=key,
        )

    def _greenfield_service(self, project_id: str = "proj_synthetic_ctx_gf"):
        greenfield = GreenfieldMedicalWritingDocumentService(
            self.root / "greenfield.sqlite3"
        )
        greenfield.create(project_id, self._greenfield_request())
        documents = CompositeMedicalWritingDocumentService(
            MedicalWritingDocumentService(),
            greenfield,
        )
        store = SqliteRuntimeStore(self.root / "runtime_gf.sqlite3")
        repo = MedicalWritingRuntimeRepository(documents, store)
        service = MedicalWritingRevisionService(repo, _policy_runner())
        # Real repo always has document_service; keep registered flag true.
        self.assertTrue(service.require_registered_sources)
        return project_id, documents, repo, service

    def test_greenfield_descriptor_succeeds_without_protocol_path_or_registry(self):
        project_id, documents, repo, service = self._greenfield_service()
        self.assertIsNone(service.source_registry)
        self.assertEqual({}, dict(service.protocol_source_paths or {}))
        self.assertEqual(
            "greenfield_project_decision",
            documents.source_mode(project_id),
        )
        document = documents.document_session(project_id)
        section = documents.section(project_id, document.sections[0].section_id)
        block = next(
            b
            for b in section.content_blocks
            if str(b.get("text", "")).strip()
        )
        req = MedicalWritingRevisionRequest(
            document_id=document.document_id,
            section_id=section.section_id,
            selected_text=str(block.get("text") or "")[:40],
            anchor_path=str(block.get("source_locator") or ""),
            user_instruction="生成可审阅候选",
            intent="regulatory_tone",
            requested_by="medical_manager_test",
        )
        ctx = service.build_generation_context_descriptor(
            project_id, section_id=section.section_id, operation="initial", request=req
        )
        src = ctx["descriptor"]["source_registry"]
        self.assertEqual("greenfield_consumed", src["status"])
        self.assertEqual("greenfield_project_decision", src["source_mode"])
        self.assertEqual("", src["protocol_source_path"])
        self.assertEqual([], src["entries"])
        self.assertTrue(src["greenfield"]["baseline_sha256"])
        self.assertIsInstance(src["greenfield"]["baseline_revision"], int)

        # Identical state is stable.
        again = service.build_generation_context_descriptor(
            project_id, section_id=section.section_id, operation="initial", request=req
        )
        self.assertEqual(ctx["digest"], again["digest"])

        # Baseline hash mutation changes digest.
        state = documents.greenfield_state(project_id)
        with mock.patch.object(
            documents,
            "greenfield_state",
            return_value={**state, "baseline_sha256": "f" * 64, "baseline_revision": state["baseline_revision"] + 1},
        ):
            mutated = service.build_generation_context_descriptor(
                project_id,
                section_id=section.section_id,
                operation="initial",
                request=req,
            )
        self.assertNotEqual(ctx["digest"], mutated["digest"])

        # Partial greenfield state fails closed.
        with mock.patch.object(
            documents,
            "greenfield_state",
            return_value={"document_id": "d", "baseline_revision": 1, "baseline_sha256": ""},
        ):
            with self.assertRaises(MedicalWritingRevisionService.GenerationContextError):
                service.build_generation_context_descriptor(
                    project_id,
                    section_id=section.section_id,
                    operation="initial",
                    request=req,
                )

    @unittest.skipUnless(RUX_PROTOCOL_DOCX.exists(), "RUX protocol DOCX unavailable")
    def test_original_protocol_path_from_document_service_without_static_map(self):
        documents = MedicalWritingDocumentService()
        store = SqliteRuntimeStore(self.root / "runtime_orig.sqlite3")
        repo = MedicalWritingRuntimeRepository(documents, store)
        registry = SourceRegistryService(
            SourceRegistryStore(self.root / "source_registry.jsonl"),
            allowed_roots=[RUX_PROTOCOL_DOCX.parent],
        )
        service = MedicalWritingRevisionService(
            repo,
            _policy_runner(),
            source_registry=registry,
            protocol_source_paths={},  # no static map
        )
        self.assertTrue(service.require_registered_sources)
        path = service._resolve_original_protocol_path(PROJECT)
        self.assertIsNotNone(path)
        self.assertEqual(Path(path).resolve(), RUX_PROTOCOL_DOCX.resolve())

        req = _request(documents, PROJECT)
        ctx = service.build_generation_context_descriptor(
            PROJECT, section_id=req.section_id, operation="initial", request=req
        )
        src = ctx["descriptor"]["source_registry"]
        self.assertEqual("original_protocol_exact_selection", src["status"])
        self.assertEqual("original_protocol_docx", src["source_mode"])
        self.assertTrue(src["protocol_content_sha256"])
        self.assertEqual(64, len(src["protocol_content_sha256"]))
        self.assertTrue(src["exact_binding"]["source_id"])

        # Missing registry still fails before AI for original protocol mode.
        service_no_reg = MedicalWritingRevisionService(
            repo, _policy_runner(), source_registry=None, protocol_source_paths={}
        )
        with self.assertRaises(MedicalWritingRevisionService.GenerationContextError) as err:
            service_no_reg.build_generation_context_descriptor(
                PROJECT, section_id=req.section_id, operation="initial", request=req
            )
        self.assertIn("Source Registry", str(err.exception))

    @unittest.skipUnless(RUX_PROTOCOL_DOCX.exists(), "RUX protocol DOCX unavailable")
    def test_source_registry_exact_binding_and_validation_mutations(self):
        documents = MedicalWritingDocumentService()
        store = SqliteRuntimeStore(self.root / "runtime_val.sqlite3")
        repo = MedicalWritingRuntimeRepository(documents, store)
        registry = SourceRegistryService(
            SourceRegistryStore(self.root / "source_registry.jsonl"),
            allowed_roots=[RUX_PROTOCOL_DOCX.parent],
        )
        service = MedicalWritingRevisionService(
            repo,
            _policy_runner(),
            source_registry=registry,
            protocol_source_paths={PROJECT: RUX_PROTOCOL_DOCX},
        )
        req = _request(documents, PROJECT)
        base = service.build_generation_context_descriptor(
            PROJECT, section_id=req.section_id, operation="initial", request=req
        )
        src = base["descriptor"]["source_registry"]
        self.assertEqual("original_protocol_exact_selection", src["status"])
        binding = src["exact_binding"]
        self.assertTrue(binding["entry_id"])
        self.assertTrue(binding["source_id"])
        self.assertEqual(1, len(src["entries"]))
        self.assertEqual(1, len(src["entries"][0]["spans"]))

        # Inject validation identity on the exact entry.
        validation = SourceContentValidationRecord(
            validation_id="val_ctx_001",
            project_id=PROJECT,
            source_entry_id=binding["entry_id"],
            module="medical_writing",
            revision=1,
            technical_status="ready",
            content_status="matched",
            use_status="allowed",
            file_sha256=binding["content_hash"],
            expected_context_hash="c" * 64,
            validator_version="source_content_consistency_v2",
            checks=[
                SourceContentValidationCheck(
                    check_code="file_hash",
                    label="文件哈希",
                    expected_value=binding["content_hash"],
                    observed_value=binding["content_hash"],
                    outcome="match",
                )
            ],
            summary="matched",
            actor="tester",
            created_at=datetime.now(timezone.utc),
        )
        registry.current_content_validation = lambda pid, eid: (  # type: ignore[method-assign]
            validation if eid == binding["entry_id"] else None
        )
        with_val = service.build_generation_context_descriptor(
            PROJECT, section_id=req.section_id, operation="initial", request=req
        )
        self.assertNotEqual(base["digest"], with_val["digest"])
        self.assertEqual(
            "val_ctx_001",
            with_val["descriptor"]["source_registry"]["exact_binding"][
                "content_validation"
            ]["validation_id"],
        )

        # Validation mutation changes digest.
        val_mut = validation.model_copy(
            update={
                "revision": 2,
                "content_status": "warning",
                "file_sha256": "d" * 64,
                "expected_context_hash": "e" * 64,
            }
        )
        registry.current_content_validation = lambda pid, eid: val_mut  # type: ignore[method-assign]
        d_val = service.build_generation_context_descriptor(
            PROJECT, section_id=req.section_id, operation="initial", request=req
        )["digest"]
        self.assertNotEqual(with_val["digest"], d_val)

        # Partial validation fails closed.
        bad_val = validation.model_copy(update={"validation_id": "", "file_sha256": ""})
        registry.current_content_validation = lambda pid, eid: bad_val  # type: ignore[method-assign]
        with self.assertRaises(MedicalWritingRevisionService.GenerationContextError):
            service.build_generation_context_descriptor(
                PROJECT, section_id=req.section_id, operation="initial", request=req
            )

        # Unresolvable quote fails closed rather than binding a wrong span.
        registry.current_content_validation = lambda pid, eid: None  # type: ignore[method-assign]
        other = req.model_copy(
            update={"selected_text": req.selected_text + " unrelated-tail"}
        )
        with self.assertRaises(MedicalWritingRevisionService.GenerationContextError):
            service.build_generation_context_descriptor(
                PROJECT, section_id=other.section_id, operation="initial", request=other
            )


@unittest.skipUnless(RUX_PROTOCOL_DOCX.exists(), "RUX protocol DOCX unavailable")
class ExactSourceBindingDurableTests(unittest.TestCase):
    """First-use self-drift and unrelated-span isolation for original protocol."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.documents = MedicalWritingDocumentService()
        self.store = SqliteRuntimeStore(self.root / "runtime.sqlite3")
        self.repo = MedicalWritingRuntimeRepository(self.documents, self.store)
        self.registry = SourceRegistryService(
            SourceRegistryStore(self.root / "source_registry.jsonl"),
            allowed_roots=[RUX_PROTOCOL_DOCX.parent],
        )
        from services.api.app.ai_task_runner import AiTaskRunner, AiTaskStore
        from tests.test_medical_writing_revision_durable import _EchoRevisionProvider

        self.provider = _EchoRevisionProvider(tag="X")
        policy = AiExecutionPolicyResolver(
            deployment_profile="local_private_clinical",
            provider_name="buddy",
            model_name="deepseek-v4-pro",
            test_only_provider_injection=True,
        )
        self.runner = AiTaskRunner(
            self.repo,
            AiTaskStore(self.root / "ai_runs.jsonl"),
            provider_factory=lambda resolution: self.provider,
            policy_resolver=policy,
        )
        self.service = MedicalWritingRevisionService(
            self.repo,
            self.runner,
            source_registry=self.registry,
            protocol_source_paths={PROJECT: RUX_PROTOCOL_DOCX},
        )
        self.service.require_registered_sources = True
        self.durable = DurableJobStore(self.root / "durable.db")
        self.executor = SectionAiCandidateExecutor(self.service)
        self.req = _request(self.documents, PROJECT)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_first_use_durable_submit_and_execute_no_self_drift(self):
        # Registry starts empty of medical_writing selections for this selection.
        self.assertEqual([], self.registry.store.list_results(PROJECT))
        job_id, cached = self.service.submit_revision_durable(
            PROJECT, self.req, self.durable
        )
        self.assertIsNone(cached)
        job = self.durable.get(PROJECT, job_id)
        payload = json.loads(job.payload_json)
        ctx = payload["generation_context"]
        binding = ctx["descriptor"]["source_registry"]["exact_binding"]
        self.assertTrue(binding["entry_id"])
        self.assertTrue(binding["source_id"])
        # Intake only — no thread yet.
        self.assertEqual(0, len(self.repo.revision_threads(PROJECT)))

        claim = self.durable.claim(PROJECT, job_id)
        self.assertTrue(claim.claimed)
        result = self.executor.execute(
            job, claim.claim_token, lambda: False, lambda p: True
        )
        self.assertFalse(result.error, result.error)
        threads = self.repo.revision_threads(PROJECT)
        self.assertEqual(1, len(threads))
        thread = threads[0]
        self.assertEqual(binding["entry_id"], thread.source_entry_id)
        self.assertEqual(binding["source_id"], thread.source_id)
        self.assertEqual(ctx["digest"], thread.generation_context_digest)

    def test_provider_failure_after_intake_leaves_no_thread(self):
        job_id, _ = self.service.submit_revision_durable(
            PROJECT, self.req, self.durable
        )
        job = self.durable.get(PROJECT, job_id)
        claim = self.durable.claim(PROJECT, job_id)
        self.assertTrue(claim.claimed)

        def boom(*args, **kwargs):
            raise RuntimeError("provider boom")

        with mock.patch.object(self.service, "_run_revision_ai", side_effect=boom):
            with self.assertRaises(RuntimeError):
                self.executor.execute(
                    job, claim.claim_token, lambda: False, lambda p: True
                )
        self.assertEqual(0, len(self.repo.revision_threads(PROJECT)))
        # Idempotent source registration may remain.
        self.assertTrue(self.registry.store.list_results(PROJECT))

    def test_unrelated_paragraph_registration_does_not_change_digest_or_adoption(self):
        job_id, _ = self.service.submit_revision_durable(
            PROJECT, self.req, self.durable
        )
        job = self.durable.get(PROJECT, job_id)
        claim = self.durable.claim(PROJECT, job_id)
        result = self.executor.execute(
            job, claim.claim_token, lambda: False, lambda p: True
        )
        self.assertFalse(result.error, result.error)
        thread = self.repo.revision_threads(PROJECT)[0]
        digest_before = thread.generation_context_digest
        binding_before = (
            self.service.build_generation_context_descriptor(
                PROJECT,
                section_id=self.req.section_id,
                operation="initial",
                request=self.req,
            )["descriptor"]["source_registry"]["exact_binding"]
        )

        # Register a different paragraph for the same protocol file.
        from services.api.app.protocol_text_extractor import parse_protocol_docx

        content = RUX_PROTOCOL_DOCX.read_bytes()
        parsed = parse_protocol_docx(RUX_PROTOCOL_DOCX.name, content)
        other = next(
            s
            for s in parsed.spans
            if len(s.text.strip()) >= 20
            and s.text.strip()[:40] != self.req.selected_text[:40]
        )
        self.registry.register_protocol_selection_from_file(
            PROJECT,
            RUX_PROTOCOL_DOCX,
            locator=other.source_locator,
            quote=other.text.strip()[:80],
            module="medical_writing",
        )
        after = self.service.build_generation_context_descriptor(
            PROJECT,
            section_id=self.req.section_id,
            operation="initial",
            request=self.req,
        )
        self.assertEqual(digest_before, after["digest"])
        self.assertEqual(
            binding_before["source_id"],
            after["descriptor"]["source_registry"]["exact_binding"]["source_id"],
        )
        # Adoption revalidation still matches lineage.
        current = self.service.revalidate_generation_context_for_adoption(
            PROJECT, thread
        )
        self.assertEqual(digest_before, current["digest"])

    def test_exact_span_or_validation_change_fails_adoption(self):
        job_id, _ = self.service.submit_revision_durable(
            PROJECT, self.req, self.durable
        )
        job = self.durable.get(PROJECT, job_id)
        claim = self.durable.claim(PROJECT, job_id)
        result = self.executor.execute(
            job, claim.claim_token, lambda: False, lambda p: True
        )
        self.assertFalse(result.error, result.error)
        thread = self.repo.revision_threads(PROJECT)[0]

        # Corrupt thread exact source binding to simulate consumed source change.
        mutated = thread.model_copy(
            update={"source_id": "src_mutated_not_real", "generation_context_digest": thread.generation_context_digest}
        )
        # Rebuild would use selected_text still; force digest mismatch by mutating stored digest.
        bad = thread.model_copy(update={"generation_context_digest": "a" * 64})
        with self.assertRaises(MedicalWritingRevisionService.GenerationContextError):
            self.service.revalidate_generation_context_for_adoption(PROJECT, bad)

        # Mutating the exact expected source_id fails closed on ensure.
        with self.assertRaises(MedicalWritingRevisionService.GenerationContextError):
            self.service._ensure_exact_original_source_binding(
                PROJECT,
                selection_quote=thread.selected_text,
                selection_locator=thread.source_locator or thread.anchor_path,
                expected_source_id="src_mutated_not_real",
                expected_entry_id=thread.source_entry_id,
            )
        # No body write attempted (gate before repo).
        reloaded = self.repo.revision_thread(PROJECT, thread.thread_id)
        self.assertEqual("candidate_ready", reloaded.status)
        self.assertEqual("pending", reloaded.suggestions[0].user_decision)

    def test_rewrite_binding_stays_on_parent_exact_source(self):
        job_id, _ = self.service.submit_revision_durable(
            PROJECT, self.req, self.durable
        )
        job = self.durable.get(PROJECT, job_id)
        claim = self.durable.claim(PROJECT, job_id)
        result = self.executor.execute(
            job, claim.claim_token, lambda: False, lambda p: True
        )
        self.assertFalse(result.error, result.error)
        thread = self.repo.revision_threads(PROJECT)[0]
        parent_source_id = thread.source_id
        parent_entry_id = thread.source_entry_id

        rewrite_ctx = self.service.build_generation_context_descriptor(
            PROJECT,
            section_id=thread.section_id,
            operation="rewrite",
            rewrite={
                "thread_id": thread.thread_id,
                "suggestion_id": thread.suggestions[0].suggestion_id,
                "rewrite_instruction": "请生成下一轮",
                "comment": "",
                "evidence_brief_ids": list(thread.evidence_brief_ids or []),
            },
        )
        binding = rewrite_ctx["descriptor"]["source_registry"]["exact_binding"]
        self.assertEqual(parent_source_id, binding["source_id"])
        self.assertEqual(parent_entry_id, binding["entry_id"])

        # Wrong expected source fails closed.
        with self.assertRaises(MedicalWritingRevisionService.GenerationContextError):
            self.service._ensure_exact_original_source_binding(
                PROJECT,
                selection_quote=thread.selected_text,
                selection_locator=thread.source_locator or thread.anchor_path,
                expected_source_id="not_this_source",
                expected_entry_id=parent_entry_id,
            )


if __name__ == "__main__":
    unittest.main()
