from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from hashlib import sha256
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    field_validator,
    model_validator,
)

from .protected_tokens import check_protected_tokens, protected_token_issue_dicts


class WorkbenchModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ApprovalState(str, Enum):
    AI_DRAFT = "ai_draft"
    IN_MEDICAL_REVIEW = "in_medical_review"
    RETURNED_FOR_REVISION = "returned_for_revision"
    MEDICALLY_APPROVED = "medically_approved"
    LOCKED_FOR_SUBMISSION = "locked_for_submission"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class ApprovalAction(str, Enum):
    APPROVE = "approve"
    RETURN_FOR_REVISION = "return_for_revision"
    REJECT = "reject"
    VIEW_QUALITY_GATE = "view_quality_gate"


class RiskSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskStatus(str, Enum):
    NEW = "new"
    TRIAGED = "triaged"
    IN_REVIEW = "in_review"
    ACTION_REQUIRED = "action_required"
    ACCEPTED_NO_ACTION = "accepted_no_action"
    RESOLVED = "resolved"
    CLOSED = "closed"
    SUPERSEDED = "superseded"


class Project(WorkbenchModel):
    project_id: str
    project_code: str
    project_name: str
    indication: str
    product_name: str
    study_phase: str
    protocol_id: str
    protocol_version: str
    protocol_date: str
    status: str = "active"
    owner_user_id: str = "medical_manager"
    created_at: datetime
    updated_at: datetime


class UserProjectCreateRequest(WorkbenchModel):
    project_code: str = Field(default="", max_length=80)
    project_name: str = Field(default="", max_length=200)
    indication: str = Field(min_length=2, max_length=120)
    product_name: str = Field(default="待定义试验药物", max_length=160)
    study_phase: str = Field(default="", max_length=40)
    protocol_id: str = Field(default="", max_length=100)
    protocol_version: str = Field(default="草案", max_length=40)
    protocol_date: str = Field(default="", max_length=20)
    entry_mode: Literal["from_zero", "synopsis_import"] = "from_zero"
    actor: str = Field(default="medical_manager", min_length=2, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=160)

    @model_validator(mode="after")
    def normalize_project_fields(self) -> "UserProjectCreateRequest":
        for field_name in (
            "project_code",
            "project_name",
            "indication",
            "product_name",
            "study_phase",
            "protocol_id",
            "protocol_version",
            "protocol_date",
            "actor",
            "idempotency_key",
        ):
            setattr(self, field_name, str(getattr(self, field_name)).strip())
        self.study_phase = {
            "I": "I期",
            "I/II": "I/II期",
            "II": "II期",
            "II/III": "II/III期",
            "III": "III期",
        }.get(self.study_phase, self.study_phase)
        if not self.project_code:
            phase_token = re.sub(r"[^A-Za-z0-9]+", "", self.study_phase).upper()
            phase_token = phase_token or "PHASE"
            identity = "|".join(
                (
                    self.product_name,
                    self.indication,
                    self.study_phase,
                    self.idempotency_key,
                )
            )
            suffix = sha256(identity.encode("utf-8")).hexdigest()[:8].upper()
            self.project_code = f"MW-{phase_token}-{suffix}"
        if not self.project_name:
            phase_label = self.study_phase or "分期待确认"
            self.project_name = (
                f"{self.product_name}用于治疗{self.indication}的"
                f"{phase_label}临床研究"
            )
        if not self.protocol_id:
            self.protocol_id = f"{self.project_code}-DRAFT"
        return self


class EvidenceSource(WorkbenchModel):
    evidence_id: str
    project_id: str
    source_type: str
    title: str
    file_path: str
    file_hash: str = ""
    version_label: str = ""
    confidentiality: str = "internal"
    data_batch_id: Optional[str] = None
    created_at: datetime


class EvidenceSpan(WorkbenchModel):
    span_id: str
    evidence_id: str
    page: Optional[int] = None
    sheet: Optional[str] = None
    row: Optional[int] = None
    column: Optional[str] = None
    quote: str = ""
    normalized_value: str = ""
    confidence: float = 1.0


class DataBatch(WorkbenchModel):
    batch_id: str
    project_id: str
    batch_label: str
    extract_date: str
    uploaded_by: str
    status: str
    source_file_ids: List[str] = Field(default_factory=list)
    previous_batch_id: Optional[str] = None
    mapping_profile_id: str = "default_edc_listing_mapping"
    row_count: int
    subject_count: int
    site_count: int
    created_at: datetime


class RiskEvidenceFragmentSnapshot(WorkbenchModel):
    locator: str
    source_revision: str
    captured_at: datetime
    available: StrictBool = True
    fragment: Dict[str, Any] = Field(default_factory=dict)
    error_code: str = ""


class RiskCase(WorkbenchModel):
    risk_id: str
    risk_key: str = ""
    risk_instance_id: str = ""
    project_id: str
    module: str
    risk_type: str
    primary_category: str = ""
    tags: List[str] = Field(default_factory=list)
    title: str
    subject_id: Optional[str] = None
    site_id: Optional[str] = None
    scope_type: Literal["trial", "site", "subject"] = "subject"
    scope_id: str = ""
    aggregation_scope: Literal["rule_scope", "episode"] = "rule_scope"
    episode_key: str = ""
    severity: RiskSeverity
    inspection_priority: str = "not_assessed"
    ctcae_grade: Optional[int] = Field(default=None, ge=1, le=5)
    action_priority: str = "not_assessed"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    status: RiskStatus
    source_batch_id: Optional[str] = None
    source_revision: str = ""
    rule_profile_revision: str = ""
    engine_version: str = ""
    batch_delta: Literal[
        "baseline",
        "new",
        "changed",
        "persisting",
        "resolved_by_data",
        "superseded_by_engine",
        "reopened",
        "requires_rereview",
        "unclassified",
    ] = "unclassified"
    rule_id: str
    evidence_span_ids: List[str] = Field(default_factory=list)
    evidence_snapshots: List[RiskEvidenceFragmentSnapshot] = Field(default_factory=list)
    rationale: str
    recommended_action: str
    owner: str = "medical_manager"
    created_at: datetime
    closed_at: Optional[datetime] = None
    closure_evidence: str = ""

    @model_validator(mode="after")
    def populate_legacy_identity_and_scope(self) -> "RiskCase":
        if not self.risk_key:
            self.risk_key = self.risk_id
        if not self.risk_instance_id:
            self.risk_instance_id = self.risk_id
        if not self.primary_category:
            self.primary_category = self.risk_type
        if not self.scope_id:
            if self.subject_id:
                self.scope_type = "subject"
                self.scope_id = self.subject_id
            elif self.site_id:
                self.scope_type = "site"
                self.scope_id = self.site_id
            else:
                self.scope_type = "trial"
                self.scope_id = self.project_id
        return self


class ApprovalGate(WorkbenchModel):
    approval_id: str
    project_id: str
    target_type: str
    target_id: str
    target_revision: Optional[int] = Field(default=None, ge=0)
    display_title: str = ""
    display_detail: str = ""
    state: ApprovalState
    requested_by: str
    reviewed_by: Optional[str] = None
    approved_by: Optional[str] = None
    review_comments: str = ""
    created_at: datetime
    updated_at: datetime


class ApprovalBlocker(WorkbenchModel):
    blocker_id: str
    blocker_type: str
    source_type: str
    source_id: str
    severity: RiskSeverity = RiskSeverity.HIGH
    message: str


class ApprovalActionRequest(WorkbenchModel):
    action: ApprovalAction
    actor: str = "medical_manager"
    comment: str = ""
    idempotency_key: str = ""


class ApprovalDecisionRecord(WorkbenchModel):
    decision_id: str
    approval_id: str
    project_id: str
    action: ApprovalAction
    actor: str
    previous_state: ApprovalState
    new_state: ApprovalState
    comment: str = ""
    blocked: bool = False
    blockers: List[ApprovalBlocker] = Field(default_factory=list)
    audit_event_id: str
    created_at: datetime


class AiTaskRunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class AiTaskOutputValidationStatus(str, Enum):
    NOT_VALIDATED = "not_validated"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


class AiTaskSourceRef(WorkbenchModel):
    source_id: str
    source_type: str
    title: str
    locator: str
    text_preview: str = ""
    project_id: str = ""
    module: str = ""
    source_entry_id: str = ""


class AiTaskRequest(WorkbenchModel):
    module: str
    task_type: str
    prompt_version: str
    allowed_sources: List[AiTaskSourceRef]
    forbidden_source_ids: List[str] = Field(default_factory=list)
    user_instruction: str = ""
    task_context: Dict[str, Any] = Field(default_factory=dict)


class SourceRegistryEntry(WorkbenchModel):
    entry_id: str
    project_id: str
    module: str
    source_kind: str
    public_title: str
    content_hash: str
    size_bytes: int = 0
    parser_status: str = "parsed"
    parser_version: str = "source_registry_v0_1"
    span_count: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)
    storage_key: str = Field(default="", exclude=True)
    server_path: str = Field(default="", exclude=True)
    created_at: datetime


class SourceRegistrySpan(WorkbenchModel):
    source_id: str
    entry_id: str
    project_id: str
    module: str
    source_type: str
    title: str
    locator: str
    text_preview: str = ""
    preview_hash: str = Field(default="", exclude=True)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class SourceRegistrationResult(WorkbenchModel):
    entry: SourceRegistryEntry
    spans: List[SourceRegistrySpan] = Field(default_factory=list)


class SourceContentValidationCheck(WorkbenchModel):
    check_code: str
    label: str
    expected_value: str = ""
    observed_value: str = ""
    outcome: Literal["match", "warning", "mismatch", "not_assessed"]
    overridable: bool = True
    evidence_locators: List[str] = Field(default_factory=list)


class SourceContentValidationRecord(WorkbenchModel):
    validation_id: str
    project_id: str
    source_entry_id: str
    module: str
    revision: int = Field(ge=1)
    technical_status: Literal["ready", "failed"]
    content_status: Literal["matched", "warning", "mismatch", "not_assessed"]
    use_status: Literal[
        "allowed",
        "requires_confirmation",
        "confirmed_after_warning",
        "blocked_technical_failure",
    ]
    file_sha256: str
    expected_context_hash: str
    validator_version: str = "source_content_consistency_v2"
    checks: List[SourceContentValidationCheck] = Field(default_factory=list)
    summary: str
    actor: str
    confirmation_reason: str = ""
    acknowledged_check_codes: List[str] = Field(default_factory=list)
    identity_assurance: str = "unverified_client_claim"
    created_at: datetime


class SourceContentValidationConfirmationRequest(WorkbenchModel):
    reason: str
    acknowledged_check_codes: List[str] = Field(default_factory=list)
    actor: str = "medical_manager"
    expected_revision: int = Field(ge=1)
    idempotency_key: str


class SourceValidationBinding(WorkbenchModel):
    source_role_code: str
    source_role: str
    source_entry_id: str
    validation_id: str
    revision: int = Field(ge=1)
    validator_version: str
    technical_status: Literal["ready", "failed"]
    content_status: Literal["matched", "warning", "mismatch", "not_assessed"]
    use_status: Literal[
        "allowed",
        "requires_confirmation",
        "confirmed_after_warning",
        "blocked_technical_failure",
    ]


class SourceAdmissionSource(SourceValidationBinding):
    public_title: str
    summary: str
    checks: List[SourceContentValidationCheck] = Field(default_factory=list)
    confirmation_reason: str = ""
    confirmation_actor: str = ""
    confirmed_at: Optional[datetime] = None


class SourceAdmissionState(WorkbenchModel):
    project_id: str
    module: str
    scope_id: str
    sources: List[SourceAdmissionSource] = Field(default_factory=list)
    missing_source_roles: List[str] = Field(default_factory=list)
    ready_for_use: bool = False


class AiTaskFromRegistryRequest(WorkbenchModel):
    module: str
    task_type: str
    expected_prompt_version: str = ""
    source_ids: List[str]
    expected_source_entry_ids: List[str] = Field(default_factory=list)
    forbidden_source_ids: List[str] = Field(default_factory=list)
    user_instruction: str = ""
    task_context: Dict[str, Any] = Field(default_factory=dict)


class AiTaskEvidenceEntry(WorkbenchModel):
    evidence_id: str
    source_id: str
    locator: str
    quote: str = ""
    finding_ids: List[str] = Field(default_factory=list)


class AiTaskArtifact(WorkbenchModel):
    artifact_id: str
    artifact_type: str
    content_type: str = "application/json"
    payload: Dict[str, Any] = Field(default_factory=dict)
    validation_errors: List[str] = Field(default_factory=list)


class AiTaskRun(WorkbenchModel):
    run_id: str
    project_id: str
    module: str
    task_type: str
    purpose: str
    status: AiTaskRunStatus
    provider: str
    model_name: str
    ai_gateway_status: str
    codex_runtime_dependency: bool = False
    request_origin: str = "legacy_unresolved"
    data_classification: str = "unclassified"
    deployment_profile: str = "legacy_unresolved"
    policy_decision_id: str = ""
    task_context_summary: Dict[str, Any] = Field(default_factory=dict)
    prompt_version: str
    schema_version: str = "ai_task_output_v0_1"
    output_validation_status: AiTaskOutputValidationStatus = AiTaskOutputValidationStatus.NOT_VALIDATED
    route_profile_id: str = ""
    route_profile_revision: int = 0
    route_transport: str = ""
    route_base_url: str = ""
    expected_response_model: str = ""
    actual_response_model: str = ""
    route_identity_hash: str = ""
    route_thinking: str = ""
    route_reasoning_effort: str = ""
    fallback_chain_id: str = ""
    fallback_parent_run_id: str = ""
    fallback_depth: int = Field(default=0, ge=0)
    fallback_reason: str = ""
    input_sources: List[AiTaskSourceRef] = Field(default_factory=list)
    forbidden_source_ids: List[str] = Field(default_factory=list)
    artifacts: List[AiTaskArtifact] = Field(default_factory=list)
    evidence_entries: List[AiTaskEvidenceEntry] = Field(default_factory=list)
    validation_errors: List[str] = Field(default_factory=list)
    error_message: str = ""
    needs_medical_confirmation: bool = True
    created_at: datetime
    updated_at: datetime


class WorkbenchItemAction(str, Enum):
    MARK_READ = "mark_read"


class WorkbenchItemActionRequest(WorkbenchModel):
    action: WorkbenchItemAction
    actor: str = "medical_manager"
    comment: str = ""
    expected_source_version: str


class MonitoringMedicalJudgments(WorkbenchModel):
    patient_safety_impact: bool = False
    key_data_impact: bool = False
    query_required: bool = False
    lock_or_export_impact: bool = False
    review_completed: bool = False


class RuxRiskDispositionAction(str, Enum):
    REVIEWED = "reviewed"
    QUERY_DRAFT = "query_draft"
    SUBMITTED_FOR_APPROVAL = "submitted_for_approval"
    REOPEN = "reopen"


class MonitoringRiskDispositionKind(str, Enum):
    EXPLAINED_NO_EXTERNAL_ACTION = "explained_no_external_action"
    CENTER_QUERY = "center_query"
    DATA_CORRECTION = "data_correction"
    FOLLOW_UP = "follow_up"
    PD_UPDATE = "pd_update"
    SAFETY_PV_COLLABORATION = "safety_pv_collaboration"
    CONTINUE_OBSERVATION = "continue_observation"
    DUPLICATE_NOT_APPLICABLE = "duplicate_not_applicable"


class RuxRiskDispositionActionRequest(WorkbenchModel):
    action: RuxRiskDispositionAction
    disposition_kind: Optional[MonitoringRiskDispositionKind] = None
    actor: str = "medical_manager"
    reauthenticated: bool = False
    signature_evidence_sha256: str = Field(default="", max_length=64)
    comment: str = ""
    expected_source_version: str
    query_draft_text: str = ""
    idempotency_key: str = ""
    medical_judgments: Optional[MonitoringMedicalJudgments] = None
    expected_disposition_state: str = ""
    basis_disposition_record_id: str = ""
    reassessment_change_reason: str = ""


class WorkbenchItemSourceRef(WorkbenchModel):
    source_type: str
    source_id: str
    label: str
    locator: str = ""


class RuxRiskDispositionRecord(WorkbenchModel):
    record_id: str
    project_id: str
    item_id: str
    risk_id: str
    risk_key: str = ""
    risk_instance_id: str = ""
    snapshot_id: str = ""
    subject_id: str
    rule_id: str
    action: RuxRiskDispositionAction
    disposition_kind: Optional[MonitoringRiskDispositionKind] = None
    previous_state: str
    new_state: str
    actor: str = "medical_manager"
    comment: str = ""
    query_draft_text: str = ""
    approval_ref: str = ""
    source_version: str
    source_refs_snapshot: List[WorkbenchItemSourceRef] = Field(default_factory=list)
    medical_judgments: Optional[MonitoringMedicalJudgments] = None
    basis_disposition_record_id: str = ""
    reassessment_change_reason: str = ""
    created_at: datetime


class WorkbenchItem(WorkbenchModel):
    item_id: str
    project_id: str
    module: str
    module_label: str
    item_type: str
    source_type: str
    source_id: str
    risk_key: str = ""
    risk_instance_id: str = ""
    snapshot_id: str = ""
    title: str
    summary: str
    priority: str
    status: str
    unread: bool = True
    needs_action: bool = True
    owner_role: str = "医学经理"
    action_label: str = "查看"
    target_page: str = "overview"
    target_id: str = ""
    source_version: str
    source_refs: List[WorkbenchItemSourceRef] = Field(default_factory=list)
    updated_at: datetime
    boundary_note: str = ""
    medical_judgments: Optional[MonitoringMedicalJudgments] = None
    disposition_kind: Optional[MonitoringRiskDispositionKind] = None


class WorkbenchModuleInboxSummary(WorkbenchModel):
    module: str
    module_label: str
    open_count: int = 0
    unread_count: int = 0
    blocked_count: int = 0
    handoff_count: int = 0
    needs_action_count: int = 0


class WorkbenchInboxActionRecord(WorkbenchModel):
    record_id: str
    project_id: str
    item_id: str
    action: WorkbenchItemAction
    actor: str = "medical_manager"
    source_version: str
    comment: str = ""
    created_at: datetime


class WorkbenchInboxResult(WorkbenchModel):
    project_id: str
    generated_at: datetime
    total_open_count: int
    unread_count: int
    handoff_count: int
    items: List[WorkbenchItem] = Field(default_factory=list)
    module_summaries: List[WorkbenchModuleInboxSummary] = Field(default_factory=list)


class AiRun(WorkbenchModel):
    ai_run_id: str
    project_id: str
    module: str
    purpose: str
    provider: str
    model_name: str
    ai_gateway_status: str = "not_configured"
    llm_connected: bool = False
    prompt_version: str = ""
    schema_version: str = ""
    output_validation_status: str = "not_validated"
    input_refs: List[str] = Field(default_factory=list)
    output_refs: List[str] = Field(default_factory=list)
    status: str = "completed"
    created_at: datetime


class ModuleManifest(WorkbenchModel):
    module: str
    label: str
    lifecycle_step: Optional[int] = None
    medical_role: str
    implementation_status: str
    route_key: str = ""
    primary_user_role: str = "医学经理"
    source_inputs: List[str] = Field(default_factory=list)
    ai_task_types: List[str] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)
    acceptance_status: str = "not_started"
    visible_in_dashboard: bool = True
    note: str = ""


class ModuleCatalog(WorkbenchModel):
    project_id: str
    generated_at: datetime
    modules: List[ModuleManifest] = Field(default_factory=list)


class AuditEvent(WorkbenchModel):
    audit_id: str
    project_id: str
    actor: str
    action: str
    target_type: str
    target_id: str
    detail: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ApprovalActionResult(WorkbenchModel):
    approval: ApprovalGate
    decision: ApprovalDecisionRecord
    audit_event: AuditEvent
    blockers: List[ApprovalBlocker] = Field(default_factory=list)


NonEmptyContractString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class EligibilityCriterionKind(str, Enum):
    INCLUSION = "inclusion"
    EXCLUSION = "exclusion"


class EligibilityInclusionDecision(str, Enum):
    MET = "met"
    NOT_MET = "not_met"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_APPLICABLE = "not_applicable"
    REQUIRES_INVESTIGATOR_JUDGMENT = "requires_investigator_judgment"


class EligibilityExclusionDecision(str, Enum):
    ABSENT = "absent"
    PRESENT = "present"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_APPLICABLE = "not_applicable"
    REQUIRES_INVESTIGATOR_JUDGMENT = "requires_investigator_judgment"


EligibilityCriterionDecision = Union[
    EligibilityInclusionDecision,
    EligibilityExclusionDecision,
]


class EligibilityReviewAction(str, Enum):
    SAVE_AI_DRAFT = "save_ai_draft"
    ACCEPT_AI_DRAFT = "accept_ai_draft"
    REVISE_DECISION = "revise_decision"
    REQUEST_EVIDENCE = "request_evidence"
    DEFER_REVIEW = "defer_review"
    RESET_AFTER_SOURCE_CHANGE = "reset_after_source_change"


class EligibilityEvidenceProcessingState(str, Enum):
    NOT_STARTED = "not_started"
    QUEUED = "queued"
    RUNNING = "running"
    PARTIAL = "partial"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_VISUAL_QC = "needs_visual_qc"
    NOT_APPLICABLE = "not_applicable"


class EligibilityEvidenceJobKind(str, Enum):
    MEDIA_CLASSIFICATION = "media_classification"
    PDF_TEXT_EXTRACTION = "pdf_text_extraction"
    PDF_PAGE_RENDER = "pdf_page_render"
    OCR = "ocr"
    VLM = "vlm"


class EligibilityEvidenceJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EligibilityVlmMediaClass(str, Enum):
    DOCUMENT_PAGE = "document_page"
    CLINICAL_PHOTO = "clinical_photo"
    DEVICE_SCREEN = "device_screen"
    SPECIMEN_OR_SAMPLE = "specimen_or_sample"
    MIXED_OR_COLLAGE = "mixed_or_collage"
    UNKNOWN = "unknown"


class EligibilityVlmDocumentType(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    MEDICAL_RECORD = "medical_record"
    LABORATORY_REPORT = "laboratory_report"
    PRESCRIPTION_OR_MEDICATION_RECORD = "prescription_or_medication_record"
    IMAGING_REPORT = "imaging_report"
    CONSENT_OR_SIGNATURE_PAGE = "consent_or_signature_page"
    IDENTITY_OR_ADMINISTRATIVE_PAGE = "identity_or_administrative_page"
    UNKNOWN = "unknown"


class EligibilityVlmCaptureQualityOverall(str, Enum):
    ADEQUATE_FOR_HUMAN_QC = "adequate_for_human_qc"
    LIMITED = "limited"
    UNUSABLE = "unusable"


class EligibilityVlmCaptureQualityFlag(str, Enum):
    NONE = "none"
    BLUR = "blur"
    GLARE = "glare"
    UNDEREXPOSED = "underexposed"
    OVEREXPOSED = "overexposed"
    LOW_RESOLUTION = "low_resolution"
    PARTIAL_CROP = "partial_crop"
    OBSTRUCTION = "obstruction"
    PERSPECTIVE_DISTORTION = "perspective_distortion"
    COMPRESSION_ARTIFACT = "compression_artifact"
    ORIENTATION_UNCERTAIN = "orientation_uncertain"
    TEXT_TOO_SMALL = "text_too_small"


class EligibilityVlmOrientation(str, Enum):
    UPRIGHT = "upright"
    ROTATE_90_CLOCKWISE = "rotate_90_clockwise"
    ROTATE_180 = "rotate_180"
    ROTATE_90_COUNTERCLOCKWISE = "rotate_90_counterclockwise"
    UNCERTAIN = "uncertain"
    NOT_APPLICABLE = "not_applicable"


class EligibilityVlmHumanAttention(str, Enum):
    NONE = "none"
    POSSIBLE_IDENTIFIER_VISIBLE = "possible_identifier_visible"
    CAPTURE_QUALITY_LIMITED = "capture_quality_limited"
    ORIENTATION_UNCERTAIN = "orientation_uncertain"
    IMAGE_CONTAINS_INSTRUCTION_LIKE_TEXT = "image_contains_instruction_like_text"
    UNSUPPORTED_CONTENT = "unsupported_content"


class EligibilityVlmGatewayOutcome(str, Enum):
    REJECTED = "rejected"
    DESCRIPTOR_VALID = "descriptor_valid"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    RUNTIME_FAILED = "runtime_failed"


class EligibilityVlmCaptureQuality(WorkbenchModel):
    overall: EligibilityVlmCaptureQualityOverall
    flags: List[EligibilityVlmCaptureQualityFlag]

    @model_validator(mode="after")
    def validate_flags(self) -> "EligibilityVlmCaptureQuality":
        _validate_closed_ordered_array(
            self.flags,
            list(EligibilityVlmCaptureQualityFlag),
            EligibilityVlmCaptureQualityFlag.NONE,
            "capture_quality.flags",
        )
        if self.overall == EligibilityVlmCaptureQualityOverall.ADEQUATE_FOR_HUMAN_QC:
            if self.flags != [EligibilityVlmCaptureQualityFlag.NONE]:
                raise ValueError("adequate capture quality requires only the none flag")
        elif EligibilityVlmCaptureQualityFlag.NONE in self.flags:
            raise ValueError("limited or unusable capture quality requires concrete flags")
        return self


class EligibilityVlmDescriptor(WorkbenchModel):
    schema_version: Literal["eligibility_visual_descriptor_v1"]
    media_class: EligibilityVlmMediaClass
    primary_document_type: EligibilityVlmDocumentType
    capture_quality: EligibilityVlmCaptureQuality
    orientation: EligibilityVlmOrientation
    requires_human_attention: List[EligibilityVlmHumanAttention]

    @model_validator(mode="after")
    def validate_descriptor(self) -> "EligibilityVlmDescriptor":
        _validate_closed_ordered_array(
            self.requires_human_attention,
            list(EligibilityVlmHumanAttention),
            EligibilityVlmHumanAttention.NONE,
            "requires_human_attention",
        )
        is_document = self.media_class == EligibilityVlmMediaClass.DOCUMENT_PAGE
        if is_document:
            if self.primary_document_type == EligibilityVlmDocumentType.NOT_APPLICABLE:
                raise ValueError("document page requires a document type")
            if self.orientation == EligibilityVlmOrientation.NOT_APPLICABLE:
                raise ValueError("document page requires a document orientation")
        else:
            if self.primary_document_type != EligibilityVlmDocumentType.NOT_APPLICABLE:
                raise ValueError("non-document media requires not_applicable document type")
            if self.orientation != EligibilityVlmOrientation.NOT_APPLICABLE:
                raise ValueError("non-document media requires not_applicable orientation")

        flags = set(self.capture_quality.flags)
        attention = set(self.requires_human_attention)
        if self.capture_quality.overall != EligibilityVlmCaptureQualityOverall.ADEQUATE_FOR_HUMAN_QC:
            if EligibilityVlmHumanAttention.CAPTURE_QUALITY_LIMITED not in attention:
                raise ValueError("limited capture quality requires human attention")
        if self.orientation == EligibilityVlmOrientation.UNCERTAIN:
            if (
                EligibilityVlmCaptureQualityFlag.ORIENTATION_UNCERTAIN not in flags
                or EligibilityVlmHumanAttention.ORIENTATION_UNCERTAIN not in attention
            ):
                raise ValueError("uncertain orientation requires matching flags")
        if self.media_class == EligibilityVlmMediaClass.UNKNOWN:
            if EligibilityVlmHumanAttention.UNSUPPORTED_CONTENT not in attention:
                raise ValueError("unknown media requires unsupported-content attention")
        return self


def _validate_closed_ordered_array(
    values: List[Enum],
    allowed_order: List[Enum],
    none_value: Enum,
    field_name: str,
) -> None:
    if not values:
        raise ValueError(f"{field_name} must not be empty")
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} values must be unique")
    if none_value in values and values != [none_value]:
        raise ValueError(f"{field_name} none value cannot coexist")
    order = {value: index for index, value in enumerate(allowed_order)}
    if any(value not in order for value in values):
        raise ValueError(f"{field_name} contains an unsupported value")
    if values != sorted(values, key=order.__getitem__):
        raise ValueError(f"{field_name} values must use canonical order")


class EligibilityEvidenceJobCreateRequest(WorkbenchModel):
    source_id: NonEmptyContractString
    job_kind: EligibilityEvidenceJobKind
    profile_version: NonEmptyContractString
    idempotency_key: NonEmptyContractString
    priority: int = Field(default=0, ge=-100, le=100, strict=True)
    max_attempts: int = Field(default=3, ge=1, le=10, strict=True)


class EligibilityEvidenceJobCancelRequest(WorkbenchModel):
    actor: NonEmptyContractString


class EligibilityEvidenceJob(WorkbenchModel):
    project_id: NonEmptyContractString
    subject_id: NonEmptyContractString
    job_id: NonEmptyContractString
    job_kind: EligibilityEvidenceJobKind
    profile_version: NonEmptyContractString
    source_id: NonEmptyContractString
    source_revision: NonEmptyContractString
    subject_source_revision: NonEmptyContractString
    status: EligibilityEvidenceJobStatus
    priority: int
    attempt_count: int = Field(ge=0, strict=True)
    max_attempts: int = Field(ge=1, strict=True)
    progress_current: int = Field(ge=0, strict=True)
    progress_total: int = Field(ge=0, strict=True)
    error_code: Optional[str] = None
    next_run_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    parent_job_id: Optional[NonEmptyContractString] = None
    page_index: Optional[int] = Field(default=None, ge=1, strict=True)

    @model_validator(mode="after")
    def validate_progress(self) -> "EligibilityEvidenceJob":
        if self.progress_total and self.progress_current > self.progress_total:
            raise ValueError("progress_current cannot exceed progress_total")
        return self


class EligibilityEvidenceJobCreateResult(WorkbenchModel):
    job: EligibilityEvidenceJob
    replayed: bool = False


class EligibilityEvidenceArtifactSummary(WorkbenchModel):
    project_id: NonEmptyContractString
    subject_id: NonEmptyContractString
    job_id: NonEmptyContractString
    artifact_id: NonEmptyContractString
    artifact_kind: NonEmptyContractString
    size_bytes: int = Field(ge=0, strict=True)
    media_type: NonEmptyContractString
    source_id: NonEmptyContractString
    source_revision: NonEmptyContractString
    extraction_revision: NonEmptyContractString
    locator: Dict[str, Any]
    quality_state: NonEmptyContractString
    created_at: datetime


class EligibilityEvidenceVisualQcResult(str, Enum):
    SAMPLED_PASS = "sampled_pass"
    SAMPLED_FAIL = "sampled_fail"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"


class EligibilityEvidenceVisualQcRequest(WorkbenchModel):
    expected_qc_revision: int = Field(ge=0, strict=True)
    expected_source_revision: NonEmptyContractString
    expected_extraction_revision: NonEmptyContractString
    idempotency_key: NonEmptyContractString
    result: EligibilityEvidenceVisualQcResult
    reason_code: NonEmptyContractString
    user_reason: NonEmptyContractString
    sample_plan_id: Optional[NonEmptyContractString] = None
    sample_unit: Optional[Dict[str, Any]] = None
    policy_version: NonEmptyContractString
    actor: NonEmptyContractString

    @model_validator(mode="after")
    def validate_sampling_metadata(self) -> "EligibilityEvidenceVisualQcRequest":
        sampled = self.result in {
            EligibilityEvidenceVisualQcResult.SAMPLED_PASS,
            EligibilityEvidenceVisualQcResult.SAMPLED_FAIL,
        }
        if sampled and (not self.sample_plan_id or not self.sample_unit):
            raise ValueError(
                "sampled visual QC requires sample_plan_id and sample_unit"
            )
        return self


class EligibilityEvidenceVisualQcResponse(WorkbenchModel):
    request_id: NonEmptyContractString
    qc_record_id: NonEmptyContractString
    project_id: NonEmptyContractString
    subject_id: NonEmptyContractString
    evidence_id: NonEmptyContractString
    source_revision: NonEmptyContractString
    extraction_revision: NonEmptyContractString
    qc_revision: int = Field(ge=1, strict=True)
    result: EligibilityEvidenceVisualQcResult
    actor: NonEmptyContractString
    identity_assurance: Literal["unverified_client_claim"]
    is_electronic_signature: Literal[False] = False
    replayed: bool = False


class EligibilitySubjectAggregateStatus(str, Enum):
    BLOCKED_BY_INCOMPLETE_REVIEW = "blocked_by_incomplete_review"
    BLOCKED_BY_MISSING_RULES = "blocked_by_missing_rules"
    HAS_GAPS = "has_gaps"
    HAS_INVESTIGATOR_JUDGMENT = "has_investigator_judgment"
    HAS_INCLUSION_FAILURE = "has_inclusion_failure"
    HAS_EXCLUSION = "has_exclusion"
    MEDICAL_REVIEW_PENDING = "medical_review_pending"


def _decision_enum_for_kind(
    criterion_kind: object,
) -> type[EligibilityInclusionDecision] | type[EligibilityExclusionDecision]:
    kind = (
        criterion_kind.value
        if isinstance(criterion_kind, EligibilityCriterionKind)
        else criterion_kind
    )
    if kind == EligibilityCriterionKind.INCLUSION.value:
        return EligibilityInclusionDecision
    if kind == EligibilityCriterionKind.EXCLUSION.value:
        return EligibilityExclusionDecision
    raise ValueError("criterion_kind must be inclusion or exclusion")


def _coerce_decisions_for_kind(
    payload: object,
    *field_names: str,
) -> object:
    if not isinstance(payload, dict):
        return payload
    values = dict(payload)
    decision_enum = _decision_enum_for_kind(values.get("criterion_kind"))
    for field_name in field_names:
        decision = values.get(field_name)
        if decision is None:
            continue
        raw_decision = decision.value if isinstance(decision, Enum) else decision
        try:
            values[field_name] = decision_enum(raw_decision)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{field_name} is invalid for {values.get('criterion_kind')} criterion"
            ) from exc
    return values


class EligibilityReviewActionRequest(WorkbenchModel):
    criterion_kind: EligibilityCriterionKind
    expected_state_revision: int = Field(ge=0, strict=True)
    expected_rule_revision: NonEmptyContractString
    expected_subject_source_revision: NonEmptyContractString
    idempotency_key: NonEmptyContractString
    actor: NonEmptyContractString
    action: EligibilityReviewAction
    decision: Optional[EligibilityCriterionDecision] = None
    reason: NonEmptyContractString
    evidence_ids: List[NonEmptyContractString] = Field(default_factory=list)
    evidence_processing_state: EligibilityEvidenceProcessingState = (
        EligibilityEvidenceProcessingState.NOT_STARTED
    )

    @model_validator(mode="before")
    @classmethod
    def validate_decision_kind(cls, payload: object) -> object:
        return _coerce_decisions_for_kind(payload, "decision")

    @model_validator(mode="after")
    def validate_action_payload(self) -> "EligibilityReviewActionRequest":
        decision_actions = {
            EligibilityReviewAction.SAVE_AI_DRAFT,
            EligibilityReviewAction.REVISE_DECISION,
        }
        if self.action in decision_actions and self.decision is None:
            raise ValueError(f"{self.action.value} requires a decision")
        if self.action not in decision_actions and self.decision is not None:
            raise ValueError(f"{self.action.value} cannot carry a decision")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("evidence_ids must be unique")
        decisive_values = {
            EligibilityInclusionDecision.MET,
            EligibilityInclusionDecision.NOT_MET,
            EligibilityExclusionDecision.ABSENT,
            EligibilityExclusionDecision.PRESENT,
        }
        if self.decision in decisive_values and not self.evidence_ids:
            raise ValueError("decisive eligibility review requires evidence_ids")
        if (
            self.action == EligibilityReviewAction.ACCEPT_AI_DRAFT
            and not self.evidence_ids
        ):
            raise ValueError("accept_ai_draft requires evidence_ids")
        if (
            self.action == EligibilityReviewAction.RESET_AFTER_SOURCE_CHANGE
            and self.evidence_ids
        ):
            raise ValueError(
                "reset_after_source_change cannot carry evidence_ids"
            )
        return self


class EligibilityReviewState(WorkbenchModel):
    project_id: NonEmptyContractString
    subject_id: NonEmptyContractString
    criterion_uid: NonEmptyContractString
    criterion_kind: EligibilityCriterionKind
    rule_revision: NonEmptyContractString
    subject_source_revision: NonEmptyContractString
    state_revision: int = Field(ge=1, strict=True)
    evidence_processing_state: EligibilityEvidenceProcessingState
    ai_draft_decision: Optional[EligibilityCriterionDecision] = None
    medical_decision: Optional[EligibilityCriterionDecision] = None
    latest_action: EligibilityReviewAction
    reason: NonEmptyContractString
    evidence_ids: List[NonEmptyContractString] = Field(default_factory=list)
    ai_draft_record_id: Optional[str] = None
    medical_record_id: Optional[str] = None
    latest_record_id: NonEmptyContractString
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def validate_decision_kinds(cls, payload: object) -> object:
        return _coerce_decisions_for_kind(
            payload,
            "ai_draft_decision",
            "medical_decision",
        )

    @model_validator(mode="after")
    def validate_state(self) -> "EligibilityReviewState":
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("evidence_ids must be unique")
        return self


class EligibilityReviewActionResult(WorkbenchModel):
    request_id: NonEmptyContractString
    record_id: NonEmptyContractString
    state_revision: int = Field(ge=1, strict=True)
    replayed: bool = False
    state: EligibilityReviewState


class EligibilitySubjectAggregate(WorkbenchModel):
    project_id: NonEmptyContractString
    subject_id: NonEmptyContractString
    rule_revision: str
    criterion_count: int = Field(ge=0, strict=True)
    reviewed_count: int = Field(ge=0, strict=True)
    statuses: List[EligibilitySubjectAggregateStatus]

    @model_validator(mode="after")
    def validate_counts_and_statuses(self) -> "EligibilitySubjectAggregate":
        if self.reviewed_count > self.criterion_count:
            raise ValueError("reviewed_count cannot exceed criterion_count")
        if len(self.statuses) != len(set(self.statuses)):
            raise ValueError("statuses must be unique")
        if not self.statuses:
            raise ValueError("statuses must not be empty")
        missing_rules = EligibilitySubjectAggregateStatus.BLOCKED_BY_MISSING_RULES
        medical_review_pending = (
            EligibilitySubjectAggregateStatus.MEDICAL_REVIEW_PENDING
        )
        if self.criterion_count == 0:
            if self.rule_revision or self.statuses != [missing_rules]:
                raise ValueError(
                    "zero criteria requires only blocked_by_missing_rules status"
                )
        elif not self.rule_revision.strip():
            raise ValueError("rule_revision is required when criteria exist")
        elif missing_rules in self.statuses:
            raise ValueError(
                "blocked_by_missing_rules requires zero criteria"
            )
        if medical_review_pending in self.statuses and self.statuses != [
            medical_review_pending
        ]:
            raise ValueError("medical_review_pending cannot be combined with blockers")
        return self


class EligibilityRuleType(str, Enum):
    INCLUSION = "inclusion"
    EXCLUSION = "exclusion"


class EligibilityRuleVerdict(str, Enum):
    PASS = "pass"
    PASS_VERIFY = "pass_verify"
    FAIL = "fail"
    INSUFFICIENT = "insufficient"
    INVESTIGATOR = "investigator"
    NA = "na"
    NEEDS_EVIDENCE = "needs_evidence"
    NOT_REVIEWED = "not_reviewed"
    PARSE_ERROR = "parse_error"


class EligibilityCandidateStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    REVIEWED = "reviewed"
    ERROR = "error"
    READY_FOR_REVIEW = "ready_for_review"
    ACTION_REQUIRED = "action_required"
    AWAITING_SITE_RESPONSE = "awaiting_site_response"
    READY_FOR_RANDOMIZATION = "ready_for_randomization"
    SCREEN_FAILED = "screen_failed"


class EligibilityOverallConclusion(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INSUFFICIENT = "insufficient"
    INVESTIGATOR = "investigator"
    NEEDS_EVIDENCE = "needs_evidence"
    NOT_REVIEWED = "not_reviewed"
    ELIGIBLE = "eligible"
    NOT_ELIGIBLE = "not_eligible"
    PENDING_INFORMATION = "pending_information"
    MEDICAL_REVIEW_REQUIRED = "medical_review_required"


class EligibilityEvidence(WorkbenchModel):
    evidence_id: str
    rule_id: str = Field(pattern=r"^(IN|EX)-\d{2}[A-Za-z0-9_.-]*$")
    source_type: str
    source_title: str
    source_domain: str = ""
    source_record_id: str = Field(default="", exclude=True)
    evidence_span_id: Optional[str] = None
    field_path: str = ""
    quote: str = ""
    normalized_value: str = ""
    collected_at: Optional[datetime] = None
    confidence: float = 1.0


class EligibilityActionItem(WorkbenchModel):
    item_id: str
    rule_id: str = Field(pattern=r"^(IN|EX)-\d{2}[A-Za-z0-9_.-]*$")
    item_type: str
    severity: RiskSeverity = RiskSeverity.MEDIUM
    title: str
    detail: str
    owner: str = "medical_manager"
    status: str = "open"
    due_date: Optional[str] = None
    recommended_action: str = ""


class EligibilityRuleReview(WorkbenchModel):
    rule_id: str = Field(pattern=r"^(IN|EX)-\d{2}[A-Za-z0-9_.-]*$")
    rule_type: EligibilityRuleType
    rule_label: str
    criterion_text: str
    verdict: EligibilityRuleVerdict
    verdict_label: str
    severity: RiskSeverity = RiskSeverity.LOW
    rationale: str
    evidence: List[EligibilityEvidence] = Field(default_factory=list)
    missing_information: List[EligibilityActionItem] = Field(default_factory=list)
    medical_confirmation: List[EligibilityActionItem] = Field(default_factory=list)
    reviewed_by: str = "system"
    reviewed_at: datetime
    source_phase_id: str = ""
    source_phase_label: str = ""
    source_report_path: str = Field(default="", exclude=True)
    source_raw_path: str = Field(default="", exclude=True)
    verification_type: str = ""


class EligibilityCandidate(WorkbenchModel):
    candidate_id: str
    project_id: str
    subject_id: str
    site_id: str
    screening_number: str
    source_system: str = "workbench"
    source_project_code: str = ""
    source_path: str = Field(default="", exclude=True)
    study_stage: str = ""
    active_phase_id: str = ""
    active_phase_label: str = ""
    document_count: int = 0
    phase_reviews: List[Dict[str, Any]] = Field(default_factory=list)
    status: EligibilityCandidateStatus
    overall_conclusion: EligibilityOverallConclusion
    overall_rationale: str
    review_priority: RiskSeverity
    age: Optional[int] = None
    sex: str = ""
    screening_visit_date: str
    randomization_target_date: Optional[str] = None
    key_findings: List[str] = Field(default_factory=list)
    rule_reviews: List[EligibilityRuleReview] = Field(default_factory=list)
    missing_information: List[EligibilityActionItem] = Field(default_factory=list)
    medical_confirmation_items: List[EligibilityActionItem] = Field(default_factory=list)
    audit_event_ids: List[str] = Field(default_factory=list)


class EligibilityReviewPhase(WorkbenchModel):
    phase_id: str
    name: str
    stage: str = ""
    study_stage: str = ""
    visit: str = ""
    study_week: str = ""
    day_window: str = ""
    description: str = ""
    required_items: List[str] = Field(default_factory=list)
    included_document_phases: List[str] = Field(default_factory=list)


class EligibilitySubjectPhaseReview(WorkbenchModel):
    phase_id: str
    name: str
    visit: str = ""
    day_window: str = ""
    status: str = "not_reviewed"
    verdict: str = ""
    summary: str = ""
    has_report: bool = False
    has_raw_response: bool = False
    evidence_bundle_exists: bool = False
    report_path: str = Field(default="", exclude=True)
    raw_response_path: str = Field(default="", exclude=True)
    evidence_bundle_path: str = Field(default="", exclude=True)
    updated_at: str = ""


class EligibilitySubjectRow(WorkbenchModel):
    subject_id: str
    project_code: str
    center_code: str = ""
    center_name: str = ""
    status: str = ""
    overall_verdict: str = ""
    doc_count: int = 0
    last_updated: str = ""
    icf_date: str = ""
    first_dosing_date: str = ""
    birth_date: str = ""
    phase_reviews: Dict[str, EligibilitySubjectPhaseReview] = Field(default_factory=dict)
    evidence_bundle_exists: bool = False
    report_exists: bool = False
    can_open_report: bool = False


class EligibilityRuleDefinition(WorkbenchModel):
    rule_id: str = Field(pattern=r"^(IN|EX)-\d{2}[A-Za-z0-9_.-]*$")
    rule_type: EligibilityRuleType
    rule_label: str
    criterion_text: str
    source_path: str = Field(default="", exclude=True)


class EligibilityPoolSummary(WorkbenchModel):
    total_candidates: int
    counts_by_status: Dict[str, int]
    counts_by_overall_conclusion: Dict[str, int]
    rules_with_findings: List[str] = Field(default_factory=list)
    open_missing_information_count: int = 0
    open_medical_confirmation_count: int = 0


class EligibilityTaskEntry(WorkbenchModel):
    module: str = "eligibility_review"
    module_label: str = "入排审核"
    source_system: str = "enrollment-review-app"
    source_project_code: str
    default_phase_id: str = ""
    selected_subject_id: str = ""
    selected_phase_id: str = ""
    source_project_path: str = Field(default="", exclude=True)


class EligibilityProjectStats(WorkbenchModel):
    total_subjects: int
    counts_by_status: Dict[str, int] = Field(default_factory=dict)
    counts_by_overall_verdict: Dict[str, int] = Field(default_factory=dict)
    counts_by_phase_status: Dict[str, int] = Field(default_factory=dict)
    subjects_with_reports: int = 0
    subjects_with_evidence_bundles: int = 0
    criteria_rule_count: int = 0


class EligibilityAuditSummary(WorkbenchModel):
    audit_ledger_path: str = Field(default="", exclude=True)
    event_count: int = 0
    recent_events: List[Dict[str, Any]] = Field(default_factory=list)


class EligibilityAvailableAction(WorkbenchModel):
    action_id: str
    label: str
    target_type: str
    target_id: str = ""
    enabled: bool = True
    reason: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EligibilityReviewDataset(WorkbenchModel):
    project_id: str
    module: str = "eligibility_review"
    module_label: str = "入排审核"
    source_system: str = "enrollment-review-app"
    source_project_code: str = ""
    source_path: str = Field(default="", exclude=True)
    protocol_id: str
    protocol_version: str
    source_batch_id: str = ""
    study_stage: str = ""
    active_phase_id: str = ""
    task_entry: Optional[EligibilityTaskEntry] = None
    project_stats: Optional[EligibilityProjectStats] = None
    review_phases: List[EligibilityReviewPhase] = Field(default_factory=list)
    subject_rows: List[EligibilitySubjectRow] = Field(default_factory=list)
    criteria_rules: List[EligibilityRuleDefinition] = Field(default_factory=list)
    criteria_rule_ids: List[str] = Field(default_factory=list)
    generated_at: datetime
    summary: EligibilityPoolSummary
    candidates: List[EligibilityCandidate] = Field(default_factory=list)
    selected_candidate: Optional[EligibilityCandidate] = None
    audit_events: List[AuditEvent] = Field(default_factory=list)
    audit_summary: Optional[EligibilityAuditSummary] = None
    available_actions: List[EligibilityAvailableAction] = Field(default_factory=list)


def _validate_section_drafting_readiness(model):
    model.drafting_blocker_code = model.drafting_blocker_code.strip()
    model.drafting_blocker_reason = model.drafting_blocker_reason.strip()
    model.drafting_missing_inputs = [
        item.strip() for item in model.drafting_missing_inputs
    ]
    model.drafting_resolution_actions = [
        item.strip() for item in model.drafting_resolution_actions
    ]
    for label, items in (
        ("drafting missing inputs", model.drafting_missing_inputs),
        ("drafting resolution actions", model.drafting_resolution_actions),
    ):
        if any(not item for item in items):
            raise ValueError(f"{label} must not contain blank values")
        if len(items) != len(set(items)):
            raise ValueError(f"{label} must be unique")
    blocker_fields_present = bool(
        model.drafting_blocker_code
        or model.drafting_blocker_reason
        or model.drafting_missing_inputs
        or model.drafting_resolution_actions
    )
    if model.drafting_status == "actionable_blocker":
        if not (
            model.drafting_blocker_code
            and model.drafting_blocker_reason
            and model.drafting_missing_inputs
            and model.drafting_resolution_actions
        ):
            raise ValueError(
                "actionable drafting blocker requires code, reason, missing "
                "inputs, and resolution actions"
            )
        if str(getattr(model, "initial_text", "") or "").strip():
            raise ValueError(
                "actionable drafting blocker must not contain initial body text"
            )
        if getattr(model, "initial_data", None):
            raise ValueError(
                "actionable drafting blocker must not contain initial structured data"
            )
        for block in getattr(model, "content_blocks", []) or []:
            if block.get("block_type") == "heading":
                continue
            if str(block.get("style_id") or "").startswith("greenfield_heading"):
                continue
            if str(block.get("text") or "").strip():
                raise ValueError(
                    "actionable drafting blocker must not contain substantive body text"
                )
            if block.get("block_type") in {
                "table",
                "figure",
                "image",
                "document_object",
            }:
                raise ValueError(
                    "actionable drafting blocker must not contain substantive body objects"
                )
    elif blocker_fields_present:
        raise ValueError(
            "drafting blocker details require actionable_blocker status"
        )
    if (
        model.drafting_status == "substantive_draft"
        and hasattr(model, "initial_text")
        and not str(model.initial_text or "").strip()
    ):
        raise ValueError("substantive drafting seed requires initial body text")
    expected_completion = {
        "actionable_blocker": "blocked_missing_inputs",
        "structural_content": "structure_ready",
        "structural_container": "structure_ready",
        "not_applicable": "not_applicable",
    }.get(model.drafting_status)
    if (
        expected_completion
        and hasattr(model, "completion_status")
        and model.completion_status != expected_completion
    ):
        raise ValueError(
            f"{model.drafting_status} requires completion_status="
            f"{expected_completion}"
        )
    return model


class ProtocolSection(WorkbenchModel):
    section_id: str
    document_id: str
    parent_id: Optional[str] = None
    heading: str
    ich_m11_anchor: str = ""
    completion_status: str = "not_started"
    approval_state: ApprovalState = ApprovalState.AI_DRAFT
    evidence_coverage: float = 0.0
    risk_count: int = 0
    content_blocks: List[Dict[str, Any]] = Field(default_factory=list)
    template_node_id: str = ""
    section_number: str = ""
    node_kind: str = "section"
    applicability_mode: str = "required"
    applicability_status: Literal[
        "applicable",
        "not_applicable",
        "unknown",
        "deferred",
    ] = "applicable"
    applicability_render_action: Literal[
        "retain_full",
        "omit",
        "retain_not_applicable",
        "retain_placeholder",
    ] = "retain_full"
    applicability_rationale: str = ""
    repeatable: bool = False
    title_locked: bool = False
    interaction_types: List[str] = Field(default_factory=list)
    drafting_status: Literal[
        "unclassified",
        "substantive_draft",
        "structural_content",
        "structural_container",
        "actionable_blocker",
        "not_applicable",
    ] = "unclassified"
    drafting_blocker_code: str = ""
    drafting_blocker_reason: str = ""
    drafting_missing_inputs: List[str] = Field(default_factory=list)
    drafting_resolution_actions: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_protocol_section_drafting_readiness(self):
        return _validate_section_drafting_readiness(self)


class StructuredTableDomain(str, Enum):
    GENERIC = "generic"
    SCHEDULE_OF_ACTIVITIES = "schedule_of_activities"
    OBJECTIVES_ENDPOINTS = "objectives_endpoints"
    SAMPLE_SIZE_ASSUMPTIONS = "sample_size_assumptions"
    TREATMENT_DOSE = "treatment_dose"
    DOSE_MODIFICATION = "dose_modification"
    STOPPING_RULES = "stopping_rules"
    AE_MANAGEMENT = "ae_management"
    LABORATORY_PANEL = "laboratory_panel"
    PK_IMMUNOGENICITY_SCHEDULE = "pk_immunogenicity_schedule"
    ANALYSIS_SETS = "analysis_sets"
    VERSION_HISTORY = "version_history"


class StructuredTableRole(str, Enum):
    UNCLASSIFIED = "unclassified"
    LAYOUT = "layout"
    PROTOCOL_SYNOPSIS = "protocol_synopsis"
    BODY_CONTENT = "body_content"
    DOCUMENT_CONTROL = "document_control"


class StructuredTableNoteType(str, Enum):
    ITEM_SET = "item_set"
    TIMING_RULE = "timing_rule"
    CONDITION = "condition"
    SPECIMEN_PREPARATION = "specimen_preparation"
    DEFINITION = "definition"
    EXCEPTION = "exception"
    OPERATIONAL = "operational"


class StructuredTableColumn(WorkbenchModel):
    column_id: str
    order: int = Field(ge=0)
    label: str = ""
    style_role: str = "body"
    width_twips: Optional[int] = Field(default=None, ge=1)
    source_locator: str = ""
    semantic_role: str = ""


class StructuredTableCell(WorkbenchModel):
    cell_id: str
    row_id: str
    column_id: str
    text: str = ""
    rich_text: Optional[Dict[str, Any]] = None
    semantic_value: Optional[Any] = None
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)
    style_role: str = "body"
    source_locator: str = ""
    provenance_lineage: List[str] = Field(default_factory=list)
    note_refs: List[str] = Field(default_factory=list)
    condition_expression: str = ""


class StructuredTableRow(WorkbenchModel):
    row_id: str
    order: int = Field(ge=0)
    label: str = ""
    style_role: str = "body"
    source_locator: str = ""
    cells: List[StructuredTableCell] = Field(default_factory=list)


class StructuredTableNote(WorkbenchModel):
    note_id: str
    marker: str = ""
    note_type: StructuredTableNoteType
    text: str
    target_ids: List[str] = Field(default_factory=list)
    module_ref: str = ""
    project_override: bool = False
    source_refs: List[str] = Field(default_factory=list)
    source_kind: str = ""
    marker_source_locator: str = ""
    review_status: str = "confirmed"
    association_reason: str = ""


class StructuredTable(WorkbenchModel):
    schema_version: str = "structured_table_v1"
    table_id: str
    block_id: str
    domain: StructuredTableDomain = StructuredTableDomain.GENERIC
    role: StructuredTableRole = StructuredTableRole.UNCLASSIFIED
    title: str = ""
    source_locator: str = ""
    version: int = Field(default=0, ge=0)
    review_state: ApprovalState = ApprovalState.AI_DRAFT
    header_row_count: int = Field(default=0, ge=0)
    columns: List[StructuredTableColumn] = Field(default_factory=list)
    rows: List[StructuredTableRow] = Field(default_factory=list)
    notes: List[StructuredTableNote] = Field(default_factory=list)
    word_layout: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_identity_and_references(self) -> "StructuredTable":
        def require_unique(values: List[str], label: str) -> None:
            if not all(values) or len(values) != len(set(values)):
                raise ValueError(f"{label} must be present and unique")

        column_ids = [column.column_id for column in self.columns]
        row_ids = [row.row_id for row in self.rows]
        cell_ids = [cell.cell_id for row in self.rows for cell in row.cells]
        note_ids = [note.note_id for note in self.notes]
        require_unique(column_ids, "structured table column ids")
        require_unique(row_ids, "structured table row ids")
        require_unique(cell_ids, "structured table cell ids")
        require_unique(note_ids, "structured table note ids")
        if self.header_row_count > len(self.rows):
            raise ValueError("structured table header row count exceeds row count")
        column_id_set = set(column_ids)
        row_id_set = set(row_ids)
        note_id_set = set(note_ids)
        for row in self.rows:
            for cell in row.cells:
                if cell.row_id != row.row_id:
                    raise ValueError("structured table cell row reference is inconsistent")
                if cell.column_id not in column_id_set:
                    raise ValueError("structured table cell references an unknown column")
                if not set(cell.note_refs).issubset(note_id_set):
                    raise ValueError("structured table cell references an unknown note")
        target_ids = {self.table_id, self.block_id, *row_id_set, *column_id_set, *cell_ids}
        for note in self.notes:
            if not note.target_ids or not set(note.target_ids).issubset(target_ids):
                raise ValueError("structured table note has an unknown or empty target")
        return self


class SoaEpoch(WorkbenchModel):
    epoch_id: str
    order: int = Field(ge=0)
    label: str
    source_locator: str = ""


class SoaVisit(WorkbenchModel):
    visit_id: str
    epoch_id: str
    order: int = Field(ge=0)
    label: str
    visit_type: str
    nominal_day: Optional[int] = None
    nominal_week: Optional[float] = None
    cycle_number: Optional[int] = Field(default=None, ge=1)
    cycle_day: Optional[int] = Field(default=None, ge=1)
    reference_anchor: str = ""
    window_before_days: Optional[int] = Field(default=None, ge=0)
    window_after_days: Optional[int] = Field(default=None, ge=0)
    delivery_mode: str = "onsite"
    condition_expression: str = ""
    source_locator: str = ""


class SoaActivity(WorkbenchModel):
    activity_id: str
    order: int = Field(ge=0)
    label: str
    domain: str
    parent_activity_id: Optional[str] = None
    definition: str = ""
    responsibility_role: str = ""
    module_ref: str = ""
    project_override: bool = False
    source_locator: str = ""


class SoaCellPlan(WorkbenchModel):
    cell_id: str
    activity_id: str
    visit_id: str
    execution_state: Literal["planned", "conditional", "not_planned", "not_applicable"]
    relative_timing: str = ""
    repeat_count: Optional[int] = Field(default=None, ge=1)
    condition_expression: str = ""
    note_refs: List[str] = Field(default_factory=list)


class ScheduleOfActivitiesDefinition(WorkbenchModel):
    table_id: str
    epochs: List[SoaEpoch] = Field(default_factory=list)
    visits: List[SoaVisit] = Field(default_factory=list)
    activities: List[SoaActivity] = Field(default_factory=list)
    cells: List[SoaCellPlan] = Field(default_factory=list)
    notes: List[StructuredTableNote] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_schedule_references(self) -> "ScheduleOfActivitiesDefinition":
        def require_unique(values: List[str], label: str) -> set[str]:
            if not all(values) or len(values) != len(set(values)):
                raise ValueError(f"{label} must be present and unique")
            return set(values)

        epoch_ids = require_unique(
            [epoch.epoch_id for epoch in self.epochs], "SoA epoch ids"
        )
        visit_ids = require_unique(
            [visit.visit_id for visit in self.visits], "SoA visit ids"
        )
        activity_ids = require_unique(
            [activity.activity_id for activity in self.activities], "SoA activity ids"
        )
        cell_ids = require_unique(
            [cell.cell_id for cell in self.cells], "SoA cell ids"
        )
        note_ids = require_unique(
            [note.note_id for note in self.notes], "SoA note ids"
        )
        if any(visit.epoch_id not in epoch_ids for visit in self.visits):
            raise ValueError("SoA visit references an unknown epoch")
        if any(
            activity.parent_activity_id and activity.parent_activity_id not in activity_ids
            for activity in self.activities
        ):
            raise ValueError("SoA activity references an unknown parent")
        seen_pairs: set[tuple[str, str]] = set()
        for cell in self.cells:
            if cell.visit_id not in visit_ids or cell.activity_id not in activity_ids:
                raise ValueError("SoA cell references an unknown visit or activity")
            pair = (cell.activity_id, cell.visit_id)
            if pair in seen_pairs:
                raise ValueError("SoA activity and visit pair must be unique")
            seen_pairs.add(pair)
            if not set(cell.note_refs).issubset(note_ids):
                raise ValueError("SoA cell references an unknown note")
        note_targets = {
            self.table_id,
            *epoch_ids,
            *visit_ids,
            *activity_ids,
            *cell_ids,
        }
        for note in self.notes:
            if not note.target_ids or not set(note.target_ids).issubset(note_targets):
                raise ValueError("SoA note has an unknown or empty target")
        return self


class ProtocolDocument(WorkbenchModel):
    document_id: str
    project_id: str
    document_type: str = "clinical_study_protocol"
    template_version: str = "protocol_template_v0_1"
    protocol_id: str
    version: str
    status: str = "draft"
    sections: List[ProtocolSection] = Field(default_factory=list)
    quality_gates: List[Dict[str, Any]] = Field(default_factory=list)
    template_id: str = ""
    template_definition_sha256: str = ""
    template_language: str = "zh-CN"
    template_country: str = "CN"
    style_profile_id: str = ""
    style_profile_version: str = ""
    style_profile_definition_sha256: str = ""
    corpus_snapshot_id: str = ""
    corpus_snapshot_version: str = ""
    corpus_snapshot_sha256: str = ""
    source_study_definition_id: str = ""
    source_study_definition_revision: Optional[int] = Field(default=None, ge=1)
    source_study_definition_sha256: str = ""
    module_resolutions: List["MedicalWritingProtocolModuleResolution"] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def validate_study_definition_binding(self):
        self.source_study_definition_id = self.source_study_definition_id.strip()
        self.source_study_definition_sha256 = self.source_study_definition_sha256.strip()
        binding = (
            bool(self.source_study_definition_id),
            self.source_study_definition_revision is not None,
            bool(self.source_study_definition_sha256),
        )
        if any(binding) and not all(binding):
            raise ValueError(
                "protocol document study-definition id, revision, and hash must be provided together"
            )
        if self.source_study_definition_sha256 and (
            len(self.source_study_definition_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.source_study_definition_sha256
            )
        ):
            raise ValueError("protocol document study-definition hash must be lowercase SHA-256")
        return self


class MedicalWritingPreviewBlock(WorkbenchModel):
    """One source-bound block locator in the deterministic fast preview."""

    block_id: str = Field(min_length=1, max_length=200)
    section_id: str = Field(min_length=1, max_length=200)
    block_type: str = Field(min_length=1, max_length=80)
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    estimated_lines: int = Field(ge=1)
    text_preview: str = Field(default="", max_length=600)
    layout_note: str = Field(default="", max_length=240)

    @model_validator(mode="after")
    def validate_page_range(self):
        if self.page_end < self.page_start:
            raise ValueError("preview block page range must be ordered")
        return self


class MedicalWritingPreviewPage(WorkbenchModel):
    """A page-sized source map; dimensions are the style-profile estimate."""

    page_number: int = Field(ge=1)
    orientation: Literal["portrait", "landscape"]
    width_twips: int = Field(gt=0)
    height_twips: int = Field(gt=0)
    # A single estimated page can legitimately contain many short protocol
    # headings/blocks (for example, a generated greenfield protocol's TOC and
    # front matter).  Keep a bounded payload, but do not reject ordinary
    # full-protocol previews merely because they exceed the former 100/200
    # locator limits.
    section_ids: List[str] = Field(default_factory=list, max_length=512)
    block_ids: List[str] = Field(default_factory=list, max_length=1024)
    estimated: bool = True
    layout_note: str = Field(default="", max_length=240)


def medical_writing_word_verification_manifest_sha256(
    page_evidence: List["MedicalWritingWordVerificationPage"],
    *,
    pdf_sha256: str,
) -> str:
    payload = {
        "pdf_sha256": pdf_sha256,
        "page_evidence": [item.model_dump(mode="json") for item in page_evidence],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


class MedicalWritingWordVerificationPage(WorkbenchModel):
    """Immutable evidence locator for one page of a Word/PDF verification."""

    page_number: int = Field(ge=1)
    orientation: Literal["portrait", "landscape"]
    width_twips: int = Field(gt=0)
    height_twips: int = Field(gt=0)
    pdf_page_sha256: str = Field(min_length=64, max_length=64)
    screenshot_sha256: str = ""
    visual_qc_status: Literal["pass", "pass_with_notes"] = "pass"
    note: str = Field(default="", max_length=240)

    @model_validator(mode="after")
    def validate_page_evidence_hashes(self):
        for field_name in ("pdf_page_sha256", "screenshot_sha256"):
            value = getattr(self, field_name)
            if value and not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError(f"{field_name} must be lowercase SHA-256")
        if not self.pdf_page_sha256:
            raise ValueError("Word verification page evidence requires a PDF hash")
        return self


class MedicalWritingWordVerificationReceipt(WorkbenchModel):
    """Auditable, source-bound evidence needed to claim Word verification."""

    schema_version: str = "medical_writing_word_verification_v1"
    verification_id: str = Field(min_length=1, max_length=200)
    project_id: str = Field(min_length=1, max_length=200)
    document_id: str = Field(min_length=1, max_length=200)
    source_snapshot_sha256: str = Field(min_length=64, max_length=64)
    docx_sha256: str = Field(min_length=64, max_length=64)
    pdf_sha256: str = Field(min_length=64, max_length=64)
    page_count: int = Field(ge=1)
    page_evidence: List[MedicalWritingWordVerificationPage] = Field(min_length=1)
    evidence_manifest_sha256: str = Field(min_length=64, max_length=64)
    verifier_id: str = Field(min_length=1, max_length=120)
    verifier_role: str = Field(min_length=1, max_length=120)
    verification_tool: Literal["microsoft_word"] = "microsoft_word"
    verification_tool_version: str = Field(min_length=1, max_length=120)
    workflow: Literal["open_update_fields_save_reopen_export_pdf"] = (
        "open_update_fields_save_reopen_export_pdf"
    )
    verified_at: datetime
    idempotency_key: str = Field(min_length=8, max_length=200)
    status: Literal["word_verified"] = "word_verified"

    @model_validator(mode="after")
    def validate_receipt_integrity(self):
        for field_name in (
            "source_snapshot_sha256",
            "docx_sha256",
            "pdf_sha256",
            "evidence_manifest_sha256",
        ):
            if not re.fullmatch(r"[0-9a-f]{64}", getattr(self, field_name)):
                raise ValueError(f"{field_name} must be lowercase SHA-256")
        if self.page_count != len(self.page_evidence):
            raise ValueError("Word verification page_count must match page_evidence")
        expected_pages = list(range(1, self.page_count + 1))
        if [item.page_number for item in self.page_evidence] != expected_pages:
            raise ValueError("Word verification pages must be contiguous and ordered")
        expected_manifest = medical_writing_word_verification_manifest_sha256(
            self.page_evidence,
            pdf_sha256=self.pdf_sha256,
        )
        if self.evidence_manifest_sha256 != expected_manifest:
            raise ValueError("Word verification evidence manifest does not match pages")
        if self.verified_at.tzinfo is None:
            raise ValueError("Word verification timestamp must include a timezone")
        return self


class MedicalWritingWordVerificationSubmitRequest(WorkbenchModel):
    """Controlled API input linking a receipt to one stored DOCX artifact."""

    export_job_id: str = Field(min_length=1, max_length=200)
    receipt: MedicalWritingWordVerificationReceipt
    actor: str = Field(min_length=2, max_length=120)
    # The external Word/PDF producer supplies the PDF bytes only for this
    # verification request. The API computes canonical PDFium page hashes and
    # never persists this base64 payload. Historical request payloads can still
    # be parsed, but the controlled submission route fails closed when absent.
    canonical_pdf_base64: str = Field(default="", max_length=70_000_000)


class MedicalWritingDocumentPreview(WorkbenchModel):
    """Explicit preview truth boundary shared with DOCX export identity."""

    schema_version: str = "medical_writing_fast_preview_v2"
    project_id: str = Field(min_length=1, max_length=200)
    document_id: str = Field(min_length=1, max_length=200)
    mode: Literal["draft_preview", "approved_final"] = "draft_preview"
    preview_status: Literal["fast_preview", "word_verified", "stale"] = "fast_preview"
    snapshot_sha256: str = Field(min_length=64, max_length=64)
    word_verified_snapshot_sha256: str = ""
    style_profile_id: str = ""
    style_profile_version: str = ""
    # The displayed page count is only comparable to a Word page count when
    # it is backed by an exact Word/PDF receipt for the same immutable snapshot.
    page_count_basis: Literal[
        "style_profile_estimate", "microsoft_word_receipt"
    ] = "style_profile_estimate"
    page_count: int = Field(ge=1)
    pages: List[MedicalWritingPreviewPage] = Field(min_length=1)
    blocks: List[MedicalWritingPreviewBlock] = Field(default_factory=list)
    warning: str = (
        "当前页数是 StyleProfile 快速估算，不等同于 DOCX/ Microsoft Word 原生页数；"
        "封面、目录/索引、域更新、分页、表格跨页和版式节均可能造成差异。"
        "需要申报级页数与最终版式时，必须对同一快照执行 Word verification。"
    )

    @model_validator(mode="after")
    def validate_preview_identity(self):
        if not re.fullmatch(r"[0-9a-f]{64}", self.snapshot_sha256):
            raise ValueError("preview snapshot_sha256 must be lowercase SHA-256")
        if self.word_verified_snapshot_sha256 and not re.fullmatch(
            r"[0-9a-f]{64}", self.word_verified_snapshot_sha256
        ):
            raise ValueError(
                "word_verified_snapshot_sha256 must be lowercase SHA-256"
            )
        if self.preview_status == "word_verified":
            if self.word_verified_snapshot_sha256 != self.snapshot_sha256:
                raise ValueError(
                    "word-verified preview must bind the current snapshot"
                )
            if self.page_count_basis != "microsoft_word_receipt":
                raise ValueError(
                    "word-verified preview page_count must come from a Microsoft Word receipt"
                )
        if self.preview_status == "fast_preview" and self.page_count_basis != "style_profile_estimate":
            raise ValueError(
                "fast preview page_count must remain a StyleProfile estimate"
            )
        if self.preview_status == "stale":
            if not self.word_verified_snapshot_sha256:
                raise ValueError(
                    "stale preview must retain the previous Word-verified snapshot"
                )
            if self.word_verified_snapshot_sha256 == self.snapshot_sha256:
                raise ValueError(
                    "stale preview cannot claim the current snapshot is verified"
                )
            if not self.warning.strip():
                raise ValueError("stale preview must explain its warning state")
        if self.page_count != len(self.pages):
            raise ValueError("preview page_count must match pages")
        expected_pages = list(range(1, self.page_count + 1))
        if [page.page_number for page in self.pages] != expected_pages:
            raise ValueError("preview pages must be contiguous and ordered")
        return self


class MedicalWritingStudyConsistencySection(WorkbenchModel):
    section_id: str
    template_node_id: str = ""
    section_number: str = ""
    heading: str
    affected_dependents: List[str] = Field(default_factory=list)


class MedicalWritingStudyConsistencyStatus(WorkbenchModel):
    project_id: str
    document_id: str
    status: Literal[
        "current",
        "unbound_legacy",
        "binding_required",
        "missing_definition",
        "foreign_definition",
        "stale",
        "reconciliation_required",
    ]
    document_definition_id: str = ""
    document_definition_revision: Optional[int] = Field(default=None, ge=1)
    document_definition_sha256: str = ""
    current_definition_id: str = ""
    current_definition_revision: Optional[int] = Field(default=None, ge=1)
    current_definition_sha256: str = ""
    affected_dependents: List[str] = Field(default_factory=list)
    affected_sections: List[MedicalWritingStudyConsistencySection] = Field(
        default_factory=list
    )
    blocks_new_approval: bool = False
    blocks_approved_export: bool = False
    message: str


class MedicalWritingStudyRebindPreview(WorkbenchModel):
    preview_id: str
    project_id: str
    document_id: str
    baseline_revision: int = Field(ge=1)
    baseline_sha256: str = Field(min_length=64, max_length=64)
    consistency: MedicalWritingStudyConsistencyStatus
    affected_sections: List[MedicalWritingStudyConsistencySection] = Field(
        default_factory=list
    )
    affected_working_copy_count: int = Field(ge=0)
    approval_reset_count: int = Field(ge=0)
    can_apply: bool = False
    blocking_reasons: List[str] = Field(default_factory=list)


class MedicalWritingStudyRebindRequest(WorkbenchModel):
    preview_id: str = Field(min_length=1, max_length=200)
    expected_document_id: str = Field(min_length=1, max_length=200)
    expected_baseline_revision: int = Field(ge=1)
    expected_baseline_sha256: str = Field(min_length=64, max_length=64)
    confirm_content_preserved: bool = False
    confirm_affected_approvals_reset: bool = False
    reason: str = Field(min_length=10, max_length=2_000)
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def normalize_study_rebind_request(self):
        self.preview_id = self.preview_id.strip()
        self.expected_document_id = self.expected_document_id.strip()
        self.expected_baseline_sha256 = self.expected_baseline_sha256.strip()
        self.reason = self.reason.strip()
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if not all(
            (
                self.preview_id,
                self.expected_document_id,
                self.expected_baseline_sha256,
                self.reason,
                self.actor,
                self.idempotency_key,
            )
        ):
            raise ValueError("study rebind request fields must not be blank")
        if not self.confirm_content_preserved or not self.confirm_affected_approvals_reset:
            raise ValueError(
                "study rebind requires explicit content-preservation and approval-reset confirmations"
            )
        return self


class MedicalWritingStudyRebindResult(WorkbenchModel):
    project_id: str
    document_id: str
    baseline_revision: int = Field(ge=2)
    baseline_sha256: str = Field(min_length=64, max_length=64)
    reset_working_copy_ids: List[str] = Field(default_factory=list)
    reset_approval_count: int = Field(ge=0)
    audit_id: str
    consistency: MedicalWritingStudyConsistencyStatus
    rebound_at: datetime


class MedicalWritingStyleProfileDefinition(WorkbenchModel):
    style_profile_id: str = Field(min_length=1, max_length=100)
    style_profile_version: str = Field(min_length=1, max_length=100)
    authority: str = Field(min_length=1, max_length=1000)
    country: Literal["CN"] = "CN"
    language: Literal["zh-CN"] = "zh-CN"
    source_documents: List[Dict[str, str]] = Field(min_length=1, max_length=20)
    page_layout: Dict[str, Any]
    style_presets: Dict[str, Dict[str, Any]]
    definition_sha256: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_style_profile_definition(self):
        required_margins = {"top_mm", "bottom_mm", "left_mm", "right_mm"}
        if self.page_layout.get("paper") != "A4":
            raise ValueError("medical-writing style profile must use A4 paper")
        if not required_margins.issubset(self.page_layout):
            raise ValueError("medical-writing style profile is missing page margins")
        required_presets = {"heading_1", "heading_2", "heading_3", "heading_4", "body", "note"}
        if not required_presets.issubset(self.style_presets):
            raise ValueError("medical-writing style profile is missing required presets")
        return self


class MedicalWritingCorpusSnapshotDefinition(WorkbenchModel):
    snapshot_id: str = Field(min_length=1, max_length=100)
    snapshot_version: str = Field(min_length=1, max_length=100)
    snapshot_sha256: str = Field(min_length=64, max_length=64)
    schema_version: str = Field(min_length=1, max_length=100)
    authority: str = Field(min_length=1, max_length=1000)
    entry_count: int = Field(ge=1)
    base_library: Dict[str, Any]
    supplemental_sources: List[Dict[str, Any]] = Field(default_factory=list, max_length=20)


class MedicalWritingSharedCorpusReviewRequest(WorkbenchModel):
    decision: Literal["approved", "returned", "rejected"]
    comment: str = Field(min_length=2, max_length=4_000)
    actor: str = Field(default="medical_manager", min_length=2, max_length=80)
    expected_revision: int = Field(default=0, ge=0)
    idempotency_key: str = Field(min_length=8, max_length=160)

    @model_validator(mode="after")
    def normalize_shared_corpus_review(self):
        self.comment = self.comment.strip()
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        return self


class MedicalWritingSharedCorpusAdmissionRequest(WorkbenchModel):
    medical_review_id: str = Field(min_length=1, max_length=160)
    expected_review_revision: int = Field(ge=1)
    actor: str = Field(default="medical_manager", min_length=2, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=160)

    @model_validator(mode="after")
    def normalize_shared_corpus_admission(self):
        self.medical_review_id = self.medical_review_id.strip()
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        return self


class MedicalWritingSharedCorpusCandidate(WorkbenchModel):
    layer_id: str
    asset_version: str
    asset_sha256: str = Field(min_length=64, max_length=64)
    candidate_sha256: str = Field(min_length=64, max_length=64)
    segment_id: str
    nct_id: str
    sponsor: str
    phases: List[str] = Field(default_factory=list)
    conditions: List[str] = Field(default_factory=list)
    modality: str
    compound: str
    corpus_function: str
    ich_m11_anchor: str
    applicability: str
    protocol_version: str = ""
    document_date: str = ""
    source_url: str
    source_locator: str
    document_sha256: str = Field(min_length=64, max_length=64)
    source_text: str
    source_text_sha256: str = Field(min_length=64, max_length=64)
    translated_text: str
    translated_text_sha256: str = Field(min_length=64, max_length=64)
    provider: str
    model_name: str
    prompt_version: str
    glossary_version: str
    contract_hash: str = Field(min_length=64, max_length=64)
    ai_run_id: str
    automatic_fidelity_status: Literal["passed"] = "passed"
    medical_review_status: Literal[
        "not_reviewed", "approved", "returned", "rejected"
    ] = "not_reviewed"
    medical_review_revision: int = Field(default=0, ge=0)
    medical_review_id: str = ""
    medical_review_comment: str = ""
    medical_review_actor: str = ""
    medical_reviewed_at: Optional[datetime] = None
    admission_status: Literal["not_admitted", "admitted", "invalidated"] = "not_admitted"
    admission_id: str = ""
    admitted_at: Optional[datetime] = None


class MedicalWritingSharedCorpusCatalog(WorkbenchModel):
    layer_id: str
    asset_version: str
    asset_sha256: str = Field(min_length=64, max_length=64)
    item_count: int = Field(ge=0)
    pending_review_count: int = Field(ge=0)
    approved_count: int = Field(ge=0)
    admitted_count: int = Field(ge=0)
    items: List[MedicalWritingSharedCorpusCandidate] = Field(default_factory=list)


class MedicalWritingProtocolTemplateNode(WorkbenchModel):
    node_id: str = Field(min_length=1, max_length=100)
    semantic_node_id: str = Field(default="", max_length=160)
    section_number: str = Field(default="", max_length=40)
    parent_node_id: str = Field(default="", max_length=100)
    title_zh: str = Field(min_length=1, max_length=300)
    level: int = Field(ge=0, le=5)
    node_kind: str = Field(min_length=1, max_length=80)
    applicability_mode: Literal[
        "required",
        "conditional_by_design",
        "conditional_by_plugin",
    ]
    repeatable: bool = False
    title_locked: bool = True
    interaction_types: List[str] = Field(min_length=1, max_length=10)
    include_in_toc: bool = True
    applicability_rules: List[str] = Field(default_factory=list, max_length=20)
    authority_source_ids: List[str] = Field(default_factory=list, max_length=20)
    m11_coverage_anchors: List[str] = Field(default_factory=list, max_length=20)
    structural_function_ids: List[str] = Field(default_factory=list, max_length=10)
    structural_evidence_class: Literal[
        "company_core",
        "phase_core",
        "design_optional",
        "modality_or_indication_optional",
        "insufficient_evidence",
    ] = "insufficient_evidence"
    structural_evidence_refs: List[str] = Field(default_factory=list, max_length=10)
    structural_evidence_note: str = Field(default="", max_length=1_000)


class MedicalWritingProtocolModuleResolution(WorkbenchModel):
    template_node_id: str = Field(min_length=1, max_length=100)
    semantic_node_id: str = Field(min_length=1, max_length=160)
    status: Literal[
        "applicable",
        "not_applicable",
        "unknown",
        "deferred",
    ]
    render_action: Literal[
        "retain_full",
        "omit",
        "retain_not_applicable",
        "retain_placeholder",
    ]
    resolution_source: Literal[
        "template_required",
        "deterministic_rule",
        "user_override",
        "ai_proposal",
    ]
    rationale: str = Field(min_length=1, max_length=2_000)
    source_fact_ids: List[str] = Field(default_factory=list, max_length=100)
    affected_artifacts: List[
        Literal[
            "synopsis",
            "body",
            "statistics",
            "schedule",
            "evidence",
            "ai_candidates",
        ]
    ] = Field(default_factory=lambda: ["body"], min_length=1, max_length=6)
    user_override: bool = False

    @model_validator(mode="after")
    def validate_protocol_module_resolution(self):
        self.template_node_id = self.template_node_id.strip()
        self.semantic_node_id = self.semantic_node_id.strip()
        self.rationale = self.rationale.strip()
        self.source_fact_ids = [
            item.strip() for item in self.source_fact_ids if item.strip()
        ]
        if len(self.source_fact_ids) != len(set(self.source_fact_ids)):
            raise ValueError("protocol module resolution source fact ids must be unique")
        if self.status == "applicable" and self.render_action != "retain_full":
            raise ValueError("applicable protocol modules must render in full")
        if self.status == "not_applicable" and self.render_action not in {
            "omit",
            "retain_not_applicable",
        }:
            raise ValueError(
                "not-applicable protocol modules must be omitted or retained as N/A"
            )
        if self.status in {"unknown", "deferred"} and self.render_action not in {
            "omit",
            "retain_placeholder",
        }:
            raise ValueError(
                "unknown or deferred protocol modules must be omitted or retained as placeholders"
            )
        if self.resolution_source == "user_override" and not self.user_override:
            raise ValueError("user override resolutions must set user_override")
        return self


class MedicalWritingProtocolTemplateDefinition(WorkbenchModel):
    template_id: str = Field(min_length=1, max_length=100)
    template_version: str = Field(min_length=1, max_length=100)
    authority: str = Field(min_length=1, max_length=500)
    country: Literal["CN"] = "CN"
    language: Literal["zh-CN"] = "zh-CN"
    effective_date: str = Field(min_length=10, max_length=10)
    lifecycle_status: Literal["draft", "final"] = "final"
    china_regulatory_status: Literal[
        "historical_draft", "public_consultation", "effective"
    ] = "public_consultation"
    china_applicability_rule: str = Field(default="", max_length=500)
    source_documents: List[Dict[str, str]] = Field(default_factory=list, max_length=10)
    definition_sha256: str = Field(min_length=64, max_length=64)
    nodes: List[MedicalWritingProtocolTemplateNode] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_protocol_template_definition(self):
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("protocol template node ids must be unique")
        seen: set[str] = set()
        for node in self.nodes:
            if node.parent_node_id and node.parent_node_id not in seen:
                raise ValueError(f"protocol template parent must precede child: {node.node_id}")
            seen.add(node.node_id)
        return self


class MedicalWritingProductEvidenceFact(WorkbenchModel):
    fact_id: str = Field(min_length=1, max_length=160)
    field_path: str = Field(min_length=1, max_length=200)
    value: str = Field(default="", max_length=20_000)
    evidence_status: Literal[
        "user_provided",
        "source_extracted",
        "public_evidence",
        "ai_inferred",
        "unknown",
    ] = "unknown"
    source_ids: List[str] = Field(default_factory=list, max_length=100)
    confidence: Literal["unknown", "low", "medium", "high"] = "unknown"
    user_confirmed: bool = False

    @model_validator(mode="after")
    def normalize_product_evidence_fact(self):
        self.fact_id = self.fact_id.strip()
        self.field_path = self.field_path.strip()
        self.value = self.value.strip()
        self.source_ids = [item.strip() for item in self.source_ids if item.strip()]
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("product evidence fact source ids must be unique")
        if self.evidence_status == "unknown":
            self.value = ""
            self.source_ids = []
            self.confidence = "unknown"
            self.user_confirmed = False
        elif not self.value:
            raise ValueError("known product evidence fact requires a value")
        return self


class MedicalWritingInvestigationalProductProfile(WorkbenchModel):
    technology_type: Literal[
        "unknown",
        "monoclonal_antibody",
        "other_biologic",
        "small_molecule",
        "rna_therapy",
        "cell_therapy",
        "gene_therapy",
        "vaccine",
        "other",
    ] = "unknown"
    technology_description: str = Field(default="", max_length=1_000)
    administration_routes: List[str] = Field(default_factory=list, max_length=20)
    dosage_forms: List[str] = Field(default_factory=list, max_length=20)
    exposure_scope: Literal["unknown", "systemic", "local", "mixed"] = "unknown"
    device_dependency: Literal["unknown", "none", "integrated", "external"] = "unknown"
    immunogenicity_relevance: Literal[
        "unknown", "not_expected", "potential", "expected"
    ] = "unknown"
    pharmacology_considerations: List[str] = Field(default_factory=list, max_length=50)
    safety_considerations: List[str] = Field(default_factory=list, max_length=100)
    pk_pd_considerations: List[str] = Field(default_factory=list, max_length=100)
    historical_study_summaries: List[str] = Field(
        default_factory=list, max_length=100
    )
    historical_dose_regimens: List[str] = Field(
        default_factory=list, max_length=100
    )
    historical_population_designs: List[str] = Field(
        default_factory=list, max_length=100
    )
    evidence_facts: List[MedicalWritingProductEvidenceFact] = Field(
        default_factory=list, max_length=200
    )

    @model_validator(mode="after")
    def normalize_product_profile(self):
        self.technology_description = self.technology_description.strip()
        for field_name in (
            "administration_routes",
            "dosage_forms",
            "pharmacology_considerations",
            "safety_considerations",
            "pk_pd_considerations",
            "historical_study_summaries",
            "historical_dose_regimens",
            "historical_population_designs",
        ):
            values = [item.strip() for item in getattr(self, field_name) if item.strip()]
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must be unique")
            setattr(self, field_name, values)
        fact_ids = [item.fact_id for item in self.evidence_facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("product evidence fact ids must be unique")
        return self

    def applicability_facets(self) -> List[str]:
        facets: List[str] = []
        if self.technology_type != "unknown":
            facets.append(f"technology:{self.technology_type}")
        facets.extend(f"route:{item}" for item in self.administration_routes)
        facets.extend(f"dosage_form:{item}" for item in self.dosage_forms)
        if self.exposure_scope != "unknown":
            facets.append(f"exposure:{self.exposure_scope}")
        return facets


class MedicalWritingMinimumProductFactPacket(WorkbenchModel):
    ib_status: Literal[
        "not_provided",
        "not_available",
        "uploaded",
        "parsed",
    ] = "not_provided"
    ib_source_ids: List[str] = Field(default_factory=list, max_length=50)
    ib_validation_status: Literal[
        "not_assessed",
        "matched",
        "confirmed_after_warning",
    ] = "not_assessed"
    ib_warning_codes: List[str] = Field(default_factory=list, max_length=20)
    ib_override_reason: str = Field(default="", max_length=2_000)
    status: Literal[
        "not_started",
        "assembling",
        "sufficient_for_research",
        "needs_user_input",
    ] = "not_started"
    supporting_source_ids: List[str] = Field(default_factory=list, max_length=200)
    unresolved_high_impact_fields: List[str] = Field(
        default_factory=list, max_length=100
    )
    safe_to_start_competitor_research: bool = False
    safe_to_generate_protocol_candidates: bool = False
    assessed_at: Optional[datetime] = None

    @model_validator(mode="after")
    def normalize_minimum_product_fact_packet(self):
        for field_name in (
            "ib_source_ids",
            "ib_warning_codes",
            "supporting_source_ids",
            "unresolved_high_impact_fields",
        ):
            values = [item.strip() for item in getattr(self, field_name) if item.strip()]
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must be unique")
            setattr(self, field_name, values)
        if self.ib_status in {"not_provided", "not_available"}:
            self.ib_source_ids = []
            self.ib_validation_status = "not_assessed"
            self.ib_warning_codes = []
            self.ib_override_reason = ""
        if self.ib_status in {"uploaded", "parsed"} and not self.ib_source_ids:
            raise ValueError("uploaded or parsed IB requires at least one source id")
        self.ib_override_reason = self.ib_override_reason.strip()
        if self.ib_validation_status == "confirmed_after_warning":
            if not self.ib_warning_codes:
                raise ValueError("IB warning confirmation requires warning codes")
        elif self.ib_override_reason:
            raise ValueError(
                "IB override reason is only valid after warning confirmation"
            )
        if self.safe_to_generate_protocol_candidates:
            self.safe_to_start_competitor_research = True
        return self


class MedicalWritingPhase1Part(WorkbenchModel):
    """Typed I期 Part object — per-Part clinical design structure.

    Each Part (SAD, MAD, food effect, first-in-patient, etc.) carries its own
    population, cohort/dose, PK/PD, safety, stopping rules, SoA, and transition
    dependency fields.  Legacy ``List[str]`` inputs are migrated with
    ``part_code`` filled and all clinical detail fields left empty/unknown;
    the typed object is always the downstream authority.
    """

    part_code: str = Field(default="", max_length=100)
    part_label: str = Field(default="", max_length=200)
    population: str = Field(default="", max_length=1_000)
    cohort_dose: str = Field(default="", max_length=1_000)
    pk_pd: str = Field(default="", max_length=1_000)
    safety: str = Field(default="", max_length=1_000)
    stopping_rules: str = Field(default="", max_length=1_000)
    soa_summary: str = Field(default="", max_length=1_000)
    transition_dependencies: str = Field(default="", max_length=1_000)
    unresolved: bool = True

    def __str__(self) -> str:
        """Return part_code so legacy string-join consumers still work."""
        return self.part_code

    @model_validator(mode="after")
    def normalize_phase1_part(self):
        for field_name in (
            "part_code",
            "part_label",
            "population",
            "cohort_dose",
            "pk_pd",
            "safety",
            "stopping_rules",
            "soa_summary",
            "transition_dependencies",
        ):
            setattr(self, field_name, getattr(self, field_name).strip())
        # A Part is resolved only when part_code is set and at least
        # population and cohort_dose are no longer empty — i.e. the
        # clinical detail has been filled, not just the code.
        self.unresolved = not (
            self.part_code
            and self.population
            and self.cohort_dose
        )
        return self


class MedicalWritingInterimAnalysisDesign(WorkbenchModel):
    planned: Optional[bool] = None
    purpose: str = Field(default="", max_length=2_000)
    timing: str = Field(default="", max_length=2_000)
    information_fraction: str = Field(default="", max_length=500)
    statistical_boundary: str = Field(default="", max_length=2_000)
    alpha_control: str = Field(default="", max_length=2_000)
    independent_committee: str = Field(default="", max_length=1_000)
    operational_firewall: str = Field(default="", max_length=2_000)
    notes: str = Field(default="", max_length=4_000)

    @model_validator(mode="after")
    def normalize_interim_analysis_design(self):
        for field_name in (
            "purpose",
            "timing",
            "information_fraction",
            "statistical_boundary",
            "alpha_control",
            "independent_committee",
            "operational_firewall",
            "notes",
        ):
            setattr(self, field_name, getattr(self, field_name).strip())
        if self.planned is False:
            for field_name in (
                "purpose",
                "timing",
                "information_fraction",
                "statistical_boundary",
                "alpha_control",
                "independent_committee",
                "operational_firewall",
            ):
                setattr(self, field_name, "")
        return self


def _normalize_complex_design_fields(
    design: Any,
    *,
    scalar_fields: tuple[str, ...],
    list_fields: tuple[str, ...] = (),
) -> None:
    for field_name in scalar_fields:
        setattr(design, field_name, getattr(design, field_name).strip())
    for field_name in list_fields:
        values = [
            item.strip() for item in getattr(design, field_name) if item.strip()
        ]
        if len(values) != len(set(values)):
            raise ValueError(f"{field_name} must be unique")
        setattr(design, field_name, values)


def _clear_complex_design_fields(
    design: Any,
    *,
    scalar_fields: tuple[str, ...],
    list_fields: tuple[str, ...] = (),
) -> None:
    for field_name in scalar_fields:
        setattr(design, field_name, "")
    for field_name in list_fields:
        setattr(design, field_name, [])


class MedicalWritingTreatmentSwitchDesign(WorkbenchModel):
    """Protocol-writing facts for a non-crossover treatment switch."""

    planned: Optional[bool] = None
    trigger_or_timing: str = Field(default="", max_length=2_000)
    eligible_population: str = Field(default="", max_length=2_000)
    destination_treatment: str = Field(default="", max_length=2_000)
    blinding_strategy: str = Field(default="", max_length=2_000)
    analysis_handling: str = Field(default="", max_length=3_000)
    notes: str = Field(default="", max_length=4_000)

    @model_validator(mode="after")
    def normalize_treatment_switch(self):
        detail_fields = (
            "trigger_or_timing",
            "eligible_population",
            "destination_treatment",
            "blinding_strategy",
            "analysis_handling",
        )
        _normalize_complex_design_fields(
            self, scalar_fields=(*detail_fields, "notes")
        )
        if self.planned is False:
            _clear_complex_design_fields(self, scalar_fields=detail_fields)
        return self

    def missing_required_fields(self) -> List[str]:
        if self.planned is not True:
            return []
        return [
            field_name
            for field_name in (
                "trigger_or_timing",
                "eligible_population",
                "destination_treatment",
                "blinding_strategy",
                "analysis_handling",
            )
            if not getattr(self, field_name)
        ]


class MedicalWritingCrossoverDesign(WorkbenchModel):
    """Period/sequence crossover facts, distinct from one-way switching."""

    planned: Optional[bool] = None
    sequences: List[str] = Field(default_factory=list, max_length=20)
    periods: List[str] = Field(default_factory=list, max_length=30)
    washout_strategy: str = Field(default="", max_length=2_000)
    carryover_assessment: str = Field(default="", max_length=2_000)
    period_sequence_analysis: str = Field(default="", max_length=3_000)
    notes: str = Field(default="", max_length=4_000)

    @model_validator(mode="after")
    def normalize_crossover(self):
        detail_scalars = (
            "washout_strategy",
            "carryover_assessment",
            "period_sequence_analysis",
        )
        detail_lists = ("sequences", "periods")
        _normalize_complex_design_fields(
            self,
            scalar_fields=(*detail_scalars, "notes"),
            list_fields=detail_lists,
        )
        if self.planned is False:
            _clear_complex_design_fields(
                self,
                scalar_fields=detail_scalars,
                list_fields=detail_lists,
            )
        return self

    def missing_required_fields(self) -> List[str]:
        if self.planned is not True:
            return []
        return [
            field_name
            for field_name in (
                "sequences",
                "periods",
                "washout_strategy",
                "carryover_assessment",
                "period_sequence_analysis",
            )
            if not getattr(self, field_name)
        ]


class MedicalWritingOpenLabelExtensionDesign(WorkbenchModel):
    """Open-label extension entry, treatment and long-term objective facts."""

    planned: Optional[bool] = None
    entry_source: str = Field(default="", max_length=2_000)
    entry_eligibility: str = Field(default="", max_length=2_000)
    treatment_regimen: str = Field(default="", max_length=3_000)
    duration: str = Field(default="", max_length=1_000)
    blind_break_and_transition: str = Field(default="", max_length=2_000)
    long_term_objectives: List[str] = Field(default_factory=list, max_length=50)
    notes: str = Field(default="", max_length=4_000)

    @model_validator(mode="after")
    def normalize_open_label_extension(self):
        detail_scalars = (
            "entry_source",
            "entry_eligibility",
            "treatment_regimen",
            "duration",
            "blind_break_and_transition",
        )
        _normalize_complex_design_fields(
            self,
            scalar_fields=(*detail_scalars, "notes"),
            list_fields=("long_term_objectives",),
        )
        if self.planned is False:
            _clear_complex_design_fields(
                self,
                scalar_fields=detail_scalars,
                list_fields=("long_term_objectives",),
            )
        return self

    def missing_required_fields(self) -> List[str]:
        if self.planned is not True:
            return []
        return [
            field_name
            for field_name in (
                "entry_source",
                "entry_eligibility",
                "treatment_regimen",
                "duration",
                "blind_break_and_transition",
                "long_term_objectives",
            )
            if not getattr(self, field_name)
        ]


class MedicalWritingSampleSizeReestimationDesign(WorkbenchModel):
    """Blinded or unblinded sample-size re-estimation design facts."""

    planned: Optional[bool] = None
    reestimation_mode: Literal["undecided", "blinded", "unblinded"] = "undecided"
    timing_or_information: str = Field(default="", max_length=2_000)
    reestimated_parameter: str = Field(default="", max_length=2_000)
    decision_rule: str = Field(default="", max_length=3_000)
    alpha_protection: str = Field(default="", max_length=2_000)
    operational_protection: str = Field(default="", max_length=3_000)
    notes: str = Field(default="", max_length=4_000)

    @model_validator(mode="after")
    def normalize_sample_size_reestimation(self):
        detail_fields = (
            "timing_or_information",
            "reestimated_parameter",
            "decision_rule",
            "alpha_protection",
            "operational_protection",
        )
        _normalize_complex_design_fields(
            self, scalar_fields=(*detail_fields, "notes")
        )
        if self.planned is False:
            self.reestimation_mode = "undecided"
            _clear_complex_design_fields(self, scalar_fields=detail_fields)
        return self

    def missing_required_fields(self) -> List[str]:
        if self.planned is not True:
            return []
        missing = [
            field_name
            for field_name in (
                "timing_or_information",
                "reestimated_parameter",
                "decision_rule",
                "alpha_protection",
                "operational_protection",
            )
            if not getattr(self, field_name)
        ]
        if self.reestimation_mode == "undecided":
            missing.insert(0, "reestimation_mode")
        return missing


class MedicalWritingAdaptiveDesign(WorkbenchModel):
    """Adaptive-design decisions and operating-characteristic controls."""

    planned: Optional[bool] = None
    adaptive_type: Literal[
        "undecided",
        "group_sequential",
        "sample_size_reestimation",
        "dose_selection",
        "population_enrichment",
        "treatment_arm_selection",
        "response_adaptive_randomization",
        "seamless_phase",
        "other",
    ] = "undecided"
    adaptation_timing: str = Field(default="", max_length=2_000)
    decision_criteria: str = Field(default="", max_length=3_000)
    adaptable_elements: List[str] = Field(default_factory=list, max_length=50)
    simulation_operating_characteristics: str = Field(default="", max_length=4_000)
    type_i_error_control: str = Field(default="", max_length=3_000)
    operational_control: str = Field(default="", max_length=3_000)
    notes: str = Field(default="", max_length=4_000)

    @model_validator(mode="after")
    def normalize_adaptive_design(self):
        detail_scalars = (
            "adaptation_timing",
            "decision_criteria",
            "simulation_operating_characteristics",
            "type_i_error_control",
            "operational_control",
        )
        _normalize_complex_design_fields(
            self,
            scalar_fields=(*detail_scalars, "notes"),
            list_fields=("adaptable_elements",),
        )
        if self.planned is False:
            self.adaptive_type = "undecided"
            _clear_complex_design_fields(
                self,
                scalar_fields=detail_scalars,
                list_fields=("adaptable_elements",),
            )
        return self

    def missing_required_fields(self) -> List[str]:
        if self.planned is not True:
            return []
        missing = [
            field_name
            for field_name in (
                "adaptation_timing",
                "decision_criteria",
                "adaptable_elements",
                "simulation_operating_characteristics",
                "type_i_error_control",
                "operational_control",
            )
            if not getattr(self, field_name)
        ]
        if self.adaptive_type == "undecided":
            missing.insert(0, "adaptive_type")
        return missing


class MedicalWritingStructuredStudyDesign(WorkbenchModel):
    schema_version: Literal[
        "medical_writing_structured_study_design_v1",
        "medical_writing_structured_study_design_v2",
    ] = (
        "medical_writing_structured_study_design_v2"
    )
    randomization_mode: Literal[
        "undecided", "randomized", "non_randomized", "other"
    ] = "undecided"
    randomization_details: str = Field(default="", max_length=2_000)
    blinding_mode: Literal[
        "undecided",
        "open_label",
        "single_blind",
        "double_blind",
        "triple_blind",
        "other",
    ] = "undecided"
    blinded_roles: List[str] = Field(default_factory=list, max_length=20)
    blinding_details: str = Field(default="", max_length=2_000)
    comparator_type: Literal[
        "undecided",
        "placebo",
        "active",
        "none_or_dose_escalation",
        "other",
    ] = "undecided"
    comparator_intervention: str = Field(default="", max_length=2_000)
    assignment_model: str = Field(default="", max_length=500)
    center_model: str = Field(default="", max_length=500)
    treatment_switch: MedicalWritingTreatmentSwitchDesign = Field(
        default_factory=MedicalWritingTreatmentSwitchDesign
    )
    crossover: MedicalWritingCrossoverDesign = Field(
        default_factory=MedicalWritingCrossoverDesign
    )
    open_label_extension: MedicalWritingOpenLabelExtensionDesign = Field(
        default_factory=MedicalWritingOpenLabelExtensionDesign
    )
    sample_size_reestimation: MedicalWritingSampleSizeReestimationDesign = Field(
        default_factory=MedicalWritingSampleSizeReestimationDesign
    )
    adaptive_design: MedicalWritingAdaptiveDesign = Field(
        default_factory=MedicalWritingAdaptiveDesign
    )
    adaptive_design_enabled: Optional[bool] = Field(
        default=None, exclude=True, repr=False
    )
    adaptive_features: List[str] = Field(
        default_factory=list, max_length=50, exclude=True, repr=False
    )
    sample_size_reestimation_planned: Optional[bool] = Field(
        default=None, exclude=True, repr=False
    )
    treatment_switch_planned: Optional[bool] = Field(
        default=None, exclude=True, repr=False
    )
    crossover_planned: Optional[bool] = Field(
        default=None, exclude=True, repr=False
    )
    open_label_extension_planned: Optional[bool] = Field(
        default=None, exclude=True, repr=False
    )
    src_planned: Optional[bool] = None
    dmc_planned: Optional[bool] = None
    interim_analysis: MedicalWritingInterimAnalysisDesign = Field(
        default_factory=MedicalWritingInterimAnalysisDesign
    )
    phase1_parts: List[MedicalWritingPhase1Part] = Field(
        default_factory=list, max_length=30
    )
    phase1_sequence: str = Field(default="", max_length=500)
    arm_or_cohort_kind: str = Field(default="", max_length=200)
    arm_or_cohort_labels: List[str] = Field(default_factory=list, max_length=100)
    other_design_notes: str = Field(default="", max_length=4_000)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_complex_design_booleans(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        migrations = (
            ("treatment_switch", "treatment_switch_planned"),
            ("crossover", "crossover_planned"),
            ("open_label_extension", "open_label_extension_planned"),
            ("sample_size_reestimation", "sample_size_reestimation_planned"),
            ("adaptive_design", "adaptive_design_enabled"),
        )
        for typed_field, legacy_field in migrations:
            if typed_field in payload and payload[typed_field] is not None:
                continue
            typed_payload: Dict[str, Any] = {
                "planned": payload.get(legacy_field)
            }
            if typed_field == "adaptive_design":
                features = payload.get("adaptive_features")
                if isinstance(features, list):
                    typed_payload["adaptable_elements"] = list(features)
            payload[typed_field] = typed_payload
        payload["schema_version"] = "medical_writing_structured_study_design_v2"
        return payload

    @model_validator(mode="after")
    def normalize_structured_study_design(self):
        self.schema_version = "medical_writing_structured_study_design_v2"
        for field_name in (
            "randomization_details",
            "blinding_details",
            "comparator_intervention",
            "assignment_model",
            "center_model",
            "phase1_sequence",
            "arm_or_cohort_kind",
            "other_design_notes",
        ):
            setattr(self, field_name, getattr(self, field_name).strip())
        for field_name in (
            "blinded_roles",
            "arm_or_cohort_labels",
        ):
            values = [item.strip() for item in getattr(self, field_name) if item.strip()]
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must be unique")
            setattr(self, field_name, values)
        # phase1_parts typed uniqueness: deduplicate by part_code.
        seen_codes: set[str] = set()
        unique_parts: list[MedicalWritingPhase1Part] = []
        for part in self.phase1_parts:
            code = part.part_code.strip()
            if code and code not in seen_codes:
                seen_codes.add(code)
                unique_parts.append(part)
        self.phase1_parts = unique_parts
        # Compatibility mirrors are derived from typed authority and excluded
        # from serialization, so they cannot become a parallel fact source.
        self.treatment_switch_planned = self.treatment_switch.planned
        self.crossover_planned = self.crossover.planned
        self.open_label_extension_planned = self.open_label_extension.planned
        self.sample_size_reestimation_planned = (
            self.sample_size_reestimation.planned
        )
        self.adaptive_design_enabled = self.adaptive_design.planned
        self.adaptive_features = list(self.adaptive_design.adaptable_elements)
        return self

    @field_validator("phase1_parts", mode="before")
    @classmethod
    def _migrate_legacy_phase1_parts(cls, value: Any) -> Any:
        """Read-only migration: legacy ``List[str]`` → typed ``Phase1Part`` list.

        Each legacy string is converted to a :class:`MedicalWritingPhase1Part`
        with ``part_code`` filled from the normalized token and all clinical
        detail fields left empty/unknown.  Downstream authority is always the
        typed object; the string list is never the authority after load.
        """
        if value is None:
            return []
        if isinstance(value, list):
            migrated: list[MedicalWritingPhase1Part] = []
            for item in value:
                if isinstance(item, MedicalWritingPhase1Part):
                    migrated.append(item)
                elif isinstance(item, str):
                    code = item.strip()
                    if code:
                        migrated.append(MedicalWritingPhase1Part(part_code=code))
                elif isinstance(item, dict):
                    migrated.append(MedicalWritingPhase1Part.model_validate(item))
            return migrated
        # Single string or other scalar — wrap.
        if isinstance(value, str):
            code = value.strip()
            return [MedicalWritingPhase1Part(part_code=code)] if code else []
        return value


class MedicalWritingStudyFraming(WorkbenchModel):
    protocol_id: str = Field(default="", max_length=200)
    version: str = Field(default="V0.1", max_length=80)
    document_title: str = Field(default="", max_length=500)
    indication: str = Field(default="", max_length=300)
    clinicaltrials_condition_term: str = Field(default="", max_length=300)
    study_phase: str = Field(default="", max_length=100)
    intrinsic_objectives: List[str] = Field(default_factory=list, max_length=20)
    investigational_product: str = Field(default="", max_length=300)
    product_profile: MedicalWritingInvestigationalProductProfile = Field(
        default_factory=MedicalWritingInvestigationalProductProfile
    )
    minimum_product_fact_packet: MedicalWritingMinimumProductFactPacket = Field(
        default_factory=MedicalWritingMinimumProductFactPacket
    )
    target_mechanism: str = Field(default="", max_length=500)
    competitor_target_scope: str = Field(default="", max_length=500)
    development_regions: List[str] = Field(default_factory=lambda: ["中国"], max_length=20)
    design_pattern: str = Field(default="", max_length=500)
    structured_design: MedicalWritingStructuredStudyDesign = Field(
        default_factory=MedicalWritingStructuredStudyDesign
    )
    population_intent: str = Field(default="", max_length=2_000)
    key_uncertainties: List[str] = Field(default_factory=list, max_length=50)
    manual_source_ids: List[str] = Field(default_factory=list, max_length=100)
    terminology_policy: Literal["cde_participant", "subject", "project_override"] = (
        "cde_participant"
    )

    @model_validator(mode="after")
    def normalize_study_framing(self):
        scalar_fields = (
            "protocol_id",
            "version",
            "document_title",
            "indication",
            "clinicaltrials_condition_term",
            "study_phase",
            "investigational_product",
            "target_mechanism",
            "competitor_target_scope",
            "design_pattern",
            "population_intent",
        )
        for field_name in scalar_fields:
            setattr(self, field_name, getattr(self, field_name).strip())
        for field_name in (
            "intrinsic_objectives",
            "development_regions",
            "key_uncertainties",
            "manual_source_ids",
        ):
            values = [item.strip() for item in getattr(self, field_name) if item.strip()]
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must be unique")
            setattr(self, field_name, values)
        return self

    def creation_minimum_missing_fields(self) -> List[str]:
        required_scalars = {
            "indication": self.indication,
            "study_phase": self.study_phase,
            "investigational_product": self.investigational_product,
        }
        return [key for key, value in required_scalars.items() if not value]

    def creation_minimum_complete(self) -> bool:
        return not self.creation_minimum_missing_fields()

    def missing_required_fields(self) -> List[str]:
        missing = []
        required_scalars = {
            "protocol_id": self.protocol_id,
            "document_title": self.document_title,
            "indication": self.indication,
            "study_phase": self.study_phase,
            "investigational_product": self.investigational_product,
            "design_pattern": self.design_pattern,
            "population_intent": self.population_intent,
        }
        missing.extend(key for key, value in required_scalars.items() if not value)
        if not self.intrinsic_objectives:
            missing.append("intrinsic_objectives")
        return missing


class MedicalWritingPicosFieldApplicability(WorkbenchModel):
    status: Literal["applicable", "not_applicable"] = "applicable"
    reason: str = Field(default="", max_length=2_000)
    confirmed_by_medical_manager: bool = False

    @model_validator(mode="after")
    def normalize_applicability(self):
        self.reason = self.reason.strip()
        if self.status == "applicable":
            self.reason = ""
            self.confirmed_by_medical_manager = False
        return self


class MedicalWritingInstrumentSourceBinding(WorkbenchModel):
    source_kind: Literal[
        "project_protocol",
        "competitor_protocol",
        "instrument_owner",
        "regulator",
        "validation_publication",
        "user_upload",
        "other",
    ]
    source_id: str = Field(default="", max_length=200)
    title: str = Field(default="", max_length=500)
    url: str = Field(default="", max_length=2_000)
    locator: str = Field(default="", max_length=1_000)
    artifact_id: str = Field(default="", max_length=200)
    evidence_sha256: str = Field(default="", max_length=64)
    accessed_at: Optional[datetime] = None

    @model_validator(mode="after")
    def normalize_instrument_source(self):
        for field_name in (
            "source_id",
            "title",
            "url",
            "locator",
            "artifact_id",
            "evidence_sha256",
        ):
            setattr(self, field_name, getattr(self, field_name).strip())
        if self.evidence_sha256 and len(self.evidence_sha256) != 64:
            raise ValueError("instrument source evidence_sha256 must contain 64 characters")
        if not (self.source_id or self.url or self.artifact_id):
            raise ValueError("instrument source requires a source id, URL, or artifact id")
        return self


class MedicalWritingInstrumentRightsState(WorkbenchModel):
    status: Literal[
        "unknown",
        "permission_required",
        "license_pending",
        "licensed",
        "public_domain",
        "permission_not_required",
    ] = "unknown"
    full_text_policy: Literal[
        "metadata_only",
        "link_only",
        "licensed_copy_allowed",
        "open_copy_allowed",
    ] = "metadata_only"
    owner: str = Field(default="", max_length=300)
    license_reference: str = Field(default="", max_length=500)
    evidence_url: str = Field(default="", max_length=2_000)
    checked_at: Optional[datetime] = None
    confirmed_by: str = Field(default="", max_length=100)
    confirmed_at: Optional[datetime] = None

    @model_validator(mode="after")
    def normalize_instrument_rights(self):
        for field_name in (
            "owner",
            "license_reference",
            "evidence_url",
            "confirmed_by",
        ):
            setattr(self, field_name, getattr(self, field_name).strip())
        if self.full_text_policy in {"licensed_copy_allowed", "open_copy_allowed"} and self.status not in {
            "licensed",
            "public_domain",
            "permission_not_required",
        }:
            raise ValueError("instrument full-text use requires a permissive rights status")
        if self.confirmed_by and self.confirmed_at is None:
            raise ValueError("instrument rights confirmation requires a timestamp")
        return self


class MedicalWritingInstrumentTranslationState(WorkbenchModel):
    source_language: str = Field(default="", max_length=100)
    target_language: str = Field(default="简体中文", max_length=100)
    status: Literal[
        "unknown",
        "not_needed",
        "official_available",
        "validated_available",
        "permission_required",
        "translation_candidate",
        "medical_reviewed",
        "unavailable",
    ] = "unknown"
    version_label: str = Field(default="", max_length=200)
    source_url: str = Field(default="", max_length=2_000)
    artifact_id: str = Field(default="", max_length=200)
    reviewed_by: str = Field(default="", max_length=100)
    reviewed_at: Optional[datetime] = None

    @model_validator(mode="after")
    def normalize_instrument_translation(self):
        for field_name in (
            "source_language",
            "target_language",
            "version_label",
            "source_url",
            "artifact_id",
            "reviewed_by",
        ):
            setattr(self, field_name, getattr(self, field_name).strip())
        if self.status == "medical_reviewed" and (
            not self.reviewed_by or self.reviewed_at is None
        ):
            raise ValueError("a medically reviewed translation requires reviewer identity")
        return self


class MedicalWritingAssessmentInstrumentUse(WorkbenchModel):
    instrument_id: str = Field(min_length=1, max_length=120)
    canonical_name_zh: str = Field(min_length=1, max_length=300)
    canonical_name_en: str = Field(default="", max_length=300)
    acronym: str = Field(default="", max_length=80)
    version_label: str = Field(default="", max_length=200)
    instrument_kind: Literal[
        "clinician_reported",
        "patient_reported",
        "observer_reported",
        "performance_outcome",
        "diagnostic_criterion",
        "safety_grading",
        "other",
    ] = "other"
    administration_mode: str = Field(default="", max_length=300)
    respondent: str = Field(default="", max_length=200)
    recall_period: str = Field(default="", max_length=300)
    scoring_range: str = Field(default="", max_length=200)
    scoring_direction: str = Field(default="", max_length=300)
    scoring_summary: str = Field(default="", max_length=2_000)
    study_purpose: str = Field(default="", max_length=2_000)
    endpoint_paths: List[str] = Field(default_factory=list, max_length=50)
    visit_labels: List[str] = Field(default_factory=list, max_length=100)
    soa_activity_ids: List[str] = Field(default_factory=list, max_length=100)
    appendix_locator: str = Field(default="", max_length=1_000)
    protocol_modified: bool = False
    source_synopsis_only: bool = False
    evidence_span_ids: List[str] = Field(default_factory=list, max_length=50)
    source_bindings: List[MedicalWritingInstrumentSourceBinding] = Field(
        default_factory=list, max_length=50
    )
    rights: MedicalWritingInstrumentRightsState = Field(
        default_factory=MedicalWritingInstrumentRightsState
    )
    translation: MedicalWritingInstrumentTranslationState = Field(
        default_factory=MedicalWritingInstrumentTranslationState
    )
    confirmation_status: Literal["candidate", "needs_review", "confirmed"] = "candidate"
    confirmed_by: str = Field(default="", max_length=100)
    confirmed_at: Optional[datetime] = None
    notes: str = Field(default="", max_length=2_000)

    @model_validator(mode="after")
    def normalize_assessment_instrument(self):
        for field_name in (
            "instrument_id",
            "canonical_name_zh",
            "canonical_name_en",
            "acronym",
            "version_label",
            "administration_mode",
            "respondent",
            "recall_period",
            "scoring_range",
            "scoring_direction",
            "scoring_summary",
            "study_purpose",
            "appendix_locator",
            "confirmed_by",
            "notes",
        ):
            setattr(self, field_name, getattr(self, field_name).strip())
        for field_name in (
            "endpoint_paths",
            "visit_labels",
            "soa_activity_ids",
            "evidence_span_ids",
        ):
            values = [item.strip() for item in getattr(self, field_name) if item.strip()]
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must be unique")
            setattr(self, field_name, values)
        allowed_endpoint_paths = {
            "picos.primary_endpoint",
            "picos.key_secondary_endpoints",
            "picos.other_secondary_endpoints",
            "picos.exploratory_endpoints",
            "picos.safety_endpoints",
            "picos.inclusion_modules",
            "picos.exclusion_modules",
        }
        unsupported = set(self.endpoint_paths) - allowed_endpoint_paths
        if unsupported:
            raise ValueError(
                "unsupported assessment instrument binding(s): "
                + ", ".join(sorted(unsupported))
            )
        if self.confirmation_status == "confirmed" and (
            not self.confirmed_by or self.confirmed_at is None
        ):
            raise ValueError("a confirmed assessment instrument requires confirmer identity")
        return self


class InterventionRulesAuthority(str, Enum):
    LEGACY = "legacy"
    STRUCTURED = "structured"


class InterventionRulesProductRole(str, Enum):
    INVESTIGATIONAL_PRODUCT = "investigational_product"
    ACTIVE_COMPARATOR = "active_comparator"
    PLACEBO = "placebo"
    OTHER = "other"


class InterventionRulesIpAdjustmentPolicy(str, Enum):
    UNSPECIFIED = "unspecified"
    NO_PLANNED_ADJUSTMENT = "no_planned_adjustment"
    PROTOCOL_DEFINED = "protocol_defined"


class InterventionRulesIpActionKind(str, Enum):
    PLANNED_ON_OFF = "planned_on_off"
    TEMPORARY_INTERRUPTION = "temporary_interruption"
    RESUME = "resume"
    PERMANENT_DISCONTINUATION = "permanent_discontinuation"
    DISCONTINUATION_TAPER = "discontinuation_taper"
    POST_DISCONTINUATION_FOLLOW_UP = "post_discontinuation_follow_up"
    OTHER = "other"


class InterventionRulesNonIpRuleClass(str, Enum):
    BACKGROUND = "background"
    ALLOWED_CM = "allowed_cm"
    PROHIBITED_CM = "prohibited_cm"
    RESCUE = "rescue"
    OTHER_NON_INVESTIGATIONAL = "other_non_investigational"


class InterventionRulesNonIpPolicy(str, Enum):
    ALLOWED = "allowed"
    ALLOWED_IF_STABLE = "allowed_if_stable"
    ALLOWED_WITH_APPROVAL = "allowed_with_approval"
    ALLOWED_WITH_TIMING = "allowed_with_timing"
    PROHIBITED = "prohibited"
    RESCUE_POLICY = "rescue_policy"


class InterventionRulesLinkSourceKind(str, Enum):
    RESCUE = "rescue"
    CM = "cm"
    BACKGROUND = "background"
    OTHER_NON_IP = "other_non_ip"


class InterventionRulesLinkAction(str, Enum):
    HOLD = "hold"
    STOP = "stop"
    NO_AUTO_IP_ACTION = "no_auto_ip_action"
    RESUME = "resume"


class MedicalWritingInterventionIpRegimen(WorkbenchModel):
    regimen_id: str = Field(min_length=1, max_length=120)
    product_name: str = Field(default="", max_length=240)
    product_role: InterventionRulesProductRole = (
        InterventionRulesProductRole.INVESTIGATIONAL_PRODUCT
    )
    dose_and_frequency: str = Field(default="", max_length=2_000)
    route: str = Field(default="", max_length=240)
    treatment_period: str = Field(default="", max_length=2_000)
    adherence_notes: str = Field(default="", max_length=2_000)
    source_location: str = Field(default="", max_length=500)


class MedicalWritingInterventionIpActionRule(WorkbenchModel):
    rule_id: str = Field(min_length=1, max_length=120)
    action_kind: InterventionRulesIpActionKind = (
        InterventionRulesIpActionKind.OTHER
    )
    trigger: str = Field(default="", max_length=2_000)
    severity_or_threshold: str = Field(default="", max_length=2_000)
    confirmation_required: str = Field(default="", max_length=2_000)
    exceptions: List[str] = Field(default_factory=list, max_length=50)
    study_product_action: str = Field(default="", max_length=2_000)
    retest_recovery: str = Field(default="", max_length=2_000)
    approvers: List[str] = Field(default_factory=list, max_length=50)
    wait_period: str = Field(default="", max_length=2_000)
    permanent_discontinuation_condition: str = Field(default="", max_length=2_000)
    taper_steps: List[str] = Field(default_factory=list, max_length=50)
    linked_non_ip_rule_ids: List[str] = Field(default_factory=list, max_length=50)
    source_location: str = Field(default="", max_length=500)
    notes: str = Field(default="", max_length=4_000)


class MedicalWritingInterventionNonIpTreatmentRule(WorkbenchModel):
    rule_id: str = Field(min_length=1, max_length=120)
    rule_class: InterventionRulesNonIpRuleClass = (
        InterventionRulesNonIpRuleClass.BACKGROUND
    )
    policy: InterventionRulesNonIpPolicy = InterventionRulesNonIpPolicy.ALLOWED
    agent_or_category: str = Field(default="", max_length=240)
    collection_window: str = Field(default="", max_length=240)
    timing_restrictions: List[str] = Field(default_factory=list, max_length=50)
    washout_or_window: str = Field(default="", max_length=2_000)
    cm_dose_rule: str = Field(default="", max_length=2_000)
    phase_applicability: str = Field(default="", max_length=240)
    exceptions: List[str] = Field(default_factory=list, max_length=50)
    source_location: str = Field(default="", max_length=500)
    notes: str = Field(default="", max_length=4_000)


class MedicalWritingInterventionCrossObjectLink(WorkbenchModel):
    link_id: str = Field(min_length=1, max_length=120)
    source_rule_id: str = Field(min_length=1, max_length=120)
    source_kind: InterventionRulesLinkSourceKind = (
        InterventionRulesLinkSourceKind.CM
    )
    target_kind: Literal["ip"] = "ip"
    target_rule_id: str = Field(default="", max_length=120)
    action: InterventionRulesLinkAction = (
        InterventionRulesLinkAction.NO_AUTO_IP_ACTION
    )
    resume_condition: str = Field(default="", max_length=2_000)
    notes: str = Field(default="", max_length=4_000)
    source_location: str = Field(default="", max_length=500)


class MedicalWritingInterventionRules(WorkbenchModel):
    """Additive structured intervention rules contract.

    Authority rules:
    - ``authority = legacy`` (default): the legacy 4 PICOS fields remain
      authoritative. The structured block, when present, is opt-in.
    - ``authority = structured``: the structured objects are canonical; the
      legacy 4 fields become deterministic compatibility projections and are
      no longer independent editable truth. IP action rules are never
      projected into CM-family fields.
    """

    schema_version: Literal["medical_writing_intervention_rules_v1"] = (
        "medical_writing_intervention_rules_v1"
    )
    authority: InterventionRulesAuthority = InterventionRulesAuthority.LEGACY
    ip_regimens: List[MedicalWritingInterventionIpRegimen] = Field(
        default_factory=list, max_length=100
    )
    ip_adjustment_policy: InterventionRulesIpAdjustmentPolicy = (
        InterventionRulesIpAdjustmentPolicy.UNSPECIFIED
    )
    no_planned_adjustment_statement: str = Field(default="", max_length=4_000)
    ip_action_rules: List[MedicalWritingInterventionIpActionRule] = Field(
        default_factory=list, max_length=100
    )
    non_ip_treatment_rules: List[MedicalWritingInterventionNonIpTreatmentRule] = Field(
        default_factory=list, max_length=200
    )
    cross_object_links: List[MedicalWritingInterventionCrossObjectLink] = Field(
        default_factory=list, max_length=200
    )

    @model_validator(mode="after")
    def validate_structured_rules(self) -> "MedicalWritingInterventionRules":
        if self.no_planned_adjustment_statement:
            self.no_planned_adjustment_statement = (
                self.no_planned_adjustment_statement.strip()
            )
        # ID uniqueness across all 4 collections. Dispatch by class because
        # IpRegimen uses ``regimen_id`` while Action/NonIP rules use
        # ``rule_id`` and CrossObjectLink uses ``link_id``. The runtime classes
        # are defined above this class body, so the isinstance lookup resolves
        # at validator-call time.
        seen: dict[str, str] = {}
        for collection_name, items in (
            ("ip_regimens", self.ip_regimens),
            ("ip_action_rules", self.ip_action_rules),
            ("non_ip_treatment_rules", self.non_ip_treatment_rules),
            ("cross_object_links", self.cross_object_links),
        ):
            for item in items:
                if isinstance(item, MedicalWritingInterventionIpRegimen):
                    key = (item.regimen_id or "").strip()
                elif isinstance(item, MedicalWritingInterventionCrossObjectLink):
                    key = (item.link_id or "").strip()
                else:
                    key = (item.rule_id or "").strip()
                if not key:
                    raise ValueError(
                        f"intervention_rules.{collection_name} entries must carry a nonblank id"
                    )
                if key in seen:
                    raise ValueError(
                        "intervention_rules ids must be unique across all collections: "
                        f"id {key!r} appears in both {seen[key]} and {collection_name}"
                    )
                seen[key] = collection_name
        ip_action_ids = {
            item.rule_id for item in self.ip_action_rules if item.rule_id
        }
        non_ip_ids = {
            item.rule_id for item in self.non_ip_treatment_rules if item.rule_id
        }
        non_ip_by_id = {
            item.rule_id: item for item in self.non_ip_treatment_rules if item.rule_id
        }
        # policy invariants.
        if (
            self.ip_adjustment_policy
            == InterventionRulesIpAdjustmentPolicy.NO_PLANNED_ADJUSTMENT
            and not self.no_planned_adjustment_statement
        ):
            raise ValueError(
                "no_planned_adjustment policy requires a nonblank no_planned_adjustment_statement"
            )
        if (
            self.ip_adjustment_policy
            == InterventionRulesIpAdjustmentPolicy.PROTOCOL_DEFINED
            and not self.ip_action_rules
        ):
            raise ValueError(
                "protocol_defined policy requires at least one ip_action_rule"
            )
        for action_rule in self.ip_action_rules:
            unknown_linked_ids = sorted(
                set(action_rule.linked_non_ip_rule_ids) - non_ip_ids
            )
            if unknown_linked_ids:
                raise ValueError(
                    "ip_action_rule.linked_non_ip_rule_ids must reference existing "
                    "non_ip_treatment_rules: " + ", ".join(unknown_linked_ids)
                )
        # Cross-object link integrity.
        non_ip_source_kinds = {
            InterventionRulesLinkSourceKind.RESCUE,
            InterventionRulesLinkSourceKind.CM,
            InterventionRulesLinkSourceKind.BACKGROUND,
            InterventionRulesLinkSourceKind.OTHER_NON_IP,
        }
        for link in self.cross_object_links:
            if link.source_rule_id not in non_ip_ids:
                raise ValueError(
                    "cross_object_link.source_rule_id must reference an existing "
                    f"non_ip_treatment_rules rule: {link.source_rule_id!r}"
                )
            if link.source_kind not in non_ip_source_kinds:
                raise ValueError(
                    f"cross_object_link.source_kind {link.source_kind!r} is not a non-IP source"
                )
            source_rule = non_ip_by_id[link.source_rule_id]
            expected_source_kind = {
                InterventionRulesNonIpRuleClass.RESCUE: InterventionRulesLinkSourceKind.RESCUE,
                InterventionRulesNonIpRuleClass.ALLOWED_CM: InterventionRulesLinkSourceKind.CM,
                InterventionRulesNonIpRuleClass.PROHIBITED_CM: InterventionRulesLinkSourceKind.CM,
                InterventionRulesNonIpRuleClass.BACKGROUND: InterventionRulesLinkSourceKind.BACKGROUND,
                InterventionRulesNonIpRuleClass.OTHER_NON_INVESTIGATIONAL: InterventionRulesLinkSourceKind.OTHER_NON_IP,
            }[source_rule.rule_class]
            if link.source_kind != expected_source_kind:
                raise ValueError(
                    "cross_object_link.source_kind must match the referenced non-IP "
                    f"rule class: expected {expected_source_kind.value!r} for "
                    f"{source_rule.rule_class.value!r}, got {link.source_kind.value!r}"
                )
            if link.target_rule_id and link.target_rule_id not in ip_action_ids:
                raise ValueError(
                    "cross_object_link.target_rule_id must reference an existing "
                    f"ip_action_rule when nonblank: {link.target_rule_id!r}"
                )
        return self

    @classmethod
    def from_legacy_fields(
        cls,
        *,
        intervention_dose_regimen: str = "",
        required_background_rules: list[str] | None = None,
        allowed_concomitant_rules: list[str] | None = None,
        prohibited_concomitant_rules: list[str] | None = None,
    ) -> "MedicalWritingInterventionRules":
        """Deterministically materialize structured rules from legacy fields.

        This is the migration path for legacy PICOS payloads that lack an
        ``intervention_rules`` block. The result is idempotent: running it
        twice on the same input produces the same structured objects.
        Source meaning is preserved losslessly; no stronger policy than the
        input supports is inferred.
        """
        ip_regimens: list[MedicalWritingInterventionIpRegimen] = []
        dose_text = (intervention_dose_regimen or "").strip()
        if dose_text:
            ip_regimens.append(
                MedicalWritingInterventionIpRegimen(
                    regimen_id="investigational_product_regimen",
                    product_role=InterventionRulesProductRole.INVESTIGATIONAL_PRODUCT,
                    dose_and_frequency=dose_text,
                )
            )

        non_ip_rules: list[MedicalWritingInterventionNonIpTreatmentRule] = []

        def _add_rules(
            strings: list[str] | None,
            rule_class: InterventionRulesNonIpRuleClass,
            id_prefix: str,
        ) -> None:
            if not strings:
                return
            for idx, text in enumerate(strings):
                text = (text or "").strip()
                if not text:
                    continue
                non_ip_rules.append(
                    MedicalWritingInterventionNonIpTreatmentRule(
                        rule_id=f"{id_prefix}_{idx + 1:03d}",
                        rule_class=rule_class,
                        agent_or_category=text,
                    )
                )

        _add_rules(
            required_background_rules,
            InterventionRulesNonIpRuleClass.BACKGROUND,
            "background",
        )
        _add_rules(
            allowed_concomitant_rules,
            InterventionRulesNonIpRuleClass.ALLOWED_CM,
            "allowed_cm",
        )
        _add_rules(
            prohibited_concomitant_rules,
            InterventionRulesNonIpRuleClass.PROHIBITED_CM,
            "prohibited_cm",
        )

        return cls(
            authority=InterventionRulesAuthority.LEGACY,
            ip_regimens=ip_regimens,
            non_ip_treatment_rules=non_ip_rules,
        )


class MedicalWritingPicosDefinition(WorkbenchModel):
    design_archetype: Literal[
        "",
        "randomized_confirmatory",
        "randomized_exploratory",
        "single_arm_early_phase",
        "open_label_extension",
        "other",
    ] = ""
    field_applicability: Dict[str, MedicalWritingPicosFieldApplicability] = Field(
        default_factory=dict
    )
    population_summary: str = Field(default="", max_length=5_000)
    inclusion_modules: List[str] = Field(default_factory=list, max_length=100)
    exclusion_modules: List[str] = Field(default_factory=list, max_length=100)
    washout_rules: List[str] = Field(default_factory=list, max_length=100)
    intervention_summary: str = Field(default="", max_length=5_000)
    intervention_dose_regimen: str = Field(default="", max_length=5_000)
    allowed_concomitant_rules: List[str] = Field(default_factory=list, max_length=100)
    required_background_rules: List[str] = Field(default_factory=list, max_length=100)
    prohibited_concomitant_rules: List[str] = Field(default_factory=list, max_length=100)
    assessment_timing_restrictions: List[str] = Field(default_factory=list, max_length=100)
    intervention_rules: Optional[MedicalWritingInterventionRules] = None
    comparator_summary: str = Field(default="", max_length=5_000)
    primary_objectives: List[str] = Field(default_factory=list, max_length=50)
    secondary_objectives: List[str] = Field(default_factory=list, max_length=100)
    exploratory_objectives: List[str] = Field(default_factory=list, max_length=100)
    primary_endpoint: str = Field(default="", max_length=5_000)
    key_secondary_endpoints: List[str] = Field(default_factory=list, max_length=100)
    other_secondary_endpoints: List[str] = Field(default_factory=list, max_length=100)
    exploratory_endpoints: List[str] = Field(default_factory=list, max_length=100)
    safety_endpoints: List[str] = Field(default_factory=list, max_length=100)
    aesi_definitions: List[str] = Field(default_factory=list, max_length=100)
    assessment_instruments: List[MedicalWritingAssessmentInstrumentUse] = Field(
        default_factory=list, max_length=100
    )
    study_epochs: List[str] = Field(default_factory=list, max_length=50)
    visit_strategy: str = Field(default="", max_length=5_000)
    estimand_strategy: str = Field(default="", max_length=5_000)
    sample_size_strategy: str = Field(default="", max_length=5_000)
    statistical_strategy: str = Field(default="", max_length=5_000)

    @model_validator(mode="after")
    def normalize_picos(self):
        scalar_fields = (
            "population_summary",
            "intervention_summary",
            "intervention_dose_regimen",
            "comparator_summary",
            "primary_endpoint",
            "visit_strategy",
            "estimand_strategy",
            "sample_size_strategy",
            "statistical_strategy",
        )
        for field_name in scalar_fields:
            setattr(self, field_name, getattr(self, field_name).strip())
        list_fields = (
            "inclusion_modules",
            "exclusion_modules",
            "washout_rules",
            "allowed_concomitant_rules",
            "required_background_rules",
            "prohibited_concomitant_rules",
            "assessment_timing_restrictions",
            "primary_objectives",
            "secondary_objectives",
            "exploratory_objectives",
            "key_secondary_endpoints",
            "other_secondary_endpoints",
            "exploratory_endpoints",
            "safety_endpoints",
            "aesi_definitions",
            "study_epochs",
        )
        for field_name in list_fields:
            values = [item.strip() for item in getattr(self, field_name) if item.strip()]
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must be unique")
            setattr(self, field_name, values)
        instrument_ids = [item.instrument_id for item in self.assessment_instruments]
        if len(instrument_ids) != len(set(instrument_ids)):
            raise ValueError("assessment instrument ids must be unique")
        supported_applicability_fields = {"comparator_summary", "estimand_strategy"}
        unsupported = set(self.field_applicability) - supported_applicability_fields
        if unsupported:
            raise ValueError(
                "unsupported PICOS applicability field(s): " + ", ".join(sorted(unsupported))
            )
        for field_name, decision in self.field_applicability.items():
            if decision.status != "not_applicable":
                continue
            if getattr(self, field_name):
                raise ValueError(
                    f"{field_name} cannot contain a value when marked not applicable"
                )
            if self.design_archetype == "randomized_confirmatory":
                raise ValueError(
                    f"{field_name} cannot be marked not applicable for a randomized confirmatory design"
                )
            if (
                self.design_archetype == "randomized_exploratory"
                and field_name == "comparator_summary"
            ):
                raise ValueError(
                    "comparator_summary cannot be marked not applicable for a randomized exploratory design"
                )
        return self

    def missing_required_fields(self) -> List[str]:
        missing = []
        if not self.design_archetype:
            missing.append("design_archetype")
        required = {
            "population_summary": self.population_summary,
            "inclusion_modules": self.inclusion_modules,
            "exclusion_modules": self.exclusion_modules,
            "intervention_summary": self.intervention_summary,
            "intervention_dose_regimen": self.intervention_dose_regimen,
            "primary_endpoint": self.primary_endpoint,
            "safety_endpoints": self.safety_endpoints,
            "study_epochs": self.study_epochs,
            "visit_strategy": self.visit_strategy,
            "sample_size_strategy": self.sample_size_strategy,
            "statistical_strategy": self.statistical_strategy,
        }
        missing.extend(key for key, value in required.items() if not value)
        for field_name, value in (
            ("comparator_summary", self.comparator_summary),
            ("estimand_strategy", self.estimand_strategy),
        ):
            if value:
                continue
            decision = self.field_applicability.get(field_name)
            allowed_not_applicable = self.design_archetype in {
                "randomized_exploratory",
                "single_arm_early_phase",
                "open_label_extension",
                "other",
            } and not (
                self.design_archetype == "randomized_exploratory"
                and field_name == "comparator_summary"
            )
            if not (
                allowed_not_applicable
                and decision is not None
                and decision.status == "not_applicable"
                and len(decision.reason) >= 10
                and decision.confirmed_by_medical_manager
            ):
                missing.append(field_name)
        return missing

    def project_legacy_intervention_fields(
        self,
    ) -> Dict[str, Any]:
        """Deterministically project structured intervention rules into the legacy
        4 PICOS compatibility fields.

        Only invoked when ``intervention_rules.authority == "structured"``. The
        projection is one-way and never projects IP action rules into the CM
        fields. Returns a dict with keys ``intervention_dose_regimen``,
        ``required_background_rules``, ``allowed_concomitant_rules`` and
        ``prohibited_concomitant_rules``. Callers decide whether to apply the
        projection to the model instance (legacy fields stay required for
        backward compatibility, but the structured block remains canonical).
        """
        rules = self.intervention_rules
        # When authority is not "structured", the legacy 4 fields remain the
        # authoritative editable truth. The structured block, if present, is
        # kept for future migration but must not silently rewrite legacy
        # values. Return the legacy fields unchanged.
        if rules is None or rules.authority != InterventionRulesAuthority.STRUCTURED:
            return {
                "intervention_dose_regimen": self.intervention_dose_regimen,
                "required_background_rules": list(self.required_background_rules),
                "allowed_concomitant_rules": list(self.allowed_concomitant_rules),
                "prohibited_concomitant_rules": list(
                    self.prohibited_concomitant_rules
                ),
            }

        # intervention_dose_regimen: ip_regimens + ip_action_rules + policy.
        regimen_parts: List[str] = []
        for regimen in rules.ip_regimens:
            if not regimen.regimen_id:
                continue
            row = regimen.dose_and_frequency.strip()
            if regimen.product_name:
                row = f"{regimen.product_name}：{row}" if row else regimen.product_name
            if regimen.route:
                row = f"{row}（{regimen.route}）" if row else f"（{regimen.route}）"
            if regimen.treatment_period:
                row = f"{row}；{regimen.treatment_period}" if row else regimen.treatment_period
            if regimen.adherence_notes:
                row = f"{row}。依从：{regimen.adherence_notes}" if row else f"依从：{regimen.adherence_notes}"
            regimen_parts.append(row)
        if (
            rules.ip_adjustment_policy
            == InterventionRulesIpAdjustmentPolicy.NO_PLANNED_ADJUSTMENT
            and rules.no_planned_adjustment_statement
        ):
            regimen_parts.append(
                "剂量调整：" + rules.no_planned_adjustment_statement
            )
        if rules.ip_action_rules:
            rendered = "；".join(
                f"[{rule.action_kind.value}] {rule.trigger} → {rule.study_product_action}".strip()
                for rule in rules.ip_action_rules
                if rule.rule_id
            )
            if rendered:
                regimen_parts.append("剂量调整：" + rendered)
        intervention_dose_regimen = (
            "\n".join(part for part in regimen_parts if part).strip()
        )

        def _label_non_ip(rule: MedicalWritingInterventionNonIpTreatmentRule) -> str:
            bits: List[str] = []
            if rule.agent_or_category:
                bits.append(rule.agent_or_category)
            if rule.collection_window:
                bits.append(rule.collection_window)
            if rule.policy != InterventionRulesNonIpPolicy.ALLOWED:
                bits.append(f"策略={rule.policy.value}")
            if rule.washout_or_window:
                bits.append(f"洗脱/窗口={rule.washout_or_window}")
            if rule.phase_applicability:
                bits.append(f"阶段={rule.phase_applicability}")
            if rule.timing_restrictions:
                bits.append("时序=" + "；".join(rule.timing_restrictions))
            if rule.cm_dose_rule:
                # CM dose rules live only on the non-IP rule; they are never
                # projected into IP action rules or into IP family fields.
                bits.append(f"剂量规则={rule.cm_dose_rule}")
            if rule.notes:
                bits.append(rule.notes)
            head = rule.agent_or_category or rule.rule_id
            tail = "（" + "；".join(bits[1:]) + "）" if len(bits) > 1 else ""
            return f"{head}{tail}".strip()

        required_background_rules: List[str] = []
        allowed_concomitant_rules: List[str] = []
        prohibited_concomitant_rules: List[str] = []
        for rule in rules.non_ip_treatment_rules:
            if not rule.rule_id:
                continue
            label = _label_non_ip(rule)
            if rule.rule_class == InterventionRulesNonIpRuleClass.BACKGROUND:
                required_background_rules.append(label)
            elif rule.rule_class == InterventionRulesNonIpRuleClass.ALLOWED_CM:
                allowed_concomitant_rules.append(label)
            elif rule.rule_class == InterventionRulesNonIpRuleClass.PROHIBITED_CM:
                prohibited_concomitant_rules.append(label)
            # rescue and other_non_investigational are NOT projected into the
            # CM-family legacy fields. They live under non_investigational
            # consumers and never collide with allowed/prohibited CM.

        # CM dose rules stay only on the source non-IP rule. We must never
        # silently expand them into the allowed/prohibited CM lists in a way
        # that reads as an IP action; the projection above places cm_dose_rule
        # only inside the non-IP rule's own text and only when the rule's own
        # rule_class is allowed_cm / prohibited_cm.

        return {
            "intervention_dose_regimen": intervention_dose_regimen,
            "required_background_rules": required_background_rules,
            "allowed_concomitant_rules": allowed_concomitant_rules,
            "prohibited_concomitant_rules": prohibited_concomitant_rules,
        }


class MedicalWritingAuthoringStageDraft(WorkbenchModel):
    stage: Literal["framing", "picos"]
    framing: Optional[MedicalWritingStudyFraming] = None
    picos: Optional[MedicalWritingPicosDefinition] = None
    missing_required_fields: List[str] = Field(default_factory=list)
    saved_from_revision: int = Field(ge=1)
    saved_at: datetime
    saved_by: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_stage_payload(self):
        self.saved_by = self.saved_by.strip()
        if self.stage == "framing" and (self.framing is None or self.picos is not None):
            raise ValueError("framing draft must contain only framing payload")
        if self.stage == "picos" and (self.picos is None or self.framing is not None):
            raise ValueError("PICOS draft must contain only PICOS payload")
        return self


class MedicalWritingSynopsisSource(WorkbenchModel):
    source_id: str
    original_filename: str
    media_type: Literal[
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ]
    actual_size: int = Field(gt=0)
    content_sha256: str = Field(min_length=64, max_length=64)
    extraction_revision: str
    parser_name: str
    source_role_status: Literal["matched", "warning", "mismatch"]
    indication_status: Literal["matched", "warning", "not_assessed"] = "not_assessed"
    validation_warnings: List[str] = Field(default_factory=list)
    imported_at: datetime
    imported_by: str


class MedicalWritingSynopsisEvidenceSpan(WorkbenchModel):
    span_id: str
    source_id: str
    locator: str
    source_text: str = Field(max_length=20_000)
    source_text_sha256: str = Field(min_length=64, max_length=64)


class MedicalWritingSynopsisImport(WorkbenchModel):
    status: Literal[
        "not_started",
        "extraction_pending",
        "review_pending",
        "confirmed",
        "failed",
    ] = "not_started"
    source: Optional[MedicalWritingSynopsisSource] = None
    proposed_framing: MedicalWritingStudyFraming = Field(
        default_factory=MedicalWritingStudyFraming
    )
    proposed_picos: MedicalWritingPicosDefinition = Field(
        default_factory=MedicalWritingPicosDefinition
    )
    proposed_synopsis_text: str = Field(default="", max_length=100_000)
    proposed_synopsis_origin: Literal[
        "imported_text",
        "medical_manager_text",
        "deterministic_projection",
    ] = "imported_text"
    synopsis_bound_value_sha256: Dict[str, str] = Field(default_factory=dict)
    missing_fields: List[str] = Field(default_factory=list)
    conflict_notes: List[str] = Field(default_factory=list)
    field_evidence_span_ids: Dict[str, List[str]] = Field(default_factory=dict)
    field_extracted_value_sha256: Dict[str, str] = Field(default_factory=dict)
    evidence_spans: List[MedicalWritingSynopsisEvidenceSpan] = Field(default_factory=list)
    ai_run_id: str = ""
    failure_reason: str = ""
    confirmed_at: Optional[datetime] = None
    confirmed_by: str = ""


class MedicalWritingStudyFactEvidence(WorkbenchModel):
    source_id: str
    extraction_revision: str
    evidence_span_id: str
    locator: str
    quote_sha256: str = Field(min_length=64, max_length=64)


class MedicalWritingStudyFactState(WorkbenchModel):
    status: Literal[
        "manual_candidate",
        "extracted_candidate",
        "confirmed",
        "missing",
        "conflict",
        "not_applicable",
        "deferred",
    ]
    evidence: List[MedicalWritingStudyFactEvidence] = Field(default_factory=list)
    value_origin: Literal[
        "manual_entry",
        "source_extraction",
        "medical_manager_edit",
    ] = "manual_entry"
    reviewed_by: str = ""
    reviewed_at: Optional[datetime] = None
    confirmed_by: str = ""
    confirmed_at: Optional[datetime] = None


class MedicalWritingStudySchemaSourceBinding(WorkbenchModel):
    study_definition_path: str = Field(default="", max_length=300)
    source_id: str = Field(default="", max_length=200)
    evidence_span_id: str = Field(default="", max_length=200)
    locator: str = Field(default="", max_length=1_000)

    @model_validator(mode="after")
    def require_traceable_binding(self):
        for field_name in (
            "study_definition_path",
            "source_id",
            "evidence_span_id",
            "locator",
        ):
            setattr(self, field_name, getattr(self, field_name).strip())
        if not self.study_definition_path and not (
            self.source_id and (self.evidence_span_id or self.locator)
        ):
            raise ValueError(
                "study-schema source binding requires a StudyDefinition path or source locator"
            )
        return self


class MedicalWritingStudySchemaPart(WorkbenchModel):
    part_id: str = Field(min_length=1, max_length=100)
    order: int = Field(ge=0)
    label: str = Field(min_length=1, max_length=200)
    flow_direction: Literal["left_to_right", "top_to_bottom", "bottom_to_top"] = (
        "left_to_right"
    )
    source_bindings: List[MedicalWritingStudySchemaSourceBinding] = Field(
        default_factory=list, max_length=20
    )


class MedicalWritingStudySchemaNode(WorkbenchModel):
    node_id: str = Field(min_length=1, max_length=100)
    part_id: str = Field(min_length=1, max_length=100)
    order: int = Field(ge=0)
    lane_order: int = Field(default=0, ge=0, le=20)
    node_kind: Literal[
        "entry",
        "screening",
        "run_in",
        "randomization",
        "allocation",
        "arm",
        "dose_cohort",
        "treatment",
        "treatment_switch",
        "extension_period",
        "decision_gate",
        "follow_up",
        "end",
        "other",
    ]
    label: str = Field(min_length=1, max_length=300)
    detail_lines: List[str] = Field(default_factory=list, max_length=12)
    fact_status: Literal[
        "manual_candidate", "extracted_candidate", "confirmed", "missing", "conflict"
    ] = "manual_candidate"
    source_bindings: List[MedicalWritingStudySchemaSourceBinding] = Field(
        default_factory=list, max_length=20
    )

    @model_validator(mode="after")
    def normalize_node_text(self):
        self.label = self.label.strip()
        self.detail_lines = [line.strip() for line in self.detail_lines if line.strip()]
        if len(self.detail_lines) != len(set(self.detail_lines)):
            raise ValueError("study-schema node detail lines must be unique")
        return self


class MedicalWritingStudySchemaEdge(WorkbenchModel):
    edge_id: str = Field(min_length=1, max_length=100)
    from_node_id: str = Field(min_length=1, max_length=100)
    to_node_id: str = Field(min_length=1, max_length=100)
    edge_kind: Literal[
        "participant_flow",
        "activation_dependency",
        "randomization",
        "conditional",
        "treatment_switch",
        "treatment_continuation",
        "discontinuation",
        "follow_up",
    ] = "participant_flow"
    label: str = Field(default="", max_length=300)
    fact_status: Literal[
        "manual_candidate", "extracted_candidate", "confirmed", "missing", "conflict"
    ] = "manual_candidate"
    source_bindings: List[MedicalWritingStudySchemaSourceBinding] = Field(
        default_factory=list, max_length=20
    )

    @model_validator(mode="after")
    def normalize_edge(self):
        self.label = self.label.strip()
        if self.from_node_id == self.to_node_id:
            raise ValueError("study-schema edge cannot reference the same node twice")
        if self.edge_kind == "conditional" and not self.label:
            raise ValueError("conditional study-schema edge requires a label")
        if self.edge_kind in {"treatment_switch", "treatment_continuation"} and not self.label:
            raise ValueError(
                f"{self.edge_kind} study-schema edge requires a label"
            )
        return self


class MedicalWritingStudySchemaDefinition(WorkbenchModel):
    schema_version: str = "medical_writing_study_schema_v1"
    schema_id: str = Field(min_length=1, max_length=100)
    revision: int = Field(ge=1)
    source_facts_sha256: str = Field(min_length=64, max_length=64)
    status: Literal["draft", "confirmed", "stale"] = "draft"
    title: str = Field(default="研究设计概况", min_length=1, max_length=300)
    parts: List[MedicalWritingStudySchemaPart] = Field(min_length=1, max_length=10)
    nodes: List[MedicalWritingStudySchemaNode] = Field(min_length=1, max_length=200)
    edges: List[MedicalWritingStudySchemaEdge] = Field(default_factory=list, max_length=400)
    annotations: List[str] = Field(default_factory=list, max_length=30)
    state_sha256: str = Field(min_length=64, max_length=64)
    updated_at: datetime
    updated_by: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_graph_references(self):
        def unique(values: List[str], label: str) -> set[str]:
            if len(values) != len(set(values)):
                raise ValueError(f"{label} must be unique")
            return set(values)

        part_ids = unique([part.part_id for part in self.parts], "study-schema part ids")
        node_ids = unique([node.node_id for node in self.nodes], "study-schema node ids")
        unique([edge.edge_id for edge in self.edges], "study-schema edge ids")
        if any(node.part_id not in part_ids for node in self.nodes):
            raise ValueError("study-schema node references an unknown study part")
        if any(
            edge.from_node_id not in node_ids or edge.to_node_id not in node_ids
            for edge in self.edges
        ):
            raise ValueError("study-schema edge references an unknown node")
        node_by_id = {node.node_id: node for node in self.nodes}
        for edge in self.edges:
            if (
                edge.edge_kind == "participant_flow"
                and node_by_id[edge.from_node_id].node_kind == "dose_cohort"
                and node_by_id[edge.to_node_id].node_kind == "dose_cohort"
            ):
                raise ValueError(
                    "dose-cohort progression must use activation_dependency, not participant_flow"
                )
        self.title = self.title.strip()
        self.annotations = [item.strip() for item in self.annotations if item.strip()]
        if len(self.annotations) != len(set(self.annotations)):
            raise ValueError("study-schema annotations must be unique")
        return self


class MedicalWritingStudySchemaLayoutOverride(WorkbenchModel):
    node_id: str = Field(min_length=1, max_length=100)
    dx: int = Field(default=0, ge=-48, le=48)
    dy: int = Field(default=0, ge=-32, le=32)


class MedicalWritingStudySchemaPresentation(WorkbenchModel):
    schema_id: str = Field(min_length=1, max_length=100)
    schema_revision: int = Field(ge=1)
    source_schema_sha256: str = Field(min_length=64, max_length=64)
    layout_revision: int = Field(ge=0)
    node_overrides: List[MedicalWritingStudySchemaLayoutOverride] = Field(
        default_factory=list, max_length=200
    )
    updated_at: datetime
    updated_by: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_layout_identity(self):
        node_ids = [item.node_id for item in self.node_overrides]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("study-schema layout node overrides must be unique")
        return self


class MedicalWritingStudySchemaValidationIssue(WorkbenchModel):
    issue_id: str = Field(min_length=1, max_length=160)
    severity: Literal["blocker", "warning"]
    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=500)
    target_id: str = Field(default="", max_length=100)


class MedicalWritingStudySchemaSnapshot(WorkbenchModel):
    project_id: str
    journey_revision: int = Field(ge=1)
    study_definition_revision: int = Field(ge=1)
    study_definition_sha256: str = Field(min_length=64, max_length=64)
    study_schema: Optional[MedicalWritingStudySchemaDefinition] = None
    presentation: Optional[MedicalWritingStudySchemaPresentation] = None
    issues: List[MedicalWritingStudySchemaValidationIssue] = Field(default_factory=list)
    formal_render_allowed: bool = False
    svg_sha256: str = ""
    svg: str = ""


class MedicalWritingStudySchemaImpactPreviewRequest(WorkbenchModel):
    expected_journey_revision: int = Field(ge=1)
    study_schema: MedicalWritingStudySchemaDefinition


class MedicalWritingStudySchemaImpactPreview(WorkbenchModel):
    preview_id: str
    project_id: str
    expected_journey_revision: int = Field(ge=1)
    changed_fields: List[str] = Field(default_factory=list)
    affected_dependents: List[str] = Field(default_factory=list)
    issues: List[MedicalWritingStudySchemaValidationIssue] = Field(default_factory=list)
    requires_confirmation: bool = False
    formal_render_allowed: bool = False
    svg_sha256: str = ""
    svg: str = ""


class MedicalWritingStudySchemaCommitRequest(MedicalWritingStudySchemaImpactPreviewRequest):
    impact_preview_id: str = ""
    reason: str = Field(min_length=10, max_length=2_000)
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def normalize_schema_commit(self):
        self.impact_preview_id = self.impact_preview_id.strip()
        self.reason = self.reason.strip()
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if len(self.reason) < 10:
            raise ValueError("study-schema change reason must contain at least 10 characters")
        return self


class MedicalWritingStudySchemaLayoutUpdateRequest(WorkbenchModel):
    expected_journey_revision: int = Field(ge=1)
    expected_schema_revision: int = Field(ge=1)
    expected_layout_revision: int = Field(ge=0)
    node_overrides: List[MedicalWritingStudySchemaLayoutOverride] = Field(
        default_factory=list, max_length=200
    )
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def normalize_layout_update(self):
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        node_ids = [item.node_id for item in self.node_overrides]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("study-schema layout node overrides must be unique")
        return self


class MedicalWritingStudySchemaFigureProjectRequest(WorkbenchModel):
    expected_journey_revision: int = Field(ge=1)
    expected_schema_revision: int = Field(ge=1)
    expected_layout_revision: int = Field(ge=0)
    expected_working_copy_revision: int = Field(ge=0)
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    reason: str = Field(min_length=10, max_length=2_000)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def normalize_projection_request(self):
        self.actor = self.actor.strip()
        self.reason = self.reason.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if not self.actor or not self.idempotency_key:
            raise ValueError("study-schema figure projection identity must not be blank")
        return self


class MedicalWritingInterventionRulesProjectRequest(WorkbenchModel):
    expected_journey_revision: int = Field(ge=1)
    expected_intervention_rules_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    expected_working_copy_revision: int = Field(ge=0)
    overwrite_medical_edits: bool = False
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    reason: str = Field(min_length=10, max_length=2_000)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def normalize_projection_request(self):
        self.actor = self.actor.strip()
        self.reason = self.reason.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if not self.actor or not self.idempotency_key:
            raise ValueError(
                "intervention-rules projection identity must not be blank"
            )
        return self


class MedicalWritingStudyDefinition(WorkbenchModel):
    definition_id: str
    project_id: str
    revision: int = Field(ge=1)
    schema_version: str = "medical_writing_study_definition_v2"
    origin: Literal[
        "guided_greenfield",
        "imported_synopsis",
        "full_protocol_import",
    ]
    framing: MedicalWritingStudyFraming = Field(default_factory=MedicalWritingStudyFraming)
    picos: MedicalWritingPicosDefinition = Field(default_factory=MedicalWritingPicosDefinition)
    study_schema: Optional[MedicalWritingStudySchemaDefinition] = None
    synopsis_text: str = Field(default="", max_length=100_000)
    synopsis_origin: Literal[
        "imported_text",
        "medical_manager_text",
        "deterministic_projection",
    ] = "deterministic_projection"
    field_states: Dict[str, MedicalWritingStudyFactState] = Field(default_factory=dict)
    module_resolutions: Dict[str, MedicalWritingProtocolModuleResolution] = Field(
        default_factory=dict
    )
    source_artifact_ids: List[str] = Field(default_factory=list)
    unresolved_paths: List[str] = Field(default_factory=list)
    state_sha256: str = Field(min_length=64, max_length=64)
    created_at: datetime
    updated_at: datetime
    updated_by: str

    @model_validator(mode="after")
    def migrate_study_definition_schema(self):
        self.schema_version = "medical_writing_study_definition_v2"
        nested_roots = {
            "framing.product_profile": self.framing.product_profile.model_dump(
                mode="json"
            ),
            "framing.structured_design": self.framing.structured_design.model_dump(
                mode="json"
            ),
        }
        if self.picos.intervention_rules is not None:
            nested_roots["picos.intervention_rules"] = (
                self.picos.intervention_rules.model_dump(mode="json")
            )
        unresolved_sentinels = {
            "unknown",
            "undecided",
            "not_assessed",
            "not_started",
        }
        migrated_states = dict(self.field_states)
        migration_applied = False

        def has_material_value(value: Any) -> bool:
            if value is False or value == 0:
                return True
            if isinstance(value, dict):
                return any(has_material_value(item) for item in value.values())
            if isinstance(value, list):
                return any(has_material_value(item) for item in value)
            return value not in ("", None)

        def walk(path: str, value: Any):
            if not isinstance(value, dict):
                return
            for child_name, child_value in value.items():
                if child_name == "schema_version":
                    continue
                child_path = f"{path}.{child_name}"
                if not has_material_value(child_value):
                    continue
                yield child_path, child_value
                yield from walk(child_path, child_value)

        for root_path, root_value in nested_roots.items():
            parent_state = migrated_states.get(root_path)
            if parent_state is None:
                continue
            metadata_path = f"{root_path}.schema_version"
            if metadata_path in migrated_states:
                migrated_states.pop(metadata_path)
                migration_applied = True
            for path, value in walk(root_path, root_value):
                sentinel = (
                    isinstance(value, str)
                    and value.strip().lower() in unresolved_sentinels
                )
                if sentinel:
                    current_state = migrated_states.get(path, parent_state)
                    migrated_states[path] = MedicalWritingStudyFactState(
                        status="deferred",
                        evidence=list(current_state.evidence),
                        value_origin=current_state.value_origin,
                        reviewed_by=current_state.reviewed_by,
                        reviewed_at=current_state.reviewed_at,
                    )
                    if current_state.status != "deferred" or current_state.confirmed_by:
                        migration_applied = True
                    continue
                if path in migrated_states:
                    continue
                inherited_status = parent_state.status
                if inherited_status == "missing":
                    inherited_status = (
                        "extracted_candidate"
                        if parent_state.evidence
                        else "manual_candidate"
                    )
                migrated_states[path] = parent_state.model_copy(
                    update={"status": inherited_status},
                    deep=True,
                )
                migration_applied = True

        if migration_applied:
            self.field_states = migrated_states
            self.unresolved_paths = sorted(
                path
                for path, state in migrated_states.items()
                if state.status not in {"confirmed", "not_applicable"}
            )
            self.revision += 1
            payload = self.model_dump(mode="json", exclude={"state_sha256"})
            self.state_sha256 = medical_writing_protocol_assembly_sha256(payload)
        for semantic_node_id, resolution in self.module_resolutions.items():
            if semantic_node_id != resolution.semantic_node_id:
                raise ValueError(
                    "study-definition module resolution key must match semantic node id"
                )
        return self


MEDICAL_WRITING_PROTOCOL_ASSEMBLY_PROJECTIONS = (
    "synopsis",
    "sections_toc",
    "soa",
    "study_schema_flowchart",
    "evidence_intent",
    "ai_candidate_intent",
    "docx_toc",
)


def medical_writing_protocol_assembly_sha256(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")

    def canonical_default(item: Any) -> Any:
        if isinstance(item, BaseModel):
            return item.model_dump(mode="json")
        if isinstance(item, datetime):
            encoded = item.isoformat()
            return encoded[:-6] + "Z" if encoded.endswith("+00:00") else encoded
        if isinstance(item, Enum):
            return item.value
        raise TypeError(f"unsupported protocol assembly hash value: {type(item)!r}")

    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=canonical_default,
        ).encode("utf-8")
    ).hexdigest()


class MedicalWritingProtocolAssemblyFactReference(WorkbenchModel):
    fact_id: str = Field(min_length=1, max_length=300)
    fact_path: str = Field(min_length=1, max_length=300)
    value_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def normalize_reference(self):
        self.fact_id = self.fact_id.strip()
        self.fact_path = self.fact_path.strip()
        return self


class MedicalWritingProtocolAssemblyDesignDriver(WorkbenchModel):
    driver_id: str = Field(min_length=1, max_length=220)
    driver_kind: Literal[
        "phase",
        "indication",
        "drug_modality",
        "drug_route",
        "dosage_form",
        "exposure_scope",
        "phase1_part",
        "randomization",
        "blinding",
        "control",
        "allocation",
        "background_treatment",
        "interim_analysis",
        "treatment_switch",
        "crossover",
        "open_label_extension",
        "sample_size_reestimation",
        "adaptive_design",
        "src",
        "dmc",
        "pk_pd",
        "aesi",
        "analysis_set",
        "soa",
        "study_schema_flowchart",
        "ip_regimen",
        "active_comparator",
        "placebo",
        "dose_action",
        "safety",
    ]
    decision_state: Literal["required", "design_driven", "not_applicable", "unknown"]
    fact_path: str = Field(min_length=1, max_length=300)
    source_references: List[MedicalWritingProtocolAssemblyFactReference] = Field(
        min_length=1, max_length=20
    )
    rationale: str = Field(min_length=1, max_length=1_000)
    value_summary: str = Field(default="", max_length=800)
    projection_targets: List[
        Literal[
            "synopsis",
            "sections_toc",
            "soa",
            "study_schema_flowchart",
            "evidence_intent",
            "ai_candidate_intent",
            "docx_toc",
        ]
    ] = Field(min_length=1, max_length=7)
    driver_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_design_driver(self):
        for field_name in ("driver_id", "fact_path", "rationale", "value_summary"):
            setattr(self, field_name, getattr(self, field_name).strip())
        if len(self.projection_targets) != len(set(self.projection_targets)):
            raise ValueError("protocol assembly driver projection targets must be unique")
        source_paths = [item.fact_path for item in self.source_references]
        if len(source_paths) != len(set(source_paths)):
            raise ValueError("protocol assembly driver source paths must be unique")
        if self.value_summary and self.decision_state == "unknown":
            raise ValueError("unknown protocol assembly drivers cannot carry a value summary")
        expected_hash = medical_writing_protocol_assembly_sha256(
            self.model_dump(mode="json", exclude={"driver_sha256"})
        )
        if self.driver_sha256 != expected_hash:
            raise ValueError("protocol assembly design driver hash mismatch")
        return self


class MedicalWritingProtocolAssemblyUnresolvedQuestion(WorkbenchModel):
    question_id: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=120)
    fact_path: str = Field(min_length=1, max_length=300)
    prompt: str = Field(min_length=1, max_length=1_000)
    severity: Literal["warning", "blocker"] = "blocker"

    @model_validator(mode="after")
    def normalize_question(self):
        for field_name in ("question_id", "code", "fact_path", "prompt"):
            setattr(self, field_name, getattr(self, field_name).strip())
        return self


class MedicalWritingProtocolAssemblyModuleResolution(WorkbenchModel):
    module_id: str = Field(min_length=1, max_length=200)
    applicability: Literal[
        "required",
        "conditional_applicable",
        "not_applicable",
    ]
    reason: str = Field(min_length=1, max_length=1_000)
    fact_references: List[MedicalWritingProtocolAssemblyFactReference] = Field(
        default_factory=list, max_length=50
    )
    unresolved_questions: List[
        MedicalWritingProtocolAssemblyUnresolvedQuestion
    ] = Field(default_factory=list, max_length=50)
    blocking_severity: Literal["none", "warning", "blocker"] = "none"
    deterministic_projection_allowed: bool = True
    projection_targets: List[
        Literal[
            "synopsis",
            "sections_toc",
            "soa",
            "study_schema_flowchart",
            "evidence_intent",
            "ai_candidate_intent",
            "docx_toc",
        ]
    ] = Field(min_length=1, max_length=7)
    resolution_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_resolution(self):
        self.module_id = self.module_id.strip()
        self.reason = self.reason.strip()
        fact_paths = [item.fact_path for item in self.fact_references]
        if len(fact_paths) != len(set(fact_paths)):
            raise ValueError("protocol assembly fact reference paths must be unique")
        question_ids = [item.question_id for item in self.unresolved_questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("protocol assembly unresolved question ids must be unique")
        if len(self.projection_targets) != len(set(self.projection_targets)):
            raise ValueError("protocol assembly projection targets must be unique")
        if self.unresolved_questions:
            expected_severity = (
                "blocker"
                if any(item.severity == "blocker" for item in self.unresolved_questions)
                else "warning"
            )
            if self.blocking_severity != expected_severity:
                raise ValueError(
                    "protocol assembly resolution severity must match its "
                    "unresolved questions"
                )
            if self.deterministic_projection_allowed:
                raise ValueError(
                    "unresolved protocol assembly facts cannot allow deterministic projection"
                )
        elif self.blocking_severity == "blocker":
            raise ValueError("a blocker resolution requires an unresolved question")
        expected_hash = medical_writing_protocol_assembly_sha256(
            self.model_dump(mode="json", exclude={"resolution_sha256"})
        )
        if self.resolution_sha256 != expected_hash:
            raise ValueError("protocol assembly module resolution hash mismatch")
        return self


class MedicalWritingProtocolAssemblyProjectionManifest(WorkbenchModel):
    projection: Literal[
        "synopsis",
        "sections_toc",
        "soa",
        "study_schema_flowchart",
        "evidence_intent",
        "ai_candidate_intent",
        "docx_toc",
    ]
    applicable_module_ids: List[str] = Field(default_factory=list, max_length=200)
    not_applicable_module_ids: List[str] = Field(default_factory=list, max_length=200)
    unresolved_module_ids: List[str] = Field(default_factory=list, max_length=200)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_manifest_lists(self):
        groups = (
            self.applicable_module_ids,
            self.not_applicable_module_ids,
            self.unresolved_module_ids,
        )
        for values in groups:
            if values != sorted(set(values)):
                raise ValueError(
                    "protocol assembly projection module ids must be sorted and unique"
                )
        flattened = [module_id for values in groups for module_id in values]
        if len(flattened) != len(set(flattened)):
            raise ValueError(
                "protocol assembly projection module classifications must be disjoint"
            )
        return self


class MedicalWritingProtocolAssemblyPlan(WorkbenchModel):
    schema_version: Literal["medical_writing_protocol_assembly_plan_v1"] = (
        "medical_writing_protocol_assembly_plan_v1"
    )
    plan_id: str = Field(min_length=1, max_length=200)
    revision: int = Field(ge=1)
    project_id: str = Field(min_length=1, max_length=200)
    source_definition_id: str = Field(min_length=1, max_length=200)
    source_definition_revision: int = Field(ge=1)
    source_definition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    modules: List[MedicalWritingProtocolAssemblyModuleResolution] = Field(
        min_length=1, max_length=300
    )
    design_drivers: List[MedicalWritingProtocolAssemblyDesignDriver] = Field(
        default_factory=list, max_length=300
    )
    projection_manifest: List[
        MedicalWritingProtocolAssemblyProjectionManifest
    ] = Field(min_length=7, max_length=7)
    previous_plan_revision: int = Field(default=0, ge=0)
    affected_module_ids: List[str] = Field(default_factory=list, max_length=300)
    affected_projections: List[
        Literal[
            "synopsis",
            "sections_toc",
            "soa",
            "study_schema_flowchart",
            "evidence_intent",
            "ai_candidate_intent",
            "docx_toc",
        ]
    ] = Field(default_factory=list, max_length=7)
    confirmation_status: Literal["draft", "author_confirmed"] = "draft"
    confirmation_kind: Literal["author_plan_confirmation"] = (
        "author_plan_confirmation"
    )
    created_by: str = Field(min_length=1, max_length=100)
    created_at: datetime
    updated_by: str = Field(min_length=1, max_length=100)
    updated_at: datetime
    confirmed_by: str = Field(default="", max_length=100)
    confirmed_at: Optional[datetime] = None
    state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_plan(self):
        for field_name in (
            "plan_id",
            "project_id",
            "source_definition_id",
            "created_by",
            "updated_by",
            "confirmed_by",
        ):
            setattr(self, field_name, getattr(self, field_name).strip())
        module_by_id = {item.module_id: item for item in self.modules}
        if len(module_by_id) != len(self.modules):
            raise ValueError("protocol assembly module ids must be unique")
        if [item.module_id for item in self.modules] != sorted(module_by_id):
            raise ValueError("protocol assembly modules must be sorted by module id")
        driver_by_id = {item.driver_id: item for item in self.design_drivers}
        if len(driver_by_id) != len(self.design_drivers):
            raise ValueError("protocol assembly design driver ids must be unique")
        if [item.driver_id for item in self.design_drivers] != sorted(driver_by_id):
            raise ValueError("protocol assembly design drivers must be sorted by id")
        manifest_by_projection = {
            item.projection: item for item in self.projection_manifest
        }
        if set(manifest_by_projection) != set(
            MEDICAL_WRITING_PROTOCOL_ASSEMBLY_PROJECTIONS
        ):
            raise ValueError(
                "protocol assembly plan requires every deterministic projection"
            )
        if [item.projection for item in self.projection_manifest] != list(
            MEDICAL_WRITING_PROTOCOL_ASSEMBLY_PROJECTIONS
        ):
            raise ValueError("protocol assembly projection manifest order is fixed")
        for projection, manifest in manifest_by_projection.items():
            expected_module_ids = {
                module.module_id
                for module in self.modules
                if projection in module.projection_targets
            }
            observed_module_ids = {
                *manifest.applicable_module_ids,
                *manifest.not_applicable_module_ids,
                *manifest.unresolved_module_ids,
            }
            if observed_module_ids != expected_module_ids:
                missing = sorted(expected_module_ids - observed_module_ids)
                extra = sorted(observed_module_ids - expected_module_ids)
                raise ValueError(
                    "protocol assembly projection manifest is incomplete: "
                    f"projection={projection}, missing={missing}, extra={extra}"
                )
            for module_id in manifest.applicable_module_ids:
                module = module_by_id[module_id]
                if (
                    not module.deterministic_projection_allowed
                    or module.applicability == "not_applicable"
                ):
                    raise ValueError(
                        "only resolved required or conditional modules may be projected"
                    )
            for module_id in manifest.not_applicable_module_ids:
                if module_by_id[module_id].applicability != "not_applicable":
                    raise ValueError(
                        "not-applicable projection entries must use not_applicable resolutions"
                    )
            for module_id in manifest.unresolved_module_ids:
                if module_by_id[module_id].deterministic_projection_allowed:
                    raise ValueError(
                        "unresolved projection entries cannot allow deterministic output"
                    )
            expected_projection_hash = medical_writing_protocol_assembly_sha256(
                {
                    "projection": projection,
                    "modules": {
                        module_id: module_by_id[module_id].resolution_sha256
                        for module_id in sorted(expected_module_ids)
                    },
                }
            )
            if manifest.content_sha256 != expected_projection_hash:
                raise ValueError("protocol assembly projection content hash mismatch")
        if self.affected_module_ids != sorted(set(self.affected_module_ids)):
            raise ValueError("affected protocol assembly module ids must be sorted")
        if not set(self.affected_module_ids).issubset(module_by_id):
            raise ValueError("affected protocol assembly modules must exist in the plan")
        projection_order = {
            name: index
            for index, name in enumerate(MEDICAL_WRITING_PROTOCOL_ASSEMBLY_PROJECTIONS)
        }
        if self.affected_projections != sorted(
            set(self.affected_projections), key=projection_order.__getitem__
        ):
            raise ValueError("affected protocol assembly projections must be ordered")
        if self.previous_plan_revision >= self.revision:
            raise ValueError("previous protocol assembly revision must precede revision")
        if self.confirmation_status == "author_confirmed":
            if not self.confirmed_by or self.confirmed_at is None:
                raise ValueError("author plan confirmation requires author and timestamp")
        elif self.confirmed_by or self.confirmed_at is not None:
            raise ValueError("draft protocol assembly plan cannot carry confirmation")
        state_payload = self.model_dump(mode="json", exclude={"state_sha256"})
        expected_state_hash = medical_writing_protocol_assembly_sha256(state_payload)
        legacy_state_payload = dict(state_payload)
        legacy_state_payload.pop("design_drivers", None)
        legacy_state_hash = medical_writing_protocol_assembly_sha256(
            legacy_state_payload
        )
        acceptable_hashes = {expected_state_hash}
        if not self.design_drivers:
            acceptable_hashes.add(legacy_state_hash)
        if self.state_sha256 not in acceptable_hashes:
            raise ValueError("protocol assembly plan state hash mismatch")
        return self


class MedicalWritingNormalizedDesignView(WorkbenchModel):
    """Read-only view of structured design facts that consumers can safely consume."""

    randomization_mode: Literal["undecided", "randomized", "non_randomized", "other"]
    blinding_mode: Literal[
        "undecided",
        "open_label",
        "single_blind",
        "double_blind",
        "triple_blind",
        "other",
    ]
    comparator_type: Literal[
        "undecided",
        "placebo",
        "active",
        "none_or_dose_escalation",
        "other",
    ]
    randomization_details: str = ""
    blinded_roles: List[str] = Field(default_factory=list)
    blinding_details: str = ""
    comparator_intervention: str = ""
    study_phase: str
    phase1_parts: list[MedicalWritingPhase1Part] = Field(default_factory=list)
    phase1_sequence: str = ""
    assignment_model: str = ""
    center_model: str = ""
    arm_or_cohort_kind: str = ""
    arm_or_cohort_labels: List[str] = Field(default_factory=list)
    interim_analysis: MedicalWritingInterimAnalysisDesign = Field(
        default_factory=MedicalWritingInterimAnalysisDesign
    )
    src_planned: Optional[bool] = None
    dmc_planned: Optional[bool] = None
    treatment_switch: MedicalWritingTreatmentSwitchDesign = Field(
        default_factory=MedicalWritingTreatmentSwitchDesign
    )
    crossover: MedicalWritingCrossoverDesign = Field(
        default_factory=MedicalWritingCrossoverDesign
    )
    open_label_extension: MedicalWritingOpenLabelExtensionDesign = Field(
        default_factory=MedicalWritingOpenLabelExtensionDesign
    )
    sample_size_reestimation: MedicalWritingSampleSizeReestimationDesign = Field(
        default_factory=MedicalWritingSampleSizeReestimationDesign
    )
    adaptive_design: MedicalWritingAdaptiveDesign = Field(
        default_factory=MedicalWritingAdaptiveDesign
    )


class MedicalWritingNormalizedDesignProjection(WorkbenchModel):
    """Single authoritative projection of StudyDefinition.design facts.

    This is a read-only derived view generated from StudyDefinition.framing.structured_design
    by normalize_study_design(). Authority order:

    1. Decided typed structured fields win for all projections.
    2. PICOS / intrinsic_objectives / design_pattern / free text may be used ONLY when the
       matching structured fact is undecided or absent.
    3. No consumer in Slice A may silently prefer legacy text over a decided structured fact.

    Fields:
        source_definition_id: The definition id that was normalized.
        source_definition_revision: The revision used.
        source_definition_sha256: State hash at normalization time.
        design_view: The normalized design fact view consumed by consumers.
        blockers: List of precise missing facts that block deterministic projection.
        deterministic_projection_allowed: False if any blocker exists.
        affected_projections: Which of the 7 projection targets are affected by blockers.

    Blocker semantics (Slice A):
        - Phase I Parts with unresolved=True must produce precise blockers.
        - non-Phase I studies must filter out residual Phase I Parts as applicable content.
        - Never invent dose, population, sequence, cohort, or transition details.
    """

    source_definition_id: str
    source_definition_revision: int
    source_definition_sha256: str
    design_view: MedicalWritingNormalizedDesignView
    blockers: List[
        MedicalWritingProtocolAssemblyUnresolvedQuestion
    ] = Field(default_factory=list, max_length=50)
    deterministic_projection_allowed: bool = True
    affected_projections: List[
        Literal[
            "synopsis",
            "sections_toc",
            "soa",
            "study_schema_flowchart",
            "evidence_intent",
            "ai_candidate_intent",
            "docx_toc",
        ]
    ] = Field(default_factory=list, max_length=7)

    @model_validator(mode="after")
    def validate_normalized_design_projection(self):
        self.source_definition_id = self.source_definition_id.strip()
        blocking_questions = [
            question for question in self.blockers if question.severity == "blocker"
        ]
        # Warnings remain visible but do not make deterministic projection false.
        if blocking_questions and self.deterministic_projection_allowed:
            raise ValueError(
                "NormalizedDesignProjection with blocking questions must set "
                "deterministic_projection_allowed=False"
            )
        if not blocking_questions and not self.deterministic_projection_allowed:
            raise ValueError(
                "NormalizedDesignProjection without blocking questions must keep "
                "deterministic_projection_allowed=True"
            )
        if self.blockers and not self.affected_projections:
            raise ValueError(
                "Design questions must list which projections are affected"
            )
        return self


class MedicalWritingNormalizedDesignProjectionWithSources(MedicalWritingNormalizedDesignProjection):
    """Extended view with semantic-to-canonical-source-path bindings."""

    design_fact_paths: Dict[str, str] = Field(default_factory=dict)
    """Map a normalized semantic name to the canonical source path actually used."""

    @model_validator(mode="after")
    def validate_fact_paths(self):
        for semantic, source_path in self.design_fact_paths.items():
            if not semantic.strip() or not source_path.strip():
                raise ValueError("design fact paths require non-empty semantics and paths")
        return self


class MedicalWritingProtocolAssemblyPlanPreviewRequest(WorkbenchModel):
    expected_plan_revision: int = Field(ge=0)
    expected_source_definition_id: str = Field(min_length=1, max_length=200)
    expected_source_definition_revision: int = Field(ge=1)
    expected_source_definition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)

    @model_validator(mode="after")
    def normalize_preview_request(self):
        for field_name in ("expected_source_definition_id", "actor"):
            setattr(self, field_name, getattr(self, field_name).strip())
        return self


class MedicalWritingProtocolAssemblyPlanRefreshRequest(WorkbenchModel):
    expected_plan_revision: int = Field(ge=0)
    expected_source_definition_id: str = Field(min_length=1, max_length=200)
    expected_source_definition_revision: int = Field(ge=1)
    expected_source_definition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def normalize_refresh_request(self):
        for field_name in (
            "expected_source_definition_id",
            "actor",
            "idempotency_key",
        ):
            setattr(self, field_name, getattr(self, field_name).strip())
        return self


class MedicalWritingProtocolAssemblyPlanConfirmRequest(WorkbenchModel):
    expected_plan_revision: int = Field(ge=1)
    expected_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def normalize_confirm_request(self):
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        return self


class MedicalWritingProtocolAssemblyPlanChangeResult(WorkbenchModel):
    plan: MedicalWritingProtocolAssemblyPlan
    previous_revision: int = Field(ge=0)
    affected_module_ids: List[str] = Field(default_factory=list)
    affected_projections: List[str] = Field(default_factory=list)
    replayed: bool = False


class MedicalWritingProtocolAssemblyPlanCurrentState(WorkbenchModel):
    project_id: str
    available: bool = False
    source_current: bool = False
    confirmation_current: bool = False
    deterministic_projection_allowed: bool = False
    stale_reason: str = ""
    plan: Optional[MedicalWritingProtocolAssemblyPlan] = None


class MedicalWritingProtocolAssemblyConsumerProjection(WorkbenchModel):
    projection: Literal[
        "synopsis",
        "sections_toc",
        "soa",
        "study_schema_flowchart",
        "evidence_intent",
        "ai_candidate_intent",
        "docx_toc",
    ]
    project_id: str
    plan_id: str
    plan_revision: int = Field(ge=1)
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_definition_id: str
    source_definition_revision: int = Field(ge=1)
    source_definition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_current: bool = False
    confirmation_status: Literal["draft", "author_confirmed"] = "draft"
    confirmation_current: bool = False
    required_module_ids: List[str] = Field(default_factory=list, max_length=200)
    design_driven_module_ids: List[str] = Field(default_factory=list, max_length=200)
    not_applicable_module_ids: List[str] = Field(default_factory=list, max_length=200)
    unresolved_module_ids: List[str] = Field(default_factory=list, max_length=200)
    unresolved_driver_ids: List[str] = Field(default_factory=list, max_length=300)
    deterministic_projection_allowed: bool = False
    design_drivers: List[MedicalWritingProtocolAssemblyDesignDriver] = Field(
        default_factory=list, max_length=300
    )
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_consumer_projection(self):
        groups = (
            self.required_module_ids,
            self.design_driven_module_ids,
            self.not_applicable_module_ids,
            self.unresolved_module_ids,
        )
        for values in groups:
            if values != sorted(set(values)):
                raise ValueError("consumer projection module ids must be sorted")
        flattened = [module_id for values in groups for module_id in values]
        if len(flattened) != len(set(flattened)):
            raise ValueError("consumer projection module classifications must be disjoint")
        if [item.driver_id for item in self.design_drivers] != sorted(
            item.driver_id for item in self.design_drivers
        ):
            raise ValueError("consumer projection design drivers must be sorted")
        expected_unresolved_driver_ids = sorted(
            item.driver_id
            for item in self.design_drivers
            if item.decision_state == "unknown"
        )
        if self.unresolved_driver_ids != expected_unresolved_driver_ids:
            raise ValueError(
                "consumer projection unresolved driver ids must match unknown drivers"
            )
        expected_deterministic = not (
            self.unresolved_module_ids or self.unresolved_driver_ids
        )
        if self.deterministic_projection_allowed != expected_deterministic:
            raise ValueError(
                "consumer projection deterministic state must fail closed on unresolved facts"
            )
        return self


class MedicalWritingDocumentCreationReservation(WorkbenchModel):
    reservation_id: str
    source_revision: int = Field(ge=1)
    source_gate_sha256: str
    request_idempotency_key: str
    actor: str
    reserved_at: datetime


class MedicalWritingCompetitorRegistryFilter(WorkbenchModel):
    condition_term: str = ""
    phases: List[str] = Field(default_factory=list)
    study_type: Literal["INTERVENTIONAL", "OBSERVATIONAL", "EXPANDED_ACCESS"] = (
        "INTERVENTIONAL"
    )
    regions: List[str] = Field(default_factory=list)
    intervention_terms: List[str] = Field(default_factory=list)


class MedicalWritingCompetitorTriageCriterion(WorkbenchModel):
    criterion_id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=2_000)
    source_field_paths: List[str] = Field(default_factory=list, max_length=20)


class MedicalWritingCompetitorSearchPlan(WorkbenchModel):
    plan_id: str
    plan_revision: int = Field(ge=1)
    strategy: Literal["broad_then_triage"] = "broad_then_triage"
    queries: List[str] = Field(default_factory=list)
    registry_filter: Optional[MedicalWritingCompetitorRegistryFilter] = None
    triage_criteria: List[MedicalWritingCompetitorTriageCriterion] = Field(
        default_factory=list
    )
    document_roles: List[Literal["protocol"]] = Field(
        default_factory=lambda: ["protocol"]
    )
    status: Literal[
        "planned", "searching", "triage_pending", "triaged", "no_results"
    ] = "planned"
    latest_snapshot_id: str = ""
    returned_count: int = Field(default=0, ge=0)
    public_document_count: int = Field(default=0, ge=0)
    searched_at: Optional[datetime] = None
    source_study_definition_revision: int = Field(ge=1)
    generated_at: datetime


def _medical_writing_ctgov_phases(study_phase: str) -> List[str]:
    value = str(study_phase or "").upper().replace(" ", "")
    if "I/II" in value or "1/2" in value:
        return ["PHASE1", "PHASE2"]
    if "II/III" in value or "2/3" in value:
        return ["PHASE2", "PHASE3"]
    if "III/IV" in value or "3/4" in value:
        return ["PHASE3", "PHASE4"]
    if "EARLY" in value or "早期I" in value or "0期" in value:
        return ["EARLY_PHASE1"]
    if "IV" in value or "4" in value:
        return ["PHASE4"]
    if "III" in value or "3" in value:
        return ["PHASE3"]
    if "II" in value or "2" in value:
        return ["PHASE2"]
    return ["PHASE1"]


def medical_writing_competitor_search_contract(
    framing: MedicalWritingStudyFraming,
) -> tuple[
    MedicalWritingCompetitorRegistryFilter,
    List[MedicalWritingCompetitorTriageCriterion],
    List[str],
]:
    # Prefer English ClinicalTrials.gov condition terms. Chinese indication
    # strings (e.g. IgA肾病) return zero hits on CT.gov; resolve via alias
    # table when AI enrich has not yet written an English term.
    try:
        from services.api.app.medical_writing_condition_term_resolver import (
            resolve_clinicaltrials_condition_term,
        )

        condition_term, _alias = resolve_clinicaltrials_condition_term(
            indication=framing.indication or "",
            clinicaltrials_condition_term=framing.clinicaltrials_condition_term
            or "",
        )
    except Exception:
        condition_term = (
            framing.clinicaltrials_condition_term.strip()
            or framing.indication.strip()
        )
    registry_filter = MedicalWritingCompetitorRegistryFilter(
        condition_term=condition_term,
        phases=_medical_writing_ctgov_phases(framing.study_phase),
        study_type="INTERVENTIONAL",
        regions=[],
        intervention_terms=[],
    )
    candidates = [
        (
            "target_mechanism",
            "靶点/作用机制相近",
            framing.competitor_target_scope or framing.target_mechanism,
            ["framing.competitor_target_scope", "framing.target_mechanism"],
        ),
        (
            "intrinsic_objectives",
            "内在研究目的相近",
            "、".join(framing.intrinsic_objectives),
            ["framing.intrinsic_objectives"],
        ),
        (
            "design_pattern",
            "总体设计相近",
            framing.design_pattern,
            ["framing.design_pattern"],
        ),
        (
            "population_intent",
            "目标研究人群相近",
            framing.population_intent,
            ["framing.population_intent"],
        ),
        (
            "product_technology",
            "研究药物技术类型相近",
            (
                framing.product_profile.technology_description
                or (
                    framing.product_profile.technology_type
                    if framing.product_profile.technology_type != "unknown"
                    else ""
                )
            ),
            ["framing.product_profile.technology_type"],
        ),
        (
            "administration_route",
            "给药途径相近",
            "、".join(framing.product_profile.administration_routes),
            ["framing.product_profile.administration_routes"],
        ),
        (
            "exposure_scope",
            "系统或局部暴露特征相近",
            (
                framing.product_profile.exposure_scope
                if framing.product_profile.exposure_scope != "unknown"
                else ""
            ),
            ["framing.product_profile.exposure_scope"],
        ),
    ]
    triage_criteria = [
        MedicalWritingCompetitorTriageCriterion(
            criterion_id=criterion_id,
            label=label,
            value=value.strip(),
            source_field_paths=source_field_paths,
        )
        for criterion_id, label, value, source_field_paths in candidates
        if value and value.strip()
    ]
    queries = [
        f"疾病/适应症：{registry_filter.condition_term}",
        f"研究分期：{'、'.join(registry_filter.phases)}",
        f"研究类型：{registry_filter.study_type}",
    ]
    if framing.product_profile.applicability_facets():
        queries.append(
            "适用性重排特征："
            + "；".join(framing.product_profile.applicability_facets())
        )
    return registry_filter, triage_criteria, queries


class MedicalWritingCorpusGateOverride(WorkbenchModel):
    active: bool = False
    reason: str = ""
    actor: str = ""
    recorded_at: Optional[datetime] = None
    acknowledged_missing_requirements: List[str] = Field(default_factory=list)


class MedicalWritingCorpusRequirementStatus(WorkbenchModel):
    code: Literal[
        "candidate_triage",
        "protocol_structure",
        "regulatory_zh_translation",
        "medical_admission",
        "picos_alignment",
    ]
    label: str
    satisfied: bool = False
    evidence_ids: List[str] = Field(default_factory=list)
    detail: str = ""


class MedicalWritingCorpusTriage(WorkbenchModel):
    status: Literal["pending", "finalized"] = "pending"
    snapshot_id: str = ""
    retained_candidate_ids: List[str] = Field(default_factory=list)
    reason: str = ""
    actor: str = ""
    finalized_at: Optional[datetime] = None


class DiscoveryBasketProjection(WorkbenchModel):
    """Derived projection of a confirmed competitor discovery basket into the
    authoring journey.

    This is NOT final corpus admission and does NOT require PICOS completion.
    It carries the authoritative confirmation identity/hash from
    ``writing_reference.sqlite3`` so the preparation batch can verify the
    current authoritative confirmation without a cross-database transaction.

    The journey stores this as a derived reference; the authoritative record
    lives in the reference database.  When PICOS later becomes complete, the
    same confirmation idempotently projects into ``corpus_triage`` via
    ``finalize_corpus_triage`` without a second user action.
    """

    confirmation_id: str = ""
    confirmation_hash: str = ""
    snapshot_id: str = ""
    retained_nct_ids: List[str] = Field(default_factory=list)
    excluded_nct_ids: List[str] = Field(default_factory=list)
    run_id: str = ""
    actor: str = ""
    reason: str = ""
    projected_at: Optional[datetime] = None


class MedicalWritingPicosCorpusAlignment(WorkbenchModel):
    status: Literal["pending", "no_conflicts", "resolved"] = "pending"
    source_picos_sha256: str = ""
    conflict_count: int = Field(default=0, ge=0)
    disposition_summary: str = ""
    evidence_brief_ids: List[str] = Field(default_factory=list)
    actor: str = ""
    assessed_at: Optional[datetime] = None


class MedicalWritingCorpusGate(WorkbenchModel):
    readiness_status: Literal["not_ready", "ready"] = "not_ready"
    access_permitted: bool = False
    missing_requirements: List[str] = Field(default_factory=list)
    covered_requirements: List[str] = Field(default_factory=list)
    requirements: List[MedicalWritingCorpusRequirementStatus] = Field(default_factory=list)
    bound_snapshot_id: str = ""
    source_state_hash: str = ""
    evaluated_at: Optional[datetime] = None
    stale: bool = True
    override: MedicalWritingCorpusGateOverride = Field(
        default_factory=MedicalWritingCorpusGateOverride
    )


class MedicalWritingAuthoringJourney(WorkbenchModel):
    schema_version: str = "medical_writing_authoring_journey_v4"
    journey_id: str
    project_id: str
    revision: int = Field(ge=1)
    entry_mode: Literal["guided_greenfield", "synopsis_import"] = "guided_greenfield"
    synopsis_import: MedicalWritingSynopsisImport = Field(
        default_factory=MedicalWritingSynopsisImport
    )
    study_definition: Optional[MedicalWritingStudyDefinition] = None
    study_schema_presentation: Optional[MedicalWritingStudySchemaPresentation] = None
    status: Literal[
        "stage1_in_progress",
        "stage1_complete",
        "stage2_in_progress",
        "corpus_not_ready",
        "writing_allowed",
        "document_creation_reserved",
        "document_created",
    ] = "stage1_in_progress"
    current_stage: Literal["framing", "picos", "corpus", "writing"] = "framing"
    framing: MedicalWritingStudyFraming = Field(default_factory=MedicalWritingStudyFraming)
    picos: MedicalWritingPicosDefinition = Field(default_factory=MedicalWritingPicosDefinition)
    framing_draft: Optional[MedicalWritingAuthoringStageDraft] = None
    picos_draft: Optional[MedicalWritingAuthoringStageDraft] = None
    document_creation_reservation: Optional[
        MedicalWritingDocumentCreationReservation
    ] = None
    framing_complete: bool = False
    picos_complete: bool = False
    search_plan: Optional[MedicalWritingCompetitorSearchPlan] = None
    prefill_package: Optional["AuthoringPrefillPackage"] = None
    corpus_triage: MedicalWritingCorpusTriage = Field(
        default_factory=MedicalWritingCorpusTriage
    )
    discovery_basket_projection: DiscoveryBasketProjection = Field(
        default_factory=DiscoveryBasketProjection
    )
    picos_corpus_alignment: MedicalWritingPicosCorpusAlignment = Field(
        default_factory=MedicalWritingPicosCorpusAlignment
    )
    corpus_gate: MedicalWritingCorpusGate = Field(default_factory=MedicalWritingCorpusGate)
    research_pipeline: Dict[str, Any] = Field(default_factory=dict)
    invalidated_dependents: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    updated_by: str

    @model_validator(mode="after")
    def migrate_and_fail_closed(self):
        design_legacy_payload = self.schema_version not in {
            "medical_writing_authoring_journey_v2",
            "medical_writing_authoring_journey_v3",
            "medical_writing_authoring_journey_v4",
        }
        if design_legacy_payload and not self.picos.design_archetype:
            pattern = " ".join(
                [self.framing.design_pattern, *self.framing.intrinsic_objectives]
            ).lower()
            if "ole" in pattern or "延展" in pattern:
                archetype = "open_label_extension"
            elif self.picos.comparator_summary and any(
                token in pattern
                for token in ("随机", "random", "安慰剂", "placebo", "对照")
            ):
                archetype = "randomized_confirmatory"
            elif any(
                token in pattern
                for token in (
                    "单臂",
                    "single-arm",
                    "single arm",
                    "fih",
                    "first-in-patient",
                    "pom",
                    "剂量探索",
                )
            ):
                archetype = "single_arm_early_phase"
            else:
                archetype = "other"
            self.picos = self.picos.model_copy(
                update={"design_archetype": archetype}, deep=True
            )

        if self.search_plan is not None and (
            self.schema_version != "medical_writing_authoring_journey_v4"
            or self.search_plan.registry_filter is None
        ):
            registry_filter, triage_criteria, queries = (
                medical_writing_competitor_search_contract(self.framing)
            )
            self.search_plan = self.search_plan.model_copy(
                update={
                    "registry_filter": self.search_plan.registry_filter
                    or registry_filter,
                    "triage_criteria": self.search_plan.triage_criteria
                    or triage_criteria,
                    "queries": queries,
                },
                deep=True,
            )

        framing_invalid = self.framing_complete and bool(
            self.framing.missing_required_fields()
        )
        picos_invalid = self.picos_complete and bool(
            self.picos.missing_required_fields()
        )
        if framing_invalid or picos_invalid:
            if framing_invalid:
                self.framing_complete = False
                self.picos_complete = False
                self.status = "stage1_in_progress"
                self.current_stage = "framing"
            else:
                self.picos_complete = False
                self.status = "stage2_in_progress"
                self.current_stage = "picos"
            self.document_creation_reservation = None
            self.corpus_gate = self.corpus_gate.model_copy(
                update={
                    "access_permitted": False,
                    "stale": True,
                    "override": MedicalWritingCorpusGateOverride(),
                },
                deep=True,
            )
        self.schema_version = "medical_writing_authoring_journey_v4"
        return self


class MedicalWritingAuthoringJourneyCreateRequest(WorkbenchModel):
    entry_mode: Literal["guided_greenfield", "synopsis_import"] = "guided_greenfield"
    framing: MedicalWritingStudyFraming = Field(default_factory=MedicalWritingStudyFraming)
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def normalize_create_request(self):
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if not self.actor or not self.idempotency_key:
            raise ValueError("authoring journey actor and idempotency key must not be blank")
        return self


class MedicalWritingSynopsisImportConfirmRequest(WorkbenchModel):
    expected_revision: int = Field(ge=1)
    source_id: str = Field(min_length=1, max_length=200)
    framing: MedicalWritingStudyFraming
    picos: MedicalWritingPicosDefinition
    synopsis_text: str = Field(min_length=1, max_length=100_000)
    acknowledged_validation_warnings: List[str] = Field(default_factory=list)
    validation_override_reason: str = Field(default="", max_length=2_000)
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def normalize_synopsis_confirmation(self):
        self.source_id = self.source_id.strip()
        self.synopsis_text = self.synopsis_text.strip()
        self.actor = self.actor.strip()
        self.validation_override_reason = self.validation_override_reason.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if not all(
            (self.source_id, self.synopsis_text, self.actor, self.idempotency_key)
        ):
            raise ValueError("synopsis confirmation fields must not be blank")
        return self


class MedicalWritingLegacyAuthoringBootstrapPrepareRequest(WorkbenchModel):
    expected_document_id: str = Field(min_length=1, max_length=200)
    expected_source_sha256: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    expected_indication: str = Field(default="", max_length=500)
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def normalize_legacy_prepare(self):
        for field_name in (
            "expected_document_id",
            "expected_source_sha256",
            "expected_indication",
            "actor",
            "idempotency_key",
        ):
            setattr(self, field_name, str(getattr(self, field_name)).strip())
        return self


class MedicalWritingLegacyAuthoringBootstrapConfirmRequest(WorkbenchModel):
    expected_document_id: str = Field(min_length=1, max_length=200)
    expected_source_sha256: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    import_idempotency_key: str = Field(min_length=1, max_length=200)
    source_id: str = Field(min_length=1, max_length=200)
    confirmed_source_role: Optional[Literal["protocol", "synopsis"]] = None
    framing: MedicalWritingStudyFraming
    picos: MedicalWritingPicosDefinition
    synopsis_text: str = Field(min_length=1, max_length=100_000)
    acknowledged_validation_warnings: List[str] = Field(default_factory=list)
    validation_override_reason: str = Field(default="", max_length=2_000)
    source_role_override_reason: str = Field(default="", max_length=2_000)
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def normalize_legacy_confirmation(self):
        for field_name in (
            "expected_document_id",
            "expected_source_sha256",
            "import_idempotency_key",
            "source_id",
            "synopsis_text",
            "validation_override_reason",
            "source_role_override_reason",
            "actor",
            "idempotency_key",
        ):
            setattr(self, field_name, str(getattr(self, field_name)).strip())
        return self


class MedicalWritingLegacyAuthoringBootstrapStatus(WorkbenchModel):
    project_id: str
    state: Literal[
        "eligible",
        "extracting",
        "review_pending",
        "failed",
        "confirmed_ready_for_binding",
        "bound",
        "not_eligible",
    ]
    document_id: str = ""
    source_filename: str = ""
    source_sha256: str = ""
    source_read_only: bool = True
    source_role: Literal["protocol", "synopsis"] = "protocol"
    detected_source_role: Optional[Literal["protocol", "synopsis"]] = None
    confirmed_source_role: Optional[Literal["protocol", "synopsis"]] = None
    source_role_overridden: bool = False
    import_idempotency_key: str = ""
    job_id: str = ""
    job_status: str = ""
    warnings: List[str] = Field(default_factory=list)
    candidate: Optional[MedicalWritingSynopsisImport] = None
    study_definition_id: str = ""
    study_definition_revision: Optional[int] = Field(default=None, ge=1)
    study_definition_sha256: str = ""
    next_action: str = ""
    message: str = ""

    @model_validator(mode="after")
    def preserve_detected_and_confirmed_source_roles(self):
        self.detected_source_role = self.detected_source_role or self.source_role
        self.source_role = self.detected_source_role
        self.source_role_overridden = bool(
            self.confirmed_source_role
            and self.confirmed_source_role != self.detected_source_role
        )
        return self


class MedicalWritingSynopsisProjectCreateRequest(WorkbenchModel):
    """Confirm a file-first synopsis intake and create its canonical project."""

    intake_id: str = Field(min_length=1, max_length=200)
    import_idempotency_key: str = Field(min_length=1, max_length=200)
    source_id: str = Field(min_length=1, max_length=200)
    framing: MedicalWritingStudyFraming
    picos: MedicalWritingPicosDefinition
    synopsis_text: str = Field(min_length=1, max_length=100_000)
    acknowledged_validation_warnings: List[str] = Field(default_factory=list)
    validation_override_reason: str = Field(default="", max_length=2_000)
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def normalize_project_create_request(self):
        for field_name in (
            "intake_id",
            "import_idempotency_key",
            "source_id",
            "synopsis_text",
            "validation_override_reason",
            "actor",
            "idempotency_key",
        ):
            setattr(self, field_name, str(getattr(self, field_name)).strip())
        if not all(
            (
                self.intake_id,
                self.import_idempotency_key,
                self.source_id,
                self.synopsis_text,
                self.actor,
                self.idempotency_key,
            )
        ):
            raise ValueError("file-first synopsis project confirmation fields must not be blank")
        if not self.framing.investigational_product.strip():
            raise ValueError("investigational product must be confirmed before project creation")
        if not self.framing.indication.strip():
            raise ValueError("indication must be confirmed before project creation")
        if not self.framing.study_phase.strip():
            raise ValueError("study phase must be confirmed before project creation")
        return self


class SynopsisImportJobProgress(WorkbenchModel):
    phase: Literal[
        "uploaded",
        "parsing",
        "chunking",
        "ai_synthesis",
        "validating",
        "review_ready",
        "cancelled",
        "failed",
        "recoverable",
    ]
    chunk_index: int = Field(default=0, ge=0)
    chunk_total: int = Field(default=0, ge=0)
    provider_status: Literal[
        "queued", "streaming", "done", "repairing", "failed", "skipped"
    ] = Field(default="queued")
    last_chunk_elapsed_ms: int = Field(default=0, ge=0)
    last_chunk_tokens: int = Field(default=0, ge=0)
    repair_count: int = Field(default=0, ge=0)
    anchor_count: int = Field(default=0, ge=0)
    error_message: str = Field(default="", max_length=4_000)


class SynopsisImportJobChunk(WorkbenchModel):
    chunk_index: int = Field(ge=0)
    status: Literal["pending", "streaming", "done", "repairing", "failed", "skipped"]
    attempt_count: int = Field(default=1, ge=1)
    provider_output_hash: str = Field(default="")
    validation_error: str = Field(default="", max_length=4_000)
    evidence_span_ids: List[str] = Field(default_factory=list)
    started_at: datetime
    finished_at: Optional[datetime] = None


class SynopsisImportJob(WorkbenchModel):
    job_id: str = Field(min_length=1, max_length=200)
    project_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=200)
    status: Literal[
        "uploaded",
        "parsing",
        "chunking",
        "ai_synthesis",
        "validating",
        "review_ready",
        "cancelled",
        "failed",
        "recoverable",
    ]
    phase: Literal[
        "uploaded",
        "parsing",
        "chunking",
        "ai_synthesis",
        "validating",
        "review_ready",
        "cancelled",
        "failed",
        "recoverable",
    ] = "uploaded"
    chunk_index: int = Field(default=0, ge=0)
    chunk_total: int = Field(default=0, ge=0)
    progress: SynopsisImportJobProgress = Field(
        default_factory=lambda: SynopsisImportJobProgress(phase="uploaded")
    )
    source_identity: Optional[MedicalWritingSynopsisSource] = None
    content_sha256: str = Field(default="", max_length=64)
    source_filename: str = Field(default="", max_length=500)
    warnings: List[str] = Field(default_factory=list)
    cancellation_state: Literal["none", "requested", "cancelled"] = Field(
        default="none"
    )
    result: Optional[MedicalWritingSynopsisImport] = None
    chunks: List[SynopsisImportJobChunk] = Field(default_factory=list)
    attempt_count: int = Field(default=1, ge=1)
    error_message: str = Field(default="", max_length=4_000)
    created_at: datetime
    updated_at: datetime


class SynopsisImportJobStartResponse(WorkbenchModel):
    job_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=200)
    status: str = Field(min_length=1, max_length=50)
    phase: str = Field(min_length=1, max_length=50)
    content_sha256: str = Field(default="", max_length=64)
    span_count: int = Field(default=0, ge=0)
    media_type: str = Field(default="", max_length=200)
    warnings: List[str] = Field(default_factory=list)


class SynopsisImportJobStatusResponse(WorkbenchModel):
    job_id: str = Field(min_length=1, max_length=200)
    status: str = Field(min_length=1, max_length=50)
    phase: str = Field(min_length=1, max_length=50)
    chunk_index: int = Field(default=0, ge=0)
    chunk_total: int = Field(default=0, ge=0)
    provider_status: str = Field(default="queued", max_length=50)
    content_sha256: str = Field(default="", max_length=64)
    source_filename: str = Field(default="", max_length=500)
    warnings: List[str] = Field(default_factory=list)
    cancellation_state: str = Field(default="none", max_length=20)
    error_message: str = Field(default="", max_length=4_000)
    repair_count: int = Field(default=0, ge=0)
    anchor_count: int = Field(default=0, ge=0)
    result_ref: Optional[str] = Field(default=None, max_length=200)
    started_at: Optional[datetime] = None
    heartbeat_at: Optional[datetime] = None
    elapsed_seconds: int = Field(default=0, ge=0)
    heartbeat_age_seconds: int = Field(default=0, ge=0)


class SynopsisImportJobCancelResponse(WorkbenchModel):
    job_id: str = Field(min_length=1, max_length=200)
    status: str = Field(min_length=1, max_length=50)
    cancellation_state: str = Field(min_length=1, max_length=20)
    last_completed_chunk: int = Field(default=-1, ge=-1)
    partial_evidence_span_ids: List[str] = Field(default_factory=list)


class MedicalWritingJourneyImpactPreviewRequest(WorkbenchModel):
    expected_revision: int = Field(ge=1)
    stage: Literal["framing", "picos"]
    framing: Optional[MedicalWritingStudyFraming] = None
    picos: Optional[MedicalWritingPicosDefinition] = None

    @model_validator(mode="after")
    def validate_preview_payload(self):
        if self.stage == "framing" and self.framing is None:
            raise ValueError("framing impact preview requires framing payload")
        if self.stage == "picos" and self.picos is None:
            raise ValueError("picos impact preview requires picos payload")
        return self


class MedicalWritingJourneyImpactPreview(WorkbenchModel):
    preview_id: str
    project_id: str
    expected_revision: int = Field(ge=1)
    stage: Literal["framing", "picos"]
    changed_fields: List[str] = Field(default_factory=list)
    affected_dependents: List[str] = Field(default_factory=list)
    requires_confirmation: bool = False


class MedicalWritingAuthoringJourneyCommitRequest(MedicalWritingJourneyImpactPreviewRequest):
    impact_preview_id: str = ""
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def normalize_commit_request(self):
        self.impact_preview_id = self.impact_preview_id.strip()
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if not self.actor or not self.idempotency_key:
            raise ValueError("authoring journey commit fields must not be blank")
        return self


class MedicalWritingAuthoringJourneyDraftSaveRequest(
    MedicalWritingJourneyImpactPreviewRequest
):
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def normalize_draft_request(self):
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if not self.actor or not self.idempotency_key:
            raise ValueError("authoring journey draft fields must not be blank")
        return self


class MedicalWritingCorpusGateOverrideRequest(WorkbenchModel):
    expected_revision: int = Field(ge=1)
    reason: str = Field(default="", max_length=5_000)
    acknowledged_missing_requirements: List[str] = Field(min_length=1, max_length=100)
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def normalize_corpus_override(self):
        self.reason = self.reason.strip()
        self.acknowledged_missing_requirements = [
            item.strip() for item in self.acknowledged_missing_requirements if item.strip()
        ]
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if not self.acknowledged_missing_requirements:
            raise ValueError("corpus gate override must acknowledge missing requirements")
        if len(self.acknowledged_missing_requirements) != len(
            set(self.acknowledged_missing_requirements)
        ):
            raise ValueError("acknowledged missing requirements must be unique")
        if not self.actor or not self.idempotency_key:
            raise ValueError("corpus gate override fields must not be blank")
        return self


class MedicalWritingCorpusTriageFinalizeRequest(WorkbenchModel):
    expected_revision: int = Field(ge=1)
    snapshot_id: str = Field(min_length=1)
    retained_candidate_ids: List[str] = Field(default_factory=list)
    reason: str = Field(min_length=10, max_length=2000)
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def normalize_triage_finalize(self):
        self.snapshot_id = self.snapshot_id.strip()
        self.retained_candidate_ids = list(
            dict.fromkeys(item.strip() for item in self.retained_candidate_ids if item.strip())
        )
        self.reason = self.reason.strip()
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if not self.snapshot_id:
            raise ValueError("corpus triage requires a snapshot")
        return self


class MedicalWritingPicosCorpusAlignmentRequest(WorkbenchModel):
    expected_revision: int = Field(ge=1)
    source_picos_sha256: str = Field(min_length=64, max_length=64)
    status: Literal["no_conflicts", "resolved"]
    conflict_count: int = Field(default=0, ge=0)
    disposition_summary: str = Field(min_length=10, max_length=4000)
    evidence_brief_ids: List[str] = Field(default_factory=list)
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def normalize_alignment(self):
        self.source_picos_sha256 = self.source_picos_sha256.strip().lower()
        self.disposition_summary = self.disposition_summary.strip()
        self.evidence_brief_ids = list(
            dict.fromkeys(item.strip() for item in self.evidence_brief_ids if item.strip())
        )
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if self.status == "no_conflicts" and self.conflict_count != 0:
            raise ValueError("no_conflicts assessment must have conflict_count=0")
        if self.status == "resolved" and self.conflict_count < 1:
            raise ValueError("resolved assessment must record at least one conflict")
        return self


class MedicalWritingCompetitorSearchExecuteRequest(WorkbenchModel):
    search_plan_id: str = Field(min_length=1, max_length=200)
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def normalize_competitor_search_execute(self):
        self.search_plan_id = self.search_plan_id.strip()
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if not self.search_plan_id or not self.actor or not self.idempotency_key:
            raise ValueError("competitor search execution fields must not be blank")
        return self


class AuthoringPrefillEvidenceRef(WorkbenchModel):
    source_kind: Literal[
        "registry",
        "study_definition",
        "search_snapshot",
        "synopsis",
        "manual",
        "other",
    ] = "study_definition"
    source_id: str = Field(default="", max_length=200)
    locator: str = Field(default="", max_length=1_000)
    source_text: str = Field(default="", max_length=5_000)
    quote_sha256: str = Field(default="", max_length=64)

    @model_validator(mode="after")
    def normalize_evidence_ref(self):
        for field_name in ("source_id", "locator", "source_text", "quote_sha256"):
            setattr(self, field_name, getattr(self, field_name).strip())
        if self.quote_sha256 and len(self.quote_sha256) != 64:
            raise ValueError("prefill evidence quote_sha256 must contain 64 characters")
        if not self.source_id and not self.source_text:
            raise ValueError("prefill evidence requires a source id or source text")
        if self.source_text and not self.quote_sha256:
            self.quote_sha256 = sha256(self.source_text.encode("utf-8")).hexdigest()
        return self


class AuthoringPrefillCandidate(WorkbenchModel):
    candidate_id: str = Field(min_length=1, max_length=200)
    field_path: str = Field(min_length=1, max_length=300)
    structured_value: Any = None
    preview: str = Field(default="", max_length=5_000)
    evidence_refs: List[AuthoringPrefillEvidenceRef] = Field(
        default_factory=list, max_length=20
    )
    rationale: str = Field(default="", max_length=5_000)
    limitations: List[str] = Field(default_factory=list, max_length=20)
    confidence: Literal["high", "medium", "low", "none"] = "medium"
    state: Literal["ai_proposed", "user_confirmed", "superseded"] = "ai_proposed"
    candidate_scope: Literal[
        "field", "module", "design_package", "table", "chapter"
    ] = "field"
    target_paths: List[str] = Field(default_factory=list, max_length=50)
    recommendation_role: Literal[
        "recommended", "alternative", "pending_decision"
    ] = "recommended"
    clinical_tradeoffs: List[str] = Field(default_factory=list, max_length=20)
    evidence_gaps: List[str] = Field(default_factory=list, max_length=20)
    ai_run_id: str = Field(default="", max_length=200)
    adoption_mode: Literal["manual_only", "batch_allowed"] = "manual_only"
    # W2b: evidence catalog binding (all optional for backward compatibility)
    evidence_catalog_id: str = Field(default="", max_length=200)
    evidence_catalog_sha256: str = Field(default="", max_length=64)
    claim_bindings: List[AuthoringPrefillClaimBinding] = Field(
        default_factory=list, max_length=100
    )
    evidence_status: Literal[
        "supported", "partially_supported", "insufficient"
    ] = "insufficient"

    @model_validator(mode="after")
    def normalize_candidate(self):
        self.candidate_id = self.candidate_id.strip()
        self.field_path = self.field_path.strip()
        self.preview = self.preview.strip()
        self.rationale = self.rationale.strip()
        self.ai_run_id = self.ai_run_id.strip()
        self.evidence_catalog_id = self.evidence_catalog_id.strip()
        self.evidence_catalog_sha256 = (
            self.evidence_catalog_sha256.strip().lower()
        )
        self.limitations = [
            item.strip() for item in self.limitations if item and str(item).strip()
        ]
        self.clinical_tradeoffs = [
            item.strip()
            for item in self.clinical_tradeoffs
            if item and str(item).strip()
        ]
        self.evidence_gaps = [
            item.strip()
            for item in self.evidence_gaps
            if item and str(item).strip()
        ]
        if not self.candidate_id or not self.field_path:
            raise ValueError("prefill candidate requires candidate_id and field_path")
        if not self.preview and self.structured_value is not None:
            if isinstance(self.structured_value, list):
                self.preview = "；".join(str(item) for item in self.structured_value)
            else:
                self.preview = str(self.structured_value)

        # W2b: validate evidence catalog fields when provided.
        if self.evidence_catalog_sha256:
            if len(self.evidence_catalog_sha256) != 64 or not re.fullmatch(
                r"[0-9a-f]{64}", self.evidence_catalog_sha256
            ):
                raise ValueError(
                    "evidence_catalog_sha256 must be 64 lowercase hex characters"
                )

        # Reject duplicate claim bindings (same target_path + value_pointer + catalog_entry_id).
        seen_binding_keys: set[tuple[str, str, str]] = set()
        unique_bindings: list[AuthoringPrefillClaimBinding] = []
        for binding in self.claim_bindings:
            key = (
                binding.target_path,
                binding.value_pointer,
                binding.catalog_entry_id,
            )
            if key in seen_binding_keys:
                raise ValueError(
                    f"duplicate claim binding rejected: {key}"
                )
            seen_binding_keys.add(key)
            unique_bindings.append(binding)
        self.claim_bindings = unique_bindings

        # supported / partially_supported require catalog id, hash, and >=1 binding.
        if self.evidence_status in ("supported", "partially_supported"):
            if not self.evidence_catalog_id:
                raise ValueError(
                    f"evidence_status={self.evidence_status} requires evidence_catalog_id"
                )
            if not self.evidence_catalog_sha256:
                raise ValueError(
                    f"evidence_status={self.evidence_status} requires evidence_catalog_sha256"
                )
            if not self.claim_bindings:
                raise ValueError(
                    f"evidence_status={self.evidence_status} requires at least one claim binding"
                )

        scope = self.candidate_scope
        if scope in ("module", "design_package"):
            self._validate_multi_path_targets()
        elif scope == "field":
            self.target_paths = []
        self._validate_structured_value_for_scope(scope)

        if self.recommendation_role == "pending_decision":
            if self.adoption_mode != "manual_only":
                raise ValueError(
                    "pending_decision recommendation_role must use manual_only adoption_mode"
                )

        return self

    # -- internal helpers ------------------------------------------------

    def _validate_multi_path_targets(self) -> None:
        if not self.target_paths:
            raise ValueError(
                f"{self.candidate_scope} candidate requires non-empty target_paths"
            )
        seen: set[str] = set()
        for path in self.target_paths:
            stripped = path.strip()
            if not stripped:
                raise ValueError("target_paths must not contain empty strings")
            if stripped in seen:
                raise ValueError(f"target_paths must not contain duplicates: {stripped}")
            seen.add(stripped)
        self.target_paths = sorted(seen)

    def _validate_structured_value_for_scope(self, scope: str) -> None:
        if scope not in ("module", "design_package"):
            return
        if not isinstance(self.structured_value, dict):
            raise ValueError(
                f"{scope} candidate structured_value must be an object keyed by target_paths"
            )
        target_set = set(self.target_paths)
        value_keys = set(self.structured_value.keys())
        if value_keys != target_set:
            missing = target_set - value_keys
            extra = value_keys - target_set
            parts: list[str] = []
            if missing:
                parts.append(f"missing keys: {sorted(missing)}")
            if extra:
                parts.append(f"unexpected keys: {sorted(extra)}")
            raise ValueError(
                f"{scope} candidate structured_value keys must exactly match target_paths"
                + (" (" + "; ".join(parts) + ")" if parts else "")
            )


class AuthoringPrefillFieldCandidates(WorkbenchModel):
    field_path: str = Field(min_length=1, max_length=300)
    recommended_candidate_id: str = Field(default="", max_length=200)
    candidates: List[AuthoringPrefillCandidate] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def validate_field_candidates(self):
        self.field_path = self.field_path.strip()
        self.recommended_candidate_id = self.recommended_candidate_id.strip()
        if not self.field_path:
            raise ValueError("prefill field path must not be blank")
        if len(self.candidates) > 5:
            raise ValueError("each prefill field allows at most 1 recommended + 4 alternatives")
        ids = [item.candidate_id for item in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("prefill candidate ids must be unique within a field")
        for item in self.candidates:
            if item.field_path != self.field_path:
                raise ValueError("prefill candidate field_path must match its parent field")
        if self.candidates:
            # Corrective round 2 (post-conference): a non-empty group MAY
            # carry an empty recommended id when every visible candidate is
            # pending, manual-only, or otherwise unsafe — the group keeps all
            # its candidates but has no effective recommendation.  Any
            # non-empty id must still reference exactly one candidate in the
            # same group.
            if self.recommended_candidate_id and self.recommended_candidate_id not in ids:
                raise ValueError("recommended_candidate_id must reference a candidate")
        elif self.recommended_candidate_id:
            raise ValueError("recommended_candidate_id requires candidates")
        return self


class AuthoringPrefillProgress(WorkbenchModel):
    total_fields: int = Field(default=0, ge=0)
    fields_with_recommendation: int = Field(default=0, ge=0)
    fields_blocked_missing_evidence: int = Field(default=0, ge=0)
    percent_complete: int = Field(default=0, ge=0, le=100)
    stage: str = Field(default="", max_length=100)
    message: str = Field(default="", max_length=2_000)


class AuthoringPrefillPackage(WorkbenchModel):
    package_id: str = Field(min_length=1, max_length=200)
    project_id: str = Field(min_length=1, max_length=200)
    package_revision: int = Field(ge=1)
    journey_revision: int = Field(ge=1)
    search_snapshot_id: str = Field(default="", max_length=200)
    corpus_source_hash: str = Field(default="", max_length=64)
    status: Literal["queued", "running", "partial", "ready", "failed", "stale"] = "queued"
    field_candidates: Dict[str, AuthoringPrefillFieldCandidates] = Field(
        default_factory=dict
    )
    progress: AuthoringPrefillProgress = Field(default_factory=AuthoringPrefillProgress)
    partial_source_failures: List[str] = Field(default_factory=list, max_length=50)
    # Product-internal lineage for a completed independent-AI prefill call.
    # This never represents an external provider job or request identifier.
    ai_run_id: str = Field(default="", max_length=200)
    ai_provider: str = Field(default="", max_length=200)
    model_name: str = Field(default="deterministic_registry_prefill", max_length=200)
    prompt_version: str = Field(default="authoring_prefill_v1", max_length=100)
    ai_input_sha256: str = Field(default="", max_length=64)
    ai_output_sha256: str = Field(default="", max_length=64)
    input_fingerprint: str = Field(default="", max_length=64)
    search_fingerprint: str = Field(default="", max_length=64)
    corpus_fingerprint: str = Field(default="", max_length=64)
    source_fact_fingerprint: str = Field(default="", max_length=64)
    evidence_catalog: Optional[AuthoringPrefillEvidenceCatalog] = None
    generated_at: datetime
    updated_at: datetime
    generated_by: str = Field(default="system", max_length=100)

    @model_validator(mode="after")
    def validate_package(self):
        self.package_id = self.package_id.strip()
        self.project_id = self.project_id.strip()
        self.search_snapshot_id = self.search_snapshot_id.strip()
        self.ai_run_id = self.ai_run_id.strip()
        self.ai_provider = self.ai_provider.strip()
        self.model_name = self.model_name.strip() or "deterministic_registry_prefill"
        self.prompt_version = self.prompt_version.strip() or "authoring_prefill_v1"
        self.ai_input_sha256 = self.ai_input_sha256.strip().lower()
        self.ai_output_sha256 = self.ai_output_sha256.strip().lower()
        for field_name in ("ai_input_sha256", "ai_output_sha256"):
            value = getattr(self, field_name)
            if value and (len(value) != 64 or not re.fullmatch(r"[0-9a-f]{64}", value)):
                raise ValueError(f"{field_name} must be 64 lowercase hex characters")
        self.partial_source_failures = [
            item.strip() for item in self.partial_source_failures if item.strip()
        ]
        for field_path, group in self.field_candidates.items():
            if group.field_path != field_path:
                raise ValueError("prefill package field key must match field_path")
        return self


class AuthoringPrefillGenerateRequest(WorkbenchModel):
    expected_revision: int = Field(ge=1)
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)
    force: bool = False

    @model_validator(mode="after")
    def normalize_generate_request(self):
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if not self.actor or not self.idempotency_key:
            raise ValueError("prefill generate actor and idempotency key must not be blank")
        return self


class AuthoringPrefillAdoptRequest(WorkbenchModel):
    expected_revision: int = Field(ge=1)
    expected_package_revision: int = Field(ge=1)
    field_path: str = Field(min_length=1, max_length=300)
    candidate_id: str = Field(default="", max_length=200)
    edited_value: Any = None
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def normalize_adopt_request(self):
        self.field_path = self.field_path.strip()
        self.candidate_id = self.candidate_id.strip()
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if not self.field_path or not self.actor or not self.idempotency_key:
            raise ValueError("prefill adopt fields must not be blank")
        if not self.candidate_id and self.edited_value is None:
            raise ValueError("prefill adopt requires a candidate_id or edited_value")
        return self


class AuthoringPrefillCompositeAdoptRequest(WorkbenchModel):
    """Request to atomically adopt a composite (module / design_package) candidate.

    Only the contract is defined here; the service-layer transaction that updates
    every ``target_path`` in a single commit is a later slice.
    """

    expected_revision: int = Field(ge=1)
    expected_package_revision: int = Field(ge=1)
    package_field_path: str = Field(min_length=1, max_length=300)
    candidate_id: str = Field(min_length=1, max_length=200)
    path_overrides: Dict[str, Any] = Field(default_factory=dict)
    skipped_paths: List[str] = Field(default_factory=list, max_length=50)
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def normalize_composite_adopt_request(self):
        self.package_field_path = self.package_field_path.strip()
        self.candidate_id = self.candidate_id.strip()
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if (
            not self.package_field_path
            or not self.candidate_id
            or not self.actor
            or not self.idempotency_key
        ):
            raise ValueError(
                "composite adopt requires package_field_path, candidate_id, "
                "actor and idempotency_key"
            )
        for override_path, override_value in self.path_overrides.items():
            stripped_path = override_path.strip()
            if not stripped_path:
                raise ValueError("path_overrides keys must be non-empty paths")
            if override_value is None:
                raise ValueError(
                    f"path_overrides value for '{stripped_path}' must not be None"
                )
        if self.path_overrides:
            normalized = {k.strip(): v for k, v in self.path_overrides.items()}
            if len(normalized) != len(self.path_overrides):
                raise ValueError("path_overrides keys must not collide after stripping")
            self.path_overrides = normalized
        if any(not path or not path.strip() for path in self.skipped_paths):
            raise ValueError("skipped_paths entries must be non-empty paths")
        self.skipped_paths = sorted({path.strip() for path in self.skipped_paths})
        overlap = set(self.path_overrides).intersection(self.skipped_paths)
        if overlap:
            raise ValueError(
                "path_overrides and skipped_paths must not overlap: "
                + ", ".join(sorted(overlap))
            )
        return self


class AuthoringPrefillCompositeSkippedPath(WorkbenchModel):
    path: str
    reason: str = Field(default="", max_length=500)


class AuthoringPrefillCompositeAdoptReceipt(WorkbenchModel):
    """Immutable per-path receipt persisted as the event payload for a single
    composite adoption transaction."""

    operation_id: str = Field(default="", max_length=200)
    package_id: str = Field(default="", max_length=200)
    candidate_id: str = Field(default="", max_length=200)
    package_field_path: str = Field(default="", max_length=300)
    journey_revision_before: int = Field(default=0, ge=0)
    journey_revision_after: int = Field(default=0, ge=0)
    package_revision_before: int = Field(default=0, ge=0)
    package_revision_after: int = Field(default=0, ge=0)
    applied_paths: List[str] = Field(default_factory=list)
    overridden_paths: List[str] = Field(default_factory=list)
    derived_paths: List[str] = Field(default_factory=list)
    skipped_paths: List[AuthoringPrefillCompositeSkippedPath] = Field(
        default_factory=list
    )
    invalidated_dependents: List[str] = Field(default_factory=list)
    search_plan_rebuilt: bool = False
    package_marked_stale: bool = False
    replayed: bool = False

    @model_validator(mode="after")
    def normalize_receipt(self):
        self.operation_id = self.operation_id.strip()
        self.package_id = self.package_id.strip()
        self.candidate_id = self.candidate_id.strip()
        self.package_field_path = self.package_field_path.strip()
        self.applied_paths = sorted(set(self.applied_paths))
        self.overridden_paths = sorted(set(self.overridden_paths))
        self.derived_paths = sorted(set(self.derived_paths))
        self.invalidated_dependents = sorted(set(self.invalidated_dependents))
        seen: set[str] = set()
        unique_skipped: list[AuthoringPrefillCompositeSkippedPath] = []
        for item in self.skipped_paths:
            path = item.path.strip()
            if not path or path in seen:
                continue
            seen.add(path)
            unique_skipped.append(
                AuthoringPrefillCompositeSkippedPath(
                    path=path,
                    reason=item.reason.strip(),
                )
            )
        unique_skipped.sort(key=lambda s: s.path)
        self.skipped_paths = unique_skipped
        return self


class AuthoringPrefillCompositeAdoptResult(WorkbenchModel):
    """Result returned by the composite adopt endpoint."""

    journey: Dict[str, Any]
    receipt: AuthoringPrefillCompositeAdoptReceipt


# ---------------------------------------------------------------------------
# W2b: Server-side evidence catalog and per-claim binding contracts.
# These are backward-compatible additions: old AuthoringPrefillCandidate JSON
# without the new fields still loads.  The catalog is an immutable, hash-stable
# snapshot of the evidence available to a single generate call.
# ---------------------------------------------------------------------------


class AuthoringPrefillEvidenceCatalogEntry(WorkbenchModel):
    catalog_entry_id: str = Field(min_length=1, max_length=200)
    catalog_id: str = Field(min_length=1, max_length=200)
    source_kind: Literal[
        "project_fact",
        "synopsis",
        "ctgov_snapshot",
        "registered_source",
        "evidence_brief",
    ]
    source_id: str = Field(default="", max_length=300)
    source_revision: str = Field(default="", max_length=300)
    locator: str = Field(default="", max_length=1_000)
    quote: str = Field(default="", max_length=20_000)
    quote_sha256: str = Field(default="", max_length=64)
    title: str = Field(default="", max_length=500)
    support_scope: Literal[
        "current_project_fact", "competitor_observation"
    ] = "current_project_fact"
    supported_target_paths: List[str] = Field(default_factory=list, max_length=100)
    provenance: Dict[str, Any] = Field(default_factory=dict, max_length=50)

    @model_validator(mode="after")
    def normalize_catalog_entry(self):
        # Normalize identifier fields (strip whitespace), but NEVER strip quote.
        for field_name in (
            "catalog_entry_id",
            "catalog_id",
            "source_id",
            "source_revision",
            "locator",
            "quote_sha256",
            "title",
        ):
            setattr(self, field_name, str(getattr(self, field_name)).strip())
        if not self.catalog_entry_id or not self.catalog_id:
            raise ValueError(
                "catalog entry requires catalog_entry_id and catalog_id"
            )
        # Normalize and strict-validate 64-hex-lowercase for quote_sha256.
        if self.quote_sha256:
            self.quote_sha256 = self.quote_sha256.lower()
            if len(self.quote_sha256) != 64 or not re.fullmatch(
                r"[0-9a-f]{64}", self.quote_sha256
            ):
                raise ValueError(
                    "catalog entry quote_sha256 must be 64 lowercase hex characters"
                )
        # If quote is provided, compute or verify hash against the UNMODIFIED quote.
        if self.quote:
            computed = sha256(self.quote.encode("utf-8")).hexdigest()
            if self.quote_sha256:
                if computed != self.quote_sha256:
                    raise ValueError(
                        "catalog entry quote_sha256 does not match the quote text"
                    )
            else:
                self.quote_sha256 = computed
        if not self.quote and not self.quote_sha256:
            raise ValueError(
                "catalog entry requires either quote or quote_sha256"
            )
        # Deduplicate supported_target_paths preserving order.
        seen: set[str] = set()
        paths: list[str] = []
        for path in self.supported_target_paths:
            stripped = path.strip()
            if stripped and stripped not in seen:
                seen.add(stripped)
                paths.append(stripped)
        self.supported_target_paths = paths
        if len(self.provenance) > 50:
            raise ValueError("catalog entry provenance must not exceed 50 keys")
        return self


class AuthoringPrefillClaimBinding(WorkbenchModel):
    target_path: str = Field(min_length=1, max_length=300)
    value_pointer: str = Field(default="", max_length=500)
    catalog_entry_id: str = Field(min_length=1, max_length=200)
    source_id: str = Field(default="", max_length=300)
    locator: str = Field(default="", max_length=1_000)
    quote_sha256: str = Field(min_length=64, max_length=64)
    support_kind: Literal[
        "exact_fact", "normalized_enum", "competitor_option"
    ] = "exact_fact"

    @model_validator(mode="after")
    def normalize_claim_binding(self):
        self.target_path = self.target_path.strip()
        self.value_pointer = self.value_pointer.strip()
        self.catalog_entry_id = self.catalog_entry_id.strip()
        self.source_id = self.source_id.strip()
        self.locator = self.locator.strip()
        self.quote_sha256 = self.quote_sha256.strip().lower()
        if not self.target_path or not self.catalog_entry_id:
            raise ValueError(
                "claim binding requires target_path and catalog_entry_id"
            )
        if len(self.quote_sha256) != 64 or not re.fullmatch(
            r"[0-9a-f]{64}", self.quote_sha256
        ):
            raise ValueError(
                "claim binding quote_sha256 must be 64 lowercase hex characters"
            )
        return self


class AuthoringPrefillEvidenceCatalog(WorkbenchModel):
    catalog_id: str = Field(min_length=1, max_length=200)
    project_id: str = Field(min_length=1, max_length=200)
    journey_revision: int = Field(ge=1)
    snapshot_id: str = Field(default="", max_length=200)
    entries: List[AuthoringPrefillEvidenceCatalogEntry] = Field(
        default_factory=list
    )
    catalog_sha256: str = Field(default="", max_length=64)
    truncation_notes: List[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def normalize_catalog(self):
        self.catalog_id = self.catalog_id.strip()
        self.project_id = self.project_id.strip()
        self.snapshot_id = self.snapshot_id.strip()
        self.catalog_sha256 = self.catalog_sha256.strip().lower()
        self.truncation_notes = [
            note.strip() for note in self.truncation_notes if note and note.strip()
        ]
        entry_ids = [entry.catalog_entry_id for entry in self.entries]
        if len(entry_ids) != len(set(entry_ids)):
            dupes = [eid for eid in entry_ids if entry_ids.count(eid) > 1]
            raise ValueError(
                f"catalog entries must have unique ids; duplicates: {set(dupes)}"
            )
        for entry in self.entries:
            if entry.catalog_id != self.catalog_id:
                raise ValueError(
                    f"catalog entry {entry.catalog_entry_id} catalog_id mismatch: "
                    f"expected {self.catalog_id}, got {entry.catalog_id}"
                )
        if not self.catalog_sha256:
            raise ValueError("catalog requires catalog_sha256")
        if len(self.catalog_sha256) != 64 or not re.fullmatch(
            r"[0-9a-f]{64}", self.catalog_sha256
        ):
            raise ValueError(
                "catalog_sha256 must be 64 lowercase hex characters"
            )
        return self


class MedicalWritingGreenfieldSectionSeed(WorkbenchModel):
    section_key: str = Field(min_length=1, max_length=80)
    heading: str = Field(min_length=1, max_length=200)
    parent_key: str = Field(default="", max_length=80)
    ich_m11_anchor: str = Field(default="", max_length=200)
    initial_text: str = Field(default="", max_length=100_000)
    source_fact_ids: List[str] = Field(default_factory=list, max_length=100)
    template_node_id: str = Field(default="", max_length=100)
    section_number: str = Field(default="", max_length=40)
    node_kind: str = Field(default="section", max_length=80)
    applicability_mode: str = Field(default="required", max_length=80)
    applicability_status: Literal[
        "applicable",
        "not_applicable",
        "unknown",
        "deferred",
    ] = "applicable"
    applicability_render_action: Literal[
        "retain_full",
        "omit",
        "retain_not_applicable",
        "retain_placeholder",
    ] = "retain_full"
    applicability_rationale: str = Field(default="", max_length=2_000)
    repeatable: bool = False
    title_locked: bool = False
    interaction_types: List[str] = Field(default_factory=list, max_length=10)
    initial_data: Dict[str, Any] = Field(default_factory=dict)
    drafting_status: Literal[
        "unclassified",
        "substantive_draft",
        "structural_content",
        "structural_container",
        "actionable_blocker",
        "not_applicable",
    ] = "unclassified"
    drafting_blocker_code: str = Field(default="", max_length=100)
    drafting_blocker_reason: str = Field(default="", max_length=2_000)
    drafting_missing_inputs: List[str] = Field(default_factory=list, max_length=100)
    drafting_resolution_actions: List[str] = Field(
        default_factory=list, max_length=20
    )

    @model_validator(mode="after")
    def validate_greenfield_section_seed(self):
        self.section_key = self.section_key.strip()
        self.heading = self.heading.strip()
        self.parent_key = self.parent_key.strip()
        self.ich_m11_anchor = self.ich_m11_anchor.strip()
        self.source_fact_ids = [item.strip() for item in self.source_fact_ids]
        if not self.section_key or not self.heading:
            raise ValueError("greenfield section key and heading must not be blank")
        if self.parent_key == self.section_key:
            raise ValueError("greenfield section cannot be its own parent")
        if any(not item for item in self.source_fact_ids):
            raise ValueError("greenfield section source fact ids must not be blank")
        if len(self.source_fact_ids) != len(set(self.source_fact_ids)):
            raise ValueError("greenfield section source fact ids must be unique")
        return _validate_section_drafting_readiness(self)


class MedicalWritingGreenfieldDecision(WorkbenchModel):
    decision_id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=200)
    status: Literal["unresolved", "resolved"] = "unresolved"
    value: str = Field(default="", max_length=20_000)
    rationale: str = Field(default="", max_length=20_000)
    source_refs: List[str] = Field(default_factory=list, max_length=100)
    approval_blocking: bool = True

    @model_validator(mode="after")
    def validate_greenfield_decision(self):
        self.decision_id = self.decision_id.strip()
        self.label = self.label.strip()
        self.value = self.value.strip()
        self.rationale = self.rationale.strip()
        self.source_refs = [item.strip() for item in self.source_refs]
        if not self.decision_id or not self.label:
            raise ValueError("greenfield decision id and label must not be blank")
        if any(not item for item in self.source_refs):
            raise ValueError("greenfield decision source refs must not be blank")
        if len(self.source_refs) != len(set(self.source_refs)):
            raise ValueError("greenfield decision source refs must be unique")
        if self.status == "resolved" and (not self.value or not self.rationale or not self.source_refs):
            raise ValueError(
                "resolved greenfield decision requires value, rationale, and source refs"
            )
        return self


class MedicalWritingGreenfieldCreateRequest(WorkbenchModel):
    protocol_id: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=80)
    document_title: str = Field(min_length=1, max_length=500)
    indication: str = Field(min_length=1, max_length=300)
    study_phase: str = Field(min_length=1, max_length=100)
    investigational_product: str = Field(default="", max_length=300)
    protocol_date: str = Field(default="", max_length=20)
    sponsor: str = Field(default="", max_length=300)
    source_study_definition_id: str = Field(default="", max_length=200)
    source_study_definition_revision: Optional[int] = Field(default=None, ge=1)
    source_study_definition_sha256: str = Field(default="", max_length=64)
    template_id: str = Field(default="", max_length=100)
    template_version: str = Field(default="", max_length=100)
    sections: List[MedicalWritingGreenfieldSectionSeed] = Field(
        default_factory=list,
        max_length=200,
    )
    decisions: List[MedicalWritingGreenfieldDecision] = Field(
        default_factory=list,
        max_length=200,
    )
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_greenfield_create_request(self):
        self.protocol_id = self.protocol_id.strip()
        self.version = self.version.strip()
        self.document_title = self.document_title.strip()
        self.indication = self.indication.strip()
        self.study_phase = self.study_phase.strip()
        self.investigational_product = self.investigational_product.strip()
        self.protocol_date = self.protocol_date.strip()
        self.sponsor = self.sponsor.strip()
        self.source_study_definition_id = self.source_study_definition_id.strip()
        self.source_study_definition_sha256 = self.source_study_definition_sha256.strip()
        self.template_id = self.template_id.strip()
        self.template_version = self.template_version.strip()
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if not all(
            (
                self.protocol_id,
                self.version,
                self.document_title,
                self.indication,
                self.study_phase,
                self.actor,
                self.idempotency_key,
            )
        ):
            raise ValueError(
                "greenfield document identity, actor, and idempotency key must not be blank"
            )
        template_binding = (bool(self.template_id), bool(self.template_version))
        if any(template_binding) and not all(template_binding):
            raise ValueError("greenfield template id and version must be provided together")
        if self.template_id and self.sections:
            raise ValueError("server-owned template requests must not provide client section seeds")
        if self.template_id and self.decisions:
            raise ValueError("server-owned template requests must not provide client approval decisions")
        if not self.template_id and not self.sections:
            raise ValueError("greenfield request requires a server template or legacy section seeds")
        section_keys = [item.section_key for item in self.sections]
        if len(section_keys) != len(set(section_keys)):
            raise ValueError("greenfield section keys must be unique")
        known_keys: set[str] = set()
        for section in self.sections:
            if section.parent_key and section.parent_key not in known_keys:
                raise ValueError(
                    "greenfield section parent must precede its child: "
                    f"{section.section_key}/{section.parent_key}"
                )
            known_keys.add(section.section_key)
        decision_ids = [item.decision_id for item in self.decisions]
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("greenfield decision ids must be unique")
        definition_binding = (
            bool(self.source_study_definition_id),
            self.source_study_definition_revision is not None,
            bool(self.source_study_definition_sha256),
        )
        if any(definition_binding) and not all(definition_binding):
            raise ValueError(
                "greenfield study-definition id, revision, and hash must be provided together"
            )
        if self.source_study_definition_sha256 and (
            len(self.source_study_definition_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.source_study_definition_sha256
            )
        ):
            raise ValueError("greenfield study-definition hash must be lowercase SHA-256")
        return self


class MedicalWritingGreenfieldCreateResult(WorkbenchModel):
    document: ProtocolDocument
    baseline_revision: int = Field(ge=1)
    baseline_sha256: str = Field(min_length=64, max_length=64)
    created: bool
    created_at: datetime
    decisions: List[MedicalWritingGreenfieldDecision] = Field(default_factory=list)


class MedicalWritingGreenfieldDecisionResolveRequest(WorkbenchModel):
    expected_baseline_revision: int = Field(ge=1)
    value: str = Field(min_length=1, max_length=20_000)
    rationale: str = Field(min_length=1, max_length=20_000)
    source_refs: List[str] = Field(min_length=1, max_length=100)
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_greenfield_decision_resolution(self):
        self.value = self.value.strip()
        self.rationale = self.rationale.strip()
        self.source_refs = [item.strip() for item in self.source_refs]
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if not self.value or not self.rationale or not self.actor or not self.idempotency_key:
            raise ValueError("greenfield decision resolution fields must not be blank")
        if any(not item for item in self.source_refs):
            raise ValueError("greenfield decision resolution source refs must not be blank")
        if len(self.source_refs) != len(set(self.source_refs)):
            raise ValueError("greenfield decision resolution source refs must be unique")
        return self


class MedicalWritingGreenfieldDecisionResolveResult(WorkbenchModel):
    project_id: str
    document_id: str
    baseline_revision: int = Field(ge=2)
    baseline_sha256: str = Field(min_length=64, max_length=64)
    decision: MedicalWritingGreenfieldDecision
    resolved_at: datetime


class MedicalWritingProtocolModuleResolutionApplyRequest(WorkbenchModel):
    expected_baseline_revision: int = Field(ge=1)
    expected_baseline_sha256: str = Field(min_length=64, max_length=64)
    semantic_node_id: str = Field(min_length=1, max_length=160)
    status: Literal[
        "applicable",
        "not_applicable",
        "unknown",
        "deferred",
    ]
    render_action: Literal[
        "retain_full",
        "omit",
        "retain_not_applicable",
        "retain_placeholder",
    ]
    rationale: str = Field(min_length=5, max_length=2_000)
    source_refs: List[str] = Field(min_length=1, max_length=100)
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_protocol_module_resolution_apply(self):
        self.expected_baseline_sha256 = self.expected_baseline_sha256.strip()
        self.semantic_node_id = self.semantic_node_id.strip()
        self.rationale = self.rationale.strip()
        self.source_refs = [item.strip() for item in self.source_refs if item.strip()]
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        resolution = MedicalWritingProtocolModuleResolution(
            template_node_id="pending_template_node",
            semantic_node_id=self.semantic_node_id,
            status=self.status,
            render_action=self.render_action,
            resolution_source="user_override",
            rationale=self.rationale,
            source_fact_ids=self.source_refs,
            user_override=True,
        )
        if not resolution or not self.actor or not self.idempotency_key:
            raise ValueError("protocol module resolution identity must not be blank")
        if len(self.source_refs) != len(set(self.source_refs)):
            raise ValueError("protocol module resolution source refs must be unique")
        return self


class MedicalWritingProtocolModuleResolutionApplyResult(WorkbenchModel):
    project_id: str
    document_id: str
    baseline_revision: int = Field(ge=2)
    baseline_sha256: str = Field(min_length=64, max_length=64)
    resolution: MedicalWritingProtocolModuleResolution
    added_section_ids: List[str] = Field(default_factory=list)
    updated_section_ids: List[str] = Field(default_factory=list)
    removed_section_ids: List[str] = Field(default_factory=list)
    quarantined_section_ids: List[str] = Field(default_factory=list)
    reset_working_copy_ids: List[str] = Field(default_factory=list)
    reset_approval_count: int = Field(default=0, ge=0)
    affected_artifacts: List[str] = Field(default_factory=list)
    applied_at: datetime


class MedicalWritingTemplateUpgradeSectionMapping(WorkbenchModel):
    source_section_id: str = Field(min_length=1, max_length=200)
    source_heading: str = Field(min_length=1, max_length=500)
    source_section_key: str = Field(min_length=1, max_length=200)
    source_content_revision: int = Field(ge=0)
    source_content_origin: Literal["baseline", "working_copy"]
    source_approval_state: ApprovalState = ApprovalState.AI_DRAFT
    target_template_node_id: str = Field(min_length=1, max_length=200)
    target_section_number: str = Field(default="", max_length=40)
    target_heading: str = Field(min_length=1, max_length=500)
    mapping_kind: Literal["direct", "consolidated"] = "direct"
    content_block_count: int = Field(ge=0)
    nonempty_content_block_count: int = Field(ge=0)
    approval_will_reset: bool = True


class MedicalWritingTemplateUpgradePreview(WorkbenchModel):
    project_id: str
    current_document_id: str
    current_template_id: str = ""
    current_template_version: str
    current_baseline_revision: int = Field(ge=1)
    current_baseline_sha256: str = Field(min_length=64, max_length=64)
    target_template_id: str
    target_template_version: str
    target_template_definition_sha256: str = Field(min_length=64, max_length=64)
    source_section_count: int = Field(ge=1)
    target_section_count: int = Field(ge=1)
    mapped_source_section_count: int = Field(ge=0)
    working_copy_count: int = Field(ge=0)
    approval_reset_count: int = Field(ge=0)
    mappings: List[MedicalWritingTemplateUpgradeSectionMapping] = Field(
        default_factory=list
    )
    unmapped_source_section_ids: List[str] = Field(default_factory=list)
    consolidation_target_node_ids: List[str] = Field(default_factory=list)
    blockers: List[str] = Field(default_factory=list)
    can_apply: bool = False
    preview_sha256: str = Field(min_length=64, max_length=64)
    generated_at: datetime


class MedicalWritingTemplateUpgradeApplyRequest(WorkbenchModel):
    expected_baseline_revision: int = Field(ge=1)
    expected_baseline_sha256: str = Field(min_length=64, max_length=64)
    expected_preview_sha256: str = Field(min_length=64, max_length=64)
    target_template_id: str = Field(min_length=1, max_length=100)
    target_template_version: str = Field(min_length=1, max_length=100)
    target_template_definition_sha256: str = Field(min_length=64, max_length=64)
    acknowledge_consolidation: bool = False
    acknowledge_approval_reset: bool = False
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)


class MedicalWritingTemplateUpgradeApplyResult(WorkbenchModel):
    project_id: str
    previous_document_id: str
    document: ProtocolDocument
    baseline_revision: int = Field(ge=2)
    baseline_sha256: str = Field(min_length=64, max_length=64)
    migration_event_id: str = Field(min_length=1, max_length=200)
    migrated_source_section_count: int = Field(ge=1)
    target_section_count: int = Field(ge=1)
    approval_reset_count: int = Field(ge=0)
    applied_at: datetime


class MedicalWritingTemplateUpgradeRollbackRequest(WorkbenchModel):
    migration_event_id: str = Field(min_length=1, max_length=200)
    expected_baseline_revision: int = Field(ge=2)
    expected_baseline_sha256: str = Field(min_length=64, max_length=64)
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)


class MedicalWritingTemplateUpgradeRollbackResult(WorkbenchModel):
    project_id: str
    removed_document_id: str
    restored_document: ProtocolDocument
    baseline_revision: int = Field(ge=3)
    baseline_sha256: str = Field(min_length=64, max_length=64)
    rollback_event_id: str = Field(min_length=1, max_length=200)
    rolled_back_at: datetime


class MedicalWritingWorkingCopy(WorkbenchModel):
    working_copy_id: str
    project_id: str
    document_id: str
    section_id: str
    source_document_version: str
    revision: int = Field(ge=0)
    content_blocks: List[Dict[str, Any]] = Field(default_factory=list)
    approval_state: ApprovalState = ApprovalState.AI_DRAFT
    approved_revision: Optional[int] = Field(default=None, ge=0)
    approved_snapshot_id: Optional[str] = None
    freeze_status: Literal["editable", "frozen", "invalidated"] = "editable"
    frozen_revision: Optional[int] = Field(default=None, ge=1)
    frozen_snapshot_id: Optional[str] = None
    frozen_by: str = ""
    frozen_at: Optional[datetime] = None
    frozen_study_definition_id: str = ""
    frozen_study_definition_revision: Optional[int] = Field(default=None, ge=1)
    frozen_study_definition_sha256: str = ""
    source_study_definition_id: str = ""
    source_study_definition_revision: Optional[int] = Field(default=None, ge=1)
    source_study_definition_sha256: str = ""
    content_authority_state: Literal[
        "active_authoritative", "historical_quarantined"
    ] = "historical_quarantined"
    quarantined_revision: Optional[int] = Field(default=None, ge=0)
    quarantine_reason: str = ""
    study_definition_reconciliation_required: bool = False
    study_definition_reconciliation_reason: str = ""
    applied_revision_thread_ids: List[str] = Field(default_factory=list)
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_working_copy_study_definition_binding(self):
        self.source_study_definition_id = self.source_study_definition_id.strip()
        self.source_study_definition_sha256 = self.source_study_definition_sha256.strip()
        binding = (
            bool(self.source_study_definition_id),
            self.source_study_definition_revision is not None,
            bool(self.source_study_definition_sha256),
        )
        if any(binding) and not all(binding):
            raise ValueError(
                "working copy study-definition id, revision, and hash must be provided together"
            )
        if self.frozen_snapshot_id is not None:
            self.frozen_snapshot_id = self.frozen_snapshot_id.strip() or None
        self.frozen_by = self.frozen_by.strip()
        self.frozen_study_definition_id = self.frozen_study_definition_id.strip()
        self.frozen_study_definition_sha256 = (
            self.frozen_study_definition_sha256.strip()
        )
        freeze_identity = (
            self.frozen_revision is not None,
            bool(self.frozen_snapshot_id),
            bool(self.frozen_by),
            self.frozen_at is not None,
        )
        freeze_binding = (
            bool(self.frozen_study_definition_id),
            self.frozen_study_definition_revision is not None,
            bool(self.frozen_study_definition_sha256),
        )
        if self.freeze_status == "frozen":
            if not all(freeze_identity):
                raise ValueError(
                    "a frozen working copy requires revision, snapshot, actor, and timestamp"
                )
            if any(binding) and not all(freeze_binding):
                raise ValueError(
                    "a frozen working copy requires the complete StudyDefinition binding"
                )
        if any(freeze_identity) and not all(freeze_identity):
            raise ValueError(
                "working-copy freeze revision, snapshot, actor, and timestamp must be provided together"
            )
        if any(freeze_binding) and not all(freeze_binding):
            raise ValueError(
                "working-copy freeze StudyDefinition id, revision, and hash must be provided together"
            )
        return self


class MedicalWritingSectionFreezeRequest(WorkbenchModel):
    document_id: str = Field(min_length=1, max_length=200)
    expected_working_copy_revision: int = Field(ge=1)
    expected_study_definition_id: str = Field(default="", max_length=200)
    expected_study_definition_revision: Optional[int] = Field(default=None, ge=1)
    expected_study_definition_sha256: str = Field(default="", max_length=64)
    reason: str = Field(default="作者确认当前章节内容已定稿。", min_length=6, max_length=2_000)
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=8, max_length=200)

    @model_validator(mode="after")
    def normalize_freeze_request(self):
        self.document_id = self.document_id.strip()
        self.expected_study_definition_id = self.expected_study_definition_id.strip()
        self.expected_study_definition_sha256 = (
            self.expected_study_definition_sha256.strip()
        )
        self.reason = self.reason.strip()
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        binding = (
            bool(self.expected_study_definition_id),
            self.expected_study_definition_revision is not None,
            bool(self.expected_study_definition_sha256),
        )
        if any(binding) and not all(binding):
            raise ValueError(
                "section freeze expected StudyDefinition id, revision, and hash must be provided together"
            )
        if self.expected_study_definition_sha256 and len(
            self.expected_study_definition_sha256
        ) != 64:
            raise ValueError("section freeze expected StudyDefinition hash must be SHA-256")
        return self


class MedicalWritingSectionFreezeRecord(WorkbenchModel):
    snapshot_id: str
    project_id: str
    document_id: str
    section_id: str
    working_copy_id: str
    working_copy_revision: int = Field(ge=1)
    study_definition_id: str = ""
    study_definition_revision: Optional[int] = Field(default=None, ge=1)
    study_definition_sha256: str = ""
    frozen_by: str = ""
    frozen_at: datetime
    audit_id: str = ""
    source: Literal["author_freeze", "legacy_medical_approval"] = "author_freeze"
    is_current: bool = False


class MedicalWritingSectionFreezeResult(WorkbenchModel):
    operation: Literal["freeze_current_version", "unfreeze"]
    working_copy: MedicalWritingWorkingCopy
    freeze_record: Optional[MedicalWritingSectionFreezeRecord] = None
    audit_event: Optional[AuditEvent] = None
    replayed: bool = False


class MedicalWritingSectionFreezeGap(WorkbenchModel):
    section_id: str
    section_heading: str
    reason_code: Literal[
        "working_copy_not_saved",
        "working_copy_quarantined",
        "section_not_frozen",
        "freeze_invalidated",
        "freeze_snapshot_missing",
        "freeze_snapshot_inconsistent",
        "applicability_unresolved",
    ]
    message: str
    current_revision: int = Field(ge=0)
    frozen_revision: Optional[int] = Field(default=None, ge=1)


class MedicalWritingFinalFreezeReadiness(WorkbenchModel):
    project_id: str
    document_id: str
    ready: bool = False
    required_section_count: int = Field(ge=0)
    current_frozen_section_count: int = Field(ge=0)
    omitted_not_applicable_section_count: int = Field(ge=0)
    gaps: List[MedicalWritingSectionFreezeGap] = Field(default_factory=list)


class MedicalWritingStudyReconciliationConfirmRequest(WorkbenchModel):
    document_id: str = Field(min_length=1, max_length=200)
    expected_working_copy_revision: int = Field(ge=1)
    reason: str = Field(min_length=10, max_length=2_000)
    acknowledge_content_reconciled: bool = False
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def normalize_reconciliation_confirmation(self):
        self.document_id = self.document_id.strip()
        self.reason = self.reason.strip()
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if not self.acknowledge_content_reconciled:
            raise ValueError("section reconciliation requires explicit acknowledgement")
        return self


class MedicalWritingStudyReconciliationConfirmResult(WorkbenchModel):
    working_copy: MedicalWritingWorkingCopy
    consistency: MedicalWritingStudyConsistencyStatus
    audit_id: str


class MedicalWritingWorkingCopySaveRequest(WorkbenchModel):
    document_id: str
    expected_revision: int = Field(ge=0)
    content_blocks: List[Dict[str, Any]] = Field(default_factory=list)
    actor: str = "medical_manager"
    idempotency_key: str = ""


class MedicalWritingWorkingCopyBindingRecoveryRequest(WorkbenchModel):
    document_id: str = Field(min_length=1, max_length=200)
    expected_working_copy_revision: int = Field(ge=0)
    reason: str = Field(min_length=10, max_length=2_000)
    acknowledge_binding: bool = False
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=8, max_length=200)

    @model_validator(mode="after")
    def normalize_binding_recovery(self):
        self.document_id = self.document_id.strip()
        self.reason = self.reason.strip()
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if not self.acknowledge_binding:
            raise ValueError("working-copy binding recovery requires explicit acknowledgement")
        return self


class MedicalWritingWorkingCopyBindingRecoveryResult(WorkbenchModel):
    operation: Literal["accept_and_bind", "revert_to_authoritative_baseline"]
    working_copy: MedicalWritingWorkingCopy
    quarantined_snapshot_id: str = ""
    audit_event: AuditEvent


class MedicalWritingContentDispositionStatus(str, Enum):
    OPEN = "open"
    CONFIRMED_SOURCE_TEXT = "confirmed_source_text"
    CORRECTION_REQUIRED = "correction_required"


class MedicalWritingContentFinding(WorkbenchModel):
    finding_id: str
    project_id: str
    document_id: str
    document_version: str
    section_id: str
    section_heading: str
    block_id: str
    location_kind: str
    source_kind: str = "original_protocol_docx"
    source_text: str
    matched_text: str
    match_start: int = Field(ge=0)
    match_end: int = Field(ge=0)
    occurrence_index: int = Field(ge=0)
    source_locator: str = ""
    table_id: str = ""
    cell_id: str = ""
    row_index: Optional[int] = Field(default=None, ge=0)
    cell_index: Optional[int] = Field(default=None, ge=0)
    rule_code: str
    rule_label: str
    detector_version: str = "medical_writing_content_quality_v1"
    finding_reason: str
    severity: RiskSeverity = RiskSeverity.HIGH
    approval_blocking: bool = True
    content_fingerprint: str
    content_revision: int = Field(default=0, ge=0)
    disposition_status: MedicalWritingContentDispositionStatus = (
        MedicalWritingContentDispositionStatus.OPEN
    )
    disposition_revision: int = Field(default=0, ge=0)
    disposition_reason: str = ""
    disposition_actor: str = ""
    disposition_at: Optional[datetime] = None


class MedicalWritingContentDispositionRequest(WorkbenchModel):
    status: MedicalWritingContentDispositionStatus
    reason: str
    actor: str = "medical_manager"
    expected_content_fingerprint: str = Field(min_length=64, max_length=64)
    expected_content_revision: int = Field(ge=0)
    expected_disposition_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=160)


class MedicalWritingContentDispositionRecord(WorkbenchModel):
    record_id: str
    finding_id: str
    project_id: str
    document_id: str
    document_version: str
    section_id: str
    source_locator: str = ""
    rule_code: str
    detector_version: str = "medical_writing_content_quality_v1"
    content_fingerprint: str
    content_revision: int = Field(ge=0)
    previous_status: MedicalWritingContentDispositionStatus
    status: MedicalWritingContentDispositionStatus
    revision: int = Field(ge=1)
    reason: str
    actor: str
    identity_assurance: str = "unverified_client_claim"
    created_at: datetime


class MedicalWritingContentQualityResult(WorkbenchModel):
    project_id: str
    document_id: str
    document_version: str
    section_id: str = ""
    finding_count: int = Field(ge=0)
    open_count: int = Field(ge=0)
    correction_required_count: int = Field(ge=0)
    confirmed_count: int = Field(ge=0)
    approval_blocking_count: int = Field(ge=0)
    findings: List[MedicalWritingContentFinding] = Field(default_factory=list)


class MedicalWritingTableBatchUpdateRequest(WorkbenchModel):
    expected_working_copy_revision: int = Field(ge=0)
    expected_table_version: int = Field(ge=0)
    operations: List[Dict[str, Any]] = Field(min_length=1, max_length=500)
    actor: str = "medical_manager"
    idempotency_key: str = Field(min_length=8, max_length=160)


class MedicalWritingTableBatchUpdateResult(WorkbenchModel):
    working_copy: MedicalWritingWorkingCopy
    table: StructuredTable
    table_block: Dict[str, Any]


class MedicalWritingRevisionApplyRequest(WorkbenchModel):
    expected_working_copy_revision: int = Field(ge=0)
    actor: str = "medical_manager"
    idempotency_key: str = Field(min_length=8, max_length=160)


class MedicalWritingRevisionApplyResult(WorkbenchModel):
    thread_id: str
    suggestion_id: str
    working_copy: MedicalWritingWorkingCopy
    audit_event: AuditEvent


class MedicalWritingTableCellAnchor(WorkbenchModel):
    """Server-normalized identity for one working-copy table cell."""

    working_copy_id: str = ""
    working_copy_revision: int = Field(ge=0)
    table_version: int = Field(ge=0)
    block_hash: str = ""
    block_id: str
    table_id: str
    row_id: str
    column_id: str
    cell_id: str
    captured_text: str = ""
    source_kind: str = "source_linked"


class RevisionDiffSegment(WorkbenchModel):
    """Deterministic text diff segment for one AI revision candidate.

    Coordinates are Python string offsets into the immutable selected text and
    the candidate proposal.  A replacement is represented as a delete followed
    by an insert so the ordering is stable and consumers never have to infer a
    hidden replacement operation.
    """

    operation: Literal["equal", "delete", "insert"]
    source_start: int = Field(ge=0)
    source_end: int = Field(ge=0)
    proposal_start: int = Field(ge=0)
    proposal_end: int = Field(ge=0)
    text: str

    @model_validator(mode="after")
    def validate_coordinates(self) -> "RevisionDiffSegment":
        if self.source_end < self.source_start or self.proposal_end < self.proposal_start:
            raise ValueError("revision diff segment coordinates must be ordered")
        source_length = self.source_end - self.source_start
        proposal_length = self.proposal_end - self.proposal_start
        if self.operation == "equal":
            if source_length != proposal_length or len(self.text) != source_length:
                raise ValueError("equal revision diff segment has inconsistent coordinates")
        elif self.operation == "delete":
            if source_length != len(self.text) or proposal_length != 0:
                raise ValueError("delete revision diff segment has inconsistent coordinates")
        elif proposal_length != len(self.text) or source_length != 0:
            raise ValueError("insert revision diff segment has inconsistent coordinates")
        return self


def canonical_revision_diff_segments(
    source_text: str,
    proposal_text: str,
) -> list[RevisionDiffSegment]:
    """Build the one canonical segment sequence accepted by the contract."""

    source = str(source_text)
    proposal = str(proposal_text)
    segments: list[RevisionDiffSegment] = []
    matcher = SequenceMatcher(a=source, b=proposal, autojunk=False)
    for operation, source_start, source_end, proposal_start, proposal_end in matcher.get_opcodes():
        if operation == "equal":
            segments.append(
                RevisionDiffSegment(
                    operation="equal",
                    source_start=source_start,
                    source_end=source_end,
                    proposal_start=proposal_start,
                    proposal_end=proposal_end,
                    text=source[source_start:source_end],
                )
            )
        elif operation in {"delete", "replace"} and source_start != source_end:
            segments.append(
                RevisionDiffSegment(
                    operation="delete",
                    source_start=source_start,
                    source_end=source_end,
                    proposal_start=proposal_start,
                    proposal_end=proposal_start,
                    text=source[source_start:source_end],
                )
            )
        if operation in {"insert", "replace"} and proposal_start != proposal_end:
            segments.append(
                RevisionDiffSegment(
                    operation="insert",
                    source_start=source_end,
                    source_end=source_end,
                    proposal_start=proposal_start,
                    proposal_end=proposal_end,
                    text=proposal[proposal_start:proposal_end],
                )
            )
    return segments


class RevisionImpactRef(WorkbenchModel):
    """Auditable local/downstream impact locator for one revision candidate."""

    scope: Literal["local", "downstream", "unresolved"]
    target_type: Literal["section", "paragraph", "table", "table_cell", "unknown"]
    section_id: str = ""
    target_id: str = ""
    block_id: str = ""
    reason_code: str
    matched_source_fact_ids: List[str] = Field(default_factory=list)
    message: str = ""

    @model_validator(mode="after")
    def normalize_identity(self) -> "RevisionImpactRef":
        self.section_id = self.section_id.strip()
        self.target_id = self.target_id.strip()
        self.block_id = self.block_id.strip()
        self.reason_code = self.reason_code.strip()
        self.matched_source_fact_ids = sorted(
            {item.strip() for item in self.matched_source_fact_ids if item.strip()}
        )
        self.message = self.message.strip()
        if not self.reason_code:
            raise ValueError("revision impact reason_code must not be blank")
        return self


class RevisionProtectedTokenIssue(WorkbenchModel):
    """Auditable identity-token issue detected in a revision candidate."""

    kind: Literal[
        "numeric",
        "numeric_unit",
        "controlled_term",
        "citation",
        "cross_reference",
        "sequence",
    ]
    source_text: str = ""
    proposal_text: str = ""
    reason_code: Literal[
        "protected_token_missing",
        "protected_token_order_changed",
        "protected_token_added_unresolved",
    ]
    message: str = ""

    @model_validator(mode="after")
    def normalize_issue(self) -> "RevisionProtectedTokenIssue":
        self.source_text = self.source_text.strip()
        self.proposal_text = self.proposal_text.strip()
        self.message = self.message.strip()
        return self


class RevisionSuggestion(WorkbenchModel):
    suggestion_id: str
    proposal_text: str
    diff_patch: str
    rationale: str
    evidence_span_ids: List[str] = Field(default_factory=list)
    evidence_source_types: List[str] = Field(default_factory=list)
    fact_adoption_status: Literal[
        "candidate_only",
        "adopted_as_project_fact",
        "superseded",
    ] = "candidate_only"
    uncertainty: str = ""
    user_decision: str = "pending"
    turn_number: int = Field(default=1, ge=1)
    parent_suggestion_id: str = ""
    user_instruction: str = ""
    user_comment: str = ""
    ai_run_id: str = ""
    # Additive deterministic local diff and impact fields.  Legacy rows omit
    # them and remain readable as ``legacy_unavailable``.
    diff_segments: List[RevisionDiffSegment] = Field(default_factory=list)
    diff_source_hash: str = Field(default="", max_length=64)
    diff_proposal_hash: str = Field(default="", max_length=64)
    impact_status: Literal["known", "unresolved", "legacy_unavailable"] = (
        "legacy_unavailable"
    )
    impact_refs: List[RevisionImpactRef] = Field(default_factory=list)
    protected_token_status: Literal[
        "verified",
        "violated",
        "unresolved",
        "legacy_unavailable",
    ] = "legacy_unavailable"
    protected_token_issues: List[RevisionProtectedTokenIssue] = Field(
        default_factory=list
    )
    created_at: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_fact_adoption_state(self) -> "RevisionSuggestion":
        self.evidence_source_types = sorted(
            {
                source_type.strip()
                for source_type in self.evidence_source_types
                if source_type.strip()
            }
        )
        if (
            self.user_decision == "accepted"
            and self.fact_adoption_status == "candidate_only"
        ):
            # Legacy records already contain the medical author's explicit
            # selection but predate the structured adoption field.
            self.fact_adoption_status = "adopted_as_project_fact"
        if (
            self.fact_adoption_status == "adopted_as_project_fact"
            and self.user_decision != "accepted"
        ):
            raise ValueError(
                "a project-fact adoption requires explicit medical-author acceptance"
            )
        self.diff_source_hash = self.diff_source_hash.strip().lower()
        self.diff_proposal_hash = self.diff_proposal_hash.strip().lower()
        has_diff_segments = bool(self.diff_segments)
        has_source_hash = bool(self.diff_source_hash)
        has_proposal_hash = bool(self.diff_proposal_hash)
        # The additive contract is all-or-nothing.  Legacy rows are allowed
        # only when all three deterministic identity components are absent;
        # otherwise a caller could persist/render a diff that is not bound to
        # either the selected source or the proposal text.
        if has_diff_segments or has_source_hash or has_proposal_hash:
            if not (has_diff_segments and has_source_hash and has_proposal_hash):
                raise ValueError(
                    "revision diff segments and paired hashes must be provided together"
                )
            if not self.diff_source_hash or not self.diff_proposal_hash:
                raise ValueError(
                    "revision diff source and proposal hashes must be provided together"
                )
            if not re.fullmatch(r"[0-9a-f]{64}", self.diff_source_hash) or not re.fullmatch(
                r"[0-9a-f]{64}", self.diff_proposal_hash
            ):
                raise ValueError("revision diff hashes must be lowercase SHA-256")
            expected_proposal_hash = sha256(
                self.proposal_text.encode("utf-8")
            ).hexdigest()
            if self.diff_proposal_hash != expected_proposal_hash:
                raise ValueError(
                    "revision diff proposal hash does not match proposal_text"
                )
        if self.impact_status != "legacy_unavailable" and not self.diff_source_hash:
            raise ValueError(
                "revision impact status requires deterministic diff identity"
            )
        token_fields_supplied = (
            "protected_token_status" in self.model_fields_set
            or "protected_token_issues" in self.model_fields_set
        )
        if (
            token_fields_supplied
            and self.protected_token_status == "legacy_unavailable"
            and self.protected_token_issues
        ):
            raise ValueError(
                "legacy protected-token status cannot carry protected-token issues"
            )
        if self.protected_token_status == "violated" and not self.protected_token_issues:
            raise ValueError(
                "a violated protected-token status requires auditable issues"
            )
        if (
            self.protected_token_status != "legacy_unavailable"
            and not self.diff_source_hash
        ):
            raise ValueError(
                "protected-token status requires deterministic diff identity"
            )
        return self


class RevisionAction(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    REQUEST_REWRITE = "request_rewrite"


class RevisionThread(WorkbenchModel):
    thread_id: str
    project_id: str
    document_id: str
    section_id: str
    anchor_type: str
    anchor_path: str
    selected_text: str
    user_instruction: str
    intent: str
    ai_run_id: str
    # Stable semantic identity for the exact normalized selection.  The field
    # is additive so legacy JSON can be loaded and deterministically backfilled
    # by the model validator below.
    selected_hash: str = Field(default="", max_length=64)
    source_entry_id: str = ""
    source_id: str = ""
    source_locator: str = ""
    table_cell_anchor: Optional[MedicalWritingTableCellAnchor] = None
    evidence_brief_ids: List[str] = Field(default_factory=list)
    evidence_source_types: List[str] = Field(default_factory=list)
    ai_policy_decision_id: str = ""
    source_study_definition_id: str = ""
    source_study_definition_revision: Optional[int] = Field(default=None, ge=1)
    source_study_definition_sha256: str = ""
    source_working_copy_id: str = ""
    source_working_copy_revision: Optional[int] = Field(default=None, ge=0)
    source_working_copy_content_sha256: str = ""
    # Durable generation lineage (section AI candidate jobs). Empty for legacy threads.
    generation_context_version: str = ""
    generation_context_digest: str = ""
    suggestions: List[RevisionSuggestion] = Field(default_factory=list)
    status: str = "open"
    created_at: datetime
    resolved_at: Optional[datetime] = None

    @staticmethod
    def selected_text_hash(value: str) -> str:
        return sha256(str(value).encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def normalize_evidence_source_types(self) -> "RevisionThread":
        self.evidence_source_types = sorted(
            {
                source_type.strip()
                for source_type in self.evidence_source_types
                if source_type.strip()
            }
        )
        self.source_study_definition_id = self.source_study_definition_id.strip()
        self.source_study_definition_sha256 = self.source_study_definition_sha256.strip()
        selected_hash_was_supplied = "selected_hash" in self.model_fields_set
        self.selected_hash = self.selected_hash.strip().lower()
        expected_selected_hash = self.selected_text_hash(self.selected_text)
        if selected_hash_was_supplied and self.selected_hash != expected_selected_hash:
            raise ValueError(
                "revision thread selected_hash does not match selected_text"
            )
        # Legacy persisted threads did not carry this field.  Backfill them at
        # the model boundary so snapshots/CAS comparisons use one normalized
        # payload without a schema migration or silent hash invention.
        self.selected_hash = expected_selected_hash
        for suggestion in self.suggestions:
            if suggestion.diff_source_hash and suggestion.diff_source_hash != self.selected_hash:
                raise ValueError(
                    "revision suggestion diff source hash does not match selected_text"
                )
            if suggestion.diff_source_hash:
                expected_segments = canonical_revision_diff_segments(
                    self.selected_text, suggestion.proposal_text
                )
                actual_segments = [
                    item.model_dump(mode="json") for item in suggestion.diff_segments
                ]
                canonical_segments = [
                    item.model_dump(mode="json") for item in expected_segments
                ]
                if actual_segments != canonical_segments:
                    raise ValueError(
                        "revision diff segments do not replay selected_text and proposal_text"
                    )
            token_fields_supplied = (
                "protected_token_status" in suggestion.model_fields_set
                or "protected_token_issues" in suggestion.model_fields_set
            )
            if token_fields_supplied and suggestion.protected_token_status != "legacy_unavailable":
                token_check = check_protected_tokens(
                    self.selected_text,
                    suggestion.proposal_text,
                )
                expected_token_issues = protected_token_issue_dicts(token_check)
                actual_token_issues = [
                    item.model_dump(mode="json")
                    for item in suggestion.protected_token_issues
                ]
                if suggestion.protected_token_status != token_check.status:
                    raise ValueError(
                        "revision protected-token status does not match selected_text and proposal_text"
                    )
                if actual_token_issues != expected_token_issues:
                    raise ValueError(
                        "revision protected-token issues do not match selected_text and proposal_text"
                    )
        binding = (
            bool(self.source_study_definition_id),
            self.source_study_definition_revision is not None,
            bool(self.source_study_definition_sha256),
        )
        if any(binding) and not all(binding):
            raise ValueError(
                "revision thread study-definition id, revision, and hash must be provided together"
            )
        self.source_working_copy_id = self.source_working_copy_id.strip()
        self.source_working_copy_content_sha256 = (
            self.source_working_copy_content_sha256.strip()
        )
        working_binding = (
            bool(self.source_working_copy_id),
            self.source_working_copy_revision is not None,
            bool(self.source_working_copy_content_sha256),
        )
        if any(working_binding) and not all(working_binding):
            raise ValueError(
                "revision thread working-copy id, revision, and hash must be provided together"
            )
        if self.source_working_copy_content_sha256 and (
            len(self.source_working_copy_content_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.source_working_copy_content_sha256
            )
        ):
            raise ValueError("revision thread working-copy hash must be lowercase SHA-256")
        return self


class MedicalWritingRevisionRequest(WorkbenchModel):
    document_id: Optional[str] = None
    section_id: str
    anchor_type: str = "paragraph"
    anchor_path: str = ""
    selected_text: str = ""
    table_cell_anchor: Optional[MedicalWritingTableCellAnchor] = None
    user_instruction: str
    intent: str = "medical_writing_revision"
    evidence_brief_ids: List[str] = Field(default_factory=list)
    requested_by: str = "medical_manager"


class MedicalWritingRevisionResult(WorkbenchModel):
    thread: RevisionThread
    suggestion: RevisionSuggestion
    approval_state: ApprovalState = ApprovalState.IN_MEDICAL_REVIEW
    audit_event: AuditEvent


class MedicalWritingReferenceManualMetadata(WorkbenchModel):
    title: str = ""
    authors: List[str] = Field(default_factory=list)
    journal: str = ""
    year: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    doi: str = ""
    pmid: str = ""
    url: str = ""


class MedicalWritingReferenceImportRequest(WorkbenchModel):
    source_input: str = Field(min_length=1, max_length=2_000)
    manual_metadata: Optional[MedicalWritingReferenceManualMetadata] = None
    override_validation: bool = False
    override_reason: str = Field(default="", max_length=2_000)
    actor: str = Field(default="medical_manager", min_length=2, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=160)

    @model_validator(mode="after")
    def normalize_reference_import(self) -> "MedicalWritingReferenceImportRequest":
        self.source_input = self.source_input.strip()
        self.override_reason = self.override_reason.strip()
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if self.manual_metadata:
            values = self.manual_metadata.model_dump()
            for field_name, value in values.items():
                if isinstance(value, str):
                    setattr(self.manual_metadata, field_name, value.strip())
            self.manual_metadata.authors = [
                item.strip() for item in self.manual_metadata.authors if item.strip()
            ]
        return self


class MedicalWritingProjectReference(WorkbenchModel):
    reference_id: str
    project_id: str
    canonical_key: str
    source_kind: Literal["doi", "pmid", "pubmed_url", "publisher_url", "manual"]
    source_input: str
    title: str
    authors: List[str] = Field(default_factory=list)
    journal: str = ""
    year: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    doi: str = ""
    pmid: str = ""
    url: str = ""
    validation_status: Literal["confirmed", "needs_review", "overridden"] = "confirmed"
    validation_warnings: List[str] = Field(default_factory=list)
    override_reason: str = ""
    revision: int = Field(default=1, ge=1)
    created_by: str = "medical_manager"
    updated_by: str = "medical_manager"
    created_at: datetime
    updated_at: datetime


class MedicalWritingReferenceImportResult(WorkbenchModel):
    reference: MedicalWritingProjectReference
    created: bool
    matched_on: str


class MedicalWritingCitationStyleUpdateRequest(WorkbenchModel):
    citation_style: Literal["gbt_7714_2015_numeric", "gbt_7714_2025_numeric"]
    actor: str = Field(default="medical_manager", min_length=2, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=160)


class MedicalWritingLiteratureLibrary(WorkbenchModel):
    project_id: str
    citation_style: Literal["gbt_7714_2015_numeric", "gbt_7714_2025_numeric"] = (
        "gbt_7714_2015_numeric"
    )
    references: List[MedicalWritingProjectReference] = Field(default_factory=list)


class WritingReferenceSearchRequest(WorkbenchModel):
    indication: str
    phases: List[str] = Field(default_factory=list)
    study_type: str = "INTERVENTIONAL"
    regions: List[str] = Field(default_factory=list)
    intervention_terms: List[str] = Field(default_factory=list)
    page_size: int = Field(default=100, ge=1, le=100)
    page_token: Optional[str] = None


class WritingReferenceSearchCreateRequest(WorkbenchModel):
    search: WritingReferenceSearchRequest
    actor: str = "medical_manager"
    idempotency_key: str


class WritingReferencePublicDocument(WorkbenchModel):
    document_id: str
    nct_id: str
    document_type: str
    label: str = ""
    filename: str
    document_date: str = ""
    upload_date: str = ""
    declared_size: Optional[int] = Field(default=None, ge=0)
    download_url: str
    source_status: str = "discovered"
    rights_status: str = "pending_review"


class WritingReferenceTrialIntervention(WorkbenchModel):
    name: str = ""
    intervention_type: str = ""


class WritingReferenceTrialCandidate(WorkbenchModel):
    nct_id: str
    brief_title: str = ""
    official_title: str = ""
    brief_summary: str = ""
    conditions: List[str] = Field(default_factory=list)
    phases: List[str] = Field(default_factory=list)
    study_type: str = ""
    interventions: List[WritingReferenceTrialIntervention] = Field(
        default_factory=list
    )
    design_allocation: str = ""
    design_intervention_model: str = ""
    design_masking: str = ""
    enrollment_count: Optional[int] = Field(default=None, ge=0)
    lead_sponsor: str = ""
    overall_status: str = ""
    first_posted: str = ""
    last_update_posted: str = ""
    study_record_url: str
    relevance_status: str = "pending_medical_relevance"
    relevance_reason: str = ""
    public_documents: List[WritingReferencePublicDocument] = Field(default_factory=list)


class WritingReferenceSearchSnapshot(WorkbenchModel):
    snapshot_id: str
    project_id: str
    request: WritingReferenceSearchRequest
    query_url: str
    api_version: str = ""
    data_timestamp: str = ""
    total_count: int = Field(ge=0)
    returned_count: int = Field(ge=0)
    page_count: int = Field(ge=1)
    candidates: List[WritingReferenceTrialCandidate] = Field(default_factory=list)
    created_by: str = "medical_manager"
    created_at: datetime


class WritingReferenceRelevanceDecisionRequest(WorkbenchModel):
    nct_id: str
    relevance_status: str
    reason: str
    actor: str = "medical_manager"
    expected_revision: int = Field(default=0, ge=0)
    idempotency_key: str


class WritingReferenceRelevanceDecision(WorkbenchModel):
    decision_id: str
    project_id: str
    snapshot_id: str
    nct_id: str
    relevance_status: str
    reason: str
    revision: int = Field(ge=1)
    actor: str
    identity_assurance: str = "unverified_client_claim"
    created_at: datetime


# ---------------------------------------------------------------------------
# Medical-writing competitor triage contracts (product-owned DeepSeek Pro).
# ---------------------------------------------------------------------------

class CompetitorTriageClassification(str, Enum):
    DIRECT_COMPETITOR = "direct_competitor"
    INDIRECT_REFERENCE = "indirect_reference"
    EXCLUDED = "excluded"


class CompetitorTriageRunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    REVIEW_READY = "review_ready"
    PARTIAL_FAILED = "partial_failed"
    FAILED = "failed"
    STALE = "stale"
    CONFIRMED = "confirmed"
    PROJECTION_PENDING = "projection_pending"


class CompetitorTriageChunkStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class CompetitorTriageCandidateDocumentSuitability(WorkbenchModel):
    has_public_protocol: bool = False
    has_public_sap: bool = False
    document_role: str = ""


class CompetitorTriageMatchingDimension(WorkbenchModel):
    dimension: str
    match: Literal["match", "partial", "mismatch", "unknown"] = "unknown"
    detail: str = ""


class CompetitorTriageCandidateResult(WorkbenchModel):
    nct_id: str
    classification: CompetitorTriageClassification
    confidence: float = Field(ge=0.0, le=1.0)
    matching_dimensions: List[CompetitorTriageMatchingDimension] = Field(
        default_factory=list
    )
    document_suitability: CompetitorTriageCandidateDocumentSuitability = Field(
        default_factory=CompetitorTriageCandidateDocumentSuitability
    )
    reason: str = ""
    evidence_gaps: List[str] = Field(default_factory=list)


class CompetitorTriageProvenance(WorkbenchModel):
    provider: str
    response_model: str
    prompt_version: str
    schema_version: str
    canonical_input_hash: str
    canonical_output_hash: str
    snapshot_id: str
    snapshot_hash: str = ""
    journey_revision: int = 0
    material_facts_hash: str = ""
    route_profile_id: str = ""
    route_identity_hash: str = ""
    fallback_chain_id: str = ""
    fallback_depth: int = Field(default=0, ge=0)
    fallback_reason: str = ""
    created_at: datetime


class CompetitorTriageChunkRecord(WorkbenchModel):
    chunk_id: str
    chunk_index: int = Field(ge=0)
    nct_ids: List[str]
    input_hash: str
    status: CompetitorTriageChunkStatus = CompetitorTriageChunkStatus.PENDING
    attempt: int = Field(default=0, ge=0)
    error_message: str = ""
    provenance: Optional[CompetitorTriageProvenance] = None
    results: List[CompetitorTriageCandidateResult] = Field(default_factory=list)


class CompetitorTriageRun(WorkbenchModel):
    run_id: str
    project_id: str
    journey_id: str
    snapshot_id: str
    status: CompetitorTriageRunStatus = CompetitorTriageRunStatus.QUEUED
    prompt_version: str
    schema_version: str
    provider: str = ""
    response_model: str = ""
    canonical_input_hash: str = ""
    canonical_output_hash: str = ""
    snapshot_hash: str = ""
    journey_revision: int = 0
    material_facts_hash: str = ""
    chunks: List[CompetitorTriageChunkRecord] = Field(default_factory=list)
    recommended_retain: List[str] = Field(default_factory=list)
    recommended_exclude: List[str] = Field(default_factory=list)
    stale_reason: str = ""
    error_message: str = ""
    created_at: datetime
    updated_at: datetime


class CompetitorTriageCreateRequest(WorkbenchModel):
    # Empty allowed: service resolves to journey.search_plan.latest_snapshot_id
    # so lazy writers need not copy the snapshot id by hand.
    snapshot_id: str = Field(default="", max_length=160)
    expected_journey_revision: int = Field(ge=1)
    actor: str = Field(default="medical_manager", min_length=2, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=160)


class CompetitorTriageRetryRequest(WorkbenchModel):
    actor: str = Field(default="medical_manager", min_length=2, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=160)
    chunk_ids: List[str] = Field(default_factory=list)


class CompetitorTriageBasketConfirmationRequest(WorkbenchModel):
    expected_run_revision: str = Field(min_length=1)
    retained_nct_ids: List[str] = Field(default_factory=list)
    excluded_nct_ids: List[str] = Field(default_factory=list)
    final_classifications: Dict[str, CompetitorTriageClassification] = Field(
        min_length=1
    )
    no_suitable_competitor_reason: str = Field(default="", max_length=2000)
    actor: str = Field(default="medical_manager", min_length=2, max_length=80)
    reason: str = Field(default="", max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=160)
    expected_journey_revision: int = Field(ge=1)

class CompetitorTriageProjectionRetryRequest(WorkbenchModel):
    actor: str = Field(default="medical_manager", min_length=2, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=160)


class CompetitorTriageBasketReconfirmationRequest(WorkbenchModel):
    source_confirmation_id: str = Field(min_length=1, max_length=160)
    expected_journey_revision: int = Field(ge=1)
    retained_nct_ids: List[str] = Field(default_factory=list)
    excluded_nct_ids: List[str] = Field(default_factory=list)
    final_classifications: Dict[str, CompetitorTriageClassification] = Field(
        min_length=1
    )
    no_suitable_competitor_reason: str = Field(default="", max_length=2000)
    actor: str = Field(default="medical_manager", min_length=2, max_length=80)
    reason: str = Field(default="", max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=160)


class CompetitorTriageReconfirmationStatus(WorkbenchModel):
    required: bool = False
    reason: str = ""
    source_confirmation_id: str = ""
    snapshot_id: str = ""
    current_journey_revision: int = Field(default=0, ge=0)
    retained_nct_ids: List[str] = Field(default_factory=list)
    excluded_nct_ids: List[str] = Field(default_factory=list)
    final_classifications: Dict[str, CompetitorTriageClassification] = Field(
        default_factory=dict
    )
    current_triage_criteria: List[MedicalWritingCompetitorTriageCriterion] = Field(
        default_factory=list
    )


class CompetitorTriageConfirmationRecord(WorkbenchModel):
    confirmation_id: str
    run_id: str
    project_id: str
    snapshot_id: str
    retained_nct_ids: List[str]
    excluded_nct_ids: List[str]
    final_classifications: Dict[str, CompetitorTriageClassification] = Field(
        default_factory=dict
    )
    no_suitable_competitor_reason: str = ""
    actor: str
    reason: str = ""
    confirmation_hash: str
    journey_revision: int
    confirmation_kind: Literal[
        "initial_ai_assisted", "human_reconfirmation"
    ] = "initial_ai_assisted"
    source_confirmation_id: str = ""
    confirmed_material_facts_hash: str = ""
    confirmed_search_plan_id: str = ""
    projection_status: Literal[
        "pending",
        "discovery_projected",
        "deferred_until_picos",
        "corpus_projected",
        "failed",
    ] = "pending"
    projection_error: str = ""
    projection_attempts: int = Field(default=0, ge=0)
    created_at: datetime


class CompetitorTriageRunSummary(WorkbenchModel):
    run_id: str
    project_id: str
    status: CompetitorTriageRunStatus
    snapshot_id: str
    total_chunks: int = Field(ge=0)
    succeeded_chunks: int = Field(ge=0)
    failed_chunks: int = Field(ge=0)
    total_candidates: int = Field(ge=0)
    recommended_retain_count: int = Field(ge=0)
    recommended_exclude_count: int = Field(ge=0)
    provider: str = ""
    response_model: str = ""
    prompt_version: str = ""
    canonical_input_hash: str = ""
    canonical_output_hash: str = ""
    stale_reason: str = ""
    confirmation_id: str = ""
    created_at: datetime
    updated_at: datetime


class CompetitorTriageRunResponse(WorkbenchModel):
    run: CompetitorTriageRun
    summary: CompetitorTriageRunSummary
    reconfirmation: CompetitorTriageReconfirmationStatus = Field(
        default_factory=CompetitorTriageReconfirmationStatus
    )


class WritingReferenceDocumentIngestRequest(WorkbenchModel):
    snapshot_id: str
    nct_id: str
    document_id: str
    actor: str = "medical_manager"
    idempotency_key: str


class WritingReferenceManualDocumentUploadRequest(WorkbenchModel):
    snapshot_id: str
    nct_id: str
    document_type: Literal["protocol", "sap", "protocol_sap"]
    document_date: str = ""
    actor: str = "medical_manager"
    idempotency_key: str


class WritingReferenceExtractionRequest(WorkbenchModel):
    actor: str = "medical_manager"
    extraction_idempotency_key: str


class WritingReferenceOcrConsistencyRecheckRequest(WorkbenchModel):
    actor: str = Field(default="system_ocr_qc", min_length=2, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=200)


class WritingReferenceOcrConsistencyBatchDispositionRequest(WorkbenchModel):
    decision: Literal["confirmed", "returned"] = "confirmed"
    comment: str = Field(min_length=8, max_length=1000)
    actor: str = Field(default="medical_manager", min_length=2, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=200)


class WritingReferencePreparationBatchCreateRequest(WorkbenchModel):
    snapshot_id: str = Field(min_length=1, max_length=160)
    actor: str = Field(default="medical_manager", min_length=2, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=160)
    # Preparation is admitted in bounded, auditable stages.  The default is
    # aligned with the shared OCR admission ceiling; callers may request a
    # larger bounded stage for a deliberately scoped offline run.
    stage_size: int = Field(default=8, ge=1, le=32)


class WritingReferencePreparationBatchStageAdvanceRequest(WorkbenchModel):
    actor: str = Field(default="medical_manager", min_length=2, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=160)


class WritingReferencePreparationBatchRetryRequest(WorkbenchModel):
    actor: str = Field(default="medical_manager", min_length=2, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=160)


class WritingReferencePreparationProgress(WorkbenchModel):
    """Durable, user-visible progress for one preparation item.

    ``percent`` is a projection of real phase boundaries and page/file units;
    it is never model-token or network-byte progress.
    """

    phase: Literal[
        "queued",
        "downloading",
        "native_extracting",
        "ocr_rendering",
        "ocr_completing",
        "extraction_persisting",
        "content_validating",
        "completed",
        "failed",
    ] = "queued"
    current_substep: str = ""
    completed: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)
    percent: int = Field(default=0, ge=0, le=100)
    unit: str = ""
    context: Dict[str, Any] = Field(default_factory=dict)


class WritingReferencePreparationStageState(WorkbenchModel):
    status: Literal[
        "pending",
        "running",
        "succeeded",
        "review_required",
        "failed",
        "not_applicable",
    ] = "pending"
    attempt: int = Field(default=0, ge=0)
    error_code: str = ""
    error_detail: str = ""
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class WritingReferencePreparationBatchItem(WorkbenchModel):
    item_id: str
    batch_id: str
    project_id: str
    snapshot_id: str
    item_kind: Literal["public_document", "study_manual_upload_required"]
    nct_id: str
    document_id: str = ""
    document_type: str = ""
    filename: str = ""
    source_scope_sha256: str = Field(min_length=64, max_length=64)
    status: Literal[
        "pending",
        "running",
        "prepared",
        "review_required",
        "manual_upload_required",
        "deferred",
        "failed",
        "excluded",
    ] = "pending"
    attempt: int = Field(default=0, ge=0)
    error_code: str = ""
    error_detail: str = ""
    ingest: WritingReferencePreparationStageState = Field(
        default_factory=WritingReferencePreparationStageState
    )
    extraction: WritingReferencePreparationStageState = Field(
        default_factory=WritingReferencePreparationStageState
    )
    validation: WritingReferencePreparationStageState = Field(
        default_factory=WritingReferencePreparationStageState
    )
    artifact_id: str = ""
    extraction_revision: str = ""
    validation_id: str = ""
    validation_status: str = ""
    ocr_model_pin: str = ""
    ocr_model_pin_source: str = ""
    ocr_model_pinned_at: Optional[datetime] = None
    progress: WritingReferencePreparationProgress = Field(
        default_factory=WritingReferencePreparationProgress
    )
    created_at: datetime
    updated_at: datetime


class WritingReferencePreparationBatch(WorkbenchModel):
    batch_id: str
    project_id: str
    snapshot_id: str
    scope_sha256: str = Field(min_length=64, max_length=64)
    retained_candidate_ids: List[str] = Field(default_factory=list)
    retained_candidate_count: int = Field(default=0, ge=0)
    status: Literal[
        "accepted",
        "running",
        "completed",
        "completed_with_review_required",
        "completed_with_manual_upload_required",
        "awaiting_stage_admission",
        "partial_failure",
        "failed",
    ] = "accepted"
    attempt: int = Field(default=1, ge=1)
    item_count: int = Field(default=0, ge=0)
    document_item_count: int = Field(default=0, ge=0)
    pending_document_count: int = Field(default=0, ge=0)
    running_document_count: int = Field(default=0, ge=0)
    completed_document_count: int = Field(default=0, ge=0)
    prepared_count: int = Field(default=0, ge=0)
    review_required_count: int = Field(default=0, ge=0)
    manual_upload_required_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    excluded_count: int = Field(default=0, ge=0)
    admission_plan_id: str = ""
    admission_stage_index: int = Field(default=1, ge=1)
    admission_stage_size: int = Field(default=8, ge=1, le=32)
    deferred_item_count: int = Field(default=0, ge=0)
    current_item_id: str = ""
    current_nct_id: str = ""
    current_document_label: str = ""
    progress: WritingReferencePreparationProgress = Field(
        default_factory=WritingReferencePreparationProgress
    )
    items: List[WritingReferencePreparationBatchItem] = Field(default_factory=list)
    created_by: str
    created_at: datetime
    updated_at: datetime


class WritingReferenceDocumentArtifact(WorkbenchModel):
    artifact_id: str
    project_id: str
    snapshot_id: str
    nct_id: str
    source_document_id: str
    document_type: str
    filename: str
    document_date: str = ""
    upload_date: str = ""
    requested_url: str
    final_url: str
    content_type: str
    declared_size: Optional[int] = Field(default=None, ge=0)
    actual_size: int = Field(ge=0)
    content_sha256: str
    source_status: str = "downloaded"
    file_integrity_status: str = "verified"
    source_current: bool = True
    state_revision: int = Field(default=1, ge=1)
    invalidation_reason: str = ""
    created_by: str
    created_at: datetime


class WritingReferenceSourceFragment(WorkbenchModel):
    physical_page: int = Field(ge=1)
    block_index: int = Field(ge=0)
    source_locator: str
    bbox: tuple[float, float, float, float]
    source_text: str
    source_text_sha256: str
    layout_role: Literal[
        "body",
        "repeated_margin_header",
        "repeated_margin_footer",
        "repeated_visual_overlay",
    ] = "body"


class WritingReferenceSkippedInterstitial(WorkbenchModel):
    fragment: WritingReferenceSourceFragment
    reason_code: Literal["repeated_margin_header", "repeated_margin_footer"]


class WritingReferenceExtractedSpan(WorkbenchModel):
    span_id: str
    project_id: str
    artifact_id: str
    extraction_revision: str
    physical_page: int = Field(ge=1)
    block_index: int = Field(ge=0)
    source_locator: str
    section_heading: str = ""
    ich_m11_anchor: str = "unmapped"
    source_text: str
    source_text_sha256: str
    extraction_status: str = "pending_medical_structure_review"
    needs_visual_qc: bool = True
    source_fragments: List[WritingReferenceSourceFragment] = Field(default_factory=list)
    skipped_interstitials: List[WritingReferenceSkippedInterstitial] = Field(
        default_factory=list
    )
    semantic_merge_method: Literal[
        "none",
        "cross_page_continuation_v1",
        "adjacent_abbreviation_continuation_v1",
    ] = "none"
    semantic_merge_reason_codes: List[str] = Field(default_factory=list)


class WritingReferenceOcrPageEvidence(WorkbenchModel):
    """Page-level OCR evidence with safe defaults for legacy extraction rows."""

    physical_page: int = Field(ge=1)
    dpi: int = Field(ge=0)
    image_media_type: Literal["image/png"] = "image/png"
    image_sha256: str = ""
    image_size_bytes: int = Field(default=0, ge=0)
    image_width_px: int = Field(default=0, ge=0)
    image_height_px: int = Field(default=0, ge=0)
    storage_relpath: str = ""
    model: str
    provider: str = ""
    fell_back: bool = False
    primary_model: str = ""
    fallback_reason: str = ""
    ocr_profile_digest: str
    ocr_text_sha256: str = ""
    ocr_character_count: int = Field(default=0, ge=0)
    channel: Literal["ocr", "ocr_reconciled"]
    selection_reason: str
    ocr_result_status: Literal[
        "text_recovered",
        "empty_text",
        "legacy_metadata_only",
    ] = "legacy_metadata_only"
    span_id: str = ""
    # Legacy extraction payloads used this key before ocr_text_sha256 existed.
    source_text_sha256: str = ""
    # Existing reconciled-page payloads retain their native-text comparison.
    native_channel: List[Dict[str, str]] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_legacy_text_hash(self) -> "WritingReferenceOcrPageEvidence":
        if not self.ocr_text_sha256 and self.source_text_sha256:
            self.ocr_text_sha256 = self.source_text_sha256
        elif self.ocr_text_sha256 and not self.source_text_sha256:
            self.source_text_sha256 = self.ocr_text_sha256
        return self

    def get(self, key: str, default: Any = None) -> Any:
        """Preserve read-only dict-style access used by legacy consumers."""

        return getattr(self, key, default)


class WritingReferenceExtractionResult(WorkbenchModel):
    artifact_id: str
    project_id: str
    extraction_revision: str
    parser_name: str
    parser_version: str
    page_count: int = Field(ge=1)
    zero_text_pages: List[int] = Field(default_factory=list)
    status: str
    spans: List[WritingReferenceExtractedSpan] = Field(default_factory=list)
    excluded_layout_fragments: List[WritingReferenceSkippedInterstitial] = Field(
        default_factory=list
    )
    # Legacy rows without PNG metadata parse as legacy_metadata_only. New
    # extraction revisions persist immutable page-image and OCR-text evidence.
    ocr_recovery_pages: List[WritingReferenceOcrPageEvidence] = Field(
        default_factory=list
    )
    ocr_model: str = ""
    ocr_dpi: int = Field(default=0, ge=0)
    ocr_profile_digest: str = ""
    ocr_consistency_qc: Dict[str, Any] = Field(default_factory=dict)


class WritingReferenceOcrConsistencyQcRecheck(WorkbenchModel):
    """Immutable, independently persisted QC result for mixed OCR evidence."""

    recheck_id: str
    project_id: str
    artifact_id: str
    extraction_revision: str
    base_qc_identity_hash: str
    stage_version: str
    schema_version: str
    provider: str
    model: str
    prompt_version: str
    models: List[str] = Field(default_factory=list)
    physical_pages: List[int] = Field(default_factory=list)
    verdict: Literal["pass", "review_required", "fail"]
    notes: str = ""
    input_hash: str
    output_hash: str
    revision: int = Field(ge=1)
    created_at: datetime


class WritingReferenceOcrConsistencyMedicalDisposition(WorkbenchModel):
    """Immutable medical decision bound to one exact OCR recheck revision."""

    disposition_id: str
    project_id: str
    artifact_id: str
    extraction_revision: str
    recheck_id: str
    recheck_revision: int = Field(ge=1)
    decision: Literal["confirmed", "returned"]
    comment: str
    actor: str
    revision: int = Field(ge=1)
    created_at: datetime


class WritingReferenceOcrConsistencyEffectiveProjection(WorkbenchModel):
    """Read-only projection combining immutable OCR QC and current disposition."""

    project_id: str
    artifact_id: str
    extraction_revision: str
    base_verdict: Literal["pass", "review_required", "fail"]
    effective_status: Literal[
        "pass",
        "pending_medical_confirmation",
        "medical_confirmed_with_residual_issue",
        "blocked",
    ]
    recheck_id: str = ""
    recheck_revision: int = Field(default=0, ge=0)
    recheck_verdict: Literal["pass", "review_required", "fail", ""] = ""
    recheck_notes: str = ""
    disposition_id: str = ""
    disposition_revision: int = Field(default=0, ge=0)
    disposition_decision: Literal["confirmed", "returned", ""] = ""
    disposition_comment: str = ""


class WritingReferenceOcrConsistencyMedicalDispositionTarget(WorkbenchModel):
    artifact_id: str
    extraction_revision: str
    recheck_id: str
    recheck_revision: int = Field(ge=1)
    expected_revision: int = Field(default=0, ge=0)


class WritingReferenceOcrConsistencyMedicalDispositionOutcome(WorkbenchModel):
    artifact_id: str
    extraction_revision: str
    recheck_id: str
    recheck_revision: int = Field(ge=1)
    outcome: Literal["confirmed", "returned", "stale", "failed", "skipped"]
    disposition_id: str = ""
    reason: str = ""


class WritingReferenceOcrConsistencyBatchMedicalDispositionResult(WorkbenchModel):
    project_id: str
    outcomes: List[WritingReferenceOcrConsistencyMedicalDispositionOutcome]
    created_at: datetime


class WritingReferenceExtractionReviewDecision(WorkbenchModel):
    review_id: str
    project_id: str
    artifact_id: str
    extraction_revision: str
    decision: str
    confirmed_anchor_coverage: List[str] = Field(default_factory=list)
    unresolved_structure_issues: List[str] = Field(default_factory=list)
    comment: str
    actor: str
    revision: int = Field(ge=1)
    identity_assurance: str = "unverified_client_claim"
    created_at: datetime


class WritingReferenceExtractionReviewRequest(WorkbenchModel):
    extraction_revision: str
    decision: str
    confirmed_anchor_coverage: List[str] = Field(default_factory=list)
    unresolved_structure_issues: List[str] = Field(default_factory=list)
    comment: str
    actor: str = "medical_manager"
    expected_revision: int = Field(ge=0)
    idempotency_key: str


class WritingReferenceDocumentValidationCheck(WorkbenchModel):
    check_code: str
    label: str
    expected_value: str = ""
    observed_value: str = ""
    outcome: str
    evidence_locators: List[str] = Field(default_factory=list)


class WritingReferenceDocumentValidationRecord(WorkbenchModel):
    validation_id: str
    project_id: str
    artifact_id: str
    revision: int = Field(ge=1)
    status: str
    document_sha256: str = ""
    extraction_revision: str = ""
    source_state_revision: int = Field(default=1, ge=1)
    expected_context_hash: str = ""
    validator_version: str = "content_consistency_v1"
    checks: List[WritingReferenceDocumentValidationCheck] = Field(default_factory=list)
    summary: str
    actor: str
    override_reason: str = ""
    acknowledged_warning_codes: List[str] = Field(default_factory=list)
    identity_assurance: str = "unverified_client_claim"
    created_at: datetime


class WritingReferenceDocumentValidationOverrideRequest(WorkbenchModel):
    reason: str
    acknowledged_warning_codes: List[str] = Field(default_factory=list)
    actor: str = "medical_manager"
    expected_revision: int = Field(ge=1)
    idempotency_key: str


class WritingReferenceTranslationRevision(WorkbenchModel):
    translation_id: str
    project_id: str
    span_id: str
    source_span_revision: str
    document_sha256: str
    glossary_version: str
    revision: int = Field(ge=1)
    translated_text: str
    rationale: str
    fidelity_status: str
    fidelity_failure_codes: List[str] = Field(default_factory=list)
    ai_run_id: str
    task_type: str = ""
    prompt_version: str = ""
    schema_version: str = ""
    provider: str = ""
    model_name: str = ""
    contract_hash: str = ""
    status: str = "pending_author_confirmation"
    created_by: str = "system_ai"
    created_at: datetime
    # Document-plan/chunk additive lineage (Round 7).  The primary span_id
    # above is retained for backward foreign-key compatibility.  The fields
    # below carry the full source-span/chunk/OCR lineage of the integrated
    # chapter candidate so the new contract is auditable end-to-end.
    document_structure_plan_id: str = ""
    chapter_id: str = ""
    source_span_ids: List[str] = Field(default_factory=list)
    translation_chunk_ids: List[str] = Field(default_factory=list)
    chapter_integration_result_id: str = ""


class DocumentStructurePlanChapter(WorkbenchModel):
    """One chapter entry within a document structure plan."""

    chapter_id: str
    chapter_order: int = Field(ge=1)
    title: str = ""
    heading_path: List[str] = Field(default_factory=list)
    ich_m11_anchor: str = "unmapped"
    source_span_ids: List[str] = Field(default_factory=list)
    ambiguity_codes: List[str] = Field(default_factory=list)


class DocumentStructurePlan(WorkbenchModel):
    """Immutable upper-layer plan — one per artifact/extraction/planner contract.

    Created once after approved extraction.  Retried batches reuse the
    immutable accepted plan rather than re-planning per span.
    """

    plan_id: str
    project_id: str
    artifact_id: str
    extraction_revision: str
    document_sha256: str
    document_role: str
    planner_model: str
    planner_prompt_version: str
    planner_input_hash: str
    planner_output_hash: str
    planner_contract_fingerprint: str
    chapters: List[DocumentStructurePlanChapter] = Field(default_factory=list)
    ambiguity_codes: List[str] = Field(default_factory=list)
    status: str = "active"
    created_at: datetime
    planner_provider: str = ""
    planner_transport: str = ""
    planner_deployment_profile: str = ""
    planner_response_model: str = ""
    upper_layer_stage_run_id: str = ""
    parent_plan_id: str = ""
    # Additive v2 -> v3 deterministic contract-migration record.  It lives in
    # the immutable plan payload so schema version 8 remains readable without
    # adding or rewriting a table.  Empty defaults preserve legacy payloads.
    contract_migration_namespace: str = ""
    contract_transition_version: str = ""
    contract_source_plan_id: str = ""
    contract_source_fingerprint: str = ""
    contract_target_fingerprint: str = ""
    contract_source_prompt_version: str = ""
    contract_target_prompt_version: str = ""
    contract_source_payload_sha256: str = ""
    contract_target_payload_sha256: str = ""

    @model_validator(mode="after")
    def validate_contract_migration(self) -> "DocumentStructurePlan":
        values = (
            self.contract_migration_namespace,
            self.contract_transition_version,
            self.contract_source_plan_id,
            self.contract_source_fingerprint,
            self.contract_target_fingerprint,
            self.contract_source_prompt_version,
            self.contract_target_prompt_version,
            self.contract_source_payload_sha256,
            self.contract_target_payload_sha256,
        )
        if not any(values):
            return self
        if not all(value.strip() for value in values):
            raise ValueError(
                "document-plan contract migration fields must coexist"
            )
        if self.parent_plan_id != self.contract_source_plan_id:
            raise ValueError(
                "document-plan migration source must equal parent_plan_id"
            )
        if (
            self.planner_model != self.contract_migration_namespace
            or self.planner_prompt_version
            != self.contract_target_prompt_version
            or self.planner_contract_fingerprint
            != self.contract_target_fingerprint
        ):
            raise ValueError(
                "document-plan migration target identity is inconsistent"
            )
        for field_name, value in (
            ("contract_source_fingerprint", self.contract_source_fingerprint),
            ("contract_target_fingerprint", self.contract_target_fingerprint),
            (
                "contract_source_payload_sha256",
                self.contract_source_payload_sha256,
            ),
            (
                "contract_target_payload_sha256",
                self.contract_target_payload_sha256,
            ),
        ):
            if len(value) != 64 or any(
                char not in "0123456789abcdef" for char in value
            ):
                raise ValueError(
                    f"document-plan migration {field_name} must be SHA-256"
                )
        return self


class TranslationChunkRecord(WorkbenchModel):
    """Immutable Hy-MT2 translation chunk — one per chunk within a chapter."""

    chunk_id: str
    plan_id: str
    project_id: str
    artifact_id: str
    chapter_id: str
    chunk_order: int = Field(ge=1)
    source_span_ids: List[str] = Field(default_factory=list)
    source_text: str
    source_text_sha256: str
    adjacent_context_sha256: str = ""
    table_header_prefix: str = ""
    chunk_fingerprint: str
    hy_mt2_model: str
    hy_mt2_prompt_version: str
    hy_mt2_input_hash: str
    translated_text: str
    translated_text_sha256: str
    # Auditable one-to-one aligned unit targets (unit ordinal -> Chinese
    # target) captured at translation time.  Additive; empty for rows
    # written before the V11 aligned-unit contract.
    unit_targets: Dict[str, str] = Field(default_factory=dict)
    translation_strategy: str = "hy_mt2_aligned_units"
    status: str = "completed"
    created_at: datetime


class ChapterIntegrationWindow(WorkbenchModel):
    """One ordered integration window within an oversized chapter."""

    window_index: int = Field(ge=1)
    chunk_ids: List[str] = Field(default_factory=list)
    chunk_hashes: List[str] = Field(default_factory=list)
    input_hash: str = ""
    output_hash: str = ""
    integrated_text_sha256: str = ""


class ChapterIntegrationResult(WorkbenchModel):
    """Immutable upper-layer integration QC result for one chapter.

    One per ordinary chapter over ordered chunk outputs.  If a chapter
    exceeds the provider context contract, ordered integration windows
    plus a final chapter envelope check are used and the lineage is
    exposed honestly here.
    """

    integration_id: str
    plan_id: str
    project_id: str
    artifact_id: str
    chapter_id: str
    chunk_ids: List[str] = Field(default_factory=list)
    chunk_hashes: List[str] = Field(default_factory=list)
    integrated_chinese_text: str
    integrated_text_sha256: str
    flash_model: str
    flash_prompt_version: str
    flash_input_hash: str
    flash_output_hash: str
    fidelity_status: str
    fidelity_failure_codes: List[str] = Field(default_factory=list)
    # Non-authoring model QC findings require medical review but cannot
    # hard-block a deterministic-valid Hy-MT2 body on their own.
    fidelity_advisory_codes: List[str] = Field(default_factory=list)
    blocked_raw_provider_output: str = ""
    blocked_raw_provider_output_sha256: str = ""
    integration_windowed: bool = False
    # Additive ordered window lineage.  Empty when integration_windowed=False.
    integration_windows: List[ChapterIntegrationWindow] = Field(default_factory=list)
    final_envelope_input_hash: str = ""
    final_envelope_output_hash: str = ""
    # Downstream translation-contract fingerprint under which this
    # integration was produced.  Reuse is allowed only when the persisted
    # fingerprint matches the current contract; empty for pre-V11 rows,
    # which are therefore never silently reused.  Old rows stay immutable.
    translation_contract_fingerprint: str = ""
    integration_contract_fingerprint: str = ""
    upper_layer_stage_run_id: str = ""
    parent_integration_id: str = ""
    status: str = "completed"
    created_at: datetime


class CompositePipelineRunStage(WorkbenchModel):
    """One stage record inside an auditable composite pipeline run ledger."""

    stage: str
    model: str = ""
    prompt_version: str = ""
    input_hash: str = ""
    output_hash: str = ""


class CompositePipelineRun(WorkbenchModel):
    """Immutable composite pipeline run ledger — queryable provenance by run_id.

    Not a fabricated provider run.  Records stage model/prompt and input/output
    hashes for the plan/chunk/integration path that produced a chapter revision.
    """

    run_id: str
    project_id: str
    plan_id: str
    chapter_id: str = ""
    artifact_id: str = ""
    stages: List[CompositePipelineRunStage] = Field(default_factory=list)
    status: str = "completed"
    created_at: datetime


class WritingReferenceTranslationRequest(WorkbenchModel):
    span_id: str
    glossary_version: str
    user_instruction: str = (
        "请在保持数字、单位、时间点、缩写、否定、终点层级、动作主体及前后时序依赖忠实的前提下，"
        "翻译为自然、克制的中国临床试验方案监管中文候选。"
    )
    actor: str = "medical_manager"
    idempotency_key: str


class WritingReferenceTranslationRevisionRequest(WorkbenchModel):
    expected_translation_revision: int = Field(ge=1)
    medical_review_id: str
    user_instruction: str = "请严格按医学审核意见修订译文，保持原文数字、单位、时间点、缩写、否定和终点层级忠实。"
    actor: str = "medical_manager"
    idempotency_key: str


UpperLayerStage = Literal[
    "document_planning",
    "post_hy_mt2_integration_qc",
    "corpus_selection_support",
]


class WritingReferenceUpperLayerProviderCallAttempt(WorkbenchModel):
    """Bounded metadata for one provider call inside an immutable stage run."""

    call_index: int = Field(ge=1)
    requested_model: str
    response_model: str = ""
    planner_attempt: int = Field(default=0, ge=0)
    retry_kind: Literal[
        "initial",
        "transport_retry",
        "structural_correction",
        "escalation_initial",
    ]
    status: Literal[
        "succeeded",
        "completed_degraded",
        "failed_retryable",
        "failed_escalatable",
        "failed_terminal",
        "interrupted",
    ]
    failure_code: str = ""
    input_hash: str
    prompt_version: str
    correction_instruction_sha256: str = ""

    @model_validator(mode="after")
    def validate_attempt_lineage(
        self,
    ) -> "WritingReferenceUpperLayerProviderCallAttempt":
        if not self.requested_model.strip():
            raise ValueError("upper-layer provider attempt requires requested_model")
        if len(self.input_hash) != 64:
            raise ValueError("upper-layer provider attempt requires input SHA-256")
        if self.retry_kind == "structural_correction":
            if self.planner_attempt != 2:
                raise ValueError(
                    "structural correction must be planner attempt 2"
                )
            if len(self.correction_instruction_sha256) != 64:
                raise ValueError(
                    "structural correction requires instruction SHA-256"
                )
        return self


class WritingReferenceUpperLayerStageRun(WorkbenchModel):
    """Immutable terminal record for one server-selected upper-layer stage."""

    stage_run_id: str
    project_id: str
    owner_type: Literal[
        "translation_batch_item",
        "direct_translation",
        "corpus_selection",
    ]
    owner_id: str
    batch_id: str = ""
    item_id: str = ""
    artifact_id: str
    extraction_revision: str
    plan_id: str = ""
    chapter_id: str = ""
    stage: UpperLayerStage
    provider: str
    transport: str
    requested_model: str
    response_model: str = ""
    expected_response_model: str = ""
    deployment_profile: str
    prompt_version: str
    input_hash: str
    output_hash: str = ""
    status: Literal[
        "succeeded",
        "completed_degraded",
        "failed_retryable",
        "failed_escalatable",
        "failed_terminal",
        "interrupted",
    ]
    failure_code: str = ""
    provider_call_count: int = Field(ge=0)
    planner_attempt_count: int = Field(default=0, ge=0)
    provider_call_attempts: List[
        WritingReferenceUpperLayerProviderCallAttempt
    ] = Field(default_factory=list)
    retry_generation: int = Field(default=0, ge=0)
    retry_parent_stage_run_id: str = ""
    parent_stage_run_id: str = ""
    escalation_id: str = ""
    # Separate from ordinary retry and Flash-to-Pro escalation lineage.
    # These fields describe the exact failed v2 Flash source superseded by
    # this fresh v3 Flash root. Empty defaults preserve legacy payloads.
    contract_supersession_generation: int = Field(default=0, ge=0)
    contract_supersession_transition_version: str = ""
    contract_supersession_source_stage_run_id: str = ""
    contract_supersession_source_execution_fingerprint: str = ""
    contract_supersession_source_prompt_version: str = ""
    contract_supersession_target_prompt_version: str = ""
    created_at: datetime
    completed_at: datetime

    @model_validator(mode="after")
    def validate_route_lineage(self) -> "WritingReferenceUpperLayerStageRun":
        if not self.provider.strip() or not self.transport.strip():
            raise ValueError("upper-layer route identity is required")
        if not self.requested_model.strip():
            raise ValueError("upper-layer requested_model is required")
        if self.status in {"succeeded", "completed_degraded"}:
            if self.response_model != (
                self.expected_response_model or self.requested_model
            ):
                raise ValueError(
                    "successful upper-layer run requires configured response_model"
                )
        if bool(self.parent_stage_run_id) != bool(self.escalation_id):
            raise ValueError(
                "upper-layer escalation parent and escalation_id must coexist"
            )
        if bool(self.retry_generation) != bool(
            self.retry_parent_stage_run_id
        ):
            raise ValueError(
                "upper-layer retry generation and retry parent must coexist"
            )
        if (
            self.retry_parent_stage_run_id
            and self.stage != "document_planning"
        ):
            raise ValueError(
                "upper-layer retry lineage is document-planning only"
            )
        if self.retry_parent_stage_run_id == self.stage_run_id:
            raise ValueError("upper-layer retry run cannot parent itself")
        supersession_values = (
            self.contract_supersession_transition_version,
            self.contract_supersession_source_stage_run_id,
            self.contract_supersession_source_execution_fingerprint,
            self.contract_supersession_source_prompt_version,
            self.contract_supersession_target_prompt_version,
        )
        if bool(self.contract_supersession_generation) != bool(
            any(supersession_values)
        ) or (
            self.contract_supersession_generation
            and not all(value.strip() for value in supersession_values)
        ):
            raise ValueError(
                "upper-layer contract supersession fields must coexist"
            )
        if self.contract_supersession_generation:
            if self.stage != "document_planning":
                raise ValueError(
                    "upper-layer contract supersession is document-planning only"
                )
            if self.retry_generation or self.retry_parent_stage_run_id:
                raise ValueError(
                    "ordinary retry and contract supersession are mutually exclusive"
                )
            if self.parent_stage_run_id or self.escalation_id:
                raise ValueError(
                    "contract-superseded Flash run must be a fresh root"
                )
            if (
                self.requested_model != "deepseek-v4-flash"
                or self.prompt_version
                != self.contract_supersession_target_prompt_version
            ):
                raise ValueError(
                    "upper-layer contract supersession target identity is inconsistent"
                )
            fingerprint = (
                self.contract_supersession_source_execution_fingerprint
            )
            if len(fingerprint) != 64 or any(
                char not in "0123456789abcdef" for char in fingerprint
            ):
                raise ValueError(
                    "upper-layer supersession source fingerprint must be SHA-256"
                )
        if (
            self.requested_model == "deepseek-v4-pro"
            and not self.parent_stage_run_id
        ):
            raise ValueError(
                "Pro upper-layer run requires parent and escalation lineage"
            )
        if self.provider_call_attempts:
            if self.provider_call_count != len(self.provider_call_attempts):
                raise ValueError(
                    "upper-layer provider call count must match attempt lineage"
                )
            if [
                attempt.call_index for attempt in self.provider_call_attempts
            ] != list(range(1, self.provider_call_count + 1)):
                raise ValueError(
                    "upper-layer provider attempt indexes must be contiguous"
                )
            if any(
                attempt.requested_model != self.requested_model
                or attempt.input_hash != self.input_hash
                or attempt.prompt_version != self.prompt_version
                for attempt in self.provider_call_attempts
            ):
                raise ValueError(
                    "upper-layer provider attempts must preserve stage lineage"
                )
            observed_planner_attempts = [
                attempt.planner_attempt
                for attempt in self.provider_call_attempts
                if attempt.planner_attempt
            ]
            observed_planner_attempt_count = (
                max(observed_planner_attempts)
                if observed_planner_attempts
                else 0
            )
            if self.planner_attempt_count != observed_planner_attempt_count:
                raise ValueError(
                    "upper-layer planner attempt count must match call lineage"
                )
        return self


class WritingReferenceUpperLayerEscalationLineage(WorkbenchModel):
    """Server-created Flash-to-Pro lineage; clients never choose the route."""

    escalation_id: str
    project_id: str
    stage: UpperLayerStage
    source_stage_run_id: str
    target_stage_run_id: str = ""
    source_model: str = "deepseek-v4-flash"
    target_model: str = "deepseek-v4-pro"
    trigger_status: Literal["failed_escalatable", "completed_degraded"]
    trigger_code: str
    lineage_hash: str
    status: Literal[
        "queued",
        "running",
        "completed",
        "failed_retryable",
        "failed_terminal",
    ]
    durable_job_id: str = ""
    created_by: Literal["server_orchestrator"] = "server_orchestrator"
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_model_lineage(
        self,
    ) -> "WritingReferenceUpperLayerEscalationLineage":
        if not self.source_model.strip() or not self.target_model.strip():
            raise ValueError("upper-layer escalation model lineage is required")
        return self


WritingReferenceUpperLayerEscalation = WritingReferenceUpperLayerEscalationLineage


class WritingReferenceUpperLayerStageCapability(WorkbenchModel):
    """Server-owned capability declaration for one non-body stage."""

    stage: UpperLayerStage
    status: Literal["implemented", "not_implemented"]
    default_model: Optional[str] = None
    escalation_model: Optional[str] = None
    automatic_escalation_supported: bool = False
    reason: str = ""

    @model_validator(mode="after")
    def validate_implementation_state(
        self,
    ) -> "WritingReferenceUpperLayerStageCapability":
        if self.status == "not_implemented":
            if (
                self.default_model is not None
                or self.escalation_model is not None
                or self.automatic_escalation_supported
            ):
                raise ValueError(
                    "not_implemented upper-layer stage cannot advertise a route"
                )
        elif self.default_model is None:
            raise ValueError("implemented upper-layer stage requires default_model")
        return self


class WritingReferenceUpperLayerCapabilities(WorkbenchModel):
    runtime_scope: Literal[
        "medical_writing_reference_upper_layer"
    ] = "medical_writing_reference_upper_layer"
    upper_layer_stages: Dict[
        UpperLayerStage,
        WritingReferenceUpperLayerStageCapability,
    ] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_stage_keys(self) -> "WritingReferenceUpperLayerCapabilities":
        for stage, capability in self.upper_layer_stages.items():
            if stage != capability.stage:
                raise ValueError("upper-layer capability key must match stage")
        return self


class WritingReferenceUpperLayerRetryRequest(WorkbenchModel):
    """User recovery intent; route identity is derived by the server."""

    actor: str = Field(default="medical_manager", min_length=2, max_length=80)
    reason: str = Field(default="", max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=160)


class WritingReferenceTranslationBatchPreviewRequest(WorkbenchModel):
    snapshot_id: str = Field(min_length=1, max_length=160)
    glossary_version: str = Field(
        default="cms_regulatory_zh_v1",
        min_length=1,
        max_length=160,
    )
    anchor_filter: List[str] = Field(default_factory=list, max_length=100)
    # Optional research-pipeline / smoke cap: keep at most N eligible spans per
    # ICH M11 anchor (longest-first). None/0 means no cap.
    max_spans_per_anchor: Optional[int] = Field(default=None, ge=1, le=50)

    @model_validator(mode="after")
    def normalize_translation_batch_preview(self):
        self.snapshot_id = self.snapshot_id.strip()
        self.glossary_version = self.glossary_version.strip()
        self.anchor_filter = sorted(
            dict.fromkeys(item.strip() for item in self.anchor_filter if item.strip())
        )
        if not self.snapshot_id or not self.glossary_version:
            raise ValueError("translation batch snapshot and glossary must not be blank")
        if not re.fullmatch(r"cms_regulatory_zh_v[1-9][0-9]*", self.glossary_version):
            raise ValueError("translation batch glossary version is not an approved contract identifier")
        supported_anchors = {
            "eligibility",
            "objectives_endpoints",
            "safety",
            "schedule",
            "statistics",
            "synopsis",
        }
        unsupported_anchors = sorted(set(self.anchor_filter) - supported_anchors)
        if unsupported_anchors:
            raise ValueError(
                "translation batch contains unsupported M11 anchors: "
                + ", ".join(unsupported_anchors)
            )
        return self


class WritingReferenceTranslationBatchCreateRequest(
    WritingReferenceTranslationBatchPreviewRequest
):
    actor: str = Field(default="medical_manager", min_length=2, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=160)

    @model_validator(mode="after")
    def normalize_translation_batch_create(self):
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if not self.actor or not self.idempotency_key:
            raise ValueError("translation batch actor and idempotency key must not be blank")
        if not re.fullmatch(r"[\w.@:-]{2,80}", self.actor):
            raise ValueError("translation batch actor must be an identifier")
        return self


class WritingReferenceTranslationBatchRetryRequest(WorkbenchModel):
    actor: str = Field(default="medical_manager", min_length=2, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=160)

    @model_validator(mode="after")
    def normalize_translation_batch_retry(self):
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if not self.actor or not self.idempotency_key:
            raise ValueError("translation batch retry fields must not be blank")
        return self


class WritingReferenceTranslationDownstreamTransitionRequest(WorkbenchModel):
    """Exact source identity for one downstream translation-contract transition.

    This is deliberately separate from ordinary batch retry.  The client pins
    the immutable source result it inspected; the server owns the current
    target contract and refuses stale, ambiguous, or already-current input.
    """

    actor: str = Field(default="medical_manager", min_length=2, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=160)
    expected_source_batch_status: Literal["completed_with_blocked"] = (
        "completed_with_blocked"
    )
    expected_source_batch_attempt: int = Field(ge=1)
    expected_source_item_status: Literal["fidelity_blocked"] = "fidelity_blocked"
    expected_source_item_attempt: int = Field(ge=1)
    expected_source_translation_id: str = Field(min_length=1, max_length=160)
    expected_source_translation_revision: int = Field(ge=1)
    expected_source_ai_run_id: str = Field(min_length=1, max_length=160)
    expected_source_plan_id: str = Field(min_length=1, max_length=160)
    expected_source_integration_id: str = Field(min_length=1, max_length=160)
    expected_source_composite_contract_hash: str = Field(
        min_length=64, max_length=64
    )
    expected_source_downstream_fingerprint: str = Field(
        min_length=64, max_length=64
    )
    expected_source_hy_mt2_prompt_version: str = Field(
        min_length=1, max_length=200
    )
    expected_source_failure_code: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def normalize_downstream_transition_request(self):
        for field_name in (
            "actor",
            "idempotency_key",
            "expected_source_translation_id",
            "expected_source_ai_run_id",
            "expected_source_plan_id",
            "expected_source_integration_id",
            "expected_source_composite_contract_hash",
            "expected_source_downstream_fingerprint",
            "expected_source_hy_mt2_prompt_version",
            "expected_source_failure_code",
        ):
            value = str(getattr(self, field_name) or "").strip()
            if not value:
                raise ValueError(
                    "downstream transition identity fields must not be blank"
                )
            setattr(self, field_name, value)
        for field_name in (
            "expected_source_composite_contract_hash",
            "expected_source_downstream_fingerprint",
        ):
            value = getattr(self, field_name)
            if any(char not in "0123456789abcdef" for char in value):
                raise ValueError(
                    "downstream transition contract hashes must be lowercase SHA-256"
                )
        if not re.fullmatch(r"[\w.@:-]{2,80}", self.actor):
            raise ValueError("downstream transition actor must be an identifier")
        return self


class WritingReferenceTranslationDownstreamTransitionRecord(WorkbenchModel):
    """Immutable semantic intent for one source item -> target contract edge."""

    transition_id: str
    project_id: str
    source_batch_id: str
    source_item_id: str
    source_batch_attempt: int = Field(ge=1)
    source_item_attempt: int = Field(ge=1)
    source_translation_id: str
    source_translation_revision: int = Field(ge=1)
    source_ai_run_id: str
    source_plan_id: str
    source_integration_id: str
    source_composite_contract_hash: str = Field(min_length=64, max_length=64)
    source_downstream_fingerprint: str = Field(min_length=64, max_length=64)
    source_hy_mt2_prompt_version: str
    source_failure_code: str
    source_blocked_output_sha256: str = Field(min_length=64, max_length=64)
    target_batch_id: str
    target_item_id: str
    target_plan_id: str
    target_composite_contract_hash: str = Field(min_length=64, max_length=64)
    target_downstream_fingerprint: str = Field(min_length=64, max_length=64)
    target_hy_mt2_prompt_version: str
    target_alignment_contract: str
    transition_version: str
    created_by: str
    created_at: datetime


class WritingReferenceTranslationDownstreamTransitionState(WorkbenchModel):
    """Mutable projection; immutable intent and produced artifacts stay separate."""

    transition_id: str
    project_id: str
    status: Literal[
        "pending",
        "running",
        "candidate_ready",
        "fidelity_blocked",
        "failed_retryable",
        "failed_terminal",
    ] = "pending"
    error_code: str = ""
    updated_at: datetime


class WritingReferenceTranslationDownstreamTransitionResult(WorkbenchModel):
    transition: WritingReferenceTranslationDownstreamTransitionRecord
    state: WritingReferenceTranslationDownstreamTransitionState
    target_batch: "WritingReferenceTranslationBatch"
    durable_job_id: str = ""


class WritingReferenceTranslationBatchReviewTarget(WorkbenchModel):
    """One pinned translation revision a medical writer saw and confirmed."""

    translation_id: str = Field(min_length=1, max_length=160)
    translation_revision: int = Field(ge=1)


class WritingReferenceTranslationBatchMedicalReviewRequest(WorkbenchModel):
    """One-click batch author confirmation for eligible translation candidates.

    Approve-only: the writer explicitly confirms routine AI candidates whose
    machine fidelity gate passed. Targets pin the exact translation revisions
    the writer saw; the server re-validates eligibility per item and reports
    per-item outcomes, so a stale or ineligible row never conceals the rest.
    At least one exact translation revision is required; the API never expands
    an empty request to rows the writer may not have reviewed.
    """

    targets: List[WritingReferenceTranslationBatchReviewTarget] = Field(
        min_length=1, max_length=2000
    )
    comment: str = Field(
        default="批量作者确认：机器忠实度检查通过，医学作者一键确认",
        min_length=1,
        max_length=500,
    )
    actor: str = Field(default="medical_manager", min_length=2, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=160)

    @model_validator(mode="after")
    def normalize_translation_batch_medical_review(self):
        self.comment = self.comment.strip()
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if not self.comment or not self.actor or not self.idempotency_key:
            raise ValueError(
                "translation batch medical review comment, actor and idempotency key must not be blank"
            )
        if not re.fullmatch(r"[\w.@:-]{2,80}", self.actor):
            raise ValueError("translation batch medical review actor must be an identifier")
        deduped: List[WritingReferenceTranslationBatchReviewTarget] = []
        seen: set[tuple[str, int]] = set()
        for target in self.targets:
            key = (target.translation_id, target.translation_revision)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(target)
        self.targets = deduped
        return self


class WritingReferenceTranslationBatchReviewItemOutcome(WorkbenchModel):
    translation_id: str
    translation_revision: int = Field(default=0, ge=0)
    outcome: Literal["approved", "skipped", "stale", "failed"]
    reason: str = ""
    review_id: str = ""


class WritingReferenceTranslationBatchMedicalReviewResult(WorkbenchModel):
    batch_id: str
    project_id: str
    decision: Literal["approved"] = "approved"
    approved_count: int = Field(default=0, ge=0)
    skipped_count: int = Field(default=0, ge=0)
    stale_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    items: List[WritingReferenceTranslationBatchReviewItemOutcome] = Field(
        default_factory=list
    )
    actor: str
    created_at: datetime


class WritingReferenceTranslationBatchAnchorSummary(WorkbenchModel):
    ich_m11_anchor: str
    eligible_new: int = Field(default=0, ge=0)
    existing_candidate: int = Field(default=0, ge=0)
    fidelity_blocked: int = Field(default=0, ge=0)


class WritingReferenceTranslationBatchExclusion(WorkbenchModel):
    scope: Literal["document", "span"]
    reason_code: str
    count: int = Field(default=1, ge=1)
    nct_id: str = ""
    artifact_id: str = ""
    span_id: str = ""
    ich_m11_anchor: str = ""


class WritingReferenceTranslationBatchItem(WorkbenchModel):
    item_id: str
    batch_id: str
    project_id: str
    snapshot_id: str
    glossary_version: str
    span_id: str
    artifact_id: str
    nct_id: str
    filename: str = ""
    document_type: str = ""
    ich_m11_anchor: str
    source_locator: str = ""
    source_text_sha256: str
    source_span_revision: str
    artifact_sha256: str
    artifact_state_revision: int = Field(ge=1)
    validation_id: str
    validation_revision: int = Field(ge=1)
    validation_status: Literal["confirmed", "user_overridden"]
    extraction_revision: str
    structure_review_id: str
    structure_review_revision: int = Field(ge=1)
    ocr_qc_effective_status: Literal[
        "",
        "pass",
        "medical_confirmed_with_residual_issue",
    ] = ""
    ocr_qc_recheck_id: str = ""
    ocr_qc_recheck_revision: int = Field(default=0, ge=0)
    ocr_qc_disposition_id: str = ""
    ocr_qc_disposition_revision: int = Field(default=0, ge=0)
    contract_hash: str = ""
    prompt_version: str = ""
    schema_version: str = ""
    origin: Literal["new", "existing"]
    generation_status: Literal[
        "pending",
        "running",
        "candidate_ready",
        "fidelity_blocked",
        "excluded",
        "failed_retryable",
        "failed_terminal",
    ] = "pending"
    attempt: int = Field(default=0, ge=0)
    translation_id: str = ""
    translation_revision: int = Field(default=0, ge=0)
    ai_run_id: str = ""
    fidelity_status: str = ""
    fidelity_failure_codes: List[str] = Field(default_factory=list)
    error_code: str = ""
    error_detail: str = ""
    medical_review_status: Literal[
        "not_reviewed", "returned", "rejected", "approved"
    ] = "not_reviewed"
    author_confirmation_status: Literal[
        "not_confirmed", "returned", "rejected", "confirmed"
    ] = "not_confirmed"
    admission_status: Literal[
        "not_admitted", "admitted", "invalidated"
    ] = "not_admitted"

    # Chapter-translation-pipeline stage and lineage (additive, backward-compatible).
    # Exposed so APIs surface human-meaningful progress without reading logs,
    # and persisted to prove OCR/model/prompt/glossary/chunk/section provenance.
    pipeline_stage: Literal[
        "",
        "unknown",
        "extracting",
        "ocr_running",
        "toc_planning",
        "translating_hy_mt2",
        "integration_qc",
        "candidate_ready",
        "fidelity_blocked",
        "excluded",
        "failed_retryable",
        "failed_terminal",
    ] = ""
    pipeline_stage_detail: str = ""
    ocr_lineage_json: str = ""
    flash_plan_model: str = ""
    flash_plan_prompt_version: str = ""
    hy_mt2_model: str = ""
    hy_mt2_prompt_version: str = ""
    flash_qc_model: str = ""
    flash_qc_prompt_version: str = ""
    # Allow deterministic structure fallbacks (e.g. anchor_grouped_structure_fallback)
    # in addition to Flash/Pro planner model ids — research pipelines must not
    # crash ValidationError when Flash planning is skipped for oversized CT.gov PDFs.
    plan_model: str = ""
    qc_model: str = ""
    active_upper_layer_stage: Literal[
        "",
        "document_planning",
        "post_hy_mt2_integration_qc",
        "corpus_selection_support",
    ] = ""
    active_upper_layer_stage_run_id: str = ""
    latest_upper_layer_stage_run_id: str = ""
    upper_layer_escalation_id: str = ""
    document_plan_failure_source_stage_run_id: str = ""
    document_plan_failure_codes: List[str] = Field(default_factory=list)
    document_plan_failure_is_derived: bool = False
    document_plan_retry_generation: int = Field(default=0, ge=0)
    document_plan_retry_parent_stage_run_id: str = ""
    document_plan_retry_source_item_id: str = ""
    # Additive contract-transition intent captured atomically by batch retry.
    # It is never interpreted as an ordinary retry edge.
    document_plan_contract_transition_kind: Literal[
        "", "migration", "supersession"
    ] = ""
    document_plan_contract_transition_version: str = ""
    document_plan_contract_generation: int = Field(default=0, ge=0)
    document_plan_contract_source_item_id: str = ""
    document_plan_contract_source_plan_id: str = ""
    document_plan_contract_target_plan_id: str = ""
    document_plan_contract_source_stage_run_id: str = ""
    document_plan_contract_source_execution_fingerprint: str = ""
    document_plan_contract_source_prompt_version: str = ""
    document_plan_contract_target_prompt_version: str = ""
    document_plan_contract_source_fingerprint: str = ""
    document_plan_contract_target_fingerprint: str = ""
    # Independent downstream translation-contract transition lineage.
    # The source batch/item is never rewritten; these fields exist only on
    # the new single-item child batch created for the target contract.
    downstream_contract_transition_id: str = ""
    downstream_contract_transition_version: str = ""
    downstream_contract_source_batch_id: str = ""
    downstream_contract_source_item_id: str = ""
    downstream_contract_source_item_attempt: int = Field(default=0, ge=0)
    downstream_contract_source_translation_id: str = ""
    downstream_contract_source_translation_revision: int = Field(default=0, ge=0)
    downstream_contract_source_plan_id: str = ""
    downstream_contract_source_integration_id: str = ""
    downstream_contract_source_fingerprint: str = ""
    downstream_contract_target_plan_id: str = ""
    downstream_contract_target_fingerprint: str = ""
    upper_layer_escalation_status: Literal[
        "",
        "queued",
        "running",
        "completed",
        "failed_retryable",
        "failed_terminal",
    ] = ""
    pipeline_fingerprint: str = ""
    # Document-plan/chunk progress fields (Round 7/8, additive).  Expose
    # real document/chapter/chunk counts and titles so the UI can show
    # product state without reading logs.  Developer IDs/hashes stay in
    # the lineage fields above and in audit evidence — not in the UI.
    document_structure_plan_id: str = ""
    document_total: int = Field(default=0, ge=0)
    document_index: int = Field(default=0, ge=0)
    document_label: str = ""
    chapter_id: str = ""
    chapter_title: str = ""
    chapter_total: int = Field(default=0, ge=0)
    chapter_index: int = Field(default=0, ge=0)
    chunk_count: int = Field(default=0, ge=0)
    chunk_completed: int = Field(default=0, ge=0)
    chunk_running: int = Field(default=0, ge=0)
    chunk_failed: int = Field(default=0, ge=0)
    chunk_reused: int = Field(default=0, ge=0)
    source_span_count: int = Field(default=0, ge=0)
    # retryable | terminal | "" — medical-user-facing blocker state.
    blocker_kind: str = ""
    blocker_message: str = ""

    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_upper_layer_model_roles(
        self,
    ) -> "WritingReferenceTranslationBatchItem":
        if (
            self.plan_model.strip()
            == "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX"
        ):
            raise ValueError(
                "body translation model cannot be used for upper-layer planning"
            )
        downstream_values = (
            self.downstream_contract_transition_version,
            self.downstream_contract_source_batch_id,
            self.downstream_contract_source_item_id,
            self.downstream_contract_source_translation_id,
            self.downstream_contract_source_plan_id,
            self.downstream_contract_source_integration_id,
            self.downstream_contract_source_fingerprint,
            self.downstream_contract_target_plan_id,
            self.downstream_contract_target_fingerprint,
        )
        if not self.downstream_contract_transition_id:
            if (
                any(downstream_values)
                or self.downstream_contract_source_item_attempt
                or self.downstream_contract_source_translation_revision
            ):
                raise ValueError(
                    "downstream contract transition id is required"
                )
        else:
            if (
                not all(value.strip() for value in downstream_values)
                or self.downstream_contract_source_item_attempt < 1
                or self.downstream_contract_source_translation_revision < 1
            ):
                raise ValueError(
                    "downstream contract transition lineage fields must coexist"
                )
            for fingerprint in (
                self.downstream_contract_source_fingerprint,
                self.downstream_contract_target_fingerprint,
            ):
                if len(fingerprint) != 64 or any(
                    char not in "0123456789abcdef" for char in fingerprint
                ):
                    raise ValueError(
                        "downstream contract fingerprints must be SHA-256"
                    )
            if (
                self.downstream_contract_source_fingerprint
                == self.downstream_contract_target_fingerprint
            ):
                raise ValueError(
                    "downstream contract transition requires a new target fingerprint"
                )
        retry_identifiers = (
            self.document_plan_retry_parent_stage_run_id,
            self.document_plan_retry_source_item_id,
        )
        if (
            self.document_plan_retry_generation == 0
            and any(retry_identifiers)
        ) or (
            self.document_plan_retry_generation > 0
            and not all(retry_identifiers)
        ):
            raise ValueError(
                "document-plan retry generation, parent, and source item must coexist"
            )
        transition_values = (
            self.document_plan_contract_transition_version,
            self.document_plan_contract_source_item_id,
            self.document_plan_contract_source_prompt_version,
            self.document_plan_contract_target_prompt_version,
        )
        if not self.document_plan_contract_transition_kind:
            if self.document_plan_contract_generation or any(
                (
                    *transition_values,
                    self.document_plan_contract_source_plan_id,
                    self.document_plan_contract_target_plan_id,
                    self.document_plan_contract_source_stage_run_id,
                    self.document_plan_contract_source_execution_fingerprint,
                    self.document_plan_contract_source_fingerprint,
                    self.document_plan_contract_target_fingerprint,
                )
            ):
                raise ValueError(
                    "document-plan contract transition kind is required"
                )
            return self
        if (
            self.document_plan_contract_generation == 0
            or not all(value.strip() for value in transition_values)
        ):
            raise ValueError(
                "document-plan contract transition fields must coexist"
            )
        if self.document_plan_retry_generation or any(retry_identifiers):
            raise ValueError(
                "ordinary retry and document-plan contract transition are mutually exclusive"
            )
        if self.document_plan_contract_transition_kind == "migration":
            required = (
                self.document_plan_contract_source_plan_id,
                self.document_plan_contract_target_plan_id,
                self.document_plan_contract_source_fingerprint,
                self.document_plan_contract_target_fingerprint,
            )
            if not all(value.strip() for value in required):
                raise ValueError(
                    "document-plan migration identity fields must coexist"
                )
            if (
                self.document_plan_contract_source_stage_run_id
                or self.document_plan_contract_source_execution_fingerprint
            ):
                raise ValueError(
                    "document-plan migration cannot carry supersession lineage"
                )
            for fingerprint in (
                self.document_plan_contract_source_fingerprint,
                self.document_plan_contract_target_fingerprint,
            ):
                if len(fingerprint) != 64:
                    raise ValueError(
                        "document-plan migration fingerprints must be SHA-256"
                    )
        else:
            if (
                not self.document_plan_contract_source_stage_run_id
                or len(
                    self.document_plan_contract_source_execution_fingerprint
                )
                != 64
            ):
                raise ValueError(
                    "document-plan supersession source identity is required"
                )
            if any(
                (
                    self.document_plan_contract_source_plan_id,
                    self.document_plan_contract_target_plan_id,
                    self.document_plan_contract_source_fingerprint,
                    self.document_plan_contract_target_fingerprint,
                )
            ):
                raise ValueError(
                    "document-plan supersession cannot carry migration identity"
                )
        return self


class WritingReferenceTranslationBatchCounts(WorkbenchModel):
    eligible_count: int = Field(default=0, ge=0)
    item_count: int = Field(default=0, ge=0)
    candidate_ready_count: int = Field(default=0, ge=0)
    fidelity_blocked_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    reused_count: int = Field(default=0, ge=0)
    pending_medical_review_count: int = Field(default=0, ge=0)
    approved_count: int = Field(default=0, ge=0)
    pending_author_confirmation_count: int = Field(default=0, ge=0)
    author_confirmed_count: int = Field(default=0, ge=0)
    admitted_count: int = Field(default=0, ge=0)
    excluded_count: int = Field(default=0, ge=0)


class WritingReferenceTranslationBatchPreview(WorkbenchModel):
    project_id: str
    snapshot_id: str
    glossary_version: str
    anchor_filter: List[str] = Field(default_factory=list)
    preparation_batch_id: str
    scope_sha256: str = Field(min_length=64, max_length=64)
    eligible_count: int = Field(default=0, ge=0)
    eligible_new_count: int = Field(default=0, ge=0)
    existing_candidate_count: int = Field(default=0, ge=0)
    fidelity_blocked_count: int = Field(default=0, ge=0)
    excluded_count: int = Field(default=0, ge=0)
    anchor_summaries: List[WritingReferenceTranslationBatchAnchorSummary] = Field(
        default_factory=list
    )
    document_exclusion_reason_counts: Dict[str, int] = Field(default_factory=dict)
    span_exclusion_reason_counts: Dict[str, int] = Field(default_factory=dict)
    exclusions: List[WritingReferenceTranslationBatchExclusion] = Field(
        default_factory=list
    )


class WritingReferenceTranslationBatch(WorkbenchModel):
    batch_id: str
    project_id: str
    snapshot_id: str
    glossary_version: str
    anchor_filter: List[str] = Field(default_factory=list)
    preparation_batch_id: str
    scope_sha256: str = Field(min_length=64, max_length=64)
    status: Literal[
        "accepted",
        "running",
        "completed",
        "completed_with_blocked",
        "partial_failure",
        "failed",
    ] = "accepted"
    attempt: int = Field(default=1, ge=1)
    counts: WritingReferenceTranslationBatchCounts = Field(
        default_factory=WritingReferenceTranslationBatchCounts
    )
    items: List[WritingReferenceTranslationBatchItem] = Field(default_factory=list)
    exclusions: List[WritingReferenceTranslationBatchExclusion] = Field(
        default_factory=list
    )
    created_by: str
    created_at: datetime
    updated_at: datetime


class WritingReferenceMedicalReviewRequest(WorkbenchModel):
    translation_revision: int = Field(ge=1)
    decision: str
    comment: str
    actor: str = "medical_manager"
    expected_revision: int = Field(default=0, ge=0)
    idempotency_key: str


class WritingReferenceAdmissionRequest(WorkbenchModel):
    expected_translation_revision: int = Field(ge=1)
    medical_review_id: str
    idempotency_key: str


class WritingReferenceInvalidationRequest(WorkbenchModel):
    reason: str
    actor: str = "medical_manager"
    expected_revision: int = Field(ge=1)
    idempotency_key: str


class WritingReferenceMedicalReviewDecision(WorkbenchModel):
    review_id: str
    project_id: str
    translation_id: str
    translation_revision: int = Field(ge=1)
    decision: str
    comment: str
    actor: str
    revision: int = Field(ge=1)
    decision_type: str = "legacy_medical_review"
    admission_status: str = "not_admitted"
    evidence_brief_id: str = ""
    identity_assurance: str = "unverified_client_claim"
    created_at: datetime


class WritingReferenceEvidenceBrief(WorkbenchModel):
    brief_id: str
    project_id: str
    nct_id: str
    artifact_id: str
    span_id: str
    translation_id: str
    translation_revision: int = Field(ge=1)
    ich_m11_anchor: str
    approved_zh_text: str
    source_locator: str
    source_text_sha256: str
    document_sha256: str
    glossary_version: str
    medical_review_id: str
    confirmation_type: str = "legacy_medical_review"
    author_confirmation_id: str = ""
    status: str = "approved_current"
    created_at: datetime


class RevisionActionRequest(WorkbenchModel):
    action: RevisionAction
    suggestion_id: Optional[str] = None
    actor: str = "medical_manager"
    comment: str = ""
    rewrite_instruction: str = ""


class RevisionAcceptAndApplyRequest(WorkbenchModel):
    """Request body for the atomic accept-and-apply endpoint.

    Uses WorkbenchModel (extra='forbid') so extra payload fields are rejected
    at the Pydantic boundary instead of being silently ignored.
    """

    suggestion_id: str = Field(min_length=1, max_length=160)
    expected_working_copy_revision: int = Field(ge=0)
    actor: str = Field(default="medical_manager", min_length=2, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=160)

    @model_validator(mode="after")
    def normalize_request(self) -> "RevisionAcceptAndApplyRequest":
        self.suggestion_id = self.suggestion_id.strip()
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if not self.suggestion_id:
            raise ValueError("suggestion_id must not be blank")
        if len(self.actor) < 2:
            raise ValueError("actor must not be blank")
        if len(self.idempotency_key) < 8:
            raise ValueError("idempotency_key must contain at least 8 characters")
        return self


class RevisionActionResult(WorkbenchModel):
    thread: RevisionThread
    action: RevisionAction
    suggestion: Optional[RevisionSuggestion] = None
    audit_event: AuditEvent


class SubjectTimelineEventType(str, Enum):
    VISIT = "visit"
    MEDICAL_HISTORY = "medical_history"
    CONCOMITANT_MEDICATION = "concomitant_medication"
    STUDY_DRUG_DISPENSING = "study_drug_dispensing"
    STUDY_DRUG_ADMINISTRATION = "study_drug_administration"
    STUDY_DRUG_ADHERENCE = "study_drug_adherence"
    BACKGROUND_TREATMENT = "background_treatment"
    NON_DRUG_TREATMENT = "non_drug_treatment"
    DOSE_ADJUSTMENT = "dose_adjustment"
    LAB = "lab"
    EFFICACY_SCORE = "efficacy_score"
    ADVERSE_EVENT = "adverse_event"
    PROTOCOL_DEVIATION = "protocol_deviation"
    QUERY = "query"


class SubjectTimelineEventDatePrecision(str, Enum):
    DAY = "day"
    MONTH = "month"
    YEAR = "year"
    UNKNOWN = "unknown"


class SubjectTimelineEventSubtype(str, Enum):
    PLANNED_VISIT = "planned_visit"
    UNSCHEDULED_VISIT = "unscheduled_visit"
    HISTORY_CONDITION = "history_condition"
    NON_STUDY_MEDICATION = "non_study_medication"
    STUDY_DRUG_DISPENSING = "study_drug_dispensing"
    STUDY_DRUG_ADMINISTRATION = "study_drug_administration"
    STUDY_DRUG_ADHERENCE = "study_drug_adherence"
    PROTOCOL_BACKGROUND_TREATMENT = "protocol_background_treatment"
    NON_DRUG_TREATMENT = "non_drug_treatment"
    STUDY_DRUG_INTERRUPTION = "study_drug_interruption"
    STUDY_DRUG_RESUMPTION = "study_drug_resumption"
    STUDY_DRUG_DOSE_REDUCTION = "study_drug_dose_reduction"
    STUDY_DRUG_DOSE_INCREASE = "study_drug_dose_increase"
    STUDY_DRUG_PERMANENT_DISCONTINUATION = "study_drug_permanent_discontinuation"
    LAB_RESULT = "lab_result"
    EFFICACY_ASSESSMENT = "efficacy_assessment"
    ADVERSE_EVENT = "adverse_event"
    PROTOCOL_DEVIATION = "protocol_deviation"
    QUERY = "query"
    OTHER = "other"


class SubjectDomainAvailabilityStatus(str, Enum):
    AVAILABLE = "available"
    ABSENT = "absent"
    UNMAPPED = "unmapped"
    UNSUPPORTED = "unsupported"


class SubjectTrendDomain(str, Enum):
    EFFICACY = "efficacy"
    SAFETY = "safety"


class SubjectTrendDirection(str, Enum):
    LOWER_IS_BETTER = "lower_is_better"
    HIGHER_IS_BETTER = "higher_is_better"
    STABLE_RANGE = "stable_range"


class SubjectOverview(WorkbenchModel):
    project_id: str
    subject_id: str
    site_id: str
    screening_number: str
    randomization_number: Optional[str] = None
    treatment_arm: str
    enrollment_status: str
    first_dose_date: Optional[str] = None
    baseline_visit_date: Optional[str] = None
    latest_visit_code: str
    latest_visit_label: str
    latest_visit_date: str
    sex: Optional[str] = None
    age_years: Optional[float] = None
    blinded: bool = False
    treatment_arm_masked: bool = False
    key_medical_context: List[str] = Field(default_factory=list)


class SubjectVisitAnchor(WorkbenchModel):
    anchor_id: str
    visit_code: str
    visit_label: str
    planned_study_day: Optional[int] = None
    window_before_days: Optional[int] = Field(default=None, ge=0)
    window_after_days: Optional[int] = Field(default=None, ge=0)
    actual_date: Optional[str] = None
    actual_study_day: Optional[int] = None
    is_unscheduled: bool = False
    deviation_days: Optional[int] = None
    source_domain: str = ""
    source_record_id: str = ""
    source_locator: str = ""


class SubjectTimelineEvent(WorkbenchModel):
    event_id: str
    project_id: str
    subject_id: str
    module: str = "medical_monitoring"
    module_label: str = "医学监查"
    event_type: SubjectTimelineEventType
    event_subtype: SubjectTimelineEventSubtype = SubjectTimelineEventSubtype.OTHER
    event_date: Optional[str] = None
    event_end_date: Optional[str] = None
    raw_event_date: str = ""
    raw_event_end_date: str = ""
    earliest_possible_date: Optional[str] = None
    latest_possible_date: Optional[str] = None
    date_parse_status: str = "parsed"
    study_day: Optional[int] = None
    end_study_day: Optional[int] = None
    ongoing: bool = False
    date_precision: SubjectTimelineEventDatePrecision = SubjectTimelineEventDatePrecision.DAY
    is_planned: Optional[bool] = None
    is_unscheduled: bool = False
    visit_code: Optional[str] = None
    visit_label: str = ""
    source_domain: str
    source_record_id: str
    source_locator: str = ""
    title: str
    detail: str
    result_value: Optional[str] = None
    severity: str = ""
    relationship: str = ""
    outcome: str = ""
    clinical_interpretation: str = ""
    related_risk_ids: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def fill_legacy_source_locator(self) -> "SubjectTimelineEvent":
        if not self.source_locator:
            self.source_locator = f"{self.source_domain}:{self.source_record_id}"
        return self


class SubjectTrendPoint(WorkbenchModel):
    point_id: str
    visit_code: str
    visit_label: str
    assessment_date: str
    study_day: Optional[int] = None
    value: float
    original_value: str = ""
    standardized_value: Optional[float] = None
    unit: str = ""
    baseline_value: Optional[float] = None
    is_baseline: bool = False
    baseline_rule: str = ""
    baseline_source_locator: str = ""
    baseline_component_source_locators: List[str] = Field(default_factory=list)
    baseline_expected_count: Optional[int] = Field(default=None, ge=1)
    baseline_observed_count: Optional[int] = Field(default=None, ge=0)
    baseline_missing_count: Optional[int] = Field(default=None, ge=0)
    change_from_baseline: Optional[float] = None
    percent_change_from_baseline: Optional[float] = None
    reference_low: Optional[float] = None
    reference_high: Optional[float] = None
    reference_range_text: str = ""
    reference_range_source: str = ""
    normality: str = "not_applicable"
    abnormal_direction: str = ""
    ctcae_grade: Optional[int] = Field(default=None, ge=0, le=5)
    ctcae_version: str = ""
    clinical_significance: str = ""
    assessment_sequence: Optional[int] = Field(default=None, ge=1)
    is_unscheduled: bool = False
    include_in_aggregate: bool = True
    risk_flag: bool = False
    source_domain: str
    source_record_id: str
    source_locator: str = ""
    source_component_locators: List[str] = Field(default_factory=list)
    related_risk_ids: List[str] = Field(default_factory=list)
    note: str = ""

    @model_validator(mode="after")
    def fill_legacy_source_locator(self) -> "SubjectTrendPoint":
        if not self.source_locator:
            self.source_locator = f"{self.source_domain}:{self.source_record_id}"
        return self


class SubjectTrendMetric(WorkbenchModel):
    metric_key: str
    metric_label: str
    domain: SubjectTrendDomain
    unit: str = ""
    direction: SubjectTrendDirection
    clinically_meaningful_change: Optional[float] = None
    points: List[SubjectTrendPoint] = Field(default_factory=list)


class SubjectDomainAvailability(WorkbenchModel):
    domain: str
    label: str
    status: SubjectDomainAvailabilityStatus
    detail: str = ""
    source_locator: str = ""


class TimepointRiskPrompt(WorkbenchModel):
    prompt_id: str
    project_id: str
    subject_id: str
    module: str = "medical_monitoring"
    module_label: str = "医学监查"
    visit_code: str
    visit_label: str
    prompt_date: str
    study_day: int
    severity: RiskSeverity
    status: RiskStatus
    risk_type: str
    title: str
    prompt_text: str
    trigger_domains: List[str] = Field(default_factory=list)
    related_event_ids: List[str] = Field(default_factory=list)
    related_metric_keys: List[str] = Field(default_factory=list)
    related_risk_ids: List[str] = Field(default_factory=list)
    evidence_span_ids: List[str] = Field(default_factory=list)
    query_id: Optional[str] = None
    pd_id: Optional[str] = None
    recommended_action: str


class SubjectMonitoringDrilldown(WorkbenchModel):
    project_id: str
    subject_id: str
    source_revision: NonEmptyContractString = "legacy"
    module: str = "medical_monitoring"
    module_label: str = "医学监查"
    generated_at: datetime
    subject: SubjectOverview
    visit_anchors: List[SubjectVisitAnchor] = Field(default_factory=list)
    timeline: List[SubjectTimelineEvent] = Field(default_factory=list)
    efficacy_trends: List[SubjectTrendMetric] = Field(default_factory=list)
    safety_trends: List[SubjectTrendMetric] = Field(default_factory=list)
    domain_availability: List[SubjectDomainAvailability] = Field(default_factory=list)
    risk_prompts: List[TimepointRiskPrompt] = Field(default_factory=list)
    review_focus: List[str] = Field(default_factory=list)
    capability_mode: Literal["full", "restricted"] = "full"
    capability_states: Dict[str, str] = Field(default_factory=dict)
    capability_limitations: Dict[str, List[str]] = Field(default_factory=dict)


class ListingSheetPayload(WorkbenchModel):
    sheet_name: str
    headers: List[str] = Field(default_factory=list)
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    row_numbers: List[int] = Field(default_factory=list)
    parser_warnings: List[str] = Field(default_factory=list)


class MonitoringIntakeRequest(WorkbenchModel):
    batch_label: str = "原始数据 listing Batch 004"
    extract_date: str
    previous_batch_id: Optional[str] = None
    uploaded_by: str = "medical_manager"
    mapping_confirmations: Dict[str, str] = Field(default_factory=dict)
    sheets: List[ListingSheetPayload] = Field(default_factory=list)


class MonitoringBatchValidationEvidenceRequest(WorkbenchModel):
    mapping_revision: str
    mapping: Dict[str, Any]
    expected_domains: List[str]
    full_snapshot_proof: Dict[str, Any]
    expected_version: int = Field(ge=1)
    idempotency_key: str


class MonitoringBatchConfirmFullSnapshotRequest(WorkbenchModel):
    expected_version: int = Field(ge=1)
    full_snapshot_proof: Dict[str, Any]
    actor: str = "medical_manager"
    idempotency_key: str


class MonitoringDerivedSnapshotSheetFact(WorkbenchModel):
    sheet_name: NonEmptyContractString
    parsed_row_count: int = Field(ge=0)


class MonitoringBatchVerifyDerivedSnapshotRequest(WorkbenchModel):
    expected_version: int = Field(ge=1)
    source_id: NonEmptyContractString
    source_content_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    original_source_class: Literal["raw_snapshot_with_format_defect"]
    parser_version: NonEmptyContractString
    transformation_type: Literal["parser_dimension_recovery"]
    execution_tool: NonEmptyContractString
    execution_tool_version: NonEmptyContractString
    original_parse_sheets: List[MonitoringDerivedSnapshotSheetFact] = Field(
        min_length=1
    )
    normalized_row_count: int = Field(ge=1)
    expected_domains: List[NonEmptyContractString] = Field(min_length=1)
    verified_by: NonEmptyContractString
    reason: str = Field(min_length=8, max_length=2_000)
    idempotency_key: NonEmptyContractString

    @model_validator(mode="after")
    def normalize_derived_snapshot_verification(self):
        sheet_names = [item.sheet_name.strip() for item in self.original_parse_sheets]
        if len(sheet_names) != len(set(sheet_names)):
            raise ValueError("original_parse_sheets sheet_name must be unique")
        domains = [item.strip().upper() for item in self.expected_domains]
        if len(domains) != len(set(domains)):
            raise ValueError("expected_domains must be unique")
        self.expected_domains = sorted(domains)
        self.reason = self.reason.strip()
        return self


class MonitoringBatchTransitionRequest(WorkbenchModel):
    target_state: Literal["parsed", "validated", "confirmed", "frozen"]
    expected_version: int = Field(ge=1)
    idempotency_key: str


class FieldMappingCandidate(WorkbenchModel):
    sheet_name: str
    source_field: str
    standard_field: str
    confidence: float
    status: str
    note: str = ""


class ListingDiffSummary(WorkbenchModel):
    previous_batch_id: Optional[str] = None
    new_batch_id: str
    added_row_count: int = 0
    changed_row_count: int = 0
    removed_row_count: int = 0
    subject_count: int = 0
    site_count: int = 0
    sheet_row_counts: Dict[str, int] = Field(default_factory=dict)
    new_subject_ids: List[str] = Field(default_factory=list)
    changed_subject_ids: List[str] = Field(default_factory=list)


class RuleRunSummary(WorkbenchModel):
    total_rules: int
    generated_risk_count: int
    generated_query_count: int
    blocked_by_mapping: bool = False
    messages: List[str] = Field(default_factory=list)


class MonitoringIntakeResult(WorkbenchModel):
    session_id: str
    project_id: str
    mapping_status: str
    batch: DataBatch
    field_mappings: List[FieldMappingCandidate] = Field(default_factory=list)
    diff_summary: ListingDiffSummary
    generated_risks: List[RiskCase] = Field(default_factory=list)
    rule_run: RuleRunSummary
    audit_preview: List[AuditEvent] = Field(default_factory=list)


class ClinicalDatasetSummary(WorkbenchModel):
    dataset_id: str
    dataset_name: str
    standard: str
    package_role: str = ""
    domain: str = ""
    label: str = ""
    class_name: str = ""
    purpose: str = ""
    structure: str = ""
    source_package: str
    relative_path: str
    file_format: str
    parser_status: str
    row_count: Optional[int] = None
    column_count: Optional[int] = None
    key_variables: List[str] = Field(default_factory=list)
    sample_variables: List[str] = Field(default_factory=list)
    define_linked: bool = False
    define_source: str = ""
    size_bytes: int = 0
    observed_study_ids: List[str] = Field(default_factory=list)
    study_identity_status: Literal["match", "warning", "mismatch", "not_assessed", "not_applicable"] = "not_assessed"
    observed_domain_values: List[str] = Field(default_factory=list)
    domain_consistency_status: Literal["match", "warning", "mismatch", "not_assessed", "not_applicable"] = "not_assessed"
    content_validation_notes: List[str] = Field(default_factory=list)


class TflOutputSummary(WorkbenchModel):
    output_id: str
    display_id: str
    output_type: str
    domain_hint: str = ""
    title_hint: str = ""
    source_package: str
    relative_path: str
    file_format: str
    parser_status: str
    paired_file_id: Optional[str] = None
    size_bytes: int = 0


class TflPackageSummary(WorkbenchModel):
    package_id: str
    package_label: str
    project_id: str
    module: str = "data_analysis_tfl"
    module_label: str = "数据分析与TFL"
    generated_at: datetime
    dataset_root_label: str
    tfl_root_label: str
    define_xml_count: int = 0
    define_itemgroup_count: int = 0
    dataset_count_by_standard: Dict[str, int] = Field(default_factory=dict)
    dataset_count_by_role: Dict[str, int] = Field(default_factory=dict)
    dataset_count_by_format: Dict[str, int] = Field(default_factory=dict)
    tfl_count_by_type: Dict[str, int] = Field(default_factory=dict)
    datasets: List[ClinicalDatasetSummary] = Field(default_factory=list)
    outputs: List[TflOutputSummary] = Field(default_factory=list)
    traceability_notes: List[str] = Field(default_factory=list)
    parser_warnings: List[str] = Field(default_factory=list)
    content_validation_status: Literal["matched", "warning", "mismatch", "not_assessed"] = "not_assessed"
    content_validation_notes: List[str] = Field(default_factory=list)
    expected_sap_version: str = ""
    sap_version_status: Literal["bound", "warning", "mismatch", "not_assessed", "not_applicable"] = "not_assessed"


class TflManifestResult(WorkbenchModel):
    project_id: str
    module: str = "data_analysis_tfl"
    module_label: str = "数据分析与TFL"
    generated_at: datetime
    package_count: int = 0
    total_datasets: int = 0
    total_outputs: int = 0
    packages: List[TflPackageSummary] = Field(default_factory=list)
    parser_notes: List[str] = Field(default_factory=list)


class TflReviewAction(str, Enum):
    MARK_REVIEWED = "mark_reviewed"
    REQUEST_STATISTICAL_REVIEW = "request_statistical_review"
    CREATE_WRITING_CANDIDATE = "create_writing_candidate"
    RETURN_FOR_DATASET_CHECK = "return_for_dataset_check"
    RESET_REVIEW = "reset_review"


class TflReviewActionRequest(WorkbenchModel):
    action: TflReviewAction
    actor: str = "medical_manager"
    comment: str = ""


class TflReviewRecord(WorkbenchModel):
    record_id: str
    project_id: str
    package_id: str
    output_id: str
    output_display_id: str
    action: TflReviewAction
    actor: str
    previous_status: str
    new_status: str
    comment: str = ""
    source_validation_bindings: List[SourceValidationBinding] = Field(default_factory=list)
    created_at: datetime


class TflReviewQualityGate(WorkbenchModel):
    gate_id: str
    gate_label: str
    status: str
    detail: str
    source_refs: List[str] = Field(default_factory=list)


class TflReviewWorkbenchResult(WorkbenchModel):
    project_id: str
    module: str = "data_analysis_tfl"
    module_label: str = "数据分析与TFL"
    generated_at: datetime
    package_id: str
    package_label: str
    selected_output_id: str
    selected_output: Optional[TflOutputSummary] = None
    paired_dataset: Optional[ClinicalDatasetSummary] = None
    current_status: str = "待医学审阅"
    review_records: List[TflReviewRecord] = Field(default_factory=list)
    quality_gates: List[TflReviewQualityGate] = Field(default_factory=list)
    candidate_outputs: List[TflOutputSummary] = Field(default_factory=list)
    dataset_context: List[ClinicalDatasetSummary] = Field(default_factory=list)
    source_admission: Optional[SourceAdmissionState] = None
    available_actions: List[TflReviewAction] = Field(default_factory=list)
    formal_output_boundary: str = "当前仅形成待医学确认的数据审阅和写作引用候选，不生成正式监管TFL。"
    needs_medical_confirmation: bool = True
    codex_runtime_dependency: bool = False


class TflWritingCitationCandidate(WorkbenchModel):
    candidate_id: str
    project_id: str
    source_module: str = "data_analysis_tfl"
    source_module_label: str = "数据分析与TFL"
    target_module: str = "medical_writing"
    target_module_label: str = "医学写作"
    package_id: str
    package_label: str
    output_id: str
    output_display_id: str
    output_type: str
    domain_hint: str = ""
    title_hint: str = ""
    paired_dataset_id: str = ""
    paired_dataset_name: str = ""
    paired_dataset_standard: str = ""
    paired_dataset_domain: str = ""
    paired_dataset_row_count: Optional[int] = None
    review_record_id: str
    reviewer: str
    review_comment: str
    review_created_at: datetime
    recommended_writing_sections: List[str] = Field(default_factory=list)
    source_refs: List[str] = Field(default_factory=list)
    source_validation_bindings: List[SourceValidationBinding] = Field(default_factory=list)
    citation_boundary: str = "仅作为待医学确认的写作引用候选；正式写入前需核对CSR/SAP/统计输出和版本。"
    needs_medical_confirmation: bool = True
    codex_runtime_dependency: bool = False


class TflWritingCitationManifestResult(WorkbenchModel):
    project_id: str
    module: str = "medical_writing"
    module_label: str = "医学写作"
    source_module: str = "data_analysis_tfl"
    source_module_label: str = "数据分析与TFL"
    generated_at: datetime
    total_candidates: int = 0
    candidates: List[TflWritingCitationCandidate] = Field(default_factory=list)
    quality_gates: List[TflReviewQualityGate] = Field(default_factory=list)
    source_admissions: List[SourceAdmissionState] = Field(default_factory=list)
    blocked_stale_candidate_count: int = 0
    formal_output_boundary: str = "当前仅汇总TFL写作引用候选，不自动生成或改写正式医学写作正文。"
    needs_medical_confirmation: bool = True
    codex_runtime_dependency: bool = False


class SafetySourceDocumentSummary(WorkbenchModel):
    document_id: str
    document_type: str
    project_code: str
    public_title: str
    source_package: str
    relative_path: str
    file_format: str
    parser_status: str
    size_bytes: int = 0
    role_hint: str = ""
    key_topics: List[str] = Field(default_factory=list)


class SafetyListingDomainSummary(WorkbenchModel):
    domain_id: str
    sheet_name: str
    domain: str
    domain_label: str
    safety_relevance: str
    row_count: int = 0
    subject_count: int = 0
    site_count: int = 0
    key_fields: List[str] = Field(default_factory=list)
    parser_status: str = "parsed"
    parser_notes: List[str] = Field(default_factory=list)
    source_package: str = ""


class SafetySignalCandidate(WorkbenchModel):
    signal_id: str
    signal_type: str
    signal_label: str
    title: str
    severity: RiskSeverity
    source_package: str
    source_domains: List[str] = Field(default_factory=list)
    evidence_locators: List[str] = Field(default_factory=list)
    subject_id: Optional[str] = None
    site_id: Optional[str] = None
    observation: str
    medical_pv_boundary: str
    recommended_next_step: str
    confirmation_status: str = "待医学/PV确认"


class SafetyReviewAction(str, Enum):
    MARK_MEDICAL_REVIEWED = "mark_medical_reviewed"
    REQUEST_PV_CONFIRMATION = "request_pv_confirmation"
    RETURN_FOR_SOURCE_CHECK = "return_for_source_check"
    ACCEPT_NO_ACTION = "accept_no_action"
    RESET_REVIEW = "reset_review"


class SafetyReviewActionRequest(WorkbenchModel):
    action: SafetyReviewAction
    actor: str = "medical_manager"
    comment: str = ""
    expected_revision: int = Field(default=0, ge=0)
    idempotency_key: str = ""
    expected_source_binding_digest: str = ""


class SafetyReviewRecord(WorkbenchModel):
    record_id: str
    project_id: str
    package_id: str
    signal_id: str
    signal_label: str
    action: SafetyReviewAction
    actor: str
    previous_status: str
    new_status: str
    comment: str = ""
    previous_revision: int = Field(default=0, ge=0)
    revision: int = Field(default=1, ge=1)
    source_validation_bindings: List[SourceValidationBinding] = Field(default_factory=list)
    created_at: datetime


class SafetyQualityGate(WorkbenchModel):
    gate_id: str
    gate_label: str
    status: str
    owner: str
    detail: str
    source_refs: List[str] = Field(default_factory=list)


class SafetySourcePackageSummary(WorkbenchModel):
    package_id: str
    package_label: str
    project_code: str
    source_root_label: str
    package_role: str
    listing_domains: List[SafetyListingDomainSummary] = Field(default_factory=list)
    documents: List[SafetySourceDocumentSummary] = Field(default_factory=list)
    signal_candidates: List[SafetySignalCandidate] = Field(default_factory=list)
    quality_gates: List[SafetyQualityGate] = Field(default_factory=list)
    parser_warnings: List[str] = Field(default_factory=list)


class SafetyPvManifestResult(WorkbenchModel):
    project_id: str
    module: str = "safety_pv"
    module_label: str = "安全信号与PV协同"
    generated_at: datetime
    package_count: int = 0
    total_listing_domains: int = 0
    total_documents: int = 0
    total_signal_candidates: int = 0
    quality_gate_count: int = 0
    packages: List[SafetySourcePackageSummary] = Field(default_factory=list)
    parser_notes: List[str] = Field(default_factory=list)


class SafetyReviewWorkbenchResult(WorkbenchModel):
    project_id: str
    module: str = "safety_pv"
    module_label: str = "安全信号与PV协同"
    generated_at: datetime
    package_id: str
    package_label: str
    selected_signal_id: str
    selected_signal: Optional[SafetySignalCandidate] = None
    current_status: str = "待医学/PV确认"
    state_revision: int = Field(default=0, ge=0)
    source_binding_digest: str = ""
    review_records: List[SafetyReviewRecord] = Field(default_factory=list)
    quality_gates: List[SafetyQualityGate] = Field(default_factory=list)
    candidate_signals: List[SafetySignalCandidate] = Field(default_factory=list)
    listing_context: List[SafetyListingDomainSummary] = Field(default_factory=list)
    document_context: List[SafetySourceDocumentSummary] = Field(default_factory=list)
    source_admission: Optional[SourceAdmissionState] = None
    available_actions: List[SafetyReviewAction] = Field(default_factory=list)
    formal_output_boundary: str = "当前仅形成待医学/PV确认的安全信号审阅和PV交接候选，不生成最终药物警戒结论或监管递交动作。"
    needs_medical_pv_confirmation: bool = True
    codex_runtime_dependency: bool = False


class SafetyPvHandoffCandidate(WorkbenchModel):
    candidate_id: str
    project_id: str
    source_module: str = "safety_pv"
    source_module_label: str = "安全信号与PV协同"
    package_id: str
    package_label: str
    signal_id: str
    signal_label: str
    signal_type: str
    title: str
    severity: RiskSeverity
    source_domains: List[str] = Field(default_factory=list)
    evidence_locators: List[str] = Field(default_factory=list)
    review_record_id: str
    reviewer: str
    review_comment: str
    review_created_at: datetime
    recommended_handoff_sections: List[str] = Field(default_factory=list)
    source_validation_bindings: List[SourceValidationBinding] = Field(default_factory=list)
    handoff_boundary: str = "仅作为待医学/PV确认的协同交接候选；最终安全性结论、报告性判断和监管递交流程仍需PV流程确认。"
    needs_medical_pv_confirmation: bool = True
    codex_runtime_dependency: bool = False


class SafetyMonitoringCollaborationHandoff(WorkbenchModel):
    handoff_id: str
    project_id: str
    source_module: str = "medical_monitoring"
    source_module_label: str = "医学监查"
    risk_id: str
    risk_key: str = ""
    risk_instance_id: str = ""
    snapshot_id: str = ""
    subject_id: str = ""
    rule_id: str = ""
    title: str
    severity: RiskSeverity
    source_version: str
    disposition_record_id: str
    disposition_status: str = "已转Safety/PV协作"
    reviewer: str
    review_comment: str
    source_refs: List[WorkbenchItemSourceRef] = Field(default_factory=list)
    created_at: datetime
    is_current: bool = True
    stale_reason: str = ""
    handoff_boundary: str = "医学监查是风险事实源；Safety/PV仅显示同一风险的只读协作投影，处置仍回到医学监查完成。"


class SafetyPvHandoffManifestResult(WorkbenchModel):
    project_id: str
    module: str = "safety_pv"
    module_label: str = "安全信号与PV协同"
    generated_at: datetime
    total_candidates: int = 0
    candidates: List[SafetyPvHandoffCandidate] = Field(default_factory=list)
    monitoring_collaboration_count: int = 0
    monitoring_collaborations: List[SafetyMonitoringCollaborationHandoff] = Field(default_factory=list)
    blocked_monitoring_collaboration_count: int = 0
    quality_gates: List[SafetyQualityGate] = Field(default_factory=list)
    source_admissions: List[SourceAdmissionState] = Field(default_factory=list)
    blocked_stale_candidate_count: int = 0
    formal_output_boundary: str = "当前仅汇总待医学/PV确认的协同交接候选，不生成最终药物警戒结论或监管递交动作。"
    needs_medical_pv_confirmation: bool = True
    codex_runtime_dependency: bool = False


class EvidenceSourceDocumentSummary(WorkbenchModel):
    document_id: str
    document_type: str
    public_title: str
    drug_name: str = ""
    trial_identifier: str = ""
    source_package: str
    relative_path: str = ""
    file_format: str = ""
    parser_status: str = "inventory_only"
    primary_source_type: str = ""
    primary_source_id: str = ""
    primary_source_date: str = ""
    verification_status: str = ""
    evidence_level: str = ""
    role_hint: str = ""


class CompetitiveProductSummary(WorkbenchModel):
    product_id: str
    drug_name: str
    target: str = ""
    sponsor: str = ""
    trial_count: int = 0
    phase_summary: Dict[str, int] = Field(default_factory=dict)
    region_summary: Dict[str, int] = Field(default_factory=dict)
    highest_evidence_level: str = ""
    approval_status_hint: str = ""


class CompetitiveTrialDesignSummary(WorkbenchModel):
    trial_id: str
    drug_name: str
    target: str = ""
    sponsor: str = ""
    registry: str = ""
    registry_id: str = ""
    trial_acronym: str = ""
    phase: str = ""
    trial_status: str = ""
    region: str = ""
    design_type: str = ""
    sample_size: str = ""
    treatment_group: str = ""
    comparator: str = ""
    dose: str = ""
    route: str = ""
    dosing_frequency: str = ""
    treatment_period: str = ""
    background_treatment: str = ""
    key_population: str = ""
    primary_endpoint: str = ""
    primary_timepoint: str = ""
    key_secondary_endpoint: str = ""
    protocol_available: str = ""
    sap_available: str = ""
    publication_available: str = ""
    verification_status: str = ""
    evidence_level: str = ""


class CompetitiveResultEndpointSummary(WorkbenchModel):
    result_id: str
    result_kind: str
    trial_id: str
    drug_name: str
    trial_identifier: str = ""
    endpoint_name: str
    endpoint_type: str = ""
    timepoint: str = ""
    treatment_group: str = ""
    comparator: str = ""
    sample_size: str = ""
    effect_summary: str = ""
    source_type: str = ""
    source_locator: str = ""
    verification_status: str = ""
    evidence_level: str = ""
    medical_boundary: str = "待医学确认，不构成跨试验疗效或安全性判断"


class EvidencePicosOptionTemplate(WorkbenchModel):
    label: str
    design_summary: str
    medical_rationale_prompt: str
    writing_target_section: str = ""
    evidence_summary: str = ""
    risk_notes: List[str] = Field(default_factory=list)


class EvidencePicosQuestion(WorkbenchModel):
    question_id: str
    picos_domain: str
    question: str
    evidence_status: str
    current_evidence_summary: str
    required_user_decision: str
    source_refs: List[str] = Field(default_factory=list)
    handoff_to_writing: bool = True
    option_templates: List[EvidencePicosOptionTemplate] = Field(default_factory=list)


class EvidencePicosDecisionAction(str, Enum):
    SELECT_OPTION = "select_option"
    SAVE_RATIONALE = "save_rationale"
    MARK_WRITING_CANDIDATE = "mark_writing_candidate"
    RETURN_FOR_EVIDENCE = "return_for_evidence"
    RESET_DECISION = "reset_decision"


class EvidencePicosDecisionOption(WorkbenchModel):
    option_id: str
    label: str
    design_summary: str
    evidence_summary: str
    medical_rationale_prompt: str
    writing_target_section: str = ""
    source_refs: List[str] = Field(default_factory=list)
    risk_notes: List[str] = Field(default_factory=list)
    candidate_rank: int = 0


class EvidencePicosDecisionRecord(WorkbenchModel):
    record_id: str
    project_id: str
    package_id: str
    working_state_id: str = ""
    question_id: str
    action: EvidencePicosDecisionAction
    actor: str = "medical_manager"
    option_id: str = ""
    user_rationale: str = ""
    comment: str = ""
    from_status: str = ""
    to_status: str = ""
    previous_revision: int = 0
    new_revision: int = 0
    created_at: datetime


class EvidencePicosWorkflowStep(WorkbenchModel):
    question_id: str
    picos_domain: str
    question: str
    evidence_status: str
    current_evidence_summary: str
    required_user_decision: str
    source_refs: List[str] = Field(default_factory=list)
    handoff_to_writing: bool = True
    options: List[EvidencePicosDecisionOption] = Field(default_factory=list)
    selected_option_id: str = ""
    user_rationale: str = ""
    decision_status: str = "待用户确认"
    writing_handoff_status: str = "暂不可流转"
    writing_target_section: str = ""
    quality_gate_status: str = "blocked"
    revision_thread_id: str = ""
    ai_task_type: str = "picos_design_coach"
    ai_gateway_status: str = "not_configured"
    codex_runtime_dependency: bool = False
    needs_medical_confirmation: bool = True
    author_confirmation_status: str = "not_confirmed"
    revision: int = 0
    audit_trail: List[EvidencePicosDecisionRecord] = Field(default_factory=list)


class EvidencePicosActionRequest(WorkbenchModel):
    action: EvidencePicosDecisionAction
    option_id: str = ""
    user_rationale: str = ""
    comment: str = ""
    actor: str = "medical_manager"
    expected_revision: Optional[int] = Field(default=None, ge=0)
    expected_evidence_package_hash: str = ""
    idempotency_key: str = ""


class EvidencePicosQuestionState(WorkbenchModel):
    question_id: str
    selected_option_id: str = ""
    user_rationale: str = ""
    decision_status: str = "待用户确认"
    writing_target_section: str = ""


class EvidencePicosWorkingState(WorkbenchModel):
    working_state_id: str
    project_id: str
    package_id: str
    evidence_package_hash: str
    revision: int = Field(ge=0)
    approval_state: ApprovalState = ApprovalState.AI_DRAFT
    approved_revision: Optional[int] = None
    approved_snapshot_id: str = ""
    question_states: List[EvidencePicosQuestionState] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class EvidenceReviewAction(str, Enum):
    INCLUDE = "include"
    EXCLUDE = "exclude"
    DEFER = "defer"
    MARK_DUPLICATE = "mark_duplicate"
    SAVE_EXTRACTION = "save_extraction"
    SAVE_APPRAISAL = "save_appraisal"
    RESET_REVIEW = "reset_review"


class EvidenceReviewActionRequest(WorkbenchModel):
    action: EvidenceReviewAction
    actor: str = "medical_manager"
    reason: str = ""
    extraction: Dict[str, str] = Field(default_factory=dict)
    quality_rating: str = ""
    expected_revision: int = Field(default=0, ge=0)
    idempotency_key: str = ""


class EvidenceReviewRecord(WorkbenchModel):
    record_id: str
    project_id: str
    package_id: str
    evidence_id: str
    action: EvidenceReviewAction
    actor: str = "medical_manager"
    reason: str = ""
    extraction: Dict[str, str] = Field(default_factory=dict)
    quality_rating: str = ""
    screening_status: str = "待筛选"
    appraisal_status: str = "待评价"
    previous_revision: int = 0
    new_revision: int = 1
    created_at: datetime


class EvidenceReviewState(WorkbenchModel):
    project_id: str
    package_id: str
    evidence_id: str
    revision: int = 0
    screening_status: str = "待筛选"
    appraisal_status: str = "待评价"
    reason: str = ""
    extraction: Dict[str, str] = Field(default_factory=dict)
    quality_rating: str = ""
    history: List[EvidenceReviewRecord] = Field(default_factory=list)


class EvidencePicosWorkflowResult(WorkbenchModel):
    project_id: str
    package_id: str
    module: str = "evidence_design"
    module_label: str = "证据调研与方案设计"
    workflow_label: str = "PICOS 决策工作台"
    generated_at: datetime
    working_state_id: str = ""
    revision: int = 0
    evidence_package_hash: str = ""
    approval_state: ApprovalState = ApprovalState.AI_DRAFT
    approved_revision: Optional[int] = None
    approved_snapshot_id: str = ""
    confirmation_status: str = "not_confirmed"
    confirmed_revision: Optional[int] = None
    confirmed_snapshot_id: str = ""
    current_handoff_id: str = ""
    current_handoff_snapshot_id: str = ""
    current_handoff_revision: Optional[int] = None
    current_handoff_target_document_type: str = ""
    decision_count: int = 0
    writing_candidate_count: int = 0
    blocking_gate_count: int = 0
    ai_gateway_status: str = "not_configured"
    codex_runtime_dependency: bool = False
    needs_medical_confirmation: bool = True
    formal_output_boundary: str = "所有PICOS输出均为待作者确认的写作候选；作者确认后方可进入当前写作版本，不代表已完成Evidence/PV/Safety审批。"
    steps: List[EvidencePicosWorkflowStep] = Field(default_factory=list)
    quality_gates: List[EvidenceQualityGate] = Field(default_factory=list)
    parser_notes: List[str] = Field(default_factory=list)


class EvidencePicosSnapshot(WorkbenchModel):
    snapshot_id: str
    project_id: str
    package_id: str
    working_state_id: str
    revision: int = Field(ge=1)
    evidence_package_hash: str
    approval_id: str
    snapshot_type: str = "medical_review_submission"
    confirmation_type: str = "legacy_medical_approval"
    created_by: str = "medical_manager"
    question_states: List[EvidencePicosQuestionState] = Field(default_factory=list)
    created_at: datetime


class EvidencePicosWritingHandoff(WorkbenchModel):
    handoff_id: str
    project_id: str
    package_id: str
    working_state_id: str
    snapshot_id: str
    approval_id: str
    approved_revision: int = Field(ge=1)
    confirmation_id: str = ""
    confirmed_revision: Optional[int] = Field(default=None, ge=1)
    target_module: str = "medical_writing"
    target_document_type: str = "protocol"
    created_by: str = "medical_manager"
    source_refs: List[str] = Field(default_factory=list)
    created_at: datetime


class EvidencePicosSubmitApprovalRequest(WorkbenchModel):
    actor: str = "medical_manager"
    comment: str = ""
    expected_revision: int = Field(ge=1)
    expected_evidence_package_hash: str
    idempotency_key: str = ""


class EvidencePicosApprovalSubmissionResult(WorkbenchModel):
    snapshot: EvidencePicosSnapshot
    approval: ApprovalGate
    workflow: EvidencePicosWorkflowResult


class EvidencePicosHandoffRequest(WorkbenchModel):
    snapshot_id: str
    actor: str = "medical_manager"
    target_document_type: str = "protocol"
    idempotency_key: str = ""


class EvidenceAiRevisionAction(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    REQUEST_REWRITE = "request_rewrite"


class EvidenceAiRevisionProposal(WorkbenchModel):
    proposal_id: str
    ai_run_id: str
    proposal_text: str
    proposed_option_id: str
    rationale: str
    evidence_span_ids: List[str] = Field(default_factory=list)
    uncertainty: str = ""
    user_decision: str = "pending"
    created_at: datetime


class EvidenceAiRevisionThread(WorkbenchModel):
    thread_id: str
    project_id: str
    package_id: str
    anchor_type: str
    anchor_id: str
    base_picos_revision: int = Field(ge=0)
    evidence_package_hash: str
    revision: int = Field(ge=1)
    status: str = "pending_medical_action"
    user_instruction: str
    source_evidence_ids: List[str] = Field(default_factory=list)
    proposals: List[EvidenceAiRevisionProposal] = Field(default_factory=list)
    created_by: str = "medical_manager"
    created_at: datetime
    updated_at: datetime


class EvidenceAiRevisionRequest(WorkbenchModel):
    anchor_type: str = "picos_question"
    anchor_id: str
    user_instruction: str
    source_evidence_ids: List[str] = Field(default_factory=list)
    expected_picos_revision: int = Field(ge=0)
    expected_evidence_package_hash: str
    actor: str = "medical_manager"
    idempotency_key: str = ""


class EvidenceAiRevisionActionRequest(WorkbenchModel):
    action: EvidenceAiRevisionAction
    proposal_id: str
    expected_thread_revision: int = Field(ge=1)
    actor: str = "medical_manager"
    comment: str = ""
    rewrite_instruction: str = ""
    idempotency_key: str = ""


class EvidenceAiRevisionResult(WorkbenchModel):
    thread: EvidenceAiRevisionThread
    proposal: EvidenceAiRevisionProposal
    requires_explicit_picos_action: bool = True
    recommended_picos_action: Dict[str, str] = Field(default_factory=dict)


class EvidenceQualityGate(WorkbenchModel):
    gate_id: str
    gate_label: str
    status: str
    owner: str
    detail: str
    source_refs: List[str] = Field(default_factory=list)


class EvidencePackageCatalogSummary(WorkbenchModel):
    package_id: str
    package_label: str
    indication: str
    source_root_label: str
    package_role: str
    product_count: int = 0
    candidate_count_by_type: Dict[str, int] = Field(default_factory=dict)
    source_status: str = "ready"
    diagnostics: List[str] = Field(default_factory=list)


class EvidencePackageCatalogResult(WorkbenchModel):
    project_id: str
    module: str = "evidence_design"
    module_label: str = "证据调研与方案设计"
    generated_at: datetime
    packages: List[EvidencePackageCatalogSummary] = Field(default_factory=list)


class EvidenceCandidateSummary(WorkbenchModel):
    evidence_id: str
    package_id: str
    evidence_type: str
    title: str
    primary_source_id: str
    drug_name: str = ""
    trial_identifier: str = ""
    phase: str = ""
    source_status: str = ""
    source_date: str = ""
    evidence_level: str = ""
    screening_status: str = "待筛选"
    appraisal_status: str = "待评价"
    review_revision: int = 0
    source_ref_count: int = 0
    search_text: str = Field(default="", exclude=True)


class EvidenceCandidateDetail(EvidenceCandidateSummary):
    project_id: str = ""
    source_scope: str = "real_raw_source"
    source_refs: List[str] = Field(default_factory=list)
    provenance: Dict[str, str] = Field(default_factory=dict)
    metadata: Dict[str, str] = Field(default_factory=dict)


class EvidenceCandidatePage(WorkbenchModel):
    project_id: str
    package_id: str
    candidate_type: str
    page: int
    page_size: int
    total: int
    has_next: bool = False
    items: List[EvidenceCandidateSummary] = Field(default_factory=list)


class EvidenceDesignPackageSummary(WorkbenchModel):
    package_id: str
    package_label: str
    indication: str
    source_root_label: str
    package_role: str
    total_product_count: int = 0
    total_trial_count: int = 0
    total_document_count: int = 0
    total_result_count: int = 0
    candidate_count_by_type: Dict[str, int] = Field(default_factory=dict)
    products: List[CompetitiveProductSummary] = Field(default_factory=list)
    trial_count_by_phase: Dict[str, int] = Field(default_factory=dict)
    trial_count_by_status: Dict[str, int] = Field(default_factory=dict)
    document_count_by_type: Dict[str, int] = Field(default_factory=dict)
    endpoint_count_by_name: Dict[str, int] = Field(default_factory=dict)
    safety_row_count: int = 0
    documents: List[EvidenceSourceDocumentSummary] = Field(default_factory=list)
    trial_designs: List[CompetitiveTrialDesignSummary] = Field(default_factory=list)
    efficacy_results: List[CompetitiveResultEndpointSummary] = Field(default_factory=list)
    safety_results: List[CompetitiveResultEndpointSummary] = Field(default_factory=list)
    picos_questions: List[EvidencePicosQuestion] = Field(default_factory=list)
    quality_gates: List[EvidenceQualityGate] = Field(default_factory=list)
    parser_warnings: List[str] = Field(default_factory=list)


class EvidenceDesignManifestResult(WorkbenchModel):
    project_id: str
    module: str = "evidence_design"
    module_label: str = "证据调研与方案设计"
    generated_at: datetime
    package_count: int = 0
    total_products: int = 0
    total_trials: int = 0
    total_documents: int = 0
    total_result_rows: int = 0
    picos_question_count: int = 0
    quality_gate_count: int = 0
    packages: List[EvidenceDesignPackageSummary] = Field(default_factory=list)
    parser_notes: List[str] = Field(default_factory=list)


class WritingSourceDocumentSummary(WorkbenchModel):
    document_id: str
    document_type: str
    project_code: str
    public_title: str
    source_package: str
    relative_path: str
    file_format: str
    parser_status: str
    content_hash: str = Field(default="", exclude=True)
    size_bytes: int = 0
    paragraph_count: int = 0
    table_count: int = 0
    span_count: int = 0
    section_count: int = 0
    image_count: int = 0
    has_revision_marks: bool = False
    has_fields: bool = False
    style_summary: Dict[str, int] = Field(default_factory=dict)
    protocol_identifier: str = ""
    protocol_version: str = ""
    protocol_date: str = ""
    indication_hint: str = ""
    role_hint: str = ""


class WritingSectionSummary(WorkbenchModel):
    section_id: str
    source_document_id: str
    section_number: str = ""
    heading: str
    heading_level: int = 1
    anchor_path: str
    source_locator: str
    paragraph_count: int = 0
    table_count: int = 0
    word_count: int = 0
    ich_m11_area: str = ""
    writing_status: str = "待医学审阅"
    evidence_status: str = "待补来源定位"
    medical_approval_status: str = "待作者确认"
    ai_task_ready: bool = False
    extraction_confidence: float = 0.0
    requires_human_mapping: bool = True
    evidence_coverage_percent: int = 0
    revision_thread_count: int = 0
    risk_count: int = 0
    text_preview: str = Field(default="", exclude=True)
    source_refs: List[str] = Field(default_factory=list)


class WritingTableSummary(WorkbenchModel):
    table_id: str
    source_document_id: str
    table_index: int
    source_locator: str
    title_hint: str = ""
    row_count: int = 0
    column_count: int = 0
    nonempty_cell_count: int = 0
    merge_detected: bool = False
    headers: List[str] = Field(default_factory=list)
    role_hint: str = ""
    parser_status: str = "parsed"
    linked_section_id: str = ""
    quality_notes: List[str] = Field(default_factory=list)


class WritingQualityGate(WorkbenchModel):
    gate_id: str
    gate_label: str
    status: str
    owner: str
    detail: str
    source_refs: List[str] = Field(default_factory=list)


class WritingSourcePackageSummary(WorkbenchModel):
    package_id: str
    package_label: str
    project_code: str
    indication: str
    source_root_label: str
    package_role: str
    source_span_count: int = 0
    evidence_coverage_percent: int = 0
    revision_thread_count: int = 0
    pending_medical_approval_count: int = 0
    blocking_gate_count: int = 0
    can_generate_review_docx: bool = False
    formal_export_status: str = "不可生成正式导出包"
    ai_revision_boundary: str = "AI 修订建议仅为写作候选，须经作者确认后方可冻结当前版本；独立模型未接入前不可生成生产写作结论。"
    documents: List[WritingSourceDocumentSummary] = Field(default_factory=list)
    sections: List[WritingSectionSummary] = Field(default_factory=list)
    tables: List[WritingTableSummary] = Field(default_factory=list)
    quality_gates: List[WritingQualityGate] = Field(default_factory=list)
    parser_warnings: List[str] = Field(default_factory=list)


class MedicalWritingManifestResult(WorkbenchModel):
    project_id: str
    module: str = "medical_writing"
    module_label: str = "医学写作"
    generated_at: datetime
    package_count: int = 0
    total_documents: int = 0
    total_sections: int = 0
    total_tables: int = 0
    total_source_spans: int = 0
    quality_gate_count: int = 0
    packages: List[WritingSourcePackageSummary] = Field(default_factory=list)
    parser_notes: List[str] = Field(default_factory=list)


class ModuleStatus(WorkbenchModel):
    module: str
    label: str
    status: str
    completion_rate: float
    open_risk_count: int
    pending_task_count: int
    pending_approval_count: int


class DashboardSummary(WorkbenchModel):
    project: Project
    modules: List[ModuleStatus]
    latest_batch: Optional[DataBatch]
    risk_counts_by_severity: Dict[str, int]
    pending_approvals: List[ApprovalGate]
    recent_risks: List[RiskCase]


# ---------------------------------------------------------------------------
# Conversational fact intake (IB-optional, generic study-fact collection)
# ---------------------------------------------------------------------------

class MedicalWritingFactIntakeScope(str, Enum):
    """The conversational fact-intake surface is generic: ``study_framing``
    is the first concrete scope (IB-optional product/study facts) and later
    scopes such as ``picos`` reuse the same conversation mechanism."""

    STUDY_FRAMING = "study_framing"


class MedicalWritingFactIntakeFactKind(str, Enum):
    """How a proposed fact was established. The AI must keep user-stated
    facts, its own inferences, unknowns, conflicts and high-impact gaps
    separate; it must never invent an exact dose, escalation step, interval,
    exposure margin, threshold or monitoring window."""

    USER_STATED = "user_stated"
    SOURCE_EXTRACTED = "source_extracted"
    AI_INFERRED = "ai_inferred"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


class MedicalWritingFactIntakeProposalDecision(str, Enum):
    PENDING = "pending"
    ADOPTED = "adopted"
    EDITED = "edited"
    REJECTED = "rejected"


class MedicalWritingFactIntakeProposal(WorkbenchModel):
    """A single AI-proposed structured fact, bound to an allowlisted field
    path. A medical manager's explicit adoption/edit/rejection is final
    project-level confirmation; there is no second ``pending medical
    approval`` state."""

    proposal_id: str = Field(min_length=1, max_length=120)
    field_path: str = Field(min_length=1, max_length=200)
    fact_kind: MedicalWritingFactIntakeFactKind
    value: str = Field(default="", max_length=20_000)
    rationale: str = Field(default="", max_length=4_000)
    source_ids: List[str] = Field(default_factory=list, max_length=50)
    confidence: Literal["unknown", "low", "medium", "high"] = "unknown"
    decision: MedicalWritingFactIntakeProposalDecision = (
        MedicalWritingFactIntakeProposalDecision.PENDING
    )
    edited_value: str = Field(default="", max_length=20_000)
    decided_by: str = Field(default="", max_length=100)
    decided_at: Optional[datetime] = None
    decision_note: str = Field(default="", max_length=4_000)

    @model_validator(mode="after")
    def normalize_fact_intake_proposal(self) -> "MedicalWritingFactIntakeProposal":
        self.proposal_id = self.proposal_id.strip()
        self.field_path = self.field_path.strip()
        self.value = self.value.strip()
        self.rationale = self.rationale.strip()
        self.edited_value = self.edited_value.strip()
        self.decision_note = self.decision_note.strip()
        self.decided_by = self.decided_by.strip()
        self.source_ids = [item.strip() for item in self.source_ids if item.strip()]
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("fact intake proposal source ids must be unique")
        if self.fact_kind == MedicalWritingFactIntakeFactKind.UNKNOWN:
            if self.value.strip():
                raise ValueError(
                    "an unknown fact must not carry a value; record it as a "
                    "high-impact missing field instead"
                )
            self.source_ids = []
            self.confidence = "unknown"
        elif not self.value and self.fact_kind in {
            MedicalWritingFactIntakeFactKind.USER_STATED,
            MedicalWritingFactIntakeFactKind.SOURCE_EXTRACTED,
            MedicalWritingFactIntakeFactKind.AI_INFERRED,
        }:
            raise ValueError(
                "a user-stated, source-extracted or ai-inferred fact requires a value"
            )
        if self.decision == MedicalWritingFactIntakeProposalDecision.PENDING:
            if self.edited_value or self.decided_by or self.decision_note:
                raise ValueError(
                    "pending fact intake proposals must not carry decision fields"
                )
        else:
            if not self.decided_by or self.decided_at is None:
                raise ValueError(
                    "a decided fact intake proposal requires decided_by and decided_at"
                )
            if self.decision == MedicalWritingFactIntakeProposalDecision.EDITED and (
                not self.edited_value
            ):
                raise ValueError(
                    "an edited fact intake proposal requires an edited_value"
                )
        return self


class MedicalWritingFactIntakeTurnKind(str, Enum):
    USER_MESSAGE = "user_message"
    AI_RESPONSE = "ai_response"
    PROPOSAL_APPLIED = "proposal_applied"
    PROPOSAL_EDITED = "proposal_edited"
    PROPOSAL_REJECTED = "proposal_rejected"


class MedicalWritingFactIntakeMessage(WorkbenchModel):
    """Every user message, AI response, proposal and user adoption/edit/
    rejection is preserved verbatim with source, version and idempotency
    identity."""

    message_id: str = Field(min_length=1, max_length=120)
    turn_kind: MedicalWritingFactIntakeTurnKind
    actor: str = Field(default="", max_length=100)
    text: str = Field(default="", max_length=20_000)
    proposals: List[MedicalWritingFactIntakeProposal] = Field(
        default_factory=list, max_length=100
    )
    questions: List[str] = Field(default_factory=list, max_length=3)
    affected_proposal_ids: List[str] = Field(default_factory=list, max_length=100)
    ai_run_id: str = Field(default="", max_length=120)
    source_ids: List[str] = Field(default_factory=list, max_length=50)
    created_at: datetime
    idempotency_key: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def normalize_fact_intake_message(self) -> "MedicalWritingFactIntakeMessage":
        self.message_id = self.message_id.strip()
        self.actor = self.actor.strip()
        self.text = self.text.strip()
        self.ai_run_id = self.ai_run_id.strip()
        self.idempotency_key = self.idempotency_key.strip()
        self.questions = [item.strip() for item in self.questions if item.strip()]
        if len(self.questions) > 3:
            raise ValueError("at most three current-turn questions are allowed")
        self.source_ids = [item.strip() for item in self.source_ids if item.strip()]
        self.affected_proposal_ids = [
            item.strip() for item in self.affected_proposal_ids if item.strip()
        ]
        return self


class MedicalWritingFactIntakeConversation(WorkbenchModel):
    """Durable, versioned conversation state for conversational fact intake.
    ``revision`` drives optimistic concurrency; ``confirmed_field_values``
    is the medical-manager-confirmed view used by downstream research and
    writing. Missing IB does not block research; it only locally blocks the
    deterministic clauses that depend on the missing fact."""

    schema_version: str = "medical_writing_fact_intake_conversation_v1"
    conversation_id: str
    project_id: str
    scope: MedicalWritingFactIntakeScope
    revision: int = Field(ge=1)
    status: Literal[
        "collecting",
        "sufficient_for_research",
        "sufficient_for_writing_candidates",
    ] = "collecting"
    messages: List[MedicalWritingFactIntakeMessage] = Field(
        default_factory=list, max_length=2000
    )
    open_proposals: List[MedicalWritingFactIntakeProposal] = Field(
        default_factory=list, max_length=200
    )
    confirmed_field_values: Dict[str, str] = Field(default_factory=dict)
    locally_blocked_clauses: List[str] = Field(default_factory=list, max_length=200)
    unresolved_high_impact_fields: List[str] = Field(
        default_factory=list, max_length=200
    )
    ai_provider: str = Field(default="", max_length=120)
    ai_model: str = Field(default="", max_length=120)
    ai_prompt_version: str = Field(default="", max_length=120)
    created_at: datetime
    updated_at: datetime
    updated_by: str

    @model_validator(mode="after")
    def normalize_fact_intake_conversation(self) -> "MedicalWritingFactIntakeConversation":
        confirmed = {
            key.strip(): value.strip()
            for key, value in self.confirmed_field_values.items()
            if str(key).strip()
        }
        self.confirmed_field_values = confirmed
        for field_name in (
            "locally_blocked_clauses",
            "unresolved_high_impact_fields",
        ):
            values = [item.strip() for item in getattr(self, field_name) if item.strip()]
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must be unique")
            setattr(self, field_name, values)
        self.schema_version = "medical_writing_fact_intake_conversation_v1"
        return self


class MedicalWritingFactIntakeConversationCreateRequest(WorkbenchModel):
    scope: MedicalWritingFactIntakeScope = MedicalWritingFactIntakeScope.STUDY_FRAMING
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def normalize_create_request(self) -> "MedicalWritingFactIntakeConversationCreateRequest":
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if not self.actor or not self.idempotency_key:
            raise ValueError(
                "fact intake conversation actor and idempotency key must not be blank"
            )
        return self


class MedicalWritingFactIntakeTurnRequest(WorkbenchModel):
    """User natural-language text for one conversational turn. DeepSeek V4
    Pro decomposes it server-side; the user then confirms, edits or rejects
    each proposal. ``expected_revision`` is the optimistic-concurrency guard."""

    expected_revision: int = Field(ge=1)
    message_text: str = Field(min_length=1, max_length=10_000)
    ib_status: Literal[
        "not_provided",
        "not_available",
        "uploaded",
        "parsed",
    ] = "not_provided"
    ib_source_ids: List[str] = Field(default_factory=list, max_length=20)
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def normalize_turn_request(self) -> "MedicalWritingFactIntakeTurnRequest":
        self.message_text = self.message_text.strip()
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        self.ib_source_ids = [item.strip() for item in self.ib_source_ids if item.strip()]
        if not self.message_text or not self.actor or not self.idempotency_key:
            raise ValueError("fact intake turn fields must not be blank")
        if self.ib_status in {"uploaded", "parsed"} and not self.ib_source_ids:
            raise ValueError("uploaded or parsed IB requires at least one source id")
        return self


class MedicalWritingFactIntakeTurnResult(WorkbenchModel):
    conversation: MedicalWritingFactIntakeConversation
    ai_message: MedicalWritingFactIntakeMessage
    proposals: List[MedicalWritingFactIntakeProposal] = Field(default_factory=list)
    questions: List[str] = Field(default_factory=list, max_length=3)
    ai_run_id: str = Field(default="", max_length=120)
    provider: str = Field(default="", max_length=120)
    model: str = Field(default="", max_length=120)
    prompt_version: str = Field(default="", max_length=120)


class MedicalWritingFactIntakeApplyDecision(WorkbenchModel):
    proposal_id: str = Field(min_length=1, max_length=120)
    action: Literal["adopt", "edit", "reject"]
    edited_value: str = Field(default="", max_length=20_000)
    note: str = Field(default="", max_length=4_000)

    @model_validator(mode="after")
    def normalize_apply_decision(self) -> "MedicalWritingFactIntakeApplyDecision":
        self.proposal_id = self.proposal_id.strip()
        self.edited_value = self.edited_value.strip()
        self.note = self.note.strip()
        if self.action == "edit" and not self.edited_value:
            raise ValueError("an edit decision requires an edited_value")
        if self.action != "edit" and self.edited_value:
            raise ValueError("only edit decisions may carry an edited_value")
        return self


class MedicalWritingFactIntakeApplyRequest(WorkbenchModel):
    """Adopt, edit or reject one or more AI proposals. A medical manager's
    explicit decision is final project-level confirmation; there is no
    second ``pending medical approval`` state."""

    expected_revision: int = Field(ge=1)
    decisions: List[MedicalWritingFactIntakeApplyDecision] = Field(
        default_factory=list, max_length=50
    )
    actor: str = Field(default="medical_manager", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def normalize_apply_request(self) -> "MedicalWritingFactIntakeApplyRequest":
        self.actor = self.actor.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if not self.actor or not self.idempotency_key:
            raise ValueError("fact intake apply fields must not be blank")
        if not self.decisions:
            raise ValueError("fact intake apply requires at least one decision")
        proposal_ids = [item.proposal_id for item in self.decisions]
        if len(proposal_ids) != len(set(proposal_ids)):
            raise ValueError("fact intake apply decisions must be unique")
        return self


class MedicalWritingFactIntakeApplyResult(WorkbenchModel):
    conversation: MedicalWritingFactIntakeConversation
    applied_messages: List[MedicalWritingFactIntakeMessage] = Field(default_factory=list)
    confirmed_field_values: Dict[str, str] = Field(default_factory=dict)
    locally_blocked_clauses: List[str] = Field(default_factory=list)


class MedicalWritingFactIntakeConflictError(ValueError):
    """Raised for duplicate, stale, or forbidden fact-intake writes."""


# ---------------------------------------------------------------------------
# Durable medical-writing job contracts (shared SQLite job engine)
# ---------------------------------------------------------------------------

DurableJobStatus = Literal[
    "queued",
    "running",
    "retry_wait",
    "completed",
    "failed",
    "cancelled",
]

DurableJobProgress = Literal[
    "queued",
    "running",
    "retry_wait",
    "completed",
    "failed",
    "cancelled",
]


class DurableJobProgressPayload(WorkbenchModel):
    phase: str = Field(default="", max_length=120)
    percent: float = Field(default=0.0, ge=0.0, le=1.0)
    step: int = Field(default=0, ge=0)
    step_total: int = Field(default=0, ge=0)
    message: str = Field(default="", max_length=4_000)


class DurableJobRequestConflict(ValueError):
    """Raised when a business key is reused with a different request hash."""


class DurableJobNotFound(KeyError):
    """Raised when a project-scoped job lookup fails (fail-closed isolation)."""


class DurableJobCreateRequest(WorkbenchModel):
    project_id: str = Field(min_length=1, max_length=200)
    job_type: str = Field(min_length=1, max_length=120)
    business_key: str = Field(min_length=1, max_length=300)
    request_hash: str = Field(min_length=8, max_length=128)
    input_hash: str = Field(default="", max_length=128)
    payload_json: str = Field(default="")
    created_by: str = Field(default="system", max_length=120)
    max_attempts: int = Field(default=3, ge=1, le=20)
    provider: str = Field(default="", max_length=120)
    model: str = Field(default="", max_length=200)


class DurableJobRecord(WorkbenchModel):
    job_id: str = Field(min_length=1, max_length=200)
    project_id: str = Field(min_length=1, max_length=200)
    job_type: str = Field(min_length=1, max_length=120)
    business_key: str = Field(min_length=1, max_length=300)
    request_hash: str = Field(min_length=8, max_length=128)
    status: DurableJobStatus
    claim_token: str = Field(default="")
    lease_expires_at: str = Field(default="")
    attempt_count: int = Field(default=1, ge=1)
    max_attempts: int = Field(default=3, ge=1, le=20)
    progress: DurableJobProgressPayload = Field(
        default_factory=DurableJobProgressPayload
    )
    error_summary: str = Field(default="", max_length=4_000)
    input_hash: str = Field(default="", max_length=128)
    output_hash: str = Field(default="", max_length=128)
    artifact_locator: str = Field(default="", max_length=2_000)
    provider: str = Field(default="", max_length=120)
    model: str = Field(default="", max_length=200)
    schema_version: int = Field(default=1, ge=1)
    payload_json: str = Field(default="")
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    created_by: str = Field(default="system", max_length=120)


class DurableJobStartResponse(WorkbenchModel):
    job_id: str = Field(min_length=1, max_length=200)
    project_id: str = Field(min_length=1, max_length=200)
    status: DurableJobStatus
    reused: bool = False


class DurableJobClaimResult(WorkbenchModel):
    claimed: bool = False
    claim_token: str = ""
    job: Optional[DurableJobRecord] = None


class DurableJobCancelResult(WorkbenchModel):
    job_id: str = Field(min_length=1, max_length=200)
    status: DurableJobStatus
    cancelled: bool = False


class DurableJobRetryResult(WorkbenchModel):
    job_id: str = Field(min_length=1, max_length=200)
    status: DurableJobStatus
    requeued: bool = False
