from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import Enum
from functools import lru_cache
from hashlib import sha256
import json
import re
from typing import Any, Iterable, Mapping, Sequence

from .monitoring_mapping_contract import MonitoringFieldKind


SEMANTIC_QUALITY_SCHEMA_VERSION = "monitoring_mapping_semantic_quality_v2"
ROLE_CATALOG_VERSION = "monitoring_role_catalog_v2"
RULE_CATALOG_VERSION = "monitoring_semantic_rules_v3"
CAPABILITY_MANIFEST_VERSION = "monitoring_capability_manifest_v1"


class SemanticQualityStatus(str, Enum):
    BLOCKED = "blocked"
    PASS_WITH_WARNINGS = "pass_with_warnings"
    PASSED = "passed"


class SemanticFindingSeverity(str, Enum):
    GLOBAL_BLOCKER = "global_blocker"
    CAPABILITY_BLOCKER = "capability_blocker"
    REVIEW_WARNING = "review_warning"
    AUTO_RESOLVED = "auto_resolved"


class MappingActivationDisposition(str, Enum):
    REJECT = "reject"
    ACTIVATE_RESTRICTED = "activate_restricted"
    ACTIVATE_FULL = "activate_full"


class MappingCapabilityStateCode(str, Enum):
    READY = "ready"
    LIMITED = "limited"
    BLOCKED_BY_QUALITY = "blocked_by_quality"
    DISABLED_BY_DESIGN = "disabled_by_design"


@dataclass(frozen=True)
class RoleConcept:
    role_concept_id: str
    role_family: str
    value_semantics: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, order=True)
class SemanticFieldRef:
    domain: str
    source_field: str
    role_concept_id: str


@dataclass(frozen=True)
class SemanticFindingGroup:
    finding_group_id: str
    rule_id: str
    severity: SemanticFindingSeverity
    clinical_topic: str
    title_zh: str
    summary_zh: str
    affected_fields: tuple[SemanticFieldRef, ...]
    affected_capability_ids: tuple[str, ...]


@dataclass(frozen=True)
class MonitoringCapabilityManifestEntry:
    capability_id: str
    required_role_concepts: tuple[str, ...] = ()
    required_lineage_contracts: tuple[str, ...] = ()
    allowed_limited_modes: tuple[str, ...] = ()
    dependent_rule_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class MappingCapabilityState:
    capability_id: str
    state: MappingCapabilityStateCode
    blocking_finding_group_ids: tuple[str, ...]
    limitation_codes: tuple[str, ...]


@dataclass(frozen=True)
class MappingSemanticQualityReport:
    schema_version: str
    role_catalog_version: str
    rule_catalog_version: str
    input_sha256: str
    status: SemanticQualityStatus
    activation_disposition: MappingActivationDisposition
    capability_manifest_version: str
    capability_manifest_sha256: str
    global_blocker_count: int
    capability_blocker_count: int
    warning_count: int
    finding_groups: tuple[SemanticFindingGroup, ...]
    capability_states: tuple[MappingCapabilityState, ...]
    report_sha256: str

    def as_payload(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class _NormalizedField:
    domain: str
    source_field: str
    source_key: str
    raw_role: str
    role_concept_id: str
    role_family: str
    value_semantics: str
    field_kind: str
    related_fields: tuple[str, ...]
    standards_reference: Mapping[str, Any] | None
    derivation_lineage: Mapping[str, Any] | None
    coding_lineage: Mapping[str, Any] | None
    value_constraints: Mapping[str, Any] | None
    object_identity: str
    object_identity_evidence_fields: tuple[str, ...]
    object_identity_binding_id: str
    validated_treatment_identity_binding: Mapping[str, Any] | None
    dose_semantics: str
    quality_gate_actions: tuple[str, ...]

    @property
    def ref(self) -> SemanticFieldRef:
        return SemanticFieldRef(
            domain=self.domain,
            source_field=self.source_field,
            role_concept_id=self.role_concept_id or "unresolved",
        )


def _concept(
    role_concept_id: str,
    role_family: str,
    value_semantics: str,
    *aliases: str,
) -> RoleConcept:
    return RoleConcept(
        role_concept_id=role_concept_id,
        role_family=role_family,
        value_semantics=value_semantics,
        aliases=tuple(aliases),
    )


ROLE_CATALOG_V2: tuple[RoleConcept, ...] = (
    _concept(
        "metadata.subject_id",
        "metadata",
        "identifier",
        "subject_id",
        "subject_identifier",
        "source_subject_identifier",
        "technical_subject_id",
        "usubjid",
        "subjid",
    ),
    _concept(
        "metadata.site_id",
        "metadata",
        "identifier",
        "site_id",
        "site_identifier",
        "source_site_identifier",
        "technical_site_id",
    ),
    _concept(
        "metadata.site_name",
        "metadata",
        "text",
        "site_name",
        "source_site_name",
    ),
    _concept(
        "metadata.subject_initials",
        "metadata",
        "identifier",
        "subject_initials",
    ),
    _concept(
        "metadata.visit_id",
        "metadata",
        "identifier",
        "visit_id",
        "visit_identifier",
        "source_visit_identifier",
        "technical_visit_id",
    ),
    _concept(
        "metadata.visit_name",
        "metadata",
        "text",
        "visit_name",
        "source_visit_name",
    ),
    _concept(
        "metadata.visit_sequence",
        "metadata",
        "number",
        "visit_sequence_number",
        "visit_number",
    ),
    _concept(
        "metadata.form_id",
        "metadata",
        "identifier",
        "form_id",
        "form_identifier",
        "source_form_identifier",
        "technical_form_id",
    ),
    _concept(
        "metadata.record_id",
        "metadata",
        "identifier",
        "record_id",
        "source_record_identifier",
        "technical_record_id",
    ),
    _concept(
        "metadata.domain_id",
        "metadata",
        "identifier",
        "source_domain_identifier",
    ),
    _concept(
        "metadata.study_id",
        "metadata",
        "identifier",
        "study_identifier",
    ),
    _concept(
        "metadata.visit_repeat_key",
        "metadata",
        "identifier",
        "visit_repeat_key",
    ),
    _concept(
        "metadata.form_repeat_key",
        "metadata",
        "identifier",
        "form_repeat_key",
    ),
    _concept(
        "metadata.item_group_id",
        "metadata",
        "identifier",
        "item_group_identifier",
    ),
    _concept(
        "metadata.record_group_id",
        "metadata",
        "identifier",
        "record_group_identifier",
    ),
    _concept(
        "metadata.crf_version",
        "metadata",
        "version",
        "crf_version",
    ),
    _concept(
        "metadata.form_name",
        "metadata",
        "text",
        "form_name",
        "form_display_name",
        "edc_form_display_name",
        "edc_form_name",
        "metadata_form_name",
    ),
    _concept(
        "metadata.page_name",
        "metadata",
        "text",
        "page_name",
        "page_display_name",
        "edc_page_display_name",
        "edc_page_name",
        "form_page_name",
        "page_or_form_display_name",
        "form_page_identifier",
    ),
    _concept(
        "metadata.form_name_duplicate",
        "metadata",
        "text",
        "form_name_duplicate",
    ),
    _concept(
        "metadata.record_block_sequence",
        "metadata",
        "number",
        "record_block_sequence",
    ),
    _concept(
        "metadata.source_row_number",
        "metadata",
        "number",
        "record_line_number",
        "source_row_number",
        "record_sequence_number",
        "listing_line_number",
        "edc_record_line_number",
        "record_line_sequence_number",
        "metadata_source_row_number",
    ),
    _concept(
        "metadata.lab_configuration_name",
        "metadata",
        "text",
        "laboratory_configuration_name",
        "lab_panel_specimen_identifier_label",
        "lab_specimen_or_test_identifier_text",
        "specimen_or_test_identifier",
    ),
    _concept(
        "metadata.record_deletion_flag",
        "metadata",
        "boolean",
        "record_deletion_flag",
    ),
    _concept(
        "metadata.page_first_saved_datetime",
        "metadata",
        "datetime",
        "page_first_saved_datetime",
    ),
    _concept(
        "metadata.page_last_modified_by",
        "metadata",
        "identifier",
        "page_last_modified_by",
    ),
    _concept(
        "metadata.page_last_modified_datetime",
        "metadata",
        "datetime",
        "page_last_modified_datetime",
    ),
    _concept(
        "metadata.study_name",
        "metadata",
        "text",
        "study_name",
    ),
    _concept(
        "metadata.record_repeat_key",
        "metadata",
        "identifier",
        "record_repeat_key",
    ),
    _concept(
        "metadata.edc_object_id",
        "metadata",
        "identifier",
        "edc_object_identifier",
    ),
    _concept(
        "metadata.edc_repeat_key",
        "metadata",
        "identifier",
        "edc_repeat_key",
    ),
    _concept("ae.source_other", "ae", "source_value"),
    _concept("mh.source_other", "mh", "source_value"),
    _concept("cm.source_other", "cm", "source_value"),
    _concept("lab.source_other", "lab", "source_value"),
    _concept("scale.source_other", "scale", "source_value"),
    _concept("assessment.source_other", "assessment", "source_value"),
    _concept("disposition.source_other", "disposition", "source_value"),
    _concept("demographics.source_other", "demographics", "source_value"),
    _concept("metadata.source_other", "metadata", "source_value"),
    _concept("clinical.source_other", "clinical.other", "source_value"),
    _concept("coding.meddra.source_other", "coding.meddra", "source_value"),
    _concept("coding.drug.source_other", "coding.drug", "source_value"),
    _concept(
        "coding.meddra.dictionary_version",
        "coding.meddra",
        "version",
        "meddra_dictionary_version",
    ),
    _concept(
        "coding.meddra.dictionary_language",
        "coding.meddra",
        "category",
        "meddra_dictionary_language",
        "meddra_coding_language",
        "meddra_language",
    ),
    _concept(
        "coding.drug.dictionary_version",
        "coding.drug",
        "version",
        "drug_dictionary_version",
    ),
    _concept(
        "coding.drug.dictionary_language",
        "coding.drug",
        "category",
        "drug_dictionary_language",
        "drug_language_code",
        "concomitant_medication_drug_term_language",
    ),
    _concept(
        "coding.drug.reported_code",
        "coding.drug",
        "code",
        "drug_code_reported",
        "cm_drug_code",
    ),
    _concept(
        "coding.drug.reported_term",
        "coding.drug",
        "term",
        "drug_term_name_reported",
    ),
    _concept(
        "coding.drug.atc_code",
        "coding.drug",
        "code",
        "atc_level1_code",
        "atc_level2_code",
        "atc_level3_code",
        "atc_level4_code",
    ),
    _concept(
        "coding.drug.atc_term",
        "coding.drug",
        "term",
        "atc_level1_term",
        "atc_level2_term",
        "atc_level3_term",
        "atc_level4_term",
    ),
    _concept(
        "ae.verbatim_term",
        "ae",
        "text",
        "adverse_event_verbatim_term",
        "adverse_event_observation",
        "ae_term",
        "ae_reported_term",
    ),
    _concept(
        "ae.seriousness",
        "ae",
        "category",
        "ae_serious_flag",
        "ae_serious_flag_code",
        "ae_serious_flag_term",
        "ae_serious_event_category",
    ),
    _concept(
        "ae.severity",
        "ae",
        "category",
        "ae_severity",
        "ae_toxicity_grade_code",
        "ae_toxicity_grade_text",
        "ae_toxicity_grade_highest_code",
        "ae_toxicity_grade_highest_text",
    ),
    _concept("ae.start_date", "ae", "date", "ae_start_date"),
    _concept("ae.end_date", "ae", "date", "ae_end_date"),
    _concept(
        "mh.verbatim_term",
        "mh",
        "text",
        "medical_history_verbatim_term",
        "mh_reported_term",
        "mh_term",
    ),
    _concept("mh.start_date", "mh", "date", "mh_start_date"),
    _concept("mh.end_date", "mh", "date", "mh_end_date"),
    _concept(
        "cm.non_ip_medication.name",
        "cm",
        "text",
        "concomitant_medication_term",
        "concomitant_medication_name",
        "cm_medication_name",
    ),
    _concept("cm.non_ip_medication.dose", "cm", "number", "cm_dose"),
    _concept("cm.non_ip_medication.dose_unit", "cm", "unit", "cm_dose_unit"),
    _concept("cm.non_ip_medication.route", "cm", "category", "cm_route"),
    _concept("cm.non_ip_medication.frequency", "cm", "category", "cm_frequency"),
    _concept("cm.non_ip_medication.start_date", "cm", "date", "cm_start_date"),
    _concept("cm.non_ip_medication.end_date", "cm", "date", "cm_end_date"),
    _concept("cm.non_ip_medication.indication", "cm", "text", "cm_indication"),
    _concept(
        "ip.administration.date",
        "ip.administration",
        "date",
        "ip_administration_date",
        "actual_dose_date",
        "exposure_administration_date",
    ),
    _concept(
        "ip.administration.time",
        "ip.administration",
        "time",
        "ip_administration_time",
        "actual_dose_time",
        "exposure_administration_time",
    ),
    _concept(
        "ip.administration.dose",
        "ip.administration",
        "number",
        "ip_administration_dose",
        "actual_dose",
        "ip_administered_dose",
        "ip_dose",
        "exposure_dose",
    ),
    _concept(
        "ip.administration.dose_with_unit_text",
        "ip.administration",
        "source_value",
        "ip_administered_dose_with_unit_text",
    ),
    _concept(
        "ip.administration.dose_unit",
        "ip.administration",
        "unit",
        "ip_administration_dose_unit",
        "actual_dose_unit",
    ),
    _concept(
        "ip.administration.route",
        "ip.administration",
        "category",
        "ip_administration_route",
        "actual_dose_route",
    ),
    _concept(
        "ip.administration.frequency",
        "ip.administration",
        "category",
        "ip_administration_frequency",
        "actual_dose_frequency",
    ),
    _concept(
        "ip.administration.frequency_or_interval_raw",
        "ip.administration",
        "source_value",
        "dose_administration_interval_or_frequency_raw",
    ),
    _concept(
        "ip.administration.performed_flag",
        "ip.administration",
        "boolean",
        "ip_administration_performed_flag",
    ),
    _concept(
        "ip.administration.non_administration_reason",
        "ip.administration",
        "text",
        "ip_dose_not_administered_reason",
    ),
    _concept(
        "ip.administration.note",
        "ip.administration",
        "text",
        "ip_administration_comment",
    ),
    _concept(
        "ip.schedule.planned_day",
        "ip.schedule",
        "category",
        "ip_planned_dosing_day",
    ),
    _concept(
        "ip.schedule.other_day",
        "ip.schedule",
        "category",
        "ip_other_dosing_day",
    ),
    _concept(
        "ip.schedule.timepoint",
        "ip.schedule",
        "category",
        "ip_timepoint_category",
    ),
    _concept(
        "ip.dose_adjustment.action",
        "ip.dose_adjustment",
        "category",
        "ip_dose_adjustment",
        "ip_dose_adjustment_action",
    ),
    _concept(
        "ip.dose_adjustment.date",
        "ip.dose_adjustment",
        "date",
        "ip_dose_adjustment_date",
    ),
    _concept(
        "ip.dose_adjustment.reason",
        "ip.dose_adjustment",
        "text",
        "ip_dose_adjustment_reason",
    ),
    _concept(
        "ip.interruption.start_date",
        "ip.interruption",
        "date",
        "ip_interruption_start_date",
        "temporary_discontinuation_start",
    ),
    _concept(
        "ip.interruption.end_date",
        "ip.interruption",
        "date",
        "ip_interruption_end_date",
        "temporary_discontinuation_end",
    ),
    _concept(
        "ip.interruption.reason",
        "ip.interruption",
        "text",
        "ip_interruption_reason",
        "temporary_discontinuation_reason",
    ),
    _concept(
        "ip.discontinuation.date",
        "ip.discontinuation",
        "date",
        "ip_discontinuation_date",
        "permanent_discontinuation_date",
    ),
    _concept(
        "ip.discontinuation.reason",
        "ip.discontinuation",
        "text",
        "ip_discontinuation_reason",
        "permanent_discontinuation_reason",
    ),
    _concept(
        "ip.restart.date",
        "ip.restart",
        "date",
        "ip_restart_date",
        "dose_restart_date",
    ),
    _concept(
        "ip.restart.dose",
        "ip.restart",
        "number",
        "ip_restart_dose",
        "dose_restart_amount",
    ),
    _concept(
        "ip.restart.condition",
        "ip.restart",
        "text",
        "ip_restart_condition",
    ),
    _concept(
        "ip.other_change.action",
        "ip.other_change",
        "category",
        "ip_other_change_action",
        "other_ip_change",
    ),
    _concept(
        "ip.other_change.date",
        "ip.other_change",
        "date",
        "ip_other_change_date",
    ),
    _concept("ip.dispense.date", "ip.dispense", "date", "ip_dispense_date"),
    _concept(
        "ip.dispense.quantity",
        "ip.dispense",
        "number",
        "ip_dispense_quantity",
    ),
    _concept("ip.dispense.unit", "ip.dispense", "unit", "ip_dispense_unit"),
    _concept(
        "ip.dispense.container_id",
        "ip.dispense",
        "identifier",
        "ip_dispense_container_id",
    ),
    _concept("ip.return.date", "ip.return", "date", "ip_return_date"),
    _concept("ip.return.quantity", "ip.return", "number", "ip_return_quantity"),
    _concept("ip.return.unit", "ip.return", "unit", "ip_return_unit"),
    _concept(
        "ip.return.status_code",
        "ip.return",
        "category",
        "item_returned_flag_code",
    ),
    _concept(
        "ip.return.status_text",
        "ip.return",
        "text",
        "item_returned_flag_display_text",
    ),
    _concept(
        "ip.return.reason",
        "ip.return",
        "text",
        "non_return_reason_text",
    ),
    _concept(
        "ip.return.container_id",
        "ip.return",
        "identifier",
        "ip_return_container_id",
    ),
    _concept(
        "ip.accountability.lot_id",
        "ip.accountability",
        "identifier",
        "ip_lot_id",
        "ip_batch_id",
    ),
    _concept(
        "ip.accountability.status",
        "ip.accountability",
        "category",
        "ip_accountability_status",
    ),
    _concept(
        "ip.compliance.result",
        "ip.compliance",
        "number",
        "ip_compliance",
        "ip_compliance_result",
        "compliance_percentage_value",
    ),
    _concept(
        "ip.compliance.unit",
        "ip.compliance",
        "unit",
        "ip_compliance_unit",
        "compliance_percentage_unit",
    ),
    _concept(
        "coding.meddra.llt_code",
        "coding.meddra",
        "code",
        "meddra_llt_code",
    ),
    _concept(
        "coding.meddra.llt_term",
        "coding.meddra",
        "term",
        "meddra_llt_term",
    ),
    _concept(
        "coding.meddra.pt_code",
        "coding.meddra",
        "code",
        "meddra_pt_code",
        "meddra_preferred_term_code",
    ),
    _concept(
        "coding.meddra.pt_term",
        "coding.meddra",
        "term",
        "meddra_pt_term",
        "meddra_preferred_term",
    ),
    _concept(
        "coding.meddra.hlt_code",
        "coding.meddra",
        "code",
        "meddra_hlt_code",
    ),
    _concept(
        "coding.meddra.hlt_term",
        "coding.meddra",
        "term",
        "meddra_hlt_term",
    ),
    _concept(
        "coding.meddra.hlgt_code",
        "coding.meddra",
        "code",
        "meddra_hlgt_code",
    ),
    _concept(
        "coding.meddra.hlgt_term",
        "coding.meddra",
        "term",
        "meddra_hlgt_term",
    ),
    _concept(
        "coding.meddra.soc_code",
        "coding.meddra",
        "code",
        "meddra_soc_code",
    ),
    _concept(
        "coding.meddra.soc_term",
        "coding.meddra",
        "term",
        "meddra_soc_term",
    ),
    _concept(
        "coding.drug.code",
        "coding.drug",
        "code",
        "drug_dictionary_code",
        "whodrug_code",
    ),
    _concept(
        "coding.drug.preferred_term",
        "coding.drug",
        "term",
        "drug_dictionary_preferred_term",
        "whodrug_preferred_term",
        "coded_preferred_term",
    ),
    # Treatment-object identity concepts (project-neutral).
    _concept(
        "treatment.identity.name",
        "treatment.identity",
        "text",
        "treatment_name",
        "medication_name",
        "product_name",
    ),
    _concept(
        "treatment.identity.role",
        "treatment.identity",
        "category",
        "treatment_role",
        "treatment_object_role",
    ),
    _concept(
        "treatment.identity.randomized_assignment",
        "treatment.identity",
        "category",
        "randomized_treatment",
        "randomization_assignment",
        "treatment_arm",
    ),
    _concept(
        "treatment.identity.investigational_product",
        "treatment.identity",
        "category",
        "investigational_product",
        "ip_identity",
        "study_drug_identity",
    ),
    _concept(
        "treatment.administration.neutral",
        "treatment.administration",
        "source_value",
        "treatment_administration_neutral",
        "treatment_administration_unresolved_identity",
    ),
    # Dose ambiguity concepts.
    _concept(
        "ip.dose.planned",
        "ip.dose_planned",
        "number",
        "ip_planned_dose",
        "planned_dose",
    ),
    _concept(
        "ip.dose.prescribed",
        "ip.dose_prescribed",
        "number",
        "ip_prescribed_dose",
        "prescribed_dose",
    ),
    _concept(
        "ip.dose.unresolved",
        "ip.dose_unresolved",
        "source_value",
        "ip_dose_unresolved_meaning",
        "dose_meaning_unresolved",
    ),
)

# Backward-compatible alias for scripts and adjacent code that reference the
# historical v1 name. The live catalog is ROLE_CATALOG_V2.
ROLE_CATALOG_V1 = ROLE_CATALOG_V2


CAPABILITY_MANIFEST_V1: tuple[MonitoringCapabilityManifestEntry, ...] = (
    MonitoringCapabilityManifestEntry(
        capability_id="raw_source_review",
    ),
    MonitoringCapabilityManifestEntry(
        capability_id="subject_timeline",
        required_role_concepts=("metadata.subject_id",),
        allowed_limited_modes=("source_values_without_exact_temporal_inference",),
        dependent_rule_ids=("G-DATE-001", "G-CODE-002"),
    ),
    MonitoringCapabilityManifestEntry(
        capability_id="patient_profile",
        required_role_concepts=("metadata.subject_id",),
        allowed_limited_modes=(
            "source_values_without_standardized_coding",
            "source_values_without_scale_recalculation",
            "source_values_without_lab_grading",
        ),
        dependent_rule_ids=("G-CODE-002", "G-SCALE-001", "G-LAB-001"),
    ),
    MonitoringCapabilityManifestEntry(
        capability_id="ae_mh_reconciliation",
        dependent_rule_ids=("G-AEMH-001",),
    ),
    MonitoringCapabilityManifestEntry(
        capability_id="standard_coding_rules",
        required_lineage_contracts=("coding_system_and_version",),
        dependent_rule_ids=("G-CODE-001", "G-CODE-002"),
    ),
    MonitoringCapabilityManifestEntry(
        capability_id="precise_temporal_rules",
        required_lineage_contracts=("day_precision_or_bounded_partial_date",),
        dependent_rule_ids=("G-DATE-001",),
    ),
    MonitoringCapabilityManifestEntry(
        capability_id="lab_ctcae_rules",
        required_lineage_contracts=(
            "result_unit_reference_range_and_grading_definition",
        ),
        dependent_rule_ids=("G-LAB-001",),
    ),
    MonitoringCapabilityManifestEntry(
        capability_id="protocol_medication_rules",
        dependent_rule_ids=("G-CMIP-001", "G-CMIP-002"),
    ),
    MonitoringCapabilityManifestEntry(
        capability_id="ip_exposure_adherence",
        required_lineage_contracts=("separated_ip_actions_and_recomputable_exposure",),
        dependent_rule_ids=("G-CMIP-001", "G-CMIP-002"),
    ),
    MonitoringCapabilityManifestEntry(
        capability_id="ip_change_lifecycle",
        required_lineage_contracts=("distinct_ip_change_action_families",),
        dependent_rule_ids=(
            "G-CMIP-005",
            "G-CMIP-006",
            "G-CMIP-007",
        ),
    ),
    MonitoringCapabilityManifestEntry(
        capability_id="scale_recalculation",
        required_lineage_contracts=("scale_version_items_branches_and_formula",),
        dependent_rule_ids=("G-SCALE-001",),
    ),
)


_CAPABILITY_RULE_IMPACTS: Mapping[
    str,
    tuple[tuple[str, MappingCapabilityStateCode, str], ...],
] = {
    "G-CODE-002": (
        (
            "standard_coding_rules",
            MappingCapabilityStateCode.BLOCKED_BY_QUALITY,
            "coding_lineage_incomplete",
        ),
        (
            "subject_timeline",
            MappingCapabilityStateCode.LIMITED,
            "standardized_coding_unavailable",
        ),
        (
            "patient_profile",
            MappingCapabilityStateCode.LIMITED,
            "standardized_coding_unavailable",
        ),
    ),
    "G-DATE-001": (
        (
            "precise_temporal_rules",
            MappingCapabilityStateCode.BLOCKED_BY_QUALITY,
            "exact_date_precision_unavailable",
        ),
        (
            "subject_timeline",
            MappingCapabilityStateCode.LIMITED,
            "partial_date_source_values_only",
        ),
    ),
    "G-SCALE-001": (
        (
            "scale_recalculation",
            MappingCapabilityStateCode.BLOCKED_BY_QUALITY,
            "scale_recalculation_lineage_incomplete",
        ),
        (
            "patient_profile",
            MappingCapabilityStateCode.LIMITED,
            "source_scale_values_only",
        ),
    ),
    "G-LAB-001": (
        (
            "lab_ctcae_rules",
            MappingCapabilityStateCode.BLOCKED_BY_QUALITY,
            "lab_grading_lineage_incomplete",
        ),
        (
            "patient_profile",
            MappingCapabilityStateCode.LIMITED,
            "source_lab_values_only",
        ),
    ),
    "G-CMIP-003": (
        (
            "ip_exposure_adherence",
            MappingCapabilityStateCode.BLOCKED_BY_QUALITY,
            "ip_action_roles_unresolved",
        ),
    ),
    "G-CMIP-004": (
        (
            "ip_exposure_adherence",
            MappingCapabilityStateCode.BLOCKED_BY_QUALITY,
            "ip_accountability_roles_unresolved",
        ),
    ),
    "G-CMIP-005": (
        (
            "ip_change_lifecycle",
            MappingCapabilityStateCode.BLOCKED_BY_QUALITY,
            "treatment_identity_not_established",
        ),
        (
            "ip_exposure_adherence",
            MappingCapabilityStateCode.BLOCKED_BY_QUALITY,
            "treatment_identity_not_established",
        ),
    ),
    "G-CMIP-006": (
        (
            "ip_exposure_adherence",
            MappingCapabilityStateCode.BLOCKED_BY_QUALITY,
            "dose_semantics_indistinguishable",
        ),
    ),
    "G-CMIP-007": (
        (
            "ip_change_lifecycle",
            MappingCapabilityStateCode.BLOCKED_BY_QUALITY,
            "ip_change_action_families_not_available",
        ),
    ),
    "G-SCALE-002": (
        (
            "patient_profile",
            MappingCapabilityStateCode.LIMITED,
            "scale_score_misclassified_as_procedure",
        ),
    ),
    "G-AEMH-001": (
        (
            "ae_mh_reconciliation",
            MappingCapabilityStateCode.BLOCKED_BY_QUALITY,
            "reported_term_coding_anchor_missing",
        ),
    ),
}


_ACTION_MARKERS: Mapping[str, tuple[str, ...]] = {
    "ip.administration": (
        "administration",
        "administered.dose",
        "actual.dose",
        "actual.exposure",
        "实际给药",
    ),
    "ip.dose_adjustment": ("dose.adjustment", "dose.change", "剂量调整"),
    "ip.interruption": ("interruption", "temporary.discontinuation", "暂时停药"),
    "ip.discontinuation": ("permanent.discontinuation", "永久停药"),
    "ip.restart": ("restart", "resume", "重启"),
    "ip.dispense": ("dispense", "dispensing", "发放"),
    "ip.return": ("return", "returned", "回收"),
    "ip.compliance": ("compliance", "adherence", "依从"),
}
_IP_ACCOUNTABILITY_MARKERS: tuple[str, ...] = (
    "drug.accountability",
    "drug.amount.presented",
    "drug.weight",
    "withdrawn.dose",
    "study.drug.inventory",
    "investigational.product.inventory",
    "试验药物盘点",
    "试验药物责任",
)
_SCALE_SCORE_MARKERS: tuple[str, ...] = (
    "score",
    "total.score",
    "total",
    "sum",
    "subscore",
    "sub.scale",
    "index.score",
    "severity.score",
    "symptom.score",
    "rating.total",
)
_SCALE_FORM_MARKERS: tuple[str, ...] = (
    "scale",
    "questionnaire",
    "assessment.scale",
    "patient.reported.outcome",
    "symptom.assessment",
    "disease.assessment",
    "nasal.polyp",
    "quality.of.life",
)
_PROCEDURE_RECORD_MARKERS: tuple[str, ...] = (
    "procedure.number",
    "record.number",
    "study.procedure",
    "sequence.number",
    "assessment.number",
    "test.number",
    "panel.number",
    "episode.number",
)
_DOSE_AMBIGUITY_MARKERS: tuple[str, ...] = (
    "dose.or.prescribed",
    "planned.or.actual",
    "planned.or.administered",
    "prescribed.or.administered",
    "dose.and.administered",
    "dose.text",
    "dose.value.text",
    "dose.with.unit.text",
    "prescribed.or.actual",
)
_NON_SPECIFIC_CODING_RE = re.compile(
    r"(?:unknown|unspecified|pending|field.?name|term.?code|"
    r"project.?dictionary|local.?dictionary|待确认|未指定|不明确|不详|"
    r"项目(?:字典|词典)|本地(?:字典|词典)|未明确(?:的)?(?:项目)?(?:字典|词典))",
    re.IGNORECASE,
)


def evaluate_mapping_semantic_quality(
    *,
    fields: Sequence[Any],
    expected_fields: Iterable[tuple[str, str]] | None = None,
    domain_family_hints: Mapping[str, str] | None = None,
    role_catalog: Sequence[RoleConcept] = ROLE_CATALOG_V2,
) -> MappingSemanticQualityReport:
    """Evaluate one complete mapping draft without reading or mutating state."""

    capability_manifest_sha256 = current_capability_manifest_sha256()
    aliases, concepts = _compile_role_catalog(role_catalog)
    normalized = tuple(
        sorted(
            (
                _normalize_field(field, aliases=aliases, concepts=concepts)
                for field in fields
            ),
            key=lambda item: (
                item.domain,
                item.source_field,
                item.raw_role,
                item.field_kind,
            ),
        )
    )
    hints = {
        str(domain).strip().casefold(): str(family).strip().casefold()
        for domain, family in (domain_family_hints or {}).items()
    }
    expected = (
        frozenset(
            (str(domain).strip(), str(source_field).strip())
            for domain, source_field in expected_fields
        )
        if expected_fields is not None
        else None
    )
    input_payload = {
        "fields": [_field_payload(item) for item in normalized],
        "expected_fields": sorted(expected) if expected is not None else None,
        "domain_family_hints": sorted(hints.items()),
        "role_catalog_version": ROLE_CATALOG_VERSION,
        "rule_catalog_version": RULE_CATALOG_VERSION,
        "capability_manifest_version": CAPABILITY_MANIFEST_VERSION,
        "capability_manifest_sha256": capability_manifest_sha256,
    }
    input_sha256 = _sha256(input_payload)

    findings: list[SemanticFindingGroup] = []
    _evaluate_coverage(normalized, expected, findings)
    _evaluate_closed_roles(normalized, findings)
    _evaluate_metadata_consistency(normalized, findings)
    _evaluate_cm_ip_boundaries(normalized, hints, findings)
    _evaluate_ip_action_separation(normalized, findings)
    _evaluate_treatment_identity(normalized, hints, findings)
    _evaluate_dose_ambiguity(normalized, findings)
    _evaluate_scale_protection(normalized, findings)
    _evaluate_ip_change_capability(normalized, findings)
    _evaluate_coding_lineage(normalized, findings)
    _evaluate_ae_mh_boundaries(normalized, findings)
    _evaluate_date_precision(normalized, findings)
    _evaluate_scale_lineage(normalized, findings)
    _evaluate_lab_lineage(normalized, findings)
    _evaluate_deterministic_lineage(normalized, findings)

    normalized_findings = tuple(
        _normalize_finding_capability_scope(item) for item in findings
    )
    ordered = tuple(
        sorted(
            normalized_findings,
            key=lambda item: (
                _severity_rank(item.severity),
                item.rule_id,
                item.finding_group_id,
            ),
        )
    )
    global_count = sum(
        item.severity == SemanticFindingSeverity.GLOBAL_BLOCKER
        for item in ordered
    )
    capability_count = sum(
        item.severity == SemanticFindingSeverity.CAPABILITY_BLOCKER
        for item in ordered
    )
    warning_count = sum(
        item.severity == SemanticFindingSeverity.REVIEW_WARNING
        for item in ordered
    )
    if global_count:
        status = SemanticQualityStatus.BLOCKED
        activation_disposition = MappingActivationDisposition.REJECT
    elif capability_count:
        status = SemanticQualityStatus.PASS_WITH_WARNINGS
        activation_disposition = MappingActivationDisposition.ACTIVATE_RESTRICTED
    elif warning_count:
        status = SemanticQualityStatus.PASS_WITH_WARNINGS
        activation_disposition = MappingActivationDisposition.ACTIVATE_FULL
    else:
        status = SemanticQualityStatus.PASSED
        activation_disposition = MappingActivationDisposition.ACTIVATE_FULL
    capability_states = _build_capability_states(ordered)

    report_payload = {
        "schema_version": SEMANTIC_QUALITY_SCHEMA_VERSION,
        "role_catalog_version": ROLE_CATALOG_VERSION,
        "rule_catalog_version": RULE_CATALOG_VERSION,
        "input_sha256": input_sha256,
        "status": status.value,
        "activation_disposition": activation_disposition.value,
        "capability_manifest_version": CAPABILITY_MANIFEST_VERSION,
        "capability_manifest_sha256": capability_manifest_sha256,
        "global_blocker_count": global_count,
        "capability_blocker_count": capability_count,
        "warning_count": warning_count,
        "finding_groups": [_json_ready(asdict(item)) for item in ordered],
        "capability_states": [
            _json_ready(asdict(item)) for item in capability_states
        ],
    }
    return MappingSemanticQualityReport(
        schema_version=SEMANTIC_QUALITY_SCHEMA_VERSION,
        role_catalog_version=ROLE_CATALOG_VERSION,
        rule_catalog_version=RULE_CATALOG_VERSION,
        input_sha256=input_sha256,
        status=status,
        activation_disposition=activation_disposition,
        capability_manifest_version=CAPABILITY_MANIFEST_VERSION,
        capability_manifest_sha256=capability_manifest_sha256,
        global_blocker_count=global_count,
        capability_blocker_count=capability_count,
        warning_count=warning_count,
        finding_groups=ordered,
        capability_states=capability_states,
        report_sha256=_sha256(report_payload),
    )


def _compile_role_catalog(
    catalog: Sequence[RoleConcept],
) -> tuple[dict[str, str], dict[str, RoleConcept]]:
    aliases: dict[str, str] = {}
    concepts: dict[str, RoleConcept] = {}
    for concept in catalog:
        if concept.role_concept_id in concepts:
            raise ValueError("role catalog contains duplicate concept IDs")
        concepts[concept.role_concept_id] = concept
        for alias in (concept.role_concept_id, *concept.aliases):
            key = _normalize_token(alias)
            prior = aliases.get(key)
            if prior is not None and prior != concept.role_concept_id:
                raise ValueError("role catalog aliases must resolve uniquely")
            aliases[key] = concept.role_concept_id
    return aliases, concepts


@lru_cache(maxsize=1)
def _closed_role_catalog_v2(
) -> tuple[dict[str, str], dict[str, RoleConcept]]:
    return _compile_role_catalog(ROLE_CATALOG_V2)


def resolve_closed_monitoring_role_concept(
    role: str,
) -> RoleConcept | None:
    """Resolve only an explicit catalog role or alias, without fallback inference."""

    aliases, concepts = _closed_role_catalog_v2()
    concept_id = aliases.get(_normalize_token(role))
    if not concept_id:
        return None
    return concepts[concept_id]


def current_capability_manifest_sha256() -> str:
    return _sha256(
        {
            "manifest_version": CAPABILITY_MANIFEST_VERSION,
            "capabilities": [
                _json_ready(asdict(item)) for item in CAPABILITY_MANIFEST_V1
            ],
        }
    )


def _normalize_field(
    field: Any,
    *,
    aliases: Mapping[str, str],
    concepts: Mapping[str, RoleConcept],
) -> _NormalizedField:
    domain = str(_read(field, "domain", "")).strip()
    source_field = str(_read(field, "source_field", "")).strip()
    raw_role = str(_read(field, "recommended_role", "")).strip()
    raw_kind = _read(field, "field_kind", MonitoringFieldKind.UNMAPPED)
    field_kind = (
        raw_kind.value if isinstance(raw_kind, MonitoringFieldKind) else str(raw_kind)
    )
    normalized_role = _normalize_token(raw_role)
    concept_id = aliases.get(normalized_role, "")
    if not concept_id:
        concept_id = _fallback_role_concept(
            normalized_role,
            field_kind=field_kind,
        )
    concept = concepts.get(concept_id)
    related = _read(field, "related_fields", ()) or ()
    return _NormalizedField(
        domain=domain,
        source_field=source_field,
        source_key=source_field.casefold(),
        raw_role=raw_role,
        role_concept_id=concept_id,
        role_family=concept.role_family if concept is not None else "",
        value_semantics=concept.value_semantics if concept is not None else "",
        field_kind=field_kind,
        related_fields=tuple(sorted(str(item).strip() for item in related if str(item).strip())),
        standards_reference=_mapping_or_none(_read(field, "standards_reference", None)),
        derivation_lineage=_mapping_or_none(_read(field, "derivation_lineage", None)),
        coding_lineage=_mapping_or_none(_read(field, "coding_lineage", None)),
        value_constraints=_mapping_or_none(_read(field, "value_constraints", None)),
        object_identity=str(
            _read(field, "object_identity", "not_applicable")
        ).strip(),
        object_identity_evidence_fields=tuple(
            sorted(
                str(item).strip()
                for item in (
                    _read(field, "object_identity_evidence_fields", ()) or ()
                )
                if str(item).strip()
            )
        ),
        object_identity_binding_id=str(
            _read(field, "object_identity_binding_id", "")
        ).strip(),
        validated_treatment_identity_binding=_mapping_or_none(
            _read(field, "validated_treatment_identity_binding", None)
        ),
        dose_semantics=str(
            _read(field, "dose_semantics", "not_applicable")
        ).strip(),
        quality_gate_actions=tuple(
            sorted(
                str(item).strip()
                for item in (_read(field, "quality_gate_actions", ()) or ())
                if str(item).strip()
            )
        ),
    )


def _fallback_role_concept(
    normalized_role: str,
    *,
    field_kind: str,
) -> str:
    """Classify non-core source roles without inventing project-specific concepts."""

    if field_kind == MonitoringFieldKind.UNMAPPED.value:
        return ""
    if field_kind == MonitoringFieldKind.SOURCE_METADATA.value:
        return ""
    if normalized_role.startswith(("ip.", "investigational.", "study.drug.")):
        return ""
    if normalized_role.startswith(("treatment.", "background.therapy", "background.medication")):
        return "treatment.identity.name"
    if normalized_role.startswith(("meddra.",)):
        return "coding.meddra.source_other"
    if normalized_role.startswith(
        ("atc.", "drug.dictionary.", "drug.preferred.", "whodrug.")
    ):
        return "coding.drug.source_other"
    if normalized_role.startswith(("ae.", "adverse.event.")):
        return "ae.source_other"
    if normalized_role.startswith(("mh.", "medical.history.")):
        return "mh.source_other"
    if normalized_role.startswith(("cm.", "concomitant.medication.")):
        return "cm.source_other"
    if normalized_role.startswith(
        ("lab.", "lb.", "original.result.", "reference.range.")
    ):
        return "lab.source_other"
    if normalized_role.startswith(
        ("easi.", "dlqi.", "cdlqi.", "bsa.", "scale.", "questionnaire.")
    ):
        return "scale.source_other"
    if normalized_role.startswith(
        ("assessment.", "performed.", "not.performed.", "body.region.")
    ):
        return "assessment.source_other"
    if normalized_role.startswith(
        (
            "disposition.",
            "deviation.",
            "death.",
            "early.",
            "end.of.",
            "last.study.",
        )
    ):
        return "disposition.source_other"
    if normalized_role.startswith(
        ("subject.", "sex.", "ethnicity.", "birth.", "age.")
    ):
        return "demographics.source_other"
    if normalized_role.startswith(
        (
            "visit.",
            "form.",
            "crf.",
            "page.",
            "edc.",
            "record.",
            "project.",
            "study.",
        )
    ):
        return "metadata.source_other"
    return "clinical.source_other"


def _evaluate_coverage(
    fields: tuple[_NormalizedField, ...],
    expected: frozenset[tuple[str, str]] | None,
    findings: list[SemanticFindingGroup],
) -> None:
    indexed: dict[tuple[str, str], list[_NormalizedField]] = {}
    for field in fields:
        indexed.setdefault((field.domain, field.source_field), []).append(field)
    duplicates = tuple(
        item
        for group in indexed.values()
        if len(group) > 1
        for item in group
    )
    actual = frozenset(indexed)
    missing = expected.difference(actual) if expected is not None else frozenset()
    unexpected = actual.difference(expected) if expected is not None else frozenset()
    if duplicates or missing or unexpected:
        affected = tuple(item.ref for item in duplicates)
        synthetic = tuple(
            SemanticFieldRef(domain, source_field, "missing")
            for domain, source_field in sorted(missing)
        ) + tuple(
            SemanticFieldRef(domain, source_field, "unexpected")
            for domain, source_field in sorted(unexpected)
        )
        _add_finding(
            findings,
            rule_id="G-COVER-001",
            severity=SemanticFindingSeverity.GLOBAL_BLOCKER,
            clinical_topic="mapping_integrity",
            title_zh="字段映射覆盖不完整",
            summary_zh=(
                "完整字段集合存在重复、遗漏或越界映射，不能形成确定的项目映射。"
            ),
            affected_fields=affected + synthetic,
        )


def _evaluate_closed_roles(
    fields: tuple[_NormalizedField, ...],
    findings: list[SemanticFindingGroup],
) -> None:
    unknown = tuple(
        field
        for field in fields
        if not field.role_concept_id
        and field.field_kind != MonitoringFieldKind.UNMAPPED.value
    )
    if unknown:
        _add_finding(
            findings,
            rule_id="G-ROLE-002",
            severity=SemanticFindingSeverity.GLOBAL_BLOCKER,
            clinical_topic="role_catalog",
            title_zh="核心角色未进入闭合目录",
            summary_zh=(
                "存在无法解析到项目无关角色概念的自由角色名；应选择目录角色或保持未映射。"
            ),
            affected_fields=tuple(item.ref for item in unknown),
        )


def _evaluate_metadata_consistency(
    fields: tuple[_NormalizedField, ...],
    findings: list[SemanticFindingGroup],
) -> None:
    by_source: dict[str, list[_NormalizedField]] = {}
    by_concept: dict[str, list[_NormalizedField]] = {}
    for field in fields:
        if field.role_family != "metadata":
            continue
        by_source.setdefault(field.source_key, []).append(field)
        by_concept.setdefault(field.role_concept_id, []).append(field)
    conflicts: list[_NormalizedField] = []
    for group in (*by_source.values(), *by_concept.values()):
        if len(group) < 2:
            continue
        concepts = {item.role_concept_id for item in group}
        kinds = {item.field_kind for item in group}
        if len(concepts) > 1 or len(kinds) > 1:
            conflicts.extend(group)
    if conflicts:
        _add_finding(
            findings,
            rule_id="G-ROLE-001",
            severity=SemanticFindingSeverity.GLOBAL_BLOCKER,
            clinical_topic="technical_metadata",
            title_zh="技术元数据跨域语义不一致",
            summary_zh=(
                "同一技术标识在不同数据域中使用了不同角色概念或字段性质。"
            ),
            affected_fields=tuple(item.ref for item in conflicts),
        )


def _evaluate_cm_ip_boundaries(
    fields: tuple[_NormalizedField, ...],
    hints: Mapping[str, str],
    findings: list[SemanticFindingGroup],
) -> None:
    by_domain: dict[str, list[_NormalizedField]] = {}
    for field in fields:
        by_domain.setdefault(field.domain.casefold(), []).append(field)
    conflicts: list[_NormalizedField] = []
    for domain_key, group in by_domain.items():
        families = {item.role_family for item in group if item.role_family}
        explicit_family = hints.get(domain_key, "")
        weak_family = "cm" if domain_key == "cm" else ""
        if explicit_family == "cm" and any(
            item.role_family.startswith("ip.") for item in group
        ):
            conflicts.extend(group)
        elif explicit_family == "ip" and any(
            item.role_family == "cm" for item in group
        ):
            conflicts.extend(group)
        elif explicit_family == "background" and any(
            item.role_family.startswith("ip.") for item in group
        ):
            conflicts.extend(group)
        elif "cm" in families and any(family.startswith("ip.") for family in families):
            conflicts.extend(group)
        elif weak_family == "cm" and any(
            item.role_family.startswith("ip.") for item in group
        ):
            conflicts.extend(group)
    if conflicts:
        _add_finding(
            findings,
            rule_id="G-CMIP-001",
            severity=SemanticFindingSeverity.GLOBAL_BLOCKER,
            clinical_topic="cm_ip_boundary",
            title_zh="非试验用药与试验药物角色混用",
            summary_zh=(
                "同一语义域中混入 CM 与试验药物角色；CM 仅表示非试验用药或治疗。"
            ),
            affected_fields=tuple(item.ref for item in conflicts),
        )


def _evaluate_ip_action_separation(
    fields: tuple[_NormalizedField, ...],
    findings: list[SemanticFindingGroup],
) -> None:
    ambiguous: list[_NormalizedField] = []
    unresolved: list[_NormalizedField] = []
    unresolved_accountability: list[_NormalizedField] = []
    for field in fields:
        normalized_role = _normalize_token(field.raw_role)
        matched = {
            family
            for family, markers in _ACTION_MARKERS.items()
            if any(marker in normalized_role for marker in markers)
        }
        if len(matched) > 1:
            ambiguous.append(field)
        elif (
            len(matched) == 1
            and not field.role_family.startswith("ip.")
            and field.role_family != "cm"
        ):
            unresolved.append(field)
        if (
            any(marker in normalized_role for marker in _IP_ACCOUNTABILITY_MARKERS)
            and not field.role_family.startswith("ip.")
            and field.role_family != "cm"
        ):
            unresolved_accountability.append(field)
    if ambiguous:
        _add_finding(
            findings,
            rule_id="G-CMIP-002",
            severity=SemanticFindingSeverity.GLOBAL_BLOCKER,
            clinical_topic="ip_action_boundary",
            title_zh="试验药物动作语义未分离",
            summary_zh=(
                "一个字段角色同时表达多个试验药物动作；实际给药、剂量调整、"
                "停药、重启、发放、回收和依从性必须分别映射。"
            ),
            affected_fields=tuple(item.ref for item in ambiguous),
        )
    if unresolved:
        _add_finding(
            findings,
            rule_id="G-CMIP-003",
            severity=SemanticFindingSeverity.CAPABILITY_BLOCKER,
            clinical_topic="ip_action_boundary",
            title_zh="试验药物动作尚未进入闭合角色",
            summary_zh=(
                "来源角色已表达回收、依从性、剂量调整或其他试验药物动作，"
                "但尚未映射到独立的闭合 IP 角色；原始值可保留，"
                "相关暴露和依从性结论不得启用。"
            ),
            affected_fields=tuple(item.ref for item in unresolved),
        )
    if unresolved_accountability:
        _add_finding(
            findings,
            rule_id="G-CMIP-004",
            severity=SemanticFindingSeverity.CAPABILITY_BLOCKER,
            clinical_topic="ip_accountability_boundary",
            title_zh="试验药物责任或盘点语义尚未闭合",
            summary_zh=(
                "来源角色疑似表达试验药物称量、呈交、撤回剂量或库存责任，"
                "但未显式进入独立 IP 责任/盘点角色；原始值可保留，"
                "不得据此计算给药、回收或依从性。"
            ),
            affected_fields=tuple(item.ref for item in unresolved_accountability),
        )


def _evaluate_treatment_identity(
    fields: tuple[_NormalizedField, ...],
    hints: Mapping[str, str],
    findings: list[SemanticFindingGroup],
) -> None:
    """G-CMIP-005: IP identity requires an independent, auditable anchor.

    A provider-assigned identity role — even with a self-consistent object
    identity and self-cited evidence fields — is circular self-attestation
    and cannot establish investigational-product identity. A domain name
    (EX, dosing, PM, or any project-specific name) is likewise never
    evidence. Accepted anchors are independent of the mapping being
    guarded:

    - medically confirmed domain-family metadata supplied as an explicit
      ``"ip"`` domain-family hint, or
    - a frozen source-profile treatment identity binding that was
      validated by the AI service against the frozen field profile and
      whose source field is part of this same mapping.

    Without such an anchor, fields with IP administration/dose roles keep
    their source values but exposure and IP-change capabilities stay
    blocked. Prior medication, prior therapy, background, rescue, and
    concomitant/non-study treatment domains therefore cannot be promoted
    to investigational product by the provider alone.
    """

    by_domain: dict[str, list[_NormalizedField]] = {}
    for field in fields:
        by_domain.setdefault(field.domain.casefold(), []).append(field)

    mapped_keys = {
        (field.domain.casefold(), field.source_key) for field in fields
    }
    anchored_domains: set[str] = {
        domain_key for domain_key, family in hints.items() if family == "ip"
    }
    for field in fields:
        binding = _field_validated_treatment_identity_binding(
            field,
            mapped_keys=mapped_keys,
        )
        if binding is not None:
            anchored_domains.add(field.domain.casefold())
            anchored_domains.add(
                str(binding.get("source_domain", "")).strip().casefold()
            )

    unanchored: list[_NormalizedField] = []
    for domain_key, domain_fields in by_domain.items():
        if domain_key in anchored_domains:
            continue
        families = {item.role_family for item in domain_fields if item.role_family}
        has_ip_roles = any(
            family.startswith("ip.") or family == "treatment.administration"
            for family in families
        )
        if not has_ip_roles:
            continue
        unanchored.extend(
            field
            for field in domain_fields
            if field.role_family.startswith("ip.")
            or field.role_family == "treatment.administration"
        )

    if unanchored:
        _add_finding(
            findings,
            rule_id="G-CMIP-005",
            severity=SemanticFindingSeverity.CAPABILITY_BLOCKER,
            clinical_topic="treatment_object_identity",
            title_zh="试验药物身份证据不足",
            summary_zh=(
                "试验药物身份需要独立于字段映射输出的可审计锚点：经冻结来源"
                "画像校验的跨域治疗身份绑定，或经医学确认的域族元数据；"
                "模型自洽的身份角色、对象身份与自引证据不构成独立证据，"
                "域名同样不构成证据。证据不足时，来源值可保留在中性给药"
                "角色下，暴露和变更能力不得启用。"
            ),
            affected_fields=tuple(item.ref for item in unanchored),
        )


def _field_validated_treatment_identity_binding(
    field: _NormalizedField,
    *,
    mapped_keys: frozenset[tuple[str, str]] | set[tuple[str, str]],
) -> Mapping[str, Any] | None:
    """Return the field's frozen-profile identity binding when it is intact.

    The binding is only meaningful when the AI service validated it against
    the frozen field profile; the gate re-checks structural integrity and
    requires the binding's source field to be part of the same mapping so a
    dangling or fabricated reference cannot anchor a domain.
    """
    binding = field.validated_treatment_identity_binding
    if binding is None or not field.object_identity_binding_id:
        return None
    if (
        str(binding.get("schema_version", "")).strip()
        != "monitoring_treatment_identity_binding_v1"
        or str(binding.get("binding_id", "")).strip()
        != field.object_identity_binding_id
        or str(binding.get("target_domain", "")).strip().casefold()
        != field.domain.casefold()
        or str(binding.get("relationship_type", "")).strip()
        not in {
            "subject_level_randomized_assignment",
            "subject_level_treatment_assignment",
            "protocol_defined_treatment_binding",
        }
    ):
        return None
    join_keys = binding.get("join_keys")
    if (
        not isinstance(join_keys, list)
        or not join_keys
        or any(not str(item).strip() for item in join_keys)
    ):
        return None
    source_key = (
        str(binding.get("source_domain", "")).strip().casefold(),
        str(binding.get("source_field", "")).strip().casefold(),
    )
    if source_key not in mapped_keys:
        return None
    return binding


def _evaluate_dose_ambiguity(
    fields: tuple[_NormalizedField, ...],
    findings: list[SemanticFindingGroup],
) -> None:
    """G-CMIP-006: Indistinguishable dose fields must not silently pick a role.

    When multiple same-domain dose-like fields have indistinguishable evidence
    or the CRF label is absent, the mapping must not silently choose planned or
    actual. An unresolved dose meaning must be visible and actionable.
    """

    by_domain: dict[str, list[_NormalizedField]] = {}
    for field in fields:
        by_domain.setdefault(field.domain.casefold(), []).append(field)

    ambiguous: list[_NormalizedField] = []
    for domain_fields in by_domain.values():
        dose_fields = [
            field
            for field in domain_fields
            if _is_dose_like_field(field)
        ]
        for field in domain_fields:
            if _is_ambiguous_dose_role(field) and field not in ambiguous:
                ambiguous.append(field)
        if len(dose_fields) <= 1:
            continue
        value_signatures = {_dose_value_signature(field) for field in dose_fields}
        if len(value_signatures) == 1 and len(dose_fields) > 1:
            for field in dose_fields:
                if field not in ambiguous:
                    ambiguous.append(field)

    if ambiguous:
        _add_finding(
            findings,
            rule_id="G-CMIP-006",
            severity=SemanticFindingSeverity.CAPABILITY_BLOCKER,
            clinical_topic="dose_semantic_ambiguity",
            title_zh="剂量语义未分离或不可区分",
            summary_zh=(
                "同域多个剂量样字段的证据不可区分，或CRF标签缺失时，"
                "不得静默选择计划或实际剂量。计划、处方、实际给药、发放、"
                "回收和派生剂量语义必须分别映射；无法确定时保留为未解决剂量语义。"
            ),
            affected_fields=tuple(item.ref for item in ambiguous),
        )


def _is_dose_like_field(field: _NormalizedField) -> bool:
    """Check whether a field is a dose value (not action/reason/date/derived)."""
    if field.field_kind == MonitoringFieldKind.DETERMINISTIC_DERIVED.value:
        return False
    if (
        field.role_family == "ip.administration"
        and field.value_semantics in ("number", "source_value")
    ):
        return True
    if field.role_family in ("ip.dose_planned", "ip.dose_prescribed"):
        return True
    return False


def _is_ambiguous_dose_role(field: _NormalizedField) -> bool:
    """Check whether a field's role merges mutually exclusive dose concepts."""
    if field.dose_semantics in {
        "planned",
        "prescribed",
        "actual_administered",
        "dispensed",
        "returned",
        "duplicate_or_derived",
    }:
        return False
    normalized_role = _normalize_token(field.raw_role)
    return any(
        marker in normalized_role for marker in _DOSE_AMBIGUITY_MARKERS
    )


def _dose_value_signature(field: _NormalizedField) -> str:
    """Build a coarse signature for comparing dose fields."""
    return (
        f"{field.role_family}:{field.value_semantics}:"
        f"{field.dose_semantics}"
    )


def _evaluate_scale_protection(
    fields: tuple[_NormalizedField, ...],
    findings: list[SemanticFindingGroup],
) -> None:
    """G-SCALE-002: Numeric scale totals must not become procedure/record numbers.

    Use form/page context, scale-item siblings, labels and value shape together.
    Source totals remain source-collected unless a separately validated
    deterministic formula exists.
    """

    by_domain: dict[str, list[_NormalizedField]] = {}
    for field in fields:
        by_domain.setdefault(field.domain.casefold(), []).append(field)

    misclassified: list[_NormalizedField] = []
    for domain_key, domain_fields in by_domain.items():
        domain_has_scale_context = _domain_has_scale_context(domain_key, domain_fields)
        if not domain_has_scale_context:
            continue
        scale_siblings = [
            field
            for field in domain_fields
            if field.role_family == "scale"
            or any(
                marker in _normalize_token(field.raw_role)
                for marker in ("scale.item", "item.score", "量表条目", "条目评分")
            )
        ]
        if len(scale_siblings) < 2:
            continue

        for field in domain_fields:
            normalized_role = _normalize_token(field.raw_role)
            is_procedure_like = any(
                marker in normalized_role for marker in _PROCEDURE_RECORD_MARKERS
            )
            if not is_procedure_like:
                continue
            source_name = _normalize_token(field.source_field)
            total_like_source = any(
                marker in source_name
                for marker in (
                    "total",
                    "score",
                    "sum",
                    "subscore",
                    "总分",
                    "评分",
                    "合计",
                )
            )
            sibling_prefix_evidence = _shares_scale_item_prefix(
                field,
                scale_siblings,
            )
            if total_like_source or sibling_prefix_evidence:
                misclassified.append(field)

    if misclassified:
        _add_finding(
            findings,
            rule_id="G-SCALE-002",
            severity=SemanticFindingSeverity.GLOBAL_BLOCKER,
            clinical_topic="scale_score_protection",
            title_zh="量表总分被误判为程序或记录编号",
            summary_zh=(
                "量表总分或评分应保留为来源采集语义，不得仅因数值形状"
                "归为程序编号或记录编号。需结合表单/页面上下文、同胞条目、"
                "标签和值形状综合判断。"
            ),
            affected_fields=tuple(item.ref for item in misclassified),
        )


def _domain_has_scale_context(
    domain_key: str,
    domain_fields: list[_NormalizedField],
) -> bool:
    normalized_domain = _normalize_token(domain_key)
    if any(
        marker in normalized_domain for marker in _SCALE_FORM_MARKERS
    ):
        return True
    for field in domain_fields:
        normalized_role = _normalize_token(field.raw_role)
        if any(
            marker in normalized_role for marker in _SCALE_FORM_MARKERS
        ):
            return True
    return False


def _field_has_scale_siblings(
    target: _NormalizedField,
    domain_fields: list[_NormalizedField],
) -> bool:
    for field in domain_fields:
        if field.source_key == target.source_key:
            continue
        normalized_role = _normalize_token(field.raw_role)
        if any(
            marker in normalized_role
            for marker in ("item", "条目", "individual.item", "scale.item")
        ):
            return True
    return False


def _shares_scale_item_prefix(
    target: _NormalizedField,
    siblings: list[_NormalizedField],
) -> bool:
    target_token = re.sub(
        r"[^a-z0-9\u3400-\u4dbf\u4e00-\u9fff]+",
        "",
        target.source_field.casefold(),
    )
    target_alpha = re.sub(r"(?:total|score|sum|num|number|\d+)$", "", target_token)
    if len(target_alpha) < 3:
        return False
    matching = 0
    for sibling in siblings:
        sibling_token = re.sub(
            r"[^a-z0-9\u3400-\u4dbf\u4e00-\u9fff]+",
            "",
            sibling.source_field.casefold(),
        )
        sibling_alpha = re.sub(r"\d+$", "", sibling_token)
        if (
            len(sibling_alpha) >= 3
            and (
                sibling_alpha.startswith(target_alpha)
                or target_alpha.startswith(sibling_alpha)
            )
        ):
            matching += 1
    return matching >= 2


def _evaluate_ip_change_capability(
    fields: tuple[_NormalizedField, ...],
    findings: list[SemanticFindingGroup],
) -> None:
    """G-CMIP-007: Missing IP change-lifecycle fields = capability unavailable.

    If the listing lacks distinct source-backed fields for dose adjustment,
    interruption, restart, discontinuation and other IP changes, the quality
    report must explicitly limit that capability. Missing fields mean
    capability unavailable, never "no changes occurred."

    Only fires when the mapping already contains IP administration or exposure
    fields — if no IP fields exist at all, there is nothing to limit.
    """

    change_families = (
        "ip.dose_adjustment",
        "ip.interruption",
        "ip.discontinuation",
        "ip.restart",
        "ip.other_change",
    )
    has_ip_exposure = any(
        field.role_family.startswith("ip.")
        and not field.role_family.startswith("ip.dose_")
        for field in fields
    )
    if not has_ip_exposure:
        return

    present_families: set[str] = set()
    for field in fields:
        for family in change_families:
            if field.role_family == family:
                present_families.add(family)

    missing_families = set(change_families) - present_families
    if missing_families:
        _add_finding(
            findings,
            rule_id="G-CMIP-007",
            severity=SemanticFindingSeverity.CAPABILITY_BLOCKER,
            clinical_topic="ip_change_lifecycle_capability",
            title_zh="试验药物变更事件族不可用",
            summary_zh=(
                "当前listing缺少独立识别剂量调整、暂停、恢复、永久停药"
                "及其他试验药物变更的字段族。缺少字段表示该能力不可用，"
                "不等于未发生变更。AE措施和CM不得替代试验药物变更事件。"
            ),
            affected_fields=(),
        )


def _evaluate_coding_lineage(
    fields: tuple[_NormalizedField, ...],
    findings: list[SemanticFindingGroup],
) -> None:
    available_by_domain = {
        (item.domain.casefold(), item.source_key): item for item in fields
    }
    coded = tuple(
        item
        for item in fields
        if (
            item.role_family.startswith("coding.")
            or item.field_kind == MonitoringFieldKind.STANDARDIZED_CODED.value
        )
        and not _is_coding_support_field(item)
    )
    missing_source_lineage: list[_NormalizedField] = []
    invalid_standardized_claims: list[_NormalizedField] = []
    chains: dict[str, list[tuple[_NormalizedField, str, str]]] = {}
    for field in coded:
        lineage = field.coding_lineage or field.derivation_lineage
        coding_system = _lineage_text(lineage, "coding_system")
        version = _lineage_text(lineage, "dictionary_version")
        version_field = _lineage_text(lineage, "dictionary_version_field")
        chain_id = _lineage_text(lineage, "coding_chain_id")
        source_fields = tuple(
            str(item).strip()
            for item in ((lineage or {}).get("source_fields") or ())
            if str(item).strip()
        )
        source_fields_exist = bool(source_fields) and all(
            (field.domain.casefold(), source.casefold()) in available_by_domain
            for source in source_fields
        )
        version_support = (
            available_by_domain.get(
                (field.domain.casefold(), version_field.casefold())
            )
            if version_field
            else None
        )
        independent_version_supported = (
            version_support is not None
            and version_support.source_key != field.source_key
            and _is_coding_support_field(version_support)
        )
        effective_chain = chain_id or (
            f"{field.role_family}:{field.domain.casefold()}"
        )
        if coding_system and (version_field or version):
            chains.setdefault(effective_chain, []).append(
                (field, coding_system, version_field or version)
            )
        if (
            not coding_system
            or _NON_SPECIFIC_CODING_RE.search(coding_system)
            or not source_fields_exist
            or not independent_version_supported
        ):
            if field.field_kind == MonitoringFieldKind.STANDARDIZED_CODED.value:
                invalid_standardized_claims.append(field)
            else:
                missing_source_lineage.append(field)
            continue
    if missing_source_lineage:
        _add_finding(
            findings,
            rule_id="G-CODE-002",
            severity=SemanticFindingSeverity.CAPABILITY_BLOCKER,
            clinical_topic="coding_lineage",
            title_zh="编码体系或版本血缘不完整",
            summary_zh=(
                "编码角色缺少明确编码体系、真实来源字段或独立版本字段，"
                "不能作为可核验的标准编码事实。"
            ),
            affected_fields=tuple(item.ref for item in missing_source_lineage),
        )
    if invalid_standardized_claims:
        _add_finding(
            findings,
            rule_id="G-CODE-003",
            severity=SemanticFindingSeverity.GLOBAL_BLOCKER,
            clinical_topic="coding_lineage",
            title_zh="标准编码声明缺少必要血缘",
            summary_zh=(
                "字段已声明为标准编码，但缺少明确编码体系、真实来源字段"
                "或独立版本字段；"
                "必须降级为真实来源值或补齐可核验编码血缘。"
            ),
            affected_fields=tuple(
                item.ref for item in invalid_standardized_claims
            ),
        )
    inconsistent: list[_NormalizedField] = []
    for group in chains.values():
        systems = {system.casefold() for _, system, _ in group}
        versions = {version.casefold() for _, _, version in group}
        kinds = {field.field_kind for field, _, _ in group}
        if len(systems) > 1 or len(versions) > 1 or len(kinds) > 1:
            inconsistent.extend(field for field, _, _ in group)
    if inconsistent:
        _add_finding(
            findings,
            rule_id="G-CODE-001",
            severity=SemanticFindingSeverity.GLOBAL_BLOCKER,
            clinical_topic="coding_lineage",
            title_zh="同一编码链定义不一致",
            summary_zh=(
                "同一编码链中的编码体系、版本或字段性质不一致，必须按整链修订。"
            ),
            affected_fields=tuple(item.ref for item in inconsistent),
        )


def _is_coding_support_field(field: _NormalizedField) -> bool:
    return (
        field.field_kind == MonitoringFieldKind.SOURCE_METADATA.value
        and field.role_concept_id
        in {
            "coding.meddra.dictionary_version",
            "coding.meddra.dictionary_language",
            "coding.drug.dictionary_version",
            "coding.drug.dictionary_language",
        }
    )


def _evaluate_ae_mh_boundaries(
    fields: tuple[_NormalizedField, ...],
    findings: list[SemanticFindingGroup],
) -> None:
    domain_conflicts = tuple(
        field
        for field in fields
        if (
            field.domain.casefold() == "ae"
            and field.role_family == "mh"
        )
        or (
            field.domain.casefold() == "mh"
            and field.role_family == "ae"
        )
    )
    if domain_conflicts:
        _add_finding(
            findings,
            rule_id="G-AEMH-002",
            severity=SemanticFindingSeverity.GLOBAL_BLOCKER,
            clinical_topic="ae_mh_boundary",
            title_zh="AE 与 MH 来源角色发生互换",
            summary_zh=(
                "AE 报告事实与 MH 报告事实必须保持来源域边界，"
                "不能仅凭术语相似跨域替换。"
            ),
            affected_fields=tuple(item.ref for item in domain_conflicts),
        )

    collapsed = []
    for field in fields:
        token = _normalize_token(field.raw_role)
        has_seriousness = any(
            marker in token
            for marker in ("serious", "seriousness", "严重性", "严重标准")
        )
        has_severity = any(
            marker in token
            for marker in (
                "severity",
                "intensity",
                "toxicity.grade",
                "严重程度",
                "毒性等级",
            )
        )
        if has_seriousness and has_severity:
            collapsed.append(field)
    if collapsed:
        _add_finding(
            findings,
            rule_id="G-AEMH-003",
            severity=SemanticFindingSeverity.GLOBAL_BLOCKER,
            clinical_topic="ae_mh_boundary",
            title_zh="AE 严重性与严重程度未分离",
            summary_zh=(
                "SAE 严重性判定与 AE 严重程度/毒性分级是不同医学概念，"
                "不得合并为同一正式角色。"
            ),
            affected_fields=tuple(item.ref for item in collapsed),
        )

    by_domain: dict[str, list[_NormalizedField]] = {}
    for field in fields:
        domain_key = field.domain.casefold()
        if domain_key in {"ae", "mh"}:
            by_domain.setdefault(domain_key, []).append(field)

    for domain_key, domain_fields in by_domain.items():
        standardized_meddra = tuple(
            field
            for field in domain_fields
            if field.role_family == "coding.meddra"
            and field.field_kind
            == MonitoringFieldKind.STANDARDIZED_CODED.value
        )
        if not standardized_meddra:
            continue
        expected_report_role = (
            "ae.verbatim_term"
            if domain_key == "ae"
            else "mh.verbatim_term"
        )
        reported_terms = tuple(
            field
            for field in domain_fields
            if field.role_concept_id == expected_report_role
        )
        reported_keys = {item.source_key for item in reported_terms}
        unanchored = tuple(
            field
            for field in standardized_meddra
            if not reported_keys.intersection(
                str(item).strip().casefold()
                for item in (
                    (
                        field.coding_lineage
                        or field.derivation_lineage
                        or {}
                    ).get("source_fields")
                    or ()
                )
            )
        )
        if reported_terms and not unanchored:
            continue
        _add_finding(
            findings,
            rule_id="G-AEMH-001",
            severity=SemanticFindingSeverity.CAPABILITY_BLOCKER,
            clinical_topic="ae_mh_reconciliation",
            title_zh="报告术语与 MedDRA 编码链缺少来源锚点",
            summary_zh=(
                "同一 AE/MH 来源域内缺少报告术语，或标准 MedDRA 字段未逐项"
                "锚定该报告术语；不得跨域借用字段，也不得据此执行漏报对账"
                "或来源术语到标准术语的确定性追踪。"
            ),
            affected_fields=tuple(
                item.ref
                for item in (
                    *reported_terms,
                    *(unanchored or standardized_meddra),
                )
            ),
        )


def _evaluate_date_precision(
    fields: tuple[_NormalizedField, ...],
    findings: list[SemanticFindingGroup],
) -> None:
    partial: list[_NormalizedField] = []
    for field in fields:
        constraints = field.value_constraints or field.standards_reference or {}
        precision = _normalize_token(str(constraints.get("date_precision", "")))
        exact_supported = constraints.get("supports_exact_date")
        has_explicit_date_contract = bool(precision) or isinstance(
            exact_supported,
            bool,
        )
        if (
            field.value_semantics not in {"date", "datetime"}
            and not has_explicit_date_contract
        ):
            continue
        if precision in {
            "year",
            "month",
            "partial",
            "unknown",
            "year.month",
        } or exact_supported is False:
            partial.append(field)
    if partial:
        _add_finding(
            findings,
            rule_id="G-DATE-001",
            severity=SemanticFindingSeverity.CAPABILITY_BLOCKER,
            clinical_topic="date_precision",
            title_zh="日期精度不足以支持精确时间规则",
            summary_zh=(
                "来源日期可按其原始精度展示，但不能用于精确访视窗、"
                "洗脱期、持续时间或固定天数阈值判断。"
            ),
            affected_fields=tuple(item.ref for item in partial),
        )


def _evaluate_scale_lineage(
    fields: tuple[_NormalizedField, ...],
    findings: list[SemanticFindingGroup],
) -> None:
    scale_fields = tuple(item for item in fields if item.role_family == "scale")
    if not scale_fields:
        return
    recomputable = any(
        item.field_kind == MonitoringFieldKind.DETERMINISTIC_DERIVED.value
        and bool(item.derivation_lineage)
        for item in scale_fields
    )
    if not recomputable:
        _add_finding(
            findings,
            rule_id="G-SCALE-001",
            severity=SemanticFindingSeverity.CAPABILITY_BLOCKER,
            clinical_topic="scale_lineage",
            title_zh="量表复算血缘不完整",
            summary_zh=(
                "量表来源条目和来源总分仍可展示，但缺少版本、条目、"
                "分支、缺失值规则或可复算公式时不得生成工作台复算结论。"
            ),
            affected_fields=tuple(item.ref for item in scale_fields),
        )


def _evaluate_lab_lineage(
    fields: tuple[_NormalizedField, ...],
    findings: list[SemanticFindingGroup],
) -> None:
    lab_fields = tuple(item for item in fields if item.role_family == "lab")
    if not lab_fields:
        return
    normalized_roles = tuple(_normalize_token(item.raw_role) for item in lab_fields)
    has_result = any(
        any(marker in role for marker in ("result", "value", "original.result"))
        for role in normalized_roles
    )
    has_unit = any("unit" in role for role in normalized_roles)
    has_lower = any(
        any(marker in role for marker in ("lower", "low", "lln"))
        for role in normalized_roles
    )
    has_upper = any(
        any(marker in role for marker in ("upper", "high", "uln"))
        for role in normalized_roles
    )
    has_grading_definition = any(
        str((item.standards_reference or {}).get("ctcae_version", "")).strip()
        or str(
            (item.standards_reference or {}).get(
                "grading_definition_version",
                "",
            )
        ).strip()
        for item in lab_fields
    )
    if not (
        has_result
        and has_unit
        and has_lower
        and has_upper
        and has_grading_definition
    ):
        _add_finding(
            findings,
            rule_id="G-LAB-001",
            severity=SemanticFindingSeverity.CAPABILITY_BLOCKER,
            clinical_topic="lab_lineage",
            title_zh="实验室分级前置血缘不完整",
            summary_zh=(
                "实验室来源结果和来源异常标志仍可展示，但结果、单位、"
                "参考范围或分级定义不足时不得自动统一阈值或生成 CTCAE 分级。"
            ),
            affected_fields=tuple(item.ref for item in lab_fields),
        )


def _evaluate_deterministic_lineage(
    fields: tuple[_NormalizedField, ...],
    findings: list[SemanticFindingGroup],
) -> None:
    available = {
        (item.domain, item.source_field)
        for item in fields
    }
    invalid: list[_NormalizedField] = []
    for field in fields:
        if field.field_kind != MonitoringFieldKind.DETERMINISTIC_DERIVED.value:
            continue
        lineage = field.derivation_lineage
        sources = (
            tuple(str(item).strip() for item in lineage.get("source_fields", ()))
            if isinstance(lineage, Mapping)
            and isinstance(lineage.get("source_fields"), (list, tuple))
            else ()
        )
        formula = _lineage_text(lineage, "formula")
        confirmed = bool(lineage and lineage.get("user_confirmed") is True)
        source_refs_valid = bool(sources) and all(
            _source_ref_exists(
                source,
                current_domain=field.domain,
                available=available,
            )
            for source in sources
        )
        self_reference = any(
            source in {
                field.source_field,
                f"{field.domain}.{field.source_field}",
            }
            for source in sources
        )
        if (
            not sources
            or not formula
            or not confirmed
            or not source_refs_valid
            or self_reference
        ):
            invalid.append(field)
    if invalid:
        _add_finding(
            findings,
            rule_id="G-DERIVE-001",
            severity=SemanticFindingSeverity.GLOBAL_BLOCKER,
            clinical_topic="deterministic_lineage",
            title_zh="确定性派生血缘不可复算",
            summary_zh=(
                "确定性派生缺少有效源字段、明确公式或确认状态，不能作为确定性事实。"
            ),
            affected_fields=tuple(item.ref for item in invalid),
        )


def _source_ref_exists(
    source: str,
    *,
    current_domain: str,
    available: set[tuple[str, str]],
) -> bool:
    if "." in source:
        domain, source_field = source.split(".", 1)
        return (domain, source_field) in available
    return (current_domain, source) in available


def _add_finding(
    findings: list[SemanticFindingGroup],
    *,
    rule_id: str,
    severity: SemanticFindingSeverity,
    clinical_topic: str,
    title_zh: str,
    summary_zh: str,
    affected_fields: tuple[SemanticFieldRef, ...],
) -> None:
    unique_fields = tuple(sorted(set(affected_fields)))
    identity = {
        "rule_id": rule_id,
        "severity": severity.value,
        "clinical_topic": clinical_topic,
        "affected_fields": [_json_ready(asdict(item)) for item in unique_fields],
    }
    findings.append(
        SemanticFindingGroup(
            finding_group_id=f"semfg_{_sha256(identity)[:24]}",
            rule_id=rule_id,
            severity=severity,
            clinical_topic=clinical_topic,
            title_zh=title_zh,
            summary_zh=summary_zh,
            affected_fields=unique_fields,
            affected_capability_ids=(),
        )
    )


def _normalize_finding_capability_scope(
    finding: SemanticFindingGroup,
) -> SemanticFindingGroup:
    if finding.severity != SemanticFindingSeverity.CAPABILITY_BLOCKER:
        return finding
    impacts = _CAPABILITY_RULE_IMPACTS.get(finding.rule_id, ())
    registered = {item.capability_id for item in CAPABILITY_MANIFEST_V1}
    affected = tuple(sorted({item[0] for item in impacts}))
    if not affected or any(item not in registered for item in affected):
        return replace(
            finding,
            severity=SemanticFindingSeverity.GLOBAL_BLOCKER,
            affected_capability_ids=(),
            summary_zh=(
                finding.summary_zh
                + " 该局部问题未能闭合映射到已登记能力，已失败关闭为全局阻断。"
            ),
        )
    return replace(finding, affected_capability_ids=affected)


def _build_capability_states(
    findings: tuple[SemanticFindingGroup, ...],
) -> tuple[MappingCapabilityState, ...]:
    states: dict[str, MappingCapabilityStateCode] = {
        item.capability_id: MappingCapabilityStateCode.READY
        for item in CAPABILITY_MANIFEST_V1
    }
    finding_ids: dict[str, set[str]] = {
        item.capability_id: set() for item in CAPABILITY_MANIFEST_V1
    }
    limitations: dict[str, set[str]] = {
        item.capability_id: set() for item in CAPABILITY_MANIFEST_V1
    }
    rank = {
        MappingCapabilityStateCode.READY: 0,
        MappingCapabilityStateCode.LIMITED: 1,
        MappingCapabilityStateCode.BLOCKED_BY_QUALITY: 2,
        MappingCapabilityStateCode.DISABLED_BY_DESIGN: 3,
    }
    for finding in findings:
        if finding.severity != SemanticFindingSeverity.CAPABILITY_BLOCKER:
            continue
        for capability_id, target_state, limitation_code in (
            _CAPABILITY_RULE_IMPACTS.get(finding.rule_id, ())
        ):
            if rank[target_state] > rank[states[capability_id]]:
                states[capability_id] = target_state
            finding_ids[capability_id].add(finding.finding_group_id)
            limitations[capability_id].add(limitation_code)
    return tuple(
        MappingCapabilityState(
            capability_id=capability.capability_id,
            state=states[capability.capability_id],
            blocking_finding_group_ids=tuple(
                sorted(finding_ids[capability.capability_id])
            ),
            limitation_codes=tuple(
                sorted(limitations[capability.capability_id])
            ),
        )
        for capability in CAPABILITY_MANIFEST_V1
    )


def _read(value: Any, key: str, default: Any) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _mapping_or_none(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _lineage_text(lineage: Mapping[str, Any] | None, key: str) -> str:
    return str(lineage.get(key, "")).strip() if lineage is not None else ""


def _normalize_token(value: str) -> str:
    normalized = re.sub(r"[\s_:/\\-]+", ".", value.strip().casefold())
    return re.sub(r"\.+", ".", normalized).strip(".")


def _field_payload(field: _NormalizedField) -> dict[str, Any]:
    return {
        "domain": field.domain,
        "source_field": field.source_field,
        "raw_role": field.raw_role,
        "role_concept_id": field.role_concept_id,
        "role_family": field.role_family,
        "value_semantics": field.value_semantics,
        "field_kind": field.field_kind,
        "related_fields": list(field.related_fields),
        "standards_reference": field.standards_reference,
        "derivation_lineage": field.derivation_lineage,
        "coding_lineage": field.coding_lineage,
        "value_constraints": field.value_constraints,
        "object_identity": field.object_identity,
        "object_identity_evidence_fields": list(
            field.object_identity_evidence_fields
        ),
        "object_identity_binding_id": field.object_identity_binding_id,
        "validated_treatment_identity_binding": (
            field.validated_treatment_identity_binding
        ),
        "dose_semantics": field.dose_semantics,
        "quality_gate_actions": list(field.quality_gate_actions),
    }


def _sha256(value: Any) -> str:
    return sha256(
        json.dumps(
            _json_ready(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _json_ready(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_ready(item) for item in value]
    return value


def _severity_rank(severity: SemanticFindingSeverity) -> int:
    return {
        SemanticFindingSeverity.GLOBAL_BLOCKER: 0,
        SemanticFindingSeverity.CAPABILITY_BLOCKER: 1,
        SemanticFindingSeverity.REVIEW_WARNING: 2,
        SemanticFindingSeverity.AUTO_RESOLVED: 3,
    }[severity]
