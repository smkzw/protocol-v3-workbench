"""Capture representative v1 serialization and material hashes.

Task3R.2 pin: run BEFORE the v2 chapter-contract schema extension and again
after implementation; the two outputs must be byte-identical for every entry.

Usage: capture_v1_fixtures.py <output-json-path>
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import sys

from packages.contracts.workbench_contracts.protocol_v3 import (
    ChapterContract,
    ChapterLockSnapshot,
    NodeExecutionContract,
    SemanticBlock,
    SemanticDocumentRevision,
    SubstantiveContentContract,
)

NOW = datetime(2026, 9, 6, 2, 0, tzinfo=timezone.utc)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def _sha(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _chapter_contract() -> ChapterContract:
    return ChapterContract(
        chapter_contract_id="contract:objectives:v1",
        semantic_node_id="node:study-objectives",
        contract_version="1.0.0",
        template_id="template:tp-ma-07",
        template_sha256=SHA_A,
        chapter_skill_id="skill:chapter:objectives",
        chapter_skill_version="1.0.0",
        required_fact_paths=("picos.outcome.primary",),
        required_claim_types=("primary_objective",),
        required_source_roles=("competitor_full_protocol",),
        required_structural_objects=("paragraph",),
        positive_qc_rules=("主要目的必须与主要终点形成一一映射",),
        word_block_schema="paragraph-list-v1",
        dependency_ids=("contract:background:v1",),
    )


def _substantive_content_contract() -> SubstantiveContentContract:
    return SubstantiveContentContract(
        substantive_content_contract_id="content:objectives:v1",
        chapter_contract_id="contract:objectives:v1",
        required_claim_types=("primary_objective",),
        required_fact_paths=("picos.outcome.primary",),
        minimum_source_roles=("competitor_full_protocol",),
        required_admission_claim_types=("study_objective",),
        project_specific_elements=("UC301 主要终点定义",),
        required_structural_objects=("paragraph",),
        required_object_cells=("soa:visit:week12",),
        skeleton_risk_rules=("只有标题或通用模板句即失败",),
    )


def _semantic_block() -> SemanticBlock:
    return SemanticBlock(
        semantic_block_id="block:introduction:001",
        semantic_node_id="node:introduction",
        chapter_contract_id="contract:introduction:v1",
        substantive_content_contract_id="content:introduction:v1",
        block_kind="paragraph",
        content="本研究拟评价研究药物 A 用于目标人群的有效性与安全性。",
        fact_paths=("picos.population.indication",),
        claim_evidence_link_ids=("link:introduction:001",),
        medical_admission_unit_ids=("admission:introduction:001",),
        content_sha256=SHA_B,
    )


def _semantic_document_revision() -> SemanticDocumentRevision:
    return SemanticDocumentRevision(
        semantic_document_revision_id="document:uc301:001",
        project_id="project:uc301",
        revision=1,
        study_definition_id="study:def:uc301",
        study_definition_sha256=SHA_A,
        applicability_snapshot_id="applicability:uc301:v1",
        applicability_snapshot_sha256=SHA_B,
        semantic_blocks=(_semantic_block(),),
        chapter_contract_hashes=(_sha("contract:objectives:v1"),),
        updated_at=NOW,
    )


def _chapter_lock_snapshot() -> ChapterLockSnapshot:
    return ChapterLockSnapshot(
        chapter_lock_snapshot_id="lock:objectives:001",
        semantic_node_id="node:study-objectives",
        semantic_document_revision_id="document:uc301:001",
        semantic_document_sha256=SHA_C,
        upstream_artifact_hashes=(SHA_A, SHA_B),
        accepted_semantic_block_hashes=(_sha("block:introduction:001"),),
        locked_by_actor_id="user:medical-writer",
        locked_at=NOW,
    )


def _node_execution_contract() -> NodeExecutionContract:
    return NodeExecutionContract(
        node_execution_contract_id="execution:contract:001",
        skill_definition_id="skill:chapter:objectives",
        role="chapter_writer",
        harness="zcode",
        provider="zcode",
        model="GLM-5.3-Flash",
        reasoning_effort="high",
        same_session_recovery=True,
        timeout_seconds=600,
        fallback_policy_id="policy:fallback:001",
        prompt_sha256=SHA_D,
        input_schema_ref="schemas/chapter-input-v1.json",
        output_schema_ref="schemas/chapter-output-v1.json",
        allowed_tools=("read", "grep"),
        allowed_paths=("runs/",),
        permission_policy_id="policy:permission:001",
        input_artifact_hashes=(SHA_A,),
        sensitivity_tier="confidential",
        allowed_providers=("zcode",),
        allowed_regions=("cn-north-1",),
        redaction_policy_id="policy:redaction:001",
        retention_policy_id="policy:retention:001",
        logical_call_id="call:chapter:001",
        idempotency_key="call:chapter:001@input-a",
    )


def _capture(model) -> dict:
    compact = (
        model.compact_dependencies().model_dump(mode="json")
        if isinstance(model, (SemanticDocumentRevision, ChapterLockSnapshot, NodeExecutionContract))
        else None
    )
    entry = {
        "schema_version": model.schema_version,
        "model_dump_json": model.model_dump_json(),
        "model_dump_json_compact": (
            model.compact_dependencies().model_dump_json()
            if isinstance(model, (SemanticDocumentRevision, ChapterLockSnapshot, NodeExecutionContract))
            else None
        ),
        "material_sha256": model.material_sha256(),
        "material_sha256_compact": (
            model.compact_dependencies().material_sha256()
            if isinstance(model, (SemanticDocumentRevision, ChapterLockSnapshot, NodeExecutionContract))
            else None
        ),
        "model_dump_json_schema": model.model_json_schema(),
    }
    assert compact is not None or not isinstance(
        model, (SemanticDocumentRevision, ChapterLockSnapshot, NodeExecutionContract)
    )
    return entry


def main() -> int:
    output_path = sys.argv[1]
    fixtures = {
        "captured_with": "mw_protocol_v3_3r2_contracts_20260906 worker_01",
        "models": {
            "ChapterContract": _capture(_chapter_contract()),
            "SubstantiveContentContract": _capture(_substantive_content_contract()),
            "SemanticDocumentRevision_legacy": _capture(_semantic_document_revision()),
            "ChapterLockSnapshot_legacy": _capture(_chapter_lock_snapshot()),
            "NodeExecutionContract_legacy": _capture(_node_execution_contract()),
        },
    }
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(fixtures, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"captured {len(fixtures['models'])} v1 fixtures -> {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
