from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from hashlib import sha256
import json
import re
from typing import Any, Mapping

from .monitoring_batch_repository import (
    DiffReadyBatch,
    FrozenBatchMappingContract,
    NormalizedRow,
)
from .monitoring_batch_rule_runner import MonitoringBatchRuleRunner
from .monitoring_protocol_rule_repository import (
    MonitoringProtocolRuleRepository,
    ProtocolApplicabilityConflictError,
    ProtocolApplicabilityUnresolvedError,
    RulePackLifecycleError,
)


_COMPATIBILITY_CENTRE_FIELDS = (
    "SITEID",
    "SITE_ID",
    "CENTREID",
    "CENTRE_ID",
    "CENTERID",
    "CENTER_ID",
    "中心编号",
    "试验中心编号",
)
_COMPATIBILITY_SUBJECT_FIELDS = (
    "USUBJID",
    "SUBJID",
    "SUBJECT_ID",
    "SUBJECTID",
    "__SUBJECTKEY",
    "受试者编号",
)
_COMPATIBILITY_EVENT_DATE_FIELDS_BY_DOMAIN = {
    "AE": ("AESTDTC", "AESTDAT"),
    "CM": ("CMSTDTC", "CMSTDAT"),
    "DA": ("DADTC", "DADAT"),
    "DS": ("DSSTDTC", "DSDTC", "DSDAT"),
    "DV": ("DVSTDTC", "DVDTC", "DVDAT"),
    "EC": ("ECSTDTC", "ECDAT"),
    "EG": ("EGDTC", "EGDAT"),
    "EX": ("EXSTDTC", "EXDAT"),
    "FA": ("FADTC", "FADAT"),
    "IE": ("IEDTC", "IEDAT"),
    "LB": ("LBDTC", "LBDAT"),
    "MH": ("MHSTDTC", "MHSTDAT"),
    "PC": ("PCDTC", "PCDAT"),
    "PE": ("PEDTC", "PEDAT"),
    "PP": ("PPDTC", "PPDAT"),
    "PR": ("PRSTDTC", "PRDAT"),
    "QS": ("QSDTC", "QSDAT"),
    "RS": ("RSDTC", "RSDAT"),
    "SC": ("SCDTC", "SCDAT"),
    "SV": ("SVSTDTC", "SVSTDAT", "VISDAT"),
    "TR": ("TRDTC", "TRDAT"),
    "TU": ("TUDTC", "TUDAT"),
    "VS": ("VSDTC", "VSDAT"),
}

_CENTRE_ROLE_ALIASES = frozenset(
    {
        "site_identifier",
        "site_id",
        "centre_identifier",
        "centre_id",
        "center_identifier",
        "center_id",
        "study_site_identifier",
        "study_centre_identifier",
        "study_center_identifier",
        "investigational_site_identifier",
    }
)
_SUBJECT_ROLE_ALIASES = frozenset(
    {
        "subject_identifier",
        "subject_id",
        "unique_subject_identifier",
        "unique_subject_id",
        "study_subject_identifier",
        "patient_identifier",
        "patient_id",
        "participant_identifier",
        "participant_id",
    }
)
_COMMON_EVENT_DATE_ROLE_ALIASES = frozenset(
    {
        "event_date",
        "record_event_date",
        "observation_date",
    }
)
_EVENT_DATE_ROLE_ALIASES_BY_DOMAIN = {
    "AE": frozenset({"adverse_event_start_date", "ae_start_date", "ae_date"}),
    "CM": frozenset(
        {
            "concomitant_medication_start_date",
            "conmed_start_date",
            "cm_start_date",
        }
    ),
    "DA": frozenset(
        {
            "drug_accountability_date",
            "accountability_date",
            "drug_dispensing_date",
            "drug_return_date",
        }
    ),
    "DS": frozenset({"disposition_date", "subject_disposition_date"}),
    "DV": frozenset({"protocol_deviation_date", "deviation_date", "dv_date"}),
    "EC": frozenset(
        {
            "actual_dose_date",
            "dose_date",
            "administration_date",
            "exposure_as_collected_date",
        }
    ),
    "EG": frozenset({"ecg_date", "electrocardiogram_date", "assessment_date"}),
    "EX": frozenset(
        {
            "actual_dose_date",
            "dose_date",
            "administration_date",
            "exposure_date",
            "exposure_start_date",
            "investigational_product_administration_date",
            "ip_administration_date",
            "ex_date",
        }
    ),
    "FA": frozenset({"finding_about_date", "assessment_date"}),
    "IE": frozenset(
        {"eligibility_assessment_date", "eligibility_date", "assessment_date"}
    ),
    "LB": frozenset(
        {
            "laboratory_collection_date",
            "lab_collection_date",
            "laboratory_result_date",
            "lab_result_date",
            "specimen_collection_date",
            "assessment_date",
        }
    ),
    "MH": frozenset(
        {
            "medical_history_start_date",
            "medical_history_date",
            "mh_start_date",
            "mh_date",
            "history_start_date",
        }
    ),
    "PC": frozenset(
        {"pharmacokinetic_collection_date", "specimen_collection_date"}
    ),
    "PE": frozenset({"physical_examination_date", "assessment_date"}),
    "PP": frozenset(
        {"pharmacodynamic_collection_date", "specimen_collection_date"}
    ),
    "PR": frozenset({"procedure_start_date", "procedure_date"}),
    "QS": frozenset({"questionnaire_date", "assessment_date"}),
    "RS": frozenset({"response_assessment_date", "assessment_date"}),
    "SC": frozenset({"subject_characteristic_date", "assessment_date"}),
    "SV": frozenset(
        {
            "actual_visit_date",
            "visit_date",
            "visit_start_date",
            "visit_assessment_date",
        }
    ),
    "TR": frozenset({"tumor_response_date", "assessment_date"}),
    "TU": frozenset({"tumor_identification_date", "assessment_date"}),
    "VS": frozenset({"vital_signs_date", "assessment_date"}),
}
_EXCLUDED_EVENT_DATE_ROLES = frozenset(
    {
        "birth_date",
        "date_of_birth",
        "subject_birth_date",
        "source_modified_at",
        "source_modification_date",
        "source_last_modified_date",
        "source_last_modified_datetime",
        "page_last_modified_date",
        "page_last_modified_datetime",
        "record_modified_at",
        "record_modification_date",
    }
)
_EXCLUDED_EVENT_DATE_FIELDS = frozenset(
    {
        "PAGELMDT",
        "PAGELMODDT",
        "PAGELASTMODIFIEDDATE",
        "SOURCEMODIFIEDAT",
        "SOURCEMODIFICATIONDATE",
        "SOURCELASTMODIFIEDDATE",
        "LASTMODIFIEDDATE",
        "LASTMODIFIEDDATETIME",
        "RECORDMODIFIEDAT",
        "RECORDMODIFICATIONDATE",
        "MODIFIEDDATE",
        "MODIFICATIONDATE",
        "UPDATEDAT",
        "LASTUPDATED",
        "BRTHDTC",
        "BIRTHDATE",
        "DATEOFBIRTH",
        "DOB",
        "出生日期",
        "出生年月日",
        "来源修改时间",
        "页面最后修改时间",
        "记录修改时间",
        "数据修改时间",
        "最后修改时间",
    }
)


def _canonical_sha256(value: Any) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = sha256()
    for part in parts:
        digest.update(str(part).encode("utf-8"))
        digest.update(b"\0")
    return f"{prefix}_{digest.hexdigest()[:24]}"


class RecordRuleAggregateIdentityError(ValueError):
    """Fail-closed error for project-level record-rule identity resolution."""

    def __init__(self, code: str, message: str):
        self.code = str(code).strip() or "monitoring_rule_pack_identity_unverifiable"
        self.message = str(message).strip() or self.code
        super().__init__(self.message)


_AGGREGATE_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def _aggregate_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or _AGGREGATE_SHA256_RE.fullmatch(value) is None:
        raise RecordRuleAggregateIdentityError(
            "monitoring_rule_pack_identity_unverifiable",
            f"规则聚合身份字段 {field} 不是规范的小写 SHA-256。",
        )
    return value


@dataclass(frozen=True)
class RecordRuleAggregateIdentity:
    """Deterministic project-level identity of the record-applicability rule space.

    identity_sha256 is the SHA-256 over the canonical JSON of every component
    except identity_sha256 itself.
    """

    project_id: str
    applicability_dimensions: tuple[str, ...]
    protocol_version_ids: tuple[str, ...]
    assignments: tuple[tuple[str, ...], ...]
    packs: tuple[tuple[str, ...], ...]
    rule_revision_ids: tuple[str, ...]
    mapping_revision: str
    mapping_content_sha256: str
    capability_manifest_sha256: str
    effective_capabilities_sha256: str
    identity_sha256: str

    def identity_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("identity_sha256", None)
        return value

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MonitoringRecordRuleBinding:
    current_business_key: str
    current_domain: str
    centre_id: str
    subject_id: str
    event_date: str
    centre_source_fields: tuple[str, ...]
    subject_source_fields: tuple[str, ...]
    event_date_source_fields: tuple[str, ...]
    compatibility_fallback_roles: tuple[str, ...]
    assignment_id: str
    assignment_state_version: int
    protocol_version_id: str
    rule_pack_id: str
    rule_pack_revision: int
    rule_pack_content_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MonitoringRecordResolutionDiagnostic:
    diagnostic_id: str
    code: str
    message: str
    batch_id: str
    current_business_key: str
    current_domain: str
    centre_id: str = ""
    subject_id: str = ""
    event_date: str = ""
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["details"] = dict(self.details or {})
        return value


@dataclass(frozen=True)
class MonitoringRecordRuleResolutionPlan:
    project_id: str
    batch_id: str
    field_mapping_identity: dict[str, Any]
    bindings: tuple[MonitoringRecordRuleBinding, ...]
    diagnostics: tuple[MonitoringRecordResolutionDiagnostic, ...]
    resolution_sha256: str
    mapping_contract: FrozenBatchMappingContract

    @property
    def complete(self) -> bool:
        return not self.diagnostics

    def identity_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "batch_id": self.batch_id,
            "field_mapping_identity": dict(self.field_mapping_identity),
            "bindings": [item.to_dict() for item in self.bindings],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


class MonitoringRecordRuleResolver:
    """Resolve immutable protocol/rule identities for every listing record."""

    def __init__(self, repository: MonitoringProtocolRuleRepository):
        self.repository = repository

    def project_supports_record_resolution(self, project_id: str) -> bool:
        for pack in self.repository.list_rule_packs(project_id):
            if (
                pack.status != "published"
                or pack.applicability_status != "site_specific"
            ):
                continue
            version = self.repository.protocol_version(pack.protocol_version_id)
            if (
                version.status == "confirmed"
                and version.applicability_status == "site_specific"
            ):
                return True
        return False

    def aggregate_identity(self, project_id: str) -> RecordRuleAggregateIdentity:
        """Fail-closed deterministic identity of the project's record-rule space.

        Aggregation rule: the aggregate covers exactly the resolution space that
        per-record resolution consults — every applicability assignment of the
        project whose state is ``confirmed`` and whose bound protocol version is
        ``confirmed`` with ``site_specific`` applicability (the same filters as
        the per-record SQL in ``resolve_protocol_applicability``). For each
        distinct bound protocol version, the pack is resolved through
        ``published_pack_for_protocol_version`` — the same lookup per-record
        resolution uses — and the rule set is the union of the rules of those
        packs. No parallel query is built.

        Raises RecordRuleAggregateIdentityError with code
        ``monitoring_rule_pack_required`` when no applicable assignment or no
        selected published pack exists, and with code
        ``monitoring_rule_pack_identity_unverifiable`` when a selected pack is
        unpublished/cross-project/conflicted, when any included rule carries
        empty or partial mapping identity (legacy candidate path), or when the
        included rules carry mixed mapping/capability identities. Comparison
        against the project's active mapping activation is performed by the
        daily-run service, which owns that source of truth.
        """
        project = str(project_id or "").strip()
        if not project:
            raise RecordRuleAggregateIdentityError(
                "monitoring_rule_pack_required",
                "project_id is required for record rule aggregate identity",
            )
        selected_assignments = []
        version_cache: dict[str, Any] = {}
        for assignment in self.repository.list_applicability_assignments(project):
            if str(assignment.status).strip() != "confirmed":
                continue
            version_id = str(assignment.protocol_version_id).strip()
            version = version_cache.get(version_id)
            if version is None:
                version = self.repository.protocol_version(version_id)
                version_cache[version_id] = version
            if (
                str(version.status).strip() == "confirmed"
                and str(version.applicability_status).strip() == "site_specific"
            ):
                selected_assignments.append(assignment)
        if not selected_assignments:
            raise RecordRuleAggregateIdentityError(
                "monitoring_rule_pack_required",
                "当前项目没有已确认的逐记录方案适用性指派，无法确定规则身份。",
            )

        packs: dict[str, Any] = {}
        rules_by_pack: dict[str, tuple[Any, ...]] = {}
        for version_id in sorted(
            {
                str(assignment.protocol_version_id).strip()
                for assignment in selected_assignments
            }
        ):
            try:
                pack, rules = self.repository.published_pack_for_protocol_version(
                    project,
                    version_id,
                )
            except ProtocolApplicabilityUnresolvedError as exc:
                raise RecordRuleAggregateIdentityError(
                    "monitoring_rule_pack_required",
                    f"已确认的适用性指派缺少已发布规则包：{exc}",
                ) from exc
            except (
                ProtocolApplicabilityConflictError,
                RulePackLifecycleError,
            ) as exc:
                raise RecordRuleAggregateIdentityError(
                    "monitoring_rule_pack_identity_unverifiable",
                    f"已确认的适用性指派绑定的规则包不可审计：{exc}",
                ) from exc
            if (
                str(pack.status).strip() != "published"
                or str(pack.project_id).strip() != project
            ):
                raise RecordRuleAggregateIdentityError(
                    "monitoring_rule_pack_identity_unverifiable",
                    "解析得到的规则包未发布或不属于当前项目。",
                )
            packs[pack.rule_pack_id] = pack
            rules_by_pack[pack.rule_pack_id] = tuple(rules)

        identity_values: set[tuple[str, str, str, str]] = set()
        rule_revision_ids: set[str] = set()
        for rule_pack_id in sorted(rules_by_pack):
            for rule in rules_by_pack[rule_pack_id]:
                if str(rule.project_id).strip() != project:
                    raise RecordRuleAggregateIdentityError(
                        "monitoring_rule_pack_identity_unverifiable",
                        "已发布规则包含其他项目的规则修订。",
                    )
                mapping_revision = str(rule.mapping_revision or "").strip()
                mapping_content_sha256 = _aggregate_sha256(
                    rule.mapping_content_sha256,
                    "mapping_content_sha256",
                )
                capability_manifest_sha256 = _aggregate_sha256(
                    rule.capability_manifest_sha256,
                    "capability_manifest_sha256",
                )
                effective_capabilities_sha256 = _aggregate_sha256(
                    rule.effective_capabilities_sha256,
                    "effective_capabilities_sha256",
                )
                if not mapping_revision:
                    raise RecordRuleAggregateIdentityError(
                        "monitoring_rule_pack_identity_unverifiable",
                        "已发布规则缺少可追溯的字段映射身份（legacy/partial），"
                        "请通过规则建议链重新确认并发布规则包。",
                    )
                identity_values.add(
                    (
                        mapping_revision,
                        mapping_content_sha256,
                        capability_manifest_sha256,
                        effective_capabilities_sha256,
                    )
                )
                rule_revision_ids.add(str(rule.rule_revision_id))
        if not rule_revision_ids:
            raise RecordRuleAggregateIdentityError(
                "monitoring_rule_pack_identity_unverifiable",
                "已确认的适用性空间没有可用的已发布规则。",
            )
        if len(identity_values) > 1:
            raise RecordRuleAggregateIdentityError(
                "monitoring_rule_pack_identity_unverifiable",
                "已发布规则的字段映射身份不一致（mixed mapping identity），"
                "请按最新映射重新确认规则并发布规则包。",
            )
        (
            mapping_revision,
            mapping_content_sha256,
            capability_manifest_sha256,
            effective_capabilities_sha256,
        ) = next(iter(identity_values))

        components = {
            "project_id": project,
            "applicability_dimensions": ["centre_id", "subject_id", "event_date"],
            "protocol_version_ids": sorted(
                {
                    str(assignment.protocol_version_id).strip()
                    for assignment in selected_assignments
                }
            ),
            "assignments": [
                [
                    str(assignment.assignment_id),
                    str(assignment.protocol_version_id),
                    str(assignment.centre_id),
                    str(assignment.subject_id or ""),
                    str(assignment.operational_effective_from),
                    str(assignment.operational_effective_to),
                    str(int(assignment.state_version)),
                    str(assignment.status),
                ]
                for assignment in sorted(
                    selected_assignments,
                    key=lambda item: str(item.assignment_id),
                )
            ],
            "packs": [
                [
                    str(pack.rule_pack_id),
                    _aggregate_sha256(
                        pack.content_sha256,
                        "rule_pack_content_sha256",
                    ),
                    str(int(pack.pack_revision)),
                    str(pack.status),
                ]
                for pack in (packs[key] for key in sorted(packs))
            ],
            "rule_revision_ids": sorted(rule_revision_ids),
            "mapping_revision": mapping_revision,
            "mapping_content_sha256": mapping_content_sha256,
            "capability_manifest_sha256": capability_manifest_sha256,
            "effective_capabilities_sha256": effective_capabilities_sha256,
        }
        return RecordRuleAggregateIdentity(
            project_id=project,
            applicability_dimensions=("centre_id", "subject_id", "event_date"),
            protocol_version_ids=tuple(
                str(value) for value in components["protocol_version_ids"]
            ),
            assignments=tuple(
                tuple(value) for value in components["assignments"]
            ),
            packs=tuple(tuple(value) for value in components["packs"]),
            rule_revision_ids=tuple(
                str(value) for value in components["rule_revision_ids"]
            ),
            mapping_revision=mapping_revision,
            mapping_content_sha256=mapping_content_sha256,
            capability_manifest_sha256=capability_manifest_sha256,
            effective_capabilities_sha256=effective_capabilities_sha256,
            identity_sha256=_canonical_sha256(components),
        )

    def resolve_batch(
        self,
        batch: DiffReadyBatch,
        mapping_contract: FrozenBatchMappingContract,
    ) -> MonitoringRecordRuleResolutionPlan:
        _validate_mapping_contract(batch, mapping_contract)
        pack_cache: dict[str, Any] = {}
        bindings: list[MonitoringRecordRuleBinding] = []
        diagnostics: list[MonitoringRecordResolutionDiagnostic] = []
        for row in sorted(batch.rows, key=lambda item: item.business_key):
            centre = _identifier_anchor(
                row,
                mapping_contract,
                anchor_role="centre",
            )
            subject = _identifier_anchor(
                row,
                mapping_contract,
                anchor_role="subject",
                value_required=False,
            )
            event = _event_date_anchor(row, mapping_contract)
            input_error = centre.error or subject.error or event.error
            if input_error:
                diagnostics.append(
                    _diagnostic(
                        batch,
                        row,
                        code=input_error[0],
                        message=input_error[1],
                        centre_id=centre.value,
                        subject_id=subject.value,
                        event_date=event.value,
                        details={
                            "centre_source_fields": list(centre.source_fields),
                            "subject_source_fields": list(subject.source_fields),
                            "event_date_source_fields": list(event.source_fields),
                            "compatibility_fallback_roles": sorted(
                                {
                                    role
                                    for role, anchor in (
                                        ("centre", centre),
                                        ("subject", subject),
                                        ("event_date", event),
                                    )
                                    if anchor.compatibility_fallback
                                }
                            ),
                        },
                    )
                )
                continue

            applicability = self.repository.resolve_protocol_applicability(
                batch.project_id,
                centre_id=centre.value,
                subject_id=subject.value,
                event_date=event.value,
            )
            if (
                not applicability.resolved
                or applicability.assignment is None
                or not applicability.protocol_version_id
            ):
                diagnostics.append(
                    _diagnostic(
                        batch,
                        row,
                        code=applicability.diagnostic_code,
                        message=applicability.diagnostic_message,
                        centre_id=centre.value,
                        subject_id=subject.value,
                        event_date=event.value,
                    )
                )
                continue

            try:
                cached = pack_cache.get(applicability.protocol_version_id)
                if cached is None:
                    cached = self.repository.published_pack_for_protocol_version(
                        batch.project_id,
                        applicability.protocol_version_id,
                    )
                    pack_cache[applicability.protocol_version_id] = cached
                pack, _rules = cached
            except ProtocolApplicabilityUnresolvedError as exc:
                diagnostics.append(
                    _diagnostic(
                        batch,
                        row,
                        code="monitoring_record_rule_pack_unresolved",
                        message=str(exc),
                        centre_id=centre.value,
                        subject_id=subject.value,
                        event_date=event.value,
                        details={
                            "protocol_version_id": applicability.protocol_version_id
                        },
                    )
                )
                continue
            except ProtocolApplicabilityConflictError as exc:
                diagnostics.append(
                    _diagnostic(
                        batch,
                        row,
                        code="monitoring_record_rule_pack_conflict",
                        message=str(exc),
                        centre_id=centre.value,
                        subject_id=subject.value,
                        event_date=event.value,
                        details={
                            "protocol_version_id": applicability.protocol_version_id
                        },
                    )
                )
                continue
            except RulePackLifecycleError as exc:
                diagnostics.append(
                    _diagnostic(
                        batch,
                        row,
                        code="monitoring_record_rule_pack_invalid",
                        message=str(exc),
                        centre_id=centre.value,
                        subject_id=subject.value,
                        event_date=event.value,
                        details={
                            "protocol_version_id": applicability.protocol_version_id
                        },
                    )
                )
                continue

            assignment = applicability.assignment
            bindings.append(
                MonitoringRecordRuleBinding(
                    current_business_key=row.business_key,
                    current_domain=row.domain.upper(),
                    centre_id=centre.value,
                    subject_id=subject.value,
                    event_date=event.value,
                    centre_source_fields=centre.source_fields,
                    subject_source_fields=subject.source_fields,
                    event_date_source_fields=event.source_fields,
                    compatibility_fallback_roles=tuple(
                        role
                        for role, anchor in (
                            ("centre", centre),
                            ("subject", subject),
                            ("event_date", event),
                        )
                        if anchor.compatibility_fallback
                    ),
                    assignment_id=assignment.assignment_id,
                    assignment_state_version=assignment.state_version,
                    protocol_version_id=applicability.protocol_version_id,
                    rule_pack_id=pack.rule_pack_id,
                    rule_pack_revision=pack.pack_revision,
                    rule_pack_content_sha256=pack.content_sha256,
                )
            )

        mapping_identity = mapping_contract.identity_dict()
        identity = {
            "project_id": batch.project_id,
            "batch_id": batch.batch_id,
            "field_mapping_identity": mapping_identity,
            "bindings": [item.to_dict() for item in bindings],
            "diagnostics": [item.to_dict() for item in diagnostics],
        }
        return MonitoringRecordRuleResolutionPlan(
            project_id=batch.project_id,
            batch_id=batch.batch_id,
            field_mapping_identity=mapping_identity,
            bindings=tuple(bindings),
            diagnostics=tuple(diagnostics),
            resolution_sha256=_canonical_sha256(identity),
            mapping_contract=mapping_contract,
        )

    def run_resolved(
        self,
        batch: DiffReadyBatch,
        plan: MonitoringRecordRuleResolutionPlan,
        runner: MonitoringBatchRuleRunner,
        *,
        capability_states: Any = None,
    ) -> dict[str, Any]:
        if plan.project_id != batch.project_id or plan.batch_id != batch.batch_id:
            raise ValueError("record rule resolution plan does not match batch")
        _validate_mapping_contract(batch, plan.mapping_contract)
        row_by_key = {row.business_key: row for row in batch.rows}
        subject_rows = _rows_by_subject(batch.rows, plan.mapping_contract)
        candidates: list[dict[str, Any]] = []
        diagnostics = [item.to_dict() for item in plan.diagnostics]
        evaluated_records: set[str] = set()
        rule_revision_ids: set[str] = set()
        runnable_by_pack: dict[str, list[MonitoringRecordRuleBinding]] = {}

        for binding in plan.bindings:
            anchor = row_by_key.get(binding.current_business_key)
            if anchor is None:
                diagnostics.append(
                    _runtime_diagnostic(
                        batch,
                        binding,
                        code="monitoring_record_anchor_missing",
                        message="resolved record anchor is absent from the frozen batch",
                    )
                )
                continue
            context_rows = (
                subject_rows.get(binding.subject_id, ())
                if binding.subject_id
                else ()
            )
            if not context_rows:
                diagnostics.append(
                    _runtime_diagnostic(
                        batch,
                        binding,
                        code="monitoring_record_subject_context_unresolved",
                        message=(
                            "record has no deterministic subject context; rule execution "
                            "is closed for this anchor"
                        ),
                    )
                )
                continue
            conflicting_centres = sorted(
                {
                    centre.value
                    for row in context_rows
                    for centre in (
                        _identifier_anchor(
                            row,
                            plan.mapping_contract,
                            anchor_role="centre",
                        ),
                    )
                    if (
                        centre.error is None
                        and centre.value
                        and centre.value != binding.centre_id
                    )
                }
            )
            if conflicting_centres:
                diagnostics.append(
                    _runtime_diagnostic(
                        batch,
                        binding,
                        code="monitoring_record_subject_context_conflict",
                        message=(
                            "the exact subject identifier appears under multiple centres; "
                            "related-record context is ambiguous"
                        ),
                        details={"conflicting_centre_ids": conflicting_centres},
                    )
                )
                continue
            runnable_by_pack.setdefault(binding.rule_pack_id, []).append(binding)

        for rule_pack_id, pack_bindings in sorted(runnable_by_pack.items()):
            anchor_bindings = {
                (binding.current_business_key, binding.current_domain): binding
                for binding in pack_bindings
            }
            context_by_key = {
                row.business_key: row
                for binding in pack_bindings
                for row in subject_rows[binding.subject_id]
            }
            scoped_batch = DiffReadyBatch(
                batch_id=batch.batch_id,
                project_id=batch.project_id,
                state=batch.state,
                version=batch.version,
                expected_domains=batch.expected_domains,
                mapping_revision=batch.mapping_revision,
                source_bindings=batch.source_bindings,
                source_hashes=batch.source_hashes,
                rows=tuple(
                    context_by_key[key] for key in sorted(context_by_key)
                ),
                schema_fields=batch.schema_fields,
            )
            result = runner.run(
                scoped_batch,
                rule_pack_id=rule_pack_id,
                capability_states=capability_states,
            )
            rule_revision_ids.update(result.rule_revision_ids)
            for candidate in result.candidates:
                binding = anchor_bindings.get(
                    (
                        candidate.current_business_key,
                        candidate.current_domain.upper(),
                    )
                )
                if binding is None:
                    continue
                value = candidate.to_dict()
                value["protocol_resolution"] = binding.to_dict()
                candidates.append(value)
                evaluated_records.add(binding.current_business_key)
            global_diagnostic_ids: set[str] = set()
            for diagnostic in result.diagnostics:
                binding = anchor_bindings.get(
                    (
                        diagnostic.current_business_key,
                        diagnostic.current_domain.upper(),
                    )
                )
                is_global = not diagnostic.current_business_key
                if binding is None and not is_global:
                    continue
                value = diagnostic.to_dict()
                if is_global:
                    global_key = _stable_id(
                        "monglobaldiag",
                        rule_pack_id,
                        diagnostic.rule_revision_id,
                        diagnostic.code,
                        diagnostic.message,
                    )
                    if global_key in global_diagnostic_ids:
                        continue
                    global_diagnostic_ids.add(global_key)
                if binding is not None:
                    value["details"] = {
                        **dict(value.get("details") or {}),
                        "protocol_resolution": binding.to_dict(),
                    }
                diagnostics.append(value)
            evaluated_records.update(
                binding.current_business_key for binding in pack_bindings
            )

        binding_payload = [item.to_dict() for item in plan.bindings]
        resolution_diagnostic_payload = [
            item.to_dict() for item in plan.diagnostics
        ]
        pack_ids = sorted({item.rule_pack_id for item in plan.bindings})
        output = {
            "run_id": _stable_id(
                "monrecordrun",
                batch.project_id,
                batch.batch_id,
                batch.version,
                batch.mapping_revision,
                plan.resolution_sha256,
            ),
            "project_id": batch.project_id,
            "batch_id": batch.batch_id,
            "batch_version": batch.version,
            "mapping_revision": batch.mapping_revision,
            "resolution_mode": "record_applicability",
            "resolution_sha256": plan.resolution_sha256,
            "field_mapping_identity": dict(plan.field_mapping_identity),
            "rule_pack_id": pack_ids[0] if len(pack_ids) == 1 else "",
            "rule_pack_ids": pack_ids,
            "rule_revision_ids": sorted(rule_revision_ids),
            "record_rule_resolutions": binding_payload,
            "record_resolution_diagnostics": resolution_diagnostic_payload,
            "resolved_record_count": len(plan.bindings),
            "failed_resolution_count": len(plan.diagnostics),
            "evaluated_record_count": len(evaluated_records),
            "analysis_complete": not plan.diagnostics
            and not any(
                str(item.get("code") or "").startswith(
                    ("monitoring_record_", "monitoring_capability_")
                )
                for item in diagnostics
            ),
            "candidates": sorted(
                candidates,
                key=lambda item: (
                    str(item.get("rule_key") or ""),
                    str(item.get("subject_id") or ""),
                    str(item.get("current_business_key") or ""),
                    str(item.get("candidate_id") or ""),
                ),
            ),
            "diagnostics": sorted(
                diagnostics,
                key=lambda item: (
                    str(item.get("current_business_key") or ""),
                    str(item.get("code") or ""),
                    str(item.get("diagnostic_id") or ""),
                ),
            ),
        }
        output["output_sha256"] = _canonical_sha256(output)
        return output


@dataclass(frozen=True)
class _AnchorValue:
    value: str
    source_fields: tuple[str, ...]
    compatibility_fallback: bool
    error: tuple[str, str] | None = None


def _validate_mapping_contract(
    batch: DiffReadyBatch,
    contract: FrozenBatchMappingContract,
) -> None:
    if contract.schema_version not in {
        "monitoring_project_mapping_v1",
        "monitoring_project_mapping_v2",
    }:
        raise ValueError("unsupported frozen field-mapping schema")
    if (
        contract.batch_id != batch.batch_id
        or contract.project_id != batch.project_id
        or contract.batch_version != batch.version
        or contract.mapping_revision != str(batch.mapping_revision or "")
    ):
        raise ValueError("frozen field-mapping identity does not match batch")


def _normalized_role(value: Any) -> str:
    return re.sub(r"[\s./-]+", "_", str(value or "").strip().casefold()).strip(
        "_"
    )


def _normalized_source_field(value: Any) -> str:
    return re.sub(r"[\s_-]+", "", str(value or "").strip()).upper()


def _mapping_fields_for_domain(
    contract: FrozenBatchMappingContract,
    domain: str,
) -> tuple[Mapping[str, Any], ...]:
    normalized_domain = str(domain or "").strip().upper()
    return tuple(
        field
        for field in contract.fields
        if str(field.get("domain") or "").strip().upper() == normalized_domain
    )


def _row_field_values(
    data: Mapping[str, Any],
    source_fields: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    requested = {field.casefold(): field for field in source_fields}
    present_fields: list[str] = []
    values: list[tuple[str, str]] = []
    for raw_key, raw_value in data.items():
        key = str(raw_key).strip()
        configured = requested.get(key.casefold())
        if configured is None:
            continue
        if configured not in present_fields:
            present_fields.append(configured)
        value = str(raw_value or "").strip()
        if value:
            values.append((configured, value))
    return tuple(present_fields), tuple(values)


def _mapped_source_fields(
    row: NormalizedRow,
    contract: FrozenBatchMappingContract,
    *,
    anchor_role: str,
) -> tuple[tuple[str, ...], tuple[str, str] | None]:
    domain_fields = _mapping_fields_for_domain(contract, row.domain)
    if anchor_role == "centre":
        allowed_roles = _CENTRE_ROLE_ALIASES
    elif anchor_role == "subject":
        allowed_roles = _SUBJECT_ROLE_ALIASES
    elif anchor_role == "event_date":
        allowed_roles = (
            _COMMON_EVENT_DATE_ROLE_ALIASES
            | _EVENT_DATE_ROLE_ALIASES_BY_DOMAIN.get(
                row.domain.upper(),
                frozenset(),
            )
        )
    else:
        raise ValueError(f"unsupported anchor role: {anchor_role}")

    source_fields: list[str] = []
    for field in domain_fields:
        role = _normalized_role(field.get("recommended_role"))
        if role not in allowed_roles:
            continue
        source_field = str(field.get("source_field") or "").strip()
        if anchor_role == "event_date" and (
            role in _EXCLUDED_EVENT_DATE_ROLES
            or _normalized_source_field(source_field)
            in _EXCLUDED_EVENT_DATE_FIELDS
        ):
            return (), (
                "monitoring_record_event_date_mapping_excluded",
                "confirmed mapping points to a non-event administrative or birth date",
            )
        source_fields.append(source_field)
    return tuple(dict.fromkeys(source_fields)), None


def _compatibility_source_fields(
    row: NormalizedRow,
    contract: FrozenBatchMappingContract,
    *,
    anchor_role: str,
) -> tuple[str, ...]:
    if anchor_role == "centre":
        aliases = _COMPATIBILITY_CENTRE_FIELDS
    elif anchor_role == "subject":
        aliases = _COMPATIBILITY_SUBJECT_FIELDS
    elif anchor_role == "event_date":
        aliases = _COMPATIBILITY_EVENT_DATE_FIELDS_BY_DOMAIN.get(
            row.domain.upper(),
            (),
        )
    else:
        raise ValueError(f"unsupported anchor role: {anchor_role}")
    mapped_fields = {
        str(field.get("source_field") or "").strip().casefold()
        for field in _mapping_fields_for_domain(contract, row.domain)
    }
    row_fields = {str(key).strip().casefold() for key in row.data}
    return tuple(
        alias
        for alias in aliases
        if (
            alias.casefold() in row_fields
            and alias.casefold() not in mapped_fields
            and (
                anchor_role != "event_date"
                or _normalized_source_field(alias)
                not in _EXCLUDED_EVENT_DATE_FIELDS
            )
        )
    )


def _identifier_anchor(
    row: NormalizedRow,
    contract: FrozenBatchMappingContract,
    *,
    anchor_role: str,
    value_required: bool = True,
) -> _AnchorValue:
    source_fields, mapping_error = _mapped_source_fields(
        row,
        contract,
        anchor_role=anchor_role,
    )
    if mapping_error is not None:
        return _AnchorValue("", (), False, mapping_error)
    compatibility_fallback = False
    if not source_fields:
        source_fields = _compatibility_source_fields(
            row,
            contract,
            anchor_role=anchor_role,
        )
        compatibility_fallback = bool(source_fields)
    if not source_fields:
        return _AnchorValue(
            "",
            (),
            False,
            (
                f"monitoring_record_{anchor_role}_mapping_missing",
                f"confirmed mapping has no closed {anchor_role} anchor role",
            ),
        )

    present_fields, field_values = _row_field_values(row.data, source_fields)
    values = tuple(dict.fromkeys(value for _, value in field_values))
    if len(values) > 1:
        label = "centre" if anchor_role == "centre" else "subject"
        return _AnchorValue(
            "",
            present_fields or source_fields,
            compatibility_fallback,
            (
                f"monitoring_record_{label}_identifier_conflict",
                f"record contains conflicting mapped {label} identifiers",
            ),
        )
    if values:
        return _AnchorValue(
            values[0],
            present_fields or source_fields,
            compatibility_fallback,
        )
    if value_required:
        label = "centre" if anchor_role == "centre" else "subject"
        return _AnchorValue(
            "",
            present_fields or source_fields,
            compatibility_fallback,
            (
                f"monitoring_record_{label}_identifier_missing",
                f"record has no value for its mapped {label} identifier",
            ),
        )
    return _AnchorValue(
        "",
        present_fields or source_fields,
        compatibility_fallback,
    )


def _event_date_anchor(
    row: NormalizedRow,
    contract: FrozenBatchMappingContract,
) -> _AnchorValue:
    source_fields, mapping_error = _mapped_source_fields(
        row,
        contract,
        anchor_role="event_date",
    )
    if mapping_error is not None:
        return _AnchorValue("", (), False, mapping_error)
    compatibility_fallback = False
    if not source_fields:
        source_fields = _compatibility_source_fields(
            row,
            contract,
            anchor_role="event_date",
        )
        compatibility_fallback = bool(source_fields)
    if not source_fields:
        return _AnchorValue(
            "",
            (),
            False,
            (
                "monitoring_record_event_date_mapping_missing",
                "confirmed mapping has no closed event-date role and no audited compatibility field",
            ),
        )

    present_fields, field_values = _row_field_values(row.data, source_fields)
    values: list[str] = []
    invalid_fields: list[str] = []
    for source_field, raw_value in field_values:
        normalized = _iso_date(raw_value)
        if not normalized:
            invalid_fields.append(source_field)
        elif normalized not in values:
            values.append(normalized)
    if invalid_fields:
        return _AnchorValue(
            "",
            present_fields or source_fields,
            compatibility_fallback,
            (
                "monitoring_record_event_date_invalid",
                "record contains a non-ISO value in its mapped event-date field",
            ),
        )
    if len(values) > 1:
        return _AnchorValue(
            "",
            present_fields or source_fields,
            compatibility_fallback,
            (
                "monitoring_record_event_date_conflict",
                "record contains conflicting mapped event-date values",
            ),
        )
    if values:
        return _AnchorValue(
            values[0],
            present_fields or source_fields,
            compatibility_fallback,
        )
    return _AnchorValue(
        "",
        present_fields or source_fields,
        compatibility_fallback,
        (
            "monitoring_record_event_date_missing",
            "record has no mapped ISO event date; no operational-date fallback is permitted",
        ),
    )


def _iso_date(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            return ""


def _rows_by_subject(
    rows: tuple[NormalizedRow, ...],
    contract: FrozenBatchMappingContract,
) -> dict[str, tuple[NormalizedRow, ...]]:
    grouped: dict[str, list[NormalizedRow]] = {}
    for row in rows:
        subject = _identifier_anchor(
            row,
            contract,
            anchor_role="subject",
            value_required=False,
        )
        if subject.error is None and subject.value:
            grouped.setdefault(subject.value, []).append(row)
    return {
        subject: tuple(sorted(values, key=lambda item: item.business_key))
        for subject, values in grouped.items()
    }


def _diagnostic(
    batch: DiffReadyBatch,
    row: NormalizedRow,
    *,
    code: str,
    message: str,
    centre_id: str = "",
    subject_id: str = "",
    event_date: str = "",
    details: Mapping[str, Any] | None = None,
) -> MonitoringRecordResolutionDiagnostic:
    return MonitoringRecordResolutionDiagnostic(
        diagnostic_id=_stable_id(
            "monrecorddiag",
            batch.batch_id,
            row.business_key,
            code,
            message,
        ),
        code=code,
        message=message,
        batch_id=batch.batch_id,
        current_business_key=row.business_key,
        current_domain=row.domain.upper(),
        centre_id=centre_id,
        subject_id=subject_id,
        event_date=event_date,
        details=dict(details or {}),
    )


def _runtime_diagnostic(
    batch: DiffReadyBatch,
    binding: MonitoringRecordRuleBinding,
    *,
    code: str,
    message: str,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "diagnostic_id": _stable_id(
            "monrecorddiag",
            batch.batch_id,
            binding.current_business_key,
            code,
            message,
        ),
        "code": code,
        "message": message,
        "batch_id": batch.batch_id,
        "rule_pack_id": binding.rule_pack_id,
        "rule_key": "",
        "rule_revision_id": "",
        "subject_id": binding.subject_id,
        "current_domain": binding.current_domain,
        "current_business_key": binding.current_business_key,
        "details": {
            **dict(details or {}),
            "protocol_resolution": binding.to_dict(),
        },
    }
