from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from packages.contracts.workbench_contracts import (
    MedicalWritingAuthoringJourneyCommitRequest,
    MedicalWritingAuthoringJourneyCreateRequest,
    MedicalWritingCompetitorSearchExecuteRequest,
    MedicalWritingCorpusTriageFinalizeRequest,
    MedicalWritingPicosCorpusAlignmentRequest,
    WritingReferenceDocumentArtifact,
    WritingReferenceDocumentValidationCheck,
    WritingReferenceDocumentValidationRecord,
    WritingReferenceExtractedSpan,
    WritingReferenceExtractionResult,
    WritingReferenceTranslationRevision,
)
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyConflictError,
    MedicalWritingAuthoringJourneyService,
)
from services.api.app.medical_writing_corpus_readiness import (
    MedicalWritingCorpusReadinessService,
)
from services.api.app.writing_reference_repository import WritingReferenceRepository
from services.api.app.writing_reference_translation_batch import (
    WritingReferenceTranslationBatchService,
)
from tests.test_medical_writing_authoring_journey import (
    _complete_framing,
    _complete_picos,
    _search_snapshot,
)


NOW = datetime(2026, 7, 15, 1, 30, tzinfo=timezone.utc)


class MedicalWritingCorpusReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.project_id = "proj_ra_corpus_readiness"
        self.journeys = MedicalWritingAuthoringJourneyService(root / "journeys.sqlite3")
        self.references = WritingReferenceRepository(root / "references.sqlite3")
        self.service = MedicalWritingCorpusReadinessService(
            self.journeys, self.references
        )

        created = self.journeys.create(
            self.project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_complete_framing(),
                actor="medical_manager_test",
                idempotency_key="create-readiness-journey",
            ),
        )
        designed = self.journeys.commit_stage(
            self.project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=created.revision,
                stage="picos",
                picos=_complete_picos(),
                actor="medical_manager_test",
                idempotency_key="commit-readiness-picos",
            ),
        )
        self.snapshot = _search_snapshot(self.project_id)
        self.references.save_search_snapshot(
            self.snapshot, idempotency_key="save-readiness-snapshot"
        )
        self.attached = self.journeys.attach_search_snapshot(
            self.project_id,
            self.snapshot,
            MedicalWritingCompetitorSearchExecuteRequest(
                search_plan_id=created.search_plan.plan_id,
                actor="medical_manager_test",
                idempotency_key="attach-readiness-snapshot",
            ),
        )
        self.decision = self.references.record_relevance_decision(
            project_id=self.project_id,
            snapshot_id=self.snapshot.snapshot_id,
            nct_id="NCT00000001",
            relevance_status="direct_competitor",
            reason="同适应症、同研究分期且研究设计可直接参照。",
            actor="medical_manager_test",
            expected_revision=0,
            idempotency_key="classify-readiness-candidate",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _prepare_protocol_corpus(self, *, thin: bool = False) -> list[str]:
        artifact = WritingReferenceDocumentArtifact(
            artifact_id="wref_artifact_ra_protocol",
            project_id=self.project_id,
            snapshot_id=self.snapshot.snapshot_id,
            nct_id="NCT00000001",
            source_document_id="wref_doc_protocol_001",
            document_type="protocol",
            filename="ra_phase2_protocol.pdf",
            requested_url="https://cdn.clinicaltrials.gov/ra_protocol.pdf",
            final_url="https://cdn.clinicaltrials.gov/ra_protocol.pdf",
            content_type="application/pdf",
            actual_size=1024,
            content_sha256="a" * 64,
            created_by="medical_manager_test",
            created_at=NOW,
        )
        self.references.save_document_artifact(
            artifact,
            storage_relpath="ra/phase2/protocol.pdf",
            idempotency_key="save-ra-protocol",
        )
        self.references.save_document_validation(
            WritingReferenceDocumentValidationRecord(
                validation_id="wref_validation_ra_protocol",
                project_id=self.project_id,
                artifact_id=artifact.artifact_id,
                revision=1,
                status="confirmed",
                document_sha256=artifact.content_sha256,
                extraction_revision="pymupdf_ra_protocol_r1",
                source_state_revision=artifact.state_revision,
                expected_context_hash="b" * 64,
                validator_version="content_consistency_v2",
                checks=[
                    WritingReferenceDocumentValidationCheck(
                        check_code="document_role",
                        label="文件角色",
                        expected_value="protocol",
                        observed_value="protocol",
                        outcome="match",
                    )
                ],
                summary="适应症和文件角色与当前任务一致。",
                actor="system_validator",
                created_at=NOW,
            ),
            expected_revision=0,
            idempotency_key="validate-ra-protocol",
        )
        anchors = ["objectives_endpoints", "eligibility", "schedule", "safety"]
        spans = [
            WritingReferenceExtractedSpan(
                span_id=f"wref_span_ra_{anchor}",
                project_id=self.project_id,
                artifact_id=artifact.artifact_id,
                extraction_revision="pymupdf_ra_protocol_r1",
                physical_page=index + 1,
                block_index=0,
                source_locator=f"ctgov:NCT00000001:{artifact.artifact_id}:p{index + 1}:b0",
                section_heading=anchor,
                ich_m11_anchor=anchor,
                source_text=f"Source protocol text for {anchor} at Week 12.",
                source_text_sha256=f"{index + 1}" * 64,
            )
            for index, anchor in enumerate(anchors)
        ]
        self.references.save_extraction(
            WritingReferenceExtractionResult(
                artifact_id=artifact.artifact_id,
                project_id=self.project_id,
                extraction_revision="pymupdf_ra_protocol_r1",
                parser_name="PyMuPDF",
                parser_version="1.26.5",
                page_count=20,
                status="pending_visual_and_medical_structure_review",
                spans=spans,
            ),
            idempotency_key="extract-ra-protocol",
        )
        extraction_review = self.references.record_extraction_review(
            project_id=self.project_id,
            artifact_id=artifact.artifact_id,
            extraction_revision="pymupdf_ra_protocol_r1",
            decision="approved",
            confirmed_anchor_coverage=anchors,
            unresolved_structure_issues=[],
            comment="四个关键M11锚点均已完成医学结构审核，未发现待解决的结构问题。",
            actor="medical_manager_test",
            expected_revision=0,
            idempotency_key="approve-ra-protocol-extraction-structure",
        )
        self.assertEqual("approved", extraction_review.decision)
        self.assertEqual(sorted(anchors), extraction_review.confirmed_anchor_coverage)

        brief_ids = []
        for index, span in enumerate(spans, start=1):
            translation = self.references.save_translation(
                WritingReferenceTranslationRevision(
                    translation_id=f"wref_translation_ra_{index}",
                    project_id=self.project_id,
                    span_id=span.span_id,
                    source_span_revision=f"{span.span_id}_r1",
                    document_sha256=artifact.content_sha256,
                    glossary_version="cms_regulatory_zh_v1",
                    revision=1,
                    translated_text=(
                        span.ich_m11_anchor
                        if thin
                        else f"{span.ich_m11_anchor}对应的监管中文参考文本，第12周。"
                    ),
                    rationale="保持原文时间点和医学含义。",
                    fidelity_status="passed",
                    ai_run_id=f"airun_ra_{index}",
                    created_at=NOW,
                ),
                idempotency_key=f"translate-ra-{index}",
            )
            review = self.references.record_medical_review(
                project_id=self.project_id,
                translation_id=translation.translation_id,
                translation_revision=1,
                decision="approved",
                comment="与原文医学含义一致，可作为方案写作参照。",
                actor="medical_manager_test",
                expected_revision=0,
                idempotency_key=f"review-ra-{index}",
            )
            brief = self.references.admit_translation(
                project_id=self.project_id,
                translation_id=translation.translation_id,
                expected_translation_revision=1,
                medical_review_id=review.review_id,
                idempotency_key=f"admit-ra-{index}",
            )
            brief_ids.append(brief.brief_id)
        return brief_ids

    def test_thin_admitted_briefs_do_not_satisfy_medical_or_picos_gate(self) -> None:
        triaged = self.service.finalize_triage(
            self.project_id,
            MedicalWritingCorpusTriageFinalizeRequest(
                expected_revision=self.attached.revision,
                snapshot_id=self.snapshot.snapshot_id,
                retained_candidate_ids=["NCT00000001"],
                reason="仅用于验证短文本准入不得解锁PICOS。",
                actor="medical_manager_test",
                idempotency_key="finalize-thin-brief-triage",
            ),
        )
        brief_ids = self._prepare_protocol_corpus(thin=True)
        projected = self.service.recalculate(self.project_id)
        self.assertFalse(projected.corpus_gate.requirements[3].satisfied)
        self.assertIn("短文本", projected.corpus_gate.requirements[3].detail)
        with self.assertRaisesRegex(
            ValueError, "requires substantive evidence briefs"
        ):
            self.service.record_picos_alignment(
                self.project_id,
                MedicalWritingPicosCorpusAlignmentRequest(
                    expected_revision=projected.revision,
                    source_picos_sha256=self.journeys.picos_sha256(self.project_id),
                    status="no_conflicts",
                    conflict_count=0,
                    disposition_summary="不得使用仅含标题或碎片的译文完成PICOS对齐。",
                    evidence_brief_ids=brief_ids,
                    actor="medical_manager_test",
                    idempotency_key="reject-thin-brief-picos-alignment",
                ),
            )
        self.assertEqual("pending", self.journeys.get(self.project_id).picos_corpus_alignment.status)

    def test_research_span_cap_prefers_longest_protocol_evidence(self) -> None:
        specs = [
            {
                "span": SimpleNamespace(
                    source_text=text,
                    ich_m11_anchor="eligibility",
                ),
                "artifact": SimpleNamespace(document_type="protocol"),
                "generation_status": "pending",
            }
            for text in ("Eligibility", "A complete eligibility criterion with age and disease duration.")
        ]
        selected = WritingReferenceTranslationBatchService._cap_item_specs(
            specs, 1
        )
        self.assertEqual(
            "A complete eligibility criterion with age and disease duration.",
            selected[0]["span"].source_text,
        )

    def test_research_span_cap_prefers_anchor_heading_over_long_neighbour(self) -> None:
        specs = [
            {
                "span": SimpleNamespace(
                    span_id="schedule-noise",
                    source_text=("<table>" + "VISIT 1 X " * 900 + "</table>"),
                    section_heading="Schedule of Activities",
                    ich_m11_anchor="eligibility",
                ),
                "artifact": SimpleNamespace(document_type="protocol"),
                "generation_status": "pending",
            },
            {
                "span": SimpleNamespace(
                    span_id="eligibility-criterion",
                    source_text=(
                        "Inclusion criteria: adults with a documented diagnosis "
                        "of migraine and at least 4 attacks per month."
                    ),
                    section_heading="Inclusion Criteria",
                    ich_m11_anchor="eligibility",
                ),
                "artifact": SimpleNamespace(document_type="protocol"),
                "generation_status": "pending",
            },
        ]
        selected = WritingReferenceTranslationBatchService._cap_item_specs(
            specs, 1
        )
        self.assertEqual("eligibility-criterion", selected[0]["span"].span_id)

    def test_research_span_cap_rejects_long_reference_section_for_objectives(self) -> None:
        specs = [
            {
                "span": SimpleNamespace(
                    span_id="reference-noise",
                    source_text=("References\n" + "Smith et al. 2020; " * 700),
                    section_heading="References",
                    ich_m11_anchor="objectives_endpoints",
                ),
                "artifact": SimpleNamespace(document_type="protocol"),
                "generation_status": "pending",
            },
            {
                "span": SimpleNamespace(
                    span_id="endpoint-section",
                    source_text=(
                        "The primary endpoint is the change from baseline in "
                        "monthly migraine days at Week 12."
                    ),
                    section_heading="Primary Objectives and Endpoints",
                    ich_m11_anchor="objectives_endpoints",
                ),
                "artifact": SimpleNamespace(document_type="protocol"),
                "generation_status": "pending",
            },
        ]
        selected = WritingReferenceTranslationBatchService._cap_item_specs(
            specs, 1
        )
        self.assertEqual("endpoint-section", selected[0]["span"].span_id)

    def _make_gate_ready(self):
        triaged = self.service.finalize_triage(
            self.project_id,
            MedicalWritingCorpusTriageFinalizeRequest(
                expected_revision=self.attached.revision,
                snapshot_id=self.snapshot.snapshot_id,
                retained_candidate_ids=["NCT00000001"],
                reason="锁定同适应症、同分期且有公开Protocol的直接竞品进入深度处理。",
                actor="medical_manager_test",
                idempotency_key="finalize-ready-gate-triage",
            ),
        )
        self.assertTrue(triaged.corpus_gate.requirements[0].satisfied)
        brief_ids = self._prepare_protocol_corpus()
        projected = self.service.recalculate(self.project_id)
        return self.service.record_picos_alignment(
            self.project_id,
            MedicalWritingPicosCorpusAlignmentRequest(
                expected_revision=projected.revision,
                source_picos_sha256=self.journeys.picos_sha256(self.project_id),
                status="no_conflicts",
                conflict_count=0,
                disposition_summary="逐项核对当前PICOS与四类关键监管中文语料，未发现需要处置的冲突。",
                evidence_brief_ids=brief_ids,
                actor="medical_manager_test",
                idempotency_key="align-ready-gate-picos-corpus",
            ),
        )

    def test_finalize_triage_rejects_candidate_outside_bound_snapshot(self) -> None:
        before = self.journeys.get(self.project_id)

        with self.assertRaisesRegex(
            ValueError, "retained candidates are not present in the bound snapshot"
        ):
            self.service.finalize_triage(
                self.project_id,
                MedicalWritingCorpusTriageFinalizeRequest(
                    expected_revision=before.revision,
                    snapshot_id=self.snapshot.snapshot_id,
                    retained_candidate_ids=["NCT99999999"],
                    reason="尝试锁定不属于当前不可变检索快照的候选研究。",
                    actor="medical_manager_test",
                    idempotency_key="reject-candidate-outside-bound-snapshot",
                ),
            )

        after = self.journeys.get(self.project_id)
        self.assertEqual(before.revision, after.revision)
        self.assertEqual("pending", after.corpus_triage.status)

    def test_finalize_triage_rejects_retained_candidate_without_current_related_decision(self) -> None:
        before = self.journeys.get(self.project_id)
        request_fields = {
            "expected_revision": before.revision,
            "snapshot_id": self.snapshot.snapshot_id,
            "retained_candidate_ids": ["NCT00000002"],
            "reason": "候选属于当前快照，但必须先有当前直接竞品或间接参照决策。",
            "actor": "medical_manager_test",
        }

        with self.assertRaisesRegex(
            ValueError,
            "every retained candidate must have a current direct-competitor or indirect-reference decision",
        ):
            self.service.finalize_triage(
                self.project_id,
                MedicalWritingCorpusTriageFinalizeRequest(
                    **request_fields,
                    idempotency_key="reject-candidate-without-decision",
                ),
            )

        self.references.record_relevance_decision(
            project_id=self.project_id,
            snapshot_id=self.snapshot.snapshot_id,
            nct_id="NCT00000002",
            relevance_status="excluded",
            reason="适应症相近但研究设计与当前方案无可用参照关系。",
            actor="medical_manager_test",
            expected_revision=0,
            idempotency_key="exclude-second-readiness-candidate",
        )
        with self.assertRaisesRegex(
            ValueError,
            "every retained candidate must have a current direct-competitor or indirect-reference decision",
        ):
            self.service.finalize_triage(
                self.project_id,
                MedicalWritingCorpusTriageFinalizeRequest(
                    **request_fields,
                    idempotency_key="reject-candidate-with-excluded-decision",
                ),
            )

        after = self.journeys.get(self.project_id)
        self.assertEqual(before.revision, after.revision)
        self.assertEqual("pending", after.corpus_triage.status)

    def test_picos_alignment_rejects_stale_picos_hash(self) -> None:
        with self.assertRaisesRegex(
            MedicalWritingAuthoringJourneyConflictError,
            "PICOS changed after the corpus alignment review was prepared",
        ):
            self.service.record_picos_alignment(
                self.project_id,
                MedicalWritingPicosCorpusAlignmentRequest(
                    expected_revision=self.attached.revision,
                    source_picos_sha256="0" * 64,
                    status="no_conflicts",
                    conflict_count=0,
                    disposition_summary="该结论基于过期PICOS摘要，服务端必须拒绝写入。",
                    evidence_brief_ids=[],
                    actor="medical_manager_test",
                    idempotency_key="reject-stale-picos-alignment",
                ),
            )

        current = self.journeys.get(self.project_id)
        self.assertEqual(self.attached.revision, current.revision)
        self.assertEqual("pending", current.picos_corpus_alignment.status)

    def test_picos_alignment_rejects_missing_and_invalidated_briefs(self) -> None:
        request_fields = {
            "expected_revision": self.attached.revision,
            "source_picos_sha256": self.journeys.picos_sha256(self.project_id),
            "status": "no_conflicts",
            "conflict_count": 0,
            "disposition_summary": "PICOS冲突核对只能引用当前有效且已经医学准入的证据条目。",
            "actor": "medical_manager_test",
        }
        with self.assertRaisesRegex(
            ValueError, "PICOS alignment references evidence briefs that are not current"
        ):
            self.service.record_picos_alignment(
                self.project_id,
                MedicalWritingPicosCorpusAlignmentRequest(
                    **request_fields,
                    evidence_brief_ids=["wref_brief_does_not_exist"],
                    idempotency_key="reject-missing-evidence-brief",
                ),
            )

        brief_ids = self._prepare_protocol_corpus()
        artifact = self.references.document_artifact(
            self.project_id, "wref_artifact_ra_protocol"
        )
        self.references.invalidate_artifact(
            project_id=self.project_id,
            artifact_id=artifact.artifact_id,
            reason="来源已被新版本替代，旧证据不得用于PICOS一致性结论。",
            actor="system_version_monitor",
            expected_revision=artifact.state_revision,
            idempotency_key="invalidate-brief-before-picos-alignment",
        )
        with self.assertRaisesRegex(
            ValueError, "PICOS alignment references evidence briefs that are not current"
        ):
            self.service.record_picos_alignment(
                self.project_id,
                MedicalWritingPicosCorpusAlignmentRequest(
                    **request_fields,
                    evidence_brief_ids=brief_ids,
                    idempotency_key="reject-invalidated-evidence-brief",
                ),
            )

        current = self.journeys.get(self.project_id)
        self.assertEqual(self.attached.revision, current.revision)
        self.assertEqual("pending", current.picos_corpus_alignment.status)

    def test_pre_greenfield_recalculation_closes_logically_stale_ready_gate(self) -> None:
        ready = self._make_gate_ready()
        self.assertEqual("ready", ready.corpus_gate.readiness_status)
        self.assertTrue(ready.corpus_gate.access_permitted)

        artifact = self.references.document_artifact(
            self.project_id, "wref_artifact_ra_protocol"
        )
        self.references.invalidate_artifact(
            project_id=self.project_id,
            artifact_id=artifact.artifact_id,
            reason="模拟建稿请求到达前，公开来源已由新版本替代。",
            actor="system_version_monitor",
            expected_revision=artifact.state_revision,
            idempotency_key="invalidate-source-before-greenfield-create",
        )

        persisted_before_recalculation = self.journeys.get(self.project_id)
        self.assertEqual(
            "ready", persisted_before_recalculation.corpus_gate.readiness_status
        )
        self.assertTrue(persisted_before_recalculation.corpus_gate.access_permitted)

        recalculated = self.service.recalculate(
            self.project_id, actor="system_pre_document_gate"
        )
        self.assertEqual("not_ready", recalculated.corpus_gate.readiness_status)
        self.assertFalse(recalculated.corpus_gate.access_permitted)
        self.assertFalse(recalculated.corpus_gate.stale)
        self.assertNotEqual(
            persisted_before_recalculation.corpus_gate.source_state_hash,
            recalculated.corpus_gate.source_state_hash,
        )
        self.assertFalse(recalculated.corpus_gate.requirements[1].satisfied)
        with self.assertRaisesRegex(ValueError, "corpus is not ready"):
            self.journeys.require_writing_access(self.project_id)

    def test_recalculate_projects_known_gaps_before_picos_without_stranding_stage(self) -> None:
        project_id = "proj_ra_corpus_readiness_framing_only"
        created = self.journeys.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_complete_framing(),
                actor="medical_manager_test",
                idempotency_key="create-readiness-framing-only",
            ),
        )
        snapshot = _search_snapshot(project_id)
        self.references.save_search_snapshot(
            snapshot, idempotency_key="save-readiness-framing-only-snapshot"
        )
        attached = self.journeys.attach_search_snapshot(
            project_id,
            snapshot,
            MedicalWritingCompetitorSearchExecuteRequest(
                search_plan_id=created.search_plan.plan_id,
                actor="medical_manager_test",
                idempotency_key="attach-readiness-framing-only-snapshot",
            ),
        )
        projected = self.service.recalculate(project_id)

        self.assertFalse(projected.picos_complete)
        self.assertEqual("picos", projected.current_stage)
        self.assertEqual("stage1_complete", projected.status)
        self.assertFalse(projected.corpus_gate.stale)
        self.assertEqual(5, len(projected.corpus_gate.requirements))
        self.assertFalse(projected.corpus_gate.requirements[-1].satisfied)
        self.assertEqual(attached.revision + 1, projected.revision)

    def test_confirmed_discovery_projection_satisfies_candidate_triage_before_finalization(self) -> None:
        projected_basket = self.journeys.project_discovery_basket(
            self.project_id,
            confirmation_id="ct_conf_pre_picos_readiness",
            confirmation_hash="c" * 64,
            snapshot_id=self.snapshot.snapshot_id,
            retained_nct_ids=["NCT00000001"],
            excluded_nct_ids=[],
            run_id="ct_run_pre_picos_readiness",
            actor="medical_manager_test",
            reason="已确认同适应症直接竞品进入后续研究方案证据链。",
            expected_journey_revision=self.attached.revision,
            idempotency_key="project-discovery-pre-picos-readiness",
        )
        self.assertEqual("pending", projected_basket.corpus_triage.status)

        recalculated = self.service.recalculate(self.project_id)

        self.assertTrue(recalculated.corpus_gate.requirements[0].satisfied)
        self.assertEqual(
            [self.decision.decision_id],
            recalculated.corpus_gate.requirements[0].evidence_ids,
        )
        self.assertFalse(recalculated.corpus_gate.requirements[-1].satisfied)
        self.assertNotEqual(
            projected_basket.corpus_gate.source_state_hash,
            recalculated.corpus_gate.source_state_hash,
        )

    def test_real_readiness_projection_opens_and_source_invalidation_closes_gate(self) -> None:
        triaged = self.service.finalize_triage(
            self.project_id,
            MedicalWritingCorpusTriageFinalizeRequest(
                expected_revision=self.attached.revision,
                snapshot_id=self.snapshot.snapshot_id,
                retained_candidate_ids=["NCT00000001"],
                reason="锁定同适应症、同分期且有公开Protocol的直接竞品进入深度处理。",
                actor="medical_manager_test",
                idempotency_key="finalize-ra-triage",
            ),
        )
        self.assertTrue(triaged.corpus_gate.requirements[0].satisfied)
        self.assertFalse(triaged.corpus_gate.requirements[1].satisfied)
        self.assertFalse(triaged.corpus_gate.access_permitted)

        brief_ids = self._prepare_protocol_corpus()
        projected = self.service.recalculate(self.project_id)
        self.assertEqual([True, True, True, True, False], [item.satisfied for item in projected.corpus_gate.requirements])
        self.assertFalse(projected.corpus_gate.access_permitted)

        ready = self.service.record_picos_alignment(
            self.project_id,
            MedicalWritingPicosCorpusAlignmentRequest(
                expected_revision=projected.revision,
                source_picos_sha256=self.journeys.picos_sha256(self.project_id),
                status="no_conflicts",
                conflict_count=0,
                disposition_summary="逐项核对当前PICOS与四类关键监管中文语料，未发现需要处置的冲突。",
                evidence_brief_ids=brief_ids,
                actor="medical_manager_test",
                idempotency_key="align-ra-picos-corpus",
            ),
        )
        self.assertEqual("ready", ready.corpus_gate.readiness_status)
        self.assertTrue(ready.corpus_gate.access_permitted)
        self.assertFalse(ready.corpus_gate.stale)
        self.journeys.require_writing_access(self.project_id)

        artifact = self.references.document_artifact(
            self.project_id, "wref_artifact_ra_protocol"
        )
        self.references.invalidate_artifact(
            project_id=self.project_id,
            artifact_id=artifact.artifact_id,
            reason="ClinicalTrials.gov已发布替代版本，当前版本退出语料库。",
            actor="system_version_monitor",
            expected_revision=artifact.state_revision,
            idempotency_key="invalidate-ra-protocol",
        )
        closed = self.service.recalculate(self.project_id)
        self.assertEqual("not_ready", closed.corpus_gate.readiness_status)
        self.assertFalse(closed.corpus_gate.access_permitted)
        self.assertFalse(closed.corpus_gate.requirements[1].satisfied)
        with self.assertRaisesRegex(ValueError, "corpus is not ready"):
            self.journeys.require_writing_access(self.project_id)


if __name__ == "__main__":
    unittest.main()
