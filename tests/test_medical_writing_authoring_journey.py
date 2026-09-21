from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from packages.contracts.workbench_contracts import (
    AuthoringPrefillGenerateRequest,
    MedicalWritingAuthoringJourney,
    MedicalWritingAuthoringJourneyCommitRequest,
    MedicalWritingAuthoringJourneyCreateRequest,
    MedicalWritingAuthoringJourneyDraftSaveRequest,
    MedicalWritingCompetitorSearchExecuteRequest,
    MedicalWritingCorpusGateOverrideRequest,
    MedicalWritingInvestigationalProductProfile,
    MedicalWritingJourneyImpactPreviewRequest,
    MedicalWritingMinimumProductFactPacket,
    MedicalWritingPicosDefinition,
    MedicalWritingPicosFieldApplicability,
    MedicalWritingSynopsisEvidenceSpan,
    MedicalWritingSynopsisImport,
    MedicalWritingSynopsisImportConfirmRequest,
    MedicalWritingSynopsisSource,
    MedicalWritingStudyFraming,
    WritingReferencePublicDocument,
    WritingReferenceSearchRequest,
    WritingReferenceSearchSnapshot,
    WritingReferenceTrialCandidate,
    medical_writing_competitor_search_contract,
)
from services.api.app import main as app_main
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyConflictError,
    MedicalWritingAuthoringJourneyService,
)


def _complete_framing(
    *,
    indication: str = "类风湿关节炎",
    clinicaltrials_condition_term: str = "Rheumatoid Arthritis",
) -> MedicalWritingStudyFraming:
    return MedicalWritingStudyFraming(
        protocol_id="CMS-RA-201",
        version="V0.1",
        document_title="CMS-RA-201治疗类风湿关节炎的II期临床研究方案",
        indication=indication,
        clinicaltrials_condition_term=clinicaltrials_condition_term,
        study_phase="II期",
        intrinsic_objectives=["概念验证（PoC）", "剂量探索"],
        investigational_product="CMS-RA-201注射液",
        target_mechanism="靶向炎症通路的单克隆抗体",
        competitor_target_scope="同靶点及同机制生物制剂",
        development_regions=["中国"],
        design_pattern="随机、双盲、安慰剂对照、平行组、多中心研究",
        population_intent="既往csDMARD治疗反应不充分的中重度活动性类风湿关节炎成人患者",
        key_uncertainties=["剂量-效应关系", "第12周主要终点评价时点"],
    )


def _complete_picos(**overrides) -> MedicalWritingPicosDefinition:
    payload = dict(
        design_archetype="randomized_confirmatory",
        population_summary="18至75岁中重度活动性类风湿关节炎试验参与者。",
        inclusion_modules=["筛选期与基线期满足疾病活动度阈值", "稳定使用背景甲氨蝶呤"],
        exclusion_modules=["活动性感染", "近期使用其他生物制剂且未完成洗脱"],
        washout_rules=["既往生物制剂按药代特征和方案规定完成洗脱"],
        intervention_summary="CMS-RA-201两个剂量组，皮下注射。",
        intervention_dose_regimen="每4周给药一次，持续24周。",
        allowed_concomitant_rules=["稳定剂量叶酸"],
        required_background_rules=["稳定剂量甲氨蝶呤"],
        prohibited_concomitant_rules=["其他生物制剂", "JAK抑制剂"],
        assessment_timing_restrictions=["疗效评估前限制使用救援性糖皮质激素"],
        comparator_summary="匹配安慰剂，每4周皮下注射一次。",
        primary_endpoint="第12周ACR20应答率。",
        key_secondary_endpoints=["第12周DAS28-CRP较基线变化"],
        other_secondary_endpoints=["第24周ACR50和ACR70应答率"],
        exploratory_endpoints=["炎症生物标志物较基线变化"],
        safety_endpoints=["TEAE、SAE及导致停药的AE发生率"],
        aesi_definitions=["严重感染", "超敏反应"],
        study_epochs=["筛选期", "双盲治疗期", "安全性随访期"],
        visit_strategy="筛选、基线，治疗期每4周访视，末次给药后完成安全性随访。",
        estimand_strategy="主要估计目标评价治疗策略下第12周ACR20应答差异。",
        sample_size_strategy="基于预期应答率差异、双侧显著性水平和脱落率估算。",
        statistical_strategy="主要终点采用分层分析并进行多重性控制。",
    )
    payload.update(overrides)
    return MedicalWritingPicosDefinition(**payload)


def _review_pending_synopsis_import() -> MedicalWritingSynopsisImport:
    imported_at = datetime(2026, 7, 15, tzinfo=timezone.utc)
    source_id = "mwsynopsis_source_ra_001"
    indication_text = "适应症：类风湿关节炎"
    phase_text = "研究分期：II期"
    evidence_spans = [
        MedicalWritingSynopsisEvidenceSpan(
            span_id="mwsynopsis_span_indication",
            source_id=source_id,
            locator="docx:paragraph:2",
            source_text=indication_text,
            source_text_sha256=hashlib.sha256(
                indication_text.encode("utf-8")
            ).hexdigest(),
        ),
        MedicalWritingSynopsisEvidenceSpan(
            span_id="mwsynopsis_span_phase",
            source_id=source_id,
            locator="docx:paragraph:3",
            source_text=phase_text,
            source_text_sha256=hashlib.sha256(
                phase_text.encode("utf-8")
            ).hexdigest(),
        ),
    ]
    return MedicalWritingSynopsisImport(
        status="review_pending",
        source=MedicalWritingSynopsisSource(
            source_id=source_id,
            original_filename="CMS-RA-201方案摘要.docx",
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            actual_size=2048,
            content_sha256=hashlib.sha256(
                f"{indication_text}\n{phase_text}".encode("utf-8")
            ).hexdigest(),
            extraction_revision="protocol_synopsis_structuring_v1",
            parser_name="docx_parser",
            source_role_status="matched",
            indication_status="matched",
            imported_at=imported_at,
            imported_by="medical_manager_test",
        ),
        proposed_framing=_complete_framing(),
        proposed_picos=_complete_picos(),
        proposed_synopsis_text=(
            "研究题目：CMS-RA-201治疗类风湿关节炎的II期临床研究方案\n"
            "研究分期：II期\n适应症：类风湿关节炎"
        ),
        field_evidence_span_ids={
            "framing.indication": ["mwsynopsis_span_indication"],
            "framing.study_phase": ["mwsynopsis_span_phase"],
        },
        evidence_spans=evidence_spans,
        ai_run_id="airun_ra_synopsis_001",
    )


def _search_snapshot(project_id: str) -> WritingReferenceSearchSnapshot:
    return WritingReferenceSearchSnapshot(
        snapshot_id="wref_search_ra_001",
        project_id=project_id,
        request=WritingReferenceSearchRequest(
            indication="Rheumatoid Arthritis",
            phases=["PHASE2"],
        ),
        query_url="https://clinicaltrials.gov/api/v2/studies?query.cond=RA",
        api_version="2.0",
        data_timestamp="2026-07-14",
        total_count=2,
        returned_count=2,
        page_count=1,
        candidates=[
            WritingReferenceTrialCandidate(
                nct_id="NCT00000001",
                study_record_url="https://clinicaltrials.gov/study/NCT00000001",
                public_documents=[
                    WritingReferencePublicDocument(
                        document_id="wref_doc_protocol_001",
                        nct_id="NCT00000001",
                        document_type="protocol",
                        filename="protocol.pdf",
                        download_url="https://cdn.clinicaltrials.gov/protocol.pdf",
                    ),
                    WritingReferencePublicDocument(
                        document_id="wref_doc_other_001",
                        nct_id="NCT00000001",
                        document_type="other",
                        filename="statistical_cover_note.pdf",
                        download_url="https://cdn.clinicaltrials.gov/cover-note.pdf",
                    ),
                    WritingReferencePublicDocument(
                        document_id="wref_doc_sap_001",
                        nct_id="NCT00000001",
                        document_type="sap",
                        filename="sap.pdf",
                        download_url="https://cdn.clinicaltrials.gov/sap.pdf",
                    ),
                    WritingReferencePublicDocument(
                        document_id="wref_doc_protocol_sap_001",
                        nct_id="NCT00000001",
                        document_type="protocol_sap",
                        filename="protocol-and-sap.pdf",
                        download_url="https://cdn.clinicaltrials.gov/protocol-and-sap.pdf",
                    ),
                ],
            ),
            WritingReferenceTrialCandidate(
                nct_id="NCT00000002",
                study_record_url="https://clinicaltrials.gov/study/NCT00000002",
            ),
        ],
        created_by="medical_manager_test",
        created_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
    )


class MedicalWritingAuthoringJourneyServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "authoring_journey.sqlite3"
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_research_pipeline_projection_rejects_late_stale_job_binding(self):
        project_id = "proj_research_pipeline_stale_binding"
        self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                actor="medical_manager_test",
                idempotency_key="create-research-pipeline-stale-binding",
            ),
        )
        first = self.service.save_research_pipeline(
            project_id,
            {
                "pipeline_id": "mwpipe_same",
                "job_id": "mwjob_continuation",
                "stage": "preparing",
                "percent": 50,
                "created_at": "2026-08-04T00:00:00+00:00",
                "write_generation": 1,
            },
        )
        assert first.research_pipeline["job_id"] == "mwjob_continuation"

        # Simulates a status request that captured the old awaiting-confirm
        # snapshot and returned after the continuation had been persisted.
        stale = self.service.save_research_pipeline(
            project_id,
            {
                "pipeline_id": "mwpipe_same",
                "job_id": "mwjob_old_awaiting",
                "stage": "awaiting_triage_confirm",
                "percent": 35,
                "created_at": "2026-08-04T00:00:00+00:00",
                "write_generation": 1,
            },
        )
        assert stale.research_pipeline["job_id"] == "mwjob_continuation"
        assert stale.research_pipeline["stage"] == "preparing"

        # A genuinely newer write in the same pipeline identity still passes.
        newer = self.service.save_research_pipeline(
            project_id,
            {
                "pipeline_id": "mwpipe_same",
                "job_id": "mwjob_continuation",
                "stage": "translating",
                "percent": 68,
                "created_at": "2026-08-04T00:00:00+00:00",
                "write_generation": 2,
            },
        )
        assert newer.research_pipeline["stage"] == "translating"
        assert newer.research_pipeline["write_generation"] == 2

    def test_confirmed_stages_create_nested_structured_fact_states(self):
        project_id = "proj_ra_nested_structured_fact_states"
        created = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                actor="medical_manager_test",
                idempotency_key="create-ra-nested-facts",
            ),
        )
        framing_payload = _complete_framing().model_dump(mode="json")
        framing_payload["product_profile"] = {
            "technology_type": "monoclonal_antibody",
            "administration_routes": ["皮下注射"],
            "dosage_forms": ["注射液"],
            "exposure_scope": "systemic",
        }
        framing_payload["structured_design"] = {
            "randomization_mode": "randomized",
            "blinding_mode": "double_blind",
            "comparator_type": "placebo",
            "assignment_model": "平行组",
            "treatment_switch": {"planned": False},
            "crossover": {"planned": False},
            "open_label_extension": {"planned": False},
            "sample_size_reestimation": {"planned": False},
            "adaptive_design": {"planned": False},
            "src_planned": False,
            "dmc_planned": False,
            "interim_analysis": {"planned": False},
        }
        framing = MedicalWritingStudyFraming.model_validate(framing_payload)
        framing_preview = self.service.impact_preview(
            project_id,
            MedicalWritingJourneyImpactPreviewRequest(
                expected_revision=created.revision,
                stage="framing",
                framing=framing,
            ),
        )
        framed = self.service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=created.revision,
                stage="framing",
                framing=framing,
                impact_preview_id=framing_preview.preview_id,
                actor="medical_manager_test",
                idempotency_key="commit-ra-nested-framing",
            ),
        )
        framing_states = framed.study_definition.field_states
        for path in (
            "framing.structured_design.randomization_mode",
            "framing.structured_design.interim_analysis",
            "framing.structured_design.interim_analysis.planned",
            "framing.structured_design.open_label_extension",
            "framing.product_profile.technology_type",
            "framing.product_profile.administration_routes",
        ):
            self.assertEqual("confirmed", framing_states[path].status, path)
            self.assertEqual(
                "medical_manager_test",
                framing_states[path].confirmed_by,
                path,
            )
        self.assertNotIn(
            "framing.product_profile.historical_study_summaries",
            framing_states,
        )

        picos_payload = _complete_picos().model_dump(mode="json")
        picos_payload["intervention_rules"] = {
            "schema_version": "medical_writing_intervention_rules_v1",
            "authority": "structured",
            "ip_regimens": [
                {
                    "regimen_id": "ip-main",
                    "product_name": "CMS-RA-201",
                    "product_role": "investigational_product",
                    "dose_and_frequency": "每4周给药一次",
                    "route": "皮下注射",
                    "treatment_period": "24周",
                },
                {
                    "regimen_id": "placebo-main",
                    "product_name": "匹配安慰剂",
                    "product_role": "placebo",
                    "dose_and_frequency": "每4周给药一次",
                    "route": "皮下注射",
                    "treatment_period": "24周",
                },
            ],
            "ip_adjustment_policy": "no_planned_adjustment",
            "no_planned_adjustment_statement": "不设置计划性剂量调整。",
            "non_ip_treatment_rules": [
                {
                    "rule_id": "background-mtx",
                    "rule_class": "background",
                    "policy": "allowed_if_stable",
                    "agent_or_category": "甲氨蝶呤",
                }
            ],
        }
        picos = MedicalWritingPicosDefinition.model_validate(picos_payload)
        picos_preview = self.service.impact_preview(
            project_id,
            MedicalWritingJourneyImpactPreviewRequest(
                expected_revision=framed.revision,
                stage="picos",
                picos=picos,
            ),
        )
        designed = self.service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=framed.revision,
                stage="picos",
                picos=picos,
                impact_preview_id=picos_preview.preview_id,
                actor="medical_manager_test",
                idempotency_key="commit-ra-nested-picos",
            ),
        )
        picos_states = designed.study_definition.field_states
        for path in (
            "picos.intervention_rules.ip_regimens",
            "picos.intervention_rules.ip_adjustment_policy",
            "picos.intervention_rules.non_ip_treatment_rules",
        ):
            self.assertEqual("confirmed", picos_states[path].status, path)
        self.assertNotIn(
            "picos.intervention_rules.ip_action_rules",
            picos_states,
        )

    def test_nested_metadata_is_excluded_and_unknown_values_remain_deferred(self):
        project_id = "proj_ra_nested_unknown_fact_states"
        framing_payload = _complete_framing().model_dump(mode="json")
        framing_payload["product_profile"] = {
            "technology_type": "unknown",
            "administration_routes": [],
            "dosage_forms": [],
            "exposure_scope": "unknown",
        }
        framing_payload["structured_design"] = {
            "randomization_mode": "undecided",
            "blinding_mode": "undecided",
            "comparator_type": "undecided",
            "assignment_model": "",
            "treatment_switch": {"planned": False},
            "crossover": {"planned": False},
            "open_label_extension": {"planned": False},
            "sample_size_reestimation": {"planned": False},
            "adaptive_design": {"planned": False},
            "src_planned": False,
            "dmc_planned": False,
            "interim_analysis": {"planned": False},
        }
        framing = MedicalWritingStudyFraming.model_validate(framing_payload)
        created = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=framing,
                actor="medical_manager_test",
                idempotency_key="create-ra-nested-unknown-facts",
            ),
        )
        states = created.study_definition.field_states

        self.assertNotIn("framing.product_profile.schema_version", states)
        self.assertNotIn("framing.structured_design.schema_version", states)
        for path in (
            "framing.product_profile.technology_type",
            "framing.product_profile.exposure_scope",
            "framing.structured_design.randomization_mode",
            "framing.structured_design.blinding_mode",
            "framing.structured_design.comparator_type",
        ):
            self.assertEqual("deferred", states[path].status, path)
            self.assertEqual("", states[path].confirmed_by, path)
            self.assertIsNone(states[path].confirmed_at, path)
        self.assertEqual(
            "confirmed",
            states[
                "framing.structured_design.interim_analysis.planned"
            ].status,
        )

    def test_legacy_top_level_fact_states_are_conservatively_migrated_on_read(self):
        project_id = "proj_ra_legacy_nested_fact_state_migration"
        framing_payload = _complete_framing().model_dump(mode="json")
        framing_payload["product_profile"] = {
            "technology_type": "monoclonal_antibody",
            "administration_routes": ["皮下注射"],
            "dosage_forms": ["注射液"],
            "exposure_scope": "systemic",
        }
        framing_payload["structured_design"] = {
            "randomization_mode": "randomized",
            "blinding_mode": "double_blind",
            "comparator_type": "placebo",
            "assignment_model": "平行组",
            "treatment_switch": {"planned": False},
            "crossover": {"planned": False},
            "open_label_extension": {"planned": False},
            "sample_size_reestimation": {"planned": False},
            "adaptive_design": {"planned": False},
            "src_planned": False,
            "dmc_planned": False,
            "interim_analysis": {"planned": False},
        }
        created = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=MedicalWritingStudyFraming.model_validate(framing_payload),
                actor="medical_manager_test",
                idempotency_key="create-ra-legacy-nested-facts",
            ),
        )
        legacy_payload = created.model_dump(mode="json")
        legacy_definition = legacy_payload["study_definition"]
        legacy_definition["field_states"] = {
            path: state
            for path, state in legacy_definition["field_states"].items()
            if not any(
                path.startswith(f"{root}.")
                for root in (
                    "framing.product_profile",
                    "framing.structured_design",
                    "picos.intervention_rules",
                )
            )
        }
        legacy_definition["unresolved_paths"] = [
            path
            for path in legacy_definition["unresolved_paths"]
            if path in legacy_definition["field_states"]
        ]
        legacy_definition_revision = legacy_definition["revision"]
        legacy_definition_sha256 = legacy_definition["state_sha256"]
        with self.service._connect() as connection:
            connection.execute(
                """
                UPDATE medical_writing_authoring_journeys
                SET payload_json = ?
                WHERE project_id = ?
                """,
                (json.dumps(legacy_payload, ensure_ascii=False), project_id),
            )
            connection.commit()

        migrated = self.service.get(project_id)
        definition = migrated.study_definition
        self.assertEqual(legacy_definition_revision + 1, definition.revision)
        self.assertNotEqual(legacy_definition_sha256, definition.state_sha256)
        self.assertEqual(
            "confirmed",
            definition.field_states[
                "framing.structured_design.randomization_mode"
            ].status,
        )
        self.assertEqual(
            "confirmed",
            definition.field_states[
                "framing.product_profile.technology_type"
            ].status,
        )
        self.assertNotIn(
            "framing.structured_design.schema_version",
            definition.field_states,
        )
        self.assertEqual(definition.revision, self.service.get(project_id).study_definition.revision)
        self.assertEqual(
            definition.state_sha256,
            self.service.get(project_id).study_definition.state_sha256,
        )

    def test_legacy_framing_payload_loads_without_product_profile_or_ib(self):
        legacy_payload = _complete_framing().model_dump(mode="json")
        legacy_payload.pop("product_profile")
        legacy_payload.pop("minimum_product_fact_packet")

        framing = MedicalWritingStudyFraming.model_validate(legacy_payload)

        self.assertEqual("unknown", framing.product_profile.technology_type)
        self.assertEqual(
            "not_provided", framing.minimum_product_fact_packet.ib_status
        )
        self.assertNotIn("ib_status", framing.missing_required_fields())
        self.assertTrue(framing.creation_minimum_complete())

    def test_target_mechanism_is_enrichment_not_a_framing_completion_gate(self):
        framing = _complete_framing().model_copy(
            update={
                "target_mechanism": "",
                "competitor_target_scope": "",
            },
            deep=True,
        )

        self.assertEqual([], framing.missing_required_fields())
        _, triage_criteria, _ = medical_writing_competitor_search_contract(framing)
        self.assertNotIn(
            "target_mechanism",
            [criterion.criterion_id for criterion in triage_criteria],
        )

    def test_exact_three_facts_create_and_execute_search_before_full_framing(self):
        project_id = "proj_rux_ad_minimum_search"
        framing = MedicalWritingStudyFraming(
            investigational_product="磷酸芦可替尼乳膏",
            indication="特应性皮炎",
            study_phase="III期",
        )

        created = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=framing,
                actor="medical_manager_test",
                idempotency_key="create-rux-ad-minimum-search",
            ),
        )

        self.assertFalse(created.framing_complete)
        self.assertEqual(
            [
                "protocol_id",
                "document_title",
                "design_pattern",
                "population_intent",
                "intrinsic_objectives",
            ],
            created.framing.missing_required_fields(),
        )
        self.assertIsNotNone(created.search_plan)
        self.assertEqual(
            "atopic dermatitis",
            created.search_plan.registry_filter.condition_term,
        )
        self.assertEqual(["PHASE3"], created.search_plan.registry_filter.phases)
        self.assertEqual([], created.search_plan.triage_criteria)
        self.assertEqual(
            "confirmed",
            created.study_definition.field_states[
                "framing.investigational_product"
            ].status,
        )
        self.assertEqual(
            "missing",
            created.study_definition.field_states[
                "framing.intrinsic_objectives"
            ].status,
        )

        search_request = self.service.build_competitor_search_request(
            project_id,
            MedicalWritingCompetitorSearchExecuteRequest(
                search_plan_id=created.search_plan.plan_id,
                actor="medical_manager_test",
                idempotency_key="execute-rux-ad-minimum-search",
            ),
        )
        self.assertEqual("atopic dermatitis", search_request.search.indication)
        self.assertEqual(["PHASE3"], search_request.search.phases)

    def test_missing_any_one_of_three_search_facts_blocks_plan_and_execution(self):
        complete = {
            "investigational_product": "磷酸芦可替尼乳膏",
            "indication": "特应性皮炎",
            "study_phase": "III期",
        }
        for missing_field in complete:
            payload = {**complete, missing_field: ""}
            project_id = f"proj_rux_ad_missing_{missing_field}"
            created = self.service.create(
                project_id,
                MedicalWritingAuthoringJourneyCreateRequest(
                    framing=MedicalWritingStudyFraming(**payload),
                    actor="medical_manager_test",
                    idempotency_key=f"create-rux-ad-missing-{missing_field}",
                ),
            )
            self.assertIsNone(created.search_plan)
            self.assertEqual(
                [missing_field],
                created.framing.creation_minimum_missing_fields(),
            )
            with self.assertRaisesRegex(ValueError, "creation minimum"):
                self.service.build_competitor_search_request(
                    project_id,
                    MedicalWritingCompetitorSearchExecuteRequest(
                        search_plan_id="missing",
                        actor="medical_manager_test",
                        idempotency_key=f"execute-rux-ad-missing-{missing_field}",
                    ),
                )

    def test_three_fact_draft_unlocks_search_without_confirming_other_draft_fields(self):
        project_id = "proj_rux_ad_three_fact_draft"
        created = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                actor="medical_manager_test",
                idempotency_key="create-rux-ad-draft-shell",
            ),
        )
        draft_framing = MedicalWritingStudyFraming(
            protocol_id="RUX-03-002",
            document_title="磷酸芦可替尼乳膏治疗特应性皮炎的III期临床研究方案",
            investigational_product="磷酸芦可替尼乳膏",
            indication="特应性皮炎",
            study_phase="III期",
            intrinsic_objectives=["确证性研究"],
            target_mechanism="JAK1/JAK2抑制剂",
            design_pattern="随机、双盲、安慰剂对照",
            population_intent="中重度特应性皮炎患者",
        )

        saved = self.service.save_stage_draft(
            project_id,
            MedicalWritingAuthoringJourneyDraftSaveRequest(
                expected_revision=created.revision,
                stage="framing",
                framing=draft_framing,
                actor="medical_manager_test",
                idempotency_key="save-rux-ad-three-fact-draft",
            ),
        )

        self.assertFalse(saved.framing_complete)
        self.assertIsNotNone(saved.framing_draft)
        self.assertEqual(
            "JAK1/JAK2抑制剂",
            saved.framing_draft.framing.target_mechanism,
        )
        self.assertEqual("", saved.framing.target_mechanism)
        self.assertEqual([], saved.framing.intrinsic_objectives)
        self.assertEqual("", saved.framing.design_pattern)
        self.assertEqual("", saved.framing.population_intent)
        self.assertEqual("", saved.framing.investigational_product)
        self.assertEqual(
            "missing",
            saved.study_definition.field_states[
                "framing.investigational_product"
            ].status,
        )
        self.assertEqual(
            "missing",
            saved.study_definition.field_states[
                "framing.target_mechanism"
            ].status,
        )
        self.assertIsNotNone(saved.search_plan)
        self.assertEqual(
            "atopic dermatitis",
            saved.search_plan.registry_filter.condition_term,
        )
        self.assertEqual(
            {
                "target_mechanism",
                "intrinsic_objectives",
                "design_pattern",
                "population_intent",
            },
            {
                item.criterion_id
                for item in saved.search_plan.triage_criteria
            },
        )
        search_request = self.service.build_competitor_search_request(
            project_id,
            MedicalWritingCompetitorSearchExecuteRequest(
                search_plan_id=saved.search_plan.plan_id,
                actor="medical_manager_test",
                idempotency_key="execute-rux-ad-three-fact-draft",
            ),
        )
        self.assertEqual("atopic dermatitis", search_request.search.indication)
        self.assertEqual([], search_request.search.intervention_terms)

    def test_minimum_search_snapshot_is_available_to_later_prefill(self):
        project_id = "proj_ra_minimum_search_prefill"
        created = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=MedicalWritingStudyFraming(
                    investigational_product="CMS-RA-201注射液",
                    indication="类风湿关节炎",
                    study_phase="II期",
                ),
                actor="medical_manager_test",
                idempotency_key="create-ra-minimum-search-prefill",
            ),
        )
        snapshot = _search_snapshot(project_id).model_copy(
            update={
                "request": WritingReferenceSearchRequest(
                    indication="类风湿关节炎",
                    phases=["PHASE2"],
                )
            },
            deep=True,
        )
        attached = self.service.attach_search_snapshot(
            project_id,
            snapshot,
            MedicalWritingCompetitorSearchExecuteRequest(
                search_plan_id=created.search_plan.plan_id,
                actor="medical_manager_test",
                idempotency_key="attach-ra-minimum-search-prefill",
            ),
        )
        generated = self.service.generate_prefill(
            project_id,
            AuthoringPrefillGenerateRequest(
                expected_revision=attached.revision,
                force=True,
                actor="medical_manager_test",
                idempotency_key="prefill-ra-minimum-search-snapshot",
            ),
            snapshot=snapshot,
        )

        self.assertEqual(
            snapshot.snapshot_id,
            generated.prefill_package.search_snapshot_id,
        )
        self.assertFalse(generated.framing_complete)
        self.assertEqual(
            "missing",
            generated.study_definition.field_states[
                "framing.intrinsic_objectives"
            ].status,
        )

    def test_no_ib_is_a_normal_minimum_fact_packet_state(self):
        packet = MedicalWritingMinimumProductFactPacket(
            ib_status="not_available",
            status="sufficient_for_research",
            supporting_source_ids=["ctgov:NCT00000001", "publication:PMID123456"],
            unresolved_high_impact_fields=[
                "first_in_human_starting_dose",
                "nonclinical_safety_margin",
            ],
            safe_to_start_competitor_research=True,
            safe_to_generate_protocol_candidates=False,
        )

        self.assertEqual([], packet.ib_source_ids)
        self.assertTrue(packet.safe_to_start_competitor_research)
        self.assertFalse(packet.safe_to_generate_protocol_candidates)

    def test_product_modality_and_route_change_competitor_applicability_facets(self):
        profiles = {
            "injectable_mab": MedicalWritingInvestigationalProductProfile(
                technology_type="monoclonal_antibody",
                technology_description="人源化单克隆抗体",
                administration_routes=["皮下注射"],
                dosage_forms=["注射液"],
                exposure_scope="systemic",
            ),
            "oral_small_molecule": MedicalWritingInvestigationalProductProfile(
                technology_type="small_molecule",
                technology_description="口服小分子抑制剂",
                administration_routes=["口服"],
                dosage_forms=["片剂"],
                exposure_scope="systemic",
            ),
            "local_product": MedicalWritingInvestigationalProductProfile(
                technology_type="small_molecule",
                technology_description="局部外用小分子制剂",
                administration_routes=["外用"],
                dosage_forms=["乳膏"],
                exposure_scope="local",
            ),
        }

        observed = {}
        for key, profile in profiles.items():
            framing = _complete_framing().model_copy(
                update={"product_profile": profile}, deep=True
            )
            _registry_filter, criteria, queries = (
                medical_writing_competitor_search_contract(framing)
            )
            observed[key] = {
                item.criterion_id: item.value for item in criteria
            }, queries

        self.assertEqual(
            "人源化单克隆抗体", observed["injectable_mab"][0]["product_technology"]
        )
        self.assertEqual(
            "口服", observed["oral_small_molecule"][0]["administration_route"]
        )
        self.assertEqual("local", observed["local_product"][0]["exposure_scope"])
        self.assertNotEqual(
            observed["injectable_mab"][1][-1],
            observed["oral_small_molecule"][1][-1],
        )
        self.assertNotEqual(
            observed["oral_small_molecule"][1][-1],
            observed["local_product"][1][-1],
        )

    def test_edited_imported_fact_drops_old_evidence_and_reprojects_synopsis(self):
        project_id = "proj_ra_synopsis_edit_provenance"
        imported = _review_pending_synopsis_import()
        created = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                entry_mode="synopsis_import",
                actor="medical_manager_test",
                idempotency_key="create-ra-synopsis-edit-provenance",
            ),
        )
        attached = self.service.attach_synopsis_import(
            project_id,
            imported,
            expected_revision=created.revision,
            actor="medical_manager_test",
            idempotency_key="attach-ra-synopsis-edit-provenance",
        )
        edited_framing = _complete_framing(
            indication="银屑病关节炎",
            clinicaltrials_condition_term="Psoriatic Arthritis",
        )

        confirmed = self.service.confirm_synopsis_import(
            project_id,
            MedicalWritingSynopsisImportConfirmRequest(
                expected_revision=attached.revision,
                source_id=imported.source.source_id,
                framing=edited_framing,
                picos=imported.proposed_picos,
                synopsis_text=imported.proposed_synopsis_text,
                actor="medical_manager_test",
                idempotency_key="confirm-ra-to-psa-synopsis",
            ),
        )

        indication_state = confirmed.study_definition.field_states[
            "framing.indication"
        ]
        self.assertEqual("confirmed", indication_state.status)
        self.assertEqual("medical_manager_edit", indication_state.value_origin)
        self.assertEqual([], indication_state.evidence)
        self.assertEqual("medical_manager_test", indication_state.reviewed_by)
        self.assertIsNotNone(indication_state.reviewed_at)
        self.assertEqual("medical_manager_test", indication_state.confirmed_by)
        self.assertIsNotNone(indication_state.confirmed_at)
        self.assertIn(
            "适应症：银屑病关节炎", confirmed.study_definition.synopsis_text
        )
        self.assertEqual(
            "deterministic_projection", confirmed.study_definition.synopsis_origin
        )
        self.assertNotIn(
            "适应症：类风湿关节炎", confirmed.study_definition.synopsis_text
        )

    def test_unchanged_imported_fact_retains_source_evidence_after_review(self):
        project_id = "proj_ra_synopsis_unchanged_provenance"
        imported = _review_pending_synopsis_import()
        created = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                entry_mode="synopsis_import",
                actor="medical_manager_test",
                idempotency_key="create-ra-synopsis-unchanged-provenance",
            ),
        )
        attached = self.service.attach_synopsis_import(
            project_id,
            imported,
            expected_revision=created.revision,
            actor="medical_manager_test",
            idempotency_key="attach-ra-synopsis-unchanged-provenance",
        )

        confirmed = self.service.confirm_synopsis_import(
            project_id,
            MedicalWritingSynopsisImportConfirmRequest(
                expected_revision=attached.revision,
                source_id=imported.source.source_id,
                framing=imported.proposed_framing,
                picos=imported.proposed_picos,
                synopsis_text=imported.proposed_synopsis_text,
                actor="medical_manager_test",
                idempotency_key="confirm-unchanged-ra-synopsis",
            ),
        )

        indication_state = confirmed.study_definition.field_states[
            "framing.indication"
        ]
        self.assertEqual("confirmed", indication_state.status)
        self.assertEqual("source_extraction", indication_state.value_origin)
        self.assertEqual(1, len(indication_state.evidence))
        self.assertEqual(
            "mwsynopsis_span_indication",
            indication_state.evidence[0].evidence_span_id,
        )
        self.assertEqual("medical_manager_test", indication_state.reviewed_by)
        self.assertIsNotNone(indication_state.reviewed_at)
        self.assertEqual("medical_manager_test", indication_state.confirmed_by)
        self.assertIsNotNone(indication_state.confirmed_at)
        self.assertEqual(
            imported.proposed_synopsis_text,
            confirmed.study_definition.synopsis_text,
        )
        self.assertEqual("imported_text", confirmed.study_definition.synopsis_origin)

    def test_unchanged_imported_nested_fact_inherits_parent_source_evidence(self):
        project_id = "proj_ra_synopsis_nested_provenance"
        imported = _review_pending_synopsis_import()
        product_text = "试验药物为皮下注射用人源化单克隆抗体。"
        product_span = MedicalWritingSynopsisEvidenceSpan(
            span_id="mwsynopsis_span_product_profile",
            source_id=imported.source.source_id,
            locator="docx:paragraph:4",
            source_text=product_text,
            source_text_sha256=hashlib.sha256(
                product_text.encode("utf-8")
            ).hexdigest(),
        )
        framing = imported.proposed_framing.model_copy(
            update={
                "product_profile": MedicalWritingInvestigationalProductProfile(
                    technology_type="monoclonal_antibody",
                    technology_description="人源化单克隆抗体",
                    administration_routes=["皮下注射"],
                    dosage_forms=["注射液"],
                    exposure_scope="systemic",
                )
            },
            deep=True,
        )
        imported = imported.model_copy(
            update={
                "proposed_framing": framing,
                "field_evidence_span_ids": {
                    **imported.field_evidence_span_ids,
                    "framing.product_profile": [
                        "mwsynopsis_span_product_profile"
                    ],
                },
                "evidence_spans": [*imported.evidence_spans, product_span],
            },
            deep=True,
        )
        created = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                entry_mode="synopsis_import",
                actor="medical_manager_test",
                idempotency_key="create-ra-synopsis-nested-provenance",
            ),
        )
        attached = self.service.attach_synopsis_import(
            project_id,
            imported,
            expected_revision=created.revision,
            actor="medical_manager_test",
            idempotency_key="attach-ra-synopsis-nested-provenance",
        )
        confirmed = self.service.confirm_synopsis_import(
            project_id,
            MedicalWritingSynopsisImportConfirmRequest(
                expected_revision=attached.revision,
                source_id=imported.source.source_id,
                framing=framing,
                picos=imported.proposed_picos,
                synopsis_text=imported.proposed_synopsis_text,
                actor="medical_manager_test",
                idempotency_key="confirm-ra-synopsis-nested-provenance",
            ),
        )

        for path in (
            "framing.product_profile.technology_type",
            "framing.product_profile.administration_routes",
            "framing.product_profile.dosage_forms",
            "framing.product_profile.exposure_scope",
        ):
            state = confirmed.study_definition.field_states[path]
            self.assertEqual("confirmed", state.status, path)
            self.assertEqual("source_extraction", state.value_origin, path)
            self.assertEqual(
                ["mwsynopsis_span_product_profile"],
                [item.evidence_span_id for item in state.evidence],
                path,
            )

    def test_later_upstream_edit_cannot_leave_imported_synopsis_current(self):
        project_id = "proj_ra_synopsis_later_psa_edit"
        imported = _review_pending_synopsis_import()
        created = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                entry_mode="synopsis_import",
                actor="medical_manager_test",
                idempotency_key="create-ra-synopsis-later-edit",
            ),
        )
        attached = self.service.attach_synopsis_import(
            project_id,
            imported,
            expected_revision=created.revision,
            actor="medical_manager_test",
            idempotency_key="attach-ra-synopsis-later-edit",
        )
        reviewed = self.service.confirm_synopsis_import(
            project_id,
            MedicalWritingSynopsisImportConfirmRequest(
                expected_revision=attached.revision,
                source_id=imported.source.source_id,
                framing=imported.proposed_framing,
                picos=imported.proposed_picos,
                synopsis_text=imported.proposed_synopsis_text,
                actor="medical_manager_test",
                idempotency_key="confirm-ra-synopsis-before-later-edit",
            ),
        )
        framed = self.service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=reviewed.revision,
                stage="framing",
                framing=imported.proposed_framing,
                actor="medical_manager_test",
                idempotency_key="commit-ra-framing-before-later-edit",
            ),
        )
        designed = self.service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=framed.revision,
                stage="picos",
                picos=imported.proposed_picos,
                actor="medical_manager_test",
                idempotency_key="commit-ra-picos-before-later-edit",
            ),
        )
        psa_framing = _complete_framing(
            indication="银屑病关节炎",
            clinicaltrials_condition_term="Psoriatic Arthritis",
        )
        preview = self.service.impact_preview(
            project_id,
            MedicalWritingJourneyImpactPreviewRequest(
                expected_revision=designed.revision,
                stage="framing",
                framing=psa_framing,
            ),
        )
        changed = self.service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=designed.revision,
                stage="framing",
                framing=psa_framing,
                impact_preview_id=preview.preview_id,
                actor="medical_director_test",
                idempotency_key="commit-later-psa-framing",
            ),
        )

        indication_state = changed.study_definition.field_states[
            "framing.indication"
        ]
        self.assertEqual("confirmed", indication_state.status)
        self.assertEqual("medical_manager_edit", indication_state.value_origin)
        self.assertEqual([], indication_state.evidence)
        self.assertEqual("medical_director_test", indication_state.reviewed_by)
        self.assertEqual(
            "deterministic_projection", changed.study_definition.synopsis_origin
        )
        self.assertIn("适应症：银屑病关节炎", changed.study_definition.synopsis_text)
        self.assertNotIn("适应症：类风湿关节炎", changed.study_definition.synopsis_text)

    def test_two_stage_journey_persists_search_plan_and_keeps_corpus_not_ready(self):
        project_id = "proj_synthetic_ra_journey"
        created = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=MedicalWritingStudyFraming(
                    protocol_id="CMS-RA-201",
                    version="V0.1",
                ),
                actor="medical_manager_test",
                idempotency_key="create-ra-journey",
            ),
        )
        self.assertEqual("stage1_in_progress", created.status)
        self.assertFalse(created.framing_complete)
        self.assertIsNone(created.search_plan)

        framing = _complete_framing()
        framing_preview = self.service.impact_preview(
            project_id,
            MedicalWritingJourneyImpactPreviewRequest(
                expected_revision=1,
                stage="framing",
                framing=framing,
            ),
        )
        self.assertFalse(framing_preview.requires_confirmation)
        framed = self.service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=1,
                stage="framing",
                framing=framing,
                actor="medical_manager_test",
                idempotency_key="commit-ra-framing",
            ),
        )
        self.assertEqual("stage1_complete", framed.status)
        self.assertTrue(framed.framing_complete)
        self.assertEqual("broad_then_triage", framed.search_plan.strategy)
        self.assertEqual(["protocol"], framed.search_plan.document_roles)
        self.assertTrue(any("Rheumatoid Arthritis" in query for query in framed.search_plan.queries))
        self.assertEqual(
            "Rheumatoid Arthritis",
            framed.search_plan.registry_filter.condition_term,
        )
        self.assertEqual(["PHASE2"], framed.search_plan.registry_filter.phases)
        self.assertEqual(
            "INTERVENTIONAL",
            framed.search_plan.registry_filter.study_type,
        )
        self.assertEqual([], framed.search_plan.registry_filter.intervention_terms)
        self.assertEqual([], framed.search_plan.registry_filter.regions)
        self.assertEqual(
            [
                "target_mechanism",
                "intrinsic_objectives",
                "design_pattern",
                "population_intent",
            ],
            [item.criterion_id for item in framed.search_plan.triage_criteria],
        )
        self.assertTrue(
            all(
                "protocol OR SAP" not in query
                for query in framed.search_plan.queries
            )
        )
        search_request = self.service.build_competitor_search_request(
            project_id,
            MedicalWritingCompetitorSearchExecuteRequest(
                search_plan_id=framed.search_plan.plan_id,
                idempotency_key="search-ra-request",
            ),
        )
        self.assertEqual("Rheumatoid Arthritis", search_request.search.indication)

        self.assertEqual(
            framed.search_plan.registry_filter.phases,
            search_request.search.phases,
        )
        self.assertEqual(
            framed.search_plan.registry_filter.study_type,
            search_request.search.study_type,
        )

        designed = self.service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=framed.revision,
                stage="picos",
                picos=_complete_picos(),
                actor="medical_manager_test",
                idempotency_key="commit-ra-picos",
            ),
        )
        self.assertEqual("corpus_not_ready", designed.status)
        self.assertTrue(designed.picos_complete)
        self.assertEqual("guided_greenfield", designed.study_definition.origin)
        self.assertIn("主要终点：第12周ACR20应答率。", designed.study_definition.synopsis_text)
        self.assertEqual(
            "confirmed",
            designed.study_definition.field_states["picos.primary_endpoint"].status,
        )
        self.assertEqual("not_ready", designed.corpus_gate.readiness_status)
        self.assertFalse(designed.corpus_gate.access_permitted)
        with self.assertRaisesRegex(ValueError, "corpus is not ready"):
            self.service.require_writing_access(project_id)

        restarted = MedicalWritingAuthoringJourneyService(self.service.db_path)
        persisted = restarted.get(project_id)
        self.assertEqual(designed.revision, persisted.revision)
        self.assertEqual("第12周ACR20应答率。", persisted.picos.primary_endpoint)

    def test_historical_protocol_and_sap_search_plan_is_read_as_protocol_only(self):
        project_id = "proj_historical_protocol_and_sap_plan"
        created = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_complete_framing(),
                actor="medical_manager_test",
                idempotency_key="create-historical-search-plan",
            ),
        )
        historical_payload = created.model_dump(mode="json")
        historical_payload["search_plan"]["document_roles"] = ["protocol", "sap"]
        historical_json = json.dumps(historical_payload, ensure_ascii=False)

        with self.service._connect() as connection:
            connection.execute(
                """
                UPDATE medical_writing_authoring_journeys
                SET payload_json = ?
                WHERE project_id = ?
                """,
                (historical_json, project_id),
            )
            connection.commit()

        projected = self.service.get(project_id)
        self.assertEqual(["protocol"], projected.search_plan.document_roles)

        with self.service._connect() as connection:
            stored = connection.execute(
                """
                SELECT payload_json
                FROM medical_writing_authoring_journeys
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()
        self.assertEqual(
            ["protocol", "sap"],
            json.loads(stored["payload_json"])["search_plan"]["document_roles"],
        )

    def test_incomplete_draft_persists_without_completing_or_invalidating_stage(self):
        project_id = "proj_synthetic_ra_draft"
        created = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=MedicalWritingStudyFraming(protocol_id="CMS-RA-DRAFT"),
                actor="medical_manager_test",
                idempotency_key="create-ra-draft",
            ),
        )
        partial = MedicalWritingStudyFraming(
            protocol_id="CMS-RA-DRAFT",
            document_title="类风湿关节炎早期临床研究方案",
            indication="类风湿关节炎",
        )
        request = MedicalWritingAuthoringJourneyDraftSaveRequest(
            expected_revision=created.revision,
            stage="framing",
            framing=partial,
            actor="medical_manager_test",
            idempotency_key="save-ra-framing-draft",
        )
        saved = self.service.save_stage_draft(project_id, request)
        self.assertEqual("stage1_in_progress", saved.status)
        self.assertFalse(saved.framing_complete)
        self.assertIsNone(saved.search_plan)
        self.assertEqual("CMS-RA-DRAFT", saved.framing.protocol_id)
        self.assertEqual("类风湿关节炎", saved.framing_draft.framing.indication)
        self.assertNotIn(
            "clinicaltrials_condition_term",
            saved.framing_draft.missing_required_fields,
        )

        replayed = self.service.save_stage_draft(project_id, request)
        self.assertEqual(saved.revision, replayed.revision)
        persisted = MedicalWritingAuthoringJourneyService(self.service.db_path).get(project_id)
        self.assertEqual(
            partial.model_dump(), persisted.framing_draft.framing.model_dump()
        )

    def test_draft_of_completed_framing_does_not_mutate_committed_downstream(self):
        project_id = "proj_synthetic_ra_downstream_draft"
        framed = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_complete_framing(),
                actor="medical_manager_test",
                idempotency_key="create-ra-downstream-draft",
            ),
        )
        designed = self.service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=framed.revision,
                stage="picos",
                picos=_complete_picos(),
                actor="medical_manager_test",
                idempotency_key="commit-ra-downstream-draft-picos",
            ),
        )
        changed_framing = _complete_framing(
            indication="银屑病关节炎",
            clinicaltrials_condition_term="Psoriatic Arthritis",
        )
        saved = self.service.save_stage_draft(
            project_id,
            MedicalWritingAuthoringJourneyDraftSaveRequest(
                expected_revision=designed.revision,
                stage="framing",
                framing=changed_framing,
                actor="medical_manager_test",
                idempotency_key="save-upstream-framing-draft",
            ),
        )
        self.assertEqual("类风湿关节炎", saved.framing.indication)
        self.assertEqual("银屑病关节炎", saved.framing_draft.framing.indication)
        self.assertTrue(saved.picos_complete)
        self.assertEqual(designed.search_plan.plan_id, saved.search_plan.plan_id)
        self.assertEqual(designed.invalidated_dependents, saved.invalidated_dependents)

    def test_framing_commit_preserves_uncommitted_picos_draft(self):
        project_id = "proj_synthetic_ra_preserve_picos_draft"
        framed = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_complete_framing(),
                actor="medical_manager_test",
                idempotency_key="create-ra-preserve-picos-draft",
            ),
        )
        incomplete_picos = _complete_picos().model_copy(
            update={"estimand_strategy": ""},
            deep=True,
        )
        picos_drafted = self.service.save_stage_draft(
            project_id,
            MedicalWritingAuthoringJourneyDraftSaveRequest(
                expected_revision=framed.revision,
                stage="picos",
                picos=incomplete_picos,
                actor="medical_manager_test",
                idempotency_key="save-ra-picos-before-framing-change",
            ),
        )
        changed_framing = framed.framing.model_copy(
            update={"clinicaltrials_condition_term": "Rheumatoid Arthritis (RA)"},
            deep=True,
        )
        framing_drafted = self.service.save_stage_draft(
            project_id,
            MedicalWritingAuthoringJourneyDraftSaveRequest(
                expected_revision=picos_drafted.revision,
                stage="framing",
                framing=changed_framing,
                actor="medical_manager_test",
                idempotency_key="save-ra-framing-with-picos-draft",
            ),
        )
        preview = self.service.impact_preview(
            project_id,
            MedicalWritingJourneyImpactPreviewRequest(
                expected_revision=framing_drafted.revision,
                stage="framing",
                framing=changed_framing,
            ),
        )
        self.assertTrue(preview.requires_confirmation)

        committed = self.service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=framing_drafted.revision,
                stage="framing",
                framing=changed_framing,
                impact_preview_id=preview.preview_id,
                actor="medical_manager_test",
                idempotency_key="commit-ra-framing-preserve-picos-draft",
            ),
        )

        self.assertTrue(committed.framing_complete)
        self.assertFalse(committed.picos_complete)
        self.assertIsNotNone(committed.picos_draft)
        self.assertEqual(
            incomplete_picos.model_dump(),
            committed.picos_draft.picos.model_dump(),
        )
        self.assertIn(
            "estimand_strategy",
            committed.picos_draft.missing_required_fields,
        )
        self.assertIn("competitor_search_plan", committed.invalidated_dependents)

    def test_second_draft_from_stale_revision_is_rejected(self):
        project_id = "proj_synthetic_ra_stale_draft"
        created = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=MedicalWritingStudyFraming(protocol_id="CMS-RA-STALE"),
                actor="medical_manager_test",
                idempotency_key="create-ra-stale-draft",
            ),
        )
        first = self.service.save_stage_draft(
            project_id,
            MedicalWritingAuthoringJourneyDraftSaveRequest(
                expected_revision=created.revision,
                stage="framing",
                framing=MedicalWritingStudyFraming(
                    protocol_id="CMS-RA-STALE", indication="类风湿关节炎"
                ),
                actor="medical_manager_test",
                idempotency_key="save-first-stale-draft",
            ),
        )
        self.assertEqual(created.revision + 1, first.revision)
        with self.assertRaisesRegex(
            MedicalWritingAuthoringJourneyConflictError, "stale authoring journey revision"
        ):
            self.service.save_stage_draft(
                project_id,
                MedicalWritingAuthoringJourneyDraftSaveRequest(
                    expected_revision=created.revision,
                    stage="framing",
                    framing=MedicalWritingStudyFraming(
                        protocol_id="CMS-RA-STALE", indication="银屑病关节炎"
                    ),
                    actor="medical_manager_test",
                    idempotency_key="save-second-stale-draft",
                ),
            )

    def test_picos_applicability_depends_on_explicit_design_archetype(self):
        not_applicable = MedicalWritingPicosFieldApplicability(
            status="not_applicable",
            reason="该研究为无同期对照的单臂剂量探索设计。",
            confirmed_by_medical_manager=True,
        )
        with self.assertRaisesRegex(
            ValueError,
            "cannot be marked not applicable for a randomized confirmatory design",
        ):
            _complete_picos(
                comparator_summary="",
                field_applicability={"comparator_summary": not_applicable},
            )

        with self.assertRaisesRegex(
            ValueError, "cannot contain a value when marked not applicable"
        ):
            _complete_picos(
                design_archetype="single_arm_early_phase",
                field_applicability={"comparator_summary": not_applicable},
            )

        single_arm = _complete_picos(
            design_archetype="single_arm_early_phase",
            comparator_summary="",
            estimand_strategy="",
            field_applicability={
                "comparator_summary": not_applicable,
                "estimand_strategy": MedicalWritingPicosFieldApplicability(
                    status="not_applicable",
                    reason="当前阶段以安全性、耐受性和药代动力学描述为主。",
                    confirmed_by_medical_manager=True,
                ),
            },
        )
        self.assertEqual([], single_arm.missing_required_fields())

        randomized_exploratory = _complete_picos(
            design_archetype="randomized_exploratory",
            comparator_summary="低剂量组与高剂量组平行对照。",
            estimand_strategy="",
            field_applicability={
                "estimand_strategy": MedicalWritingPicosFieldApplicability(
                    status="not_applicable",
                    reason="本剂量探索研究以组内变化和描述性剂量比较为主，不预设确证性治疗效应估计目标。",
                    confirmed_by_medical_manager=True,
                ),
            },
        )
        self.assertEqual([], randomized_exploratory.missing_required_fields())
        self.assertIn(
            "comparator_summary",
            randomized_exploratory.model_copy(
                update={"comparator_summary": ""},
            ).missing_required_fields(),
        )
        with self.assertRaisesRegex(
            ValueError,
            "cannot be marked not applicable for a randomized exploratory design",
        ):
            _complete_picos(
                design_archetype="randomized_exploratory",
                comparator_summary="",
                field_applicability={"comparator_summary": not_applicable},
            )

        ole = _complete_picos(
            design_archetype="open_label_extension",
            comparator_summary="",
            field_applicability={"comparator_summary": not_applicable},
        )
        self.assertNotIn("comparator_summary", ole.missing_required_fields())

        incomplete_reason = single_arm.model_copy(
            update={
                "field_applicability": {
                    "comparator_summary": MedicalWritingPicosFieldApplicability(
                        status="not_applicable",
                        reason="单臂",
                        confirmed_by_medical_manager=True,
                    ),
                    "estimand_strategy": single_arm.field_applicability[
                        "estimand_strategy"
                    ],
                }
            }
        )
        self.assertIn("comparator_summary", incomplete_reason.missing_required_fields())

    def test_legacy_v1_journey_migrates_design_and_fails_closed_when_incomplete(self):
        project_id = "proj_synthetic_ra_legacy_v1"
        framed = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_complete_framing(),
                actor="medical_manager_test",
                idempotency_key="create-ra-legacy-v1",
            ),
        )
        designed = self.service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=framed.revision,
                stage="picos",
                picos=_complete_picos(),
                actor="medical_manager_test",
                idempotency_key="commit-ra-legacy-v1-picos",
            ),
        )
        missing = list(designed.corpus_gate.missing_requirements)
        allowed = self.service.override_corpus_gate(
            project_id,
            MedicalWritingCorpusGateOverrideRequest(
                expected_revision=designed.revision,
                reason="验证旧版建项记录迁移时继续保留已经确认的正式研究事实。",
                acknowledged_missing_requirements=missing,
                actor="medical_manager_test",
                idempotency_key="override-ra-legacy-v1",
            ),
        )

        legacy_payload = allowed.model_dump(mode="json")
        legacy_payload["schema_version"] = "medical_writing_authoring_journey_v1"
        legacy_payload["picos"]["design_archetype"] = ""
        legacy_payload["search_plan"] = dict(legacy_payload["search_plan"])
        original_plan_id = legacy_payload["search_plan"]["plan_id"]
        legacy_payload["search_plan"].pop("registry_filter")
        legacy_payload["search_plan"].pop("triage_criteria")
        legacy_payload["search_plan"]["queries"] = [
            "Rheumatoid Arthritis 同靶点、同机制及同治疗线生物制剂 II期",
            "Rheumatoid Arthritis 概念验证（PoC） 剂量探索 interventional",
            "Rheumatoid Arthritis 同靶点、同机制及同治疗线生物制剂 protocol OR SAP",
        ]
        legacy_payload["search_plan"]["status"] = "triage_pending"
        legacy_payload["search_plan"]["latest_snapshot_id"] = "wref_search_legacy_ra"
        legacy_payload["search_plan"]["returned_count"] = 652
        legacy_payload["search_plan"]["public_document_count"] = 8
        migrated = MedicalWritingAuthoringJourney.model_validate(legacy_payload)
        self.assertEqual("medical_writing_authoring_journey_v4", migrated.schema_version)
        self.assertEqual("randomized_confirmatory", migrated.picos.design_archetype)
        self.assertTrue(migrated.picos_complete)
        self.assertTrue(migrated.corpus_gate.access_permitted)
        self.assertEqual(original_plan_id, migrated.search_plan.plan_id)
        self.assertEqual("wref_search_legacy_ra", migrated.search_plan.latest_snapshot_id)
        self.assertEqual(652, migrated.search_plan.returned_count)
        self.assertEqual(
            "Rheumatoid Arthritis",
            migrated.search_plan.registry_filter.condition_term,
        )
        self.assertEqual(["PHASE2"], migrated.search_plan.registry_filter.phases)
        self.assertEqual(
            [
                "target_mechanism",
                "intrinsic_objectives",
                "design_pattern",
                "population_intent",
            ],
            [item.criterion_id for item in migrated.search_plan.triage_criteria],
        )
        self.assertEqual(
            [
                "疾病/适应症：Rheumatoid Arthritis",
                "研究分期：PHASE2",
                "研究类型：INTERVENTIONAL",
            ],
            migrated.search_plan.queries,
        )
        self.assertNotIn(
            "同靶点",
            " ".join(migrated.search_plan.queries),
        )

        with self.service._connect() as connection:
            connection.execute(
                "UPDATE medical_writing_authoring_journeys SET payload_json = ? WHERE project_id = ?",
                (json.dumps(legacy_payload, ensure_ascii=False), project_id),
            )
            connection.commit()
        request = self.service.build_competitor_search_request(
            project_id,
            MedicalWritingCompetitorSearchExecuteRequest(
                search_plan_id=original_plan_id,
                idempotency_key="search-migrated-ra-request",
            ),
        )
        self.assertEqual("Rheumatoid Arthritis", request.search.indication)
        self.assertEqual(["PHASE2"], request.search.phases)
        self.assertEqual([], request.search.intervention_terms)
        self.assertEqual([], request.search.regions)

        incomplete_payload = dict(legacy_payload)
        incomplete_payload["picos"] = dict(legacy_payload["picos"])
        incomplete_payload["picos"]["comparator_summary"] = ""
        failed_closed = MedicalWritingAuthoringJourney.model_validate(
            incomplete_payload
        )
        self.assertFalse(failed_closed.picos_complete)
        self.assertFalse(failed_closed.corpus_gate.access_permitted)
        self.assertEqual("stage2_in_progress", failed_closed.status)
        self.assertEqual("picos", failed_closed.current_stage)

    def test_search_contract_is_project_agnostic_for_crswnp(self):
        project_id = "proj_synthetic_crswnp_search_contract"
        framing = _complete_framing(
            indication="伴鼻息肉的慢性鼻窦炎",
            clinicaltrials_condition_term="Chronic Rhinosinusitis with Nasal Polyps",
        ).model_copy(
            update={
                "protocol_id": "CMS-CRSWNP-301",
                "document_title": "CMS-CRSWNP-301 III期临床研究方案",
                "study_phase": "III期",
                "investigational_product": "CMS-CRSWNP-301注射液",
                "target_mechanism": "靶向2型炎症通路的单克隆抗体",
                "competitor_target_scope": "同靶点或同通路生物制剂",
                "intrinsic_objectives": ["确证性研究"],
                "population_intent": "标准治疗控制不佳的重度CRSwNP成人患者",
            }
        )
        state = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=framing,
                actor="medical_manager_test",
                idempotency_key="create-crswnp-search-contract",
            ),
        )
        self.assertEqual(
            "Chronic Rhinosinusitis with Nasal Polyps",
            state.search_plan.registry_filter.condition_term,
        )
        self.assertEqual(["PHASE3"], state.search_plan.registry_filter.phases)
        triage_values = {
            item.criterion_id: item.value for item in state.search_plan.triage_criteria
        }
        self.assertEqual("同靶点或同通路生物制剂", triage_values["target_mechanism"])
        self.assertEqual("确证性研究", triage_values["intrinsic_objectives"])
        request = self.service.build_competitor_search_request(
            project_id,
            MedicalWritingCompetitorSearchExecuteRequest(
                search_plan_id=state.search_plan.plan_id,
                idempotency_key="search-crswnp-contract",
            ),
        )
        self.assertEqual(
            "Chronic Rhinosinusitis with Nasal Polyps",
            request.search.indication,
        )
        self.assertEqual(["PHASE3"], request.search.phases)
        self.assertNotIn("同靶点", request.search.indication)

    def test_identical_commit_is_noop_and_draft_promotion_preserves_gate(self):
        project_id = "proj_synthetic_ra_noop"
        framed = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_complete_framing(),
                actor="medical_manager_test",
                idempotency_key="create-ra-noop",
            ),
        )
        designed = self.service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=framed.revision,
                stage="picos",
                picos=_complete_picos(),
                actor="medical_manager_test",
                idempotency_key="commit-ra-noop-picos",
            ),
        )
        missing = list(designed.corpus_gate.missing_requirements)
        allowed = self.service.override_corpus_gate(
            project_id,
            MedicalWritingCorpusGateOverrideRequest(
                expected_revision=designed.revision,
                reason="验证重复提交不会清空已确认的语料准入和正式研究事实。",
                acknowledged_missing_requirements=missing,
                actor="medical_manager_test",
                idempotency_key="override-ra-noop",
            ),
        )
        no_change = self.service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=allowed.revision,
                stage="picos",
                picos=allowed.picos,
                actor="medical_manager_test",
                idempotency_key="commit-ra-noop-identical",
            ),
        )
        self.assertEqual(allowed.revision, no_change.revision)
        self.assertEqual("writing_allowed", no_change.status)
        self.assertTrue(no_change.corpus_gate.access_permitted)

        drafted = self.service.save_stage_draft(
            project_id,
            MedicalWritingAuthoringJourneyDraftSaveRequest(
                expected_revision=no_change.revision,
                stage="picos",
                picos=no_change.picos,
                actor="medical_manager_test",
                idempotency_key="draft-ra-noop-identical",
            ),
        )
        promoted = self.service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=drafted.revision,
                stage="picos",
                picos=drafted.picos,
                actor="medical_manager_test",
                idempotency_key="promote-ra-noop-identical",
            ),
        )
        self.assertEqual(drafted.revision + 1, promoted.revision)
        self.assertIsNone(promoted.picos_draft)
        self.assertEqual("writing_allowed", promoted.status)
        self.assertTrue(promoted.corpus_gate.access_permitted)
        self.assertEqual(
            allowed.search_plan.model_dump(), promoted.search_plan.model_dump()
        )

    def test_identical_picos_commit_reconciles_completion_after_upstream_invalidation(self):
        project_id = "proj_synthetic_ra_picos_completion_reconcile"
        framed = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_complete_framing(),
                actor="medical_manager_test",
                idempotency_key="create-ra-picos-reconcile",
            ),
        )
        designed = self.service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=framed.revision,
                stage="picos",
                picos=_complete_picos(),
                actor="medical_manager_test",
                idempotency_key="commit-ra-picos-reconcile-first",
            ),
        )
        self.assertTrue(designed.picos_complete)

        # A confirmed upstream framing change invalidates the downstream
        # completion flag while retaining the committed PICOS values.
        changed_framing = designed.framing.model_copy(
            update={"design_pattern": "随机、双盲、安慰剂对照、平行组；修订版"},
            deep=True,
        )
        preview = self.service.impact_preview(
            project_id,
            MedicalWritingJourneyImpactPreviewRequest(
                expected_revision=designed.revision,
                stage="framing",
                framing=changed_framing,
            ),
        )
        invalidated = self.service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=designed.revision,
                stage="framing",
                framing=changed_framing,
                impact_preview_id=preview.preview_id,
                actor="medical_manager_test",
                idempotency_key="commit-ra-picos-reconcile-framing",
            ),
        )
        self.assertFalse(invalidated.picos_complete)
        self.assertEqual(invalidated.current_stage, "picos")

        reconciled = self.service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=invalidated.revision,
                stage="picos",
                picos=invalidated.picos,
                actor="medical_manager_test",
                idempotency_key="commit-ra-picos-reconcile-second",
            ),
        )
        self.assertEqual(invalidated.revision + 1, reconciled.revision)
        self.assertTrue(reconciled.picos_complete)
        self.assertEqual("corpus", reconciled.current_stage)
        self.assertEqual("corpus_not_ready", reconciled.status)
        self.assertIsNone(reconciled.picos_draft)
        self.assertEqual(
            reconciled.picos.model_dump(),
            reconciled.study_definition.picos.model_dump(),
        )
        self.assertEqual(
            "confirmed",
            reconciled.study_definition.field_states["picos.design_archetype"].status,
        )

    def test_document_creation_reservation_locks_facts_until_created_or_released(self):
        project_id = "proj_synthetic_ra_document_reservation"
        framed = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_complete_framing(),
                actor="medical_manager_test",
                idempotency_key="create-ra-document-reservation",
            ),
        )
        designed = self.service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=framed.revision,
                stage="picos",
                picos=_complete_picos(),
                actor="medical_manager_test",
                idempotency_key="commit-ra-document-reservation-picos",
            ),
        )
        allowed = self.service.override_corpus_gate(
            project_id,
            MedicalWritingCorpusGateOverrideRequest(
                expected_revision=designed.revision,
                reason="验证建立工作稿期间研究事实和准入状态保持原子绑定。",
                acknowledged_missing_requirements=list(
                    designed.corpus_gate.missing_requirements
                ),
                actor="medical_manager_test",
                idempotency_key="override-ra-document-reservation",
            ),
        )
        reservation_id = self.service.reserve_document_creation(
            project_id,
            actor="medical_manager_test",
            request_idempotency_key="create-greenfield-ra-reservation",
        )
        reserved = self.service.get(project_id)
        self.assertEqual("document_creation_reserved", reserved.status)
        self.assertEqual(
            reservation_id,
            self.service.reserve_document_creation(
                project_id,
                actor="medical_manager_test",
                request_idempotency_key="create-greenfield-ra-reservation",
            ),
        )
        with self.assertRaisesRegex(
            MedicalWritingAuthoringJourneyConflictError, "active.*reservation"
        ):
            self.service.save_stage_draft(
                project_id,
                MedicalWritingAuthoringJourneyDraftSaveRequest(
                    expected_revision=reserved.revision,
                    stage="picos",
                    picos=allowed.picos,
                    actor="medical_manager_test",
                    idempotency_key="draft-during-document-reservation",
                ),
            )
        self.service.mark_document_created(
            project_id, "medical_manager_test", reservation_id
        )
        created = self.service.get(project_id)
        self.assertEqual("document_created", created.status)
        self.assertIsNone(created.document_creation_reservation)

        second_project_id = "proj_synthetic_ra_document_release"
        framed = self.service.create(
            second_project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_complete_framing(),
                actor="medical_manager_test",
                idempotency_key="create-ra-document-release",
            ),
        )
        designed = self.service.commit_stage(
            second_project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=framed.revision,
                stage="picos",
                picos=_complete_picos(),
                actor="medical_manager_test",
                idempotency_key="commit-ra-document-release-picos",
            ),
        )
        allowed = self.service.override_corpus_gate(
            second_project_id,
            MedicalWritingCorpusGateOverrideRequest(
                expected_revision=designed.revision,
                reason="验证工作稿创建失败后可释放预约并恢复医学写作准入。",
                acknowledged_missing_requirements=list(
                    designed.corpus_gate.missing_requirements
                ),
                actor="medical_manager_test",
                idempotency_key="override-ra-document-release",
            ),
        )
        released_reservation_id = self.service.reserve_document_creation(
            second_project_id,
            actor="medical_manager_test",
            request_idempotency_key="create-greenfield-ra-release",
        )
        self.service.release_document_creation_reservation(
            second_project_id,
            reservation_id=released_reservation_id,
            actor="medical_manager_test",
        )
        released = self.service.get(second_project_id)
        self.assertEqual(allowed.revision + 2, released.revision)
        self.assertEqual("writing_allowed", released.status)
        self.assertIsNone(released.document_creation_reservation)

    def test_writing_document_binding_rejects_stale_study_definition(self):
        project_id = "proj_synthetic_ra_definition_binding"
        framed = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_complete_framing(),
                actor="medical_manager_test",
                idempotency_key="create-ra-definition-binding",
            ),
        )
        designed = self.service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=framed.revision,
                stage="picos",
                picos=_complete_picos(),
                actor="medical_manager_test",
                idempotency_key="commit-ra-definition-binding-picos",
            ),
        )
        definition = designed.study_definition
        bound = self.service.require_study_definition_binding(
            project_id,
            definition_id=definition.definition_id,
            revision=definition.revision,
            state_sha256=definition.state_sha256,
        )
        self.assertEqual(definition.state_sha256, bound.state_sha256)
        with self.assertRaisesRegex(
            MedicalWritingAuthoringJourneyConflictError, "not bound"
        ):
            self.service.require_study_definition_binding(
                project_id,
                definition_id=definition.definition_id,
                revision=definition.revision,
                state_sha256="0" * 64,
            )

    def test_reasoned_override_allows_writing_without_falsifying_readiness(self):
        project_id = "proj_synthetic_ra_override"
        framed = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_complete_framing(),
                actor="medical_manager_test",
                idempotency_key="create-complete-ra-journey",
            ),
        )
        designed = self.service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=framed.revision,
                stage="picos",
                picos=_complete_picos(),
                actor="medical_manager_test",
                idempotency_key="commit-complete-ra-picos",
            ),
        )
        missing = list(designed.corpus_gate.missing_requirements)
        overridden = self.service.override_corpus_gate(
            project_id,
            MedicalWritingCorpusGateOverrideRequest(
                expected_revision=designed.revision,
                reason="为验证完整写作工作流，医学经理确认保留全部语料缺口并例外进入。",
                acknowledged_missing_requirements=missing,
                actor="medical_manager_test",
                idempotency_key="override-ra-corpus-gate",
            ),
        )
        self.assertEqual("writing_allowed", overridden.status)
        self.assertEqual("not_ready", overridden.corpus_gate.readiness_status)
        self.assertTrue(overridden.corpus_gate.access_permitted)
        self.assertTrue(overridden.corpus_gate.override.active)
        self.assertEqual(set(missing), set(overridden.corpus_gate.override.acknowledged_missing_requirements))
        self.service.require_writing_access(project_id)

        replayed = self.service.override_corpus_gate(
            project_id,
            MedicalWritingCorpusGateOverrideRequest(
                expected_revision=designed.revision,
                reason="为验证完整写作工作流，医学经理确认保留全部语料缺口并例外进入。",
                acknowledged_missing_requirements=missing,
                actor="medical_manager_test",
                idempotency_key="override-ra-corpus-gate",
            ),
        )
        self.assertEqual(overridden.revision, replayed.revision)

    def test_search_snapshot_is_attached_to_current_plan_and_survives_reload(self):
        project_id = "proj_synthetic_ra_search_link"
        created = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_complete_framing(),
                actor="medical_manager_test",
                idempotency_key="create-ra-search-link",
            ),
        )
        designed = self.service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=created.revision,
                stage="picos",
                picos=_complete_picos(),
                actor="medical_manager_test",
                idempotency_key="commit-ra-search-link-picos",
            ),
        )
        attached = self.service.attach_search_snapshot(
            project_id,
            _search_snapshot(project_id),
            MedicalWritingCompetitorSearchExecuteRequest(
                search_plan_id=created.search_plan.plan_id,
                actor="medical_manager_test",
                idempotency_key="attach-ra-search-snapshot",
            ),
        )
        self.assertEqual(designed.revision + 1, attached.revision)
        self.assertTrue(attached.picos_complete)
        self.assertEqual("corpus_not_ready", attached.status)
        self.assertEqual("triage_pending", attached.search_plan.status)
        self.assertEqual("wref_search_ra_001", attached.search_plan.latest_snapshot_id)
        self.assertEqual(2, attached.search_plan.returned_count)
        self.assertEqual(2, attached.search_plan.public_document_count)

        replayed = self.service.attach_search_snapshot(
            project_id,
            _search_snapshot(project_id),
            MedicalWritingCompetitorSearchExecuteRequest(
                search_plan_id=created.search_plan.plan_id,
                actor="medical_manager_test",
                idempotency_key="attach-ra-search-snapshot",
            ),
        )
        self.assertEqual(attached.revision, replayed.revision)
        persisted = MedicalWritingAuthoringJourneyService(self.service.db_path).get(project_id)
        self.assertEqual(attached.search_plan.model_dump(), persisted.search_plan.model_dump())

    def test_framing_triage_change_preserves_matching_registry_snapshot(self):
        project_id = "proj_synthetic_ra_preserve_registry_snapshot"
        created = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_complete_framing(),
                actor="medical_manager_test",
                idempotency_key="create-ra-preserve-registry-snapshot",
            ),
        )
        attached = self.service.attach_search_snapshot(
            project_id,
            _search_snapshot(project_id),
            MedicalWritingCompetitorSearchExecuteRequest(
                search_plan_id=created.search_plan.plan_id,
                actor="medical_manager_test",
                idempotency_key="attach-ra-preserve-registry-snapshot",
            ),
        )
        changed_profile = attached.framing.product_profile.model_copy(
            update={"administration_routes": ["口服"]},
            deep=True,
        )
        changed_framing = attached.framing.model_copy(
            update={"product_profile": changed_profile},
            deep=True,
        )
        preview = self.service.impact_preview(
            project_id,
            MedicalWritingJourneyImpactPreviewRequest(
                expected_revision=attached.revision,
                stage="framing",
                framing=changed_framing,
            ),
        )
        committed = self.service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=attached.revision,
                stage="framing",
                framing=changed_framing,
                impact_preview_id=preview.preview_id,
                actor="medical_manager_test",
                idempotency_key="commit-ra-preserve-registry-snapshot",
            ),
        )

        self.assertNotEqual(attached.search_plan.plan_id, committed.search_plan.plan_id)
        self.assertEqual(
            attached.search_plan.registry_filter,
            committed.search_plan.registry_filter,
        )
        self.assertEqual(
            attached.search_plan.latest_snapshot_id,
            committed.search_plan.latest_snapshot_id,
        )
        self.assertEqual(attached.search_plan.returned_count, committed.search_plan.returned_count)
        self.assertEqual("triage_pending", committed.search_plan.status)
        self.assertIn(
            "口服",
            [item.value for item in committed.search_plan.triage_criteria],
        )

    def test_upstream_change_requires_matching_impact_preview_and_invalidates_downstream(self):
        project_id = "proj_synthetic_ra_change"
        framed = self.service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_complete_framing(),
                actor="medical_manager_test",
                idempotency_key="create-ra-change",
            ),
        )
        designed = self.service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=framed.revision,
                stage="picos",
                picos=_complete_picos(),
                actor="medical_manager_test",
                idempotency_key="commit-ra-change-picos",
            ),
        )
        designed = self.service.attach_search_snapshot(
            project_id,
            _search_snapshot(project_id),
            MedicalWritingCompetitorSearchExecuteRequest(
                search_plan_id=designed.search_plan.plan_id,
                actor="medical_manager_test",
                idempotency_key="attach-ra-change-snapshot",
            ),
        )
        changed_framing = _complete_framing(
            indication="银屑病关节炎",
            clinicaltrials_condition_term="Psoriatic Arthritis",
        )
        preview = self.service.impact_preview(
            project_id,
            MedicalWritingJourneyImpactPreviewRequest(
                expected_revision=designed.revision,
                stage="framing",
                framing=changed_framing,
            ),
        )
        self.assertTrue(preview.requires_confirmation)
        self.assertIn("framing.indication", preview.changed_fields)
        self.assertIn("competitor_search_plan", preview.affected_dependents)

        with self.assertRaisesRegex(
            MedicalWritingAuthoringJourneyConflictError, "impact preview"
        ):
            self.service.commit_stage(
                project_id,
                MedicalWritingAuthoringJourneyCommitRequest(
                    expected_revision=designed.revision,
                    stage="framing",
                    framing=changed_framing,
                    actor="medical_manager_test",
                    idempotency_key="commit-ra-indication-without-preview",
                ),
            )

        changed = self.service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=designed.revision,
                stage="framing",
                framing=changed_framing,
                impact_preview_id=preview.preview_id,
                actor="medical_manager_test",
                idempotency_key="commit-ra-indication-with-preview",
            ),
        )
        self.assertEqual("银屑病关节炎", changed.framing.indication)
        self.assertFalse(changed.picos_complete)
        self.assertIn("corpus_coverage", changed.invalidated_dependents)
        self.assertFalse(changed.corpus_gate.access_permitted)
        self.assertEqual("", changed.search_plan.latest_snapshot_id)
        self.assertEqual("planned", changed.search_plan.status)
        self.assertEqual("", changed.discovery_basket_projection.confirmation_id)


class MedicalWritingAuthoringJourneyApiTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "authoring_journey.sqlite3"
        )
        self.patch = patch(
            "services.api.app.main.medical_writing_authoring_journey_service",
            self.service,
        )
        self.patch.start()
        self.client = TestClient(app_main.app)

    def tearDown(self):
        self.patch.stop()
        self.tmpdir.cleanup()

    def test_api_exposes_locked_product_decisions_and_resumable_journey(self):
        config = self.client.get("/api/medical-writing/authoring-product-configuration")
        self.assertEqual(200, config.status_code, config.text)
        self.assertEqual("draft_translation", config.json()["decisions"]["scales"])
        self.assertEqual("monitoring", config.json()["decisions"]["second_port"])

        project_id = "proj_mgk10_crswnp"
        missing = self.client.get(
            f"/api/projects/{project_id}/medical-writing/authoring-journey"
        )
        self.assertEqual(404, missing.status_code, missing.text)
        optional_missing = self.client.get(
            f"/api/projects/{project_id}/medical-writing/authoring-journey"
            "?allow_missing=true"
        )
        self.assertEqual(200, optional_missing.status_code, optional_missing.text)
        self.assertFalse(optional_missing.json()["available"])

        created = self.client.post(
            f"/api/projects/{project_id}/medical-writing/authoring-journey",
            json={
                "framing": _complete_framing().model_dump(mode="json"),
                "actor": "medical_manager_test",
                "idempotency_key": "api-create-authoring-journey",
            },
        )
        self.assertEqual(200, created.status_code, created.text)
        self.assertEqual("stage1_complete", created.json()["status"])

        resumed = self.client.get(
            f"/api/projects/{project_id}/medical-writing/authoring-journey"
        )
        self.assertEqual(200, resumed.status_code, resumed.text)
        self.assertTrue(resumed.json()["available"])
        self.assertEqual(created.json()["journey_id"], resumed.json()["journey_id"])

        stale = self.client.post(
            f"/api/projects/{project_id}/medical-writing/authoring-journey/impact-preview",
            json={
                "expected_revision": 99,
                "stage": "picos",
                "picos": _complete_picos().model_dump(mode="json"),
            },
        )
        self.assertEqual(409, stale.status_code, stale.text)

        snapshot = _search_snapshot(project_id)
        with patch.object(
            app_main.writing_reference_discovery_service,
            "create_search_snapshot",
            return_value=snapshot,
        ):
            attached = self.client.post(
                f"/api/projects/{project_id}/medical-writing/authoring-journey/competitor-search",
                json={
                    "search_plan_id": created.json()["search_plan"]["plan_id"],
                    "actor": "medical_manager_test",
                    "idempotency_key": "api-attach-authoring-search",
                },
            )
        self.assertEqual(200, attached.status_code, attached.text)
        self.assertEqual(
            snapshot.snapshot_id,
            attached.json()["search_plan"]["latest_snapshot_id"],
        )
        self.assertEqual(2, attached.json()["search_plan"]["public_document_count"])

    def test_api_saves_incomplete_picos_draft_without_advancing_stage(self):
        project_id = "proj_mgk10_crswnp"
        created = self.client.post(
            f"/api/projects/{project_id}/medical-writing/authoring-journey",
            json={
                "framing": _complete_framing().model_dump(mode="json"),
                "actor": "medical_manager_test",
                "idempotency_key": "api-create-picos-draft-journey",
            },
        )
        self.assertEqual(200, created.status_code, created.text)
        partial_picos = MedicalWritingPicosDefinition(
            design_archetype="single_arm_early_phase",
            population_summary="活动性类风湿关节炎成人试验参与者。",
        )
        saved = self.client.post(
            f"/api/projects/{project_id}/medical-writing/authoring-journey/stages/picos/draft",
            json={
                "expected_revision": created.json()["revision"],
                "stage": "picos",
                "picos": partial_picos.model_dump(mode="json"),
                "actor": "medical_manager_test",
                "idempotency_key": "api-save-incomplete-picos-draft",
            },
        )
        self.assertEqual(200, saved.status_code, saved.text)
        self.assertEqual("stage1_complete", saved.json()["status"])
        self.assertFalse(saved.json()["picos_complete"])
        self.assertEqual(
            "single_arm_early_phase",
            saved.json()["picos_draft"]["picos"]["design_archetype"],
        )
        self.assertIn(
            "inclusion_modules",
            saved.json()["picos_draft"]["missing_required_fields"],
        )

    def test_api_projects_deferred_corpus_confirmation_after_picos_commit(self):
        project_id = "proj_mgk10_crswnp"
        created = self.client.post(
            f"/api/projects/{project_id}/medical-writing/authoring-journey",
            json={
                "framing": _complete_framing().model_dump(mode="json"),
                "actor": "medical_manager_test",
                "idempotency_key": "api-create-deferred-corpus-journey",
            },
        )
        self.assertEqual(200, created.status_code, created.text)
        picos = _complete_picos()
        preview = self.client.post(
            f"/api/projects/{project_id}/medical-writing/authoring-journey/impact-preview",
            json={
                "expected_revision": created.json()["revision"],
                "stage": "picos",
                "picos": picos.model_dump(mode="json"),
            },
        )
        self.assertEqual(200, preview.status_code, preview.text)
        confirmation = SimpleNamespace(
            confirmation_id="ct_conf_deferred",
            projection_status="deferred_until_picos",
        )
        with patch.object(
            app_main.medical_writing_research_pipeline_service,
            "get_state",
            return_value=SimpleNamespace(stage="awaiting_translation_scope", triage_run_id="ct_run_deferred"),
        ), patch.object(
            app_main.competitor_triage_service.repository,
            "triage_confirmation_for_run",
            return_value=confirmation,
        ) as find_confirmation, patch.object(
            app_main.competitor_triage_service,
            "retry_projection",
            return_value=SimpleNamespace(),
        ) as retry_projection:
            committed = self.client.post(
                f"/api/projects/{project_id}/medical-writing/authoring-journey/stages/picos/commit",
                json={
                    "expected_revision": created.json()["revision"],
                    "stage": "picos",
                    "picos": picos.model_dump(mode="json"),
                    "impact_preview_id": preview.json()["preview_id"],
                    "actor": "medical_manager_test",
                    "idempotency_key": "api-commit-deferred-corpus-picos",
                },
            )
        self.assertEqual(200, committed.status_code, committed.text)
        self.assertTrue(committed.json()["picos_complete"])
        find_confirmation.assert_called_once_with(project_id, "ct_run_deferred")
        retry_projection.assert_called_once()
        request = retry_projection.call_args.args[2]
        self.assertEqual("medical_manager_test", request.actor)
        self.assertIn("ct_conf_deferred", request.idempotency_key)

    def test_api_blocks_authoring_write_while_pipeline_owns_frozen_inputs(self):
        project_id = "proj_mgk10_crswnp"
        created = self.client.post(
            f"/api/projects/{project_id}/medical-writing/authoring-journey",
            json={
                "framing": _complete_framing().model_dump(mode="json"),
                "actor": "medical_manager_test",
                "idempotency_key": "api-create-frozen-pipeline-journey",
            },
        )
        self.assertEqual(200, created.status_code, created.text)
        partial_picos = MedicalWritingPicosDefinition(
            design_archetype="single_arm_early_phase",
            population_summary="活动性类风湿关节炎成人试验参与者。",
        )
        with patch.object(
            app_main.medical_writing_research_pipeline_service,
            "get_state",
            return_value=SimpleNamespace(stage="triaging"),
        ):
            blocked = self.client.post(
                f"/api/projects/{project_id}/medical-writing/authoring-journey/stages/picos/draft",
                json={
                    "expected_revision": created.json()["revision"],
                    "stage": "picos",
                    "picos": partial_picos.model_dump(mode="json"),
                    "actor": "medical_manager_test",
                    "idempotency_key": "api-save-draft-during-triage",
                },
            )
        self.assertEqual(409, blocked.status_code, blocked.text)
        self.assertIn("不能修改研究框架", blocked.text)


if __name__ == "__main__":
    unittest.main()


class CarryForwardCorpusGateTests(unittest.TestCase):
    """Round-5 P0 regression: rebuilding the gate on a fresh project (override
    inactive) must not pass override=None to pydantic — that crashed every
    first-step commit with a validation error surfaced to the user."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "authoring_journey.sqlite3"
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_inactive_override_is_carried_as_object_not_none(self):
        from packages.contracts.workbench_contracts.models import (
            MedicalWritingCorpusGate,
            MedicalWritingCorpusGateOverride,
        )
        state = SimpleNamespace(
            corpus_gate=MedicalWritingCorpusGate(
                override=MedicalWritingCorpusGateOverride(active=False))
        )
        gate = self.service._carry_forward_corpus_gate(state)
        self.assertIsInstance(gate.override, MedicalWritingCorpusGateOverride)
        self.assertFalse(gate.override.active)
        self.assertFalse(gate.access_permitted)

    def test_active_override_keeps_access(self):
        from packages.contracts.workbench_contracts.models import (
            MedicalWritingCorpusGate,
            MedicalWritingCorpusGateOverride,
        )
        state = SimpleNamespace(
            corpus_gate=MedicalWritingCorpusGate(
                override=MedicalWritingCorpusGateOverride(active=True))
        )
        gate = self.service._carry_forward_corpus_gate(state)
        self.assertTrue(gate.override.active)
        self.assertTrue(gate.access_permitted)

    def test_missing_gate_defaults_to_inactive_override(self):
        from packages.contracts.workbench_contracts.models import (
            MedicalWritingCorpusGateOverride,
        )
        gate = self.service._carry_forward_corpus_gate(SimpleNamespace(corpus_gate=None))
        self.assertIsInstance(gate.override, MedicalWritingCorpusGateOverride)
        self.assertFalse(gate.access_permitted)
