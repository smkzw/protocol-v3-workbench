"""Deterministic v2 route/service mutator inventory + AST drift check (Task 1.10).

Worker 03 inventory: every *legacy mutation path* of the v2 API surface is
enumerated with an operation id, project binding (route layer), module/class/
function locator (service layer), and a closed classification.  The surface is
exactly ``services/api/app/main.py`` route handlers plus the seven named v2
modules declared by the accepted mapping spec
``config/medical_writing/protocol_v3/v2_v3_mapping.json``:

* ``medical_writing_authoring_journey.py``   (journey_stage_draft family)
* ``sqlite_runtime_store.py``                (working copies, approvals, ...)
* ``medical_writing_company_corpus.py``      (read-only corpus denominator)
* ``writing_reference_repository.py``        (corpus/evidence + decisions)
* ``medical_writing_greenfield.py``          (protocol_document family)
* ``medical_writing_artifact_lifecycle.py``  (artifact_lineage family)
* ``source_intake.py``                       (medical-writing source intake)
* ``packages/contracts/workbench_contracts/models.py`` (pure model transforms)

Classification vocabulary is closed::

    legacy_write  - mutates legacy v2 fact data in one of the seven declared
                    families; the mutation guard blocks it outside
                    LEGACY_ACTIVE.
    read_only     - discovered candidate that performs no legacy fact write
                    (pure compute/validation/replay/preview), documented per
                    entry.
    excluded      - performs writes, but only outside the seven families:
                    store-level schema/backup/restore infrastructure,
                    constructor wiring, idempotency/audit bookkeeping, or the
                    eligibility / monitoring / AI-gateway / safety-PV / TFL /
                    project-lifecycle / source-registry domains (not declared
                    migration source types in v2_v3_mapping.json).

**Discovery is deterministic AST** (no imports of the target modules, no
runtime singletons): route handlers are parsed from ``main.py``; service
candidates are functions/methods whose name starts with a write verb, whose
body passes write SQL (DML/DDL) to ``execute/executemany/executescript``, whose body
performs file writes, or which (transitively, within the same module) call a
discovered mutator.  The drift check then fails on *any* discovered mutator
that has no classification entry, any stale entry whose operation no longer
exists, any entry whose method/path or module/function no longer matches, and
any read-only-classified or GET route that calls a legacy-write service
operation.  This is what makes "every discovered mutator must be classified
or the drift check fails" enforceable: adding a new POST route or a new write
helper without an inventory entry breaks the check.

Scope note: routers included into ``main.py`` from medical-monitoring and
eligibility modules are outside the seven-family migration boundary (their
stores are not declared migration sources) and are therefore not part of this
inventory; the boundary is recorded here for Codex review.
"""

from __future__ import annotations

import ast
from enum import Enum
from hashlib import sha256
from pathlib import Path
import re
from typing import Any, Literal, Mapping, Optional, Sequence, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
    model_validator,
)
from typing_extensions import Annotated

from ..canonical.hashing import canonical_json

__all__ = [
    "INVENTORY_SCHEMA_VERSION",
    "InventoryDriftReport",
    "InventoryFinding",
    "JUSTIFICATION_CATALOG",
    "MutatorClassification",
    "MutationInventory",
    "RouteInventoryEntry",
    "ServiceInventoryEntry",
    "build_inventory",
    "discover_route_mutators",
    "discover_service_mutators",
    "verify_inventory_drift",
]

INVENTORY_SCHEMA_VERSION = "mw_legacy_mutation_inventory_v1"

_NonEmpty = Annotated[str, StringConstraints(min_length=1)]

# ---------------------------------------------------------------------------
# Closed classification vocabulary
# ---------------------------------------------------------------------------


class MutatorClassification(str, Enum):
    """Closed vocabulary: every discovered mutator gets exactly one of these."""

    LEGACY_WRITE = "legacy_write"
    READ_ONLY = "read_only"
    EXCLUDED = "excluded"


_CLASSIFICATION_VALUES: frozenset[str] = frozenset(
    member.value for member in MutatorClassification
)

# ---------------------------------------------------------------------------
# Stable justification catalog (Chinese-safe, resolved by key)
# ---------------------------------------------------------------------------

JUSTIFICATION_CATALOG: Mapping[str, str] = {
    "journey_store": "写入 v2 写作旅程/阶段草稿族事实（journey_stage_draft 族）",
    "journey_events": "写入 v2 写作旅程事件流（journey_stage_draft 族）",
    "journey_reservation": "写入 v2 写作旅程生成预留记录（journey_stage_draft 族）",
    "working_copy": "写入 v2 工作副本/快照/修订/审批族事实（working_copy_snapshot / decision_approval 族）",
    "approval_decisions": "写入 v2 审批决策记录（decision_approval 族）",
    "approval_gate": "写入 v2 审批门记录（decision_approval 族）",
    "approval_audit": "写入 v2 审批工作流审计事件（decision_approval 族）",
    "evidence_store": "写入 v2 证据设计/证据族事实（corpus_evidence 族）",
    "reference_store": "写入 v2 写作参考文献/语料/决策族事实（corpus_evidence / decision_approval 族）",
    "reference_pipeline": "写入 v2 参考文献准备流水线运行记录（corpus_evidence 族）",
    "corpus_store": "写入 v2 共享语料族事实（corpus_evidence 族）",
    "greenfield_docs": "写入 v2 方案文档族事实（protocol_document 族）",
    "greenfield_events": "写入 v2 方案文档事件流（protocol_document 族）",
    "lineage_records": "写入 v2 产物谱系记录（artifact_lineage 族）",
    "lineage_events": "写入 v2 产物谱系事件（artifact_lineage 族）",
    "lineage_state": "写入 v2 产物谱系状态（artifact_lineage 族）",
    "read_route_write_side_effect": "GET 路由含写入副作用（调用 legacy_write 服务），按变更操作防护",
    "preview_only": "只读预览：调用纯预览服务，不持久化任何事实",
    "always_403": "路由恒返回 403，无任何写入路径",
    "pure_transform": "纯内存模型变换/哈希计算，无持久化写入",
    "pure_validation": "纯校验/守卫逻辑，无持久化写入",
    "replay_read": "只读重放：仅 SELECT 读取并返回当前状态，无写入",
    "ai_gateway": "AI 网关配置域，非七类迁移族（未声明为迁移源）",
    "eligibility": "eligibility 域存储，非七类迁移族（未声明为迁移源）",
    "monitoring": "monitoring/rux 域存储，非七类迁移族（未声明为迁移源）",
    "safety_pv": "safety/PV 域存储，非七类迁移族（未声明为迁移源）",
    "tfl": "TFL review 域存储，非七类迁移族（未声明为迁移源）",
    "project_lifecycle": "项目生命周期元数据，非七类迁移族（未声明为迁移源）",
    "source_registry": "项目源注册/eligibility 摄入域，非七类迁移族（未声明为迁移源）",
    "medical_source_registry": "写入 v2 医学写作专用源注册（investigator-brochure 摄入，corpus_evidence 族）",
    "infra_schema": "存储层 schema 迁移/初始化/通用 SQL 执行，非事实写入",
    "infra_restore": "存储级备份/恢复/导入工具，非项目事实写入",
    "infra_wiring": "内存依赖装配 setter，非持久化写入",
    "constructor_setup": "构造函数初始化（调用 schema 初始化），非事实写入",
    "idempotency_bookkeeping": "幂等/拒绝簿记记录，非事实写入",
    "audit_chain": "运行时审计链，非声明迁移源（追加式操作记录）",
}

_JUSTIFICATION_KEYS: frozenset[str] = frozenset(JUSTIFICATION_CATALOG)


def _justification(key: str) -> str:
    if key not in _JUSTIFICATION_KEYS:
        raise ValueError(f"unknown justification key: {key!r}")
    return JUSTIFICATION_CATALOG[key]


def _coerce_classification(value: Any) -> MutatorClassification:
    if isinstance(value, MutatorClassification):
        return value
    if isinstance(value, str) and value in _CLASSIFICATION_VALUES:
        return MutatorClassification(value)
    raise ValueError(f"unknown mutator classification: {value!r}")


# ---------------------------------------------------------------------------
# Inventory entry models (frozen; the curated tables are authoritative)
# ---------------------------------------------------------------------------


class RouteInventoryEntry(BaseModel):
    """One route-level inventory entry: method/path/function + classification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: _NonEmpty
    http_method: str = Field(pattern=r"^(get|post|put|patch|delete|options|head)$")
    path: _NonEmpty
    function: _NonEmpty
    source_file: _NonEmpty = "services/api/app/main.py"
    project_binding: Literal["path", "query", "body", "global"]
    project_field: str = ""
    classification: MutatorClassification
    justification_key: _NonEmpty
    justification: str = ""

    @model_validator(mode="after")
    def _resolve_justification(self) -> "RouteInventoryEntry":
        object.__setattr__(self, "justification", _justification(self.justification_key))
        return self


class ServiceInventoryEntry(BaseModel):
    """One service-level inventory entry: module/class/function + classification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: _NonEmpty
    module: _NonEmpty
    class_name: str = ""
    function: _NonEmpty
    source_file: _NonEmpty
    classification: MutatorClassification
    justification_key: _NonEmpty
    justification: str = ""

    @model_validator(mode="after")
    def _resolve_justification(self) -> "ServiceInventoryEntry":
        object.__setattr__(self, "justification", _justification(self.justification_key))
        return self


# ---------------------------------------------------------------------------
# Curated route inventory (every discovered mutation-verb route in main.py,
# plus the one GET route with a write side effect).  Rows:
#   (http_method, path, function, classification, justification_key)
# ---------------------------------------------------------------------------

_ROUTE_ROWS: tuple[tuple[str, str, str, str, str], ...] = (
    ("post", '/api/projects/{project_id}/revision-threads/{thread_id}/accept-and-apply', "accept_and_apply_revision_candidate", "legacy_write", "working_copy"),
    ("post", '/api/projects/{project_id}/medical-writing/working-copies/{section_id}/accept-and-bind', "accept_and_bind_medical_writing_working_copy", "legacy_write", "working_copy"),
    ("post", '/api/ai-gateway/active-profile', "activate_ai_gateway_profile", "excluded", "ai_gateway"),
    ("post", '/api/medical-writing/shared-corpus/phase1/{segment_id}/admissions', "admit_phase1_shared_corpus_candidate", "legacy_write", "reference_store"),
    ("post", '/api/projects/{project_id}/medical-writing/references/translations/{translation_id}/admissions', "admit_writing_reference_translation", "legacy_write", "reference_store"),
    ("post", '/api/projects/{project_id}/medical-writing/authoring-journey/prefill-package/adopt', "adopt_medical_writing_authoring_prefill_candidate", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/authoring-journey/prefill-package/adopt-composite', "adopt_medical_writing_authoring_prefill_composite", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/full-drafts/{job_id}/adopt', "adopt_medical_writing_full_draft", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/full-drafts/{job_id}/decisions', "resolve_medical_writing_full_draft_decision", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/references/preparation-batches/{batch_id}/advance-stage', "advance_writing_reference_preparation_batch_stage", "legacy_write", "reference_store"),
    ("post", '/api/projects/{project_id}/approvals/{approval_id}/actions', "apply_approval_action", "legacy_write", "working_copy"),
    ("post", '/api/projects/{project_id}/evidence-design/picos-workflow/{package_id}/ai-revisions/{thread_id}/actions', "apply_evidence_ai_revision_action", "legacy_write", "evidence_store"),
    ("post", '/api/projects/{project_id}/evidence-design/packages/{package_id}/candidates/{evidence_id}/review-actions', "apply_evidence_candidate_review_action", "legacy_write", "evidence_store"),
    ("post", '/api/projects/{project_id}/evidence-design/picos-workflow/{package_id}/questions/{question_id}/actions', "apply_evidence_picos_action", "legacy_write", "evidence_store"),
    ("post", '/api/projects/{project_id}/medical-writing/content-quality/findings/{finding_id}/disposition', "apply_medical_writing_content_disposition", "legacy_write", "working_copy"),
    ("post", '/api/projects/{project_id}/medical-writing/greenfield-document/template-upgrade/apply', "apply_medical_writing_greenfield_template_upgrade", "legacy_write", "greenfield_docs"),
    ("post", '/api/projects/{project_id}/medical-writing/greenfield-document/module-resolutions/{semantic_node_id}', "apply_medical_writing_protocol_module_resolution", "legacy_write", "greenfield_docs"),
    ("post", '/api/projects/{project_id}/medical-writing/working-copies/{section_id}/revision-threads/{thread_id}/apply', "apply_medical_writing_revision_to_working_copy", "legacy_write", "working_copy"),
    ("post", '/api/projects/{project_id}/medical-writing/study-consistency/rebind', "apply_medical_writing_study_rebind", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/workbench-inbox/{item_id}/risk-disposition', "apply_monitoring_risk_disposition", "excluded", "monitoring"),
    ("post", '/api/projects/{project_id}/revision-threads/{thread_id}/actions', "apply_revision_action", "legacy_write", "working_copy"),
    ("post", '/api/projects/{project_id}/workbench-inbox/{item_id}/rux-risk-disposition', "apply_rux_risk_disposition", "excluded", "monitoring"),
    ("post", '/api/projects/{project_id}/safety-pv/review-workbench/{package_id}/signals/{signal_id}/actions', "apply_safety_review_action", "excluded", "safety_pv"),
    ("post", '/api/projects/{project_id}/tfl/review-workbench/{package_id}/outputs/{output_id}/actions', "apply_tfl_review_action", "excluded", "tfl"),
    ("post", '/api/projects/{project_id}/workbench-inbox/{item_id}/actions', "apply_workbench_inbox_action", "excluded", "monitoring"),
    ("post", '/api/projects/{project_id}/medical-writing/references/ocr-consistency-reviews/batch-disposition', "batch_dispose_writing_reference_ocr_consistency", "legacy_write", "reference_store"),
    ("post", '/api/projects/{project_id}/medical-writing/references/translation-batches/{batch_id}/medical-review', "batch_review_writing_reference_translations", "legacy_write", "reference_store"),
    ("put", '/api/ai-gateway/roles/{role_id}', "bind_ai_gateway_role", "excluded", "ai_gateway"),
    ("post", '/api/projects/{project_id}/medical-writing/jobs/{job_id}/cancel', "cancel_durable_mw_job", "legacy_write", "journey_store"),
    ("post", '/api/medical-writing/project-intake/synopsis/{intake_id}/jobs/{idempotency_key}/cancel', "cancel_file_first_synopsis_project_intake", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/research-pipeline/cancel', "cancel_medical_writing_research_pipeline", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/authoring-journey/synopsis-import/jobs/{idempotency_key}/cancel', "cancel_medical_writing_synopsis_import_job", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/authoring-journey/stages/{stage}/commit', "commit_medical_writing_authoring_stage", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/authoring-journey/study-schema/commit', "commit_medical_writing_study_schema", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/authoring-journey/competitor-triage/{run_id}/confirm', "confirm_competitor_triage_basket", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/authoring-journey/competitor-triage/{run_id}/reconfirm', "reconfirm_competitor_triage_basket", "legacy_write", "journey_store"),
    ("post", '/api/medical-writing/project-intake/synopsis/confirm', "confirm_file_first_synopsis_project_intake", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/legacy-authoring-bootstrap/confirm', "confirm_medical_writing_legacy_authoring_bootstrap", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/protocol-assembly-plan/confirm', "confirm_medical_writing_protocol_assembly_plan", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/authoring-journey/synopsis-import/confirm', "confirm_medical_writing_protocol_synopsis", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/study-consistency/sections/{section_id}/confirm', "confirm_medical_writing_study_reconciliation", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/monitoring/batches/{batch_id}/confirm-full-snapshot', "confirm_monitoring_batch_full_snapshot", "excluded", "monitoring"),
    ("post", '/api/projects/{project_id}/sources/{source_entry_id}/content-validation/confirm', "confirm_registered_source_content_validation", "excluded", "source_registry"),
    ("post", '/api/projects/{project_id}/medical-writing/research-pipeline/continue-after-triage', "continue_medical_writing_research_pipeline_after_triage", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/authoring-journey/competitor-triage', "create_competitor_triage_run", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/evidence-design/picos-workflow/{package_id}/writing-handoffs', "create_evidence_picos_writing_handoff", "legacy_write", "evidence_store"),
    ("post", '/api/projects/{project_id}/medical-writing/authoring-journey', "create_medical_writing_authoring_journey", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/fact-intake/{scope}', "create_medical_writing_fact_intake_conversation", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/greenfield-document', "create_medical_writing_greenfield_document", "legacy_write", "greenfield_docs"),
    ("post", '/api/projects/{project_id}/medical-writing/working-copies/{section_id}/approval-gate', "create_medical_writing_working_copy_approval_gate", "legacy_write", "working_copy"),
    ("post", '/api/projects', "create_project", "excluded", "project_lifecycle"),
    ("post", '/api/projects/{project_id}/medical-writing/references/translation-batches/{batch_id}/items/{item_id}/downstream-contract-transition', "create_writing_reference_downstream_contract_transition", "legacy_write", "reference_store"),
    ("post", '/api/projects/{project_id}/medical-writing/references/preparation-batches', "create_writing_reference_preparation_batch", "legacy_write", "reference_store"),
    ("post", '/api/projects/{project_id}/medical-writing/references/search-snapshots', "create_writing_reference_search_snapshot", "legacy_write", "reference_store"),
    ("post", '/api/projects/{project_id}/medical-writing/references/translations', "create_writing_reference_translation", "legacy_write", "reference_store"),
    ("post", '/api/projects/{project_id}/medical-writing/references/translation-batches', "create_writing_reference_translation_batch", "legacy_write", "reference_store"),
    ("post", '/api/ai-gateway/discover-models', "discover_ai_gateway_models", "excluded", "ai_gateway"),
    ("post", '/api/projects/{project_id}/medical-writing/authoring-journey/competitor-search', "execute_medical_writing_authoring_competitor_search", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/references/documents/{artifact_id}/extract', "extract_writing_reference_document", "legacy_write", "reference_store"),
    ("post", '/api/projects/{project_id}/medical-writing/authoring-journey/corpus-triage/finalize', "finalize_medical_writing_corpus_triage", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/working-copies/{section_id}/freeze-current-version', "freeze_medical_writing_section_version", "legacy_write", "working_copy"),
    ("post", '/api/projects/{project_id}/medical-writing/authoring-journey/prefill-package/generate', "generate_medical_writing_authoring_prefill_package", "legacy_write", "journey_store"),
    ("get", '/api/projects/{project_id}/medical-writing/authoring-journey/synopsis-import/jobs/{idempotency_key}/result', "get_medical_writing_synopsis_import_job_result", "legacy_write", "read_route_write_side_effect"),
    ("post", '/api/projects/{project_id}/medical-writing/literature/imports', "import_medical_writing_literature_reference", "legacy_write", "reference_store"),
    ("post", '/api/projects/{project_id}/medical-writing/authoring-journey/synopsis-import', "import_medical_writing_protocol_synopsis", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/references/documents/ingest', "ingest_writing_reference_document", "legacy_write", "reference_store"),
    ("post", '/api/projects/{project_id}/medical-writing/working-copies/{section_id}/table-templates/{template_id}/instantiate', "instantiate_medical_writing_table_template", "legacy_write", "working_copy"),
    ("post", '/api/projects/{project_id}/monitoring/batches/intake-file', "intake_monitoring_batch_file", "excluded", "monitoring"),
    ("post", '/api/projects/{project_id}/medical-writing/references/documents/{artifact_id}/invalidate', "invalidate_writing_reference_document", "legacy_write", "reference_store"),
    ("post", '/api/projects/{project_id}/medical-writing/authoring-journey/corpus-gate/override', "override_medical_writing_corpus_gate", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/references/documents/{artifact_id}/content-validation/override', "override_writing_reference_document_validation", "legacy_write", "reference_store"),
    ("post", '/api/projects/{project_id}/medical-writing/fact-intake/{scope}/apply', "post_medical_writing_fact_intake_apply", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/fact-intake/{scope}/turns', "post_medical_writing_fact_intake_turn", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/legacy-authoring-bootstrap/prepare', "prepare_medical_writing_legacy_authoring_bootstrap", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/authoring-journey/impact-preview', "preview_medical_writing_authoring_impact", "read_only", "preview_only"),
    ("post", '/api/projects/{project_id}/medical-writing/protocol-assembly-plan/preview', "preview_medical_writing_protocol_assembly_plan", "read_only", "preview_only"),
    ("post", '/api/projects/{project_id}/medical-writing/authoring-journey/study-schema/impact-preview', "preview_medical_writing_study_schema_impact", "read_only", "preview_only"),
    ("post", '/api/ai-gateway/probe', "probe_ai_gateway_profile", "excluded", "ai_gateway"),
    ("post", '/api/ai-gateway/roles/ocr/probe-visual', "probe_ocr_role_visual_capability", "excluded", "ai_gateway"),
    ("post", '/api/projects/{project_id}/medical-writing/working-copies/{section_id}/assessment-instrument-appendix', "project_medical_writing_assessment_instrument_appendix", "legacy_write", "working_copy"),
    ("post", '/api/projects/{project_id}/medical-writing/working-copies/{section_id}/intervention-rules-projection', "project_medical_writing_intervention_rules", "legacy_write", "working_copy"),
    ("post", '/api/projects/{project_id}/medical-writing/working-copies/{section_id}/study-schema-figure', "project_medical_writing_study_schema_figure", "legacy_write", "working_copy"),
    ("post", '/api/projects/{project_id}/medical-writing/authoring-journey/corpus-gate/recalculate', "recalculate_medical_writing_corpus_gate", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/references/documents/{artifact_id}/ocr-consistency-rechecks', "recheck_writing_reference_ocr_consistency", "legacy_write", "reference_store"),
    ("post", '/api/projects/{project_id}/medical-writing/authoring-journey/picos-corpus-alignment', "record_medical_writing_picos_corpus_alignment", "legacy_write", "evidence_store"),
    ("post", '/api/projects/{project_id}/monitoring/batches/{batch_id}/validation-evidence', "record_monitoring_batch_validation_evidence", "excluded", "monitoring"),
    ("post", '/api/projects/{project_id}/medical-writing/references/search-snapshots/{snapshot_id}/relevance-decisions', "record_writing_reference_relevance_decision", "legacy_write", "reference_store"),
    ("post", '/api/projects/{project_id}/eligibility/source-admission/refresh', "refresh_eligibility_source_admission", "excluded", "eligibility"),
    ("post", '/api/projects/{project_id}/medical-writing/protocol-assembly-plan/refresh', "refresh_medical_writing_protocol_assembly_plan", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/sources/listing-file', "register_listing_file_source", "excluded", "source_registry"),
    ("post", '/api/projects/{project_id}/sources/local-candidate', "register_local_candidate_source", "excluded", "source_registry"),
    ("post", '/api/projects/{project_id}/sources/local-directory', "register_local_directory_source", "excluded", "source_registry"),
    ("post", '/api/projects/{project_id}/sources/local-file', "register_local_file_source", "excluded", "source_registry"),
    ("post", '/api/projects/{project_id}/medical-writing/sources/investigator-brochure', "register_medical_writing_investigator_brochure", "legacy_write", "medical_source_registry"),
    ("post", '/api/projects/{project_id}/sources/protocol-docx', "register_protocol_docx_source", "excluded", "source_registry"),
    ("post", '/api/projects/{project_id}/sources/raw-subject-bundle', "register_raw_subject_bundle_source", "excluded", "source_registry"),
    ("post", '/api/projects/{project_id}/medical-writing/greenfield-document/decisions/{decision_id}/resolve', "resolve_medical_writing_greenfield_decision", "legacy_write", "greenfield_docs"),
    ("post", '/api/medical-writing/project-intake/synopsis/{intake_id}/jobs/{idempotency_key}/resume', "resume_file_first_synopsis_project_intake", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/research-pipeline/resume', "resume_medical_writing_research_pipeline", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/authoring-journey/synopsis-import/jobs/{idempotency_key}/resume', "resume_medical_writing_synopsis_import_job", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/authoring-journey/competitor-triage/{run_id}/projection-retry', "retry_competitor_triage_projection", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/authoring-journey/competitor-triage/{run_id}/retry', "retry_competitor_triage_run", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/jobs/{job_id}/retry', "retry_durable_mw_job", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/research-pipeline/retry-triage', "retry_medical_writing_research_pipeline_triage", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/references/preparation-batches/{batch_id}/retry', "retry_writing_reference_preparation_batch", "legacy_write", "reference_store"),
    ("post", '/api/projects/{project_id}/medical-writing/references/translation-batches/{batch_id}/retry', "retry_writing_reference_translation_batch", "legacy_write", "reference_store"),
    ("post", '/api/projects/{project_id}/medical-writing/working-copies/{section_id}/revert-authoritative-baseline', "revert_medical_writing_working_copy_to_authoritative_baseline", "legacy_write", "working_copy"),
    ("post", '/api/medical-writing/shared-corpus/phase1/{segment_id}/medical-review', "review_phase1_shared_corpus_candidate", "legacy_write", "reference_store"),
    ("post", '/api/projects/{project_id}/medical-writing/references/documents/{artifact_id}/extraction-reviews', "review_writing_reference_extraction", "legacy_write", "reference_store"),
    ("post", '/api/projects/{project_id}/medical-writing/references/translations/{translation_id}/medical-review', "review_writing_reference_translation", "legacy_write", "reference_store"),
    ("post", '/api/projects/{project_id}/medical-writing/references/translations/{translation_id}/revisions', "revise_writing_reference_translation", "legacy_write", "reference_store"),
    ("post", '/api/projects/{project_id}/medical-writing/greenfield-document/template-upgrade/rollback', "rollback_medical_writing_greenfield_template_upgrade", "legacy_write", "greenfield_docs"),
    ("post", '/api/projects/{project_id}/medical-writing/authoring-journey/stages/{stage}/draft', "save_medical_writing_authoring_stage_draft", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/working-copies/{section_id}', "save_medical_writing_working_copy", "legacy_write", "working_copy"),
    ("post", '/api/medical-writing/project-intake/synopsis', "start_file_first_synopsis_project_intake", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/document-exports', "start_medical_writing_document_export", "legacy_write", "working_copy"),
    ("post", '/api/projects/{project_id}/medical-writing/full-drafts', "start_medical_writing_full_draft", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/research-pipeline/start', "start_medical_writing_research_pipeline", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/research-pipeline/round2', "start_medical_writing_research_pipeline_round2", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/ai-runs', "submit_ai_run", "read_only", "always_403"),
    ("post", '/api/projects/{project_id}/ai-runs/from-sources', "submit_ai_run_from_registered_sources", "excluded", "eligibility"),
    ("post", '/api/projects/{project_id}/evidence-design/picos-workflow/{package_id}/ai-revisions', "submit_evidence_ai_revision", "legacy_write", "evidence_store"),
    ("post", '/api/projects/{project_id}/evidence-design/picos-workflow/{package_id}/approval-submissions', "submit_evidence_picos_approval", "legacy_write", "evidence_store"),
    ("post", '/api/projects/{project_id}/medical-writing/document-preview/word-verification', "submit_medical_writing_word_verification", "legacy_write", "working_copy"),
    ("post", '/api/projects/{project_id}/monitoring/intake', "submit_monitoring_intake", "excluded", "monitoring"),
    ("post", '/api/projects/{project_id}/monitoring/intake/file', "submit_monitoring_intake_file", "excluded", "monitoring"),
    ("post", '/api/projects/{project_id}/revision-threads', "submit_revision_thread", "legacy_write", "working_copy"),
    ("post", '/api/projects/{project_id}/monitoring/batches/{batch_id}/transition', "transition_monitoring_batch", "excluded", "monitoring"),
    ("post", '/api/projects/{project_id}/medical-writing/working-copies/{section_id}/unfreeze', "unfreeze_medical_writing_section_version", "legacy_write", "working_copy"),
    ("put", '/api/projects/{project_id}/medical-writing/literature/citation-style', "update_medical_writing_citation_style", "legacy_write", "reference_store"),
    ("post", '/api/projects/{project_id}/medical-writing/working-copies/{section_id}/tables/{block_id}/batch-update', "update_medical_writing_structured_table", "legacy_write", "working_copy"),
    ("post", '/api/projects/{project_id}/medical-writing/authoring-journey/study-schema/layout', "update_medical_writing_study_schema_layout", "legacy_write", "journey_store"),
    ("post", '/api/projects/{project_id}/medical-writing/references/documents/upload', "upload_writing_reference_document", "legacy_write", "reference_store"),
    ("put", '/api/ai-gateway/profiles/{profile_id}', "upsert_ai_gateway_profile", "excluded", "ai_gateway"),
    ("post", '/api/projects/{project_id}/monitoring/batches/{batch_id}/verify-derived-snapshot', "verify_monitoring_batch_derived_snapshot", "excluded", "monitoring"),
)

# ---------------------------------------------------------------------------
# Curated service inventory (every discovered service mutator candidate in the
# seven named v2 modules).  Rows: (module_basename, qualified_function,
# classification, justification_key)
# ---------------------------------------------------------------------------

_SERVICE_ROWS: tuple[tuple[str, str, str, str], ...] = (
    ("medical_writing_artifact_lifecycle", "MedicalWritingArtifactLifecycleRepository.__init__", "excluded", "constructor_setup"),
    ("medical_writing_artifact_lifecycle", "MedicalWritingArtifactLifecycleRepository._initialize", "excluded", "infra_schema"),
    ("medical_writing_artifact_lifecycle", "MedicalWritingArtifactLifecycleRepository._insert_event", "legacy_write", "lineage_events"),
    ("medical_writing_artifact_lifecycle", "MedicalWritingArtifactLifecycleRepository.commit_purge", "legacy_write", "lineage_state"),
    ("medical_writing_artifact_lifecycle", "MedicalWritingArtifactLifecycleRepository.register", "legacy_write", "lineage_records"),
    ("medical_writing_artifact_lifecycle", "MedicalWritingArtifactLifecycleRepository.request_purge", "legacy_write", "lineage_state"),
    ("medical_writing_artifact_lifecycle", "MedicalWritingArtifactLifecycleRepository.rollback_to", "legacy_write", "lineage_state"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService.__init__", "excluded", "constructor_setup"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService._acquire_generation_reservation", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService._bootstrap_minimum_product_fact_packet", "read_only", "pure_transform"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService._ensure_reservation_allows_event", "read_only", "pure_validation"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService._initialize", "excluded", "infra_schema"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService._insert_event", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService._mark_generation_reservation_dispatched", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService._persist_update", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService._release_generation_reservation", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService._replay_completed_reservation", "read_only", "replay_read"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService._replay_from_store", "read_only", "replay_read"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService._supersede_generation_reservation", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService._try_insert_generation_reservation", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService.acknowledge_document_synchronization", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService.adopt_prefill_candidate", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService.adopt_prefill_composite", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService.apply_corpus_projection", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService.attach_search_snapshot", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService.attach_synopsis_import", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService.bind_plan_consumption_helper", "excluded", "infra_wiring"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService.bootstrap_confirmed_legacy_import", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService.commit_stage", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService.commit_study_schema", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService.confirm_synopsis_import", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService.create", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService.finalize_corpus_triage", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService.generate_prefill", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService.mark_document_created", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService.override_corpus_gate", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService.project_discovery_basket", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService.project_human_reconfirmed_basket", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService.record_picos_corpus_alignment", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService.release_document_creation_reservation", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService.reserve_document_creation", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService.restore_confirmed_search_snapshot_binding", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService.save_research_pipeline", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService.save_stage_draft", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "MedicalWritingAuthoringJourneyService.update_study_schema_layout", "legacy_write", "journey_store"),
    ("medical_writing_authoring_journey", "_merge_prefill_adoption_field_states", "read_only", "pure_transform"),
    ("medical_writing_authoring_journey", "_replace_study_definition_schema", "read_only", "pure_transform"),
    ("medical_writing_greenfield", "CompositeMedicalWritingDocumentService.apply_greenfield_module_resolution", "legacy_write", "greenfield_docs"),
    ("medical_writing_greenfield", "CompositeMedicalWritingDocumentService.create_greenfield", "legacy_write", "greenfield_docs"),
    ("medical_writing_greenfield", "CompositeMedicalWritingDocumentService.resolve_greenfield_decision", "legacy_write", "greenfield_docs"),
    ("medical_writing_greenfield", "GreenfieldMedicalWritingDocumentService.__init__", "excluded", "constructor_setup"),
    ("medical_writing_greenfield", "GreenfieldMedicalWritingDocumentService._initialize", "excluded", "infra_schema"),
    ("medical_writing_greenfield", "GreenfieldMedicalWritingDocumentService._insert_event", "legacy_write", "greenfield_events"),
    ("medical_writing_greenfield", "GreenfieldMedicalWritingDocumentService.apply_module_resolution", "legacy_write", "greenfield_docs"),
    ("medical_writing_greenfield", "GreenfieldMedicalWritingDocumentService.apply_template_upgrade", "legacy_write", "greenfield_docs"),
    ("medical_writing_greenfield", "GreenfieldMedicalWritingDocumentService.create", "legacy_write", "greenfield_docs"),
    ("medical_writing_greenfield", "GreenfieldMedicalWritingDocumentService.rebind_study_definition", "legacy_write", "greenfield_docs"),
    ("medical_writing_greenfield", "GreenfieldMedicalWritingDocumentService.resolve_decision", "legacy_write", "greenfield_docs"),
    ("medical_writing_greenfield", "GreenfieldMedicalWritingDocumentService.rollback_template_upgrade", "legacy_write", "greenfield_docs"),
    ("models", "MedicalWritingAdaptiveDesign.normalize_adaptive_design", "read_only", "pure_transform"),
    ("models", "MedicalWritingAuthoringJourney.migrate_and_fail_closed", "read_only", "pure_transform"),
    ("models", "MedicalWritingCrossoverDesign.normalize_crossover", "read_only", "pure_transform"),
    ("models", "MedicalWritingOpenLabelExtensionDesign.normalize_open_label_extension", "read_only", "pure_transform"),
    ("models", "MedicalWritingSampleSizeReestimationDesign.normalize_sample_size_reestimation", "read_only", "pure_transform"),
    ("models", "MedicalWritingStructuredStudyDesign._migrate_legacy_phase1_parts", "read_only", "pure_transform"),
    ("models", "MedicalWritingStructuredStudyDesign.migrate_legacy_complex_design_booleans", "read_only", "pure_transform"),
    ("models", "MedicalWritingStudyDefinition.migrate_study_definition_schema", "read_only", "pure_transform"),
    ("models", "MedicalWritingTreatmentSwitchDesign.normalize_treatment_switch", "read_only", "pure_transform"),
    ("models", "_clear_complex_design_fields", "read_only", "pure_transform"),
    ("source_intake", "SourceRegistryService._resolve_allowed_file", "read_only", "pure_validation"),
    ("source_intake", "SourceRegistryService._resolve_allowed_root", "read_only", "pure_validation"),
    ("source_intake", "SourceRegistryService.confirm_content_validation", "excluded", "source_registry"),
    ("source_intake", "SourceRegistryService.register_listing_file", "excluded", "source_registry"),
    ("source_intake", "SourceRegistryService.register_local_directory", "excluded", "source_registry"),
    ("source_intake", "SourceRegistryService.register_local_file", "excluded", "source_registry"),
    ("source_intake", "SourceRegistryService.register_medical_writing_document", "legacy_write", "medical_source_registry"),
    ("source_intake", "SourceRegistryService.register_protocol_docx", "excluded", "source_registry"),
    ("source_intake", "SourceRegistryService.register_protocol_selection", "excluded", "source_registry"),
    ("source_intake", "SourceRegistryService.register_protocol_selection_from_file", "excluded", "source_registry"),
    ("source_intake", "SourceRegistryService.register_raw_subject_bundle", "excluded", "source_registry"),
    ("source_intake", "SourceRegistryService.reusable_local_file_registration", "excluded", "source_registry"),
    ("source_intake", "SourceRegistryStore.append", "excluded", "source_registry"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.__init__", "excluded", "constructor_setup"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._append_runtime_audit", "excluded", "audit_chain"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._apply_v1", "excluded", "infra_schema"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._apply_v10", "excluded", "infra_schema"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._apply_v11", "excluded", "infra_schema"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._apply_v12", "excluded", "infra_schema"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._apply_v13", "excluded", "infra_schema"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._apply_v14", "excluded", "infra_schema"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._apply_v15", "excluded", "infra_schema"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._apply_v16", "excluded", "infra_schema"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._apply_v2", "excluded", "infra_schema"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._apply_v3", "excluded", "infra_schema"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._apply_v4", "excluded", "infra_schema"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._apply_v5", "excluded", "infra_schema"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._apply_v6", "excluded", "infra_schema"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._apply_v7", "excluded", "infra_schema"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._apply_v8", "excluded", "infra_schema"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._apply_v9", "excluded", "infra_schema"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._finish_eligibility_evidence_job", "excluded", "eligibility"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._import_audit", "excluded", "infra_restore"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._import_decision", "excluded", "infra_restore"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._import_disposition", "excluded", "infra_restore"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._import_gate", "excluded", "infra_restore"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._import_legacy", "excluded", "infra_restore"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._initialize", "excluded", "infra_schema"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._insert_evidence_ai_revision_snapshot", "legacy_write", "evidence_store"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._insert_evidence_picos_snapshot", "legacy_write", "evidence_store"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._insert_idempotency", "excluded", "idempotency_bookkeeping"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._insert_revision_snapshot", "legacy_write", "working_copy"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._insert_workflow_audit", "legacy_write", "approval_audit"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._insert_working_copy_snapshot", "legacy_write", "working_copy"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._issue_vlm_circuit_permit", "excluded", "eligibility"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._record_rejection", "excluded", "idempotency_bookkeeping"),
    ("sqlite_runtime_store", "SqliteRuntimeStore._upsert_gate", "legacy_write", "approval_gate"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.acquire_eligibility_vlm_circuit_permit", "excluded", "eligibility"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.add_eligibility_evidence_artifact", "excluded", "eligibility"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.add_eligibility_evidence_span", "excluded", "eligibility"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.cancel_eligibility_evidence_job", "excluded", "eligibility"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.claim_next_eligibility_evidence_job", "excluded", "eligibility"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.commit_approval_action", "legacy_write", "approval_decisions"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.commit_eligibility_ai_draft_batch", "excluded", "eligibility"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.commit_eligibility_evidence_visual_qc", "excluded", "eligibility"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.commit_eligibility_review_action", "excluded", "eligibility"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.commit_eligibility_source_processing_unit", "excluded", "eligibility"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.commit_evidence_ai_revision_action", "legacy_write", "evidence_store"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.commit_evidence_ai_revision_submission", "legacy_write", "evidence_store"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.commit_evidence_picos_action", "legacy_write", "evidence_store"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.commit_evidence_picos_handoff", "legacy_write", "evidence_store"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.commit_evidence_picos_snapshot", "legacy_write", "evidence_store"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.commit_evidence_review_action", "legacy_write", "evidence_store"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.commit_medical_writing_approval_action", "legacy_write", "working_copy"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.commit_medical_writing_atomic_accept_and_apply", "legacy_write", "working_copy"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.commit_medical_writing_content_disposition", "legacy_write", "working_copy"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.commit_medical_writing_revision_action", "legacy_write", "working_copy"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.commit_medical_writing_revision_submission", "legacy_write", "working_copy"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.commit_medical_writing_section_freeze", "legacy_write", "working_copy"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.commit_medical_writing_study_rebind_reset", "legacy_write", "working_copy"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.commit_medical_writing_working_copy_save", "legacy_write", "working_copy"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.commit_rux_disposition", "excluded", "monitoring"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.commit_safety_review", "excluded", "safety_pv"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.complete_eligibility_evidence_job", "excluded", "eligibility"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.create_eligibility_evidence_job", "excluded", "eligibility"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.create_eligibility_vlm_bound_job", "excluded", "eligibility"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.defer_eligibility_vlm_job_for_circuit", "excluded", "eligibility"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.ensure_medical_writing_approval_gate", "legacy_write", "working_copy"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.fail_eligibility_evidence_job", "excluded", "eligibility"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.fail_eligibility_vlm_job", "excluded", "eligibility"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.finalize_eligibility_vlm_job", "excluded", "eligibility"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.finalize_pdf_render_with_ocr_children", "excluded", "eligibility"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.heartbeat_eligibility_evidence_job", "excluded", "eligibility"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.record_eligibility_vlm_circuit_outcome", "excluded", "eligibility"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.record_rejection", "excluded", "idempotency_bookkeeping"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.register_eligibility_controlled_artifact", "excluded", "eligibility"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.register_eligibility_vlm_profile", "excluded", "eligibility"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.replace_eligibility_rule_revision", "excluded", "eligibility"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.replace_eligibility_subject_sources", "excluded", "eligibility"),
    ("sqlite_runtime_store", "SqliteRuntimeStore.start_eligibility_vlm_provider_attempt", "excluded", "eligibility"),
    ("sqlite_runtime_store", "_execute_sql_script_in_transaction", "excluded", "infra_schema"),
    ("sqlite_runtime_store", "load_sqlite_database", "excluded", "infra_restore"),
    ("writing_reference_repository", "WritingReferenceRepository.__init__", "excluded", "constructor_setup"),
    ("writing_reference_repository", "WritingReferenceRepository._append_audit", "excluded", "audit_chain"),
    ("writing_reference_repository", "WritingReferenceRepository._initialize", "excluded", "infra_schema"),
    ("writing_reference_repository", "WritingReferenceRepository._record_idempotency", "excluded", "idempotency_bookkeeping"),
    ("writing_reference_repository", "WritingReferenceRepository.admit_translation", "legacy_write", "reference_store"),
    ("writing_reference_repository", "WritingReferenceRepository.claim_upper_layer_escalation", "legacy_write", "reference_pipeline"),
    ("writing_reference_repository", "WritingReferenceRepository.finalize_upper_layer_escalation_from_existing_run", "legacy_write", "reference_pipeline"),
    ("writing_reference_repository", "WritingReferenceRepository.finish_upper_layer_escalation", "legacy_write", "reference_pipeline"),
    ("writing_reference_repository", "WritingReferenceRepository.invalidate_artifact", "legacy_write", "reference_store"),
    ("writing_reference_repository", "WritingReferenceRepository.override_document_validation", "legacy_write", "reference_store"),
    ("writing_reference_repository", "WritingReferenceRepository.record_batch_medical_review", "legacy_write", "reference_store"),
    ("writing_reference_repository", "WritingReferenceRepository.record_batch_ocr_consistency_medical_disposition", "legacy_write", "reference_store"),
    ("writing_reference_repository", "WritingReferenceRepository.record_extraction_review", "legacy_write", "reference_store"),
    ("writing_reference_repository", "WritingReferenceRepository.record_medical_review", "legacy_write", "reference_store"),
    ("writing_reference_repository", "WritingReferenceRepository.record_ocr_consistency_medical_disposition", "legacy_write", "reference_store"),
    ("writing_reference_repository", "WritingReferenceRepository.record_relevance_decision", "legacy_write", "reference_store"),
    ("writing_reference_repository", "WritingReferenceRepository.record_upper_layer_execution_idempotency", "excluded", "idempotency_bookkeeping"),
    ("writing_reference_repository", "WritingReferenceRepository.save_chapter_integration_result", "legacy_write", "reference_pipeline"),
    ("writing_reference_repository", "WritingReferenceRepository.save_composite_pipeline_run", "legacy_write", "reference_pipeline"),
    ("writing_reference_repository", "WritingReferenceRepository.save_document_artifact", "legacy_write", "reference_store"),
    ("writing_reference_repository", "WritingReferenceRepository.save_document_structure_plan", "legacy_write", "reference_store"),
    ("writing_reference_repository", "WritingReferenceRepository.save_document_structure_plan_with_connection", "legacy_write", "reference_store"),
    ("writing_reference_repository", "WritingReferenceRepository.save_document_validation", "legacy_write", "reference_store"),
    ("writing_reference_repository", "WritingReferenceRepository.save_extraction", "legacy_write", "reference_store"),
    ("writing_reference_repository", "WritingReferenceRepository.save_ocr_consistency_qc_recheck", "legacy_write", "reference_store"),
    ("writing_reference_repository", "WritingReferenceRepository.save_search_snapshot", "legacy_write", "reference_store"),
    ("writing_reference_repository", "WritingReferenceRepository.save_translation", "legacy_write", "reference_store"),
    ("writing_reference_repository", "WritingReferenceRepository.save_translation_chunk", "legacy_write", "reference_store"),
    ("writing_reference_repository", "WritingReferenceRepository.save_upper_layer_escalation", "legacy_write", "reference_pipeline"),
    ("writing_reference_repository", "WritingReferenceRepository.save_upper_layer_stage_run", "legacy_write", "reference_pipeline"),
    ("writing_reference_repository", "WritingReferenceRepository.store_triage_confirmation", "legacy_write", "reference_pipeline"),
    ("writing_reference_repository", "WritingReferenceRepository.store_triage_run", "legacy_write", "reference_pipeline"),
    ("writing_reference_repository", "WritingReferenceRepository.triage_record_idempotency", "excluded", "idempotency_bookkeeping"),
    ("writing_reference_repository", "_migrate_ocr_consistency_qc_v8", "excluded", "infra_schema"),
    ("writing_reference_repository", "_migrate_upper_layer_route_identity_v6", "excluded", "infra_schema"),
    ("writing_reference_repository", "_migrate_workspace_query_indexes_v7", "excluded", "infra_schema"),
)


def _route_project_binding(path: str) -> tuple[str, str]:
    if "{project_id}" in path:
        return "path", "project_id"
    return "global", ""


def _build_route_entries(
    rows: Sequence[tuple[str, str, str, str, str]],
) -> tuple[RouteInventoryEntry, ...]:
    entries: list[RouteInventoryEntry] = []
    for method, path, function, classification, key in rows:
        binding, field = _route_project_binding(path)
        entries.append(
            RouteInventoryEntry(
                operation_id=f"route.{function}",
                http_method=method,
                path=path,
                function=function,
                project_binding=binding,
                project_field=field,
                classification=_coerce_classification(classification),
                justification_key=key,
            )
        )
    return tuple(sorted(entries, key=lambda e: e.operation_id))


_SOURCE_FILES: Mapping[str, str] = {
    "medical_writing_authoring_journey": "services/api/app/medical_writing_authoring_journey.py",
    "sqlite_runtime_store": "services/api/app/sqlite_runtime_store.py",
    "medical_writing_company_corpus": "services/api/app/medical_writing_company_corpus.py",
    "writing_reference_repository": "services/api/app/writing_reference_repository.py",
    "medical_writing_greenfield": "services/api/app/medical_writing_greenfield.py",
    "medical_writing_artifact_lifecycle": "services/api/app/medical_writing_artifact_lifecycle.py",
    "source_intake": "services/api/app/source_intake.py",
    "models": "packages/contracts/workbench_contracts/models.py",
}


def _build_service_entries(
    rows: Sequence[tuple[str, str, str, str]],
) -> tuple[ServiceInventoryEntry, ...]:
    entries: list[ServiceInventoryEntry] = []
    for module, qualified, classification, key in rows:
        if "." in qualified and not qualified.startswith("_"):
            class_name, function = qualified.split(".", 1)
        else:
            class_name, function = "", qualified
        entries.append(
            ServiceInventoryEntry(
                operation_id=f"service.{module}.{qualified}",
                module=module,
                class_name=class_name,
                function=function,
                source_file=_SOURCE_FILES.get(module, module),
                classification=_coerce_classification(classification),
                justification_key=key,
            )
        )
    return tuple(sorted(entries, key=lambda e: e.operation_id))


# ---------------------------------------------------------------------------
# Deterministic AST discovery
# ---------------------------------------------------------------------------

_MUTATION_VERBS: frozenset[str] = frozenset({"post", "put", "patch", "delete"})
_ALL_VERBS: frozenset[str] = frozenset(
    {"get", "post", "put", "patch", "delete", "options", "head"}
)

_WRITE_VERBS = re.compile(
    r"^(create|insert|update|upsert|save|store|write|put|post|delete|remove|drop|destroy|append|"
    r"commit|register|record|submit|apply|adopt|confirm|finalize|override|cancel|retry|rollback|"
    r"resolve|refresh|import|ingest|extract|start|publish|archive|restore|accept|admit|revise|"
    r"invalidate|disposition|instantiate|bind|generate|execute|prepare|mutate|set|add|push|mark|"
    r"clear|toggle|increment|decrement|replace|merge|persist|flush|settle|advance|transition|"
    r"transfer|move|copy|reset|expire|acknowledge|dismiss|approve|reject|lock|unlock|reserve|"
    r"release|assign|unassign|attach|detach|embed|touch|recalculate|recompute|rebind|reconcile|"
    r"promote|demote|bootstrap|migrate|provision|dispatch|enqueue|grant|revoke|synchronize|sync|"
    r"ensure|restore|purge|replay|seal|freeze|unfreeze|dedupe)(?=_|$)"
)

_SQL_WRITE_START = re.compile(
    r"^\s*(?:WITH\s.*)?\s*(INSERT|UPDATE|DELETE|REPLACE|UPSERT|MERGE|"
    r"CREATE|ALTER|DROP|TRUNCATE)\b",
    re.I | re.S,
)

_DML_EXEC_ATTRS: frozenset[str] = frozenset({"execute", "executemany", "executescript"})
_FILE_WRITE_NAMES: frozenset[str] = frozenset(
    {"write_text", "write_bytes", "writelines", "write_json"}
)


class DiscoveredRoute(BaseModel):
    """One route handler discovered by AST in ``main.py``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str
    http_method: str
    path: str
    function: str
    lineno: int = Field(ge=1)
    mutator: bool = False
    project_binding: Literal["path", "query", "body", "global"] = "global"
    project_field: str = ""


class DiscoveredService(BaseModel):
    """One service mutator candidate discovered by AST in a named v2 module."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str
    module: str
    class_name: str = ""
    function: str
    lineno: int = Field(ge=1)
    matched_by: tuple[str, ...] = ()


def _called_attribute_names(node: ast.AST) -> set[str]:
    """All called attribute names (``self.x``/``service.x``) inside one node."""

    names: set[str] = set()
    for call in ast.walk(node):
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute):
            names.add(call.func.attr)
    return names


def _self_rooted_and_bare_calls(node: ast.AST) -> set[str]:
    """Names called by a function that are *provably* same-module calls:
    instance-method calls rooted at ``self`` (``self._persist_update``,
    ``self.store.append``) and bare function-name calls
    (``_replace_study_definition_schema(...)``).  Local-container calls such
    as ``results.append(...)`` are deliberately excluded, so the transitive
    closure cannot be pulled in by list/dict helper usage."""

    names: set[str] = set()
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        if isinstance(call.func, ast.Name):
            names.add(call.func.id)
            continue
        if not isinstance(call.func, ast.Attribute):
            continue
        base = call.func
        while isinstance(base, ast.Attribute):
            base = base.value
        if isinstance(base, ast.Name) and base.id == "self":
            names.add(call.func.attr)
    return names


def _sql_dml_literals(node: ast.AST) -> list[str]:
    """SQL strings passed to execute/executemany/executescript that start
    with a DML keyword (deterministic statement-level detection)."""

    out: list[str] = []
    for call in ast.walk(node):
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr in _DML_EXEC_ATTRS
            and call.args
        ):
            arg = call.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                statement = arg.value
            elif isinstance(arg, ast.JoinedStr):
                statement = " ".join(
                    part.value
                    for part in arg.values
                    if isinstance(part, ast.Constant) and isinstance(part.value, str)
                )
            else:
                continue
            if _SQL_WRITE_START.match(statement):
                out.append(statement)
    return out


def _file_write_calls(node: ast.AST) -> list[str]:
    out: list[str] = []
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        if isinstance(func, ast.Attribute):
            name, root = func.attr, func.value
        elif isinstance(func, ast.Name):
            name, root = func.id, None
        else:
            continue
        if name in _FILE_WRITE_NAMES:
            out.append(name)
        elif name == "dump" and isinstance(root, ast.Name) and root.id == "json":
            out.append("json.dump")
        elif (
            name == "open"
            and call.args
            and len(call.args) >= 2
            and isinstance(call.args[1], ast.Constant)
            and isinstance(call.args[1].value, str)
            and any(mode in call.args[1].value for mode in ("w", "a", "x"))
        ):
            out.append("open-write")
        elif name in {"move", "copy", "rmtree", "copy2", "copytree"} and isinstance(
            root, ast.Name
        ) and root.id == "shutil":
            out.append(f"shutil.{name}")
        elif name in {
            "remove",
            "unlink",
            "rename",
            "replace",
            "mkdir",
            "rmdir",
            "makedirs",
        } and isinstance(root, ast.Name) and root.id == "os":
            out.append(f"os.{name}")
    return out


def _route_handlers(tree: ast.AST) -> list[tuple[str, str, int, ast.AST]]:
    """(method, path, lineno, handler_node) for every @app.<verb> handler."""

    handlers: list[tuple[str, str, int, ast.AST]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr in _ALL_VERBS
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "app"
            ):
                method = decorator.func.attr
                path: str = "?"
                if decorator.args and isinstance(decorator.args[0], ast.Constant) and isinstance(
                    decorator.args[0].value, str
                ):
                    path = decorator.args[0].value
                else:
                    for kw in decorator.keywords:
                        if kw.arg == "path" and isinstance(kw.value, ast.Constant) and isinstance(
                            kw.value.value, str
                        ):
                            path = kw.value.value
                handlers.append((method, path, node.lineno, node))
    return handlers


def _module_functions(tree: ast.AST) -> list[tuple[str, int, ast.AST]]:
    """Top-level functions and class methods with qualified names."""

    result: list[tuple[str, int, ast.AST]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result.append((node.name, node.lineno, node))
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    result.append((f"{node.name}.{item.name}", item.lineno, item))
    return result


def discover_route_mutators(
    main_path: Union[str, Path] = "services/api/app/main.py",
    *,
    legacy_write_service_names: Optional[frozenset[str]] = None,
) -> tuple[DiscoveredRoute, ...]:
    """Deterministic AST discovery of route handlers in ``main.py``.

    A handler is a *discovered mutator* when its HTTP verb is a mutation verb,
    or when it calls a uniquely-named ``legacy_write`` service operation
    (this catches GET routes with write side effects).  Every discovered
    mutator MUST have a classification entry or the drift check fails.
    """

    source = Path(main_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    handlers = _route_handlers(tree)

    unique_write_names: frozenset[str] = frozenset()
    if legacy_write_service_names is not None:
        unique_write_names = legacy_write_service_names

    discovered: list[DiscoveredRoute] = []
    for method, path, lineno, node in handlers:
        binding, field = _route_project_binding(path)
        called = _called_attribute_names(node)
        is_mutator = method in _MUTATION_VERBS or bool(called & unique_write_names)
        discovered.append(
            DiscoveredRoute(
                operation_id=f"route.{node.name}",
                http_method=method,
                path=path,
                function=node.name,
                lineno=lineno,
                mutator=is_mutator,
                project_binding=binding,
                project_field=field,
            )
        )
    return tuple(sorted(discovered, key=lambda d: (d.operation_id, d.http_method)))


def discover_service_mutators(
    modules: Sequence[Union[str, Path]] = tuple(_SOURCE_FILES.values()),
) -> tuple[DiscoveredService, ...]:
    """Deterministic AST discovery of service mutator candidates.

    A candidate is a top-level function or class method in a named v2 module
    that: (a) starts with a write verb, (b) passes write SQL (DML/DDL) to
    execute/executemany/executescript, (c) performs file writes, or (d)
    transitively calls (within the same module) a discovered candidate.
    """

    discovered_by_module: dict[str, list[DiscoveredService]] = {}
    for module_path in modules:
        path = Path(module_path)
        module = path.stem
        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions = _module_functions(tree)

        direct: set[str] = set()
        matched: dict[str, tuple[str, ...]] = {}
        lineno_of: dict[str, int] = {}
        nodes: dict[str, ast.AST] = {}
        for qualified, lineno, node in functions:
            lineno_of[qualified] = lineno
            nodes[qualified] = node
            base = qualified.split(".")[-1].lstrip("_")
            reasons: list[str] = []
            if _WRITE_VERBS.match(base):
                reasons.append("write_verb")
            if _sql_dml_literals(node):
                reasons.append("dml_sql")
            if _file_write_calls(node):
                reasons.append("file_write")
            if reasons:
                direct.add(qualified)
                matched[qualified] = tuple(sorted(reasons))

        # Transitive closure: same-module callers of discovered candidates.
        # Only provably same-module calls close the loop: instance calls
        # rooted at ``self`` and bare function-name calls.  Local-container
        # calls (``results.append``) never match, so read helpers that merely
        # build lists are not dragged in.
        changed = True
        while changed:
            changed = False
            for qualified, lineno, node in functions:
                if qualified in direct:
                    continue
                hits = _self_rooted_and_bare_calls(node) & {
                    name.split(".")[-1] for name in direct
                }
                if hits:
                    direct.add(qualified)
                    matched[qualified] = ("calls_mutator",)
                    changed = True

        discovered_by_module[module] = []
        for qualified in sorted(direct):
            if "." in qualified and not qualified.startswith("_"):
                class_name, function = qualified.split(".", 1)
            else:
                class_name, function = "", qualified
            discovered_by_module[module].append(
                DiscoveredService(
                    operation_id=f"service.{module}.{qualified}",
                    module=module,
                    class_name=class_name,
                    function=function,
                    lineno=lineno_of[qualified],
                    matched_by=matched[qualified],
                )
            )
    return tuple(
        sorted(
            (item for items in discovered_by_module.values() for item in items),
            key=lambda d: d.operation_id,
        )
    )


# ---------------------------------------------------------------------------
# Inventory view + drift verification
# ---------------------------------------------------------------------------


class MutationInventory:
    """Curated inventory view with lookups and the AST drift check."""

    def __init__(
        self,
        *,
        route_entries: Optional[Sequence[RouteInventoryEntry]] = None,
        service_entries: Optional[Sequence[ServiceInventoryEntry]] = None,
    ) -> None:
        self._route_entries = tuple(
            sorted(route_entries or _build_route_entries(_ROUTE_ROWS), key=lambda e: e.operation_id)
        )
        self._service_entries = tuple(
            sorted(
                service_entries or _build_service_entries(_SERVICE_ROWS),
                key=lambda e: e.operation_id,
            )
        )
        self._route_by_id: dict[str, RouteInventoryEntry] = {
            entry.operation_id: entry for entry in self._route_entries
        }
        self._service_by_id: dict[str, ServiceInventoryEntry] = {
            entry.operation_id: entry for entry in self._service_entries
        }

    # -- lookups ---------------------------------------------------------

    @property
    def route_entries(self) -> tuple[RouteInventoryEntry, ...]:
        return self._route_entries

    @property
    def service_entries(self) -> tuple[ServiceInventoryEntry, ...]:
        return self._service_entries

    def route_entry(self, operation_id: str) -> Optional[RouteInventoryEntry]:
        return self._route_by_id.get(operation_id)

    def service_entry(self, operation_id: str) -> Optional[ServiceInventoryEntry]:
        return self._service_by_id.get(operation_id)

    def route_classification(self, operation_id: str) -> Optional[MutatorClassification]:
        entry = self._route_by_id.get(operation_id)
        return None if entry is None else entry.classification

    def service_classification(self, operation_id: str) -> Optional[MutatorClassification]:
        entry = self._service_by_id.get(operation_id)
        return None if entry is None else entry.classification

    def legacy_write_service_names(self) -> frozenset[str]:
        """Unique last-segment names of legacy_write service operations."""

        counts: dict[str, int] = {}
        for entry in self._service_entries:
            if entry.classification == MutatorClassification.LEGACY_WRITE:
                counts[entry.function] = counts.get(entry.function, 0) + 1
        return frozenset(name for name, count in counts.items() if count == 1)

    def legacy_write_route_operation_ids(self) -> tuple[str, ...]:
        return tuple(
            entry.operation_id
            for entry in self._route_entries
            if entry.classification == MutatorClassification.LEGACY_WRITE
        )

    def legacy_write_service_operation_ids(self) -> tuple[str, ...]:
        return tuple(
            entry.operation_id
            for entry in self._service_entries
            if entry.classification == MutatorClassification.LEGACY_WRITE
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": INVENTORY_SCHEMA_VERSION,
            "routes": [entry.model_dump(mode="json") for entry in self._route_entries],
            "services": [entry.model_dump(mode="json") for entry in self._service_entries],
        }

    @property
    def inventory_sha256(self) -> str:
        return sha256(canonical_json(self.canonical_payload()).encode("utf-8")).hexdigest()


class InventoryFinding(BaseModel):
    """One deterministic drift finding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    severity: Literal["error", "warning"]
    code: str
    operation_id: str = ""
    message: str


class InventoryDriftReport(BaseModel):
    """Immutable result of one inventory drift verification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["mw_legacy_mutation_inventory_v1"] = INVENTORY_SCHEMA_VERSION
    ok: bool
    discovered_route_handlers: int = Field(ge=0)
    discovered_route_mutators: int = Field(ge=0)
    discovered_service_mutators: int = Field(ge=0)
    inventoried_route_mutators: int = Field(ge=0)
    inventoried_service_mutators: int = Field(ge=0)
    findings: tuple[InventoryFinding, ...] = ()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def inventory_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"inventory_sha256"})
        return sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _finding(severity: str, code: str, operation_id: str, message: str) -> InventoryFinding:
    return InventoryFinding(
        severity=severity, code=code, operation_id=operation_id, message=message
    )


def _verify_route_consistency(
    inventory: MutationInventory,
    discovered: Sequence[DiscoveredRoute],
    handler_nodes: Mapping[str, ast.AST],
    findings: list[InventoryFinding],
) -> None:
    """Any read-only/GET route that calls a legacy_write service is drift."""

    unique_write_names = inventory.legacy_write_service_names()
    for route in discovered:
        handler_node = handler_nodes.get(route.function)
        if handler_node is None:
            continue
        called = _called_attribute_names(handler_node) & unique_write_names
        if not called:
            continue
        entry = inventory.route_entry(route.operation_id)
        classification = None if entry is None else entry.classification
        if route.http_method not in _MUTATION_VERBS and classification != MutatorClassification.LEGACY_WRITE:
            findings.append(
                _finding(
                    "error",
                    "read_route_calls_legacy_write",
                    route.operation_id,
                    f"GET route calls legacy_write service(s) {sorted(called)} "
                    "but is not inventoried as a mutator",
                )
            )
        elif classification == MutatorClassification.READ_ONLY:
            findings.append(
                _finding(
                    "error",
                    "read_only_route_calls_legacy_write",
                    route.operation_id,
                    f"route classified read_only calls legacy_write service(s) "
                    f"{sorted(called)}",
                )
            )


def verify_inventory_drift(
    *,
    main_path: Union[str, Path] = "services/api/app/main.py",
    service_modules: Sequence[Union[str, Path]] = tuple(_SOURCE_FILES.values()),
    inventory: Optional[MutationInventory] = None,
) -> InventoryDriftReport:
    """Run deterministic discovery over the current source and verify the
    curated inventory classifies every discovered mutator.

    Fails (``ok=False``) on: unclassified discovered mutator, stale
    classification entry, route entry method/path mismatch, service entry
    module/function mismatch, and read-only/GET routes that call legacy_write
    service operations.
    """

    inv = inventory if inventory is not None else MutationInventory()
    findings: list[InventoryFinding] = []

    main_tree = ast.parse(Path(main_path).read_text(encoding="utf-8"))
    handler_nodes = {
        node.name: node
        for method, path, lineno, node in _route_handlers(main_tree)
    }

    discovered_routes = discover_route_mutators(
        main_path, legacy_write_service_names=inv.legacy_write_service_names()
    )
    discovered_services = discover_service_mutators(service_modules)

    # --- route side: every discovered mutator must be classified ----------
    for route in discovered_routes:
        entry = inv.route_entry(route.operation_id)
        if not route.mutator:
            continue
        if entry is None:
            findings.append(
                _finding(
                    "error",
                    "unclassified_route_mutator",
                    route.operation_id,
                    f"discovered {route.http_method.upper()} route mutator "
                    f"{route.function!r} has no classification entry",
                )
            )
            continue
        if entry.http_method != route.http_method or entry.path != route.path:
            findings.append(
                _finding(
                    "error",
                    "route_entry_mismatch",
                    route.operation_id,
                    f"entry method/path {entry.http_method} {entry.path} does not "
                    f"match discovered {route.http_method} {route.path}",
                )
            )

    # stale route entries: entry exists but operation no longer discovered
    discovered_functions = {route.function for route in discovered_routes}
    for entry in inv.route_entries:
        if entry.function not in discovered_functions:
            findings.append(
                _finding(
                    "error",
                    "stale_route_entry",
                    entry.operation_id,
                    f"route entry {entry.function!r} is not discovered in current main.py",
                )
            )

    # --- service side: every discovered mutator must be classified ---------
    discovered_service_ids = {d.operation_id for d in discovered_services}
    for service in discovered_services:
        entry = inv.service_entry(service.operation_id)
        if entry is None:
            findings.append(
                _finding(
                    "error",
                    "unclassified_service_mutator",
                    service.operation_id,
                    f"discovered service mutator {service.operation_id!r} has no "
                    "classification entry",
                )
            )
            continue
        if entry.module != service.module or entry.function != service.function:
            findings.append(
                _finding(
                    "error",
                    "service_entry_mismatch",
                    service.operation_id,
                    f"entry module/function {entry.module}.{entry.function} does not "
                    f"match discovered {service.module}.{service.function}",
                )
            )

    # stale service entries
    for entry in inv.service_entries:
        if entry.operation_id not in discovered_service_ids:
            findings.append(
                _finding(
                    "error",
                    "stale_service_entry",
                    entry.operation_id,
                    f"service entry {entry.operation_id!r} is not discovered in the "
                    "current named v2 modules",
                )
            )

    # --- read-only / GET call-graph consistency ---------------------------
    _verify_route_consistency(inv, discovered_routes, handler_nodes, findings)

    mutator_routes = [d for d in discovered_routes if d.mutator]
    inventoried_route_mutators = sum(
        1 for d in mutator_routes if inv.route_entry(d.operation_id) is not None
    )
    inventoried_service_mutators = sum(
        1
        for d in discovered_services
        if inv.service_entry(d.operation_id) is not None
    )

    return InventoryDriftReport(
        ok=not any(f.severity == "error" for f in findings),
        discovered_route_handlers=len(discovered_routes),
        discovered_route_mutators=len(mutator_routes),
        discovered_service_mutators=len(discovered_services),
        inventoried_route_mutators=inventoried_route_mutators,
        inventoried_service_mutators=inventoried_service_mutators,
        findings=tuple(sorted(findings, key=lambda f: (f.code, f.operation_id))),
    )


def build_inventory() -> MutationInventory:
    """Build the built-in curated inventory view."""

    return MutationInventory()
