from __future__ import annotations

from collections import Counter
import base64
import binascii
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
from io import BytesIO
import os
from pathlib import Path
import re
from threading import Lock
from typing import Any, Mapping, Optional
from urllib.parse import quote

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from packages.contracts.workbench_contracts import (
    ApprovalAction,
    ApprovalActionRequest,
    ApprovalState,
    DashboardSummary,
    DataBatch,
    AiTaskFromRegistryRequest,
    EvidencePicosActionRequest,
    EvidencePicosHandoffRequest,
    EvidencePicosSubmitApprovalRequest,
    EvidenceAiRevisionActionRequest,
    EvidenceAiRevisionRequest,
    EvidenceReviewActionRequest,
    MedicalWritingRevisionApplyRequest,
    MedicalWritingContentDispositionRequest,
    MedicalWritingTableBatchUpdateRequest,
    MedicalWritingTableBatchUpdateResult,
    MedicalWritingGreenfieldCreateRequest,
    MedicalWritingGreenfieldDecision,
    MedicalWritingGreenfieldDecisionResolveRequest,
    MedicalWritingProtocolModuleResolution,
    MedicalWritingProtocolModuleResolutionApplyRequest,
    MedicalWritingProtocolAssemblyPlanConfirmRequest,
    MedicalWritingProtocolAssemblyPlanRefreshRequest,
    MedicalWritingTemplateUpgradeApplyRequest,
    MedicalWritingTemplateUpgradeRollbackRequest,
    MedicalWritingAuthoringJourneyCommitRequest,
    MedicalWritingAuthoringJourneyCreateRequest,
    MedicalWritingAuthoringJourneyDraftSaveRequest,
    MedicalWritingFactIntakeApplyRequest,
    MedicalWritingFactIntakeConflictError,
    MedicalWritingFactIntakeConversationCreateRequest,
    MedicalWritingFactIntakeScope,
    MedicalWritingFactIntakeTurnRequest,
    MedicalWritingStudyFraming,
    MedicalWritingStudyRebindRequest,
    MedicalWritingStudyReconciliationConfirmRequest,
    MedicalWritingStudySchemaCommitRequest,
    MedicalWritingStudySchemaImpactPreviewRequest,
    MedicalWritingStudySchemaLayoutUpdateRequest,
    MedicalWritingStudySchemaFigureProjectRequest,
    MedicalWritingInterventionRulesProjectRequest,
    MedicalWritingCompetitorSearchExecuteRequest,
    AuthoringPrefillGenerateRequest,
    AuthoringPrefillAdoptRequest,
    AuthoringPrefillCompositeAdoptRequest,
    MedicalWritingCorpusGateOverrideRequest,
    MedicalWritingCorpusTriageFinalizeRequest,
    MedicalWritingJourneyImpactPreviewRequest,
    MedicalWritingPicosCorpusAlignmentRequest,
    CompetitorTriageCreateRequest,
    CompetitorTriageRetryRequest,
    CompetitorTriageBasketConfirmationRequest,
    CompetitorTriageBasketReconfirmationRequest,
    CompetitorTriageProjectionRetryRequest,
    MedicalWritingSynopsisImportConfirmRequest,
    MedicalWritingLegacyAuthoringBootstrapPrepareRequest,
    MedicalWritingLegacyAuthoringBootstrapConfirmRequest,
    MedicalWritingSynopsisProjectCreateRequest,
    MedicalWritingWorkingCopySaveRequest,
    MedicalWritingWordVerificationSubmitRequest,
    MedicalWritingWorkingCopyBindingRecoveryRequest,
    MedicalWritingRevisionRequest,
    MedicalWritingSharedCorpusAdmissionRequest,
    MedicalWritingSharedCorpusReviewRequest,
    MedicalWritingCitationStyleUpdateRequest,
    MedicalWritingReferenceImportRequest,
    WritingReferenceDocumentIngestRequest,
    WritingReferenceManualDocumentUploadRequest,
    WritingReferenceDocumentValidationOverrideRequest,
    WritingReferenceExtractionRequest,
    WritingReferenceExtractionReviewRequest,
    WritingReferenceOcrConsistencyRecheckRequest,
    WritingReferenceOcrConsistencyBatchDispositionRequest,
    WritingReferenceAdmissionRequest,
    WritingReferenceMedicalReviewRequest,
    WritingReferenceInvalidationRequest,
    WritingReferenceRelevanceDecisionRequest,
    WritingReferenceSearchCreateRequest,
    WritingReferenceTranslationRequest,
    WritingReferenceTranslationRevisionRequest,
    ModuleStatus,
    Project,
    UserProjectCreateRequest,
    MonitoringIntakeRequest,
    RevisionActionRequest,
    RevisionAction,
    RevisionAcceptAndApplyRequest,
    RiskStatus,
    RuxRiskDispositionActionRequest,
    SafetyReviewActionRequest,
    SourceAdmissionSource,
    SourceAdmissionState,
    SourceContentValidationConfirmationRequest,
    TflReviewActionRequest,
    WorkbenchItemActionRequest,
    WorkbenchInboxResult,
)
from packages.contracts.workbench_contracts.models import (
    MedicalWritingSectionFreezeRequest,
    MedicalWritingProtocolAssemblyPlanPreviewRequest,
    MonitoringBatchConfirmFullSnapshotRequest,
    MonitoringBatchTransitionRequest,
    MonitoringBatchValidationEvidenceRequest,
    MonitoringBatchVerifyDerivedSnapshotRequest,
)
from packages.contracts.workbench_contracts.models import (
    WritingReferencePreparationBatchCreateRequest,
    WritingReferencePreparationBatchStageAdvanceRequest,
    WritingReferencePreparationBatchRetryRequest,
    WritingReferenceTranslationBatchCreateRequest,
    WritingReferenceTranslationBatchMedicalReviewRequest,
    WritingReferenceTranslationBatchMedicalReviewResult,
    WritingReferenceTranslationBatchPreviewRequest,
    WritingReferenceTranslationBatchReviewItemOutcome,
    WritingReferenceTranslationBatchRetryRequest,
    WritingReferenceTranslationDownstreamTransitionRequest,
    WritingReferenceTranslationDownstreamTransitionResult,
)

from .ai_gateway import (
    AiPromptEnvelope,
    AiTaskType,
    DIRECT_DEEPSEEK_MODEL,
    DIRECT_DEEPSEEK_TRANSLATION_SUPPORT_MODEL,
    ai_gateway_status_from_env,
    configured_ai_provider_from_env,
    direct_deepseek_env,
)
from .ai_runtime_settings import (
    AiFallbackChainUpdateRequest,
    AiFallbackRoute,
    AiProviderActivateRequest,
    AiProviderProbeRequest,
    AiProviderProfile,
    AiProviderProfileUpsertRequest,
    discover_models,
    runtime_ai_settings_store,
)
from .ai_role_runtime_settings import (
    DEFAULT_OCR_MODEL,
    INDEPENDENT_AI_ROLE,
    LOCAL_OMLX_PROFILE_ID,
    OCR_OMLX_PROFILE_ID,
    OCR_PADDLE_PROFILE_ID,
    OCR_SPECIALIZED_MODEL_ALLOWLIST,
    OCR_ROLE,
    TRANSLATION_BODY_ROLE,
    TRANSLATION_SUPPORT_ROLE,
    AiRoleBinding,
    AiRoleBindingUpsertRequest,
    ROLE_DEFINITION_BY_ID,
    runtime_ai_role_settings_store,
)
from .ai_execution_policy import AiExecutionPolicyDenied, AiExecutionPolicyResolver
from .runtime_readiness import (
    API_CONTRACT_VERSION,
    CLIENT_CONTRACT_HEADER,
    client_contract_enforcement_enabled,
    is_medical_writing_contract_path,
    runtime_readiness_report,
)
from .ai_task_runner import AiTaskRunner, AiTaskStore, public_ai_artifacts, public_ai_run
from .demo_repository import DemoRepository
from .evidence_design_manifest import EvidenceDesignManifestService, EvidencePackageAdapterError
from .evidence_ai_revision import EvidenceAiRevisionService
from .evidence_picos_workflow import (
    EvidencePicosApprovalService,
    EvidencePicosWorkflowService,
    SqliteEvidencePicosDecisionStore,
)
from .evidence_review_workflow import EvidenceReviewWorkflowService
from .eligibility import adapter as eligibility_adapter
from .eligibility import configure_eligibility_ai_workflow
from .eligibility import configure_protocol_rule_service
from .eligibility import configure_eligibility_review_workflow
from .eligibility import configure_eligibility_source_admission_guard
from .eligibility import RAW_INTAKE_PROJECTS
from .eligibility import router as eligibility_router
from app.protocol_workflow.api.composition import (
    mount_protocol_workflow_router as mount_protocol_v3_workflow_router,
)
from .eligibility_protocol_rules import (
    EligibilityProtocolProjectConfig,
    EligibilityProtocolRuleService,
)
from .eligibility_artifact_store import EligibilityArtifactStore
from .listing_file_parser import parse_listing_file
from .medical_writing import MedicalWritingRevisionService
from .medical_writing_durable_jobs import (
    DurableJobNotFound,
    DurableJobRequestConflict,
    DurableJobStore,
    DurableJobWorker,
)

from .medical_writing_research_pipeline import (
    MedicalWritingResearchPipelineService,
    ResearchPipelineConflictError,
    ResearchPipelineError,
    RESEARCH_PIPELINE_JOB_TYPE,
    authoring_writes_blocked_by_pipeline,
    authoring_write_blocker_detail,
)

logger = logging.getLogger(__name__)
from .medical_writing_chinadrugtrials_client import ChinaDrugTrialsClient
from .medical_writing_competitor_triage import CompetitorTriageExecutor
from .medical_writing import SectionAiCandidateExecutor
from .medical_writing_full_draft import (
    FULL_DRAFT_JOB_TYPE,
    MedicalWritingFullDraftService,
    ProtocolFullDraftExecutor,
)
from .writing_reference_translation_batch import TranslationBatchDurableExecutor
from .medical_writing_document import MedicalWritingDocumentService
from .medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyConflictError,
    MedicalWritingAuthoringJourneyService,
)
from .medical_writing_corpus_readiness import MedicalWritingCorpusReadinessService
from .medical_writing_competitor_triage import (
    CompetitorTriageConflictError,
    CompetitorTriageError,
    CompetitorTriageService,
    CompetitorTriageStaleError,
    TRIAGE_MODEL_NAME,
    VerifiedTriageProvider,
)
from .medical_writing_company_corpus import MedicalWritingCompanyCorpusService
from .medical_writing_shared_corpus import (
    MedicalWritingSharedCorpusConflictError,
    MedicalWritingSharedCorpusService,
)
from .medical_writing_fact_intake import (
    FACT_INTAKE_PROMPT_VERSION as MEDICAL_WRITING_FACT_INTAKE_PROMPT_VERSION,
    MedicalWritingFactIntakeService,
)
from .medical_writing_greenfield import (
    CompositeMedicalWritingDocumentService,
    GreenfieldMedicalWritingConflictError,
    GreenfieldMedicalWritingDocumentService,
)
from .medical_writing_protocol_template import (
    MedicalWritingProtocolTemplateService,
    render_assessment_instrument_methods,
)
from .medical_writing_protocol_assembly_plan import (
    MedicalWritingProtocolAssemblyPlanConflictError,
    MedicalWritingProtocolAssemblyPlanService,
)
from .medical_writing_plan_consumption import (
    MedicalWritingPlanConsumptionHelper,
    PlanConsumptionError,
    PlanUnconfirmedError,
    PlanStaleError,
    PlanUnresolvedDriverError,
    PlanProjectionMissingError,
)
from .medical_writing_style_profile import MedicalWritingStyleProfileService
from .medical_writing_template_upgrade import MedicalWritingTemplateUpgradeService
from .medical_writing_document_exporter import (
    MedicalWritingDocumentDocxExportError,
    build_medical_writing_fast_preview,
    build_medical_writing_word_verified_preview,
    document_index_catalog,
    export_medical_writing_document_docx,
    export_source_preserving_medical_writing_document_docx,
    medical_writing_document_export_snapshot_digest,
)
from .medical_writing_pdf_page_hash import (
    MAX_CANONICAL_PDF_BYTES,
    MedicalWritingPdfPageHashError,
    canonical_pdf_page_hash_manifest_sha256,
    canonical_pdf_page_hashes,
)
from .medical_writing_document_export_jobs import (
    MedicalWritingDocumentExportArtifactUnavailable,
    MedicalWritingDocumentExportCallbacks,
    MedicalWritingDocumentExportJobService,
    MedicalWritingRenderedDocument,
)
from .medical_writing_word_verification_repository import (
    MedicalWritingWordVerificationRepository,
    WordVerificationReceiptError,
    WordVerificationReceiptIdempotencyConflict,
    WordVerificationReceiptStaleError,
)
from .medical_writing_study_consistency import MedicalWritingStudyConsistencyService
from .medical_writing_legacy_authoring_migration import (
    MedicalWritingLegacyAuthoringMigrationService,
)
from .medical_writing_study_schema import (
    StudySchemaPlanConflictError,
    render_study_schema_png,
    require_plan_for_study_schema,
)
from .medical_writing_instrument_appendix import (
    DEFAULT_RENDER_DPI,
    MAX_PDF_BYTES as MAX_INSTRUMENT_APPENDIX_PDF_BYTES,
    render_instrument_pdf_appendix,
)
from .medical_writing_manifest import (
    D001_PROTOCOL_DOCX,
    MY008_PNH_3_01_PROTOCOL_DOCX,
    MedicalWritingManifestService,
    WRITING_PACKAGE_IDS_BY_PROJECT,
)
from .medical_writing_repository import MedicalWritingRuntimeRepository
from .medical_writing_intervention_rules_projection import (
    InterventionRulesProjectionConflictError,
    build_intervention_rules_projection_block,
    intervention_rules_sha256,
    merge_intervention_rules_projection_block,
)
from .medical_writing_literature import (
    LiteratureMetadataClient,
    MedicalWritingLiteratureConflictError,
    MedicalWritingLiteratureError,
    MedicalWritingLiteratureRepository,
    MedicalWritingLiteratureService,
)
from .medical_writing_synopsis_import import (
    MAX_SYNOPSIS_BYTES,
    MedicalWritingSynopsisImportService,
)
from .medical_writing_table_templates import MedicalWritingTableTemplateService
from .medical_writing_table_domain_profiles import (
    MedicalWritingTableDomainProfileService,
)
from .medical_writing_tables import (
    MedicalWritingTableError,
    MedicalWritingTableService,
    TableVersionConflictError,
)
from .medical_risk_repository import MedicalRiskRepository
from .medical_risk_identity_transition import classify_risk_identity_transition
from .medical_monitoring_router import create_medical_monitoring_router
from .medical_monitoring_summary import (
    MedicalMonitoringSummaryService,
    RiskSnapshotQueryError,
)
from .monitoring_risk_evidence import (
    capture_risk_evidence,
    frozen_evidence_payload,
    frozen_fragment,
    public_risk_payload,
)
from .writing_reference import (
    ClinicalTrialsGovClient,
    MAX_MANUAL_DOCUMENT_BYTES,
    WritingReferenceDiscoveryService,
    WritingReferenceDocumentService,
    WritingReferenceExtractionService,
)
from .writing_reference_repository import (
    WritingReferenceConflictError,
    WritingReferenceRepository,
    WritingReferenceStaleStateError,
)
from .writing_reference_preparation_batch import (
    WritingReferencePreparationBatchService,
)
from .writing_reference_ocr_consistency_service import (
    WritingReferenceOcrConsistencyService,
)
from .writing_reference_translation_batch import (
    WritingReferenceTranslationBatchService,
)
from .monitoring_project_registry import (
    MonitoringProjectCapabilityUnavailableError,
    MonitoringProjectRegistry,
)
from .monitoring_raw_intake import MonitoringRawProjectConfig, MonitoringRawProjectIntakeService
from .monitoring_intake import MonitoringIntakeService
from .monitoring_batch_repository import (
    MonitoringBatchRepository,
    MonitoringBatchRepositoryError,
)
from .monitoring_batch_service import (
    MonitoringBatchIntakeBlocked,
    MonitoringBatchService,
)
from .monitoring_batch_rule_runner import MonitoringBatchRuleRunner
from .monitoring_ai_repository import MonitoringAiRepository
from .monitoring_ai_contracts import MonitoringAiTaskType
from .monitoring_ai_risk_packet import MonitoringAiRiskPacketResolver
from .monitoring_ai_router import (
    create_monitoring_ai_router,
    current_monitoring_ai_revision,
)
from .monitoring_ai_service import (
    PROMPT_VERSION_BY_TASK,
    MonitoringAiService,
    resolve_monitoring_ai_runtime,
)
from .monitoring_ai_source_packet import MonitoringAiSourcePacketResolver
from .monitoring_ai_worker import MonitoringAiWorker
from .monitoring_mapping_draft_repository import MonitoringMappingDraftRepository
from .monitoring_mapping_activation import MonitoringMappingActivationService
from .monitoring_mapping_batch_lifecycle import (
    MonitoringMappingBatchLifecycleError,
    MonitoringMappingBatchLifecycleService,
    MonitoringMappingDifferenceReviewRequired,
    MonitoringMappingRequiredError,
)
from .monitoring_daily_run_repository import MonitoringDailyRunRepository
from .monitoring_daily_run_router import create_monitoring_daily_run_router
from .monitoring_assurance_repository import MonitoringAssuranceRepository
from .monitoring_assurance_service import (
    MonitoringAssuranceService,
    create_medical_risk_reference_reader,
)
from .monitoring_assurance_router import create_monitoring_assurance_router
from .monitoring_principal_host_adapter import (
    resolve_monitoring_principal_from_request,
)
from .monitoring_identity_authorization import (
    MonitoringAction,
    authorize_monitoring_action,
)
from .monitoring_runtime_principal import (
    MonitoringAuthenticatedPrincipal,
    MonitoringRuntimePrincipalDenied,
)
from .monitoring_runtime_route_context import (
    MonitoringRuntimeRouteContextError,
    build_monitoring_runtime_route_context,
)
from .monitoring_source_readiness import (
    resolve_monitoring_source_readiness,
    source_readiness_block_detail,
)
from .monitoring_daily_run_ai_service import MonitoringDailyRunAiService
from .monitoring_daily_run_analysis_service import MonitoringDailyRunAnalysisService
from .monitoring_daily_run_service import (
    MonitoringDailyRunService,
    MonitoringRuleRuntimeIdentity,
)
from .monitoring_protocol_rule_repository import MonitoringProtocolRuleRepository
from .monitoring_gold_case_authority import MonitoringGoldCaseAuthority
from .monitoring_protocol_rule_service import MonitoringProtocolRuleService
from .monitoring_protocol_preparation_router import (
    create_monitoring_protocol_preparation_router,
)
from .monitoring_metric_configuration_router import (
    create_monitoring_metric_configuration_router,
)
from .monitoring_protocol_preparation_service import (
    PROTOCOL_RETIREMENT_AUDIT_PROMPT_VERSIONS,
    MonitoringProtocolPreparationService,
)
from .monitoring_metric_configuration_service import (
    MonitoringMetricConfigurationService,
)
from .monitoring_rule_authoring_service import MonitoringRuleAuthoringService
from .monitoring_shadow_sample_service import MonitoringShadowSampleService
from .monitoring_rule_lifecycle_service import MonitoringRuleLifecycleService
from .monitoring_rule_template_recommendation_router import (
    create_monitoring_rule_template_recommendation_router,
)
from .monitoring_rule_template_recommendation_service import (
    MonitoringRuleTemplateRecommendationService,
)
from .mgk10_sar_monitoring_service import (
    MGK10_SAR_PROJECT_ID,
    Mgk10SarMonitoringService,
)
from .my009_monitoring_service import My009MonitoringService
from .project_source_manifest import ProjectSourceManifestService
from .user_project_store import UserProjectStore
from .rux_monitoring_service import RuxMonitoringService
from .safety_pv_manifest import (
    MY009_DSUR_DOC,
    MY009_LISTING,
    MY009_S1_ROOT,
    RUX_274_ROOT,
    RUX_PV_ROOT,
    SafetyPvManifestService,
)
from .safety_pv_review_workbench import SqliteSafetyReviewStore, SafetyReviewWorkbenchService
from .source_admission import SourceAdmissionRequired
from .source_intake import SourceRegistryService, SourceRegistryStore
from .source_content_projection import (
    SOURCE_CONTENT_PROJECTION_VERSION,
    SourceContentProjectionService,
)
from .shared_protocol_fact_projection import (
    SHARED_PROTOCOL_FACT_PROJECTION_VERSION,
    MedicalWritingProtocolFactReadAdapter,
    MonitoringProtocolFactReadAdapter,
    SharedProtocolFactProjectionService,
)
from .source_content_validation import (
    SourceContentValidationConflict,
    SourceContentValidationService,
    SourceContentValidationStore,
    SourceExpectedContext,
)
from .sqlite_runtime_store import RuntimeStoreError, SqliteRuntimeStore, StaleRuntimeStateError
from .tfl_manifest import (
    MY008_ROOT,
    RUX_DATASET_ROOT,
    RUX_TFL_SINGLE_ROOT,
    TflManifestService,
)
from .tfl_review_workbench import TflReviewStore, TflReviewWorkbenchService
from .tfl_writing_handoff import TflWritingHandoffService
from .workbench_inbox import (
    RUX_P0_SUBJECT_IDS,
    RUX_PROJECT_ID,
    WorkbenchInboxService,
    WorkbenchInboxStore,
)


PROJECT_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_DATA = PROJECT_ROOT / "demo_data" / "workbench_demo_v0_1.json"
RUNTIME_DIR = Path(
    os.environ.get("WORKBENCH_RUNTIME_DIR", str(PROJECT_ROOT / "runtime"))
).expanduser().resolve()
_WORD_VERIFICATION_REPOSITORY: Optional[MedicalWritingWordVerificationRepository] = None
_WORD_VERIFICATION_REPOSITORY_LOCK = Lock()


def _medical_writing_word_verification_repository() -> MedicalWritingWordVerificationRepository:
    global _WORD_VERIFICATION_REPOSITORY
    if _WORD_VERIFICATION_REPOSITORY is None:
        with _WORD_VERIFICATION_REPOSITORY_LOCK:
            if _WORD_VERIFICATION_REPOSITORY is None:
                _WORD_VERIFICATION_REPOSITORY = MedicalWritingWordVerificationRepository(
                    RUNTIME_DIR / "medical_writing_word_verification.sqlite3"
                )
    return _WORD_VERIFICATION_REPOSITORY


RUX_LISTING_PATH = Path(
    "/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/CFDI Inspection/准备阶段/"
    "RUX-03-002_列表_数据集_Excel_20250612_处理后.xlsx"
)
RUX_PROTOCOL_PATH = Path(
    "/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/CFDI Inspection/RUX-03-002-自查文件包-20260107/"
    "10-临床试验重要文件/1-临床试验方案/V1.3版-2024.8.14/"
    "磷酸芦可替尼乳膏-AD3期临床研究方案V1.3-clean-20240814.docx"
)
MY009_MONITORING_LISTING_PATH = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY009治疗UC/S1安全性评价-202604/"
    "MY009-UC-2-01-MM Listing_20260408(已自动还原).xlsx"
)
MY009_PROTOCOL_PATH = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY009治疗UC/方案及配套资料/3.0/"
    "MY009-UC-Ⅱa期-临床研究方案-V3.0 20250926-clean (1).docx"
)
MGK10_SAR_MONITORING_LISTING_PATH = Path(
    "/Users/smkzw/Documents/康哲项目资料/MG-K10/SAR/13. CFDI核查/自查/评分SDV/"
    "【锁库后Data Listing】MG-K10-SAR-001_FormExcelAllVersion_202601201126.xlsx"
)
MGK10_SAR_PROTOCOL_PATH = Path(
    "/Users/smkzw/Documents/康哲项目资料/MG-K10/SAR/4. Protocol/"
    "MG-K10-SAR-001_临床研究方案_ V2.1_20250919_clean版 .docx"
)

app = FastAPI(title="AI Medical Manager Workbench", version="0.1.0")
app.include_router(eligibility_router)

@app.middleware("http")
async def enforce_medical_writing_client_contract(request: Request, call_next):
    if (
        client_contract_enforcement_enabled()
        and is_medical_writing_contract_path(request.url.path, request.method)
        and request.headers.get(CLIENT_CONTRACT_HEADER) != API_CONTRACT_VERSION
    ):
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "workbench_client_contract_mismatch",
                    "message": "当前前端与医学写作服务合同不一致，请刷新或重新启动工作台。",
                    "expected_api_contract_version": API_CONTRACT_VERSION,
                }
            },
        )
    return await call_next(request)


runtime_store = SqliteRuntimeStore(
    RUNTIME_DIR / "workbench_runtime.sqlite3",
    legacy_gate_path=RUNTIME_DIR / "approval_gates.jsonl",
    legacy_decision_path=RUNTIME_DIR / "approval_decisions.jsonl",
    legacy_audit_path=RUNTIME_DIR / "approval_audit_events.jsonl",
    legacy_disposition_path=RUNTIME_DIR / "rux_risk_disposition_actions.jsonl",
)
medical_risk_repository = MedicalRiskRepository(RUNTIME_DIR / "medical_risks.sqlite3")
configure_eligibility_review_workflow(runtime_store)
repo = DemoRepository(DEFAULT_DATA, approval_store=runtime_store)
rux_monitoring_service = RuxMonitoringService(RUX_LISTING_PATH, RUX_PROTOCOL_PATH)
my009_monitoring_service = My009MonitoringService(
    MY009_MONITORING_LISTING_PATH,
    MY009_PROTOCOL_PATH,
    listing_label="MY009-UC-MM-Listing",
)
mgk10_sar_monitoring_service = Mgk10SarMonitoringService(
    MGK10_SAR_MONITORING_LISTING_PATH,
    MGK10_SAR_PROTOCOL_PATH,
)
monitoring_project_registry = MonitoringProjectRegistry()
monitoring_project_registry.register(
    RUX_PROJECT_ID,
    rux_monitoring_service,
    risk_subject_ids=RUX_P0_SUBJECT_IDS,
)
monitoring_project_registry.register("proj_my009_uc", my009_monitoring_service)
monitoring_project_registry.register(MGK10_SAR_PROJECT_ID, mgk10_sar_monitoring_service)
monitoring_protocol_rule_repository = MonitoringProtocolRuleRepository(
    RUNTIME_DIR / "monitoring_protocol_rules.sqlite3"
)


def _monitoring_rule_risk_binding_is_current(binding) -> bool:
    if not monitoring_protocol_rule_repository.has_trusted_risk_binding(binding):
        return False
    try:
        snapshot = medical_risk_repository.current_snapshot(binding.project_id)
        risks = medical_risk_repository.list_risks(
            binding.project_id,
            snapshot.snapshot_id,
        )
    except KeyError:
        return False
    return any(
        risk.risk_instance_id == binding.risk_instance_id
        and risk.project_id == binding.project_id
        for risk in risks
    )


monitoring_protocol_rule_service = MonitoringProtocolRuleService(
    monitoring_protocol_rule_repository,
    risk_binding_validator=_monitoring_rule_risk_binding_is_current,
)
monitoring_intake = MonitoringIntakeService(repo)
monitoring_raw_intake_service = MonitoringRawProjectIntakeService()
MONITORING_RAW_PROJECTS = {
    RUX_PROJECT_ID: MonitoringRawProjectConfig(
        project_id=RUX_PROJECT_ID,
        project_label="RUX-03-002 AD",
        listing_path=RUX_LISTING_PATH,
        protocol_path=RUX_PROTOCOL_PATH,
    ),
    "rux_03_002_monitoring_raw": MonitoringRawProjectConfig(
        project_id="rux_03_002_monitoring_raw",
        project_label="RUX-03-002 AD",
        listing_path=RUX_LISTING_PATH,
        protocol_path=RUX_PROTOCOL_PATH,
    ),
    "my009_uc_monitoring_raw": MonitoringRawProjectConfig(
        project_id="proj_my009_uc",
        project_label="MY009 UC",
        listing_path=MY009_MONITORING_LISTING_PATH,
        protocol_path=MY009_PROTOCOL_PATH,
    ),
    "proj_my009_uc": MonitoringRawProjectConfig(
        project_id="proj_my009_uc",
        project_label="MY009 UC",
        listing_path=MY009_MONITORING_LISTING_PATH,
        protocol_path=MY009_PROTOCOL_PATH,
    ),
    MGK10_SAR_PROJECT_ID: MonitoringRawProjectConfig(
        project_id=MGK10_SAR_PROJECT_ID,
        project_label="MG-K10-SAR",
        listing_path=MGK10_SAR_MONITORING_LISTING_PATH,
        protocol_path=MGK10_SAR_PROTOCOL_PATH,
    ),
}
ai_task_runner = AiTaskRunner(repo, AiTaskStore(RUNTIME_DIR / "ai_task_runs.jsonl"))


def _translation_ai_env():
    """Resolve the current translation-support role at call time."""
    store = runtime_ai_role_settings_store()
    try:
        store.migrate()
        binding = store.binding(TRANSLATION_SUPPORT_ROLE)
        profile = store.provider_store.profile(binding.profile_id)
        if not binding.enabled or not profile.enabled:
            raise ValueError("translation_support role is disabled")
        return store.role_env(TRANSLATION_SUPPORT_ROLE)
    except (KeyError, ValueError):
        values = direct_deepseek_env(DIRECT_DEEPSEEK_TRANSLATION_SUPPORT_MODEL)
        values.update(
            {
                "WORKBENCH_AI_PROVIDER": "disabled",
                "WORKBENCH_AI_MODEL": "not_configured",
                "WORKBENCH_AI_EXPECTED_RESPONSE_MODEL": "not_configured",
                "WORKBENCH_AI_API_KEY": "",
            }
        )
        return values


class _RoleBoundTranslationSupportPolicyResolver:
    """Refresh the support-role route before every trusted AI task."""

    @staticmethod
    def _resolver() -> AiExecutionPolicyResolver:
        values = _translation_ai_env()
        return AiExecutionPolicyResolver(
            deployment_profile=values.get("WORKBENCH_AI_DEPLOYMENT_PROFILE"),
            provider_name=values.get("WORKBENCH_AI_PROVIDER"),
            model_name=values.get("WORKBENCH_AI_MODEL"),
            transport_name=values.get("WORKBENCH_AI_TRANSPORT"),
            base_url=values.get("WORKBENCH_AI_BASE_URL"),
        )

    def resolve_registered(self, *args, **kwargs):
        return self._resolver().resolve_registered(*args, **kwargs)

    def resolve_internal(self, *args, **kwargs):
        return self._resolver().resolve_internal(*args, **kwargs)


class _GatedTranslationSupportProvider:
    def __init__(
        self,
        provider,
        *,
        use_omlx_gate: bool,
        provider_name: str = "",
        model_name: str = "",
    ) -> None:
        self._provider = provider
        self._use_omlx_gate = use_omlx_gate
        self.provider_name = getattr(provider, "provider_name", "") or provider_name
        self.model_name = getattr(provider, "model_name", "") or model_name

    def __getattr__(self, name):
        return getattr(self._provider, name)

    def run(self, envelope):
        if not self._use_omlx_gate:
            return self._provider.run(envelope)

        def _run_with_lease(lease):
            return self._provider.run(envelope)

        return run_gated_omlx_request(
            _run_with_lease,
            kind="translation",
            owner="medical-writing-api:translation-support",
        )


def _translation_support_provider():
    values = _translation_ai_env()
    # OCR/translation-support QC is a single bounded audit call.  Retrying a
    # very large mixed-OCR prompt three times can hold the preparation worker
    # for many minutes while producing no new evidence; the durable pipeline
    # records the failed/review-required outcome and can be resumed explicitly.
    provider = configured_ai_provider_from_env(values, max_attempts=1)
    use_omlx_gate = (
        values.get("WORKBENCH_AI_PROVIDER", "").strip().lower() == "omlx"
    )
    return _GatedTranslationSupportProvider(
        provider,
        use_omlx_gate=use_omlx_gate,
        provider_name=values.get("WORKBENCH_AI_PROVIDER", ""),
        model_name=values.get("WORKBENCH_AI_MODEL", ""),
    )


def _translation_ai_provider_factory(_resolution):
    return _translation_support_provider()


def _build_prefill_ai_enricher():
    """Build the production prefill adapter from the active product AI.

    Returns None when no qualified independent AI route is configured. The
    caller may keep pending decision scaffolds visible, but cannot promote
    those scaffolds to evidence-bound recommendations.
    """
    from .medical_writing_authoring_prefill_ai import build_prefill_ai_adapter
    from .medical_writing_authoring_prefill_corpus_bridge import (
        corpus_analysis_reader_for_repository,
        corpus_source_reader_for_repository,
    )

    return build_prefill_ai_adapter(
        corpus_analysis_reader=corpus_analysis_reader_for_repository(
            writing_reference_repository
        ),
        corpus_source_reader=corpus_source_reader_for_repository(
            writing_reference_repository
        ),
        provider_env=runtime_ai_role_settings_store().role_env(INDEPENDENT_AI_ROLE),
    )


translation_ai_task_runner = AiTaskRunner(
    repo,
    AiTaskStore(RUNTIME_DIR / "writing_reference_translation_ai_runs.jsonl"),
    provider_factory=_translation_ai_provider_factory,
    policy_resolver=_RoleBoundTranslationSupportPolicyResolver(),
)
eligibility_artifact_store = EligibilityArtifactStore(
    Path(
        os.environ.get(
            "WORKBENCH_ELIGIBILITY_ARTIFACT_DIR",
            RUNTIME_DIR / "eligibility_artifacts",
        )
    )
)
configure_eligibility_ai_workflow(ai_task_runner, eligibility_artifact_store)
user_project_store = UserProjectStore(RUNTIME_DIR / "user_projects.sqlite3")
project_source_manifest_service = ProjectSourceManifestService(
    PROJECT_ROOT,
    user_project_store=user_project_store,
    include_reference_projects=ProjectSourceManifestService.parse_include_reference_projects(
        os.environ.get("WORKBENCH_INCLUDE_REFERENCE_PROJECTS")
    ),
)


def _eligibility_protocol_configs_from_project_sources():
    configs = []
    for project_id in project_source_manifest_service.canonical_project_ids():
        manifest = project_source_manifest_service.build_manifest(project_id)
        try:
            binding = manifest.module_binding("eligibility_review")
        except KeyError:
            continue
        bound_source_ids = {
            *binding.primary_source_ids,
            *binding.supplemental_source_ids,
        }
        protocol_source = next(
            (
                source
                for source in manifest.sources
                if source.source_id in bound_source_ids
                and source.internal_path is not None
                and source.internal_path.suffix.lower() == ".docx"
                and "protocol" in source.source_role
            ),
            None,
        )
        if protocol_source is None:
            continue
        configs.append(
            EligibilityProtocolProjectConfig(
                project_id=manifest.project_id,
                aliases=tuple(
                    dict.fromkeys(
                        [
                            *manifest.aliases,
                            binding.route_project_id,
                        ]
                    )
                ),
                protocol_path=protocol_source.internal_path,
                source_entry=protocol_source.source_id,
                source_version=(
                    protocol_source.current_version
                    or manifest.header_project.protocol_version
                ),
            )
        )
    return tuple(configs)


configure_protocol_rule_service(
    EligibilityProtocolRuleService(
        _eligibility_protocol_configs_from_project_sources()
    )
)
source_content_validation_service = SourceContentValidationService(
    SourceContentValidationStore(RUNTIME_DIR / "source_content_validations.sqlite3")
)


def _expected_source_context(
    project_id: str,
    module: str,
    source_kind: str,
) -> SourceExpectedContext:
    header = project_source_manifest_service.build_manifest(project_id).header_project
    if source_kind == "listing_file":
        expected_role = {
            "medical_monitoring": "edc_data_listing",
            "data_analysis_tfl": "clinical_data_file",
            "safety_pv": "clinical_data_file",
            "evidence_design": "clinical_data_file",
        }.get(module, "clinical_data_file")
    else:
        expected_role = source_kind
    return SourceExpectedContext(
        project_identifiers=tuple(
            dict.fromkeys(
                value for value in (header.project_code, header.protocol_id) if value
            )
        ),
        indication_terms=(header.indication,) if header.indication else (),
        expected_file_role=expected_role,
        expected_protocol_version=header.protocol_version,
    )


source_registry = SourceRegistryService(
    SourceRegistryStore(RUNTIME_DIR / "source_registry.jsonl"),
    allowed_roots=[
        path
        for path in [
            PROJECT_ROOT,
            Path("/Users/smkzw/Documents/康哲项目资料"),
            Path("/Users/smkzw/Documents/朗来项目资料"),
            Path("/Users/smkzw/Documents/AI Cache/Codex x Hermes"),
        ]
        if path.exists()
    ],
    artifact_root=RUNTIME_DIR / "source_artifacts",
    content_validation_service=source_content_validation_service,
    expected_context_resolver=_expected_source_context,
)
source_content_projection_service = SourceContentProjectionService(
    source_registry.store
)
monitoring_batch_repository = MonitoringBatchRepository(
    RUNTIME_DIR / "medical_monitoring_batches.sqlite3",
    RUNTIME_DIR / "medical_monitoring_batch_objects",
)
monitoring_batch_service = MonitoringBatchService(
    source_registry,
    monitoring_batch_repository,
)
monitoring_metric_configuration_service = MonitoringMetricConfigurationService(
    protocol_repository=monitoring_protocol_rule_repository,
    batch_repository=monitoring_batch_repository,
)
monitoring_ai_repository = MonitoringAiRepository(
    RUNTIME_DIR / "medical_monitoring_ai.sqlite3"
)
monitoring_mapping_draft_repository = MonitoringMappingDraftRepository(
    RUNTIME_DIR / "medical_monitoring_ai.sqlite3"
)
monitoring_mapping_activation_service = MonitoringMappingActivationService(
    monitoring_mapping_draft_repository
)
monitoring_project_registry.bind_capability_resolver(
    monitoring_mapping_activation_service.require_monitoring_capability
)
monitoring_mapping_batch_lifecycle_service = (
    MonitoringMappingBatchLifecycleService(
        monitoring_batch_repository,
        monitoring_batch_service,
        monitoring_mapping_draft_repository,
        monitoring_mapping_activation_service,
    )
)
monitoring_daily_run_repository = MonitoringDailyRunRepository(
    RUNTIME_DIR / "medical_monitoring_daily_runs.sqlite3"
)
monitoring_assurance_repository = MonitoringAssuranceRepository(
    RUNTIME_DIR / "medical_monitoring_assurance.sqlite3"
)
monitoring_assurance_service = MonitoringAssuranceService(
    monitoring_assurance_repository,
    risk_reader=create_medical_risk_reference_reader(
        medical_risk_repository,
    ),
)


def _current_monitoring_rule_runtime(project_id: str) -> MonitoringRuleRuntimeIdentity:
    pack, rules = monitoring_protocol_rule_repository.current_published_pack(
        project_id,
        as_of=datetime.now(timezone.utc).date().isoformat(),
    )

    identity_digest_fields = frozenset(
        {
            "mapping_content_sha256",
            "capability_manifest_sha256",
            "effective_capabilities_sha256",
        }
    )
    identity_digest_pattern = re.compile(r"^[0-9a-f]{64}$")

    def _shared_rule_identity(attribute: str) -> str:
        # Fail closed: every rule in the published pack must carry a
        # non-empty value and all values must be identical. Empty members
        # or a mixed pack make the identity unverifiable instead of being
        # silently filtered out. Digest fields are contract bytes: do not
        # trim, case-fold or stringify them before the service validates the
        # runtime identity.
        raw_values = [getattr(rule, attribute, None) for rule in rules]
        if attribute in identity_digest_fields:
            if any(
                not isinstance(value, str)
                or identity_digest_pattern.fullmatch(value) is None
                for value in raw_values
            ):
                return ""
            values = set(raw_values)
        else:
            values = {
                str(value or "").strip()
                for value in raw_values
            }
        return values.pop() if len(values) == 1 else ""

    return MonitoringRuleRuntimeIdentity(
        rule_pack_revision=pack.rule_pack_id,
        engine_version="monitoring_protocol_rule_engine.v1",
        rule_mapping_revision=_shared_rule_identity("mapping_revision"),
        rule_mapping_content_sha256=_shared_rule_identity(
            "mapping_content_sha256"
        ),
        rule_capability_manifest_sha256=_shared_rule_identity(
            "capability_manifest_sha256"
        ),
        rule_effective_capabilities_sha256=_shared_rule_identity(
            "effective_capabilities_sha256"
        ),
    )


monitoring_daily_run_service = MonitoringDailyRunService(
    run_repository=monitoring_daily_run_repository,
    batch_repository=monitoring_batch_repository,
    batch_service=monitoring_batch_service,
    rule_runtime_resolver=_current_monitoring_rule_runtime,
    active_mapping_resolver=(
        monitoring_mapping_activation_service.get_active_mapping
    ),
    ai_runtime_resolver=resolve_monitoring_ai_runtime,
    rule_runner=MonitoringBatchRuleRunner(monitoring_protocol_rule_service),
)
monitoring_ai_source_packet_resolver = MonitoringAiSourcePacketResolver(
    source_registry
)
monitoring_ai_risk_packet_resolver = MonitoringAiRiskPacketResolver(
    medical_risk_repository,
    monitoring_project_registry,
)


def _current_monitoring_ai_revision(job):
    if job.task_type == MonitoringAiTaskType.RULE_TEMPLATE_RECOMMENDATION:
        try:
            return (
                monitoring_rule_template_recommendation_service
                .current_input_revision_sha256(job)
            )
        except (NameError, ValueError):
            return ""
    if job.task_type != MonitoringAiTaskType.LISTING_FIELD_MAPPING:
        payload = monitoring_ai_repository.input_payload(
            job.project_id,
            job.job_id,
        )
        source_ids = payload.get("source_ids")
        try:
            if isinstance(source_ids, list) and source_ids:
                return monitoring_ai_source_packet_resolver.resolve(
                    job.project_id,
                    source_ids,
                ).input_revision.revision_sha256
            risk_instance_id = payload.get("risk_instance_id")
            if isinstance(risk_instance_id, str) and risk_instance_id.strip():
                return monitoring_ai_risk_packet_resolver.resolve(
                    job.project_id,
                    risk_instance_id,
                ).input_revision.revision_sha256
            subject_context = payload.get("subject_context")
            if isinstance(subject_context, dict):
                daily_run_id = str(
                    subject_context.get("daily_run_id") or ""
                ).strip()
                if daily_run_id:
                    run = monitoring_daily_run_repository.get(
                        job.project_id,
                        daily_run_id,
                    )
                    batch = monitoring_batch_repository.load_diff_ready_batch(
                        run.batch_id
                    )
                    rule_snapshot = (
                        monitoring_daily_run_repository.get_rule_snapshot(
                            job.project_id,
                            daily_run_id,
                        )
                    )
                    if (
                        batch.project_id != run.project_id
                        or batch.version != run.batch_version
                        or batch.mapping_revision != run.mapping_revision
                        or rule_snapshot is None
                        or rule_snapshot.snapshot_id
                        != str(
                            subject_context.get("rule_snapshot_id") or ""
                        ).strip()
                        or rule_snapshot.output_sha256
                        != str(
                            subject_context.get("rule_output_sha256") or ""
                        ).strip()
                    ):
                        return ""
                    return job.input_revision_sha256
            return ""
        except (KeyError, ValueError):
            return ""
    return current_monitoring_ai_revision(
        monitoring_ai_repository,
        monitoring_batch_repository,
        job,
    )


monitoring_ai_service = MonitoringAiService(
    monitoring_ai_repository,
    current_revision_resolver=_current_monitoring_ai_revision,
)
monitoring_ai_worker = MonitoringAiWorker(
    monitoring_ai_service,
    parallelism=int(
        os.environ.get("WORKBENCH_MONITORING_AI_PARALLELISM", "4")
    ),
)
monitoring_protocol_preparation_service = MonitoringProtocolPreparationService(
    protocol_repository=monitoring_protocol_rule_repository,
    ai_repository=monitoring_ai_repository,
    ai_service=monitoring_ai_service,
    source_registry=source_registry,
    source_packet_resolver=monitoring_ai_source_packet_resolver.resolve,
    source_span_searcher=monitoring_ai_source_packet_resolver.search,
    source_context_expander=(
        monitoring_ai_source_packet_resolver.expand_protocol_context
    ),
    worker_wake=monitoring_ai_worker.wake,
)
monitoring_daily_run_ai_service = MonitoringDailyRunAiService(
    ai_service=monitoring_ai_service,
    ai_repository=monitoring_ai_repository,
)
monitoring_daily_run_analysis_service = MonitoringDailyRunAnalysisService(
    run_repository=monitoring_daily_run_repository,
    batch_repository=monitoring_batch_repository,
    ai_service=monitoring_daily_run_ai_service,
    risk_repository=medical_risk_repository,
    worker_wake=monitoring_ai_worker.wake,
)
monitoring_protocol_rule_repository.bind_gold_case_authority(
    MonitoringGoldCaseAuthority(
        source_registry.store,
        monitoring_batch_repository,
    ).validate
)
monitoring_rule_lifecycle_service = MonitoringRuleLifecycleService(
    monitoring_protocol_rule_repository
)
monitoring_rule_authoring_service = MonitoringRuleAuthoringService(
    repository=monitoring_protocol_rule_repository,
    lifecycle_service=monitoring_rule_lifecycle_service,
    protocol_rule_service=monitoring_protocol_rule_service,
    ai_repository=monitoring_ai_repository,
    source_registry=source_registry,
)
monitoring_shadow_sample_service = MonitoringShadowSampleService(
    repository=monitoring_protocol_rule_repository,
    batch_repository=monitoring_batch_repository,
    protocol_rule_service=monitoring_protocol_rule_service,
    rule_authoring_service=monitoring_rule_authoring_service,
)
monitoring_rule_template_recommendation_service = (
    MonitoringRuleTemplateRecommendationService(
        protocol_repository=monitoring_protocol_rule_repository,
        mapping_repository=monitoring_mapping_draft_repository,
        mapping_activation_service=monitoring_mapping_activation_service,
        ai_repository=monitoring_ai_repository,
        ai_service=monitoring_ai_service,
        rule_authoring_service=monitoring_rule_authoring_service,
        worker_wake=monitoring_ai_worker.wake,
    )
)
medical_writing_manifest_service = MedicalWritingManifestService()
medical_writing_source_document_service = MedicalWritingDocumentService()
# Journey first: plan service resolves StudyDefinition from journey store.
medical_writing_authoring_journey_service = MedicalWritingAuthoringJourneyService(
    RUNTIME_DIR / "medical_writing_authoring_journey.sqlite3"
)


def _current_medical_writing_study_definition(project_id: str):
    definition = medical_writing_authoring_journey_service.get(
        project_id
    ).study_definition
    if definition is None:
        raise KeyError(f"StudyDefinition not found: {project_id}")
    return definition


medical_writing_protocol_assembly_plan_service = (
    MedicalWritingProtocolAssemblyPlanService(
        RUNTIME_DIR / "medical_writing_protocol_assembly_plan.sqlite3",
        _current_medical_writing_study_definition,
    )
)
medical_writing_plan_consumption_helper = MedicalWritingPlanConsumptionHelper(
    medical_writing_protocol_assembly_plan_service
)
# Bind plan helper into journey after helper exists (serial DI; no early consumer).
medical_writing_authoring_journey_service.bind_plan_consumption_helper(
    medical_writing_plan_consumption_helper
)
medical_writing_greenfield_document_service = GreenfieldMedicalWritingDocumentService(
    RUNTIME_DIR / "medical_writing_greenfield.sqlite3",
    plan_consumption_helper=medical_writing_plan_consumption_helper,
)


def _medical_writing_fact_source_context(
    project_id: str,
    source_ids: list[str],
    query_text: str,
) -> list[dict[str, str]]:
    requested = {item.strip() for item in source_ids if item.strip()}
    if not requested:
        return []
    candidates = [
        {
            "source_id": span.source_id,
            "locator": span.locator,
            "title": span.title,
            "text": span.text_preview,
        }
        for span in source_registry.list_spans(project_id)
        if span.source_id in requested or span.entry_id in requested
    ]
    if len(candidates) <= 24:
        return candidates

    query = query_text.casefold()
    topic_groups = (
        (
            ("给药", "剂量", "用法", "用量", "途径", "制剂"),
            ("给药", "剂量", "用法", "用量", "途径", "制剂", "administration", "route", "dose", "dosage", "regimen"),
        ),
        (
            ("安全", "风险", "不良事件", "ae", "aesi", "监测"),
            ("安全", "风险", "不良事件", "严重不良事件", "特别关注", "监测", "safety", "adverse", "aesi", "toxicity"),
        ),
        (
            ("药代", "pk", "暴露", "半衰期", "药动"),
            ("药代", "药动", "暴露", "半衰期", "浓度", "pk", "pharmacokinetic", "exposure", "half-life"),
        ),
        (
            ("药效", "pd", "机制", "靶点", "生物标志物"),
            ("药效", "机制", "靶点", "生物标志物", "pd", "pharmacodynamic", "mechanism", "target", "biomarker"),
        ),
        (
            ("非临床", "毒理", "安全窗", "起始剂量"),
            ("非临床", "毒理", "安全窗", "起始剂量", "noael", "nonclinical", "toxicology", "starting dose"),
        ),
        (
            ("临床", "既往研究", "人体试验", "有效性"),
            ("临床研究", "既往研究", "人体试验", "有效性", "clinical study", "clinical trial", "efficacy"),
        ),
    )
    active_terms: set[str] = set()
    for triggers, terms in topic_groups:
        if any(trigger in query for trigger in triggers):
            active_terms.update(terms)
    if not active_terms:
        for _, terms in topic_groups:
            active_terms.update(terms)

    def relevance(item: dict[str, str]) -> tuple[int, int]:
        haystack = " ".join(
            (item.get("title", ""), item.get("locator", ""), item.get("text", ""))
        ).casefold()
        score = sum(
            3 if term in query and term in haystack else 1
            for term in active_terms
            if term in haystack
        )
        return score, -candidates.index(item)

    # Keep front-matter identity available, then fill the evidence window with
    # query-relevant IB spans. Stable ordering makes retries reproducible.
    selected = candidates[:2]
    selected_ids = {item["source_id"] for item in selected}
    for item in sorted(candidates[2:], key=relevance, reverse=True):
        if item["source_id"] in selected_ids:
            continue
        selected.append(item)
        selected_ids.add(item["source_id"])
        if len(selected) >= 24:
            break
    return selected


medical_writing_fact_intake_service = MedicalWritingFactIntakeService(
    RUNTIME_DIR / "medical_writing_fact_intake.sqlite3",
    source_context_resolver=_medical_writing_fact_source_context,
)
medical_writing_synopsis_import_service = MedicalWritingSynopsisImportService(
    RUNTIME_DIR / "medical_writing_synopsis_artifacts",
    ai_task_runner,
)
medical_writing_protocol_template_service = MedicalWritingProtocolTemplateService(
    plan_consumption_helper=medical_writing_plan_consumption_helper,
)
medical_writing_style_profile_service = MedicalWritingStyleProfileService()
medical_writing_company_corpus_service = MedicalWritingCompanyCorpusService()
medical_writing_shared_corpus_service = MedicalWritingSharedCorpusService(
    RUNTIME_DIR / "medical_writing_shared_corpus.sqlite3"
)
medical_writing_document_service = CompositeMedicalWritingDocumentService(
    medical_writing_source_document_service,
    medical_writing_greenfield_document_service,
)
medical_writing_study_consistency_service = MedicalWritingStudyConsistencyService(
    medical_writing_document_service,
    medical_writing_authoring_journey_service,
    medical_writing_greenfield_document_service,
    runtime_store,
)
medical_writing_legacy_authoring_migration_service = (
    MedicalWritingLegacyAuthoringMigrationService(
        document_service=medical_writing_document_service,
        authoring_journey_service=medical_writing_authoring_journey_service,
        synopsis_import_service=medical_writing_synopsis_import_service,
        project_metadata_resolver=lambda project_id: (
            project_source_manifest_service.build_manifest(project_id).header_project
        ),
        runtime_store=runtime_store,
    )
)
# Demo revision service shares the same plan helper as production real service.
medical_writing_revision = MedicalWritingRevisionService(
    repo,
    ai_task_runner,
    plan_consumption_helper=medical_writing_plan_consumption_helper,
)


@app.on_event("startup")
def _recover_synopsis_import_jobs():
    """Cold-recovery: detect incomplete synopsis-import jobs from a previous
    process and re-queue their chunk workers. Done chunks are never replayed."""
    try:
        medical_writing_synopsis_import_service.recover_stale_jobs()
    except Exception:
        pass  # recovery is best-effort; do not block app startup


@app.on_event("startup")
def _recover_monitoring_ai_jobs():
    """Resume queued or lease-expired medical-monitoring AI work."""
    try:
        for task_type, prompt_version in PROMPT_VERSION_BY_TASK.items():
            monitoring_ai_repository.supersede_prompt_versions_except(
                task_type=task_type,
                current_prompt_version=prompt_version,
                legacy_terminal_prompt_versions=(
                    PROTOCOL_RETIREMENT_AUDIT_PROMPT_VERSIONS
                    if task_type
                    == MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
                    else ()
                ),
            )
        monitoring_ai_repository.expire_exhausted_leases()
        monitoring_ai_worker.wake()
    except Exception:
        # Queue state is durable and remains visible for an explicit retry.
        pass


@app.on_event("startup")
def _recover_durable_mw_jobs():
    """Cold-recovery for the shared durable medical-writing job store.

    Requeues queued/retry_wait/expired-running jobs and wakes the worker for
    each recovered job that has a registered executor.  Also schedules durable
    jobs for translation batches that have pending/running/failed_retryable
    items from a prior process.
    """
    try:
        # Recovery must run through the worker after every executor has been
        # registered. The store-level helper only returns a count; it does not
        # wake any queued jobs.
        mw_durable_worker.recover()
        # Re-schedule translation batches that need durable execution.
        for pid, bid in writing_reference_translation_batch_service.recover_pending_batches():
            try:
                jid = writing_reference_translation_batch_service.ensure_reference_translation_job(
                    pid, bid, actor="durable_recovery",
                )
                if jid:
                    mw_durable_worker.wake(pid, jid)
            except Exception:
                pass  # best-effort per batch
    except Exception:
        pass  # recovery is best-effort; do not block app startup


@app.on_event("shutdown")
def _shutdown_synopsis_import_workers():
    """Signal synopsis-import workers to stop and join them."""
    try:
        medical_writing_synopsis_import_service.shutdown(timeout=10.0)
    except Exception:
        pass  # best-effort


@app.on_event("shutdown")
def _shutdown_durable_mw_worker():
    """Graceful shutdown: release this worker's exact live claims so a new
    process can reclaim immediately without waiting for lease expiry."""
    try:
        mw_durable_worker.shutdown(timeout=10.0)
    except Exception:
        pass  # best-effort


medical_writing_runtime_repository = MedicalWritingRuntimeRepository(
    medical_writing_document_service,
    runtime_store,
    medical_writing_study_consistency_service,
)
medical_writing_template_upgrade_service = MedicalWritingTemplateUpgradeService(
    medical_writing_greenfield_document_service,
    runtime_store,
    medical_writing_protocol_template_service,
    medical_writing_style_profile_service,
    medical_writing_company_corpus_service,
)
medical_writing_table_service = MedicalWritingTableService()
medical_writing_table_template_service = MedicalWritingTableTemplateService(
    plan_consumption_helper=medical_writing_plan_consumption_helper,
)
medical_writing_table_domain_profile_service = MedicalWritingTableDomainProfileService()
writing_reference_repository = WritingReferenceRepository(
    RUNTIME_DIR / "writing_reference.sqlite3"
)
medical_writing_literature_repository = MedicalWritingLiteratureRepository(
    RUNTIME_DIR / "medical_writing_literature.sqlite3"
)
medical_writing_literature_service = MedicalWritingLiteratureService(
    medical_writing_literature_repository,
    LiteratureMetadataClient(),
)
medical_writing_corpus_readiness_service = MedicalWritingCorpusReadinessService(
    medical_writing_authoring_journey_service,
    writing_reference_repository,
)
writing_reference_discovery_service = WritingReferenceDiscoveryService(
    writing_reference_repository,
    ClinicalTrialsGovClient(timeout_seconds=60, max_attempts=4),
)
writing_reference_document_service = WritingReferenceDocumentService(
    writing_reference_repository,
    ClinicalTrialsGovClient(timeout_seconds=180),
    artifact_root=RUNTIME_DIR / "writing_reference_artifacts",
)
# NOTE: writing_reference_translation_service is instantiated below, after the
# composite chapter translation pipeline is constructed, so that a single
# authoritative pipeline instance is injected into direct translation,
# revision and batch paths.
# ---------------------------------------------------------------------------
# Composite chapter-translation pipeline adapters.
# ---------------------------------------------------------------------------
# These adapters bridge the pipeline's injectable callables to the existing
# OCR gateway and OpenAI-compatible AI provider abstractions.  They never
# hardcode secrets — credentials come from the configured provider env/policy.
# If a required runtime (oMLX, DeepSeek) is unavailable, the adapter raises
# CompositePipelineUnavailableError so the batch item enters a visible
# retryable/terminal state instead of silently falling back to Flash-only.

from .chapter_translation_pipeline import (  # noqa: E402
    ChapterTranslationPipeline,
    CompositePipelineUnavailableError,
    FlashPlanResult,
    FlashQcResult,
    HyMt2TranslationResult,
    HY_MT2_MODEL_ID,
    FLASH_PLANNING_MODEL,
    FLASH_QC_MODEL,
    FLASH_PLANNING_PROMPT_VERSION,
    FLASH_QC_PROMPT_VERSION,
    HY_MT2_PROMPT_VERSION,
    WRITING_REFERENCE_OCR_MODEL,
    WRITING_REFERENCE_OCR_MIN_DPI,
    DocumentPlanValidationError,
    expand_document_plan_segment_ranges,
)
from .writing_reference_upper_layer_adapters import (  # noqa: E402
    DirectPersistentUpperLayerCallableBridge,
    PersistentUpperLayerWritingReferenceTranslationService,
    ProductionPersistedUpperLayerStageExecutorAdapter,
    RuntimeRoutedWritingReferenceUpperLayerExecutionService,
    upper_layer_prompt_resolver,
)
from .ocr_gateway import (  # noqa: E402
    LocalOcrGateway,
    OcrGatewaySettings,
    OcrResult,
    OcrRequest,
    _completion_text,
    _opaque_source_token,
    _request_payload,
    _validated_image_mime_type,
)
from .paddle_ocr_adapter import (  # noqa: E402
    PADDLE_OCR_MODEL as _PADDLE_OCR_MODEL,
    PaddleOcrAdapter,
    PaddleOcrSettings,
)
from .ocr_fallback_orchestrator import (  # noqa: E402
    GLM_FALLBACK_MODEL as _GLM_FALLBACK_MODEL,
    OcrFallbackOrchestrator,
    PROVIDER_GLM_OMLX as _PROVIDER_GLM_OMLX,
    PROVIDER_PADDLE as _PROVIDER_PADDLE,
)
from .omlx_workload_gate_client import (  # noqa: E402
    default_omlx_workload_gate_client,
    run_gated_omlx_request,
)
from hashlib import sha256 as _adapter_sha256  # noqa: E402
import json as _adapter_json  # noqa: E402
import threading as _adapter_threading  # noqa: E402


def _adapter_hash(text: str) -> str:
    return _adapter_sha256(text.encode("utf-8")).hexdigest()


def _bounded_paddle_ocr_concurrency(raw_value: str) -> int:
    """Return a safe hosted concurrency in the hard range 1..4."""
    try:
        requested = int(raw_value)
    except (TypeError, ValueError):
        return 4
    return max(1, min(4, requested))


_paddle_ocr_max_concurrency = _bounded_paddle_ocr_concurrency(
    os.environ.get("WORKBENCH_PADDLE_OCR_MAX_CONCURRENCY", "4")
)
_paddle_ocr_semaphore = _adapter_threading.BoundedSemaphore(
    _paddle_ocr_max_concurrency
)


def _runtime_role_context(role_id: str):
    store = runtime_ai_role_settings_store()
    try:
        store.migrate()
        binding = store.binding(role_id)
        profile = store.provider_store.profile(binding.profile_id)
    except KeyError as exc:
        raise CompositePipelineUnavailableError(
            f"{role_id} role binding is unavailable"
        ) from exc
    if not binding.enabled or not profile.enabled:
        raise CompositePipelineUnavailableError(
            f"{role_id} role binding is disabled"
        )
    return binding, profile, store.role_env(role_id)


def _independent_ai_profile():
    binding, profile, _ = _runtime_role_context(INDEPENDENT_AI_ROLE)
    if binding.model != profile.model:
        raise CompositePipelineUnavailableError(
            "independent_ai binding model does not match provider profile"
        )
    return profile


def _independent_ai_provider_for_profile(profile):
    """Build a frozen independent-AI provider with role-level thinking options."""

    store = runtime_ai_role_settings_store()
    binding = store.binding(INDEPENDENT_AI_ROLE)
    values = store.provider_store.profile_env(profile)
    values.update(
        {
            "WORKBENCH_AI_ROLE": INDEPENDENT_AI_ROLE,
            "WORKBENCH_AI_THINKING": binding.thinking,
            "WORKBENCH_AI_REASONING_EFFORT": binding.reasoning_effort,
        }
    )
    return configured_ai_provider_from_env(values)


_writing_reference_artifact_root = RUNTIME_DIR / "writing_reference_artifacts"
_writing_reference_artifact_root.mkdir(parents=True, exist_ok=True)


class _RoleBoundRemoteOcrGateway:
    """OpenAI-compatible OCR adapter for a role-selected remote profile."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float,
        use_omlx_gate: bool = False,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.use_omlx_gate = use_omlx_gate

    def run(self, request: OcrRequest) -> OcrResult:
        if request.image_bytes is None or request.image_suffix is None:
            raise CompositePipelineUnavailableError(
                "role-bound remote OCR requires image bytes"
            )
        import time
        import urllib.request
        from datetime import datetime, timezone

        image_bytes = request.image_bytes
        mime_type = _validated_image_mime_type(request.image_suffix, image_bytes)
        content_hash = _adapter_sha256(image_bytes).hexdigest()
        started = time.perf_counter()
        payload = _request_payload(self.model, mime_type, image_bytes)
        http_request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=_adapter_json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        def send_request(_lease=None):
            with urllib.request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                return response.read()

        try:
            response_body = (
                run_gated_omlx_request(
                    send_request,
                    kind="ocr",
                    owner="medical-writing-api:ocr",
                )
                if self.use_omlx_gate
                else send_request()
            )
            text = _completion_text(response_body)
        except Exception as exc:
            raise CompositePipelineUnavailableError(
                f"remote OCR request failed: {type(exc).__name__}"
            ) from exc
        duration_ms = (time.perf_counter() - started) * 1000
        return OcrResult(
            text=text,
            model=self.model,
            source_token=_opaque_source_token(content_hash),
            content_hash=content_hash,
            character_count=len(text),
            called_at=datetime.now(timezone.utc),
            duration_ms=duration_ms,
        )


class _PaddleFallbackOcrGateway:
    """Paddle-primary OCR gateway with oMLX GLM fallback.

    Wraps ``OcrFallbackOrchestrator`` so the existing pipeline (which expects
    ``.run(OcrRequest) -> OcrResult``) can use Paddle as the primary OCR model
    and automatically fall back to the local GLM gateway on verified Paddle
    failure.  The returned ``OcrResult`` always records the *actual* model that
    produced the text — GLM output is never labeled as Paddle.
    """

    def __init__(
        self,
        *,
        paddle_adapter: PaddleOcrAdapter,
        glm_gateway: LocalOcrGateway | _RoleBoundRemoteOcrGateway,
    ) -> None:
        self._paddle_adapter = paddle_adapter
        self._glm_gateway = glm_gateway
        self.model = _PADDLE_OCR_MODEL

    def run(self, request: OcrRequest) -> OcrResult:
        if request.image_bytes is None or request.image_suffix is None:
            raise CompositePipelineUnavailableError(
                "Paddle fallback OCR requires image bytes"
            )
        from datetime import datetime as _dt

        image_bytes = request.image_bytes
        suffix = str(request.image_suffix)
        mime_type = _validated_image_mime_type(suffix, image_bytes)

        def glm_runner(img: bytes, mt: str) -> str:
            glm_request = OcrRequest(
                image_bytes=img, image_suffix=suffix
            )
            return self._glm_gateway.run(glm_request).text

        orchestrator = OcrFallbackOrchestrator(
            paddle_adapter=self._paddle_adapter,
            glm_runner=glm_runner,
        )
        with _paddle_ocr_semaphore:
            fallback_result = orchestrator.run(image_bytes, mime_type)
        # Persist the actual model — GLM fallback is never mislabeled as Paddle.
        warnings: tuple[str, ...] = ()
        if fallback_result.fell_back:
            warnings = (fallback_result.fallback_reason,)
        return OcrResult(
            text=fallback_result.text,
            model=fallback_result.model,
            source_token=fallback_result.source_token,
            content_hash=fallback_result.content_hash,
            character_count=fallback_result.character_count,
            called_at=_dt.fromisoformat(fallback_result.called_at),
            duration_ms=fallback_result.duration_ms,
            warnings=warnings,
            provider=fallback_result.provider,
            fell_back=fallback_result.fell_back,
            primary_model=fallback_result.primary_model,
            fallback_reason=fallback_result.fallback_reason,
        )


def _build_role_bound_ocr_gateway(pinned_model: str | None = None):
    binding, profile, values = _runtime_role_context(OCR_ROLE)
    requested_model = str(pinned_model or binding.model).strip()
    if requested_model != binding.model:
        profile_id = {
            DEFAULT_OCR_MODEL: OCR_OMLX_PROFILE_ID,
            _GLM_FALLBACK_MODEL: OCR_OMLX_PROFILE_ID,
            _PADDLE_OCR_MODEL: OCR_PADDLE_PROFILE_ID,
        }.get(requested_model)
        if profile_id is None:
            raise CompositePipelineUnavailableError(
                f"OCR document-pinned model '{requested_model}' has no configured profile"
            )
        store = runtime_ai_role_settings_store()
        store.migrate()
        try:
            profile = store.provider_store.profile(profile_id)
        except KeyError as exc:
            raise CompositePipelineUnavailableError(
                f"OCR document-pinned profile '{profile_id}' is unavailable"
            ) from exc
        if not profile.enabled or profile.model != requested_model:
            raise CompositePipelineUnavailableError(
                f"OCR document-pinned profile '{profile_id}' is not ready for "
                f"model '{requested_model}'"
            )
        binding = AiRoleBinding(
            role_id=OCR_ROLE,
            profile_id=profile_id,
            model=requested_model,
            enabled=True,
            capability_status="specialized_whitelisted",
            capability_reason="document-pinned specialized OCR model",
        )
        values = store.provider_store.profile_env(profile)
    if binding.capability_status not in {
        "specialized_whitelisted",
        "visual_probe_passed",
    }:
        raise CompositePipelineUnavailableError(
            binding.capability_reason
        )
    provider = profile.provider.strip().lower()
    model = binding.model
    timeout_seconds = float(values.get("WORKBENCH_AI_TIMEOUT_SECONDS", "120"))

    # --- Paddle-primary with GLM fallback ---
    # When the OCR role is bound to the Paddle official provider, build a
    # Paddle adapter as primary and the local GLM gateway as fallback.
    # The fallback orchestrator records the actual per-page model so GLM
    # output is never mislabeled as Paddle.
    if provider == "paddle_official":
        paddle_api_key = values.get("WORKBENCH_AI_API_KEY", "").strip()
        if not paddle_api_key and profile.api_key_env:
            raise CompositePipelineUnavailableError(
                "OCR API Key is not configured for the Paddle provider"
            )
        paddle_adapter = PaddleOcrAdapter(
            PaddleOcrSettings(
                base_url=values.get("WORKBENCH_AI_BASE_URL", "")
                or "https://paddleocr.aistudio-app.com",
                api_key=paddle_api_key,
                timeout_seconds=timeout_seconds,
            )
        )
        # Build the GLM fallback gateway from the oMLX OCR profile.
        try:
            glm_gateway = _build_glm_fallback_gateway(timeout_seconds)
        except Exception:
            glm_gateway = None
        if glm_gateway is None:
            raise CompositePipelineUnavailableError(
                "Paddle OCR is primary but the GLM fallback gateway is "
                "unavailable; cannot configure Paddle-primary fallback"
            )
        return _PaddleFallbackOcrGateway(
            paddle_adapter=paddle_adapter,
            glm_gateway=glm_gateway,
        )

    if provider == "omlx" and binding.capability_status == "specialized_whitelisted":
        return LocalOcrGateway(
            OcrGatewaySettings(
                allowed_roots=(_writing_reference_artifact_root,),
                base_url=values.get("WORKBENCH_AI_BASE_URL", ""),
                model=model,
                timeout_seconds=timeout_seconds,
                api_key=values.get("WORKBENCH_AI_API_KEY", ""),
            )
        )
    if not values.get("WORKBENCH_AI_API_KEY", "").strip() and profile.api_key_env:
        raise CompositePipelineUnavailableError("OCR API Key is not configured")
    return _RoleBoundRemoteOcrGateway(
        base_url=values.get("WORKBENCH_AI_BASE_URL", ""),
        model=model,
        api_key=values.get("WORKBENCH_AI_API_KEY", ""),
        timeout_seconds=timeout_seconds,
        use_omlx_gate=provider == "omlx",
    )


def _build_glm_fallback_gateway(timeout_seconds: float = 120.0):
    """Build a LocalOcrGateway for GLM fallback from the oMLX OCR profile.

    This resolves the built-in oMLX OCR profile (``ocr_local_omlx``) and
    constructs a GLM gateway for use as the fallback target when Paddle is
    the primary OCR provider.  Returns ``None`` if the oMLX profile is not
    available.
    """
    store = runtime_ai_role_settings_store()
    store.migrate()
    profile = store.provider_store.profile(OCR_OMLX_PROFILE_ID)
    values = store.provider_store.profile_env(profile)
    return LocalOcrGateway(
        OcrGatewaySettings(
            allowed_roots=(_writing_reference_artifact_root,),
            base_url=values.get("WORKBENCH_AI_BASE_URL", ""),
            model=values.get("WORKBENCH_AI_MODEL", DEFAULT_OCR_MODEL),
            timeout_seconds=timeout_seconds,
            api_key=values.get("WORKBENCH_AI_API_KEY", ""),
        )
    )


_ocr_gateway: LocalOcrGateway | None = None
_ocr_gateway_settings: OcrGatewaySettings | None = None
try:
    _ocr_gateway = _build_role_bound_ocr_gateway()
    _ocr_gateway_settings = getattr(_ocr_gateway, "settings", None)
except Exception:
    # OCR gateway unavailable — pipeline will raise at call time.
    pass


class _OcrRunnerText(str):
    """String-compatible OCR runner result carrying page provenance."""

    def __new__(cls, result: OcrResult):
        instance = str.__new__(cls, result.text)
        instance.text = result.text
        instance.model = result.model
        instance.provider = result.provider
        instance.fell_back = result.fell_back
        instance.primary_model = result.primary_model
        instance.fallback_reason = result.fallback_reason
        return instance


def _writing_reference_ocr_runner(
    page_number: int, dpi: int, model: str, image_bytes: bytes
) -> str:
    """Bridge the pipeline OCR callable to the role-bound OCR gateway.

    Receives pre-rendered PNG bytes from the extraction service or pipeline
    (which renders pages sequentially — never sharing a PyMuPDF document
    across worker threads).  Forwards the image to the configured OCR
    gateway — either LocalOcrGateway, _RoleBoundRemoteOcrGateway, or
    _PaddleFallbackOcrGateway (Paddle primary with GLM fallback).

    Validates the exact model and minimum DPI at the product boundary.
    When the gateway is a Paddle-fallback gateway, the returned text may
    have been produced by GLM (on verified Paddle failure); the actual
    model is recorded in the OcrResult and persisted downstream.
    """
    if dpi < WRITING_REFERENCE_OCR_MIN_DPI:
        raise CompositePipelineUnavailableError(
            f"OCR DPI {dpi} is below the minimum {WRITING_REFERENCE_OCR_MIN_DPI}"
        )
    if not image_bytes or not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise CompositePipelineUnavailableError(
            "OCR runner received non-PNG image bytes"
        )
    gateway = (
        _ocr_gateway
        if _ocr_gateway is not None
        and not isinstance(
            _ocr_gateway,
            (LocalOcrGateway, _RoleBoundRemoteOcrGateway, _PaddleFallbackOcrGateway),
        )
        else _build_role_bound_ocr_gateway(model)
    )
    result = gateway.run(
        OcrRequest(image_bytes=image_bytes, image_suffix=".png")
    )
    return _OcrRunnerText(result)


def _mixed_ocr_consistency_qc_runner(
    system_prompt: str,
    user_prompt: str,
) -> dict:
    """Run one focused mixed-OCR consistency check through translation support."""
    from .ai_gateway import AiPromptEnvelope

    identity = sha256(user_prompt.encode("utf-8")).hexdigest()
    provider = _translation_support_provider()
    result = provider.run(
        AiPromptEnvelope(
            task_id=f"mixed_ocr_qc_{identity[:12]}",
            task_type=AiTaskType.REGULATORY_TRANSLATION_ZH,
            prompt_version="mixed_ocr_consistency_qc_v2_1",
            thinking="disabled",
            system_prompt=system_prompt,
            payload={
                "task_id": f"mixed_ocr_qc_{identity[:12]}",
                "document_ocr_evidence": user_prompt,
            },
        )
    )
    if not isinstance(result, dict):
        raise CompositePipelineUnavailableError(
            "mixed OCR consistency QC returned a non-object response"
        )
    return result


def _flash_planner_adapter(source_text: str, context: dict) -> FlashPlanResult:
    """Bridge Flash TOC planning to the DeepSeek provider.

    Uses the configured AI provider abstraction — never hardcodes secrets.
    Raises CompositePipelineUnavailableError if the provider is unavailable.
    """
    input_hash = _adapter_hash(source_text)
    try:
        planner_segments = tuple(context.get("_planner_segments") or ())
        if not planner_segments:
            raise CompositePipelineUnavailableError(
                "Flash planning received no deterministic segment manifest"
            )
        public_context = {
            key: value
            for key, value in context.items()
            if not str(key).startswith("_")
            and key not in {"span_ids", "source_span_ids"}
        }
        provider = _translation_support_provider()
        from .ai_gateway import AiPromptEnvelope

        task_id = f"flash_plan_{input_hash[:12]}"
        envelope = AiPromptEnvelope(
            task_id=task_id,
            task_type=AiTaskType.REGULATORY_TRANSLATION_ZH,
            prompt_version=FLASH_PLANNING_PROMPT_VERSION,
            thinking="disabled",
            system_prompt=(
                "你是临床试验方案文档结构规划器。输入是按原文顺序排列的"
                "有界结构段清单，不是需要翻译的正文。识别文档角色，并将所有"
                "结构段划分为连续、无重叠、无遗漏的章节区间。"
                "不得返回或猜测内部段落ID。仅返回JSON对象："
                "{\"document_role\":\"protocol|protocol_with_sap|sap|csr\","
                "\"chapters\":[{\"id\":\"ch_01\",\"title\":\"原文章节标题\","
                "\"ich_m11_anchor\":\"对应锚点或unmapped\","
                "\"start_segment_ordinal\":1,\"end_segment_ordinal\":3}]}。"
                "第一章必须从1开始，后一章起点必须等于前一章终点加1，"
                "最后一章必须覆盖输入中的最后一个结构段。"
                "document_context.required_top_level_segment_ordinals中的每个"
                "序号都必须作为一个章节的start_segment_ordinal。章节id和"
                "title必须分别唯一；若连续区间属于同一原文章节，应合并为"
                "一个章节，不得拆成同名章节。"
            ),
            payload={
                "task_id": task_id,
                "task_type": AiTaskType.REGULATORY_TRANSLATION_ZH.value,
                "source_text": source_text,
                "document_context": public_context,
            },
        )
        result = provider.run(envelope)
        output = result if isinstance(result, dict) else {}
        raw_chapters = output.get("chapters")
        if not isinstance(raw_chapters, list) or not raw_chapters:
            raise CompositePipelineUnavailableError(
                "Flash planning returned no chapters; output is malformed"
            )
        chapters = expand_document_plan_segment_ranges(
            raw_chapters, planner_segments
        )
        document_role = output.get("document_role")
        if not isinstance(document_role, str) or not document_role.strip():
            raise CompositePipelineUnavailableError(
                "Flash planning returned no document_role; output is malformed"
            )
    except DocumentPlanValidationError:
        raise
    except CompositePipelineUnavailableError:
        raise
    except Exception as exc:
        raise CompositePipelineUnavailableError(
            f"Flash planning provider unavailable: {type(exc).__name__}"
        ) from exc
    output_hash = _adapter_hash(
        _adapter_json.dumps(
            {"chapters": list(chapters), "role": document_role},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return FlashPlanResult(
        chapters=chapters,
        document_role=document_role,
        plan_prompt_version=FLASH_PLANNING_PROMPT_VERSION,
        plan_model=FLASH_PLANNING_MODEL,
        plan_input_hash=input_hash,
        plan_output_hash=output_hash,
    )


def _hy_mt2_translator_adapter(
    source_text: str,
    glossary: str,
    chapter_id: str,
    chunk_id: str,
    read_only_context: str = "",
    correction_note: str = "",
) -> HyMt2TranslationResult:
    """Bridge the explicitly bound body-translation role to its provider.

    oMLX requests acquire the shared translation lease, but the role binding
    remains authoritative for the selected model. Remote OpenAI-compatible
    profiles bypass the oMLX lease.

    V11: ``source_text`` arrives unit-delimited (``[[CMS_SEG_NNNN]]``
    markers).  The system prompt instructs the model to emit the same markers
    exactly once each, in order, preserve unit boundaries, and keep all
    numbers/units/comparators/citations.  The glossary contract content (not
    just the version label) is injected so the model sees the actual
    controlled terms, and only the clinical abbreviations detected by the
    product clinical-abbreviation pattern are listed for preservation —
    generic capitalization is never used as abbreviation logic.
    ``read_only_context`` is labelled separately from ``source_text`` so the
    model translates only the source block.  ``correction_note`` carries the
    exact failing unit IDs/codes for the single bounded corrective retry.
    Truncated (``finish_reason=length``) or empty output fails closed.
    """
    from .chapter_translation_pipeline import (
        format_hy_mt2_prompt_envelope,
        validate_completion_payload,
    )
    from .regulatory_translation_glossary import (
        render_preferred_abbreviation_contract,
    )
    from .writing_reference import detect_clinical_abbreviations

    user_content = format_hy_mt2_prompt_envelope(
        source_text, read_only_context=read_only_context
    )
    if correction_note:
        user_content = f"{user_content}\n\n{correction_note}"
    try:
        import urllib.request
        import urllib.error

        binding, profile, values = _runtime_role_context(TRANSLATION_BODY_ROLE)
        body_model = binding.model
        use_omlx_gate = profile.provider.strip().lower() == "omlx"
        api_key = values.get("WORKBENCH_AI_API_KEY", "") or "not-required"
        base_url = values.get("WORKBENCH_AI_BASE_URL", "").strip().rstrip("/")
        if not base_url:
            raise CompositePipelineUnavailableError(
                "translation_body role has no provider base URL"
            )
        url = f"{base_url}/chat/completions"
        system_prompt = (
            "你是临床试验方案翻译引擎。"
            "将 SOURCE_TEXT 英文方案段落翻译为自然、准确的中国监管中文。"
            "READ_ONLY_CONTEXT 仅供衔接参考，禁止翻译或复制到输出。"
            "输出必须且仅对应 SOURCE_TEXT。\n"
            "【对齐翻译单元规则】源文本已用 [[CMS_SEG_NNNN]] ... "
            "[[/CMS_SEG_NNNN]] 标记划分为有序翻译单元。你必须为每个单元输出"
            "对应的同名标记块，每个标记恰好出现一次，序号与顺序严格一致，"
            "不得合并、拆分、遗漏或重排单元。每个标记块内只输出该单元的中文"
            "译文，不得输出任何解释。\n"
            "【忠实度规则】逐单元完整翻译，禁止摘要、压缩、合并或省略任何"
            "项目符号、编号条款、表格行或事实。保持所有数字、引文标记(如(62))、"
            "单位、比较符方向(≥/≤/>/</至少/至多/不低于/不高于)、时间点与"
            "时间窗、否定关系、终点层级(主要/次要/探索性)、动作主体与给药频次"
            "不变。表格单元格内每个“•”项目符号必须在对应单元格原位逐个保留，"
            "不得改成冒号、顿号或直接删除。比较符必须与同一原文单元中紧随其后"
            "的原始数值和单位绑定；"
            "年龄下界的'≥'可表达为'周岁及以上'，但只能使用原文实际下界，"
            "不得从规则、示例或上下文引入原文不存在的年龄或阈值。"
            "'未满'/'不满'须保留排他边界语义；范围连接符(dash)译为'至'，"
            "不得改变上下界。"
            "缩略语定义单元必须严格保持“缩写 = 中文术语”的定义结构，"
            "不得补写用途、适用人群、机制、解释或其他原文没有的定义内容。"
            "每条定义必须直接输出ASCII等号字符“=”，不得用“表示、即、为、是、"
            "则是”等连接词替代；等号左侧ASCII缩写不得翻译。"
            "百分比降低定义只翻译术语并保留原百分比，"
            "不得改写成完全清除、降至零或推定的量表终点评分。"
            "Panel、Table、Figure、Section等标签后的阿拉伯编号在中文中仍须"
            "保留同一个阿拉伯数字，不得改写为中文数字。"
            "参考文献条目必须逐项保留原文的文章编号、年份、月份、日期、卷、期、"
            "完整页码范围、PMID、PMCID、DOI及Epub完整日期；不得缩短页码，"
            "不得把完整日期缩写为年份或年月，也不得省略任何原文已有书目信息。"
            "药物与治疗类别术语必须保持类别层级，不得将类别窄化为单一产品"
            "(例如 TCI 必须译为钙调神经磷酸酶抑制剂类，不得译为他克莫司软膏)。"
            "临床试验方案中的 subjects/participants 必须统一译为“受试者”；"
            "只有原文明确使用 patient/patients 时才可译为“患者”，同一源单元"
            "不得把 subjects 在前后分句中分别译为“受试者”和“患者”。"
        )
        inclusive_age_ranges = re.findall(
            r"(\d+(?:\.\d+)?)\s*(?:to|through|[\u2013\u2014-])\s*"
            r"(\d+(?:\.\d+)?)\s*years?(?:\s+old|\s+of\s+age)?"
            r"[^()\n]{0,40}\((?:both\s+included|inclusive)\)",
            source_text,
            re.IGNORECASE,
        )
        if inclusive_age_ranges:
            rendered_ranges = "；".join(
                f"{lower}至{upper}周岁（含两端值）"
                for lower, upper in inclusive_age_ranges
            )
            system_prompt += (
                "\n【本源文年龄边界】原文明确上下限均包含，必须写为："
                f"{rendered_ranges}。不得使用“{inclusive_age_ranges[0][1]}"
                "周岁以下”“未满”或其他排除上限的表达；不得把本段实际"
                "上下限用于任何其他源单元。"
            )
        # Inject only the clinical abbreviations detected by the product
        # clinical-abbreviation pattern (never generic title-case words).
        detected_abbreviations = detect_clinical_abbreviations(source_text)
        if detected_abbreviations:
            system_prompt += (
                "\n【缩写保留规则】以下临床缩写在对应源单元的译文中必须原样"
                "出现。有“缩写优选中文”映射时，写作“映射中的中文全称（缩写）”；"
                "没有映射时仅保留源缩写，不得虚构中文全称。绝对不得在译文中输出"
                "“规范中文”“原缩略语”“映射中的中文全称”等规则占位文字："
                + "、".join(detected_abbreviations)
            )
            abbreviation_contract = render_preferred_abbreviation_contract(
                detected_abbreviations
            )
            if abbreviation_contract:
                system_prompt += f"\n【缩写优选中文】\n{abbreviation_contract}"
        # Inject glossary contract content if provided (not just version).
        if glossary and "\n" in glossary:
            system_prompt += (
                "\n【受控术语表】以下 english/preferred_zh 等字段是翻译约束；"
                "输出只能使用字段值形成自然中文，不得输出字段名或规则说明。\n"
                f"{glossary}"
            )
        elif glossary:
            system_prompt += f"\n术语表版本: {glossary}"
        request_payload = {
            "model": body_model,
            "prompt_version": HY_MT2_PROMPT_VERSION,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {"role": "user", "content": user_content},
            ],
            "temperature": 0,
            "max_tokens": 4096,
        }
        # Audit the full semantic provider input.  This includes glossary,
        # read-only context and correction note, but never credentials.
        input_hash = _adapter_hash(
            _adapter_json.dumps(
                request_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        body = _adapter_json.dumps(
            {key: value for key, value in request_payload.items() if key != "prompt_version"}
        ).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        def _execute_body_translation_request(_lease=None):
            with urllib.request.urlopen(request, timeout=300) as response:
                return _adapter_json.loads(response.read().decode("utf-8"))

        result = (
            run_gated_omlx_request(
                _execute_body_translation_request,
                kind="translation",
                owner="medical-writing-api:translation-body",
            )
            if use_omlx_gate
            else _execute_body_translation_request()
        )
        # Truncated or empty output fails closed — never alignment-checked.
        translated = validate_completion_payload(result, body_model)
    except CompositePipelineUnavailableError:
        raise
    except Exception as exc:
        raise CompositePipelineUnavailableError(
            f"body translation model unavailable: {type(exc).__name__}"
        ) from exc
    translated_hash = _adapter_hash(translated)
    return HyMt2TranslationResult(
        chapter_id=chapter_id,
        chunk_id=chunk_id,
        translated_text=translated,
        translated_text_sha256=translated_hash,
        model=body_model,
        prompt_version=HY_MT2_PROMPT_VERSION,
        input_hash=input_hash,
        output_hash=translated_hash,
    )


def _flash_qc_runner_adapter(
    translated: str, source: str, correction_note: str = ""
) -> FlashQcResult:
    """Bridge non-authoring Flash integration QC to the DeepSeek provider.

    Flash may inspect chapter/chunk junctions and return structured findings,
    but it cannot author or replace Hy-MT2 body text. ``integrated_text`` is a
    legacy audit-echo field and must reproduce DRAFT_ZH exactly.
    """
    try:
        provider = _translation_support_provider()
        from .ai_gateway import AiPromptEnvelope

        system_prompt = (
            "你是中国临床试验方案译后整合与忠实度QC审核器，不是翻译器或改写器。"
            "translated_text是按 [[CMS_SEG_NNNN]] 标记划分的对齐信封："
            "每个标记块内含 SOURCE(英文原文单元)与 DRAFT_ZH(Hy-MT2中文草稿)。"
            "source_text是同一组标记块包裹的完整英文原文。逐单元对照并检查"
            "章节衔接、分块衔接与忠实度；不得翻译、改写、润色或修订DRAFT_ZH。"
            "完整保留标题层级、编号条款、项目符号、表格行列与单元格对应关系、"
            "引文标记(如(62))和章节交叉引用；逐一核对数字、单位、比较符方向、"
            "时间点/时间窗、否定关系、终点层级、动作主体、缩写及给药频次。\n"
            "【V11对齐标记规则】integrated_text必须保留全部 "
            "[[CMS_SEG_NNNN]] ... [[/CMS_SEG_NNNN]] 标记：每个标记恰好出现"
            "一次、顺序一致、每单元中文非空；标记内必须逐字回显原DRAFT_ZH，"
            "不得保留SOURCE/DRAFT_ZH标签或英文原文，不得改变任何汉字、标点、"
            "空格、换行或顺序。\n"
            "【V11对齐忠实度规则】"
            "年龄范围'≥18 years'译为'18周岁及以上'而非'至少18岁'；"
            "范围连接符(en-dash '–')译为中文'至'，不得改变上下界数字；"
            "'未满'/'不满'必须保留排他性边界语义；'满N年/月'是最短时长表述，"
            "不得丢失其下限含义；"
            "给药频次缩写(QD/BID/TID/QID/QW/Q3W等)首次出现保留缩写，"
            "不得展开为不同频次；"
            "安全术语缩写(AE/SAE/TEAE/AESI/ICF/IMP等)及混合大小写临床缩写"
            "(eCRF/eGFR/mITT/vIGA-AD等)首次出现保留缩写；"
            "药物类别术语保持类别层级，不得窄化为单一产品(如TCI不得译为"
            "他克莫司软膏)；"
            "受控术语表命中的词条必须使用指定中文译法，不得使用禁用译法。"
            "integrated_text必须始终原样回显完整Hy-MT2中文草稿(含全部标记)。"
            "若发现问题，仍须原样回显草稿并返回passed=false及具体failure_codes；"
            "failure_codes应优先采用unit_N:CODE格式，并仅报告可由对应英文原文"
            "与Hy-MT2草稿直接定位的问题；不得在integrated_text中自行修复。"
            "模型报告将作为可审计医学复核建议，只有确定性对齐门可自动硬阻断。"
            "无未解决问题时才返回passed=true。"
            "返回JSON: {passed: bool, failure_codes: [str,...], "
            "integrated_text: str}"
        )
        semantic_payload = {
            "task_type": AiTaskType.REGULATORY_TRANSLATION_ZH.value,
            "translated_text": translated,
            "source_text": source,
            **({"correction_note": correction_note} if correction_note else {}),
        }
        input_hash = _adapter_hash(
            _adapter_json.dumps(
                {
                    "model": FLASH_QC_MODEL,
                    "prompt_version": FLASH_QC_PROMPT_VERSION,
                    "thinking": "disabled",
                    "system_prompt": system_prompt,
                    "payload": semantic_payload,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        task_id = f"flash_qc_{input_hash[:12]}"
        envelope = AiPromptEnvelope(
            task_id=task_id,
            task_type=AiTaskType.REGULATORY_TRANSLATION_ZH,
            prompt_version=FLASH_QC_PROMPT_VERSION,
            thinking="disabled",
            system_prompt=system_prompt,
            payload={
                "task_id": task_id,
                **semantic_payload,
            },
        )
        result = provider.run(envelope)
        output = result if isinstance(result, dict) else {}
        if "passed" not in output:
            raise CompositePipelineUnavailableError(
                "Flash QC returned no 'passed' field; output is malformed"
            )
        passed_val = output["passed"]
        if not isinstance(passed_val, bool):
            raise CompositePipelineUnavailableError(
                "Flash QC 'passed' is not a boolean; output is malformed"
            )
        raw_codes = output.get("failure_codes", [])
        if not isinstance(raw_codes, list):
            raise CompositePipelineUnavailableError(
                "Flash QC 'failure_codes' is not a list; output is malformed"
            )
        failure_codes = tuple(str(c) for c in raw_codes)
        integrated_text = output.get("integrated_text", "")
        if not isinstance(integrated_text, str):
            raise CompositePipelineUnavailableError(
                "Flash QC 'integrated_text' is not a string; output is malformed"
            )
        if passed_val and not integrated_text.strip():
            raise CompositePipelineUnavailableError(
                "Flash QC passed without a complete integrated_text candidate"
            )
    except CompositePipelineUnavailableError:
        raise
    except Exception as exc:
        raise CompositePipelineUnavailableError(
            f"Flash QC provider unavailable: {type(exc).__name__}"
        ) from exc
    integrated_hash = _adapter_hash(integrated_text)
    return FlashQcResult(
        passed=passed_val,
        failure_codes=failure_codes,
        qc_prompt_version=FLASH_QC_PROMPT_VERSION,
        qc_model=FLASH_QC_MODEL,
        qc_input_hash=input_hash,
        qc_output_hash=integrated_hash,
        integrated_text=integrated_text,
        integrated_text_sha256=integrated_hash,
        notes="flash integration qc adapter",
    )


writing_reference_extraction_service = WritingReferenceExtractionService(
    writing_reference_repository,
    artifact_root=RUNTIME_DIR / "writing_reference_artifacts",
    ocr_runner=_writing_reference_ocr_runner,
    ocr_model=_PADDLE_OCR_MODEL,
    ocr_model_resolver=lambda: _runtime_role_context(OCR_ROLE)[0].model,
    ocr_dpi=200,
    ocr_profile="ocr-paddle-primary-v1",
    ocr_consistency_qc_runner=_mixed_ocr_consistency_qc_runner,
)
writing_reference_ocr_consistency_service = WritingReferenceOcrConsistencyService(
    writing_reference_repository,
    artifact_root=RUNTIME_DIR / "writing_reference_artifacts",
    qc_runner=_mixed_ocr_consistency_qc_runner,
)
writing_reference_upper_layer_execution_service = (
    RuntimeRoutedWritingReferenceUpperLayerExecutionService(
        writing_reference_repository,
        lambda: runtime_ai_role_settings_store().role_env(
            TRANSLATION_SUPPORT_ROLE
        ),
    )
)
_writing_reference_upper_layer_executor = (
    ProductionPersistedUpperLayerStageExecutorAdapter(
        writing_reference_upper_layer_execution_service,
        deployment_profile=runtime_ai_role_settings_store()
        .role_env(TRANSLATION_SUPPORT_ROLE)
        .get("WORKBENCH_AI_DEPLOYMENT_PROFILE", "disabled"),
        prompt_resolver=upper_layer_prompt_resolver,
    )
)
_direct_upper_layer_callable_bridge = DirectPersistentUpperLayerCallableBridge()
_chapter_translation_pipeline = ChapterTranslationPipeline(
    ocr_runner=_writing_reference_ocr_runner,
    flash_planner=_direct_upper_layer_callable_bridge.plan,
    hy_mt2_translator=_hy_mt2_translator_adapter,
    flash_qc_runner=_direct_upper_layer_callable_bridge.qc,
    ocr_model_resolver=lambda: _runtime_role_context(OCR_ROLE)[0].model,
    upper_layer_executor=_writing_reference_upper_layer_executor,
)
_direct_upper_layer_callable_bridge.bind(_chapter_translation_pipeline)
# Single authoritative translation service — composite pipeline is injected
# so direct translation, revision and batch paths all use the same
# Flash plan -> Hy-MT2 body -> Flash QC contract.  Missing pipeline/model
# runtime fails closed; the legacy Flash-only body translator is never called.
writing_reference_translation_service = (
    PersistentUpperLayerWritingReferenceTranslationService(
        writing_reference_repository,
        translation_ai_task_runner,
        chapter_pipeline=_chapter_translation_pipeline,
    )
)
writing_reference_preparation_batch_service = WritingReferencePreparationBatchService(
    writing_reference_repository,
    medical_writing_authoring_journey_service,
    writing_reference_document_service,
    writing_reference_extraction_service,
    writing_reference_ocr_consistency_service,
)
writing_reference_translation_batch_service = WritingReferenceTranslationBatchService(
    writing_reference_repository,
    medical_writing_authoring_journey_service,
    writing_reference_preparation_batch_service,
    writing_reference_translation_service,
    chapter_pipeline=_chapter_translation_pipeline,
)


@app.on_event("startup")
def _recover_writing_reference_upper_layer_escalations():
    """Resume queued or lease-expired Pro upper-layer work exactly once.

    The repository recovery query intentionally excludes ``failed_retryable``;
    those records require the explicit user retry contract rather than an
    automatic startup replay.
    """
    try:
        writing_reference_upper_layer_execution_service.resume_pending_escalations()
    except Exception:
        # Recovery is best-effort. Persisted status remains visible and
        # retryable; startup never falls back to the non-persisted legacy path.
        pass


# ---------------------------------------------------------------------------
# Durable medical-writing job composition root.
#
# One shared SQLite-backed DurableJobStore + DurableJobWorker serves all three
# long-AI job types (competitor triage, section AI candidates, reference
# translation).  The store is created before the business services so it can be
# injected at construction time.
# ---------------------------------------------------------------------------
_mw_durable_db_path = RUNTIME_DIR / "medical_writing_durable_jobs.sqlite3"
mw_durable_store = DurableJobStore(_mw_durable_db_path)
mw_durable_worker = DurableJobWorker(mw_durable_store)


def _mw_service_resolver(project_id: str):
    """Resolve the correct MedicalWritingRevisionService for a project.

    Demo projects use the simple ``medical_writing_revision`` service backed by
    the shared ``repo``.  Real (greenfield/imported) projects use
    ``real_medical_writing_revision`` backed by
    ``medical_writing_runtime_repository``.  This prevents demo and real
    projects from cross-routing AI candidates.
    """
    if (
        project_id in WRITING_PACKAGE_IDS_BY_PROJECT
        or medical_writing_greenfield_document_service.has_project(project_id)
    ):
        return real_medical_writing_revision
    return medical_writing_revision


competitor_triage_service = CompetitorTriageService(
    writing_reference_repository,
    medical_writing_authoring_journey_service,
    durable_store=mw_durable_store,
    durable_worker=mw_durable_worker,
    provider_factory=lambda: _resolve_triage_provider(),
    active_profile_resolver=_independent_ai_profile,
)

from .medical_writing_corpus_analysis_ai import (  # noqa: E402
    MedicalWritingCorpusAnalysisAiService,
)

medical_writing_corpus_analysis_ai_service = MedicalWritingCorpusAnalysisAiService(
    writing_reference_repository,
    active_profile_resolver=_independent_ai_profile,
    profile_provider_factory=_independent_ai_provider_for_profile,
)

medical_writing_research_pipeline_service = MedicalWritingResearchPipelineService(
    journey_service=medical_writing_authoring_journey_service,
    discovery_service=writing_reference_discovery_service,
    triage_service=competitor_triage_service,
    preparation_batch_service=writing_reference_preparation_batch_service,
    translation_batch_service=writing_reference_translation_batch_service,
    corpus_readiness_service=medical_writing_corpus_readiness_service,
    china_client_factory=ChinaDrugTrialsClient,
    durable_store=mw_durable_store,
    durable_worker=mw_durable_worker,
    triage_provider_factory=lambda: _resolve_triage_provider(),
    corpus_analysis_ai_service=medical_writing_corpus_analysis_ai_service,
)


real_medical_writing_revision = MedicalWritingRevisionService(
    medical_writing_runtime_repository,
    ai_task_runner,
    source_registry=source_registry,
    protocol_source_paths={
        "proj_rux_03_002": RUX_PROTOCOL_PATH,
        "proj_d001": D001_PROTOCOL_DOCX,
        "proj_my008_pnh_3_01": MY008_PNH_3_01_PROTOCOL_DOCX,
    },
    writing_reference_repository=writing_reference_repository,
    company_corpus_service=medical_writing_company_corpus_service,
    shared_corpus_service=medical_writing_shared_corpus_service,
    authoring_journey_service=medical_writing_authoring_journey_service,
    plan_consumption_helper=medical_writing_plan_consumption_helper,
)

medical_writing_full_draft_service = MedicalWritingFullDraftService(
    service_resolver=_mw_service_resolver,
    artifact_root=RUNTIME_DIR / "medical_writing_full_drafts",
)


def _protocol_v3_authoring_journey_provider(project_id: str):
    canonical_id = _canonical_module_project_id(project_id, "medical_writing")
    return medical_writing_authoring_journey_service.get(canonical_id)


def _protocol_v3_full_draft_artifact_provider(project_id: str, job_id: str):
    canonical_id = _canonical_module_project_id(project_id, "medical_writing")
    record = mw_durable_store.get(canonical_id, job_id)
    return medical_writing_full_draft_service.read_frozen_artifact(
        canonical_id, record
    )


# Protocol v3 workflow chain (Task 1R.2 + 0922V2 WP1): the default-off
# composition is mounted only after the existing authoring journey and
# full-draft services exist.  Both entry modes now share the canonical
# StudyDefinition/manuscript/Office chain; the legacy full draft is only an
# immutable candidate producer.
mount_protocol_v3_workflow_router(
    app,
    authoring_journey_provider=_protocol_v3_authoring_journey_provider,
    full_draft_artifact_provider=_protocol_v3_full_draft_artifact_provider,
)

# Attach the durable store to the translation batch service so create/retry
# create durable jobs, and register all three executors on the shared worker.
writing_reference_translation_batch_service.attach_durable_store(mw_durable_store)
mw_durable_worker.register_executor(
    TranslationBatchDurableExecutor(
        writing_reference_translation_batch_service,
        mode="pending",
    )
)
mw_durable_worker.register_executor(
    SectionAiCandidateExecutor(service_resolver=_mw_service_resolver)
)
mw_durable_worker.register_executor(
    ProtocolFullDraftExecutor(medical_writing_full_draft_service)
)
# The triage executor is registered inside CompetitorTriageService.__init__
# when durable_worker is provided.

evidence_design_manifest_service = EvidenceDesignManifestService()
evidence_picos_workflow_service = EvidencePicosWorkflowService(
    evidence_design_manifest_service,
    SqliteEvidencePicosDecisionStore(runtime_store),
)
evidence_picos_approval_service = EvidencePicosApprovalService(
    evidence_picos_workflow_service,
    runtime_store,
)
evidence_review_workflow_service = EvidenceReviewWorkflowService(
    evidence_design_manifest_service,
    runtime_store,
)
evidence_ai_revision_service = EvidenceAiRevisionService(
    evidence_design_manifest_service,
    evidence_picos_workflow_service,
    ai_task_runner,
    runtime_store,
)
tfl_manifest_service = TflManifestService()
tfl_review_store = TflReviewStore(RUNTIME_DIR / "tfl_review_actions.jsonl")
tfl_review_workbench_service = TflReviewWorkbenchService(
    tfl_manifest_service,
    tfl_review_store,
)
tfl_writing_handoff_service = TflWritingHandoffService(tfl_manifest_service, tfl_review_store)
safety_pv_manifest_service = SafetyPvManifestService()
safety_review_store = SqliteSafetyReviewStore(
    runtime_store,
    legacy_path=RUNTIME_DIR / "safety_review_actions.jsonl",
)
safety_review_workbench_service = SafetyReviewWorkbenchService(safety_pv_manifest_service, safety_review_store)
def _rux_dashboard_summary() -> DashboardSummary:
    base = _source_manifest_dashboard(RUX_PROJECT_ID)
    latest_batch = DataBatch(
        batch_id="rux_03_002_listing_20250612",
        project_id=RUX_PROJECT_ID,
        batch_label="RUX-03-002 原始数据 listing 2025-06-12",
        extract_date="2025-06-12",
        uploaded_by="medical_manager",
        status="real_source_qc_slice",
        source_file_ids=["tfl-rux-listing"],
        row_count=rux_monitoring_service.listing_row_count(),
        subject_count=len(rux_monitoring_service.subject_ids()),
        site_count=len(rux_monitoring_service.site_ids()),
        created_at=datetime(2025, 6, 12, tzinfo=timezone.utc),
    )
    return _monitoring_dashboard_from_snapshot(base, latest_batch=latest_batch)


def _my009_dashboard_summary() -> DashboardSummary:
    project_id = "proj_my009_uc"
    base = _source_manifest_dashboard(project_id)
    latest_batch = DataBatch(
        batch_id="my009_uc_listing_20260408",
        project_id=project_id,
        batch_label="MY009-UC 原始数据 listing 2026-04-08",
        extract_date="2026-04-08",
        uploaded_by="medical_manager",
        status="first_batch_no_previous_baseline",
        source_file_ids=["my009_mm_listing_20260408"],
        previous_batch_id=None,
        row_count=my009_monitoring_service.listing_row_count(),
        subject_count=len(my009_monitoring_service.subject_ids()),
        site_count=len(my009_monitoring_service.site_ids()),
        created_at=datetime(2026, 4, 8, tzinfo=timezone.utc),
    )
    return _monitoring_dashboard_from_snapshot(base, latest_batch=latest_batch)


def _canonical_project_id(project_id: str) -> str:
    try:
        return project_source_manifest_service.canonical_project_id(project_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")


def _canonical_module_project_id(project_id: str, module: str) -> str:
    canonical_id = _canonical_project_id(project_id)
    try:
        project_source_manifest_service.module_binding(canonical_id, module)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"{module} not configured for project: {canonical_id}")
    return canonical_id


def _legacy_monitoring_source_route(
    action: MonitoringAction,
    request_id: str,
) -> bool:
    """Identify legacy routes that require an activated monitoring binding."""

    return request_id.startswith(("legacy-monitoring-", "legacy-rux-")) or action in {
        MonitoringAction.READ_MONITORING,
        MonitoringAction.CHANGE_RISK_DISPOSITION,
        MonitoringAction.INTAKE_BATCH,
        MonitoringAction.RUN_DETERMINISTIC_RULES,
        MonitoringAction.REVIEW_AI_CANDIDATE,
        MonitoringAction.DRAFT_QUERY,
        MonitoringAction.CREATE_ASSURANCE_TASK,
        MonitoringAction.RECORD_ASSURANCE_EVIDENCE,
        MonitoringAction.REVIEW_ASSURANCE,
        MonitoringAction.COMPLETE_ASSURANCE,
        MonitoringAction.CONFIRM_HIGH_RISK_CLOSE,
        MonitoringAction.CONFIRM_DERIVED_DATA,
    }


def _ensure_legacy_monitoring_source_ready(
    project_id: str,
    *,
    operation: str,
) -> None:
    """Block legacy monitoring routes until their manifest is activated."""

    try:
        canonical_id = project_source_manifest_service.canonical_project_id(project_id)
        binding = project_source_manifest_service.module_binding(
            canonical_id,
            "medical_monitoring",
        )
    except KeyError:
        # Projects without a monitoring binding retain their existing
        # not-configured/registry response instead of receiving a fabricated
        # readiness state.
        return
    readiness = resolve_monitoring_source_readiness(binding)
    if readiness is None or readiness.can_read:
        return
    raise HTTPException(
        status_code=409,
        detail=source_readiness_block_detail(
            canonical_id,
            readiness,
            operation=operation,
        ),
    )


def _authorize_legacy_monitoring_action(
    http_request: Request,
    project_id: str,
    *,
    request_id: str,
    action: MonitoringAction,
    write: bool = False,
    high_risk: bool = False,
    reauthenticated: bool = False,
    signature_evidence_sha256: str = "",
) -> str:
    """Authorize legacy monitoring endpoints from the host principal only."""

    principal = resolve_monitoring_principal_from_request(http_request)
    if not isinstance(principal, MonitoringAuthenticatedPrincipal):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "monitoring_principal_unavailable",
                "message": (
                    "服务器验证身份尚未接入，旧版医学监查写入已阻断。"
                    if write
                    else "服务器验证身份尚未接入，旧版医学监查读取已阻断。"
                ),
            },
        )
    try:
        route_context = build_monitoring_runtime_route_context(
            principal,
            request_id=request_id,
            route_project_id=project_id,
            tenant_id=principal.tenant_id,
            target_scope="trial",
            action=action,
            high_risk=high_risk,
            reauthenticated=reauthenticated,
            signature_evidence_sha256=signature_evidence_sha256,
        )
        decision = authorize_monitoring_action(
            route_context.principal.to_monitoring_principal(
                now=route_context.validated_at,
            ),
            route_context.request,
        )
    except MonitoringRuntimePrincipalDenied as exc:
        status = (
            401
            if exc.reason_code
            in {
                "principal_not_authenticated",
                "principal_not_yet_valid",
                "principal_expired",
            }
            else 403
        )
        raise HTTPException(
            status_code=status,
            detail={
                "code": f"monitoring_{exc.reason_code}",
                "message": (
                    "服务器验证身份不满足旧版医学监查写入条件。"
                    if write
                    else "服务器验证身份不满足旧版医学监查读取条件。"
                ),
            },
        ) from exc
    except MonitoringRuntimeRouteContextError as exc:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "monitoring_route_context_invalid",
                "message": (
                    "旧版医学监查路由身份上下文无效，写入已阻断。"
                    if write
                    else "旧版医学监查路由身份上下文无效，读取已阻断。"
                ),
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "monitoring_authorization_request_invalid",
                "message": (
                    "旧版医学监查授权请求无效，写入已阻断。"
                    if write
                    else "旧版医学监查授权请求无效，读取已阻断。"
                ),
            },
        ) from exc
    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "code": f"monitoring_{decision.reason.value}",
                "message": (
                    "服务器身份无权写入旧版医学监查数据。"
                    if write
                    else "服务器身份无权读取旧版医学监查数据。"
                ),
            },
        )
    if _legacy_monitoring_source_route(action, request_id):
        _ensure_legacy_monitoring_source_ready(
            project_id,
            operation="write" if write else "read",
        )
    return principal.server_actor


def _reject_legacy_monitoring_policy_gap(
    http_request: Request,
    project_id: str,
    *,
    request_id: str,
    read_action: MonitoringAction = MonitoringAction.READ_MONITORING,
) -> None:
    """Authenticate/scope-check, then block a route with no exact write action."""

    _authorize_legacy_monitoring_action(
        http_request,
        project_id,
        request_id=request_id,
        action=read_action,
    )
    raise HTTPException(
        status_code=403,
        detail={
            "code": "monitoring_write_action_unconfigured",
            "message": "当前旧版医学监查写入动作尚未配置显式权限，写入已阻断。",
        },
    )


def _reject_legacy_monitoring_read_policy_gap(
    http_request: Request,
    project_id: str,
    *,
    request_id: str,
    read_action: MonitoringAction = MonitoringAction.READ_MONITORING,
) -> None:
    """Authenticate/scope-check, then block a composite read with no exact action."""

    _authorize_legacy_monitoring_action(
        http_request,
        project_id,
        request_id=request_id,
        action=read_action,
    )
    raise HTTPException(
        status_code=403,
        detail={
            "code": "monitoring_read_action_unconfigured",
            "message": "当前复合医学监查读取动作尚未配置显式权限，读取已阻断。",
        },
    )


def _safe_docx_filename(value: str) -> str:
    cleaned = "".join(
        "_" if character in {'/', '\\', ':', '"'} or ord(character) < 32 else character
        for character in value
    ).strip(" .")
    if not cleaned.lower().endswith(".docx"):
        cleaned = f"{cleaned}.docx"
    if len(cleaned) > 180:
        cleaned = f"{cleaned[:-5][:175]}.docx"
    return cleaned or "medical-writing.docx"


def _study_schema_figure_body_order(project_id: str, section_id: str) -> int:
    document = medical_writing_runtime_repository.protocol(project_id)
    target_index = next(
        index
        for index, section in enumerate(document.sections)
        if section.section_id == section_id
    )
    target_orders = [
        block.get("body_order")
        for block in document.sections[target_index].content_blocks
        if isinstance(block.get("body_order"), int)
        and not isinstance(block.get("body_order"), bool)
    ]
    if target_orders:
        return max(target_orders)
    previous_orders = [
        block.get("body_order")
        for section in document.sections[:target_index]
        for block in section.content_blocks
        if isinstance(block.get("body_order"), int)
        and not isinstance(block.get("body_order"), bool)
    ]
    return max(previous_orders, default=-1)


def _medical_writing_services(project_id: str):
    if (
        project_id in WRITING_PACKAGE_IDS_BY_PROJECT
        or medical_writing_greenfield_document_service.has_project(project_id)
    ):
        return real_medical_writing_revision, medical_writing_runtime_repository
    return medical_writing_revision, repo


# The demo repository is the only intentionally retained consumer of the
# pre-atomic revision endpoints.  Real and greenfield projects must use the
# single accept-and-apply transaction so an author selection cannot be
# persisted separately from the working-copy write.
LEGACY_MEDICAL_WRITING_ROUTE_PROJECT_IDS = frozenset({"proj_mgk10_sar_demo"})


def _require_atomic_medical_writing_route(project_id: str) -> None:
    if project_id not in LEGACY_MEDICAL_WRITING_ROUTE_PROJECT_IDS:
        raise HTTPException(
            status_code=410,
            detail=(
                "legacy medical-writing accept/apply routes are retired for real projects; "
                "use the atomic accept-and-apply endpoint"
            ),
        )


def _approval_target_module(target_type: str) -> str:
    if target_type == "evidence_picos_snapshot":
        return "evidence_design"
    for prefix, module in (
        ("medical_writing", "medical_writing"),
        ("medical_monitoring", "medical_monitoring"),
        ("eligibility", "eligibility_review"),
        ("data_analysis_tfl", "data_analysis_tfl"),
        ("safety_pv", "safety_pv"),
    ):
        if target_type.startswith(prefix):
            return module
    return "approvals"


def _is_retired_medical_writing_approval(approval) -> bool:
    return approval.target_type in {
        "medical_writing_revision_thread",
        "medical_writing_working_copy",
    }


def _source_manifest_dashboard(project_id: str) -> DashboardSummary:
    manifest = project_source_manifest_service.build_manifest(project_id)
    header = manifest.header_project
    generated_at = datetime.now(timezone.utc)
    try:
        created_at = datetime.fromisoformat(header.protocol_date).replace(tzinfo=timezone.utc)
    except ValueError:
        created_at = generated_at
    project = Project(
        **header.public_dict(),
        created_at=created_at,
        updated_at=generated_at,
    )
    pending_approvals = [
        approval
        for approval in repo.approvals(project_id)
        if approval.state.value in {"ai_draft", "in_medical_review", "returned_for_revision"}
        and not _is_retired_medical_writing_approval(approval)
    ]
    approval_counts = Counter(
        _approval_target_module(approval.target_type) for approval in pending_approvals
    )
    modules = [
        ModuleStatus(
            module=binding.module,
            label=binding.label,
            status=binding.implementation_status,
            completion_rate=0.35 if binding.implementation_status == "real_source_slice" else 0.1,
            open_risk_count=0,
            pending_task_count=0,
            pending_approval_count=approval_counts.get(binding.module, 0),
        )
        for binding in manifest.modules
    ]
    return DashboardSummary(
        project=project,
        modules=modules,
        latest_batch=None,
        risk_counts_by_severity={},
        pending_approvals=pending_approvals,
        recent_risks=[],
    )


def _monitoring_dashboard_from_snapshot(
    base: DashboardSummary,
    *,
    latest_batch: DataBatch | None,
) -> DashboardSummary:
    """Overlay the dashboard with the same persisted monitoring authority as the module."""

    project_id = base.project.project_id
    summary = medical_monitoring_summary_service.module_summary(project_id)
    try:
        snapshot = medical_risk_repository.current_snapshot(project_id)
        risks = medical_risk_repository.list_risks(
            project_id,
            snapshot.snapshot_id,
        )
    except KeyError:
        risks = []
    open_risks = [
        risk
        for risk in risks
        if risk.status not in {RiskStatus.CLOSED, RiskStatus.SUPERSEDED}
    ]
    severity_counts = Counter(risk.severity.value for risk in open_risks)
    modules = [
        module.model_copy(
            update={
                "open_risk_count": int(summary["open_risk_count"]),
                "pending_task_count": int(summary["needs_action_count"]),
            }
        )
        if module.module == "medical_monitoring"
        else module
        for module in base.modules
    ]
    return base.model_copy(
        update={
            "modules": modules,
            "latest_batch": latest_batch,
            "risk_counts_by_severity": dict(severity_counts),
            "recent_risks": sorted(
                open_risks,
                key=lambda item: item.created_at,
                reverse=True,
            )[:10],
        }
    )


SOURCE_REGISTRY_CANDIDATES: Mapping[str, Mapping[str, object]] = {
    "ev-crs-trial-design": {
        "kind": "local-file",
        "module": "evidence_design",
        "project_ids": {"proj_mgk10_crswnp"},
        "path": Path("/Users/smkzw/Documents/康哲项目资料/竞品调研/CRSwNP/00_Master_Database/Trial_Design.csv"),
    },
    "ev-crs-efficacy": {
        "kind": "local-file",
        "module": "evidence_design",
        "project_ids": {"proj_mgk10_crswnp"},
        "path": Path("/Users/smkzw/Documents/康哲项目资料/竞品调研/CRSwNP/00_Master_Database/Efficacy_Result.csv"),
    },
    "ev-crs-safety": {
        "kind": "local-file",
        "module": "evidence_design",
        "project_ids": {"proj_mgk10_crswnp"},
        "path": Path("/Users/smkzw/Documents/康哲项目资料/竞品调研/CRSwNP/00_Master_Database/Safety_Result.csv"),
    },
    "ev-crs-document-index": {
        "kind": "local-file",
        "module": "evidence_design",
        "project_ids": {"proj_mgk10_crswnp"},
        "path": Path("/Users/smkzw/Documents/康哲项目资料/竞品调研/CRSwNP/00_Master_Database/Document_Index.csv"),
    },
    "tfl-rux-listing": {
        "kind": "local-file",
        "module": "data_analysis_tfl",
        "project_ids": {"proj_rux_03_002"},
        "path": Path("/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/CFDI Inspection/准备阶段/RUX-03-002_列表_数据集_Excel_20250612_处理后.xlsx"),
    },
    "tfl-rux-sdtm-package": {
        "kind": "local-directory",
        "module": "data_analysis_tfl",
        "project_ids": {"proj_rux_03_002"},
        "source_kind": "tfl_dataset_package_inventory",
        "path": RUX_DATASET_ROOT,
    },
    "tfl-rux-final-tfl": {
        "kind": "local-directory",
        "module": "data_analysis_tfl",
        "project_ids": {"proj_rux_03_002"},
        "source_kind": "tfl_output_package_inventory",
        "path": RUX_TFL_SINGLE_ROOT,
    },
    "tfl-my008-dataset-package": {
        "kind": "local-directory",
        "module": "data_analysis_tfl",
        "project_ids": {"proj_my008_pnh_3_01"},
        "source_kind": "tfl_dataset_package_inventory",
        "path": MY008_ROOT,
    },
    "tfl-my008-output-package": {
        "kind": "local-directory",
        "module": "data_analysis_tfl",
        "project_ids": {"proj_my008_pnh_3_01"},
        "source_kind": "tfl_output_package_inventory",
        "path": MY008_ROOT / "tlf",
    },
    "pv-my009-mm-listing": {
        "kind": "local-file",
        "module": "safety_pv",
        "project_ids": {"proj_my009_uc"},
        "source_kind": "safety_medical_review_listing",
        "path": MY009_LISTING,
    },
    "pv-my009-safety-package": {
        "kind": "local-directory",
        "module": "safety_pv",
        "project_ids": {"proj_my009_uc"},
        "source_kind": "safety_signal_package_inventory",
        "path": MY009_S1_ROOT,
    },
    "pv-my009-dsur": {
        "kind": "local-file",
        "module": "safety_pv",
        "project_ids": {"proj_my009_uc"},
        "source_kind": "dsur_source_document",
        "path": MY009_DSUR_DOC,
    },
    "pv-rux-pv-plan": {
        "kind": "local-directory",
        "module": "safety_pv",
        "project_ids": {"proj_rux_03_002"},
        "source_kind": "pv_safety_package_inventory",
        "path": RUX_PV_ROOT,
    },
    "pv-rux-mm-listing": {
        "kind": "local-file",
        "module": "safety_pv",
        "project_ids": {"proj_rux_03_002"},
        "source_kind": "safety_medical_review_listing",
        "path": RUX_LISTING_PATH,
    },
    "pv-rux-274": {
        "kind": "local-directory",
        "module": "safety_pv",
        "project_ids": {"proj_rux_03_002"},
        "source_kind": "clinical_safety_summary_inventory",
        "path": RUX_274_ROOT,
    },
}

SOURCE_ADMISSION_REQUIREMENTS = {
    ("data_analysis_tfl", "proj_rux_03_002", "rux_03_002"): (
        ("analysis_dataset_package", "分析数据集包", "tfl-rux-sdtm-package"),
        ("tfl_output_package", "TFL输出包", "tfl-rux-final-tfl"),
    ),
    ("data_analysis_tfl", "proj_my008_pnh_3_01", "my008_pnh_3_01"): (
        ("analysis_dataset_package", "分析数据集包", "tfl-my008-dataset-package"),
        ("tfl_output_package", "TFL输出包", "tfl-my008-output-package"),
    ),
    ("safety_pv", "proj_my009_uc", "my009_uc_s1"): (
        ("safety_analysis_listing", "安全性分析listing", "pv-my009-mm-listing"),
        ("safety_evaluation_package", "安全性评估资料包", "pv-my009-safety-package"),
        ("dsur_source_document", "DSUR来源文档", "pv-my009-dsur"),
    ),
    ("safety_pv", "proj_rux_03_002", "rux_03_002_pv"): (
        ("safety_analysis_listing", "安全性分析listing", "pv-rux-mm-listing"),
        ("pv_plan_package", "PV计划资料包", "pv-rux-pv-plan"),
        ("clinical_safety_summary_package", "临床安全性总结资料包", "pv-rux-274"),
    ),
}

_SOURCE_CANDIDATE_REGISTRATION_CACHE = {}
_SOURCE_CANDIDATE_REGISTRATION_LOCK = Lock()


def _local_file_candidate_fingerprint(project_id: str, module: str, candidate_id: str, candidate) -> tuple:
    path = Path(candidate["path"]).expanduser().resolve(strict=True)
    stat = path.stat()
    return (
        project_id,
        module,
        candidate_id,
        str(path),
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
        str(candidate.get("source_kind") or ""),
    )


def _register_source_candidate(project_id: str, module: str, candidate_id: str):
    candidate = SOURCE_REGISTRY_CANDIDATES[candidate_id]
    if module != str(candidate["module"]) or project_id not in candidate.get("project_ids", set()):
        raise ValueError(f"来源候选与项目或模块不一致: {candidate_id}")
    if candidate["kind"] == "local-file":
        fingerprint = _local_file_candidate_fingerprint(project_id, module, candidate_id, candidate)
        cache_id = (project_id, module, candidate_id)
        with _SOURCE_CANDIDATE_REGISTRATION_LOCK:
            cached = _SOURCE_CANDIDATE_REGISTRATION_CACHE.get(cache_id)
            if cached is not None and cached[0] == fingerprint:
                return cached[1]
            source_kind = str(candidate.get("source_kind") or "")
            reusable_resolver = getattr(source_registry, "reusable_local_file_registration", None)
            result = (
                reusable_resolver(
                    project_id,
                    candidate["path"],
                    module=module,
                    expected_file_role=source_kind,
                )
                if callable(reusable_resolver)
                else None
            )
            if result is None:
                result = source_registry.register_local_file(
                    project_id,
                    candidate["path"],
                    module=module,
                    expected_file_role=source_kind,
                )
            _SOURCE_CANDIDATE_REGISTRATION_CACHE[cache_id] = (fingerprint, result)
            return result
    return source_registry.register_local_directory(
        project_id,
        candidate["path"],
        module=module,
        source_kind=str(candidate.get("source_kind") or "file_bundle_inventory"),
    )


def _refresh_module_source_admission(
    project_id: str,
    module: str,
    scope_id: str,
) -> SourceAdmissionState:
    requirements = SOURCE_ADMISSION_REQUIREMENTS.get((module, project_id, scope_id), ())
    sources = []
    missing_roles = []
    if not requirements:
        missing_roles.append("来源配置")
    for source_role_code, source_role, candidate_id in requirements:
        try:
            result = _register_source_candidate(project_id, module, candidate_id)
            validation = source_registry.current_content_validation(project_id, result.entry.entry_id)
        except (KeyError, ValueError, FileNotFoundError, NotADirectoryError):
            missing_roles.append(source_role)
            continue
        if validation is None:
            missing_roles.append(source_role)
            continue
        sources.append(
            SourceAdmissionSource(
                source_role_code=source_role_code,
                source_role=source_role,
                source_entry_id=result.entry.entry_id,
                validation_id=validation.validation_id,
                revision=validation.revision,
                validator_version=validation.validator_version,
                technical_status=validation.technical_status,
                content_status=validation.content_status,
                use_status=validation.use_status,
                public_title=result.entry.public_title,
                summary=validation.summary,
                checks=validation.checks,
                confirmation_reason=validation.confirmation_reason,
                confirmation_actor=validation.actor if validation.confirmation_reason else "",
                confirmed_at=validation.created_at if validation.confirmation_reason else None,
            )
        )
    return SourceAdmissionState(
        project_id=project_id,
        module=module,
        scope_id=scope_id,
        sources=sources,
        missing_source_roles=missing_roles,
        ready_for_use=(
            bool(requirements)
            and not missing_roles
            and len(sources) == len(requirements)
            and all(
                source.use_status in {"allowed", "confirmed_after_warning"}
                for source in sources
            )
        ),
    )


def _tfl_source_admission(project_id: str, package_id: str) -> SourceAdmissionState:
    return _refresh_module_source_admission(project_id, "data_analysis_tfl", package_id)


def _safety_source_admission(project_id: str, package_id: str) -> SourceAdmissionState:
    return _refresh_module_source_admission(project_id, "safety_pv", package_id)


tfl_review_workbench_service.source_admission_resolver = _tfl_source_admission
tfl_writing_handoff_service.source_admission_resolver = _tfl_source_admission
safety_review_workbench_service.source_admission_resolver = _safety_source_admission
MONITORING_QUERY_WORKFLOW_POLICIES = {
    "proj_rux_03_002": {
        "internal_approval_required": True,
        "formal_send_managed_outside_monitoring": True,
    },
    "proj_my009_uc": {
        "internal_approval_required": True,
        "formal_send_managed_outside_monitoring": True,
    },
    MGK10_SAR_PROJECT_ID: {
        "internal_approval_required": True,
        "formal_send_managed_outside_monitoring": True,
    },
}

workbench_inbox_service = WorkbenchInboxService(
    repo,
    ai_task_runner,
    evidence_picos_workflow_service,
    tfl_writing_handoff_service,
    safety_review_workbench_service,
    medical_writing_manifest_service,
    source_registry,
    eligibility_adapter,
    WorkbenchInboxStore(RUNTIME_DIR / "workbench_inbox_actions.jsonl"),
    rux_monitoring_service=rux_monitoring_service,
    rux_disposition_store=runtime_store,
    monitoring_services=monitoring_project_registry.as_mapping(),
    project_source_manifest_service=project_source_manifest_service,
    medical_risk_repository=medical_risk_repository,
    notifications_path=RUNTIME_DIR / "notifications" / "workbench_notifications.jsonl",
    monitoring_query_workflow_policies=MONITORING_QUERY_WORKFLOW_POLICIES,
)
shared_protocol_fact_projection_service = SharedProtocolFactProjectionService(
    (
        MonitoringProtocolFactReadAdapter(
            monitoring_protocol_rule_repository
        ),
        MedicalWritingProtocolFactReadAdapter(
            medical_writing_authoring_journey_service
        ),
    )
)
medical_monitoring_summary_service = MedicalMonitoringSummaryService(
    risk_repository=medical_risk_repository,
    project_source_manifest_service=project_source_manifest_service,
    workbench_inbox_service=workbench_inbox_service,
    monitoring_registry=monitoring_project_registry,
)
app.include_router(
    create_medical_monitoring_router(
        risk_repository=medical_risk_repository,
        batch_repository=monitoring_batch_repository,
        batch_service=monitoring_batch_service,
        project_source_manifest_service=project_source_manifest_service,
        workbench_inbox_service=workbench_inbox_service,
        monitoring_registry=monitoring_project_registry,
        protocol_rule_service=monitoring_protocol_rule_service,
        protocol_rule_authoring_service=monitoring_rule_authoring_service,
        protocol_rule_shadow_sample_service=monitoring_shadow_sample_service,
        principal_resolver=resolve_monitoring_principal_from_request,
        require_server_principal=True,
    )
)
app.include_router(
    create_monitoring_daily_run_router(
        repository=monitoring_daily_run_repository,
        service=monitoring_daily_run_service,
        analysis_service=monitoring_daily_run_analysis_service,
        project_resolver=lambda project_id: _canonical_module_project_id(
            project_id,
            "medical_monitoring",
        ),
        principal_resolver=resolve_monitoring_principal_from_request,
        require_server_principal=True,
    )
)
app.include_router(
    create_monitoring_assurance_router(
        repository=monitoring_assurance_repository,
        service=monitoring_assurance_service,
        project_resolver=lambda project_id: _canonical_module_project_id(
            project_id,
            "medical_monitoring",
        ),
        # The host seam only reads a verified principal from request.state.
        # Until an upstream session middleware populates that state, assurance
        # writes remain fail-closed rather than falling back to a client actor.
        principal_resolver=resolve_monitoring_principal_from_request,
        require_server_principal=True,
    )
)
app.include_router(
    create_monitoring_protocol_preparation_router(
        service=monitoring_protocol_preparation_service,
        project_resolver=lambda project_id: _canonical_module_project_id(
            project_id,
            "medical_monitoring",
        ),
        principal_resolver=resolve_monitoring_principal_from_request,
        require_server_principal=True,
    )
)
app.include_router(
    create_monitoring_metric_configuration_router(
        service=monitoring_metric_configuration_service,
        project_resolver=lambda project_id: _canonical_module_project_id(
            project_id,
            "medical_monitoring",
        ),
        principal_resolver=resolve_monitoring_principal_from_request,
        require_server_principal=True,
    )
)
app.include_router(
    create_monitoring_rule_template_recommendation_router(
        service=monitoring_rule_template_recommendation_service,
        project_resolver=lambda project_id: _canonical_module_project_id(
            project_id,
            "medical_monitoring",
        ),
        principal_resolver=resolve_monitoring_principal_from_request,
        require_server_principal=True,
    )
)
app.include_router(
    create_monitoring_ai_router(
        repository=monitoring_ai_repository,
        service=monitoring_ai_service,
        batch_repository=monitoring_batch_repository,
        mapping_repository=monitoring_mapping_draft_repository,
        mapping_activation_service=monitoring_mapping_activation_service,
        source_packet_resolver=monitoring_ai_source_packet_resolver.resolve,
        risk_packet_resolver=monitoring_ai_risk_packet_resolver.resolve,
        worker_wake=monitoring_ai_worker.wake,
        project_resolver=lambda project_id: _canonical_module_project_id(
            project_id,
            "medical_monitoring",
        ),
        principal_resolver=resolve_monitoring_principal_from_request,
        require_server_principal=True,
    )
)
safety_review_workbench_service.monitoring_collaboration_resolver = (
    workbench_inbox_service.safety_monitoring_collaboration_handoffs
)


def _ai_role_payload_with_execution_status() -> dict:
    store = runtime_ai_role_settings_store()
    payload = store.public_payload()
    profiles = {
        profile.profile_id: profile for profile in store.provider_store.profiles()
    }
    try:
        gate_status = default_omlx_workload_gate_client().status()
        gate_status.pop("db", None)
        gate_error = ""
    except Exception as exc:
        gate_status = {
            "limits": {"ocr": 8, "translation": 8, "total": 16},
            "gate_contract": "shared_sqlite_ocr8_translation8_total16_v1",
        }
        gate_error = f"workload gate unavailable: {type(exc).__name__}"

    roles = []
    for item in payload["roles"]:
        role = dict(item)
        role_id = role["role_id"]
        profile = profiles.get(role.get("profile_id", ""))
        provider = profile.provider if profile is not None else ""
        role_configured = bool(
            profile is not None and role.get("enabled") and profile.enabled
        )
        inventory_available = (
            role.get("model") in role.get("available_models", [])
            if role.get("requires_local_inventory")
            else None
        )
        execution_chain_wired = True
        workload_gate_required = provider == "omlx" and role_id in {
            OCR_ROLE, TRANSLATION_BODY_ROLE, TRANSLATION_SUPPORT_ROLE
        }
        current_runnable = bool(
            role.get("ready") and role_configured
            and not (workload_gate_required and gate_error)
        )
        execution_blocked_reason = str(role.get("blocked_reason") or "")
        if workload_gate_required and gate_error and not execution_blocked_reason:
            execution_blocked_reason = "本地 OCR/翻译服务状态暂不可用，请稍后重新检查。"

        role.update(
            {
                "provider": provider,
                "role_configured": role_configured,
                "inventory_available": inventory_available,
                "execution_binding_consumed": execution_chain_wired,
                "execution_chain_wired": execution_chain_wired,
                "current_runnable": current_runnable,
                "execution_blocked_reason": execution_blocked_reason,
                "workload_gate_required": workload_gate_required,
            }
        )
        roles.append(role)
    return {
        **payload,
        "roles": roles,
        "omlx_workload_gate": {
            **gate_status,
            "ready": not gate_error,
            "blocked_reason": gate_error,
        },
    }


def _combined_ai_settings_with_execution_status() -> dict:
    provider_payload = runtime_ai_settings_store().public_payload()
    role_status = _ai_role_payload_with_execution_status()
    return {
        **provider_payload,
        "role_schema_version": role_status["role_schema_version"],
        "role_revision": role_status["role_revision"],
        "roles": role_status["roles"],
        "local_model_inventories": role_status["local_model_inventories"],
        "local_inventory_errors": role_status["local_inventory_errors"],
        "omlx_workload_gate": role_status["omlx_workload_gate"],
    }


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "data_exists": DEFAULT_DATA.exists(),
        "runtime_store": runtime_store.health_report(),
        "medical_writing_shared_corpus": medical_writing_shared_corpus_service.health_report(),
    }


@app.get("/api/runtime-readiness")
def runtime_readiness():
    report = runtime_readiness_report(
        app.routes,
        runtime_health=runtime_store.health_report(),
        ai_status=ai_gateway_status_from_env(),
    )
    return JSONResponse(status_code=200 if report["ready"] else 503, content=report)


@app.get("/api/ai-gateway/status")
def ai_gateway_status():
    return ai_gateway_status_from_env()


@app.get("/api/ai-gateway/settings")
def ai_gateway_settings():
    return _combined_ai_settings_with_execution_status()


@app.get("/api/ai-gateway/roles/status")
def ai_gateway_role_status():
    return _ai_role_payload_with_execution_status()


@app.put("/api/ai-gateway/profiles/{profile_id}")
def upsert_ai_gateway_profile(
    profile_id: str,
    request: AiProviderProfileUpsertRequest,
):
    if profile_id != request.profile_id:
        raise HTTPException(status_code=422, detail="profile_id path/body mismatch")
    store = runtime_ai_settings_store()
    try:
        current = store.profile(profile_id)
        revision = current.revision + 1
    except KeyError:
        revision = 1
    profile = AiProviderProfile(
        profile_id=request.profile_id,
        provider=request.provider,
        label=request.label,
        base_url=request.base_url.rstrip("/"),
        model=request.model,
        transport=request.transport,
        deployment_profile=request.deployment_profile,
        timeout_seconds=request.timeout_seconds,
        expected_response_model=request.expected_response_model or request.model,
        api_key_env=request.api_key_env,
        deployment_scope=request.deployment_scope,
        discovery_mode=request.discovery_mode,
        enabled=request.enabled,
        revision=revision,
        thinking=request.thinking,
        reasoning_effort=request.reasoning_effort,
    )
    store.upsert(profile, api_key=request.api_key, activate=request.activate)
    if request.activate:
        runtime_ai_role_settings_store().sync_independent_from_active()
    return {
        **_combined_ai_settings_with_execution_status(),
        "status": ai_gateway_status_from_env(),
    }


@app.post("/api/ai-gateway/active-profile")
def activate_ai_gateway_profile(request: AiProviderActivateRequest):
    store = runtime_ai_settings_store()
    try:
        store.activate(request.profile_id)
        runtime_ai_role_settings_store().sync_independent_from_active()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="AI profile not found") from exc
    return {
        **_combined_ai_settings_with_execution_status(),
        "status": ai_gateway_status_from_env(),
    }


@app.put("/api/ai-gateway/fallback-chain")
def update_ai_gateway_fallback_chain(request: AiFallbackChainUpdateRequest):
    store = runtime_ai_settings_store()
    try:
        store.set_fallback_chain(
            AiFallbackRoute(**item) for item in request.routes
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="fallback AI profile not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        **_combined_ai_settings_with_execution_status(),
        "status": ai_gateway_status_from_env(),
    }


@app.put("/api/ai-gateway/roles/{role_id}")
def bind_ai_gateway_role(
    role_id: str,
    request: AiRoleBindingUpsertRequest,
):
    store = runtime_ai_role_settings_store()
    try:
        store.upsert(
            AiRoleBinding(
                role_id=role_id,
                profile_id=request.profile_id,
                model=request.model,
                enabled=request.enabled,
                thinking=request.thinking,
                reasoning_effort=request.reasoning_effort,
            )
        )
    except KeyError as exc:
        detail = (
            "AI role not found"
            if role_id not in ROLE_DEFINITION_BY_ID
            else "AI profile not found"
        )
        raise HTTPException(status_code=404, detail=detail) from exc
    except (RiskSnapshotQueryError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        **_combined_ai_settings_with_execution_status(),
        "status": ai_gateway_status_from_env(),
    }


@app.post("/api/ai-gateway/probe")
def probe_ai_gateway_profile(request: AiProviderProbeRequest):
    store = runtime_ai_settings_store()
    try:
        profile = store.profile(request.profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="AI profile not found") from exc
    provider = configured_ai_provider_from_env(store.profile_env(profile))
    if getattr(provider, "model_name", "") in {"", "not_configured"}:
        raise HTTPException(status_code=422, detail="AI profile is incomplete")
    started = datetime.now(timezone.utc)
    try:
        result = provider.run(
            AiPromptEnvelope(
                task_id=f"ai_probe_{sha256(profile.profile_id.encode()).hexdigest()[:12]}",
                task_type=AiTaskType.PROTOCOL_DESIGN_SYNTHESIS,
                prompt_version="ai_provider_connectivity_probe_v1",
                system_prompt=(
                    "Return one JSON object only. This is a synthetic connectivity "
                    "and structured-output probe; do not infer medical content."
                ),
                payload={
                    "probe": "cms_medical_writing_independent_ai",
                    "required_response": {"status": "ok"},
                },
            )
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"AI profile probe failed: {type(exc).__name__}: {exc}",
        ) from exc
    elapsed_ms = int(
        (datetime.now(timezone.utc) - started).total_seconds() * 1000
    )
    if not isinstance(result, dict) or result.get("status") != "ok":
        raise HTTPException(
            status_code=502,
            detail="AI profile probe returned an unexpected structured response",
        )
    return {
        "passed": True,
        "profile_id": profile.profile_id,
        "provider": getattr(provider, "provider_name", profile.provider),
        "model": getattr(provider, "model_name", profile.model),
        "response_model": getattr(provider, "response_model", ""),
        "elapsed_ms": elapsed_ms,
        "structured_output": result,
    }


@app.post("/api/ai-gateway/roles/ocr/probe-visual")
def probe_ocr_role_visual_capability(request: AiProviderProbeRequest):
    """Verify a non-specialized OCR role with a real image request.

    Connectivity or a model-name guess is not sufficient: the selected
    OpenAI-compatible endpoint must read a fixed token from a generated PNG.
    The persisted proof is bound to the exact role profile and model.
    """
    from PIL import Image, ImageDraw, ImageFont

    store = runtime_ai_role_settings_store()
    try:
        binding = store.binding(OCR_ROLE)
        profile = store.provider_store.profile(binding.profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="OCR 角色连接不存在") from exc
    requested_model = request.model or binding.model
    if (
        request.profile_id != binding.profile_id
        or requested_model != binding.model
    ):
        raise HTTPException(
            status_code=409,
            detail="OCR 角色配置已变化，请刷新后重新验证视觉能力",
        )

    token = "CMS VISION 7429"
    canvas = Image.new("RGB", (760, 190), "white")
    draw = ImageDraw.Draw(canvas)
    font = None
    for candidate in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ):
        try:
            font = ImageFont.truetype(candidate, 54)
            break
        except OSError:
            continue
    font = font or ImageFont.load_default()
    draw.text((42, 58), token, fill="black", font=font)
    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    values = store.role_env(OCR_ROLE)
    if profile.provider.strip().lower() == "paddle_official":
        gateway = _build_role_bound_ocr_gateway()
    else:
        # A general vision model reaches this endpoint precisely because it
        # has not passed the visual probe yet, so it cannot use the normal
        # runtime builder's ready-only gate.
        gateway = _RoleBoundRemoteOcrGateway(
            base_url=values.get("WORKBENCH_AI_BASE_URL", ""),
            model=binding.model,
            api_key=values.get("WORKBENCH_AI_API_KEY", ""),
            timeout_seconds=float(
                values.get("WORKBENCH_AI_TIMEOUT_SECONDS", "120")
            ),
            use_omlx_gate=profile.provider.strip().lower() == "omlx",
        )

    def run_probe(_lease=None):
        return gateway.run(
            OcrRequest(image_bytes=buffer.getvalue(), image_suffix=".png")
        )

    try:
        result = run_probe()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"OCR 视觉能力验证失败：{type(exc).__name__}",
        ) from exc
    if (
        profile.provider.strip().lower() == "paddle_official"
        and result.fell_back
    ):
        raise HTTPException(
            status_code=502,
            detail="PaddleOCR 视觉验证失败；本次结果来自 GLM-OCR 回退，不能用于证明 PaddleOCR 可用",
        )

    normalized = re.sub(r"[^A-Z0-9]+", " ", result.text.upper()).strip()
    if not all(part in normalized.split() for part in ("CMS", "VISION", "7429")):
        raise HTTPException(
            status_code=502,
            detail="模型已响应，但未能准确读取图像校验码",
        )
    store.record_ocr_visual_probe(
        profile_id=binding.profile_id,
        model=binding.model,
    )
    return {
        **_combined_ai_settings_with_execution_status(),
        "visual_probe": {
            "passed": True,
            "profile_id": binding.profile_id,
            "model": binding.model,
            "provider": result.provider or profile.provider,
            "elapsed_ms": round(result.duration_ms),
        },
    }


@app.post("/api/ai-gateway/discover-models")
def discover_ai_gateway_models(request: AiProviderProbeRequest):
    store = runtime_ai_settings_store()
    try:
        profile = store.profile(request.profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="AI profile not found") from exc
    api_key = store.credentials.get(profile.profile_id) or os.environ.get(
        profile.api_key_env, ""
    )
    try:
        models = discover_models(profile, api_key)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "profile_id": profile.profile_id,
        "provider": profile.provider,
        "models": models,
        "configured_model_present": (
            (request.model or profile.model) in models if models else None
        ),
    }


@app.get("/api/medical-writing/reference-translation/ai-status")
def writing_reference_translation_ai_status():
    role_payload = _ai_role_payload_with_execution_status()
    roles = {item["role_id"]: item for item in role_payload["roles"]}
    body_role = roles[TRANSLATION_BODY_ROLE]
    support_role = roles[TRANSLATION_SUPPORT_ROLE]
    ocr_role = roles[OCR_ROLE]
    support_status = ai_gateway_status_from_env(_translation_ai_env())
    return {
        **support_status,
        "task_type": "regulatory_protocol_translation_zh",
        "runtime_scope": "medical_writing_reference_translation",
        "audit_store": "dedicated",
        "translation_support_role": [
            "toc_and_chapter_planning",
            "post_hy_mt2_integration_qc",
            "corpus_selection_support",
        ],
        "deepseek_role": [
            "toc_and_chapter_planning",
            "post_hy_mt2_integration_qc",
            "corpus_selection_support",
        ],
        "ocr": ocr_role,
        "translation_body": body_role,
        "translation_support": support_role,
        "body_translation_model": body_role["model"],
        # Preserve the legacy public label while exposing the role-scoped
        # profile id inside ``translation_body``.
        "body_translation_provider": (
            LOCAL_OMLX_PROFILE_ID
            if body_role["provider"] == "omlx"
            else body_role["profile_id"]
        ),
        "body_translation_provider_type": body_role["provider"],
        "body_translation_runnable": body_role["current_runnable"],
        "support_model": support_role["model"],
        "support_provider": support_role["profile_id"],
        "support_provider_type": support_role["provider"],
        "support_runnable": support_role["current_runnable"],
        "execution_chain_wired": all(
            roles[role_id]["execution_chain_wired"]
            for role_id in (
                OCR_ROLE,
                TRANSLATION_BODY_ROLE,
                TRANSLATION_SUPPORT_ROLE,
            )
        ),
        "currently_runnable": all(
            roles[role_id]["current_runnable"]
            for role_id in (
                OCR_ROLE,
                TRANSLATION_BODY_ROLE,
                TRANSLATION_SUPPORT_ROLE,
            )
        ),
        "omlx_workload_gate": role_payload["omlx_workload_gate"],
        "deepseek_body_translation_allowed": False,
    }


@app.get("/api/projects")
def list_projects():
    return project_source_manifest_service.list_public_projects()


@app.post("/api/projects", status_code=201)
def create_project(request: UserProjectCreateRequest):
    try:
        record = user_project_store.create(request)
        # Auto-admit new projects into the Protocol v3 workflow allowlist
        # (T04/P0#2): without the row the writing workspace's source intake
        # 404s and the prepare button stays permanently disabled.
        try:
            from .protocol_workflow.api.composition import (
                admit_protocol_workflow_project,
            )

            admit_protocol_workflow_project(record.project_id)
        except Exception:
            pass  # best-effort; the workflow surface reports its own state
        authoring_entry_mode = (
            "synopsis_import" if record.entry_mode == "synopsis_import" else "guided_greenfield"
        )
        journey = medical_writing_authoring_journey_service.create(
            record.project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                entry_mode=authoring_entry_mode,
                framing=MedicalWritingStudyFraming(
                    protocol_id=record.protocol_id,
                    version=record.protocol_version or "草案",
                    document_title=record.project_name,
                    indication=record.indication,
                    study_phase=record.study_phase,
                    investigational_product=record.product_name,
                ),
                actor=request.actor,
                idempotency_key=f"project-bootstrap-{request.idempotency_key}"[:200],
            ),
        )
        project = project_source_manifest_service.build_manifest(record.project_id).public_project_dict()
        return {
            "project": project,
            "entry_mode": record.entry_mode,
            "next_route": f"/api/projects/{record.project_id}/medical-writing/authoring-journey",
            "authoring_journey": journey.model_dump(mode="json"),
        }
    except MedicalWritingAuthoringJourneyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/api/projects/{project_id}/dashboard")
def get_dashboard(project_id: str, http_request: Request):
    canonical_id = _canonical_project_id(project_id)
    if not project_source_manifest_service.is_user_created_project(canonical_id):
        _reject_legacy_monitoring_read_policy_gap(
            http_request,
            canonical_id,
            request_id=f"legacy-dashboard-read-gap:{canonical_id}",
        )
    if canonical_id == RUX_PROJECT_ID:
        if not RUX_LISTING_PATH.exists() or not RUX_PROTOCOL_PATH.exists():
            raise HTTPException(status_code=404, detail="RUX source files are not available in the configured local source registry")
        return _rux_dashboard_summary().model_dump(mode="json")
    if canonical_id == "proj_my009_uc":
        if not MY009_MONITORING_LISTING_PATH.exists() or not MY009_PROTOCOL_PATH.exists():
            raise HTTPException(status_code=404, detail="MY009 source files are not available in the configured local source registry")
        return _my009_dashboard_summary().model_dump(mode="json")
    if canonical_id == "proj_mgk10_sar_demo":
        return repo.dashboard(canonical_id).model_dump(mode="json")
    return _source_manifest_dashboard(canonical_id).model_dump(mode="json")


@app.get("/api/projects/{project_id}/module-catalog")
def get_module_catalog(project_id: str, http_request: Request):
    canonical_id = _canonical_project_id(project_id)
    _authorize_legacy_monitoring_action(
        http_request,
        canonical_id,
        request_id=f"legacy-module-catalog-read:{canonical_id}",
        action=MonitoringAction.READ_SOURCE_EVIDENCE,
    )
    manifest = project_source_manifest_service.build_manifest(canonical_id)
    return {
        "project_id": canonical_id,
        "modules": [binding.public_dict() for binding in manifest.modules],
    }


@app.get("/api/projects/{project_id}/source-manifest")
def get_project_source_manifest(project_id: str, http_request: Request):
    canonical_id = _canonical_project_id(project_id)
    # A freshly created writing project has no legacy medical-monitoring
    # binding.  Its manifest is the routing contract needed to render the
    # writing shell, so do not make the shell depend on an upstream monitoring
    # principal.  Canonical/reference projects retain the fail-closed legacy
    # authorization boundary below.
    if not project_source_manifest_service.is_user_created_project(canonical_id):
        _authorize_legacy_monitoring_action(
            http_request,
            canonical_id,
            request_id=f"legacy-source-manifest-read:{canonical_id}",
            action=MonitoringAction.READ_SOURCE_EVIDENCE,
        )
    try:
        return project_source_manifest_service.public_manifest(canonical_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"project source manifest not found: {project_id}")


@app.get("/api/projects/{project_id}/source-contents")
def get_project_source_contents(
    project_id: str,
    http_request: Request,
    module: str = Query("", max_length=120),
    source_kind: str = Query("", max_length=120),
):
    canonical_id = _canonical_project_id(project_id)
    _authorize_legacy_monitoring_action(
        http_request,
        canonical_id,
        request_id=f"legacy-source-content-projection-read:{canonical_id}",
        action=MonitoringAction.READ_SOURCE_EVIDENCE,
    )
    contents = source_content_projection_service.list_contents(
        canonical_id,
        module=module or None,
        source_kind=source_kind or None,
    )
    return {
        "contract_version": SOURCE_CONTENT_PROJECTION_VERSION,
        "project_id": canonical_id,
        "contents": [
            item.model_dump(mode="json")
            for item in contents
        ],
    }


@app.get("/api/projects/{project_id}/shared-protocol-facts")
def get_shared_protocol_facts(
    project_id: str,
    http_request: Request,
    consumer: str = Query(..., max_length=80),
):
    canonical_id = _canonical_project_id(project_id)
    _authorize_legacy_monitoring_action(
        http_request,
        canonical_id,
        request_id=f"legacy-shared-protocol-facts-read:{canonical_id}:{consumer}",
        action=MonitoringAction.READ_SOURCE_EVIDENCE,
    )
    try:
        facts = shared_protocol_fact_projection_service.project(
            canonical_id,
            consumer=consumer,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "contract_version": SHARED_PROTOCOL_FACT_PROJECTION_VERSION,
        "project_id": canonical_id,
        "consumer": consumer,
        "facts": [fact.public_dict() for fact in facts],
    }


@app.get("/api/projects/{project_id}/workbench-inbox")
def get_workbench_inbox(
    project_id: str,
    http_request: Request,
    actor: str = Query("medical_manager"),
    limit: int = Query(80, ge=1, le=200),
):
    canonical_id = _canonical_project_id(project_id)
    if canonical_id == "proj_mgk10_sar_demo" or monitoring_project_registry.has(canonical_id):
        _reject_legacy_monitoring_read_policy_gap(
            http_request,
            canonical_id,
            request_id=f"legacy-workbench-inbox-read-gap:{canonical_id}",
            read_action=MonitoringAction.READ_WORKBENCH_INBOX,
        )
    known = (
        canonical_id == "proj_mgk10_sar_demo"
        or monitoring_project_registry.has(canonical_id)
        or medical_writing_greenfield_document_service.has_project(canonical_id)
    )
    if not known:
        try:
            medical_writing_authoring_journey_service.get(canonical_id)
            known = True
        except Exception:
            known = False
    if not known:
        return WorkbenchInboxResult(
            project_id=canonical_id,
            generated_at=datetime.now(timezone.utc),
            total_open_count=0,
            unread_count=0,
            handoff_count=0,
            items=[],
            module_summaries=[],
        ).model_dump(mode="json")
    try:
        return workbench_inbox_service.inbox(canonical_id, actor=actor, limit=limit).model_dump(mode="json")
    except KeyError:
        # Greenfield MW project not in demo catalog: still surface durable notices.
        notices = workbench_inbox_service._workbench_notification_items(canonical_id)
        hydrated = [item.model_copy(update={"unread": True}) for item in notices]
        return WorkbenchInboxResult(
            project_id=canonical_id,
            generated_at=datetime.now(timezone.utc),
            total_open_count=len(hydrated),
            unread_count=len(hydrated),
            handoff_count=0,
            items=hydrated[:limit],
            module_summaries=[],
        ).model_dump(mode="json")


@app.get("/api/projects/{project_id}/monitoring/subjects")
def get_monitoring_subjects(project_id: str, http_request: Request):
    canonical_id = _canonical_project_id(project_id)
    _authorize_legacy_monitoring_action(
        http_request,
        canonical_id,
        request_id=f"legacy-monitoring-subjects-read:{canonical_id}",
        action=MonitoringAction.READ_MONITORING,
    )
    if monitoring_project_registry.has(canonical_id):
        try:
            return monitoring_project_registry.get(canonical_id).subject_catalog()
        except (FileNotFoundError, KeyError, RuntimeError) as exc:
            raise HTTPException(status_code=404, detail=str(exc))
    if canonical_id != "proj_mgk10_sar_demo":
        raise HTTPException(status_code=404, detail=f"medical monitoring service not registered: {canonical_id}")
    profiles = repo.subject_monitoring_profiles(canonical_id)
    subjects = [
        {
            "id": profile.subject_id,
            "site": profile.subject.site_id,
            "site_name": "",
            "status": profile.subject.enrollment_status,
            "screening_number": profile.subject.screening_number,
            "profile": " | ".join(
                value
                for value in [
                    f"中心 {profile.subject.site_id}" if profile.subject.site_id else "",
                    profile.subject.screening_number,
                    profile.subject.enrollment_status,
                ]
                if value
            ),
            "source_locator": "demo:subject_monitoring_profiles",
        }
        for profile in profiles
    ]
    return {
        "project_id": canonical_id,
        "source_batch_id": "demo_subject_monitoring_profiles",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "subject_count": len(subjects),
        "subjects": subjects,
    }


@app.get("/api/projects/{project_id}/monitoring/risks")
def get_monitoring_risks(
    project_id: str,
    http_request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    site_id: Optional[str] = Query(None),
    subject_id: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    batch_delta: Optional[str] = Query(None),
):
    canonical_id = _canonical_project_id(project_id)
    _authorize_legacy_monitoring_action(
        http_request,
        canonical_id,
        request_id=f"legacy-monitoring-risks-read:{canonical_id}",
        action=MonitoringAction.READ_RISK_AUDIT,
    )
    if not monitoring_project_registry.has(canonical_id):
        raise HTTPException(status_code=404, detail=f"medical monitoring service not registered: {canonical_id}")
    try:
        projection = medical_monitoring_summary_service.current_risk_snapshot(
            canonical_id,
            site_id=site_id or "",
            subject_id=subject_id or "",
            category=category or "",
            severity=severity or "",
            status=status or "",
            batch_delta=batch_delta or "",
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    work_items = workbench_inbox_service.monitoring_risk_items(canonical_id)
    return {
        **projection,
        "analysis_source": (
            "persisted_snapshot"
            if projection["snapshot_status"] == "available"
            else "persisted_snapshot_empty"
        ),
        "subjects_evaluated": int(projection.get("subjects_evaluated") or 0),
        "work_items": [item.model_dump(mode="json") for item in work_items],
    }


@app.get("/api/projects/{project_id}/monitoring/risks/{risk_key}/history")
def get_monitoring_risk_history(
    project_id: str,
    risk_key: str,
    http_request: Request,
):
    canonical_id = _canonical_project_id(project_id)
    _authorize_legacy_monitoring_action(
        http_request,
        canonical_id,
        request_id=(
            f"legacy-monitoring-risk-history-read:{canonical_id}:{risk_key}"
        ),
        action=MonitoringAction.READ_RISK_AUDIT,
    )
    if not monitoring_project_registry.has(canonical_id):
        raise HTTPException(status_code=404, detail=f"medical monitoring service not registered: {canonical_id}")
    history = medical_risk_repository.risk_history(canonical_id, risk_key)
    if not history:
        raise HTTPException(status_code=404, detail=f"monitoring risk history not found: {canonical_id}/{risk_key}")
    current_snapshot = medical_risk_repository.current_snapshot(canonical_id)
    historical_risk_ids = {risk.risk_id for _, risk in history}
    dispositions = [
        record
        for record in runtime_store.records(canonical_id)
        if record.risk_key == risk_key
        or (not record.risk_key and record.risk_id in historical_risk_ids)
    ]
    instances = []
    previous_entry = None
    for snapshot, risk in history:
        changes = []
        transition = classify_risk_identity_transition(
            previous_entry[1] if previous_entry is not None else None,
            risk,
        )
        if previous_entry is None:
            changes.append("首次检测")
        else:
            previous_snapshot, previous_risk = previous_entry
            if snapshot.source_revision != previous_snapshot.source_revision:
                changes.append("数据来源版本变化")
            if snapshot.rule_profile_revision != previous_snapshot.rule_profile_revision:
                changes.append("方案/规则版本变化")
            if snapshot.engine_version != previous_snapshot.engine_version:
                changes.append("风险引擎版本变化")
            if risk.evidence_span_ids != previous_risk.evidence_span_ids:
                changes.append("证据定位变化")
            if risk.severity != previous_risk.severity:
                changes.append("风险级别变化")
            if risk.rationale != previous_risk.rationale:
                changes.append("判定理由变化")
            if not changes:
                changes.append("同一风险持续存在")
        instances.append(
            {
                "snapshot_id": snapshot.snapshot_id,
                "previous_snapshot_id": snapshot.previous_snapshot_id,
                "source_revision": snapshot.source_revision,
                "rule_profile_revision": snapshot.rule_profile_revision,
                "engine_version": snapshot.engine_version,
                "snapshot_created_at": snapshot.created_at.isoformat(),
                "is_current": snapshot.snapshot_id == current_snapshot.snapshot_id,
                "change_reason": "；".join(changes),
                "transition": transition.public_dict(),
                "risk": public_risk_payload(risk),
                "frozen_evidence": frozen_evidence_payload(risk),
                "frozen_evidence_count": sum(
                    1 for item in risk.evidence_snapshots if item.available
                ),
                "evidence_capture_complete": bool(risk.evidence_snapshots)
                and all(item.available for item in risk.evidence_snapshots),
            }
        )
        previous_entry = (snapshot, risk)
    return {
        "project_id": canonical_id,
        "risk_key": risk_key,
        "current_snapshot_id": current_snapshot.snapshot_id,
        "instances": instances,
        "dispositions": [record.model_dump(mode="json") for record in dispositions],
        "boundary_note": (
            "历史处置仅用于跨批次医学上下文；当前状态、医学判断和审批仅取当前风险实例，"
            "不得由旧批次记录自动回填。"
        ),
    }


@app.get("/api/projects/{project_id}/monitoring/risks/{risk_instance_id}/evidence-fragment")
def get_monitoring_risk_evidence_fragment(
    project_id: str,
    risk_instance_id: str,
    http_request: Request,
    locator: str = Query(..., min_length=1),
    snapshot_id: str = Query(default=""),
):
    canonical_id = _canonical_project_id(project_id)
    _authorize_legacy_monitoring_action(
        http_request,
        canonical_id,
        request_id=(
            f"legacy-monitoring-risk-evidence-read:{canonical_id}:"
            f"{risk_instance_id}"
        ),
        action=MonitoringAction.READ_RISK_AUDIT,
    )
    if not monitoring_project_registry.has(canonical_id):
        raise HTTPException(status_code=404, detail=f"medical monitoring service not registered: {canonical_id}")
    try:
        snapshot, risk = medical_risk_repository.risk_instance(
            canonical_id,
            risk_instance_id,
            snapshot_id=snapshot_id,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="medical risk instance is unavailable")
    if locator not in risk.evidence_span_ids:
        raise HTTPException(
            status_code=404,
            detail="source locator is not bound to the requested risk instance",
        )
    captured = frozen_fragment(risk, locator)
    if captured is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "historical evidence was not frozen for this risk instance; "
                "the current source will not be substituted"
            ),
        )
    if not captured.available:
        raise HTTPException(
            status_code=409,
            detail=f"frozen evidence is unavailable: {captured.error_code}",
        )
    return {
        "project_id": canonical_id,
        "risk_key": risk.risk_key,
        "risk_instance_id": risk.risk_instance_id,
        "snapshot_id": snapshot.snapshot_id,
        "source_revision": snapshot.source_revision,
        "evidence_capture": "snapshot_frozen",
        "evidence_captured_at": captured.captured_at.isoformat(),
        "risk_context": risk.title,
        **captured.fragment,
    }


@app.get("/api/projects/{project_id}/monitoring/raw-intake")
def get_monitoring_raw_intake(project_id: str, http_request: Request):
    canonical_id = _canonical_project_id(project_id)
    _authorize_legacy_monitoring_action(
        http_request,
        canonical_id,
        request_id=f"legacy-monitoring-raw-intake-read:{canonical_id}",
        action=MonitoringAction.READ_MONITORING,
    )
    config = MONITORING_RAW_PROJECTS.get(canonical_id)
    if config is None:
        raise HTTPException(status_code=404, detail=f"raw monitoring project not configured: {canonical_id}")
    try:
        return monitoring_raw_intake_service.discover_project(config).public_dict()
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/projects/{project_id}/workbench-inbox/{item_id}/actions")
def apply_workbench_inbox_action(
    project_id: str,
    item_id: str,
    request: WorkbenchItemActionRequest,
    http_request: Request,
):
    canonical_id = _canonical_project_id(project_id)
    if canonical_id == "proj_mgk10_sar_demo" or monitoring_project_registry.has(canonical_id):
        _reject_legacy_monitoring_policy_gap(
            http_request,
            canonical_id,
            request_id=f"legacy-workbench-inbox-action-gap:{canonical_id}:{item_id}",
            read_action=MonitoringAction.READ_MONITORING,
        )
    try:
        return workbench_inbox_service.apply_action(canonical_id, item_id, request).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"workbench item not found: {canonical_id}/{item_id}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/api/projects/{project_id}/workbench-inbox/{item_id}/risk-disposition")
def apply_monitoring_risk_disposition(
    project_id: str,
    item_id: str,
    request: RuxRiskDispositionActionRequest,
    http_request: Request,
):
    canonical_id = _canonical_project_id(project_id)
    server_actor = _authorize_legacy_monitoring_action(
        http_request,
        canonical_id,
        request_id=f"legacy-monitoring-risk-disposition-write:{canonical_id}:{item_id}",
        action=MonitoringAction.CHANGE_RISK_DISPOSITION,
        write=True,
        high_risk=True,
        reauthenticated=request.reauthenticated,
        signature_evidence_sha256=request.signature_evidence_sha256,
    )
    request = request.model_copy(update={"actor": server_actor})
    try:
        return workbench_inbox_service.apply_monitoring_risk_disposition(canonical_id, item_id, request).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"monitoring risk item not found: {canonical_id}/{item_id}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/api/projects/{project_id}/workbench-inbox/{item_id}/rux-risk-disposition")
def apply_rux_risk_disposition(
    project_id: str,
    item_id: str,
    request: RuxRiskDispositionActionRequest,
    http_request: Request,
):
    canonical_id = _canonical_project_id(project_id)
    server_actor = _authorize_legacy_monitoring_action(
        http_request,
        canonical_id,
        request_id=f"legacy-rux-risk-disposition-write:{canonical_id}:{item_id}",
        action=MonitoringAction.CHANGE_RISK_DISPOSITION,
        write=True,
        high_risk=True,
        reauthenticated=request.reauthenticated,
        signature_evidence_sha256=request.signature_evidence_sha256,
    )
    request = request.model_copy(update={"actor": server_actor})
    try:
        return workbench_inbox_service.apply_rux_risk_disposition(canonical_id, item_id, request).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"RUX risk item not found: {canonical_id}/{item_id}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/api/projects/{project_id}/ai-runs")
def submit_ai_run(project_id: str, request: Request):
    raise HTTPException(
        status_code=403,
        detail="AI execution requires server-resolved registered source IDs; direct allowed_sources payloads are forbidden",
    )


@app.post("/api/projects/{project_id}/ai-runs/from-sources")
def submit_ai_run_from_registered_sources(
    project_id: str,
    request: AiTaskFromRegistryRequest,
    http_request: Request,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, request.module)
        _reject_legacy_monitoring_policy_gap(
            http_request,
            canonical_id,
            request_id=(
                f"legacy-ai-run-from-sources-gap:{canonical_id}:{request.module}"
            ),
            read_action=MonitoringAction.READ_SOURCE_EVIDENCE,
        )
        run = ai_task_runner.submit_registered(canonical_id, request, source_registry)
        return public_ai_run(run)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except AiExecutionPolicyDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _public_source_span(span):
    payload = span.model_dump(mode="json", exclude={"preview_hash"})
    text_preview = payload.get("text_preview") or ""
    if len(text_preview) > 600:
        payload["text_preview"] = text_preview[:600] + "...[truncated]"
    return payload


def _public_source_entry(entry):
    payload = entry.model_dump(mode="json", exclude={"content_hash", "storage_key", "server_path"})
    if str(payload.get("public_title", "")).strip().isdigit():
        filename = Path(str(payload.get("metadata", {}).get("filename", ""))).name
        if filename:
            payload["public_title"] = filename
    return payload


def _source_entry_slot(entry):
    source_kind = entry.source_kind
    if entry.module == "safety_pv" and source_kind == "listing_file":
        source_kind = "safety_medical_review_listing"
    return entry.module, source_kind


def _public_source_validation(validation):
    return validation.model_dump(
        mode="json",
        exclude={"file_sha256", "expected_context_hash"},
    )


def _real_project_monitoring_intake_not_enabled_detail(
    project_id: str,
    *,
    source_entry=None,
    validation=None,
):
    detail = {
        "code": "real_project_incremental_monitoring_not_enabled",
        "message": "当前真实项目尚未启用增量医学监查执行；文件已完成登记与内容核验，未运行通用规则引擎。",
        "project_id": project_id,
    }
    if source_entry is not None:
        detail["source_entry"] = _public_source_entry(source_entry)
        detail["content_validation"] = (
            _public_source_validation(validation) if validation is not None else None
        )
    return detail


def _public_source_registration(result):
    payload = {
        "entry": _public_source_entry(result.entry),
        "spans": [_public_source_span(span) for span in result.spans],
    }
    validation = source_registry.current_content_validation(
        result.entry.project_id,
        result.entry.entry_id,
    )
    if validation is not None:
        payload["content_validation"] = _public_source_validation(validation)
    return payload


@app.get("/api/projects/{project_id}/ai-runs")
def list_ai_runs(project_id: str, http_request: Request):
    try:
        canonical_id = _canonical_project_id(project_id)
        if not project_source_manifest_service.is_user_created_project(canonical_id):
            _reject_legacy_monitoring_read_policy_gap(
                http_request,
                canonical_id,
                request_id=f"legacy-ai-run-list-read-gap:{canonical_id}",
                read_action=MonitoringAction.READ_AI_RUN,
            )
        return [public_ai_run(run) for run in ai_task_runner.list_runs(canonical_id)]
    except KeyError:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")


@app.get("/api/projects/{project_id}/ai-runs/{run_id}")
def get_ai_run(project_id: str, run_id: str, http_request: Request):
    try:
        canonical_id = _canonical_project_id(project_id)
        if not project_source_manifest_service.is_user_created_project(canonical_id):
            _reject_legacy_monitoring_read_policy_gap(
                http_request,
                canonical_id,
                request_id=f"legacy-ai-run-detail-read-gap:{canonical_id}:{run_id}",
                read_action=MonitoringAction.READ_AI_RUN,
            )
        return public_ai_run(ai_task_runner.get(canonical_id, run_id))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"AI run not found: {project_id}/{run_id}")


@app.get("/api/projects/{project_id}/ai-runs/{run_id}/artifacts")
def get_ai_run_artifacts(project_id: str, run_id: str, http_request: Request):
    try:
        canonical_id = _canonical_project_id(project_id)
        if not project_source_manifest_service.is_user_created_project(canonical_id):
            _reject_legacy_monitoring_read_policy_gap(
                http_request,
                canonical_id,
                request_id=f"legacy-ai-run-artifacts-read-gap:{canonical_id}:{run_id}",
                read_action=MonitoringAction.READ_AI_ARTIFACT,
            )
        return public_ai_artifacts(ai_task_runner.artifacts(canonical_id, run_id))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"AI run not found: {project_id}/{run_id}")


@app.get("/api/projects/{project_id}/sources")
def list_registered_sources(project_id: str, http_request: Request):
    canonical_id = _canonical_project_id(project_id)
    _authorize_legacy_monitoring_action(
        http_request,
        canonical_id,
        request_id=f"legacy-source-catalog-read:{canonical_id}",
        action=MonitoringAction.READ_SOURCE_EVIDENCE,
    )
    entries = source_registry.list_entries(canonical_id)
    latest_by_slot = {}
    for entry in entries:
        slot = _source_entry_slot(entry)
        previous = latest_by_slot.get(slot)
        if previous is None or entry.created_at > previous.created_at:
            latest_by_slot[slot] = entry
    public_entries = []
    for entry in entries:
        payload = _public_source_entry(entry)
        payload["is_current"] = latest_by_slot[_source_entry_slot(entry)].entry_id == entry.entry_id
        public_entries.append(payload)
    return {
        "project_id": canonical_id,
        "entries": public_entries,
        "spans": [_public_source_span(span) for span in source_registry.list_spans(canonical_id)],
        "content_validations": [
            _public_source_validation(validation)
            for entry in entries
            if (validation := source_registry.current_content_validation(canonical_id, entry.entry_id))
            is not None
        ],
        "content_validation_histories": {
            entry.entry_id: [
                _public_source_validation(validation)
                for validation in source_registry.content_validation_history(
                    canonical_id,
                    entry.entry_id,
                )
            ]
            for entry in entries
        },
    }


def _eligibility_source_admission_state(project_id: str):
    canonical_id = _canonical_module_project_id(project_id, "eligibility_review")
    required_kinds = {"protocol_docx", "raw_subject_bundle_inventory"}
    latest_by_kind = {}
    for entry in source_registry.list_entries(canonical_id):
        if entry.module != "eligibility_review" or entry.source_kind not in required_kinds:
            continue
        previous = latest_by_kind.get(entry.source_kind)
        if previous is None or entry.created_at > previous.created_at:
            latest_by_kind[entry.source_kind] = entry
    sources = []
    for source_kind in sorted(required_kinds):
        entry = latest_by_kind.get(source_kind)
        if entry is None:
            continue
        validation = source_registry.current_content_validation(canonical_id, entry.entry_id)
        sources.append(
            {
                "entry": _public_source_entry(entry),
                "content_validation": _public_source_validation(validation) if validation else None,
            }
        )
    missing_source_kinds = sorted(required_kinds - set(latest_by_kind))
    ready_for_use = not missing_source_kinds and all(
        item["content_validation"] is not None
        and item["content_validation"]["use_status"] in {"allowed", "confirmed_after_warning"}
        for item in sources
    )
    return {
        "project_id": canonical_id,
        "sources": sources,
        "missing_source_kinds": missing_source_kinds,
        "ready_for_use": ready_for_use,
    }


def _refresh_eligibility_source_admission(project_id: str):
    canonical_id = _canonical_module_project_id(project_id, "eligibility_review")
    config = RAW_INTAKE_PROJECTS.get(canonical_id)
    if config is None:
        raise HTTPException(
            status_code=404,
            detail=f"eligibility raw source is not configured: {canonical_id}",
        )
    try:
        protocol = source_registry.register_local_file(
            canonical_id,
            config.protocol_path,
            module="eligibility_review",
            expected_file_role="protocol_docx",
        )
        subject_bundle = source_registry.register_raw_subject_bundle(
            canonical_id,
            config.raw_subject_root,
            module="eligibility_review",
        )
    except (ValueError, FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _eligibility_source_admission_state(canonical_id)


configure_eligibility_source_admission_guard(_eligibility_source_admission_state)


@app.post("/api/projects/{project_id}/eligibility/source-admission/refresh")
def refresh_eligibility_source_admission(project_id: str, http_request: Request):
    canonical_id = _canonical_module_project_id(project_id, "eligibility_review")
    _reject_legacy_monitoring_policy_gap(
        http_request,
        canonical_id,
        request_id=f"legacy-eligibility-source-admission-refresh-gap:{canonical_id}",
        read_action=MonitoringAction.READ_SOURCE_EVIDENCE,
    )
    return _refresh_eligibility_source_admission(project_id)


@app.post("/api/projects/{project_id}/sources/{source_entry_id}/content-validation/confirm")
def confirm_registered_source_content_validation(
    project_id: str,
    source_entry_id: str,
    request: SourceContentValidationConfirmationRequest,
    http_request: Request,
):
    canonical_id = _canonical_project_id(project_id)
    server_actor = _authorize_legacy_monitoring_action(
        http_request,
        canonical_id,
        request_id=(
            f"legacy-source-content-validation-write:{canonical_id}:"
            f"{source_entry_id}"
        ),
        action=MonitoringAction.VALIDATE_SOURCE_REVISION,
        write=True,
    )
    request = request.model_copy(update={"actor": server_actor})
    try:
        return _public_source_validation(
            source_registry.confirm_content_validation(canonical_id, source_entry_id, request)
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"source entry not found: {source_entry_id}")
    except SourceContentValidationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/projects/{project_id}/sources/protocol-docx")
async def register_protocol_docx_source(
    project_id: str,
    request: Request,
    filename: str = Query(...),
    module: str = Query("eligibility_review"),
):
    canonical_id = _canonical_module_project_id(project_id, module)
    _reject_legacy_monitoring_policy_gap(
        request,
        canonical_id,
        request_id=f"legacy-source-protocol-registration-gap:{canonical_id}:{module}",
        read_action=MonitoringAction.READ_SOURCE_EVIDENCE,
    )
    content = await request.body()
    if not content:
        raise HTTPException(status_code=400, detail="protocol docx file is empty")
    try:
        return _public_source_registration(source_registry.register_protocol_docx(canonical_id, filename, content, module=module))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/projects/{project_id}/medical-writing/sources/investigator-brochure")
async def register_medical_writing_investigator_brochure(
    project_id: str,
    file: UploadFile = File(...),
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        journey = medical_writing_authoring_journey_service.get(canonical_id)
        content = await file.read(50 * 1024 * 1024 + 1)
        result = source_registry.register_medical_writing_document(
            canonical_id,
            file.filename or "",
            file.content_type or "",
            content,
            document_role="investigator_brochure",
            expected_indication=journey.framing.indication,
        )
        return _public_source_registration(result)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    finally:
        await file.close()


@app.post("/api/projects/{project_id}/sources/listing-file")
async def register_listing_file_source(
    project_id: str,
    request: Request,
    filename: str = Query(...),
    module: str = Query("medical_monitoring"),
):
    canonical_id = _canonical_module_project_id(project_id, module)
    _reject_legacy_monitoring_policy_gap(
        request,
        canonical_id,
        request_id=f"legacy-source-listing-registration-gap:{canonical_id}:{module}",
        read_action=MonitoringAction.READ_SOURCE_EVIDENCE,
    )
    content = await request.body()
    if not content:
        raise HTTPException(status_code=400, detail="listing file is empty")
    try:
        return _public_source_registration(
            source_registry.register_listing_file(
                canonical_id,
                filename,
                content,
                module=module,
                expected_file_role=(
                    "edc_data_listing"
                    if module == "medical_monitoring"
                    else ""
                ),
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/projects/{project_id}/sources/raw-subject-bundle")
def register_raw_subject_bundle_source(
    project_id: str,
    http_request: Request,
    root_path: str = Query(...),
    module: str = Query("eligibility_review"),
):
    canonical_id = _canonical_module_project_id(project_id, module)
    _reject_legacy_monitoring_policy_gap(
        http_request,
        canonical_id,
        request_id=f"legacy-source-raw-bundle-registration-gap:{canonical_id}:{module}",
        read_action=MonitoringAction.READ_SOURCE_EVIDENCE,
    )
    try:
        return _public_source_registration(source_registry.register_raw_subject_bundle(canonical_id, root_path, module=module))
    except (ValueError, FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/projects/{project_id}/sources/local-file")
def register_local_file_source(
    project_id: str,
    http_request: Request,
    file_path: str = Query(...),
    module: str = Query(...),
):
    canonical_id = _canonical_module_project_id(project_id, module)
    _reject_legacy_monitoring_policy_gap(
        http_request,
        canonical_id,
        request_id=f"legacy-source-local-file-registration-gap:{canonical_id}:{module}",
        read_action=MonitoringAction.READ_SOURCE_EVIDENCE,
    )
    try:
        return _public_source_registration(source_registry.register_local_file(canonical_id, file_path, module=module))
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/projects/{project_id}/sources/local-directory")
def register_local_directory_source(
    project_id: str,
    http_request: Request,
    root_path: str = Query(...),
    module: str = Query(...),
    source_kind: str = Query("file_bundle_inventory"),
):
    canonical_id = _canonical_module_project_id(project_id, module)
    _reject_legacy_monitoring_policy_gap(
        http_request,
        canonical_id,
        request_id=f"legacy-source-local-directory-registration-gap:{canonical_id}:{module}",
        read_action=MonitoringAction.READ_SOURCE_EVIDENCE,
    )
    try:
        return _public_source_registration(source_registry.register_local_directory(
            canonical_id,
            root_path,
            module=module,
            source_kind=source_kind,
        ))
    except (ValueError, FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/projects/{project_id}/sources/local-candidate")
def register_local_candidate_source(
    project_id: str,
    http_request: Request,
    candidate_id: str = Query(...),
    module: str = Query(...),
):
    canonical_id = _canonical_module_project_id(project_id, module)
    _reject_legacy_monitoring_policy_gap(
        http_request,
        canonical_id,
        request_id=(
            f"legacy-source-local-candidate-registration-gap:{canonical_id}:"
            f"{module}:{candidate_id}"
        ),
        read_action=MonitoringAction.READ_SOURCE_EVIDENCE,
    )

    candidate = SOURCE_REGISTRY_CANDIDATES.get(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail=f"source candidate not found: {candidate_id}")

    try:
        expected_module = str(candidate["module"])
        if module != expected_module:
            raise ValueError(f"source candidate {candidate_id} does not belong to module {module}")
        if canonical_id not in candidate.get("project_ids", set()):
            raise ValueError(f"source candidate {candidate_id} does not belong to project {canonical_id}")
        candidate_path = candidate["path"]
        if candidate["kind"] == "local-file":
            return _public_source_registration(source_registry.register_local_file(
                canonical_id,
                candidate_path,
                module=expected_module,
                expected_file_role=str(candidate.get("source_kind") or ""),
            ))
        return _public_source_registration(source_registry.register_local_directory(
            canonical_id,
            candidate_path,
            module=expected_module,
            source_kind=str(candidate.get("source_kind") or "file_bundle_inventory"),
        ))
    except (ValueError, FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/projects/{project_id}/risks")
def get_risks(project_id: str, http_request: Request):
    canonical_id = _canonical_project_id(project_id)
    _authorize_legacy_monitoring_action(
        http_request,
        canonical_id,
        request_id=f"legacy-monitoring-risk-catalog-read:{canonical_id}",
        action=MonitoringAction.READ_RISK_AUDIT,
    )
    return [risk.model_dump(mode="json") for risk in repo.risks(canonical_id)]


@app.get("/api/projects/{project_id}/data-batches")
def get_data_batches(project_id: str, http_request: Request):
    canonical_id = _canonical_project_id(project_id)
    _authorize_legacy_monitoring_action(
        http_request,
        canonical_id,
        request_id=f"legacy-monitoring-data-batch-catalog-read:{canonical_id}",
        action=MonitoringAction.READ_MONITORING,
    )
    return [batch.model_dump(mode="json") for batch in repo.batches(canonical_id)]


@app.get("/api/projects/{project_id}/evidence-design/manifest")
def get_evidence_design_manifest(project_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "evidence_design")
        return evidence_design_manifest_service.build_manifest(canonical_id).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"evidence_design not configured for project: {project_id}")
    except EvidencePackageAdapterError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/projects/{project_id}/evidence-design/packages")
def get_evidence_package_catalog(project_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "evidence_design")
        return evidence_design_manifest_service.package_catalog(canonical_id).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"evidence_design not configured for project: {project_id}")
    except EvidencePackageAdapterError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/projects/{project_id}/evidence-design/packages/{package_id}/candidates")
def get_evidence_candidate_page(
    project_id: str,
    package_id: str,
    candidate_type: str = Query("all"),
    search: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "evidence_design")
        return evidence_review_workflow_service.candidate_page(
            canonical_id,
            package_id,
            candidate_type=candidate_type,
            search=search,
            page=page,
            page_size=page_size,
        ).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"evidence package not found for project: {project_id}/{package_id}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except EvidencePackageAdapterError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/projects/{project_id}/evidence-design/packages/{package_id}/candidates/{evidence_id}")
def get_evidence_candidate_detail(project_id: str, package_id: str, evidence_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "evidence_design")
        return evidence_design_manifest_service.candidate_detail(
            canonical_id,
            package_id,
            evidence_id,
        ).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"evidence candidate not found: {evidence_id}")
    except EvidencePackageAdapterError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/projects/{project_id}/evidence-design/packages/{package_id}/candidates/{evidence_id}/review")
def get_evidence_candidate_review(project_id: str, package_id: str, evidence_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "evidence_design")
        return evidence_review_workflow_service.state(
            canonical_id,
            package_id,
            evidence_id,
        ).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"evidence candidate not found: {evidence_id}")
    except EvidencePackageAdapterError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/api/projects/{project_id}/evidence-design/packages/{package_id}/candidates/{evidence_id}/review-actions")
def apply_evidence_candidate_review_action(
    project_id: str,
    package_id: str,
    evidence_id: str,
    request: EvidenceReviewActionRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "evidence_design")
        return evidence_review_workflow_service.apply_action(
            canonical_id,
            package_id,
            evidence_id,
            request,
        ).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"evidence candidate not found: {evidence_id}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except EvidencePackageAdapterError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/projects/{project_id}/evidence-design/picos-workflow")
def get_evidence_picos_workflow(project_id: str, package_id: Optional[str] = Query(None)):
    try:
        canonical_id = _canonical_module_project_id(project_id, "evidence_design")
        return evidence_picos_workflow_service.workflow(canonical_id, package_id=package_id).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"project or evidence package not found: {project_id}")


@app.post("/api/projects/{project_id}/evidence-design/picos-workflow/{package_id}/questions/{question_id}/actions")
def apply_evidence_picos_action(
    project_id: str,
    package_id: str,
    question_id: str,
    request: EvidencePicosActionRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "evidence_design")
        return evidence_picos_workflow_service.apply_action(canonical_id, package_id, question_id, request).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"project, evidence package, or PICOS question not found: {project_id}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/api/projects/{project_id}/evidence-design/picos-workflow/{package_id}/approval-submissions")
def submit_evidence_picos_approval(
    project_id: str,
    package_id: str,
    request: EvidencePicosSubmitApprovalRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "evidence_design")
        return evidence_picos_approval_service.submit_for_approval(
            canonical_id,
            package_id,
            request,
        ).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"project or evidence package not found: {project_id}/{package_id}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/api/projects/{project_id}/evidence-design/picos-workflow/{package_id}/writing-handoffs")
def create_evidence_picos_writing_handoff(
    project_id: str,
    package_id: str,
    request: EvidencePicosHandoffRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "evidence_design")
        return evidence_picos_approval_service.create_handoff(
            canonical_id,
            package_id,
            request,
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/api/projects/{project_id}/evidence-design/picos-workflow/{package_id}/ai-revisions")
def list_evidence_ai_revisions(
    project_id: str,
    package_id: str,
    anchor_id: str = Query(""),
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "evidence_design")
        return [
            item.model_dump(mode="json")
            for item in evidence_ai_revision_service.list_threads(
                canonical_id,
                package_id,
                anchor_id=anchor_id,
            )
        ]
    except KeyError:
        raise HTTPException(status_code=404, detail=f"project or evidence package not found: {project_id}/{package_id}")


@app.post("/api/projects/{project_id}/evidence-design/picos-workflow/{package_id}/ai-revisions")
def submit_evidence_ai_revision(
    project_id: str,
    package_id: str,
    request: EvidenceAiRevisionRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "evidence_design")
        return evidence_ai_revision_service.submit(
            canonical_id,
            package_id,
            request,
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/api/projects/{project_id}/evidence-design/picos-workflow/{package_id}/ai-revisions/{thread_id}/actions")
def apply_evidence_ai_revision_action(
    project_id: str,
    package_id: str,
    thread_id: str,
    request: EvidenceAiRevisionActionRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "evidence_design")
        thread = evidence_ai_revision_service.runtime_store.evidence_ai_revision_thread(
            canonical_id,
            thread_id,
        )
        if thread.package_id != package_id:
            raise KeyError(thread_id)
        return evidence_ai_revision_service.apply_action(
            canonical_id,
            thread_id,
            request,
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/api/projects/{project_id}/medical-writing/manifest")
def get_medical_writing_manifest(
    project_id: str,
    allow_missing: bool = Query(False),
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        try:
            result = medical_writing_manifest_service.build_manifest(canonical_id)
        except KeyError:
            state = medical_writing_document_service.greenfield_state(canonical_id)
            header = project_source_manifest_service.build_manifest(
                canonical_id
            ).header_project
            result = medical_writing_manifest_service.build_greenfield_manifest(
                canonical_id,
                medical_writing_document_service.document_for_revision(canonical_id),
                state,
                project_code=header.project_code,
                indication=header.indication,
            )
        return result.model_dump(mode="json")
    except KeyError:
        if allow_missing:
            return {"available": False}
        raise HTTPException(status_code=404, detail=f"medical_writing not configured for project: {project_id}")


@app.post("/api/projects/{project_id}/medical-writing/references/search-snapshots")
def create_writing_reference_search_snapshot(
    project_id: str,
    request: WritingReferenceSearchCreateRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return writing_reference_discovery_service.create_search_snapshot(
            canonical_id,
            request,
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except WritingReferenceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/projects/{project_id}/medical-writing/literature")
def get_medical_writing_literature(project_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_literature_service.library(canonical_id).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/projects/{project_id}/medical-writing/literature/imports")
def import_medical_writing_literature_reference(
    project_id: str,
    request: MedicalWritingReferenceImportRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_literature_service.import_reference(
            canonical_id,
            request,
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except MedicalWritingLiteratureConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except MedicalWritingLiteratureError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.put("/api/projects/{project_id}/medical-writing/literature/citation-style")
def update_medical_writing_citation_style(
    project_id: str,
    request: MedicalWritingCitationStyleUpdateRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_literature_service.update_style(
            canonical_id,
            request,
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except MedicalWritingLiteratureConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except MedicalWritingLiteratureError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get(
    "/api/projects/{project_id}/medical-writing/references/search-snapshots/{snapshot_id}"
)
def get_writing_reference_search_snapshot(project_id: str, snapshot_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return writing_reference_repository.search_snapshot(
            canonical_id,
            snapshot_id,
        ).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail="writing reference search snapshot not found")


@app.get("/api/projects/{project_id}/medical-writing/references/workspace")
def get_writing_reference_workspace(
    project_id: str,
    snapshot_id: Optional[str] = Query(None),
):
    canonical_id = _canonical_module_project_id(project_id, "medical_writing")
    try:
        snapshot = (
            writing_reference_repository.search_snapshot(canonical_id, snapshot_id)
            if snapshot_id
            else writing_reference_repository.latest_search_snapshot(canonical_id)
        )
    except KeyError:
        return {
            "project_id": canonical_id,
            "initialized": False,
            "snapshot": None,
            "decisions": [],
            "artifacts": [],
            "document_validations": [],
            "artifact_span_counts": {},
            "extraction_reviews": [],
            "ocr_consistency_reviews": [],
            "translations": [],
            "medical_reviews": [],
            "approved_evidence_briefs": [],
            "evidence_brief_history": [],
        }
    decisions = writing_reference_repository.relevance_decisions_for_snapshot(
        canonical_id,
        snapshot.snapshot_id,
    )
    artifacts = writing_reference_repository.document_artifacts(
        canonical_id,
        snapshot.snapshot_id,
    )
    document_validations = writing_reference_repository.document_validations(canonical_id)
    artifact_span_counts = writing_reference_repository.source_span_counts(
        canonical_id,
        snapshot_id=snapshot.snapshot_id,
    )
    extraction_reviews = writing_reference_repository.extraction_reviews(canonical_id)
    ocr_consistency_reviews = writing_reference_repository.ocr_consistency_qc_reviews(
        canonical_id
    )
    translations = writing_reference_repository.translations(canonical_id)
    medical_reviews = writing_reference_repository.medical_reviews(canonical_id)
    briefs = writing_reference_repository.evidence_briefs(canonical_id)
    brief_history = writing_reference_repository.evidence_brief_history(canonical_id)
    return {
        "project_id": canonical_id,
        "initialized": True,
        "snapshot": snapshot.model_dump(mode="json"),
        "decisions": [item.model_dump(mode="json") for item in decisions],
        "artifacts": [item.model_dump(mode="json") for item in artifacts],
        "document_validations": [item.model_dump(mode="json") for item in document_validations],
        "artifact_span_counts": artifact_span_counts,
        "extraction_reviews": [item.model_dump(mode="json") for item in extraction_reviews],
        "ocr_consistency_reviews": [
            item.model_dump(mode="json") for item in ocr_consistency_reviews
        ],
        "translations": [item.model_dump(mode="json") for item in translations],
        "medical_reviews": [item.model_dump(mode="json") for item in medical_reviews],
        "approved_evidence_briefs": [item.model_dump(mode="json") for item in briefs],
        "evidence_brief_history": [item.model_dump(mode="json") for item in brief_history],
    }


@app.get(
    "/api/projects/{project_id}/medical-writing/references/documents/{artifact_id}/spans"
)
def get_writing_reference_spans(
    project_id: str,
    artifact_id: str,
    extraction_revision: Optional[str] = Query(None),
    ich_m11_anchor: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    canonical_id = _canonical_module_project_id(project_id, "medical_writing")
    try:
        writing_reference_repository.document_artifact(canonical_id, artifact_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="writing reference document not found")
    if extraction_revision is None:
        try:
            extraction_revision = writing_reference_repository.latest_extraction_revision(
                canonical_id,
                artifact_id,
            )
        except KeyError:
            return {
                "artifact_id": artifact_id,
                "extraction_revision": None,
                "anchor_counts": {},
                "total": 0,
                "offset": offset,
                "limit": limit,
                "items": [],
            }
    all_spans = writing_reference_repository.source_spans(
        canonical_id,
        artifact_id,
        extraction_revision=extraction_revision,
    )
    if not all_spans:
        raise HTTPException(status_code=404, detail="writing reference extraction revision not found")
    anchor_counts = Counter(item.ich_m11_anchor for item in all_spans)
    spans = (
        [item for item in all_spans if item.ich_m11_anchor == ich_m11_anchor]
        if ich_m11_anchor
        else all_spans
    )
    return {
        "artifact_id": artifact_id,
        "extraction_revision": extraction_revision,
        "anchor_counts": dict(sorted(anchor_counts.items())),
        "total": len(spans),
        "offset": offset,
        "limit": limit,
        "items": [item.model_dump(mode="json") for item in spans[offset:offset + limit]],
    }


@app.post(
    "/api/projects/{project_id}/medical-writing/references/search-snapshots/{snapshot_id}/relevance-decisions"
)
def record_writing_reference_relevance_decision(
    project_id: str,
    snapshot_id: str,
    request: WritingReferenceRelevanceDecisionRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return writing_reference_repository.record_relevance_decision(
            project_id=canonical_id,
            snapshot_id=snapshot_id,
            nct_id=request.nct_id,
            relevance_status=request.relevance_status,
            reason=request.reason,
            actor=request.actor,
            expected_revision=request.expected_revision,
            idempotency_key=request.idempotency_key,
        ).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail="writing reference search snapshot not found")
    except (WritingReferenceConflictError, WritingReferenceStaleStateError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/projects/{project_id}/medical-writing/references/documents/ingest")
def ingest_writing_reference_document(
    project_id: str,
    request: WritingReferenceDocumentIngestRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return writing_reference_document_service.ingest(
            canonical_id,
            request,
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except WritingReferenceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/references/preparation-batches",
    status_code=202,
)
def create_writing_reference_preparation_batch(
    project_id: str,
    request: WritingReferencePreparationBatchCreateRequest,
    background_tasks: BackgroundTasks,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        batch = writing_reference_preparation_batch_service.create(
            canonical_id,
            request,
        )
        background_tasks.add_task(
            writing_reference_preparation_batch_service.run_pending,
            canonical_id,
            batch.batch_id,
            request.actor,
        )
        return batch.model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except WritingReferenceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get(
    "/api/projects/{project_id}/medical-writing/references/preparation-batches/latest"
)
def get_latest_writing_reference_preparation_batch(
    project_id: str,
    snapshot_id: str = Query(..., min_length=1),
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return writing_reference_preparation_batch_service.latest(
            canonical_id,
            snapshot_id,
        ).model_dump(mode="json")
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail="writing reference preparation batch not found for project and snapshot",
        )


@app.get(
    "/api/projects/{project_id}/medical-writing/references/preparation-batches/{batch_id}"
)
def get_writing_reference_preparation_batch(project_id: str, batch_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return writing_reference_preparation_batch_service.get(
            canonical_id,
            batch_id,
        ).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail="writing reference preparation batch not found")


@app.post(
    "/api/projects/{project_id}/medical-writing/references/preparation-batches/{batch_id}/advance-stage",
    status_code=202,
)
def advance_writing_reference_preparation_batch_stage(
    project_id: str,
    batch_id: str,
    request: WritingReferencePreparationBatchStageAdvanceRequest,
    background_tasks: BackgroundTasks,
):
    """Admit exactly one deferred preparation stage before running it."""
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        batch = writing_reference_preparation_batch_service.admit_next_stage(
            canonical_id,
            batch_id,
            request,
        )
        background_tasks.add_task(
            writing_reference_preparation_batch_service.run_pending,
            canonical_id,
            batch.batch_id,
            request.actor,
        )
        return batch.model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail="writing reference preparation batch not found")
    except WritingReferenceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/references/preparation-batches/{batch_id}/retry",
    status_code=202,
)
def retry_writing_reference_preparation_batch(
    project_id: str,
    batch_id: str,
    request: WritingReferencePreparationBatchRetryRequest,
    background_tasks: BackgroundTasks,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        batch = writing_reference_preparation_batch_service.retry(
            canonical_id,
            batch_id,
            request,
        )
        background_tasks.add_task(
            writing_reference_preparation_batch_service.run_failed,
            canonical_id,
            batch.batch_id,
            request.actor,
        )
        return batch.model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail="writing reference preparation batch not found")
    except WritingReferenceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get(
    "/api/projects/{project_id}/medical-writing/references/translation-batches/preview"
)
def preview_writing_reference_translation_batch(
    project_id: str,
    snapshot_id: str = Query(..., min_length=1),
    glossary_version: str = Query("cms_regulatory_zh_v1", min_length=1),
    anchor_filter: Optional[list[str]] = Query(None),
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        request = WritingReferenceTranslationBatchPreviewRequest(
            snapshot_id=snapshot_id,
            glossary_version=glossary_version,
            anchor_filter=anchor_filter or [],
        )
        return writing_reference_translation_batch_service.preview(
            canonical_id,
            request,
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/references/translation-batches",
    status_code=202,
)
def create_writing_reference_translation_batch(
    project_id: str,
    request: WritingReferenceTranslationBatchCreateRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        batch = writing_reference_translation_batch_service.create(
            canonical_id,
            request,
        )
        # Durable path: ensure a reference_translation durable job exists and
        # wake the worker.  No long AI call on the HTTP thread.  If wake fails
        # the sweeper recovers the queued job.
        job_id = writing_reference_translation_batch_service.ensure_reference_translation_job(
            canonical_id, batch.batch_id, actor=request.actor,
        )
        if job_id:
            try:
                mw_durable_worker.wake(canonical_id, job_id)
            except Exception:
                pass  # sweeper recovers
        result = batch.model_dump(mode="json")
        result["durable_job_id"] = job_id or ""
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except WritingReferenceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get(
    "/api/projects/{project_id}/medical-writing/references/translation-batches/latest"
)
def get_latest_writing_reference_translation_batch(
    project_id: str,
    snapshot_id: str = Query(..., min_length=1),
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return writing_reference_translation_batch_service.latest(
            canonical_id,
            snapshot_id,
        ).model_dump(mode="json")
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail="writing reference translation batch not found for project and snapshot",
        )


@app.get(
    "/api/projects/{project_id}/medical-writing/references/translation-batches/{batch_id}"
)
def get_writing_reference_translation_batch(project_id: str, batch_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return writing_reference_translation_batch_service.get(
            canonical_id,
            batch_id,
        ).model_dump(mode="json")
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail="writing reference translation batch not found",
        )


@app.post(
    "/api/projects/{project_id}/medical-writing/references/translation-batches/{batch_id}/retry",
    status_code=202,
)
def retry_writing_reference_translation_batch(
    project_id: str,
    batch_id: str,
    request: WritingReferenceTranslationBatchRetryRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        batch = writing_reference_translation_batch_service.retry(
            canonical_id,
            batch_id,
            request,
        )
        # Durable path: the retry method already created the durable job.
        # Wake the worker for it.  No BackgroundTasks long-call fallback.
        retry_bkey = f"{batch_id}:retry:{request.idempotency_key}"
        retry_job_id = ""
        try:
            from .writing_reference_translation_batch import REFERENCE_TRANSLATION_JOB_TYPE
            record = mw_durable_store.get_by_business_key(
                canonical_id, REFERENCE_TRANSLATION_JOB_TYPE, retry_bkey,
            )
            mw_durable_worker.wake(canonical_id, record.job_id)
            retry_job_id = record.job_id
        except Exception:
            pass  # sweeper recovers the queued retry job
        result = batch.model_dump(mode="json")
        result["durable_job_id"] = retry_job_id
        return result
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail="writing reference translation batch not found",
        )
    except WritingReferenceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/references/"
    "translation-batches/{batch_id}/items/{item_id}/"
    "downstream-contract-transition",
    status_code=202,
    response_model=WritingReferenceTranslationDownstreamTransitionResult,
)
def create_writing_reference_downstream_contract_transition(
    project_id: str,
    batch_id: str,
    item_id: str,
    request: WritingReferenceTranslationDownstreamTransitionRequest,
):
    """Create and enqueue one exact, auditable target-contract child item."""
    try:
        canonical_id = _canonical_module_project_id(
            project_id,
            "medical_writing",
        )
        transition = (
            writing_reference_translation_batch_service
            .create_downstream_contract_transition(
                canonical_id,
                batch_id,
                item_id,
                request,
            )
        )
        job_id = (
            writing_reference_translation_batch_service
            .ensure_reference_translation_job(
                canonical_id,
                transition.target_batch_id,
                actor=request.actor,
            )
        )
        if job_id:
            try:
                mw_durable_worker.wake(canonical_id, job_id)
            except Exception:
                pass
        result = WritingReferenceTranslationDownstreamTransitionResult(
            transition=transition,
            state=(
                writing_reference_translation_batch_service
                .downstream_contract_transition_state(
                    canonical_id,
                    transition.transition_id,
                )
            ),
            target_batch=writing_reference_translation_batch_service.get(
                canonical_id,
                transition.target_batch_id,
            ),
            durable_job_id=job_id or "",
        )
        return result.model_dump(mode="json")
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail="writing reference translation batch/item not found",
        )
    except WritingReferenceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _translation_batch_review_skip_reason(item) -> str:
    if item.generation_status != "candidate_ready":
        return f"generation_{item.generation_status}"
    if item.fidelity_status != "passed":
        return "fidelity_not_passed"
    if item.author_confirmation_status == "returned":
        return "returned"
    if item.author_confirmation_status == "rejected":
        return "rejected"
    if (
        item.author_confirmation_status == "confirmed"
        or item.medical_review_status == "approved"
    ):
        return "already_reviewed"
    if item.admission_status == "invalidated":
        return "admission_invalidated"
    return "not_eligible"


@app.post(
    "/api/projects/{project_id}/medical-writing/references/translation-batches/{batch_id}/medical-review"
)
def batch_review_writing_reference_translations(
    project_id: str,
    batch_id: str,
    request: WritingReferenceTranslationBatchMedicalReviewRequest,
):
    """Approve explicitly pinned eligible candidates in one frozen batch.

    Eligibility is re-projected from current state at request time: only
    ``candidate_ready`` rows whose fidelity gate passed and that have no
    author confirmation yet are approved. Returned, rejected, blocked,
    already-reviewed, and stale rows are reported per item, never silently
    approved. The request must name every exact translation revision that the
    writer reviewed; the server never expands an empty selection.
    """
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        batch = writing_reference_translation_batch_service.get(
            canonical_id, batch_id
        )
        eligible_keys: set[tuple[str, int]] = set()
        current_items = {}
        for item in batch.items:
            if not item.translation_id or item.translation_revision < 1:
                continue
            current_items[item.translation_id] = item
            if (
                item.generation_status == "candidate_ready"
                and item.fidelity_status == "passed"
                and item.medical_review_status == "not_reviewed"
                and item.author_confirmation_status == "not_confirmed"
                and item.admission_status != "invalidated"
            ):
                eligible_keys.add((item.translation_id, item.translation_revision))
        skipped: list[WritingReferenceTranslationBatchReviewItemOutcome] = []
        candidates: list[tuple[str, int]] = []
        for target in request.targets:
            key = (target.translation_id, target.translation_revision)
            if key in eligible_keys:
                candidates.append(key)
                continue
            current = current_items.get(target.translation_id)
            if current is None:
                skipped.append(
                    WritingReferenceTranslationBatchReviewItemOutcome(
                        translation_id=target.translation_id,
                        translation_revision=target.translation_revision,
                        outcome="skipped",
                        reason="not_in_batch",
                    )
                )
            elif current.translation_revision != target.translation_revision:
                skipped.append(
                    WritingReferenceTranslationBatchReviewItemOutcome(
                        translation_id=target.translation_id,
                        translation_revision=target.translation_revision,
                        outcome="stale",
                        reason=(
                            "translation revision changed: "
                            f"requested={target.translation_revision}, "
                            f"current={current.translation_revision}"
                        ),
                    )
                )
            else:
                skipped.append(
                    WritingReferenceTranslationBatchReviewItemOutcome(
                        translation_id=target.translation_id,
                        translation_revision=target.translation_revision,
                        outcome="skipped",
                        reason=_translation_batch_review_skip_reason(current),
                    )
                )
        review_outcomes = writing_reference_repository.record_batch_medical_review(
            project_id=canonical_id,
            batch_id=batch_id,
            targets=candidates,
            comment=request.comment,
            actor=request.actor,
            idempotency_key=request.idempotency_key,
        )
        items = skipped + review_outcomes
        return WritingReferenceTranslationBatchMedicalReviewResult(
            batch_id=batch_id,
            project_id=canonical_id,
            approved_count=sum(item.outcome == "approved" for item in items),
            skipped_count=sum(item.outcome == "skipped" for item in items),
            stale_count=sum(item.outcome == "stale" for item in items),
            failed_count=sum(item.outcome == "failed" for item in items),
            items=items,
            actor=request.actor,
            created_at=datetime.now(timezone.utc),
        ).model_dump(mode="json")
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail="writing reference translation batch not found",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/projects/{project_id}/medical-writing/references/documents/upload")
async def upload_writing_reference_document(
    project_id: str,
    file: UploadFile = File(...),
    snapshot_id: str = Form(...),
    nct_id: str = Form(...),
    document_type: str = Form(...),
    document_date: str = Form(""),
    actor: str = Form("medical_manager"),
    idempotency_key: str = Form(...),
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        payload = await file.read(MAX_MANUAL_DOCUMENT_BYTES + 1)
        request = WritingReferenceManualDocumentUploadRequest(
            snapshot_id=snapshot_id,
            nct_id=nct_id,
            document_type=document_type,
            document_date=document_date,
            actor=actor,
            idempotency_key=idempotency_key,
        )
        return writing_reference_document_service.ingest_manual(
            canonical_id,
            request,
            filename=file.filename or "",
            content_type=file.content_type or "",
            payload=payload,
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except WritingReferenceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    finally:
        await file.close()


@app.post(
    "/api/projects/{project_id}/medical-writing/references/documents/{artifact_id}/extract"
)
def extract_writing_reference_document(
    project_id: str,
    artifact_id: str,
    request: WritingReferenceExtractionRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        extraction = writing_reference_extraction_service.extract(
            canonical_id,
            artifact_id,
            actor=request.actor,
            extraction_idempotency_key=request.extraction_idempotency_key,
        )
        if extraction.ocr_consistency_qc.get("triggered"):
            writing_reference_ocr_consistency_service.recheck(
                canonical_id,
                artifact_id,
                idempotency_key=(
                    f"{request.extraction_idempotency_key}:ocr-consistency-recheck"
                ),
            )
        return extraction.model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (WritingReferenceConflictError, WritingReferenceStaleStateError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/references/documents/"
    "{artifact_id}/ocr-consistency-rechecks"
)
def recheck_writing_reference_ocr_consistency(
    project_id: str,
    artifact_id: str,
    request: WritingReferenceOcrConsistencyRecheckRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        result = writing_reference_ocr_consistency_service.recheck(
            canonical_id,
            artifact_id,
            idempotency_key=request.idempotency_key,
        )
        if result is None:
            return {
                "project_id": canonical_id,
                "artifact_id": artifact_id,
                "status": "not_applicable",
            }
        return result.model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (WritingReferenceConflictError, WritingReferenceStaleStateError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/references/"
    "ocr-consistency-reviews/batch-disposition"
)
def batch_dispose_writing_reference_ocr_consistency(
    project_id: str,
    request: WritingReferenceOcrConsistencyBatchDispositionRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        pending = [
            item
            for item in writing_reference_repository.ocr_consistency_qc_reviews(
                canonical_id
            )
            if item.effective_status == "pending_medical_confirmation"
            and item.recheck_id
            and item.recheck_verdict == "review_required"
        ]
        if not pending:
            return {
                "project_id": canonical_id,
                "outcomes": [],
                "status": "nothing_to_confirm",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        targets = [
            {
                "artifact_id": item.artifact_id,
                "extraction_revision": item.extraction_revision,
                "recheck_id": item.recheck_id,
                "recheck_revision": item.recheck_revision,
                "expected_revision": item.disposition_revision,
            }
            for item in pending
        ]
        return writing_reference_repository.record_batch_ocr_consistency_medical_disposition(
            project_id=canonical_id,
            targets=targets,
            decision=request.decision,
            comment=request.comment,
            actor=request.actor,
            idempotency_key=request.idempotency_key,
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (WritingReferenceConflictError, WritingReferenceStaleStateError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/references/documents/{artifact_id}/extraction-reviews"
)
def review_writing_reference_extraction(
    project_id: str,
    artifact_id: str,
    request: WritingReferenceExtractionReviewRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return writing_reference_repository.record_extraction_review(
            project_id=canonical_id,
            artifact_id=artifact_id,
            extraction_revision=request.extraction_revision,
            decision=request.decision,
            confirmed_anchor_coverage=request.confirmed_anchor_coverage,
            unresolved_structure_issues=request.unresolved_structure_issues,
            comment=request.comment,
            actor=request.actor,
            expected_revision=request.expected_revision,
            idempotency_key=request.idempotency_key,
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (WritingReferenceConflictError, WritingReferenceStaleStateError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/references/documents/{artifact_id}/content-validation/override"
)
def override_writing_reference_document_validation(
    project_id: str,
    artifact_id: str,
    request: WritingReferenceDocumentValidationOverrideRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return writing_reference_repository.override_document_validation(
            project_id=canonical_id,
            artifact_id=artifact_id,
            reason=request.reason,
            acknowledged_warning_codes=request.acknowledged_warning_codes,
            actor=request.actor,
            expected_revision=request.expected_revision,
            idempotency_key=request.idempotency_key,
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (WritingReferenceConflictError, WritingReferenceStaleStateError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/projects/{project_id}/medical-writing/references/translations")
def create_writing_reference_translation(
    project_id: str,
    request: WritingReferenceTranslationRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return writing_reference_translation_service.translate(
            canonical_id,
            request,
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (AiExecutionPolicyDenied, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/references/translations/{translation_id}/revisions"
)
def revise_writing_reference_translation(
    project_id: str,
    translation_id: str,
    request: WritingReferenceTranslationRevisionRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return writing_reference_translation_service.revise(
            canonical_id,
            translation_id,
            request,
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (WritingReferenceConflictError, WritingReferenceStaleStateError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (AiExecutionPolicyDenied, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/references/translations/{translation_id}/medical-review"
)
def review_writing_reference_translation(
    project_id: str,
    translation_id: str,
    request: WritingReferenceMedicalReviewRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return writing_reference_repository.record_medical_review(
            project_id=canonical_id,
            translation_id=translation_id,
            translation_revision=request.translation_revision,
            decision=request.decision,
            comment=request.comment,
            actor=request.actor,
            expected_revision=request.expected_revision,
            idempotency_key=request.idempotency_key,
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (WritingReferenceConflictError, WritingReferenceStaleStateError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/references/translations/{translation_id}/admissions"
)
def admit_writing_reference_translation(
    project_id: str,
    translation_id: str,
    request: WritingReferenceAdmissionRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return writing_reference_repository.admit_translation(
            project_id=canonical_id,
            translation_id=translation_id,
            expected_translation_revision=request.expected_translation_revision,
            medical_review_id=request.medical_review_id,
            idempotency_key=request.idempotency_key,
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except WritingReferenceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/projects/{project_id}/medical-writing/references/evidence-briefs")
def get_writing_reference_evidence_briefs(
    project_id: str,
    ich_m11_anchor: Optional[str] = Query(None),
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return [
            item.model_dump(mode="json")
            for item in writing_reference_repository.evidence_briefs(
                canonical_id,
                ich_m11_anchor=ich_m11_anchor,
            )
        ]
    except KeyError:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")


@app.post(
    "/api/projects/{project_id}/medical-writing/references/documents/{artifact_id}/invalidate"
)
def invalidate_writing_reference_document(
    project_id: str,
    artifact_id: str,
    request: WritingReferenceInvalidationRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return writing_reference_repository.invalidate_artifact(
            project_id=canonical_id,
            artifact_id=artifact_id,
            reason=request.reason,
            actor=request.actor,
            expected_revision=request.expected_revision,
            idempotency_key=request.idempotency_key,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (WritingReferenceConflictError, WritingReferenceStaleStateError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/projects/{project_id}/medical-writing/document-session")
def get_medical_writing_document_session(
    project_id: str,
    allow_missing: bool = Query(False),
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_runtime_repository.document_session(canonical_id).model_dump(mode="json")
    except (KeyError, FileNotFoundError, ValueError):
        if allow_missing:
            return {"available": False}
        raise HTTPException(status_code=404, detail=f"medical writing document session not found: {project_id}")


@app.get("/api/projects/{project_id}/medical-writing/study-consistency")
def get_medical_writing_study_consistency(project_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_study_consistency_service.status(canonical_id).model_dump(
            mode="json"
        )
    except (KeyError, FileNotFoundError, ValueError):
        raise HTTPException(
            status_code=404,
            detail=f"medical writing study consistency not found: {project_id}",
        )


@app.get(
    "/api/projects/{project_id}/medical-writing/legacy-authoring-bootstrap"
)
def get_medical_writing_legacy_authoring_bootstrap(
    project_id: str,
    import_idempotency_key: str = Query(""),
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_legacy_authoring_migration_service.status(
            canonical_id,
            import_idempotency_key=import_idempotency_key,
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/legacy-authoring-bootstrap/prepare"
)
def prepare_medical_writing_legacy_authoring_bootstrap(
    project_id: str,
    request: MedicalWritingLegacyAuthoringBootstrapPrepareRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        result = medical_writing_legacy_authoring_migration_service.prepare(
            canonical_id, request
        )
        return JSONResponse(status_code=202, content=result.model_dump(mode="json"))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/legacy-authoring-bootstrap/confirm"
)
def confirm_medical_writing_legacy_authoring_bootstrap(
    project_id: str,
    request: MedicalWritingLegacyAuthoringBootstrapConfirmRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_legacy_authoring_migration_service.confirm(
            canonical_id, request
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except MedicalWritingAuthoringJourneyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/projects/{project_id}/medical-writing/study-consistency/rebind-preview")
def preview_medical_writing_study_rebind(project_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_study_consistency_service.rebind_preview(
            canonical_id
        ).model_dump(mode="json")
    except (KeyError, FileNotFoundError, ValueError):
        raise HTTPException(
            status_code=404,
            detail=f"medical writing study rebind preview not found: {project_id}",
        )


@app.post("/api/projects/{project_id}/medical-writing/study-consistency/rebind")
def apply_medical_writing_study_rebind(
    project_id: str,
    request: MedicalWritingStudyRebindRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_study_consistency_service.apply_rebind(
            canonical_id, request
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (
        RuntimeStoreError,
        StaleRuntimeStateError,
        GreenfieldMedicalWritingConflictError,
        MedicalWritingAuthoringJourneyConflictError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/study-consistency/sections/{section_id}/confirm"
)
def confirm_medical_writing_study_reconciliation(
    project_id: str,
    section_id: str,
    request: MedicalWritingStudyReconciliationConfirmRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_study_consistency_service.confirm_section_reconciliation(
            canonical_id, section_id, request
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (RuntimeStoreError, StaleRuntimeStateError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/projects/{project_id}/medical-writing/document-index")
def get_medical_writing_document_index(project_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        document = medical_writing_runtime_repository.assemble_document_for_export(
            canonical_id,
            "draft_preview",
        )
        return document_index_catalog(document)
    except (KeyError, FileNotFoundError):
        raise HTTPException(
            status_code=404,
            detail=f"medical writing document not found: {project_id}",
        )
    except RuntimeStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/medical-writing/authoring-product-configuration")
def get_medical_writing_authoring_product_configuration():
    return medical_writing_authoring_journey_service.product_configuration()


@app.post("/api/projects/{project_id}/medical-writing/authoring-journey")
def create_medical_writing_authoring_journey(
    project_id: str,
    request: MedicalWritingAuthoringJourneyCreateRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_authoring_journey_service.create(
            canonical_id, request
        ).model_dump(mode="json")
    except MedicalWritingAuthoringJourneyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/projects/{project_id}/medical-writing/authoring-journey")
def get_medical_writing_authoring_journey(
    project_id: str,
    allow_missing: bool = False,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        state = medical_writing_authoring_journey_service.get(canonical_id)
        payload = state.model_dump(mode="json")
        payload["available"] = True
        payload["picos_sha256"] = medical_writing_authoring_journey_service.picos_sha256(
            canonical_id
        )
        rules = state.picos.intervention_rules
        payload["intervention_rules_sha256"] = (
            intervention_rules_sha256(rules)
            if rules is not None and rules.authority.value == "structured"
            else ""
        )
        return payload
    except KeyError as exc:
        if allow_missing:
            return {
                "available": False,
                "project_id": project_id,
            }
        raise HTTPException(status_code=404, detail=str(exc))


@app.get(
    "/api/projects/{project_id}/medical-writing/protocol-assembly-plan"
)
def get_medical_writing_protocol_assembly_plan(project_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_protocol_assembly_plan_service.current_state(
            canonical_id
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except MedicalWritingProtocolAssemblyPlanConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get(
    "/api/projects/{project_id}/medical-writing/protocol-assembly-plan/history"
)
def get_medical_writing_protocol_assembly_plan_history(project_id: str):
    canonical_id = _canonical_module_project_id(project_id, "medical_writing")
    return {
        "project_id": canonical_id,
        "plans": [
            plan.model_dump(mode="json")
            for plan in medical_writing_protocol_assembly_plan_service.history(
                canonical_id
            )
        ],
    }


@app.get(
    "/api/projects/{project_id}/medical-writing/protocol-assembly-plan/audit"
)
def get_medical_writing_protocol_assembly_plan_audit(project_id: str):
    canonical_id = _canonical_module_project_id(project_id, "medical_writing")
    return {
        "project_id": canonical_id,
        "audit": medical_writing_protocol_assembly_plan_service.audit_history(
            canonical_id
        ),
    }


@app.get(
    "/api/projects/{project_id}/medical-writing/protocol-assembly-plan/projections/{projection}"
)
def get_medical_writing_protocol_assembly_plan_projection(
    project_id: str,
    projection: str,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_protocol_assembly_plan_service.consumer_projection(
            canonical_id, projection
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except MedicalWritingProtocolAssemblyPlanConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/protocol-assembly-plan/preview"
)
def preview_medical_writing_protocol_assembly_plan(
    project_id: str,
    request: MedicalWritingProtocolAssemblyPlanPreviewRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_protocol_assembly_plan_service.preview(
            canonical_id, request
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except MedicalWritingProtocolAssemblyPlanConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/protocol-assembly-plan/refresh"
)
def refresh_medical_writing_protocol_assembly_plan(
    project_id: str,
    request: MedicalWritingProtocolAssemblyPlanRefreshRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_protocol_assembly_plan_service.refresh(
            canonical_id, request
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except MedicalWritingProtocolAssemblyPlanConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/protocol-assembly-plan/confirm"
)
def confirm_medical_writing_protocol_assembly_plan(
    project_id: str,
    request: MedicalWritingProtocolAssemblyPlanConfirmRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_protocol_assembly_plan_service.confirm(
            canonical_id, request
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except MedicalWritingProtocolAssemblyPlanConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ---------------------------------------------------------------------------
# Conversational fact intake (IB-optional, generic study-fact collection).
# Idempotent turn/apply endpoints with optimistic revision checks.
# ---------------------------------------------------------------------------


def _fact_intake_scope_or_422(scope: str) -> MedicalWritingFactIntakeScope:
    try:
        return MedicalWritingFactIntakeScope(scope)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"unsupported fact intake scope: {scope}",
        ) from exc


def _server_confirmed_fact_seed(
    project_id: str,
    scope: MedicalWritingFactIntakeScope,
) -> dict[str, str]:
    """Return facts already confirmed in the authoring journey.

    The client cannot submit seed facts. This prevents a second confirmation
    loop for the drug, indication and phase chosen during project creation
    while keeping AI-generated or merely inferred fields out of the seed.
    """

    if scope != MedicalWritingFactIntakeScope.STUDY_FRAMING:
        return {}
    try:
        framing = medical_writing_authoring_journey_service.get(project_id).framing
    except KeyError:
        return {}
    return {
        fact.field_path: fact.value
        for fact in framing.product_profile.evidence_facts
        if fact.user_confirmed and fact.value
    }


@app.post(
    "/api/projects/{project_id}/medical-writing/fact-intake/{scope}",
    status_code=201,
)
def create_medical_writing_fact_intake_conversation(
    project_id: str,
    scope: str,
    request: MedicalWritingFactIntakeConversationCreateRequest,
):
    scope_enum = _fact_intake_scope_or_422(scope)
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        conversation = medical_writing_fact_intake_service.create(
            canonical_id,
            MedicalWritingFactIntakeConversationCreateRequest(
                scope=scope_enum,
                actor=request.actor,
                idempotency_key=request.idempotency_key,
            ),
            initial_confirmed_field_values=_server_confirmed_fact_seed(
                canonical_id,
                scope_enum,
            ),
        )
        payload = conversation.model_dump(mode="json")
        payload["prompt_version"] = MEDICAL_WRITING_FACT_INTAKE_PROMPT_VERSION
        return payload
    except MedicalWritingFactIntakeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get(
    "/api/projects/{project_id}/medical-writing/fact-intake/{scope}"
)
def get_medical_writing_fact_intake_conversation(
    project_id: str,
    scope: str,
    allow_missing: bool = False,
):
    scope_enum = _fact_intake_scope_or_422(scope)
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        conversation = medical_writing_fact_intake_service.get(
            canonical_id, scope_enum
        )
        payload = conversation.model_dump(mode="json")
        payload["available"] = True
        payload["prompt_version"] = MEDICAL_WRITING_FACT_INTAKE_PROMPT_VERSION
        return payload
    except KeyError as exc:
        if allow_missing:
            return {
                "available": False,
                "project_id": project_id,
                "scope": scope_enum.value,
            }
        raise HTTPException(status_code=404, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/fact-intake/{scope}/turns"
)
def post_medical_writing_fact_intake_turn(
    project_id: str,
    scope: str,
    request: MedicalWritingFactIntakeTurnRequest,
):
    scope_enum = _fact_intake_scope_or_422(scope)
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        result = medical_writing_fact_intake_service.turn(
            canonical_id, scope_enum, request
        )
        payload = result.model_dump(mode="json")
        return payload
    except MedicalWritingFactIntakeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/fact-intake/{scope}/apply"
)
def post_medical_writing_fact_intake_apply(
    project_id: str,
    scope: str,
    request: MedicalWritingFactIntakeApplyRequest,
):
    scope_enum = _fact_intake_scope_or_422(scope)
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        result = medical_writing_fact_intake_service.apply(
            canonical_id, scope_enum, request
        )
        return result.model_dump(mode="json")
    except MedicalWritingFactIntakeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get(
    "/api/projects/{project_id}/medical-writing/authoring-journey/study-schema"
)
def get_medical_writing_study_schema(project_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_authoring_journey_service.study_schema_snapshot(
            canonical_id
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get(
    "/api/projects/{project_id}/medical-writing/authoring-journey/study-schema/proposal"
)
def propose_medical_writing_study_schema(project_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_authoring_journey_service.propose_study_schema(
            canonical_id
        ).model_dump(mode="json")
    except PlanConsumptionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except StudySchemaPlanConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/authoring-journey/study-schema/impact-preview"
)
def preview_medical_writing_study_schema_impact(
    project_id: str,
    request: MedicalWritingStudySchemaImpactPreviewRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_authoring_journey_service.study_schema_impact_preview(
            canonical_id, request
        ).model_dump(mode="json")
    except (
        MedicalWritingAuthoringJourneyConflictError,
        PlanConsumptionError,
        StudySchemaPlanConflictError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/authoring-journey/study-schema/commit"
)
def commit_medical_writing_study_schema(
    project_id: str,
    request: MedicalWritingStudySchemaCommitRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_authoring_journey_service.commit_study_schema(
            canonical_id, request
        ).model_dump(mode="json")
    except (
        MedicalWritingAuthoringJourneyConflictError,
        PlanConsumptionError,
        StudySchemaPlanConflictError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/authoring-journey/study-schema/layout"
)
def update_medical_writing_study_schema_layout(
    project_id: str,
    request: MedicalWritingStudySchemaLayoutUpdateRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_authoring_journey_service.update_study_schema_layout(
            canonical_id, request
        ).model_dump(mode="json")
    except MedicalWritingAuthoringJourneyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get(
    "/api/projects/{project_id}/medical-writing/authoring-journey/study-schema.svg"
)
def get_medical_writing_study_schema_svg(project_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        snapshot = medical_writing_authoring_journey_service.study_schema_snapshot(
            canonical_id
        )
        if not snapshot.svg:
            raise KeyError("study schema has not been created")
        return Response(
            content=snapshot.svg,
            media_type="image/svg+xml",
            headers={
                "ETag": f'"{snapshot.svg_sha256}"',
                "X-Study-Schema-Formal-Render": str(
                    snapshot.formal_render_allowed
                ).lower(),
            },
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/working-copies/{section_id}"
    "/study-schema-figure"
)
def project_medical_writing_study_schema_figure(
    project_id: str,
    section_id: str,
    request: MedicalWritingStudySchemaFigureProjectRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        # Document figure insertion is a design-driven projection: pin to one
        # confirmed study_schema_flowchart plan revision or fail closed.
        plan_state = require_plan_for_study_schema(
            canonical_id,
            medical_writing_plan_consumption_helper,
        )
        snapshot = medical_writing_authoring_journey_service.study_schema_snapshot(
            canonical_id
        )
        schema = snapshot.study_schema
        presentation = snapshot.presentation
        if schema is None or presentation is None or not snapshot.svg:
            raise ValueError("study schema must be committed before it can be inserted")
        if not snapshot.formal_render_allowed:
            raise ValueError(
                "study schema still contains unresolved medical-fact blockers"
            )
        if snapshot.journey_revision != request.expected_journey_revision:
            raise MedicalWritingAuthoringJourneyConflictError(
                "authoring journey changed before the study-schema figure was inserted"
            )
        if schema.revision != request.expected_schema_revision:
            raise MedicalWritingAuthoringJourneyConflictError(
                "study-schema semantic revision changed before insertion"
            )
        if presentation.layout_revision != request.expected_layout_revision:
            raise MedicalWritingAuthoringJourneyConflictError(
                "study-schema layout revision changed before insertion"
            )
        section = medical_writing_document_service.section(canonical_id, section_id)
        if not (
            section.node_kind == "study_schema"
            or "study_schema_editor" in section.interaction_types
            or section.section_number == "1.2"
        ):
            raise ValueError(
                "study-schema figures may only be projected into the governed 1.2 section"
            )
        working_copy = medical_writing_runtime_repository.working_copy(
            canonical_id, section_id
        )
        if working_copy.revision != request.expected_working_copy_revision:
            raise StaleRuntimeStateError(
                "working copy changed before the study-schema figure was inserted: "
                f"expected={request.expected_working_copy_revision}, actual={working_copy.revision}"
            )
        svg = snapshot.svg
        png = render_study_schema_png(svg)
        identity = sha256(schema.schema_id.encode("utf-8")).hexdigest()[:24]
        block_id = f"mwgenerated_figure_{identity}"
        existing_index = next(
            (
                index
                for index, block in enumerate(working_copy.content_blocks)
                if block.get("block_id") == block_id
            ),
            None,
        )
        body_order = (
            working_copy.content_blocks[existing_index].get("body_order")
            if existing_index is not None
            else _study_schema_figure_body_order(canonical_id, section_id)
        )
        figure_block = {
            "block_id": block_id,
            "block_type": "figure",
            "figure_id": f"mwfigure_{identity}",
            "figure_kind": "study_schema",
            "title": schema.title,
            "alt_text": f"研究流程图：{schema.title}",
            "body_order": body_order,
            "source_kind": "medical_writing_study_schema",
            "source_locator": (
                "generated:medical_writing_study_schema:"
                f"{schema.schema_id}:r{schema.revision}:layout{presentation.layout_revision}"
            ),
            "editable": False,
            "schema_id": schema.schema_id,
            "schema_revision": schema.revision,
            "schema_state_sha256": schema.state_sha256,
            "layout_revision": presentation.layout_revision,
            "svg": svg,
            "svg_sha256": snapshot.svg_sha256,
            "png_base64": base64.b64encode(png).decode("ascii"),
            "png_sha256": sha256(png).hexdigest(),
            "width_inches": 6.45,
            "bookmark_name": f"mwfig_{identity}",
            "projection_reason": request.reason,
            "projected_by": request.actor,
            "render_contract_version": "medical_writing_study_schema_figure_v1",
        }
        if plan_state is not None and getattr(plan_state, "plan", None) is not None:
            plan = plan_state.plan
            figure_block["protocol_assembly_plan"] = {
                "plan_id": plan.plan_id,
                "plan_revision": plan.revision,
                "plan_sha256": plan.state_sha256,
                "projection": "study_schema_flowchart",
            }
        content_blocks = [dict(block) for block in working_copy.content_blocks]
        if existing_index is None:
            content_blocks.append(figure_block)
        else:
            content_blocks[existing_index] = figure_block
        saved = medical_writing_runtime_repository.save_working_copy(
            canonical_id,
            section_id,
            MedicalWritingWorkingCopySaveRequest(
                document_id=working_copy.document_id,
                expected_revision=working_copy.revision,
                content_blocks=content_blocks,
                actor=request.actor,
                idempotency_key=request.idempotency_key,
            ),
            authorized_generated_blocks={block_id: figure_block},
        )
        return {
            "working_copy": saved.model_dump(mode="json"),
            "figure_block": next(
                block for block in saved.content_blocks if block.get("block_id") == block_id
            ),
            "projection_action": "inserted" if existing_index is None else "updated",
        }
    except (
        MedicalWritingAuthoringJourneyConflictError,
        PlanConsumptionError,
        StudySchemaPlanConflictError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except StaleRuntimeStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'"))
    except (RuntimeStoreError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/working-copies/{section_id}"
    "/intervention-rules-projection"
)
def project_medical_writing_intervention_rules(
    project_id: str,
    section_id: str,
    request: MedicalWritingInterventionRulesProjectRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        journey = medical_writing_authoring_journey_service.get(canonical_id)
        if journey.revision != request.expected_journey_revision:
            raise MedicalWritingAuthoringJourneyConflictError(
                "authoring journey changed before intervention rules were applied: "
                f"expected={request.expected_journey_revision}, actual={journey.revision}"
            )
        rules = journey.picos.intervention_rules
        if rules is None or rules.authority.value != "structured":
            raise ValueError(
                "structured intervention rules must be committed before they can be applied"
            )
        current_rules_sha256 = intervention_rules_sha256(rules)
        if current_rules_sha256 != request.expected_intervention_rules_sha256:
            raise MedicalWritingAuthoringJourneyConflictError(
                "intervention rules changed before they were applied"
            )

        section = medical_writing_document_service.section(canonical_id, section_id)
        panel_sections = {
            "dose_modification_rule_builder": "6.4",
            "non_investigational_intervention_builder": "6.9",
            "concomitant_therapy_rule_builder": "6.10",
        }
        target_section_number = (
            section.section_number
            if section.section_number in {"6.4", "6.9", "6.10"}
            else next(
                (
                    number
                    for interaction, number in panel_sections.items()
                    if interaction in section.interaction_types
                ),
                "",
            )
        )
        if not target_section_number:
            raise ValueError(
                "intervention rules may only be applied to governed sections 6.4, 6.9, or 6.10"
            )

        working_copy = medical_writing_runtime_repository.working_copy(
            canonical_id, section_id
        )
        body_orders = [
            block.get("body_order")
            for block in working_copy.content_blocks
            if isinstance(block.get("body_order"), int)
            and not isinstance(block.get("body_order"), bool)
        ]
        projected_block = build_intervention_rules_projection_block(
            rules=rules,
            section_number=target_section_number,
            journey_id=journey.journey_id,
            journey_revision=journey.revision,
            body_order=max(body_orders, default=-1) + 1,
        )
        merged_blocks, projection_action = merge_intervention_rules_projection_block(
            working_copy.content_blocks,
            projected_block,
            overwrite_medical_edits=request.overwrite_medical_edits,
        )
        authorized_projection_block = next(
            block
            for block in merged_blocks
            if block.get("block_id") == projected_block["block_id"]
        )
        saved = medical_writing_runtime_repository.save_working_copy(
            canonical_id,
            section_id,
            MedicalWritingWorkingCopySaveRequest(
                document_id=working_copy.document_id,
                expected_revision=request.expected_working_copy_revision,
                content_blocks=merged_blocks,
                actor=request.actor,
                idempotency_key=request.idempotency_key,
            ),
            authorized_generated_blocks={
                projected_block["block_id"]: authorized_projection_block
            },
        )
        persisted_block = next(
            block
            for block in saved.content_blocks
            if block.get("block_id") == projected_block["block_id"]
        )
        return {
            "working_copy": saved.model_dump(mode="json"),
            "projection_block": persisted_block,
            "projection_action": projection_action,
            "intervention_rules_sha256": current_rules_sha256,
        }
    except (
        MedicalWritingAuthoringJourneyConflictError,
        InterventionRulesProjectionConflictError,
        RuntimeStoreError,
        StaleRuntimeStateError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/working-copies/{section_id}"
    "/assessment-instrument-appendix"
)
async def project_medical_writing_assessment_instrument_appendix(
    project_id: str,
    section_id: str,
    file: UploadFile = File(...),
    instrument_id: str = Form(...),
    expected_working_copy_revision: int = Form(...),
    actor: str = Form("medical_manager"),
    idempotency_key: str = Form(...),
    dpi: int = Form(DEFAULT_RENDER_DPI),
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        journey = medical_writing_authoring_journey_service.get(canonical_id)
        instruments = (
            journey.picos.assessment_instruments
            if journey.picos is not None
            else []
        )
        instrument = next(
            (
                item
                for item in instruments
                if item.instrument_id == instrument_id.strip()
            ),
            None,
        )
        if instrument is None:
            raise ValueError(
                "assessment instrument must first be selected in the confirmed study design"
            )
        if instrument.confirmation_status != "confirmed":
            raise ValueError(
                "assessment instrument must be confirmed before its source pages are inserted"
            )
        section = medical_writing_document_service.section(canonical_id, section_id)
        section_heading = re.sub(r"\s+", "", section.heading).lower()
        semantic_appendix_section = (
            section.node_kind == "assessment_instrument_appendix"
            or "assessment_instrument_builder" in section.interaction_types
            or "instrument" in section.template_node_id.lower()
            or "量表" in section_heading
            or "评价工具" in section_heading
        )
        legacy_numbered_appendix = (
            section.section_number == "14.2"
            and ("量表" in section_heading or "评价工具" in section_heading)
        )
        if not (semantic_appendix_section or legacy_numbered_appendix):
            raise ValueError(
                "assessment-instrument source pages may only be inserted into the governed instrument section"
            )
        payload = await file.read(MAX_INSTRUMENT_APPENDIX_PDF_BYTES + 1)
        if len(payload) > MAX_INSTRUMENT_APPENDIX_PDF_BYTES:
            raise ValueError(
                "assessment-instrument appendix PDF exceeds the 50 MB limit"
            )
        rendered = await run_in_threadpool(
            render_instrument_pdf_appendix,
            payload,
            instrument_id=instrument.instrument_id,
            title=instrument.canonical_name_zh,
            original_filename=file.filename or f"{instrument.instrument_id}.pdf",
            dpi=dpi,
        )
        working_copy = medical_writing_runtime_repository.working_copy(
            canonical_id, section_id
        )
        if working_copy.revision != expected_working_copy_revision:
            raise StaleRuntimeStateError(
                "working copy changed before the assessment-instrument appendix was inserted: "
                f"expected={expected_working_copy_revision}, actual={working_copy.revision}"
            )
        existing_blocks = [dict(block) for block in working_copy.content_blocks]
        replaced_ids = {
            str(block.get("block_id") or "")
            for block in existing_blocks
            if block.get("block_type") == "appendix_image"
            and block.get("attachment_kind") == "assessment_instrument_page"
            and block.get("instrument_id") == instrument.instrument_id
        }
        retained_blocks = [
            block
            for block in existing_blocks
            if str(block.get("block_id") or "") not in replaced_ids
        ]
        body_orders = [
            int(block["body_order"])
            for block in retained_blocks
            if isinstance(block.get("body_order"), int)
            and not isinstance(block.get("body_order"), bool)
        ]
        appendix_blocks = rendered.content_blocks(
            body_order_start=max(body_orders, default=-1) + 1
        )
        content_blocks = [*retained_blocks, *appendix_blocks]
        authorized = {
            str(block["block_id"]): block for block in appendix_blocks
        }
        saved = medical_writing_runtime_repository.save_working_copy(
            canonical_id,
            section_id,
            MedicalWritingWorkingCopySaveRequest(
                document_id=working_copy.document_id,
                expected_revision=working_copy.revision,
                content_blocks=content_blocks,
                actor=actor,
                idempotency_key=idempotency_key,
            ),
            authorized_generated_blocks=authorized,
            authorized_removed_appendix_block_ids=replaced_ids,
        )
        return {
            "working_copy": saved.model_dump(mode="json"),
            "instrument_id": instrument.instrument_id,
            "instrument_title": instrument.canonical_name_zh,
            "source_filename": rendered.original_filename,
            "source_pdf_sha256": rendered.source_pdf_sha256,
            "render_dpi": rendered.render_dpi,
            "page_count": len(rendered.pages),
            "target_section_id": section.section_id,
            "target_section_number": section.section_number,
            "target_section_heading": section.heading,
            "projection_action": "replaced" if replaced_ids else "inserted",
            "replaced_page_count": len(replaced_ids),
        }
    except StaleRuntimeStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/medical-writing/project-intake/synopsis",
)
async def start_file_first_synopsis_project_intake(
    file: UploadFile = File(...),
    actor: str = Form("medical_manager"),
    idempotency_key: str = Form(...),
):
    """Parse a synopsis before a canonical project exists.

    The intake identifier is deliberately separate from a project identifier.
    No placeholder project is exposed in the project list.
    """

    try:
        actor = actor.strip()
        idempotency_key = idempotency_key.strip()
        if not actor or not idempotency_key:
            raise ValueError("synopsis intake actor and idempotency key must not be blank")
        payload = await file.read(MAX_SYNOPSIS_BYTES + 1)
        if len(payload) > MAX_SYNOPSIS_BYTES:
            raise ValueError("protocol synopsis file exceeds 30 MiB")
        if not payload:
            raise ValueError("protocol synopsis file is empty")
        content_sha256 = sha256(payload).hexdigest()
        intake_id = "mwintake_" + sha256(
            f"{idempotency_key}|{content_sha256}".encode("utf-8")
        ).hexdigest()[:24]
        started = medical_writing_synopsis_import_service.start_job(
            intake_id,
            filename=file.filename or "study-synopsis",
            content_type=file.content_type or "application/octet-stream",
            payload=payload,
            expected_indication="",
            actor=actor,
            idempotency_key=idempotency_key,
        )
        return JSONResponse(
            status_code=202,
            content={
                "intake_id": intake_id,
                **started.model_dump(mode="json"),
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get(
    "/api/medical-writing/project-intake/synopsis/{intake_id}/jobs/{idempotency_key}"
)
def get_file_first_synopsis_project_intake(
    intake_id: str,
    idempotency_key: str,
):
    try:
        return medical_writing_synopsis_import_service.get_job(
            intake_id, idempotency_key
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get(
    "/api/medical-writing/project-intake/synopsis/{intake_id}/jobs/{idempotency_key}/result"
)
def get_file_first_synopsis_project_intake_result(
    intake_id: str,
    idempotency_key: str,
):
    try:
        return medical_writing_synopsis_import_service.get_job_result(
            intake_id, idempotency_key
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post(
    "/api/medical-writing/project-intake/synopsis/{intake_id}/jobs/{idempotency_key}/cancel"
)
def cancel_file_first_synopsis_project_intake(
    intake_id: str,
    idempotency_key: str,
):
    try:
        return medical_writing_synopsis_import_service.cancel_job(
            intake_id, idempotency_key
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post(
    "/api/medical-writing/project-intake/synopsis/{intake_id}/jobs/{idempotency_key}/resume"
)
def resume_file_first_synopsis_project_intake(
    intake_id: str,
    idempotency_key: str,
    actor: str = Form("medical_manager"),
):
    try:
        return medical_writing_synopsis_import_service.resume_job(
            intake_id, idempotency_key, actor=actor
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post(
    "/api/medical-writing/project-intake/synopsis/confirm",
    status_code=201,
)
def confirm_file_first_synopsis_project_intake(
    request: MedicalWritingSynopsisProjectCreateRequest,
):
    """Create the canonical project only after the extracted synopsis is reviewed."""

    try:
        imported = medical_writing_synopsis_import_service.get_job_result(
            request.intake_id,
            request.import_idempotency_key,
        )
        if imported.source is None or imported.source.source_id != request.source_id:
            raise ValueError("the confirmed synopsis source is unavailable or stale")

        created = create_project(
            UserProjectCreateRequest(
                project_name=request.framing.document_title,
                indication=request.framing.indication,
                product_name=request.framing.investigational_product,
                study_phase=request.framing.study_phase,
                protocol_id=request.framing.protocol_id,
                protocol_version=request.framing.version or "草案",
                entry_mode="synopsis_import",
                actor=request.actor,
                idempotency_key=f"file-first-project-{request.idempotency_key}"[:160],
            )
        )
        project_id = created["project"]["project_id"]
        current = medical_writing_authoring_journey_service.get(project_id)
        attached = medical_writing_authoring_journey_service.attach_synopsis_import(
            project_id,
            imported,
            expected_revision=current.revision,
            actor=request.actor,
            idempotency_key=f"{request.idempotency_key}-attach"[:200],
        )
        confirmed = medical_writing_authoring_journey_service.confirm_synopsis_import(
            project_id,
            MedicalWritingSynopsisImportConfirmRequest(
                expected_revision=attached.revision,
                source_id=request.source_id,
                framing=request.framing,
                picos=request.picos,
                synopsis_text=request.synopsis_text,
                acknowledged_validation_warnings=request.acknowledged_validation_warnings,
                validation_override_reason=request.validation_override_reason,
                actor=request.actor,
                idempotency_key=f"{request.idempotency_key}-confirm"[:200],
            ),
        )

        # The single user confirmation is authoritative. Promote complete
        # extracted stages immediately; incomplete stages remain drafts that
        # ask only for genuinely missing facts.
        if not request.framing.missing_required_fields():
            preview_request = MedicalWritingJourneyImpactPreviewRequest(
                expected_revision=confirmed.revision,
                stage="framing",
                framing=request.framing,
            )
            preview = medical_writing_authoring_journey_service.impact_preview(
                project_id, preview_request
            )
            confirmed = medical_writing_authoring_journey_service.commit_stage(
                project_id,
                MedicalWritingAuthoringJourneyCommitRequest(
                    expected_revision=confirmed.revision,
                    stage="framing",
                    framing=request.framing,
                    impact_preview_id=preview.preview_id if preview.requires_confirmation else "",
                    actor=request.actor,
                    idempotency_key=f"{request.idempotency_key}-framing"[:200],
                ),
            )
        if (
            confirmed.framing_complete
            and not request.picos.missing_required_fields()
        ):
            preview_request = MedicalWritingJourneyImpactPreviewRequest(
                expected_revision=confirmed.revision,
                stage="picos",
                picos=request.picos,
            )
            preview = medical_writing_authoring_journey_service.impact_preview(
                project_id, preview_request
            )
            confirmed = medical_writing_authoring_journey_service.commit_stage(
                project_id,
                MedicalWritingAuthoringJourneyCommitRequest(
                    expected_revision=confirmed.revision,
                    stage="picos",
                    picos=request.picos,
                    impact_preview_id=preview.preview_id if preview.requires_confirmation else "",
                    actor=request.actor,
                    idempotency_key=f"{request.idempotency_key}-picos"[:200],
                ),
            )
        return {
            "project": project_source_manifest_service.build_manifest(
                project_id
            ).public_project_dict(),
            "entry_mode": "synopsis_import",
            "next_route": f"/api/projects/{project_id}/medical-writing/authoring-journey",
            "authoring_journey": confirmed.model_dump(mode="json"),
        }
    except MedicalWritingAuthoringJourneyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/authoring-journey/synopsis-import"
)
async def import_medical_writing_protocol_synopsis(
    project_id: str,
    file: UploadFile = File(...),
    expected_revision: int = Form(...),
    actor: str = Form("medical_manager"),
    idempotency_key: str = Form(...),
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        current = medical_writing_authoring_journey_service.get(canonical_id)
        if current.revision != expected_revision:
            raise MedicalWritingAuthoringJourneyConflictError(
                f"stale authoring journey revision: expected {expected_revision}, current {current.revision}"
            )
        header = project_source_manifest_service.build_manifest(
            canonical_id
        ).header_project
        payload = await file.read(MAX_SYNOPSIS_BYTES + 1)
        if len(payload) > MAX_SYNOPSIS_BYTES:
            raise ValueError("protocol synopsis file exceeds 30 MiB")
        start_response = medical_writing_synopsis_import_service.start_job(
            canonical_id,
            filename=file.filename or "study-synopsis",
            content_type=file.content_type or "application/octet-stream",
            payload=payload,
            expected_indication=header.indication,
            actor=actor,
            idempotency_key=idempotency_key,
        )
        # Return 202 immediately — AI runs in background.
        return JSONResponse(
            status_code=202,
            content={
                "job_id": start_response.job_id,
                "idempotency_key": start_response.idempotency_key,
                "status": start_response.status,
                "phase": start_response.phase,
                "content_sha256": start_response.content_sha256,
                "span_count": start_response.span_count,
                "media_type": start_response.media_type,
                "warnings": start_response.warnings,
            },
        )
    except MedicalWritingAuthoringJourneyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get(
    "/api/projects/{project_id}/medical-writing/authoring-journey/synopsis-import/jobs/{idempotency_key}"
)
def get_medical_writing_synopsis_import_job(
    project_id: str,
    idempotency_key: str,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_synopsis_import_service.get_job(
            canonical_id, idempotency_key
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get(
    "/api/projects/{project_id}/medical-writing/authoring-journey/synopsis-import/jobs/{idempotency_key}/result"
)
def get_medical_writing_synopsis_import_job_result(
    project_id: str,
    idempotency_key: str,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        result = medical_writing_synopsis_import_service.get_job_result(
            canonical_id, idempotency_key
        )
        journey = medical_writing_authoring_journey_service.attach_synopsis_import(
            canonical_id,
            result,
            expected_revision=medical_writing_authoring_journey_service.get(
                canonical_id
            ).revision,
            actor="medical_manager",
            idempotency_key=idempotency_key,
        )
        return journey.model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except MedicalWritingAuthoringJourneyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/authoring-journey/synopsis-import/jobs/{idempotency_key}/cancel"
)
def cancel_medical_writing_synopsis_import_job(
    project_id: str,
    idempotency_key: str,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_synopsis_import_service.cancel_job(
            canonical_id, idempotency_key
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/authoring-journey/synopsis-import/jobs/{idempotency_key}/resume"
)
def resume_medical_writing_synopsis_import_job(
    project_id: str,
    idempotency_key: str,
    actor: str = Form("medical_manager"),
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_synopsis_import_service.resume_job(
            canonical_id, idempotency_key, actor=actor
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/authoring-journey/synopsis-import/confirm"
)
def confirm_medical_writing_protocol_synopsis(
    project_id: str,
    request: MedicalWritingSynopsisImportConfirmRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_authoring_journey_service.confirm_synopsis_import(
            canonical_id, request
        ).model_dump(mode="json")
    except MedicalWritingAuthoringJourneyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ---------------------------------------------------------------------------
# Unified durable medical-writing job API.
#
# These routes are the authoritative status/result/cancel/retry surface for
# all three long-AI job types (competitor_triage, section_ai_candidate,
# reference_translation).  The response never serializes the internal
# DurableJobRecord directly — it excludes claim_token, raw payload_json, lease
# internals, and any provider prompt/source payload not already authorized for
# the UI.
# ---------------------------------------------------------------------------

def _public_durable_job_dict(record) -> dict:
    """Build a UI-safe dict from a DurableJobRecord.

    Excludes: claim_token, lease_expires_at, payload_json, input_hash,
    output_hash, and other internals not needed for progress display.
    """
    progress = record.progress
    return {
        "job_id": record.job_id,
        "project_id": record.project_id,
        "job_type": record.job_type,
        "status": record.status,
        "attempt_count": record.attempt_count,
        "max_attempts": record.max_attempts,
        "progress": {
            "phase": progress.phase,
            "percent": progress.percent,
            "step": progress.step,
            "step_total": progress.step_total,
            "message": progress.message,
        },
        "error_summary": record.error_summary,
        "artifact_locator": record.artifact_locator,
        "provider": record.provider,
        "model": record.model,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "finished_at": record.finished_at.isoformat() if record.finished_at else None,
        "cancelled_at": record.cancelled_at.isoformat() if record.cancelled_at else None,
    }


def _api_result_payload(result):
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    if is_dataclass(result):
        return asdict(result)
    raise TypeError(f"unsupported API result type: {type(result).__name__}")


@app.get(
    "/api/projects/{project_id}/medical-writing/jobs/{job_id}"
)
def get_durable_mw_job(project_id: str, job_id: str):
    """Unified job status — authoritative for all durable MW job types."""
    canonical_id = _canonical_module_project_id(project_id, "medical_writing")
    try:
        record = mw_durable_store.get(canonical_id, job_id)
    except DurableJobNotFound:
        raise HTTPException(status_code=404, detail=f"durable job not found: {job_id}")
    return _public_durable_job_dict(record)


@app.get(
    "/api/projects/{project_id}/medical-writing/jobs/{job_id}/result"
)
def get_durable_mw_job_result(project_id: str, job_id: str):
    """Unified job result — returns the artifact_locator and parsed payload.

    The actual business artifact (triage run, revision thread, translation
    batch) should be fetched via its own read endpoint using the locator.
    This route returns only the locator and job metadata.
    """
    canonical_id = _canonical_module_project_id(project_id, "medical_writing")
    try:
        record = mw_durable_store.get(canonical_id, job_id)
    except DurableJobNotFound:
        raise HTTPException(status_code=404, detail=f"durable job not found: {job_id}")
    if record.status not in ("completed", "failed", "cancelled"):
        raise HTTPException(status_code=409, detail=f"job not terminal: {record.status}")
    result = _public_durable_job_dict(record)
    # Parse the artifact locator for convenience.
    if record.artifact_locator:
        try:
            result["artifact"] = json.loads(record.artifact_locator)
        except (json.JSONDecodeError, TypeError):
            result["artifact"] = {}
    return result


@app.post("/api/projects/{project_id}/medical-writing/full-drafts", status_code=202)
def start_medical_writing_full_draft(project_id: str, request: dict):
    """Create/reuse a source-bound project-level full-draft candidate job."""
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        actor = str(request.get("actor") or "medical_manager")
        job_id, reused = medical_writing_full_draft_service.submit_durable(
            canonical_id,
            mw_durable_store,
            actor=actor,
        )
        record = mw_durable_store.get(canonical_id, job_id)
        if record.status not in {"completed", "failed", "cancelled"}:
            try:
                mw_durable_worker.wake(canonical_id, job_id)
            except Exception:
                pass
        return {
            "job_id": job_id,
            "status": record.status,
            "reused": reused,
            "job_type": FULL_DRAFT_JOB_TYPE,
        }
    except (KeyError, FileNotFoundError):
        raise HTTPException(status_code=404, detail=f"medical writing project not found: {project_id}")
    except DurableJobRequestConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (RuntimeStoreError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/api/projects/{project_id}/medical-writing/full-drafts/current")
def get_current_medical_writing_full_draft(project_id: str):
    """Rediscover the newest completed candidate that still targets this draft."""
    canonical_id = _canonical_module_project_id(project_id, "medical_writing")
    records = mw_durable_store.list_by_project(
        canonical_id,
        job_type=FULL_DRAFT_JOB_TYPE,
        status="completed",
    )
    for record in reversed(records):
        if medical_writing_full_draft_service.candidate_is_current(canonical_id, record):
            return _public_durable_job_dict(record)
    return Response(status_code=204)


@app.get("/api/projects/{project_id}/medical-writing/full-drafts/{job_id}/result")
def get_medical_writing_full_draft_result(project_id: str, job_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        record = mw_durable_store.get(canonical_id, job_id)
        if record.job_type != FULL_DRAFT_JOB_TYPE:
            raise HTTPException(status_code=404, detail=f"full-draft job not found: {job_id}")
        artifact = medical_writing_full_draft_service.read_artifact(canonical_id, record)
        return {
            "job_id": job_id,
            "project_id": canonical_id,
            "status": record.status,
            "artifact": artifact,
        }
    except HTTPException:
        raise
    except DurableJobNotFound:
        raise HTTPException(status_code=404, detail=f"durable job not found: {job_id}")
    except RuntimeStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


def _confirm_full_draft_decision_in_study_definition(
    project_id: str,
    *,
    decisions: list[dict[str, Any]],
    expected_journey_revision: int,
    authoring_journey_binding: dict[str, Any],
    actor: str,
    idempotency_key: str,
):
    """Persist one related decision group in the existing journey transaction.

    The original journey revision is part of the immutable full-draft
    artifact.  Repeating the same operation therefore reaches commit_stage's
    idempotent replay before its stale-revision check, including after facts
    committed but the continuation job response was lost.
    """
    journey = medical_writing_authoring_journey_service.get(project_id)
    roots = {str(item.get("fact_path") or "").partition(".")[0] for item in decisions}
    if len(roots) != 1 or next(iter(roots), "") not in {"framing", "picos"}:
        raise ValueError("相关决定必须属于同一研究设计阶段，才能一次确认")
    stage = next(iter(roots))
    model = getattr(journey, stage)
    payload = authoring_journey_binding.get(stage)
    if not isinstance(payload, dict):
        raise ValueError("全文初稿缺少原研究设计快照，决定未写入")
    payload = json.loads(json.dumps(payload, ensure_ascii=False))
    for item in decisions:
        path = str(item.get("fact_path") or "")
        value = item.get("value")
        tokens = path.split(".")[1:]
        if not tokens:
            raise ValueError(f"决定字段路径无效：{path}")
        cursor = payload
        for token in tokens[:-1]:
            if not isinstance(cursor, dict) or token not in cursor:
                raise ValueError(f"决定字段路径不存在：{path}")
            cursor = cursor[token]
        if not isinstance(cursor, dict) or tokens[-1] not in cursor:
            raise ValueError(f"决定字段路径不存在：{path}")
        cursor[tokens[-1]] = value
    updated = type(model).model_validate(payload)
    preview_request = MedicalWritingJourneyImpactPreviewRequest(
        expected_revision=expected_journey_revision,
        stage=stage,
        **{stage: updated},
    )
    if journey.revision == expected_journey_revision:
        preview_id = medical_writing_authoring_journey_service.impact_preview(
            project_id, preview_request
        ).preview_id
    else:
        # Recovery after a successful commit must recreate the exact original
        # commit request so commit_stage can replay it before checking the now
        # stale expected revision. impact_preview compares top-level stage
        # fields, even when the decision path itself is nested.
        changed_fields = sorted({
            ".".join(str(item.get("fact_path") or "").split(".")[:2])
            for item in decisions
        })
        dependents = sorted({
            dependent
            for field_path in changed_fields
            for dependent in medical_writing_authoring_journey_service._IMPACT_MAP.get(
                field_path, []
            )
        })
        preview_payload = {
            "project_id": project_id,
            "expected_revision": expected_journey_revision,
            "stage": stage,
            "changed_fields": changed_fields,
            "affected_dependents": dependents,
        }
        preview_id = "mwimpact_" + sha256(json.dumps(
            preview_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")).hexdigest()[:24]
    return medical_writing_authoring_journey_service.commit_stage(
        project_id,
        MedicalWritingAuthoringJourneyCommitRequest(
            expected_revision=expected_journey_revision,
            stage=stage,
            impact_preview_id=preview_id,
            actor=actor,
            idempotency_key=idempotency_key,
            **{stage: updated},
        ),
    )


@app.post("/api/projects/{project_id}/medical-writing/full-drafts/{job_id}/decisions")
def resolve_medical_writing_full_draft_decision(
    project_id: str,
    job_id: str,
    request: dict,
):
    """Resolve full-draft decision cards in one explicit confirmation.

    The confirmed answer is written through the existing authoritative
    StudyDefinition confirmation path, this artifact becomes stale under the
    unchanged binding check, and a new full-draft job is submitted for the
    affected sections only.  An unbound decision fails closed.
    """
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        record = mw_durable_store.get(canonical_id, job_id)
        if record.job_type != FULL_DRAFT_JOB_TYPE:
            raise HTTPException(status_code=404, detail=f"full-draft job not found: {job_id}")
        result = medical_writing_full_draft_service.resolve_decision(
            canonical_id,
            mw_durable_store,
            record,
            decisions=request.get("decisions") or [],
            idempotency_key=str(request.get("idempotency_key") or ""),
            actor=str(request.get("actor") or "medical_manager"),
            study_definition_writer=_confirm_full_draft_decision_in_study_definition,
        )
        regenerated = result.get("regeneration") or {}
        regenerated_id = str(regenerated.get("job_id") or "")
        if regenerated_id and not regenerated.get("reused"):
            try:
                mw_durable_worker.wake(canonical_id, regenerated_id)
            except Exception:
                pass
        return result
    except HTTPException:
        raise
    except DurableJobNotFound:
        raise HTTPException(status_code=404, detail=f"durable job not found: {job_id}")
    except MedicalWritingAuthoringJourneyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (RuntimeStoreError, StaleRuntimeStateError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/projects/{project_id}/medical-writing/full-drafts/{job_id}/adopt")
def adopt_medical_writing_full_draft(project_id: str, job_id: str, request: dict):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        record = mw_durable_store.get(canonical_id, job_id)
        if record.job_type != FULL_DRAFT_JOB_TYPE:
            raise HTTPException(status_code=404, detail=f"full-draft job not found: {job_id}")
        result = medical_writing_full_draft_service.adopt(
            canonical_id,
            record,
            actor=str(request.get("actor") or "medical_manager"),
            confirmed_section_ids=request.get("confirmed_section_ids") or [],
        )
        return result
    except HTTPException:
        raise
    except DurableJobNotFound:
        raise HTTPException(status_code=404, detail=f"durable job not found: {job_id}")
    except (RuntimeStoreError, StaleRuntimeStateError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/jobs/{job_id}/cancel"
)
def cancel_durable_mw_job(project_id: str, job_id: str):
    """Cancel a durable MW job.  Terminal jobs are no-op; running jobs are
    cancelled cooperatively (the executor's cancel_check will return True)."""
    canonical_id = _canonical_module_project_id(project_id, "medical_writing")
    try:
        result = mw_durable_store.cancel(canonical_id, job_id)
    except DurableJobNotFound:
        raise HTTPException(status_code=404, detail=f"durable job not found: {job_id}")
    return {
        "job_id": result.job_id,
        "status": result.status,
        "cancelled": result.cancelled,
    }


@app.post(
    "/api/projects/{project_id}/medical-writing/jobs/{job_id}/retry"
)
def retry_durable_mw_job(project_id: str, job_id: str):
    """Retry a failed/retry_wait/cancelled durable MW job.

    Returns 409 if the job is queued/running/completed (not retryable).
    """
    canonical_id = _canonical_module_project_id(project_id, "medical_writing")
    try:
        result = mw_durable_store.retry(canonical_id, job_id)
    except DurableJobNotFound:
        raise HTTPException(status_code=404, detail=f"durable job not found: {job_id}")
    if not result.requeued:
        raise HTTPException(
            status_code=409,
            detail=f"job is not retryable in status: {result.status}",
        )
    # Wake the worker for the retried job.
    try:
        mw_durable_worker.wake(canonical_id, job_id)
    except Exception:
        pass  # sweeper will pick it up
    return {
        "job_id": result.job_id,
        "status": result.status,
        "requeued": result.requeued,
    }



@app.post(
    "/api/projects/{project_id}/medical-writing/research-pipeline/start"
)
def start_medical_writing_research_pipeline(project_id: str, request: dict):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_research_pipeline_service.start(
            canonical_id,
            actor=str(request.get("actor") or "medical_manager"),
            idempotency_key=str(request.get("idempotency_key") or ""),
            auto_confirm_triage=bool(request.get("auto_confirm_triage") or False),
            force=bool(request.get("force") or False),
        )
    except ResearchPipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ResearchPipelineConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get(
    "/api/projects/{project_id}/medical-writing/research-pipeline/status"
)
def get_medical_writing_research_pipeline_status(project_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_research_pipeline_service.status(canonical_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/research-pipeline/cancel"
)
def cancel_medical_writing_research_pipeline(project_id: str, request: dict):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        state = medical_writing_research_pipeline_service.cancel(
            canonical_id, actor=str(request.get("actor") or "medical_manager")
        )
        return {"pipeline": state.as_dict()}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/research-pipeline/continue-after-triage"
)
def continue_medical_writing_research_pipeline_after_triage(project_id: str, request: dict):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        retained = request.get("retained_candidate_ids") or None
        state = medical_writing_research_pipeline_service.continue_after_triage(
            canonical_id,
            actor=str(request.get("actor") or "medical_manager"),
            retained_candidate_ids=list(retained) if retained else None,
        )
        return {"pipeline": state.as_dict()}
    except ResearchPipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/research-pipeline/resume"
)
def resume_medical_writing_research_pipeline(project_id: str, request: dict):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        state = medical_writing_research_pipeline_service.resume_waiting(
            canonical_id,
            actor=str(request.get("actor") or "medical_manager"),
            idempotency_key=str(request.get("idempotency_key") or ""),
            expected_pipeline_id=str(request.get("expected_pipeline_id") or ""),
            expected_stage=str(request.get("expected_stage") or ""),
        )
        return {"pipeline": state.as_dict()}
    except ResearchPipelineConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ResearchPipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/research-pipeline/retry-triage",
    status_code=202,
)
def retry_medical_writing_research_pipeline_triage(
    project_id: str, request: dict
):
    """Resume the same frozen competitor-triage run without replaying search."""
    try:
        canonical_id = _canonical_module_project_id(
            project_id, "medical_writing"
        )
        return medical_writing_research_pipeline_service.retry_triage(
            canonical_id,
            actor=str(request.get("actor") or "medical_manager"),
            idempotency_key=str(request.get("idempotency_key") or ""),
            expected_pipeline_id=str(
                request.get("expected_pipeline_id") or ""
            ),
            expected_triage_run_id=str(
                request.get("expected_triage_run_id") or ""
            ),
        )
    except ResearchPipelineConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ResearchPipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except CompetitorTriageConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except MedicalWritingAuthoringJourneyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except CompetitorTriageStaleError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except CompetitorTriageError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/research-pipeline/round2"
)
def start_medical_writing_research_pipeline_round2(project_id: str, request: dict):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_research_pipeline_service.start_round2_after_design(
            canonical_id,
            actor=str(request.get("actor") or "medical_manager"),
            idempotency_key=str(request.get("idempotency_key") or ""),
        )
    except ResearchPipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/authoring-journey/competitor-search"
)
def execute_medical_writing_authoring_competitor_search(
    project_id: str,
    request: MedicalWritingCompetitorSearchExecuteRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        search_request = medical_writing_authoring_journey_service.build_competitor_search_request(
            canonical_id, request
        )
        snapshot = writing_reference_discovery_service.create_search_snapshot(
            canonical_id, search_request
        )
        # Dual-registry: CT.gov primary; ChinaDrugTrials secondary probe (WAF-aware).
        secondary_meta: dict = {}
        try:
            from .medical_writing_authoring_prefill import effective_authoring_values
            from .medical_writing_chinadrugtrials_client import (
                ChinaDrugTrialsClient,
                dual_registry_partial_failure,
            )

            journey_before = medical_writing_authoring_journey_service.get(canonical_id)
            framing_before, _ = effective_authoring_values(journey_before)
            china_intent = ChinaDrugTrialsClient().probe_and_search(
                indication_zh=framing_before.indication or "",
                study_phase=framing_before.study_phase or "",
                product_name=framing_before.investigational_product or "",
            )
            secondary_meta = {
                "chinadrugtrials": china_intent.as_dict(),
                "dual_registry": {
                    "primary": "clinicaltrials.gov",
                    "secondary": "chinadrugtrials.org.cn",
                    "secondary_status": china_intent.status,
                },
            }
            failure = dual_registry_partial_failure(china_intent)
            if failure:
                secondary_meta["partial_failure"] = failure
        except Exception as exc:  # noqa: BLE001 — never block CT.gov search
            secondary_meta = {
                "chinadrugtrials": {
                    "status": "probe_exception",
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            }
        journey = medical_writing_authoring_journey_service.attach_search_snapshot(
            canonical_id, snapshot, request
        )
        payload = journey.model_dump(mode="json")
        payload["dual_registry"] = secondary_meta
        return payload
    except (MedicalWritingAuthoringJourneyConflictError, WritingReferenceConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get(
    "/api/projects/{project_id}/medical-writing/authoring-journey/prefill-package"
)
def get_medical_writing_authoring_prefill_package(project_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        journey = medical_writing_authoring_journey_service.get(canonical_id)
        package = journey.prefill_package
        if package is None:
            raise KeyError("no prefill package exists for this project")
        return package.model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/authoring-journey/prefill-package/generate"
)
def generate_medical_writing_authoring_prefill_package(
    project_id: str,
    request: AuthoringPrefillGenerateRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        ai_enricher = _build_prefill_ai_enricher()

        # W2b-2: Inject the precise immutable snapshot bound to the current
        # search plan.  Read journey → search_plan.latest_snapshot_id →
        # repository.search_snapshot(canonical_id, snapshot_id).
        # If the snapshot is claimed but missing from the repository, fail
        # closed to "no snapshot" and record a partial failure; never
        # silently use "latest other snapshot".
        snapshot = None
        journey = medical_writing_authoring_journey_service.get(canonical_id)
        sp = journey.search_plan
        if sp is not None and sp.latest_snapshot_id:
            try:
                snapshot = writing_reference_repository.search_snapshot(
                    canonical_id, sp.latest_snapshot_id
                )
            except KeyError:
                snapshot = None
                # The deterministic prefill already records
                # search_snapshot_unavailable when snapshot is None but
                # latest_snapshot_id is set; we preserve that behaviour by
                # passing snapshot=None to generate_prefill.

        return medical_writing_authoring_journey_service.generate_prefill(
            canonical_id, request, snapshot=snapshot, ai_enricher=ai_enricher
        ).model_dump(mode="json")
    except MedicalWritingAuthoringJourneyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _build_authoring_prefill_evidence_verifier(canonical_id: str):
    """Build a lazy live-catalog evidence verifier for authoring-prefill
    adoption (single-candidate and composite endpoints).

    The resolver reconstructs the live server catalog from the current
    journey and the writing-reference snapshot bound to the package's
    search_snapshot_id, and raises ValueError on any identity drift.  It is
    only called when the first non-override evidence path needs
    verification.
    """
    from .medical_writing_authoring_prefill import (
        ServerEvidenceVerifier,
        effective_authoring_values,
    )
    from .medical_writing_authoring_prefill_corpus_bridge import (
        corpus_analysis_reader_for_repository,
        corpus_source_reader_for_repository,
    )
    from .medical_writing_authoring_prefill_evidence import build_evidence_catalog

    def _catalog_resolver():
        journey = medical_writing_authoring_journey_service.get(canonical_id)
        pkg = journey.prefill_package
        if pkg is None:
            raise ValueError("prefill package is missing during evidence verification")
        if pkg.project_id != canonical_id:
            raise ValueError("prefill package project does not match current project")
        if pkg.journey_revision != journey.revision:
            # The journey moved past the package.  This is normally a stage
            # draft save or synopsis confirmation (both bump the revision
            # while the package keeps its generation revision) — the only
            # deterministic recovery is regeneration, which rebinds the
            # catalog to the effective (draft-wins) state.  Name the draft
            # when one diverges so callers get a precise diagnosis instead
            # of a generic tamper/stale error.
            effective_framing, effective_picos = effective_authoring_values(
                journey
            )
            draft_note = ""
            if (
                effective_framing != journey.framing
                or effective_picos != journey.picos
            ):
                draft_note = (
                    "; a stage draft diverges from the persisted "
                    "framing/picos — regenerate the prefill package to "
                    "rebind the evidence catalog"
                )
            raise ValueError(
                "prefill package journey revision is stale: expected "
                f"{journey.revision}, package {pkg.journey_revision}"
                f"{draft_note}"
            )

        planned_snapshot_id = (
            journey.search_plan.latest_snapshot_id
            if journey.search_plan is not None
            else ""
        )
        snapshot_id = pkg.search_snapshot_id
        if snapshot_id != planned_snapshot_id:
            raise ValueError(
                "prefill package snapshot does not match the current search plan"
            )

        snapshot = None
        if snapshot_id:
            try:
                snapshot = writing_reference_repository.search_snapshot(
                    canonical_id, snapshot_id
                )
            except KeyError as exc:
                raise ValueError(
                    "prefill evidence snapshot is no longer available"
                ) from exc
            if snapshot.project_id != canonical_id:
                raise ValueError(
                    "prefill evidence snapshot project does not match current project"
                )
            if snapshot.snapshot_id != snapshot_id:
                raise ValueError(
                    "prefill evidence snapshot identity does not match requested snapshot"
                )

        # Generation builds the evidence catalog from the draft-wins
        # effective state (``effective_authoring_values``).  The live
        # resolver must rebuild from the same effective state, otherwise a
        # divergent uncommitted stage draft makes the persisted and live
        # catalogs differ and every evidence-bound adoption fails closed
        # with a misleading tamper/stale diagnosis.  Tamper/stale checks are
        # unchanged: any real drift still fails the full-dump equality.
        effective_framing, effective_picos = effective_authoring_values(journey)
        if (
            effective_framing != journey.framing
            or effective_picos != journey.picos
        ):
            journey = journey.model_copy(
                update={
                    "framing": effective_framing,
                    "picos": effective_picos,
                },
                deep=True,
            )
        catalog = build_evidence_catalog(
            journey,
            snapshot=snapshot,
            corpus_analysis_reader=corpus_analysis_reader_for_repository(
                writing_reference_repository
            ),
            corpus_source_reader=corpus_source_reader_for_repository(
                writing_reference_repository
            ),
        )
        if (
            catalog.project_id != canonical_id
            or catalog.journey_revision != journey.revision
            or catalog.snapshot_id != snapshot_id
        ):
            raise ValueError("rebuilt prefill evidence catalog identity is inconsistent")
        return catalog

    return ServerEvidenceVerifier(catalog_resolver=_catalog_resolver)


@app.post(
    "/api/projects/{project_id}/medical-writing/authoring-journey/prefill-package/adopt"
)
def adopt_medical_writing_authoring_prefill_candidate(
    project_id: str,
    request: AuthoringPrefillAdoptRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        verifier = _build_authoring_prefill_evidence_verifier(canonical_id)
        return medical_writing_authoring_journey_service.adopt_prefill_candidate(
            canonical_id, request, evidence_verifier=verifier
        ).model_dump(mode="json")
    except MedicalWritingAuthoringJourneyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/authoring-journey/prefill-package/adopt-composite"
)
def adopt_medical_writing_authoring_prefill_composite(
    project_id: str,
    request: AuthoringPrefillCompositeAdoptRequest,
):
    from .medical_writing_authoring_prefill import (
        MedicalWritingAuthoringPolicyError,
    )

    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        verifier = _build_authoring_prefill_evidence_verifier(canonical_id)
        result = medical_writing_authoring_journey_service.adopt_prefill_composite(
            canonical_id, request, evidence_verifier=verifier
        )
        return result.model_dump(mode="json")
    except MedicalWritingAuthoringPolicyError as exc:
        # Structured policy rejection: distinct from revision/state conflicts
        # (plain-string 409) so the frontend can explain the override/skip
        # requirement instead of mislabeling it as a concurrency conflict.
        raise HTTPException(
            status_code=422,
            detail={
                "code": exc.code,
                "reason": exc.reason,
                "message": str(exc),
            },
        )
    except MedicalWritingAuthoringJourneyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_mw_journey_error_detail(exc))


def _mw_journey_error_detail(exc: Exception) -> str:
    """消息卫生（T17 P1）：pydantic 校验细节（模型名/字段路径/外部链接）
    不进入用户界面，转换为可操作的人话；其余原样返回。"""
    text = str(exc)
    if "validation error for" in text or "errors.pydantic.dev" in text:
        return ("本次提交未通过系统数据校验，页面与服务器状态可能不同步；"
                "请刷新页面后重新操作。如重复出现，请保留页面并反馈。")
    return text


@app.post(
    "/api/projects/{project_id}/medical-writing/authoring-journey/impact-preview"
)
def preview_medical_writing_authoring_impact(
    project_id: str,
    request: MedicalWritingJourneyImpactPreviewRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_authoring_journey_service.impact_preview(
            canonical_id, request
        ).model_dump(mode="json")
    except MedicalWritingAuthoringJourneyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_mw_journey_error_detail(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/authoring-journey/stages/{stage}/commit"
)
def commit_medical_writing_authoring_stage(
    project_id: str,
    stage: str,
    request: MedicalWritingAuthoringJourneyCommitRequest,
):
    if stage not in {"framing", "picos"} or stage != request.stage:
        raise HTTPException(status_code=422, detail="authoring journey stage is inconsistent")
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        try:
            pipeline_stage = medical_writing_research_pipeline_service.get_state(
                canonical_id
            ).stage
        except KeyError:
            # A project with no persisted pipeline is an ordinary authoring
            # target.  This also keeps isolated service fixtures independent
            # when the pipeline and journey stores are intentionally replaced.
            pipeline_stage = ""
        if authoring_writes_blocked_by_pipeline(pipeline_stage):
            raise ResearchPipelineConflictError(
                authoring_write_blocker_detail(pipeline_stage)
            )
        committed = medical_writing_authoring_journey_service.commit_stage(
            canonical_id, request
        )
        # A pre-PICOS basket confirmation is intentionally allowed to unlock
        # the PICOS form.  Once that form is committed, complete the deferred
        # corpus projection automatically so the already-confirmed retained
        # scope is available to translation/admission without asking the
        # medical manager for a redundant second basket decision.
        if stage == "picos" and bool(getattr(committed, "picos_complete", False)):
            try:
                pipeline_state = medical_writing_research_pipeline_service.get_state(
                    canonical_id
                )
                triage_run_id = str(getattr(pipeline_state, "triage_run_id", "") or "")
                if triage_run_id:
                    repository = getattr(competitor_triage_service, "repository", None)
                    get_confirmation = getattr(
                        repository, "triage_confirmation_for_run", None
                    )
                    confirmation = (
                        get_confirmation(canonical_id, triage_run_id)
                        if callable(get_confirmation)
                        else None
                    )
                    if (
                        confirmation is not None
                        and str(getattr(confirmation, "projection_status", "") or "")
                        != "corpus_projected"
                    ):
                        competitor_triage_service.retry_projection(
                            canonical_id,
                            str(confirmation.confirmation_id),
                            CompetitorTriageProjectionRetryRequest(
                                actor=request.actor or "medical_manager",
                                idempotency_key=(
                                    "triage-corpus-after-picos-"
                                    f"{confirmation.confirmation_id}-{committed.revision}"
                                ),
                            ),
                        )
                        committed = medical_writing_authoring_journey_service.get(
                            canonical_id
                        )
            except Exception as exc:  # noqa: BLE001 - commit remains authoritative
                logger.warning(
                    "deferred corpus projection after PICOS commit failed for %s: %s",
                    canonical_id,
                    exc,
                )
        return committed.model_dump(mode="json")
    except ResearchPipelineConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except MedicalWritingAuthoringJourneyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_mw_journey_error_detail(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/authoring-journey/stages/{stage}/draft"
)
def save_medical_writing_authoring_stage_draft(
    project_id: str,
    stage: str,
    request: MedicalWritingAuthoringJourneyDraftSaveRequest,
):
    if stage not in {"framing", "picos"} or stage != request.stage:
        raise HTTPException(status_code=422, detail="authoring journey stage is inconsistent")
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        try:
            pipeline_stage = medical_writing_research_pipeline_service.get_state(
                canonical_id
            ).stage
        except KeyError:
            pipeline_stage = ""
        if authoring_writes_blocked_by_pipeline(pipeline_stage):
            raise ResearchPipelineConflictError(
                authoring_write_blocker_detail(pipeline_stage)
            )
        return medical_writing_authoring_journey_service.save_stage_draft(
            canonical_id, request
        ).model_dump(mode="json")
    except ResearchPipelineConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except MedicalWritingAuthoringJourneyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_mw_journey_error_detail(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/authoring-journey/corpus-gate/override"
)
def override_medical_writing_corpus_gate(
    project_id: str,
    request: MedicalWritingCorpusGateOverrideRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_authoring_journey_service.override_corpus_gate(
            canonical_id, request
        ).model_dump(mode="json")
    except MedicalWritingAuthoringJourneyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_mw_journey_error_detail(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/authoring-journey/corpus-triage/finalize"
)
def finalize_medical_writing_corpus_triage(
    project_id: str,
    request: MedicalWritingCorpusTriageFinalizeRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_corpus_readiness_service.finalize_triage(
            canonical_id, request
        ).model_dump(mode="json")
    except MedicalWritingAuthoringJourneyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_mw_journey_error_detail(exc))


def _resolve_triage_provider():
    """Resolve the active product-owned independent AI for triage."""
    profile = _independent_ai_profile()
    role_store = runtime_ai_role_settings_store()
    provider = configured_ai_provider_from_env(
        role_store.provider_store.profile_env(profile)
    )
    configured_model = getattr(provider, "model_name", "")
    if not hasattr(provider, "run") or not configured_model or configured_model == "not_configured":
        raise HTTPException(
            status_code=503,
            detail="独立 AI 尚未完成配置，无法执行竞品研究筛选",
        )
    try:
        return VerifiedTriageProvider(provider)
    except CompetitorTriageError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"独立 AI 路由未通过竞品筛选资格校验：{exc}",
        ) from exc


@app.post(
    "/api/projects/{project_id}/medical-writing/authoring-journey/competitor-triage",
    status_code=202,
)
def create_competitor_triage_run(
    project_id: str,
    request: CompetitorTriageCreateRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        result = competitor_triage_service.create_run(
            canonical_id, request, _resolve_triage_provider()
        )
        # In durable mode, create_run returns TriageDurableStartResult with
        # run_id + job_id and does NOT execute AI inline.  Wake the worker.
        if hasattr(result, "job_id") and result.job_id:
            try:
                mw_durable_worker.wake(canonical_id, result.job_id)
            except Exception:
                pass
        return _api_result_payload(result)
    except CompetitorTriageConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except CompetitorTriageError as exc:
        raise HTTPException(status_code=422, detail=_mw_journey_error_detail(exc))


@app.get(
    "/api/projects/{project_id}/medical-writing/authoring-journey/competitor-triage/latest"
)
def get_latest_competitor_triage_run(
    project_id: str,
    snapshot_id: Optional[str] = Query(None),
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        resolved_snapshot_id = str(snapshot_id or "").strip()
        if not resolved_snapshot_id:
            journey = medical_writing_authoring_journey_service.get(canonical_id)
            resolved_snapshot_id = str(
                (
                    journey.search_plan.latest_snapshot_id
                    if journey.search_plan is not None
                    else ""
                )
                or ""
            ).strip()
        if not resolved_snapshot_id:
            raise HTTPException(
                status_code=404,
                detail=(
                    "尚无可用竞品检索快照：请先在语料门执行公开检索"
                    "（POST authoring-journey/competitor-search），"
                    "再查询 competitor-triage/latest。"
                ),
            )
        latest = writing_reference_repository.latest_triage_run_for_snapshot(
            canonical_id, resolved_snapshot_id
        )
        if latest is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "no competitor triage run found for "
                    f"project={canonical_id}, snapshot={resolved_snapshot_id}；"
                    "可先 POST authoring-journey/competitor-triage"
                    "（可省略 snapshot_id，将自动绑定当前快照）。"
                ),
            )
        return competitor_triage_service.get_run(
            canonical_id, latest.run_id
        ).model_dump(mode="json")
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get(
    "/api/projects/{project_id}/medical-writing/authoring-journey/competitor-triage/{run_id}"
)
def get_competitor_triage_run(project_id: str, run_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return competitor_triage_service.get_run(
            canonical_id, run_id
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/authoring-journey/competitor-triage/{run_id}/retry",
    status_code=202,
)
def retry_competitor_triage_run(
    project_id: str,
    run_id: str,
    request: CompetitorTriageRetryRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        result = competitor_triage_service.retry_run(
            canonical_id, run_id, request, _resolve_triage_provider()
        )
        if hasattr(result, "job_id") and result.job_id:
            try:
                mw_durable_worker.wake(canonical_id, result.job_id)
            except Exception:
                pass
        return _api_result_payload(result)
    except CompetitorTriageStaleError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except CompetitorTriageConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except CompetitorTriageStaleError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except CompetitorTriageError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/authoring-journey/competitor-triage/{run_id}/confirm"
)
def confirm_competitor_triage_basket(
    project_id: str,
    run_id: str,
    payload: dict[str, object],
):
    try:
        try:
            request = CompetitorTriageBasketConfirmationRequest.model_validate(
                payload
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        confirmation = competitor_triage_service.confirm_basket(
            canonical_id, run_id, request
        )
        result = confirmation.model_dump(mode="json")
        # Advance the parent research pipeline from awaiting_triage_confirm
        # without requiring a second user click. Idempotent: repeated calls
        # or page reloads return the current state without duplicating work.
        confirmation_id = str(result.get("confirmation_id") or "")
        # Thread the exact authoritative retained scope from the
        # confirmation into the pipeline advance so the resume path
        # never recomputes from AI classifications or public-document
        # preference.
        confirmed_retained_ids = list(result.get("retained_nct_ids") or [])
        try:
            advance = medical_writing_research_pipeline_service.advance_after_basket_confirm(
                canonical_id,
                actor=str(request.actor or "medical_manager"),
                idempotency_key=f"confirm-advance-{confirmation_id}",
                retained_candidate_ids=confirmed_retained_ids or None,
            )
            result["pipeline"] = advance.get("pipeline")
            result["pipeline_advanced"] = bool(advance.get("advanced"))
        except ResearchPipelineConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ResearchPipelineError as exc:
            # Pipeline advance failure must not turn a successful basket
            # confirmation into a 422. The basket IS confirmed; the user
            # can retry the pipeline advance from the visible banner.
            result["pipeline_error"] = str(exc)
            result["pipeline_advanced"] = False
        return result
    except CompetitorTriageStaleError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except CompetitorTriageConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except MedicalWritingAuthoringJourneyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (WritingReferenceConflictError, WritingReferenceStaleStateError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except CompetitorTriageError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/authoring-journey/competitor-triage/{run_id}/reconfirm"
)
def reconfirm_competitor_triage_basket(
    project_id: str,
    run_id: str,
    request: CompetitorTriageBasketReconfirmationRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        confirmation = competitor_triage_service.reconfirm_basket(
            canonical_id, run_id, request
        )
        result = confirmation.model_dump(mode="json")
        result["pipeline_advanced"] = False
        result["external_work_repeated"] = False
        return result
    except CompetitorTriageStaleError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except CompetitorTriageConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except MedicalWritingAuthoringJourneyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (WritingReferenceConflictError, WritingReferenceStaleStateError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except CompetitorTriageError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/authoring-journey/competitor-triage/{run_id}/projection-retry"
)
def retry_competitor_triage_projection(
    project_id: str,
    run_id: str,
    request: CompetitorTriageProjectionRetryRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        repository = getattr(competitor_triage_service, "repository", None)
        get_confirmation = getattr(repository, "triage_confirmation_for_run", None)
        confirmation = (
            get_confirmation(canonical_id, run_id)
            if callable(get_confirmation)
            else None
        )
        if confirmation is None:
            raise KeyError(f"no confirmation found for run {run_id}")
        return competitor_triage_service.retry_projection(
            canonical_id, confirmation.confirmation_id, request
        ).model_dump(mode="json")
    except CompetitorTriageStaleError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except MedicalWritingAuthoringJourneyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except CompetitorTriageError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/authoring-journey/picos-corpus-alignment"
)
def record_medical_writing_picos_corpus_alignment(
    project_id: str,
    request: MedicalWritingPicosCorpusAlignmentRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_corpus_readiness_service.record_picos_alignment(
            canonical_id, request
        ).model_dump(mode="json")
    except MedicalWritingAuthoringJourneyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/authoring-journey/corpus-gate/recalculate"
)
def recalculate_medical_writing_corpus_gate(project_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_corpus_readiness_service.recalculate(
            canonical_id, actor="medical_manager"
        ).model_dump(mode="json")
    except MedicalWritingAuthoringJourneyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/medical-writing/protocol-templates/default")
def get_default_medical_writing_protocol_template():
    return medical_writing_protocol_template_service.definition().model_dump(mode="json")


@app.get("/api/medical-writing/protocol-templates/{template_id}/{template_version}")
def get_medical_writing_protocol_template(template_id: str, template_version: str):
    try:
        return medical_writing_protocol_template_service.definition(
            template_id, template_version
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/medical-writing/style-profiles/default")
def get_default_medical_writing_style_profile():
    return medical_writing_style_profile_service.definition().model_dump(mode="json")


@app.get("/api/medical-writing/style-profiles/{style_profile_id}/{style_profile_version}")
def get_medical_writing_style_profile(
    style_profile_id: str,
    style_profile_version: str,
):
    try:
        return medical_writing_style_profile_service.definition(
            style_profile_id,
            style_profile_version,
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/medical-writing/company-corpus/default")
def get_default_medical_writing_company_corpus():
    return medical_writing_company_corpus_service.definition().model_dump(mode="json")


@app.get("/api/medical-writing/company-corpus/search")
def search_medical_writing_company_corpus(
    query: str,
    section_heading: str = "",
    section_number: str = "",
    template_node_id: str = "",
    interaction_types: str = "",
    corpus_function: str = "",
    project_indication: str = "",
    project_phase: str = "",
    limit: int = 5,
    include_table_rows: Optional[bool] = None,
):
    try:
        return {
            "snapshot": medical_writing_company_corpus_service.definition().model_dump(
                mode="json"
            ),
            "items": medical_writing_company_corpus_service.search(
                query,
                section_heading=section_heading,
                section_number=section_number,
                template_node_id=template_node_id,
                interaction_types=[
                    item.strip() for item in interaction_types.split(",") if item.strip()
                ],
                corpus_function=corpus_function,
                project_indication=project_indication,
                project_phase=project_phase,
                limit=limit,
                include_table_rows=include_table_rows,
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/medical-writing/shared-corpus/phase1")
def get_phase1_shared_corpus(
    query: str = "",
    status: str = "all",
    modality: str = "all",
):
    return medical_writing_shared_corpus_service.catalog(
        query=query,
        status=status,
        modality=modality,
    ).model_dump(mode="json")


@app.get("/api/medical-writing/shared-corpus/phase1/search")
def search_phase1_shared_corpus(
    query: str,
    project_phase: str,
    project_indication: str = "",
    section_heading: str = "",
    limit: int = 5,
):
    try:
        return {
            "items": medical_writing_shared_corpus_service.search(
                query,
                project_phase=project_phase,
                project_indication=project_indication,
                section_heading=section_heading,
                limit=limit,
            )
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/medical-writing/shared-corpus/phase1/{segment_id}/medical-review")
def review_phase1_shared_corpus_candidate(
    segment_id: str,
    request: MedicalWritingSharedCorpusReviewRequest,
):
    try:
        return medical_writing_shared_corpus_service.review(
            segment_id,
            request,
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except MedicalWritingSharedCorpusConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/medical-writing/shared-corpus/phase1/{segment_id}/admissions")
def admit_phase1_shared_corpus_candidate(
    segment_id: str,
    request: MedicalWritingSharedCorpusAdmissionRequest,
):
    try:
        return medical_writing_shared_corpus_service.admit(
            segment_id,
            request,
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except MedicalWritingSharedCorpusConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/projects/{project_id}/medical-writing/greenfield-document")
def create_medical_writing_greenfield_document(
    project_id: str,
    request: MedicalWritingGreenfieldCreateRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        project_record = user_project_store.get(canonical_id)
        if (
            user_project_store.get(canonical_id) is not None
            and not medical_writing_authoring_journey_service.has_project(canonical_id)
        ):
            raise ValueError(
                "user-created medical-writing projects require an authoring journey before a writing document can be created"
            )
        if medical_writing_authoring_journey_service.has_project(canonical_id):
            medical_writing_corpus_readiness_service.recalculate(
                canonical_id, actor="system_pre_document_gate"
            )
        medical_writing_authoring_journey_service.require_writing_access(canonical_id)
        resolved_sections = list(request.sections)
        resolved_decisions = list(request.decisions)
        resolved_module_resolutions = []
        template_definition_sha256 = ""
        definition = None
        if medical_writing_authoring_journey_service.has_project(canonical_id):
            definition = medical_writing_authoring_journey_service.require_study_definition_binding(
                canonical_id,
                definition_id=request.source_study_definition_id,
                revision=request.source_study_definition_revision,
                state_sha256=request.source_study_definition_sha256,
            )
            if request.template_id:
                template_definition = medical_writing_protocol_template_service.definition(
                    request.template_id,
                    request.template_version,
                )
                template_definition_sha256 = template_definition.definition_sha256
                resolved_sections = medical_writing_protocol_template_service.section_seeds(
                    definition,
                    template_definition,
                )
                resolved_module_resolutions = (
                    medical_writing_protocol_template_service.module_resolutions(
                        definition,
                        template_definition,
                    )
                )
                resolved_decisions = [
                    MedicalWritingGreenfieldDecision(
                        decision_id=f"study_uncertainty_{index}",
                        label=label,
                        status="unresolved",
                        value="",
                        rationale="待项目团队形成有来源的研究设计决策。",
                        source_refs=[],
                        approval_blocking=True,
                    )
                    for index, label in enumerate(
                        definition.framing.key_uncertainties,
                        start=1,
                    )
                ]
            _validate_greenfield_request_against_study_definition(
                request,
                definition,
                resolved_sections,
            )
            fact_prefix = (
                f"study_definition:{definition.definition_id}:r{definition.revision}:"
            )
            for section in resolved_sections:
                for fact_id in section.source_fact_ids:
                    if not fact_id.startswith(fact_prefix):
                        raise MedicalWritingAuthoringJourneyConflictError(
                            "greenfield section references a stale or foreign study fact"
                        )
                    field_path = fact_id[len(fact_prefix):]
                    fact_state = definition.field_states.get(field_path)
                    if fact_state is None or fact_state.status not in {
                        "confirmed",
                        "not_applicable",
                    }:
                        raise ValueError(
                            f"greenfield section references an unconfirmed study fact: {field_path}"
                        )
        authoritative_cover_fields = {}
        if definition is not None:
            authoritative_cover_fields["investigational_product"] = (
                definition.framing.investigational_product
            )
        elif project_record is not None:
            product_name = str(project_record.product_name or "").strip()
            if product_name and product_name != "待定义试验药物":
                authoritative_cover_fields["investigational_product"] = product_name
        if project_record is not None and project_record.protocol_date:
            authoritative_cover_fields["protocol_date"] = project_record.protocol_date
        elif not authoritative_cover_fields.get("protocol_date"):
            # Lazy-writer default: never export a blank cover date.
            from datetime import date as _date

            authoritative_cover_fields["protocol_date"] = _date.today().isoformat()
        resolved_request = request.model_copy(
            update=authoritative_cover_fields,
            deep=True,
        )
        reservation_id = medical_writing_authoring_journey_service.reserve_document_creation(
            canonical_id,
            actor=request.actor,
            request_idempotency_key=request.idempotency_key,
        )
        try:
            style_profile = medical_writing_style_profile_service.definition()
            corpus_snapshot = medical_writing_company_corpus_service.definition()
            if request.template_id:
                current_definition = medical_writing_authoring_journey_service.require_study_definition_binding(
                    canonical_id,
                    definition_id=request.source_study_definition_id,
                    revision=request.source_study_definition_revision,
                    state_sha256=request.source_study_definition_sha256,
                )
                if current_definition.state_sha256 != definition.state_sha256:
                    raise MedicalWritingAuthoringJourneyConflictError(
                        "StudyDefinition changed while the writing document was being reserved"
                    )
            result = medical_writing_document_service.create_greenfield(
                canonical_id,
                resolved_request,
                resolved_sections=resolved_sections,
                resolved_decisions=resolved_decisions,
                resolved_module_resolutions=resolved_module_resolutions,
                template_definition_sha256=template_definition_sha256,
                style_profile_id=style_profile.style_profile_id,
                style_profile_version=style_profile.style_profile_version,
                style_profile_definition_sha256=style_profile.definition_sha256,
                corpus_snapshot_id=corpus_snapshot.snapshot_id,
                corpus_snapshot_version=corpus_snapshot.snapshot_version,
                corpus_snapshot_sha256=corpus_snapshot.snapshot_sha256,
            )
        except Exception:
            medical_writing_authoring_journey_service.release_document_creation_reservation(
                canonical_id,
                reservation_id=reservation_id,
                actor=request.actor,
            )
            raise
        medical_writing_authoring_journey_service.mark_document_created(
            canonical_id, request.actor, reservation_id
        )
        return result.model_dump(mode="json")
    except (
        GreenfieldMedicalWritingConflictError,
        MedicalWritingAuthoringJourneyConflictError,
        PlanConsumptionError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _validate_greenfield_request_against_study_definition(
    request,
    definition,
    resolved_sections=None,
) -> None:
    resolved_sections = list(
        request.sections if resolved_sections is None else resolved_sections
    )
    framing = definition.framing
    expected_identity = {
        "protocol_id": framing.protocol_id,
        "version": framing.version,
        "document_title": framing.document_title,
        "indication": framing.indication,
        "study_phase": framing.study_phase,
    }
    identity_mismatches = [
        field_name
        for field_name, expected_value in expected_identity.items()
        if getattr(request, field_name) != expected_value
    ]
    if (
        request.investigational_product
        and request.investigational_product != framing.investigational_product
    ):
        identity_mismatches.append("investigational_product")
    if identity_mismatches:
        raise MedicalWritingAuthoringJourneyConflictError(
            "greenfield document identity does not match the bound StudyDefinition: "
            + ", ".join(identity_mismatches)
        )

    fact_prefix = f"study_definition:{definition.definition_id}:r{definition.revision}:"
    confirmed_paths = [
        path
        for path, state in definition.field_states.items()
        if state.status == "confirmed"
    ]
    design_paths = [
        "framing.design_pattern",
        "framing.population_intent",
        "picos.intervention_summary",
        "picos.comparator_summary",
        "picos.primary_endpoint",
    ]

    def field_value(path: str):
        group, field_name = path.split(".", 1)
        return getattr(getattr(definition, group), field_name)

    selected_design_paths = [
        path
        for path in design_paths
        if path in confirmed_paths and str(field_value(path) or "").strip()
    ]
    if request.template_id:
        # Production create already ran plan-gated section_seeds for the project
        # and passes those as *resolved_sections*. Integrity comparison must not
        # re-enter the global plan-gated template service: that path used empty
        # project_id and incorrectly failed closed or depended on plan state.
        #
        # Derive the expected text/fact-id map from a plan-free template service
        # so only StudyDefinition fact projection is checked. Plan fail-closed
        # remains at production entrypoints (section_seeds / greenfield create).
        template_definition = medical_writing_protocol_template_service.definition(
            request.template_id,
            request.template_version,
        )
        integrity_template_service = MedicalWritingProtocolTemplateService()
        expected_by_section = {
            section.section_key: (
                section.initial_text,
                set(section.source_fact_ids),
            )
            for section in integrity_template_service.section_seeds(
                definition,
                template_definition,
            )
            if section.source_fact_ids
        }
    else:
        expected_by_section = {
            "protocol_synopsis": (
                definition.synopsis_text,
                {fact_prefix + path for path in confirmed_paths},
            ),
            "ich_m11_1_1": (
                definition.synopsis_text,
                {fact_prefix + path for path in confirmed_paths},
            ),
            "cms_synopsis_summary": (
                definition.synopsis_text,
                {fact_prefix + path for path in confirmed_paths},
            ),
            "study_design": (
                "；".join(
                    str(field_value(path)).strip()
                    for path in selected_design_paths
                ),
                {fact_prefix + path for path in selected_design_paths},
            ),
            "ich_m11_4_1": (
                "；".join(
                    str(field_value(path)).strip()
                    for path in selected_design_paths
                ),
                {fact_prefix + path for path in selected_design_paths},
            ),
            "cms_study_design_overall": (
                "；".join(
                    str(field_value(path)).strip()
                    for path in selected_design_paths
                ),
                {fact_prefix + path for path in selected_design_paths},
            ),
            "ich_m11_8_3": (
                render_assessment_instrument_methods(definition),
                {fact_prefix + "picos.assessment_instruments"},
            ),
            "cms_procedures_assessments_efficacy": (
                render_assessment_instrument_methods(definition),
                {fact_prefix + "picos.assessment_instruments"},
            ),
        }
    for section in resolved_sections:
        if not section.source_fact_ids:
            continue
        expected = expected_by_section.get(section.section_key)
        if expected is None:
            raise MedicalWritingAuthoringJourneyConflictError(
                "greenfield fact-attributed text is not part of the canonical "
                "StudyDefinition template projection"
            )
        expected_text, expected_fact_ids = expected
        if section.initial_text != expected_text or set(section.source_fact_ids) != expected_fact_ids:
            raise MedicalWritingAuthoringJourneyConflictError(
                f"greenfield section {section.section_key} does not match the bound StudyDefinition projection"
            )


@app.get("/api/projects/{project_id}/medical-writing/greenfield-document")
def get_medical_writing_greenfield_document(project_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_document_service.greenfield_state(canonical_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get(
    "/api/projects/{project_id}/medical-writing/greenfield-document/template-upgrade/preview"
)
def preview_medical_writing_greenfield_template_upgrade(
    project_id: str,
    target_template_id: str = Query("ich_m11_zh_cn"),
    target_template_version: str = Query(
        "ich_m11_zh_cn_step4_cde_consultation_2026_06_12_v1"
    ),
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_template_upgrade_service.preview(
            canonical_id,
            target_template_id=target_template_id,
            target_template_version=target_template_version,
        ).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/greenfield-document/template-upgrade/apply"
)
def apply_medical_writing_greenfield_template_upgrade(
    project_id: str,
    request: MedicalWritingTemplateUpgradeApplyRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_template_upgrade_service.apply(
            canonical_id,
            request,
        ).model_dump(mode="json")
    except GreenfieldMedicalWritingConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/greenfield-document/template-upgrade/rollback"
)
def rollback_medical_writing_greenfield_template_upgrade(
    project_id: str,
    request: MedicalWritingTemplateUpgradeRollbackRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_template_upgrade_service.rollback(
            canonical_id,
            request,
        ).model_dump(mode="json")
    except GreenfieldMedicalWritingConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/greenfield-document/"
    "decisions/{decision_id}/resolve"
)
def resolve_medical_writing_greenfield_decision(
    project_id: str,
    decision_id: str,
    request: MedicalWritingGreenfieldDecisionResolveRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_document_service.resolve_greenfield_decision(
            canonical_id,
            decision_id,
            request,
        ).model_dump(mode="json")
    except GreenfieldMedicalWritingConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/greenfield-document/"
    "module-resolutions/{semantic_node_id}"
)
def apply_medical_writing_protocol_module_resolution(
    project_id: str,
    semantic_node_id: str,
    request: MedicalWritingProtocolModuleResolutionApplyRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        if semantic_node_id.strip() != request.semantic_node_id:
            raise ValueError(
                "module-resolution path must match request semantic_node_id"
            )
        definition = medical_writing_authoring_journey_service.get(
            canonical_id
        ).study_definition
        if definition is None:
            raise ValueError(
                "a confirmed StudyDefinition is required before resolving modules"
            )
        current_document = medical_writing_document_service.document_for_revision(
            canonical_id
        )
        template = medical_writing_protocol_template_service.definition(
            current_document.template_id,
            current_document.template_version,
        )
        matching_nodes = [
            node
            for node in template.nodes
            if node.semantic_node_id == request.semantic_node_id
        ]
        if len(matching_nodes) != 1:
            raise ValueError(
                "module resolution must identify one registered template node"
            )
        existing_overrides = {
            item.semantic_node_id: item
            for item in current_document.module_resolutions
            if item.user_override
        }
        node = matching_nodes[0]
        existing_overrides[request.semantic_node_id] = (
            MedicalWritingProtocolModuleResolution(
                template_node_id=node.node_id,
                semantic_node_id=node.semantic_node_id,
                status=request.status,
                render_action=request.render_action,
                resolution_source="user_override",
                rationale=request.rationale,
                source_fact_ids=request.source_refs,
                user_override=True,
            )
        )
        overlay_definition = definition.model_copy(
            update={"module_resolutions": existing_overrides},
            deep=True,
        )
        resolved_sections = (
            medical_writing_protocol_template_service.section_seeds(
                overlay_definition,
                template,
            )
        )
        resolved_module_resolutions = (
            medical_writing_protocol_template_service.module_resolutions(
                overlay_definition,
                template,
            )
        )
        result = medical_writing_document_service.apply_greenfield_module_resolution(
            canonical_id,
            request,
            resolved_sections=resolved_sections,
            resolved_module_resolutions=resolved_module_resolutions,
        )
        runtime_reset = (
            medical_writing_study_consistency_service.reset_after_module_resolution(
                canonical_id,
                document_id=result.document_id,
                updated_section_ids=result.updated_section_ids,
                removed_section_ids=result.removed_section_ids,
                actor=request.actor,
                idempotency_key=request.idempotency_key + ":runtime-reset",
                baseline_revision=result.baseline_revision,
            )
        )
        return result.model_copy(update=runtime_reset).model_dump(mode="json")
    except GreenfieldMedicalWritingConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/projects/{project_id}/medical-writing/content-quality")
def get_medical_writing_content_quality(
    project_id: str,
    section_id: str = Query(""),
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_runtime_repository.content_quality(
            canonical_id,
            section_id,
        ).model_dump(mode="json")
    except (KeyError, FileNotFoundError):
        raise HTTPException(
            status_code=404,
            detail=f"medical writing content quality target not found: {project_id}/{section_id}",
        )


@app.post(
    "/api/projects/{project_id}/medical-writing/content-quality/findings/{finding_id}/disposition"
)
def apply_medical_writing_content_disposition(
    project_id: str,
    finding_id: str,
    request: MedicalWritingContentDispositionRequest,
    section_id: str = Query(""),
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_runtime_repository.apply_content_disposition(
            canonical_id,
            finding_id,
            request,
            section_id,
        ).model_dump(mode="json")
    except (KeyError, FileNotFoundError):
        raise HTTPException(
            status_code=404,
            detail=f"medical writing content finding not found: {project_id}/{finding_id}",
        )
    except StaleRuntimeStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (RuntimeStoreError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/medical-writing/table-templates")
def get_medical_writing_table_templates():
    return medical_writing_table_template_service.catalog()


@app.get("/api/medical-writing/table-domain-profiles")
def get_medical_writing_table_domain_profiles():
    return medical_writing_table_domain_profile_service.catalog()


def _verify_canonical_pdf_page_evidence(receipt: Any, encoded_pdf: str) -> dict:
    """Recompute the submitted Word/PDF page evidence with the fixed adapter.

    The PDF is transport-only input for this request. It is never persisted or
    logged; only its digest and canonical renderer metadata are retained in the
    append-only receipt audit event. Missing or mismatching evidence fails
    closed before the receipt can be committed.
    """

    encoded = str(encoded_pdf or "").strip()
    if not encoded:
        raise MedicalWritingDocumentDocxExportError(
            "canonical PDF page evidence is required for Word verification"
        )
    max_encoded = ((MAX_CANONICAL_PDF_BYTES + 2) // 3) * 4
    if len(encoded) > max_encoded:
        raise MedicalWritingDocumentDocxExportError(
            "canonical PDF page evidence exceeds the 50 MB limit"
        )
    try:
        pdf_bytes = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise MedicalWritingDocumentDocxExportError(
            "canonical PDF page evidence must be strict base64"
        ) from exc
    if not pdf_bytes:
        raise MedicalWritingDocumentDocxExportError(
            "canonical PDF page evidence must not be empty"
        )
    pdf_sha256 = sha256(pdf_bytes).hexdigest()
    if receipt.pdf_sha256 != pdf_sha256:
        raise MedicalWritingDocumentDocxExportError(
            "Word verification receipt PDF hash does not match the supplied PDF"
        )
    try:
        canonical_pages = canonical_pdf_page_hashes(pdf_bytes)
    except MedicalWritingPdfPageHashError as exc:
        raise MedicalWritingDocumentDocxExportError(
            f"canonical PDF page hashing failed closed: {exc}"
        ) from exc
    if receipt.page_count != len(canonical_pages):
        raise MedicalWritingDocumentDocxExportError(
            "Word verification receipt page count does not match the canonical PDF"
        )
    expected_page_hashes = [
        str(page.pdf_page_sha256) for page in canonical_pages
    ]
    supplied_page_hashes = [
        str(page.pdf_page_sha256) for page in receipt.page_evidence
    ]
    if supplied_page_hashes != expected_page_hashes:
        raise MedicalWritingDocumentDocxExportError(
            "Word verification receipt page hashes do not match canonical PDFium evidence"
        )
    manifest_sha256 = canonical_pdf_page_hash_manifest_sha256(
        canonical_pages,
        pdf_sha256=pdf_sha256,
    )
    first_page = canonical_pages[0]
    return {
        "contract": first_page.contract_version,
        "renderer": first_page.renderer,
        "renderer_version": first_page.renderer_version,
        "render_dpi": first_page.render_dpi,
        "pixel_format": first_page.pixel_format,
        "pdf_sha256": pdf_sha256,
        "page_count": len(canonical_pages),
        "manifest_sha256": manifest_sha256,
        "pages": [page.as_dict() for page in canonical_pages],
    }


def _verify_medical_writing_document_export(project_id: str, mode: str) -> dict:
    if mode not in {"draft_preview", "approved_final"}:
        raise ValueError(f"unsupported document export mode: {mode!r}")
    return {"project_id": project_id, "mode": mode}


def _assemble_medical_writing_document_export(verified: dict) -> dict:
    canonical_id = str(verified["project_id"])
    mode = str(verified["mode"])
    document = medical_writing_runtime_repository.assemble_document_for_export(
        canonical_id,
        mode,
    )
    source_mode = medical_writing_document_service.source_mode(canonical_id)
    front_matter_overrides = {}
    if source_mode != "original_protocol_docx":
        if medical_writing_authoring_journey_service.has_project(canonical_id):
            journey = medical_writing_authoring_journey_service.get(canonical_id)
            definition = journey.study_definition
            if (
                definition is not None
                and definition.framing.investigational_product
            ):
                front_matter_overrides["investigational_product"] = (
                    definition.framing.investigational_product
                )
        project_record = user_project_store.get(canonical_id)
        if project_record is not None:
            product_name = str(project_record.product_name or "").strip()
            if (
                "investigational_product" not in front_matter_overrides
                and product_name
                and product_name != "待定义试验药物"
            ):
                front_matter_overrides["investigational_product"] = product_name
            if project_record.protocol_date:
                front_matter_overrides["protocol_date"] = (
                    project_record.protocol_date
                )
    return {
        **verified,
        "document": document,
        "source_mode": source_mode,
        "front_matter_overrides": front_matter_overrides,
    }


def _process_medical_writing_document_export_sources(assembled: dict) -> dict:
    canonical_id = str(assembled["project_id"])
    mode = str(assembled["mode"])
    document = assembled["document"]
    front_matter_overrides = assembled["front_matter_overrides"]
    freeze_reference = ""
    exporter_document = document
    if mode == "approved_final":
        # The exporter still consumes the historical approval-state shape.
        # Readiness has already proved that every applicable section is frozen.
        exporter_document = document.model_copy(
            update={
                "sections": [
                    section.model_copy(
                        update={"approval_state": ApprovalState.MEDICALLY_APPROVED},
                        deep=True,
                    )
                    for section in document.sections
                ]
            },
            deep=True,
        )
        snapshot_digest = medical_writing_document_export_snapshot_digest(
            exporter_document,
            front_matter_overrides=front_matter_overrides,
        )
        freeze_reference = f"author-frozen-document:{snapshot_digest}"
    return {
        **assembled,
        "exporter_document": exporter_document,
        "freeze_reference": freeze_reference,
        "literature_library": medical_writing_literature_service.library(
            canonical_id
        ),
    }


def _render_medical_writing_document_export(prepared: dict) -> dict:
    canonical_id = str(prepared["project_id"])
    mode = str(prepared["mode"])
    source_mode = str(prepared["source_mode"])
    exporter_document = prepared["exporter_document"]
    freeze_reference = str(prepared["freeze_reference"])
    literature_library = prepared["literature_library"]
    if source_mode == "original_protocol_docx":
        result = export_source_preserving_medical_writing_document_docx(
            medical_writing_document_service.original_protocol_path(canonical_id),
            medical_writing_source_document_service.document_for_revision(
                canonical_id
            ),
            exporter_document,
            mode=mode,
            approval_reference=freeze_reference,
            literature_library=literature_library,
        )
    else:
        result = export_medical_writing_document_docx(
            exporter_document,
            mode=mode,
            approval_reference=freeze_reference,
            literature_library=literature_library,
            front_matter_overrides=prepared["front_matter_overrides"],
            plan_consumption_helper=medical_writing_plan_consumption_helper,
        )
    return {**prepared, "result": result}


def _medical_writing_export_filename(rendered: dict) -> str:
    document = rendered["document"]
    suffix = "方案终稿" if rendered["mode"] == "approved_final" else "草稿预览"
    return _safe_docx_filename(
        f"{document.protocol_id}_{document.version}_{suffix}.docx"
    )


def _medical_writing_export_metadata(rendered: dict) -> dict:
    document = rendered["document"]
    result = rendered["result"]
    metadata = dict(result.metadata)
    source_ref_reindex = metadata.get("source_reference_reindex", {})
    metadata.update(
        {
            "document_id": document.document_id,
            "section_count": len(document.sections),
            "freeze_reference": rendered["freeze_reference"],
            "source_reference_status": str(
                source_ref_reindex.get("status", "")
            ),
            "user_action_required": bool(
                source_ref_reindex.get("user_action_required", False)
            ),
            "warning_message": str(
                source_ref_reindex.get("warning_message", "")
            ),
        }
    )
    return metadata


def _medical_writing_export_headers(
    *,
    filename: str,
    mode: str,
    metadata: Mapping,
) -> dict[str, str]:
    document_id = str(metadata.get("document_id") or "document")
    ascii_filename = f"medical-writing-{document_id}-{mode}.docx"
    return {
        "Content-Disposition": (
            f'attachment; filename="{ascii_filename}"; '
            f"filename*=UTF-8''{quote(filename, safe='')}"
        ),
        "X-Medical-Writing-Export-Mode": str(metadata.get("mode", mode)),
        "X-Medical-Writing-Document-Id": document_id,
        "X-Medical-Writing-Source-Snapshot-Sha256": str(
            metadata.get("source_snapshot_sha256", "")
        ),
        "X-Medical-Writing-Docx-Sha256": str(
            metadata.get("docx_sha256", "")
        ),
        "X-Medical-Writing-Section-Count": str(
            metadata.get("section_count", 0)
        ),
        "X-Medical-Writing-Table-Count": str(metadata.get("table_count", 0)),
        "X-Medical-Writing-Freeze-Reference": str(
            metadata.get("freeze_reference", "")
        ),
        "X-Medical-Writing-Source-Reference-Status": str(
            metadata.get("source_reference_status", "")
        ),
        "X-Medical-Writing-User-Action-Required": str(
            bool(metadata.get("user_action_required", False))
        ).lower(),
        "X-Medical-Writing-Warning-Message": str(
            metadata.get("warning_message", "")
        ),
    }


def _medical_writing_document_export_callbacks():
    return MedicalWritingDocumentExportCallbacks(
        verify_export_conditions=lambda context: (
            _verify_medical_writing_document_export(
                context.project_id,
                context.mode,
            )
        ),
        assemble_sections=lambda _context, verified: (
            _assemble_medical_writing_document_export(verified)
        ),
        process_sources_and_citations=lambda _context, assembled: (
            _process_medical_writing_document_export_sources(assembled)
        ),
        render_docx=lambda _context, prepared: _as_durable_rendered_document(
            _render_medical_writing_document_export(prepared)
        ),
    )


def _as_durable_rendered_document(rendered: dict):
    result = rendered["result"]
    return MedicalWritingRenderedDocument(
        content=result.content,
        filename=_medical_writing_export_filename(rendered),
        metadata=_medical_writing_export_metadata(rendered),
    )


medical_writing_document_export_job_service = MedicalWritingDocumentExportJobService(
    store=mw_durable_store,
    worker=mw_durable_worker,
    artifact_root=RUNTIME_DIR / "medical_writing_document_exports",
    callbacks=_medical_writing_document_export_callbacks(),
)


@app.post("/api/projects/{project_id}/medical-writing/document-exports")
def start_medical_writing_document_export(project_id: str, request: dict):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        response = medical_writing_document_export_job_service.start(
            canonical_id,
            mode=str(request.get("mode") or "draft_preview"),
            idempotency_key=str(request.get("idempotency_key") or ""),
            actor=str(request.get("actor") or "medical_manager"),
            payload=request.get("payload") or {},
        )
        return _api_result_payload(response)
    except (RuntimeStoreError, PlanConsumptionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get(
    "/api/projects/{project_id}/medical-writing/document-exports/{job_id}/download"
)
def download_medical_writing_document_export(project_id: str, job_id: str):
    canonical_id = _canonical_module_project_id(project_id, "medical_writing")
    try:
        artifact = medical_writing_document_export_job_service.read_artifact(
            canonical_id,
            job_id,
        )
    except DurableJobNotFound:
        raise HTTPException(
            status_code=404,
            detail=f"durable job not found: {job_id}",
        )
    except MedicalWritingDocumentExportArtifactUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    mode = str(artifact.metadata.get("mode") or "draft_preview")
    return FileResponse(
        artifact.path,
        media_type=artifact.media_type,
        headers=_medical_writing_export_headers(
            filename=artifact.filename,
            mode=mode,
            metadata=artifact.metadata,
        ),
    )


@app.get("/api/projects/{project_id}/medical-writing/document.docx")
def export_medical_writing_document(
    project_id: str,
    mode: str = Query("draft_preview"),
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        rendered = _render_medical_writing_document_export(
            _process_medical_writing_document_export_sources(
                _assemble_medical_writing_document_export(
                    _verify_medical_writing_document_export(canonical_id, mode)
                )
            )
        )
    except (KeyError, FileNotFoundError):
        raise HTTPException(
            status_code=404,
            detail=f"medical writing document not found: {project_id}",
        )
    except (RuntimeStoreError, PlanConsumptionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (MedicalWritingDocumentDocxExportError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    result = rendered["result"]
    filename = _medical_writing_export_filename(rendered)
    metadata = _medical_writing_export_metadata(rendered)
    return Response(
        content=result.content,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers=_medical_writing_export_headers(
            filename=filename,
            mode=mode,
            metadata=metadata,
        ),
    )


@app.get("/api/projects/{project_id}/medical-writing/document-preview")
def get_medical_writing_document_preview(
    project_id: str,
    mode: str = Query("draft_preview"),
):
    """Return a fast source-bound pagination estimate, never a Word claim."""

    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        prepared = _process_medical_writing_document_export_sources(
            _assemble_medical_writing_document_export(
                _verify_medical_writing_document_export(canonical_id, mode)
            )
        )
        preview = build_medical_writing_fast_preview(
            prepared["exporter_document"],
            mode=mode,
            front_matter_overrides=prepared.get("front_matter_overrides"),
        )
        return preview.model_dump(mode="json")
    except (KeyError, FileNotFoundError):
        raise HTTPException(
            status_code=404,
            detail=f"medical writing document not found: {project_id}",
        )
    except (RuntimeStoreError, PlanConsumptionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (MedicalWritingDocumentDocxExportError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/document-preview/word-verification"
)
def submit_medical_writing_word_verification(
    project_id: str,
    request: MedicalWritingWordVerificationSubmitRequest,
):
    """Bind an externally produced Word/PDF receipt to one stored DOCX job."""

    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        if request.receipt.project_id != canonical_id:
            raise ValueError("Word verification receipt project does not match the route")
        artifact = medical_writing_document_export_job_service.read_artifact(
            canonical_id,
            request.export_job_id,
        )
        metadata = artifact.metadata
        mode = str(metadata.get("mode") or "draft_preview")
        expected_docx_sha256 = str(metadata.get("docx_sha256") or "")
        expected_source_snapshot_sha256 = str(
            metadata.get("source_snapshot_sha256") or ""
        )
        if not expected_docx_sha256 or artifact.sha256 != expected_docx_sha256:
            raise MedicalWritingDocumentDocxExportError(
                "stored DOCX artifact hash is missing or inconsistent"
            )
        if not expected_source_snapshot_sha256:
            raise MedicalWritingDocumentDocxExportError(
                "stored DOCX artifact has no source snapshot hash"
            )
        if request.receipt.document_id != str(metadata.get("document_id") or ""):
            raise ValueError("Word verification receipt document does not match the DOCX job")
        prepared = _process_medical_writing_document_export_sources(
            _assemble_medical_writing_document_export(
                _verify_medical_writing_document_export(canonical_id, mode)
            )
        )
        preview = build_medical_writing_word_verified_preview(
            prepared["exporter_document"],
            request.receipt,
            expected_docx_sha256=expected_docx_sha256,
            mode=mode,
            front_matter_overrides=prepared.get("front_matter_overrides"),
        )
        if preview.snapshot_sha256 != expected_source_snapshot_sha256:
            raise MedicalWritingDocumentDocxExportError(
                "current document snapshot does not match the stored DOCX job"
            )
        canonical_page_hash_metadata = _verify_canonical_pdf_page_evidence(
            request.receipt,
            request.canonical_pdf_base64,
        )
        committed = _medical_writing_word_verification_repository().save(
            request.receipt,
            expected_source_snapshot_sha256=expected_source_snapshot_sha256,
            expected_docx_sha256=expected_docx_sha256,
            actor=request.actor,
            canonical_page_hash_metadata=canonical_page_hash_metadata,
        )
        return {
            "receipt": committed.receipt.model_dump(mode="json"),
            "preview": preview.model_dump(mode="json"),
            "export_job_id": request.export_job_id,
            "audit_id": committed.audit_id,
            "replayed": committed.replayed,
            "canonical_pdf_page_hash": canonical_page_hash_metadata,
        }
    except (KeyError, FileNotFoundError, DurableJobNotFound):
        raise HTTPException(
            status_code=404,
            detail=f"medical writing DOCX export job not found: {request.export_job_id}",
        )
    except MedicalWritingDocumentExportArtifactUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except WordVerificationReceiptIdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (RuntimeStoreError, PlanConsumptionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (
        WordVerificationReceiptStaleError,
        WordVerificationReceiptError,
        MedicalWritingDocumentDocxExportError,
        ValueError,
    ) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/projects/{project_id}/medical-writing/document-session/sections/{section_id}")
def get_medical_writing_document_section(project_id: str, section_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_document_service.section(
            canonical_id, section_id
        ).model_dump(mode="json")
    except (KeyError, FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail=f"medical writing section not found: {section_id}")


@app.get("/api/projects/{project_id}/medical-writing/working-copies/{section_id}")
def get_medical_writing_working_copy(project_id: str, section_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_runtime_repository.working_copy(
            canonical_id,
            section_id,
        ).model_dump(mode="json")
    except (KeyError, FileNotFoundError, ValueError):
        raise HTTPException(
            status_code=404,
            detail=f"medical writing working copy not found: {project_id}/{section_id}",
        )


@app.post(
    "/api/projects/{project_id}/medical-writing/working-copies/{section_id}"
    "/table-templates/{template_id}/instantiate"
)
def instantiate_medical_writing_table_template(
    project_id: str,
    section_id: str,
    template_id: str,
    title: str = Query(""),
    row_count: Optional[int] = Query(default=None, ge=2, le=50),
    column_count: Optional[int] = Query(default=None, ge=2, le=20),
    header_row_count: Optional[int] = Query(default=None, ge=0, le=5),
    orientation: str = Query(""),
    notes_area: bool = Query(False),
    allow_duplicate: bool = Query(False),
    duplicate_reason: str = Query("", max_length=200),
    actor: str = Query("medical_manager"),
    idempotency_key: str = Query("", max_length=160),
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        working_copy = medical_writing_runtime_repository.working_copy(
            canonical_id,
            section_id,
        )
        if working_copy.revision < 1:
            raise RuntimeStoreError(
                "working copy must be saved before a table template is inserted"
            )
        canonical_idempotency_key = idempotency_key.strip()
        request_fingerprint = sha256(
            json.dumps(
                {
                    "template_id": template_id,
                    "title": title,
                    "row_count": row_count,
                    "column_count": column_count,
                    "header_row_count": header_row_count,
                    "orientation": orientation,
                    "notes_area": notes_area,
                    "allow_duplicate": allow_duplicate,
                    "duplicate_reason": duplicate_reason.strip(),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        instance_id = (
            sha256(
                f"{canonical_id}:{section_id}:{template_id}:{canonical_idempotency_key}".encode(
                    "utf-8"
                )
            ).hexdigest()[:24]
            if canonical_idempotency_key
            else ""
        )
        table_block = medical_writing_table_template_service.instantiate(
            template_id,
            title=title,
            instance_id=instance_id,
            row_count=row_count,
            column_count=column_count,
            header_row_count=header_row_count,
            orientation=orientation,
            notes_area=notes_area,
            project_id=canonical_id,
        )
        table_block["template_insert_request_sha256"] = request_fingerprint
        existing_block = next(
            (
                block
                for block in working_copy.content_blocks
                if canonical_idempotency_key
                and block.get("block_id") == table_block["block_id"]
            ),
            None,
        )
        if existing_block is not None:
            if existing_block.get("template_insert_request_sha256") != request_fingerprint:
                raise RuntimeStoreError(
                    "table template idempotency key was reused with different options"
                )
            return {
                "working_copy": working_copy.model_dump(mode="json"),
                "table_block": existing_block,
            }
        same_template_blocks = [
            block
            for block in working_copy.content_blocks
            if block.get("block_type") == "table"
            and block.get("template_id") == template_id
        ]
        if same_template_blocks and not allow_duplicate:
            existing_ids = ", ".join(
                str(block.get("block_id") or block.get("table_id") or "unknown")
                for block in same_template_blocks
            )
            raise RuntimeStoreError(
                "the same table template already exists in this section; "
                f"open the existing table or explicitly allow a duplicate: {existing_ids}"
            )
        if same_template_blocks:
            table_block["duplicate_of_block_id"] = same_template_blocks[0].get(
                "block_id"
            )
            table_block["duplicate_reason"] = (
                duplicate_reason.strip() or "user_confirmed_duplicate"
            )
        saved = medical_writing_runtime_repository.save_working_copy(
            canonical_id,
            section_id,
            MedicalWritingWorkingCopySaveRequest(
                document_id=working_copy.document_id,
                expected_revision=working_copy.revision,
                content_blocks=[*working_copy.content_blocks, table_block],
                actor=actor,
                idempotency_key=canonical_idempotency_key,
            ),
        )
        persisted_block = next(
            block
            for block in saved.content_blocks
            if block.get("block_id") == table_block["block_id"]
        )
        return {
            "working_copy": saved.model_dump(mode="json"),
            "table_block": persisted_block,
        }
    except PlanConsumptionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (KeyError, FileNotFoundError) as exc:
        detail = str(exc).strip("'")
        raise HTTPException(status_code=404, detail=detail)
    except RuntimeStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (MedicalWritingTableError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/projects/{project_id}/medical-writing/working-copies/{section_id}")
def save_medical_writing_working_copy(
    project_id: str,
    section_id: str,
    request: MedicalWritingWorkingCopySaveRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_runtime_repository.save_working_copy(
            canonical_id,
            section_id,
            request,
        ).model_dump(mode="json")
    except (KeyError, FileNotFoundError):
        raise HTTPException(
            status_code=404,
            detail=f"medical writing working copy not found: {project_id}/{section_id}",
        )
    except (ValueError, RuntimeStoreError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get(
    "/api/projects/{project_id}/medical-writing/working-copies/{section_id}/quarantined-history"
)
def get_medical_writing_quarantined_working_copy(project_id: str, section_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_runtime_repository.historical_quarantined_working_copy(
            canonical_id, section_id
        ).model_dump(mode="json")
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'"))
    except RuntimeStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/working-copies/{section_id}/accept-and-bind"
)
def accept_and_bind_medical_writing_working_copy(
    project_id: str,
    section_id: str,
    request: MedicalWritingWorkingCopyBindingRecoveryRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_runtime_repository.accept_and_bind_working_copy(
            canonical_id, section_id, request
        ).model_dump(mode="json")
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'"))
    except (RuntimeStoreError, StaleRuntimeStateError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/working-copies/{section_id}/revert-authoritative-baseline"
)
def revert_medical_writing_working_copy_to_authoritative_baseline(
    project_id: str,
    section_id: str,
    request: MedicalWritingWorkingCopyBindingRecoveryRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_runtime_repository.revert_to_authoritative_baseline(
            canonical_id, section_id, request
        ).model_dump(mode="json")
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'"))
    except (RuntimeStoreError, StaleRuntimeStateError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/working-copies/{section_id}/freeze-current-version"
)
def freeze_medical_writing_section_version(
    project_id: str,
    section_id: str,
    request: MedicalWritingSectionFreezeRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_runtime_repository.freeze_current_version(
            canonical_id, section_id, request
        ).model_dump(mode="json")
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'"))
    except (RuntimeStoreError, StaleRuntimeStateError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/working-copies/{section_id}/unfreeze"
)
def unfreeze_medical_writing_section_version(
    project_id: str,
    section_id: str,
    request: MedicalWritingSectionFreezeRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_runtime_repository.unfreeze_current_version(
            canonical_id, section_id, request
        ).model_dump(mode="json")
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'"))
    except (RuntimeStoreError, StaleRuntimeStateError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get(
    "/api/projects/{project_id}/medical-writing/working-copies/{section_id}/freeze-history"
)
def get_medical_writing_section_freeze_history(
    project_id: str,
    section_id: str,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return [
            item.model_dump(mode="json")
            for item in medical_writing_runtime_repository.section_freeze_history(
                canonical_id, section_id
            )
        ]
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'"))
    except RuntimeStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/api/projects/{project_id}/medical-writing/freeze-readiness")
def get_medical_writing_final_freeze_readiness(project_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        return medical_writing_runtime_repository.final_freeze_readiness(
            canonical_id
        ).model_dump(mode="json")
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'"))
    except RuntimeStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get(
    "/api/projects/{project_id}/medical-writing/working-copies/{section_id}/tables/{block_id}"
)
def get_medical_writing_structured_table(
    project_id: str,
    section_id: str,
    block_id: str,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        working_copy = medical_writing_runtime_repository.working_copy(
            canonical_id,
            section_id,
        )
        block = next(
            (
                candidate
                for candidate in working_copy.content_blocks
                if candidate.get("block_id") == block_id
                and candidate.get("block_type") == "table"
            ),
            None,
        )
        if block is None:
            raise KeyError(block_id)
        return medical_writing_table_service.from_table_block(block).model_dump(mode="json")
    except (KeyError, FileNotFoundError):
        raise HTTPException(status_code=404, detail=f"medical writing table not found: {block_id}")
    except MedicalWritingTableError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/working-copies/{section_id}/tables/{block_id}/batch-update"
)
def update_medical_writing_structured_table(
    project_id: str,
    section_id: str,
    block_id: str,
    request: MedicalWritingTableBatchUpdateRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        working_copy = medical_writing_runtime_repository.working_copy(
            canonical_id,
            section_id,
        )
        block_index = next(
            (
                index
                for index, candidate in enumerate(working_copy.content_blocks)
                if candidate.get("block_id") == block_id
                and candidate.get("block_type") == "table"
            ),
            None,
        )
        if block_index is None:
            raise KeyError(block_id)
        current_block = working_copy.content_blocks[block_index]
        # Design-sensitive SoA tables must remain pinned to the confirmed plan.
        soa_domain = ""
        structured = current_block.get("structured_table")
        if isinstance(structured, dict):
            soa_domain = str(structured.get("domain") or "")
        medical_writing_table_template_service.require_soa_plan_projection(
            project_id=canonical_id,
            template_id=str(current_block.get("template_id") or ""),
            domain=soa_domain,
        )
        operation_fingerprint = sha256(
            json.dumps(
                {
                    "block_id": block_id,
                    "expected_working_copy_revision": request.expected_working_copy_revision,
                    "expected_table_version": request.expected_table_version,
                    "operations": request.operations,
                    "actor": request.actor,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        current_change_set = (
            current_block.get("structured_table", {}).get("last_change_set", {})
            if isinstance(current_block.get("structured_table"), dict)
            else {}
        )
        if current_change_set.get("idempotency_key") == request.idempotency_key:
            if current_change_set.get("request_fingerprint") != operation_fingerprint:
                raise TableVersionConflictError(
                    "table update idempotency key was reused with a different request"
                )
            current_table = medical_writing_table_service.from_table_block(current_block)
            return MedicalWritingTableBatchUpdateResult(
                working_copy=working_copy,
                table=current_table,
                table_block=current_block,
            ).model_dump(mode="json")
        if working_copy.revision != request.expected_working_copy_revision:
            raise TableVersionConflictError(
                "working copy revision conflict: "
                f"expected {request.expected_working_copy_revision}, current {working_copy.revision}"
            )
        table = medical_writing_table_service.from_table_block(
            current_block
        )
        updated_table = medical_writing_table_service.apply_operations(
            table,
            request.operations,
            expected_version=request.expected_table_version,
        )
        updated_block = medical_writing_table_service.to_table_block(updated_table)
        updated_block["structured_table"]["last_change_set"] = {
            "idempotency_key": request.idempotency_key,
            "request_fingerprint": operation_fingerprint,
            "actor": request.actor,
        }
        content_blocks = [
            dict(candidate) for candidate in working_copy.content_blocks
        ]
        content_blocks[block_index] = updated_block
        saved = medical_writing_runtime_repository.save_working_copy(
            canonical_id,
            section_id,
            MedicalWritingWorkingCopySaveRequest(
                document_id=working_copy.document_id,
                expected_revision=request.expected_working_copy_revision,
                content_blocks=content_blocks,
                actor=request.actor,
                idempotency_key=request.idempotency_key,
            ),
        )
        return MedicalWritingTableBatchUpdateResult(
            working_copy=saved,
            table=updated_table,
            table_block=updated_block,
        ).model_dump(mode="json")
    except (KeyError, FileNotFoundError):
        raise HTTPException(status_code=404, detail=f"medical writing table not found: {block_id}")
    except (TableVersionConflictError, RuntimeStoreError, PlanConsumptionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (MedicalWritingTableError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/working-copies/{section_id}/revision-threads/{thread_id}/apply"
)
def apply_medical_writing_revision_to_working_copy(
    project_id: str,
    section_id: str,
    thread_id: str,
    request: MedicalWritingRevisionApplyRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        _require_atomic_medical_writing_route(canonical_id)
        return medical_writing_runtime_repository.apply_approved_revision_to_working_copy(
            canonical_id,
            section_id,
            thread_id,
            request,
        ).model_dump(mode="json")
    except (KeyError, FileNotFoundError):
        raise HTTPException(
            status_code=404,
            detail=f"medical writing revision application target not found: {project_id}/{section_id}/{thread_id}",
        )
    except (ValueError, RuntimeStoreError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/medical-writing/working-copies/{section_id}/approval-gate"
)
def create_medical_writing_working_copy_approval_gate(
    project_id: str,
    section_id: str,
    requested_by: str = Query("medical_manager"),
):
    raise HTTPException(
        status_code=410,
        detail=(
            "medical-writing approval submission is retired; the medical author "
            "must use freeze-current-version to confirm the current chapter version"
        ),
    )


@app.get("/api/projects/{project_id}/medical-writing/tfl-citation-candidates")
def get_medical_writing_tfl_citation_candidates(project_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "data_analysis_tfl")
        return tfl_writing_handoff_service.citation_manifest(canonical_id).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")


@app.get("/api/projects/{project_id}/tfl/manifest")
def get_tfl_manifest(project_id: str, force_refresh: bool = Query(False)):
    try:
        canonical_id = _canonical_module_project_id(project_id, "data_analysis_tfl")
        return tfl_manifest_service.build_manifest(canonical_id, force_refresh=force_refresh).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"data_analysis_tfl not configured for project: {project_id}")


@app.get("/api/projects/{project_id}/tfl/review-workbench")
def get_tfl_review_workbench(
    project_id: str,
    package_id: Optional[str] = Query(None),
    output_id: Optional[str] = Query(None),
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "data_analysis_tfl")
        return tfl_review_workbench_service.workbench(canonical_id, package_id=package_id, output_id=output_id).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"project or TFL output not found: {project_id}")


@app.post("/api/projects/{project_id}/tfl/review-workbench/{package_id}/outputs/{output_id}/actions")
def apply_tfl_review_action(
    project_id: str,
    package_id: str,
    output_id: str,
    request: TflReviewActionRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "data_analysis_tfl")
        return tfl_review_workbench_service.apply_action(canonical_id, package_id, output_id, request).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"project, TFL package, or TFL output not found: {project_id}")
    except SourceAdmissionRequired as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "source_confirmation_required",
                "message": str(exc),
                "source_admission": exc.state.model_dump(mode="json"),
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/api/projects/{project_id}/safety-pv/manifest")
def get_safety_pv_manifest(project_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "safety_pv")
        return safety_pv_manifest_service.build_manifest(canonical_id).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"safety_pv not configured for project: {project_id}")


@app.get("/api/projects/{project_id}/safety-pv/review-workbench")
def get_safety_review_workbench(
    project_id: str,
    package_id: Optional[str] = Query(None),
    signal_id: Optional[str] = Query(None),
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "safety_pv")
        return safety_review_workbench_service.workbench(canonical_id, package_id=package_id, signal_id=signal_id).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"project, safety package, or safety signal not found: {project_id}")


@app.post("/api/projects/{project_id}/safety-pv/review-workbench/{package_id}/signals/{signal_id}/actions")
def apply_safety_review_action(
    project_id: str,
    package_id: str,
    signal_id: str,
    request: SafetyReviewActionRequest,
):
    try:
        canonical_id = _canonical_module_project_id(project_id, "safety_pv")
        return safety_review_workbench_service.apply_action(canonical_id, package_id, signal_id, request).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"project, safety package, or safety signal not found: {project_id}")
    except SourceAdmissionRequired as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "source_confirmation_required",
                "message": str(exc),
                "source_admission": exc.state.model_dump(mode="json"),
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/api/projects/{project_id}/safety-pv/handoff-candidates")
def get_safety_pv_handoff_candidates(project_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "safety_pv")
        return safety_review_workbench_service.handoff_candidates(canonical_id).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")


@app.get("/api/projects/{project_id}/protocol")
def get_protocol(project_id: str):
    try:
        return repo.protocol(project_id).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"protocol not found for project: {project_id}")


@app.get("/api/projects/{project_id}/revision-threads")
def get_revision_threads(project_id: str):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        _service, repository = _medical_writing_services(canonical_id)
        repository.project(canonical_id)
        return [thread.model_dump(mode="json") for thread in repository.revision_threads(canonical_id)]
    except KeyError:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")


@app.post(
    "/api/projects/{project_id}/revision-threads",
    status_code=202,
)
def submit_revision_thread(project_id: str, request: MedicalWritingRevisionRequest):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        service, _repository = _medical_writing_services(canonical_id)
        # Durable path: create-or-reuse a section_ai_candidate job and return
        # immediately with job_id.  The executor runs AI under claim/heartbeat.
        job_id, cached_result = service.submit_revision_durable(
            canonical_id, request, mw_durable_store,
        )
        # Wake the worker so execution starts immediately.
        try:
            mw_durable_worker.wake(canonical_id, job_id)
        except Exception:
            pass
        # If the job was already completed (reused), return the cached result
        # alongside the job_id so the frontend can render immediately.
        if cached_result is not None:
            return {
                "job_id": job_id,
                "status": "completed",
                "result": cached_result.model_dump(mode="json"),
            }
        return {"job_id": job_id, "status": "accepted"}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"project, document, or section not found: {project_id}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/api/projects/{project_id}/revision-threads/{thread_id}/actions")
def apply_revision_action(project_id: str, thread_id: str, request: RevisionActionRequest):
    try:
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        if request.action == RevisionAction.ACCEPT:
            _require_atomic_medical_writing_route(canonical_id)
        service, _repository = _medical_writing_services(canonical_id)
        # request_rewrite is the only action that invokes long AI work.
        # Route it through the durable job path so the HTTP thread never
        # blocks on model inference.  Accept and reject are short synchronous
        # operations that stay on the request thread.
        if request.action == RevisionAction.REQUEST_REWRITE and request.suggestion_id:
            job_id, cached_result = service.request_rewrite_durable(
                canonical_id,
                thread_id,
                request.suggestion_id,
                request.rewrite_instruction,
                request.actor,
                request.comment,
                mw_durable_store,
            )
            try:
                mw_durable_worker.wake(canonical_id, job_id)
            except Exception:
                pass
            if cached_result is not None:
                return JSONResponse(
                    status_code=202,
                    content={
                        "job_id": job_id,
                        "status": "completed",
                        "result": cached_result.model_dump(mode="json"),
                    },
                )
            return JSONResponse(
                status_code=202,
                content={"job_id": job_id, "status": "accepted"},
            )
        return service.apply_action(canonical_id, thread_id, request).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"revision thread or suggestion not found: {project_id}/{thread_id}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/revision-threads/{thread_id}/accept-and-apply"
)
async def accept_and_apply_revision_candidate(
    project_id: str,
    thread_id: str,
    request: RevisionAcceptAndApplyRequest,
):
    """Atomic accept-and-apply: record author selection AND update the working
    copy in a single backend transaction.  Replaces the two-request
    accept-then-apply chain.

    Uses RevisionAcceptAndApplyRequest (WorkbenchModel, extra='forbid') so
    extra fields in the payload are rejected at the Pydantic boundary.
    """
    try:
        suggestion_id = request.suggestion_id
        expected_wc_rev = request.expected_working_copy_revision
        actor = request.actor
        idempotency_key = request.idempotency_key
        canonical_id = _canonical_module_project_id(project_id, "medical_writing")
        service, _repository = _medical_writing_services(canonical_id)
        result = await run_in_threadpool(
            service.accept_and_apply_candidate,
            project_id=canonical_id,
            thread_id=thread_id,
            suggestion_id=suggestion_id,
            expected_working_copy_revision=int(expected_wc_rev),
            actor=actor,
            idempotency_key=idempotency_key,
        )
        return result.model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"revision thread or section not found: {project_id}/{thread_id}")
    except AttributeError as exc:
        raise HTTPException(status_code=404, detail=f"atomic adoption not available: {project_id}/{thread_id}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except RuntimeStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/api/projects/{project_id}/approvals/{approval_id}/actions")
def apply_approval_action(project_id: str, approval_id: str, request: ApprovalActionRequest):
    try:
        canonical_id = _canonical_project_id(project_id)
        retired_writing_gate = next(
            (
                gate
                for gate in medical_writing_runtime_repository.runtime_store.gates(
                    canonical_id
                )
                if gate.approval_id == approval_id
                and _is_retired_medical_writing_approval(gate)
            ),
            None,
        )
        if retired_writing_gate is not None:
            raise HTTPException(
                status_code=410,
                detail=(
                    "legacy medical-writing approval actions are retired; AI candidate "
                    "selection is the author decision and chapter completion uses version freeze"
                ),
            )
        try:
            approval = repo.approval(canonical_id, approval_id)
        except KeyError:
            approval = None
        if approval is not None and approval.target_type in {
            "medical_writing_revision_thread",
            "medical_writing_working_copy",
        }:
            raise HTTPException(
                status_code=410,
                detail=(
                    "legacy medical-writing approval actions are retired; AI candidate "
                    "selection is the author decision and chapter completion uses version freeze"
                ),
            )
        if approval is not None and approval.target_type == "medical_monitoring_risk_disposition":
            workbench_inbox_service.require_current_monitoring_approval_source(
                canonical_id,
                approval_id,
            )
        if (
            canonical_id in WRITING_PACKAGE_IDS_BY_PROJECT
            or medical_writing_greenfield_document_service.has_project(canonical_id)
        ):
            try:
                medical_writing_runtime_repository.approval(canonical_id, approval_id)
            except KeyError:
                result = repo.record_approval_action(canonical_id, approval_id, request)
            else:
                result = medical_writing_runtime_repository.record_approval_action(
                    canonical_id,
                    approval_id,
                    request,
                )
        else:
            result = repo.record_approval_action(project_id, approval_id, request)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"approval not found: {project_id}/{approval_id}")
    except RuntimeStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if request.action == ApprovalAction.APPROVE and result.decision.blocked:
        raise HTTPException(status_code=409, detail=result.model_dump(mode="json"))
    return result.model_dump(mode="json")


@app.get("/api/projects/{project_id}/subjects/{subject_id}/monitoring")
def get_subject_monitoring(
    project_id: str,
    subject_id: str,
    http_request: Request,
):
    canonical_id = _canonical_project_id(project_id)
    _authorize_legacy_monitoring_action(
        http_request,
        canonical_id,
        request_id=(
            f"legacy-monitoring-subject-read:{canonical_id}:{subject_id}"
        ),
        action=MonitoringAction.READ_MONITORING,
    )
    if monitoring_project_registry.has(canonical_id):
        try:
            return monitoring_project_registry.get(canonical_id).subject_monitoring(subject_id).model_dump(mode="json")
        except MonitoringProjectCapabilityUnavailableError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "monitoring_subject_view_capability_unavailable",
                    "message": str(exc),
                },
            ) from exc
        except (FileNotFoundError, KeyError, RuntimeError):
            raise HTTPException(status_code=404, detail=f"subject monitoring not found: {canonical_id}/{subject_id}")
    if canonical_id != "proj_mgk10_sar_demo":
        raise HTTPException(status_code=404, detail=f"medical monitoring service not registered: {canonical_id}")
    try:
        return repo.subject_monitoring(canonical_id, subject_id).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"subject monitoring not found: {canonical_id}/{subject_id}")


@app.post("/api/projects/{project_id}/monitoring/intake")
def submit_monitoring_intake(
    project_id: str,
    request: MonitoringIntakeRequest,
    http_request: Request,
):
    try:
        canonical_id = _canonical_project_id(project_id)
        server_actor = _authorize_legacy_monitoring_action(
            http_request,
            canonical_id,
            request_id=f"legacy-monitoring-intake-write:{canonical_id}",
            action=MonitoringAction.INTAKE_BATCH,
            write=True,
        )
        if monitoring_project_registry.has(canonical_id):
            raise HTTPException(
                status_code=409,
                detail=_real_project_monitoring_intake_not_enabled_detail(canonical_id),
            )
        request = request.model_copy(update={"uploaded_by": server_actor})
        return monitoring_intake.submit(canonical_id, request).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")


@app.get("/api/projects/{project_id}/monitoring/batches")
def list_monitoring_batches(project_id: str, http_request: Request):
    canonical_id = _canonical_module_project_id(project_id, "medical_monitoring")
    _authorize_legacy_monitoring_action(
        http_request,
        canonical_id,
        request_id=f"legacy-monitoring-batches-read:{canonical_id}",
        action=MonitoringAction.READ_MONITORING,
    )
    return {
        "project_id": canonical_id,
        "batches": [
            batch.to_dict()
            for batch in monitoring_batch_repository.list_batches(canonical_id)
        ],
    }


@app.post("/api/projects/{project_id}/monitoring/batches/intake-file")
async def intake_monitoring_batch_file(
    project_id: str,
    request: Request,
    filename: str = Query(...),
    idempotency_key: str = Query(...),
    classification_override_reason: str = Query(""),
):
    canonical_id = _canonical_module_project_id(project_id, "medical_monitoring")
    _authorize_legacy_monitoring_action(
        request,
        canonical_id,
        request_id=f"legacy-monitoring-batch-intake-write:{canonical_id}",
        action=MonitoringAction.INTAKE_BATCH,
        write=True,
    )
    content = await request.body()
    try:
        return monitoring_batch_service.intake_listing(
            project_id=canonical_id,
            filename=filename,
            content=content,
            idempotency_key=idempotency_key,
            classification_override_reason=classification_override_reason,
        ).to_dict()
    except MonitoringBatchIntakeBlocked as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, **exc.detail},
        )
    except MonitoringBatchRepositoryError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/projects/{project_id}/monitoring/batches/{batch_id}")
def get_monitoring_batch(
    project_id: str,
    batch_id: str,
    http_request: Request,
):
    canonical_id = _canonical_module_project_id(project_id, "medical_monitoring")
    _authorize_legacy_monitoring_action(
        http_request,
        canonical_id,
        request_id=f"legacy-monitoring-batch-read:{canonical_id}:{batch_id}",
        action=MonitoringAction.READ_MONITORING,
    )
    try:
        summary = monitoring_batch_repository.batch_summary(batch_id)
    except MonitoringBatchRepositoryError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if summary["batch"]["project_id"] != canonical_id:
        raise HTTPException(status_code=404, detail=f"monitoring batch not found: {batch_id}")
    return {
        **summary["batch"],
        "sources": summary["sources"],
        "row_count": summary["row_count"],
        "domain_counts": summary["domain_counts"],
    }


@app.post("/api/projects/{project_id}/monitoring/batches/{batch_id}/validation-evidence")
def record_monitoring_batch_validation_evidence(
    project_id: str,
    batch_id: str,
    request: MonitoringBatchValidationEvidenceRequest,
    http_request: Request,
):
    canonical_id = _canonical_module_project_id(project_id, "medical_monitoring")
    _authorize_legacy_monitoring_action(
        http_request,
        canonical_id,
        request_id=(
            f"legacy-monitoring-batch-validation-write:{canonical_id}:"
            f"{batch_id}"
        ),
        action=MonitoringAction.VALIDATE_SOURCE_REVISION,
        write=True,
    )
    try:
        batch = monitoring_batch_repository.get_batch(batch_id)
        if batch.project_id != canonical_id:
            raise HTTPException(status_code=404, detail=f"monitoring batch not found: {batch_id}")
        return monitoring_batch_service.record_validation_evidence(
            batch_id=batch_id,
            mapping_revision=request.mapping_revision,
            mapping=request.mapping,
            expected_domains=request.expected_domains,
            full_snapshot_proof=request.full_snapshot_proof,
            expected_version=request.expected_version,
            idempotency_key=request.idempotency_key,
        ).to_dict()
    except HTTPException:
        raise
    except MonitoringBatchRepositoryError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post(
    "/api/projects/{project_id}/monitoring/batches/{batch_id}/"
    "confirm-full-snapshot"
)
def confirm_monitoring_batch_full_snapshot(
    project_id: str,
    batch_id: str,
    request: MonitoringBatchConfirmFullSnapshotRequest,
    http_request: Request,
):
    canonical_id = _canonical_module_project_id(project_id, "medical_monitoring")
    _reject_legacy_monitoring_policy_gap(
        http_request,
        canonical_id,
        request_id=(
            f"legacy-monitoring-batch-full-snapshot-confirm-gap:{canonical_id}:"
            f"{batch_id}"
        ),
    )
    try:
        return monitoring_mapping_batch_lifecycle_service.confirm_full_snapshot(
            project_id=canonical_id,
            batch_id=batch_id,
            expected_version=request.expected_version,
            full_snapshot_proof=request.full_snapshot_proof,
            actor=request.actor,
            idempotency_key=request.idempotency_key,
        ).to_dict()
    except MonitoringMappingRequiredError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "monitoring_mapping_required",
                "message": str(exc),
            },
        ) from exc
    except MonitoringMappingDifferenceReviewRequired as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "monitoring_mapping_difference_review_required",
                "message": "本批次字段结构发生变化，请先校对差异字段。",
                "compatibility": exc.report,
            },
        ) from exc
    except (MonitoringMappingBatchLifecycleError, MonitoringBatchRepositoryError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/api/projects/{project_id}/monitoring/batches/{batch_id}/"
    "verify-derived-snapshot"
)
def verify_monitoring_batch_derived_snapshot(
    project_id: str,
    batch_id: str,
    request: MonitoringBatchVerifyDerivedSnapshotRequest,
    http_request: Request,
):
    canonical_id = _canonical_module_project_id(project_id, "medical_monitoring")
    server_actor = _authorize_legacy_monitoring_action(
        http_request,
        canonical_id,
        request_id=(
            f"legacy-monitoring-derived-snapshot-write:{canonical_id}:"
            f"{batch_id}"
        ),
        action=MonitoringAction.CONFIRM_DERIVED_DATA,
        write=True,
    )
    try:
        batch = monitoring_batch_repository.get_batch(batch_id)
        if batch.project_id != canonical_id:
            raise HTTPException(
                status_code=404,
                detail=f"monitoring batch not found: {batch_id}",
            )
        return monitoring_batch_service.verify_derived_snapshot(
            batch_id=batch_id,
            source_id=request.source_id,
            source_content_sha256=request.source_content_sha256,
            original_source_class=request.original_source_class,
            parser_version=request.parser_version,
            transformation_type=request.transformation_type,
            execution_tool=request.execution_tool,
            execution_tool_version=request.execution_tool_version,
            original_parse_sheets=(
                item.model_dump(mode="json")
                for item in request.original_parse_sheets
            ),
            normalized_row_count=request.normalized_row_count,
            expected_domains=request.expected_domains,
            verified_by=server_actor,
            reason=request.reason,
            expected_version=request.expected_version,
            idempotency_key=request.idempotency_key,
        ).to_dict()
    except HTTPException:
        raise
    except MonitoringBatchRepositoryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/monitoring/batches/{batch_id}/transition")
def transition_monitoring_batch(
    project_id: str,
    batch_id: str,
    request: MonitoringBatchTransitionRequest,
    http_request: Request,
):
    canonical_id = _canonical_module_project_id(project_id, "medical_monitoring")
    _reject_legacy_monitoring_policy_gap(
        http_request,
        canonical_id,
        request_id=(
            f"legacy-monitoring-batch-transition-gap:{canonical_id}:{batch_id}"
        ),
    )
    try:
        batch = monitoring_batch_repository.get_batch(batch_id)
        if batch.project_id != canonical_id:
            raise HTTPException(status_code=404, detail=f"monitoring batch not found: {batch_id}")
        return monitoring_batch_service.transition(
            batch_id=batch_id,
            target_state=request.target_state,
            expected_version=request.expected_version,
            idempotency_key=request.idempotency_key,
        ).to_dict()
    except HTTPException:
        raise
    except MonitoringBatchRepositoryError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/api/projects/{project_id}/monitoring/batch-diff")
def get_monitoring_batch_diff(
    project_id: str,
    http_request: Request,
    previous_batch_id: str = Query(...),
    current_batch_id: str = Query(...),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
):
    canonical_id = _canonical_module_project_id(project_id, "medical_monitoring")
    _authorize_legacy_monitoring_action(
        http_request,
        canonical_id,
        request_id=(
            f"legacy-monitoring-batch-diff-read:{canonical_id}:"
            f"{previous_batch_id}:{current_batch_id}"
        ),
        action=MonitoringAction.READ_MONITORING,
    )
    try:
        previous = monitoring_batch_repository.get_batch(previous_batch_id)
        current = monitoring_batch_repository.get_batch(current_batch_id)
        if previous.project_id != canonical_id or current.project_id != canonical_id:
            raise HTTPException(status_code=404, detail="monitoring batch diff not found")
        result = monitoring_batch_service.detailed_diff(previous_batch_id, current_batch_id)
        field_changes = result["field_changes"]
        result["field_change_total"] = len(field_changes)
        result["field_changes"] = field_changes[offset : offset + limit]
        result["offset"] = offset
        result["limit"] = limit
        return result
    except HTTPException:
        raise
    except MonitoringBatchRepositoryError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/api/projects/{project_id}/monitoring/intake/file")
async def submit_monitoring_intake_file(
    project_id: str,
    request: Request,
    filename: str = Query(...),
    extract_date: str = Query(...),
    batch_label: str = Query("原始数据 listing Batch 004"),
    previous_batch_id: Optional[str] = Query(None),
    uploaded_by: str = Query("medical_manager"),
    confirm_aesi_flag: bool = Query(False),
):
    canonical_id = _canonical_module_project_id(project_id, "medical_monitoring")
    server_actor = _authorize_legacy_monitoring_action(
        request,
        canonical_id,
        request_id=f"legacy-monitoring-intake-file-write:{canonical_id}",
        action=MonitoringAction.INTAKE_BATCH,
        write=True,
    )
    content = await request.body()
    if not content:
        raise HTTPException(status_code=400, detail="uploaded listing file is empty")
    try:
        sheets = parse_listing_file(filename, content)
        registered = source_registry.register_listing_file(
            canonical_id,
            filename,
            content,
            module="medical_monitoring",
            expected_file_role="edc_data_listing",
        )
        validation = source_registry.current_content_validation(
            canonical_id,
            registered.entry.entry_id,
        )
        if validation is not None and validation.use_status not in {
            "allowed",
            "confirmed_after_warning",
        }:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "source_content_confirmation_required",
                    "source_entry_id": registered.entry.entry_id,
                    "validation": _public_source_validation(validation),
                },
            )
        if monitoring_project_registry.has(canonical_id):
            raise HTTPException(
                status_code=409,
                detail=_real_project_monitoring_intake_not_enabled_detail(
                    canonical_id,
                    source_entry=registered.entry,
                    validation=validation,
                ),
            )
        intake_request = MonitoringIntakeRequest(
            batch_label=batch_label,
            extract_date=extract_date,
            previous_batch_id=previous_batch_id,
            uploaded_by=server_actor,
            mapping_confirmations={"AESI_FLAG": "safety_interest_flag"} if confirm_aesi_flag else {},
            sheets=sheets,
        )
        result = monitoring_intake.submit(canonical_id, intake_request).model_dump(mode="json")
        result["source_entry_id"] = registered.entry.entry_id
        result["content_validation"] = _public_source_validation(validation) if validation else None
        return result
    except KeyError:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/projects/{project_id}/monitoring/intake/{session_id}")
def get_monitoring_intake(
    project_id: str,
    session_id: str,
    http_request: Request,
):
    canonical_id = _canonical_module_project_id(project_id, "medical_monitoring")
    _authorize_legacy_monitoring_action(
        http_request,
        canonical_id,
        request_id=f"legacy-monitoring-intake-read:{canonical_id}:{session_id}",
        action=MonitoringAction.READ_MONITORING,
    )
    try:
        result = monitoring_intake.session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"monitoring intake session not found: {session_id}")
    if result.project_id != canonical_id:
        raise HTTPException(status_code=404, detail=f"monitoring intake session not found: {canonical_id}/{session_id}")
    return result.model_dump(mode="json")
