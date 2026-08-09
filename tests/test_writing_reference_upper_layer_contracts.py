from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from packages.contracts.workbench_contracts import (
    WritingReferenceExtractionResult,
    WritingReferenceOcrPageEvidence,
    WritingReferenceUpperLayerCapabilities,
    WritingReferenceUpperLayerEscalation,
    WritingReferenceUpperLayerRetryRequest,
    WritingReferenceUpperLayerStageCapability,
    WritingReferenceUpperLayerStageRun,
)
from packages.contracts.workbench_contracts.models import (
    DocumentStructurePlan,
    WritingReferenceTranslationBatchCreateRequest,
    WritingReferenceTranslationBatchItem,
)


NOW = datetime(2026, 7, 25, tzinfo=timezone.utc)


def _legacy_extraction_payload() -> dict:
    return {
        "artifact_id": "artifact_001",
        "project_id": "project_001",
        "extraction_revision": "extract_r1",
        "parser_name": "pymupdf",
        "parser_version": "1",
        "page_count": 1,
        "status": "pending_medical_structure_review",
        "ocr_recovery_pages": [
            {
                "physical_page": 1,
                "dpi": 200,
                "model": "GLM-OCR-bf16",
                "ocr_profile_digest": "profile-hash",
                "source_text_sha256": "a" * 64,
                "channel": "ocr",
                "selection_reason": "zero_text_page",
                "span_id": "span_001",
                "native_channel": [
                    {
                        "span_id": "native_span_001",
                        "source_locator": "protocol:p1:block0",
                        "source_text_sha256": "b" * 64,
                        "channel": "native_text",
                    }
                ],
            }
        ],
    }


def test_legacy_extraction_without_png_fields_parses_as_metadata_only() -> None:
    extraction = WritingReferenceExtractionResult.model_validate(
        _legacy_extraction_payload()
    )

    evidence = extraction.ocr_recovery_pages[0]
    assert isinstance(evidence, WritingReferenceOcrPageEvidence)
    assert evidence.ocr_result_status == "legacy_metadata_only"
    assert evidence.image_sha256 == ""
    assert evidence.image_size_bytes == 0
    assert evidence.storage_relpath == ""
    assert evidence.ocr_text_sha256 == "a" * 64
    assert evidence.get("span_id") == "span_001"
    assert evidence.native_channel[0]["span_id"] == "native_span_001"


def test_new_ocr_page_evidence_carries_png_text_and_selection_lineage() -> None:
    evidence = WritingReferenceOcrPageEvidence(
        physical_page=143,
        dpi=200,
        image_sha256="b" * 64,
        image_size_bytes=123456,
        image_width_px=1654,
        image_height_px=2339,
        storage_relpath="documents/ocr/extract_r2/page_0143.png",
        model="GLM-OCR-bf16",
        ocr_profile_digest="c" * 64,
        ocr_text_sha256="d" * 64,
        ocr_character_count=418,
        channel="ocr_reconciled",
        selection_reason="spatial_anomaly",
        ocr_result_status="text_recovered",
        span_id="wref_span_ocr_001",
    )

    assert evidence.image_media_type == "image/png"
    assert evidence.source_text_sha256 == "d" * 64
    assert evidence.model_dump(mode="json")["storage_relpath"].endswith(
        "page_0143.png"
    )


def test_terminal_stage_run_records_exact_server_selected_route() -> None:
    run = WritingReferenceUpperLayerStageRun(
        stage_run_id="stage_run_001",
        project_id="project_001",
        owner_type="translation_batch_item",
        owner_id="item_001",
        batch_id="batch_001",
        item_id="item_001",
        artifact_id="artifact_001",
        extraction_revision="extract_r2",
        plan_id="plan_001",
        stage="document_planning",
        provider="deepseek",
        transport="openai_compatible",
        requested_model="deepseek-v4-flash",
        response_model="deepseek-v4-flash",
        deployment_profile="medical-writing-upper-layer-v1",
        prompt_version="document_planning_v1",
        input_hash="e" * 64,
        output_hash="f" * 64,
        status="succeeded",
        provider_call_count=1,
        created_at=NOW,
        completed_at=NOW,
    )

    assert run.stage == "document_planning"
    assert run.requested_model == run.response_model
    assert run.retry_generation == 0
    assert run.retry_parent_stage_run_id == ""
    assert "body_translation" not in str(run.model_dump(mode="json"))


def test_document_planning_retry_lineage_is_additive_and_coherent() -> None:
    run = WritingReferenceUpperLayerStageRun(
        stage_run_id="stage_run_retry_002",
        project_id="project_001",
        owner_type="translation_batch_item",
        owner_id="item_001",
        batch_id="batch_001",
        item_id="item_001",
        artifact_id="artifact_001",
        extraction_revision="extract_r2",
        stage="document_planning",
        provider="deepseek",
        transport="openai_compatible",
        requested_model="deepseek-v4-flash",
        response_model="deepseek-v4-flash",
        deployment_profile="medical-writing-upper-layer-v1",
        prompt_version="document_planning_v1",
        input_hash="e" * 64,
        output_hash="f" * 64,
        status="succeeded",
        provider_call_count=1,
        retry_generation=2,
        retry_parent_stage_run_id="stage_run_retry_001",
        created_at=NOW,
        completed_at=NOW,
    )

    assert run.retry_generation == 2
    assert run.retry_parent_stage_run_id == "stage_run_retry_001"
    with pytest.raises(ValidationError, match="generation and retry parent"):
        WritingReferenceUpperLayerStageRun.model_validate(
            {
                **run.model_dump(mode="json"),
                "retry_parent_stage_run_id": "",
            }
        )
    with pytest.raises(ValidationError, match="document-planning only"):
        WritingReferenceUpperLayerStageRun.model_validate(
            {
                **run.model_dump(mode="json"),
                "stage": "post_hy_mt2_integration_qc",
            }
        )


def test_contract_supersession_lineage_is_additive_distinct_and_legacy_safe() -> None:
    run = WritingReferenceUpperLayerStageRun(
        stage_run_id="stage_run_supersession_v3",
        project_id="project_001",
        owner_type="translation_batch_item",
        owner_id="item_001",
        batch_id="batch_001",
        item_id="item_001",
        artifact_id="artifact_001",
        extraction_revision="extract_r2",
        stage="document_planning",
        provider="deepseek",
        transport="openai_compatible",
        requested_model="deepseek-v4-flash",
        response_model="deepseek-v4-flash",
        deployment_profile="medical-writing-upper-layer-v1",
        prompt_version="flash_toc_planning_v0_3_server_canonical_ids",
        input_hash="e" * 64,
        output_hash="f" * 64,
        status="succeeded",
        provider_call_count=1,
        contract_supersession_generation=3,
        contract_supersession_transition_version=(
            "planner_contract_v2_to_v3_supersession_v1"
        ),
        contract_supersession_source_stage_run_id="stage_run_v2_failed",
        contract_supersession_source_execution_fingerprint="a" * 64,
        contract_supersession_source_prompt_version=(
            "flash_toc_planning_v0_2_segment_ranges"
        ),
        contract_supersession_target_prompt_version=(
            "flash_toc_planning_v0_3_server_canonical_ids"
        ),
        created_at=NOW,
        completed_at=NOW,
    )

    assert run.retry_generation == 0
    assert run.retry_parent_stage_run_id == ""
    assert run.contract_supersession_generation == 3
    with pytest.raises(
        ValidationError,
        match="ordinary retry and contract supersession",
    ):
        WritingReferenceUpperLayerStageRun.model_validate(
            {
                **run.model_dump(mode="json"),
                "retry_generation": 3,
                "retry_parent_stage_run_id": "stage_run_v2_failed",
            }
        )

    legacy_payload = run.model_dump(mode="json")
    for key in tuple(legacy_payload):
        if key.startswith("contract_supersession_"):
            legacy_payload.pop(key)
    legacy_payload.update(
        {
            "stage_run_id": "stage_run_legacy",
            "prompt_version": "document_planning_v1",
        }
    )
    legacy = WritingReferenceUpperLayerStageRun.model_validate(
        legacy_payload
    )
    assert legacy.contract_supersession_generation == 0
    assert legacy.contract_supersession_source_stage_run_id == ""


def test_legacy_document_plan_defaults_contract_migration_lineage_to_empty() -> None:
    plan = DocumentStructurePlan.model_validate(
        {
            "plan_id": "plan_legacy",
            "project_id": "project_001",
            "artifact_id": "artifact_001",
            "extraction_revision": "extract_r2",
            "document_sha256": "a" * 64,
            "document_role": "protocol",
            "planner_model": "deepseek-v4-flash",
            "planner_prompt_version": (
                "flash_toc_planning_v0_2_segment_ranges"
            ),
            "planner_input_hash": "b" * 64,
            "planner_output_hash": "c" * 64,
            "planner_contract_fingerprint": "d" * 64,
            "created_at": NOW,
        }
    )

    assert plan.contract_migration_namespace == ""
    assert plan.contract_transition_version == ""
    assert plan.contract_source_plan_id == ""
    assert plan.contract_source_fingerprint == ""
    assert plan.contract_target_fingerprint == ""
    assert plan.contract_source_prompt_version == ""
    assert plan.contract_target_prompt_version == ""
    assert plan.contract_source_payload_sha256 == ""
    assert plan.contract_target_payload_sha256 == ""


def test_pro_stage_run_requires_automatic_parent_lineage() -> None:
    with pytest.raises(ValidationError, match="parent and escalation lineage"):
        WritingReferenceUpperLayerStageRun(
            stage_run_id="stage_run_pro_001",
            project_id="project_001",
            owner_type="direct_translation",
            owner_id="translation_001",
            artifact_id="artifact_001",
            extraction_revision="extract_r2",
            stage="post_hy_mt2_integration_qc",
            provider="deepseek",
            transport="openai_compatible",
            requested_model="deepseek-v4-pro",
            response_model="deepseek-v4-pro",
            deployment_profile="medical-writing-upper-layer-v1",
            prompt_version="integration_qc_v1",
            input_hash="e" * 64,
            output_hash="f" * 64,
            status="succeeded",
            provider_call_count=1,
            created_at=NOW,
            completed_at=NOW,
        )


def test_escalation_lineage_is_server_created_flash_to_pro_only() -> None:
    escalation = WritingReferenceUpperLayerEscalation(
        escalation_id="escalation_001",
        project_id="project_001",
        stage="post_hy_mt2_integration_qc",
        source_stage_run_id="stage_run_flash_001",
        target_stage_run_id="stage_run_pro_001",
        trigger_status="completed_degraded",
        trigger_code="flash_qc_degraded_with_intact_target_map",
        lineage_hash="1" * 64,
        status="completed",
        durable_job_id="job_001",
        created_at=NOW,
        updated_at=NOW,
        completed_at=NOW,
    )

    assert escalation.created_by == "server_orchestrator"
    assert escalation.source_model == "deepseek-v4-flash"
    assert escalation.target_model == "deepseek-v4-pro"


def test_stage_capabilities_can_report_corpus_support_not_implemented() -> None:
    capabilities = WritingReferenceUpperLayerCapabilities(
        upper_layer_stages={
            "document_planning": WritingReferenceUpperLayerStageCapability(
                stage="document_planning",
                status="implemented",
                default_model="deepseek-v4-flash",
                escalation_model="deepseek-v4-pro",
                automatic_escalation_supported=True,
            ),
            "corpus_selection_support": WritingReferenceUpperLayerStageCapability(
                stage="corpus_selection_support",
                status="not_implemented",
                reason="no_product_stage_owner",
            ),
        }
    )

    corpus = capabilities.upper_layer_stages["corpus_selection_support"]
    assert corpus.status == "not_implemented"
    assert corpus.default_model is None
    assert corpus.escalation_model is None


@pytest.mark.parametrize("extra_field", ["model", "provider", "base_url"])
def test_upper_layer_retry_request_rejects_client_route_fields(
    extra_field: str,
) -> None:
    payload = {
        "actor": "medical_manager",
        "reason": "retry after operator resolved the source issue",
        "idempotency_key": "retry-key-001",
        extra_field: "client-controlled-value",
    }

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        WritingReferenceUpperLayerRetryRequest.model_validate(payload)


@pytest.mark.parametrize("extra_field", ["model", "provider"])
def test_existing_batch_create_request_also_rejects_route_identity(
    extra_field: str,
) -> None:
    payload = {
        "snapshot_id": "snapshot_001",
        "glossary_version": "cms_regulatory_zh_v1",
        "preparation_batch_id": "prep_batch_001",
        "actor": "medical_manager",
        "idempotency_key": "batch-key-001",
        extra_field: "client-controlled-value",
    }

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        WritingReferenceTranslationBatchCreateRequest.model_validate(payload)


def test_batch_upper_layer_summary_rejects_body_translation_model() -> None:
    payload = {
        "item_id": "item_001",
        "batch_id": "batch_001",
        "project_id": "project_001",
        "snapshot_id": "snapshot_001",
        "glossary_version": "cms_regulatory_zh_v1",
        "span_id": "span_001",
        "artifact_id": "artifact_001",
        "nct_id": "NCT02819635",
        "ich_m11_anchor": "eligibility",
        "source_text_sha256": "a" * 64,
        "source_span_revision": "span_r1",
        "artifact_sha256": "b" * 64,
        "artifact_state_revision": 1,
        "validation_id": "validation_001",
        "validation_revision": 1,
        "validation_status": "confirmed",
        "extraction_revision": "extract_r2",
        "structure_review_id": "review_001",
        "structure_review_revision": 1,
        "origin": "new",
        "plan_model": "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX",
        "created_at": NOW,
        "updated_at": NOW,
    }

    with pytest.raises(
        ValidationError,
        match="body translation model cannot be used for upper-layer planning",
    ):
        WritingReferenceTranslationBatchItem.model_validate(payload)


def test_legacy_batch_item_defaults_retry_lineage_to_generation_zero() -> None:
    payload = {
        "item_id": "item_001",
        "batch_id": "batch_001",
        "project_id": "project_001",
        "snapshot_id": "snapshot_001",
        "glossary_version": "cms_regulatory_zh_v1",
        "span_id": "span_001",
        "artifact_id": "artifact_001",
        "nct_id": "NCT02819635",
        "ich_m11_anchor": "eligibility",
        "source_text_sha256": "a" * 64,
        "source_span_revision": "span_r1",
        "artifact_sha256": "b" * 64,
        "artifact_state_revision": 1,
        "validation_id": "validation_001",
        "validation_revision": 1,
        "validation_status": "confirmed",
        "extraction_revision": "extract_r2",
        "structure_review_id": "review_001",
        "structure_review_revision": 1,
        "origin": "new",
        "created_at": NOW,
        "updated_at": NOW,
    }
    item = WritingReferenceTranslationBatchItem.model_validate(payload)

    assert item.document_plan_retry_generation == 0
    assert item.document_plan_retry_parent_stage_run_id == ""
    assert item.document_plan_retry_source_item_id == ""
    assert item.document_plan_contract_transition_kind == ""
    assert item.document_plan_contract_transition_version == ""
    assert item.document_plan_contract_generation == 0
    assert item.document_plan_contract_source_item_id == ""
    assert item.document_plan_contract_source_plan_id == ""
    assert item.document_plan_contract_target_plan_id == ""
    assert item.document_plan_contract_source_stage_run_id == ""
    assert item.document_plan_contract_source_execution_fingerprint == ""
    assert item.document_plan_contract_source_prompt_version == ""
    assert item.document_plan_contract_target_prompt_version == ""
    assert item.document_plan_contract_source_fingerprint == ""
    assert item.document_plan_contract_target_fingerprint == ""
    with pytest.raises(ValidationError, match="must coexist"):
        WritingReferenceTranslationBatchItem.model_validate(
            {
                **payload,
                "document_plan_retry_generation": 2,
                "document_plan_retry_parent_stage_run_id": (
                    "stage_run_retry_001"
                ),
            }
        )
