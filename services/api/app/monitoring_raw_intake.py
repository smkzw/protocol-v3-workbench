from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
import re
from threading import Lock
from typing import Any, Dict, List, Optional, Sequence, Union

from .ai_gateway import AiTaskType, ai_gateway_status_from_env
from .listing_file_parser import parse_listing_file
from .protocol_text_extractor import parse_protocol_docx


PathLike = Union[str, Path]
RAW_MONITORING_SOURCE_SYSTEM = "source_registry/raw_monitoring_source"
SUBJECT_ID_FIELDS = ["SUBJID", "USUBJID", "受试者编号", "受试者筛选号", "受试者"]
SITE_ID_FIELDS = ["SITEID", "中心编号", "试验中心编号", "SITE"]
FORBIDDEN_MONITORING_INPUTS = [
    "subject-timeline-builder-output",
    "clinical-patient-profile-html-output",
    "legacy_timeline_html",
    "legacy_patient_profile_html",
    "manual_risk_summary",
]


@dataclass(frozen=True)
class MonitoringRawProjectConfig:
    project_id: str
    listing_path: PathLike
    protocol_path: PathLike
    project_label: str = ""
    supplemental_listing_paths: Sequence[PathLike] = ()
    allowed_roots: Sequence[PathLike] = ()


@dataclass(frozen=True)
class MonitoringProtocolSummary:
    filename: str
    title: str
    paragraph_count: int
    table_count: int
    span_count: int

    def public_dict(self) -> Dict[str, Any]:
        return {
            "filename": self.filename,
            "title": self.title,
            "paragraph_count": self.paragraph_count,
            "table_count": self.table_count,
            "span_count": self.span_count,
        }


@dataclass(frozen=True)
class MonitoringListingSummary:
    filename: str
    sheet_count: int
    row_count: int
    subject_count: int
    site_count: int
    subject_id_fields: List[str]
    site_id_fields: List[str]
    sheet_row_counts: Dict[str, int]
    supplemental_file_count: int

    def public_dict(self) -> Dict[str, Any]:
        return {
            "filename": self.filename,
            "sheet_count": self.sheet_count,
            "row_count": self.row_count,
            "subject_count": self.subject_count,
            "site_count": self.site_count,
            "subject_id_fields": list(self.subject_id_fields),
            "site_id_fields": list(self.site_id_fields),
            "sheet_row_counts": dict(self.sheet_row_counts),
            "supplemental_file_count": self.supplemental_file_count,
        }


@dataclass(frozen=True)
class MonitoringDomainGroup:
    group_key: str
    label: str
    sheet_names: List[str]
    source_domains: List[str]
    row_count: int
    subject_count: int

    def public_dict(self) -> Dict[str, Any]:
        return {
            "group_key": self.group_key,
            "label": self.label,
            "sheet_names": list(self.sheet_names),
            "source_domains": list(self.source_domains),
            "row_count": self.row_count,
            "subject_count": self.subject_count,
        }


@dataclass(frozen=True)
class MonitoringRawAiTaskPlanItem:
    task_type: str
    module: str
    prompt_version: str
    status: str
    input_source_scopes: List[str]
    forbidden_source_ids: List[str]

    def public_dict(self) -> Dict[str, Any]:
        return {
            "task_type": self.task_type,
            "module": self.module,
            "prompt_version": self.prompt_version,
            "status": self.status,
            "input_source_scopes": list(self.input_source_scopes),
            "forbidden_source_ids": list(self.forbidden_source_ids),
        }


@dataclass(frozen=True)
class MonitoringRawProjectSnapshot:
    project_id: str
    project_label: str
    source_system: str
    listing: MonitoringListingSummary
    protocol: MonitoringProtocolSummary
    domain_groups: Dict[str, MonitoringDomainGroup]
    unclassified_sheet_names: List[str]
    ai_task_plan: List[MonitoringRawAiTaskPlanItem]
    forbidden_legacy_inputs: List[str]
    ai_gateway_status: Dict[str, Any]

    def public_dict(self) -> Dict[str, Any]:
        configured = _strict_bool(
            self.ai_gateway_status.get("configured"),
            "ai_gateway_status.configured",
        )
        semantic_ai_tasks_enabled = _strict_bool(
            self.ai_gateway_status.get("semantic_ai_tasks_enabled"),
            "ai_gateway_status.semantic_ai_tasks_enabled",
        )
        codex_runtime_dependency = _strict_bool(
            self.ai_gateway_status.get("codex_runtime_dependency"),
            "ai_gateway_status.codex_runtime_dependency",
        )
        return {
            "project_id": self.project_id,
            "project_label": self.project_label,
            "source_system": self.source_system,
            "listing": self.listing.public_dict(),
            "protocol": self.protocol.public_dict(),
            "domain_groups": {key: group.public_dict() for key, group in self.domain_groups.items()},
            "unclassified_sheet_names": list(self.unclassified_sheet_names),
            "ai_task_plan": [task.public_dict() for task in self.ai_task_plan],
            "forbidden_legacy_inputs": list(self.forbidden_legacy_inputs),
            "ai_gateway_status": {
                "configured": configured,
                "provider": str(self.ai_gateway_status.get("provider", "")),
                "model": str(self.ai_gateway_status.get("model", "")),
                "semantic_ai_tasks_enabled": semantic_ai_tasks_enabled,
                "codex_runtime_dependency": codex_runtime_dependency,
                "missing_env": list(self.ai_gateway_status.get("missing_env", [])),
                "disabled_reason": self.ai_gateway_status.get("disabled_reason"),
            },
        }


class MonitoringRawProjectIntakeService:
    def __init__(self, ai_provider_configured: Optional[bool] = None):
        if ai_provider_configured is not None and not isinstance(
            ai_provider_configured, bool
        ):
            raise ValueError("ai_provider_configured must be boolean or None")
        self.ai_provider_configured = ai_provider_configured
        self._cache: Dict[tuple[Any, ...], MonitoringRawProjectSnapshot] = {}
        self._inflight: Dict[
            tuple[Any, ...],
            Future[MonitoringRawProjectSnapshot],
        ] = {}
        self._cache_lock = Lock()

    def discover_project(self, config: MonitoringRawProjectConfig) -> MonitoringRawProjectSnapshot:
        project_id = config.project_id.strip()
        if not project_id:
            raise ValueError("project_id is required")
        listing_path = self._resolve_existing_file(config.listing_path, config.allowed_roots)
        protocol_path = self._resolve_existing_file(config.protocol_path, config.allowed_roots)
        supplemental_paths = [
            self._resolve_existing_file(path, config.allowed_roots)
            for path in config.supplemental_listing_paths
        ]
        ai_gateway_status = ai_gateway_status_from_env()
        if self.ai_provider_configured is not None:
            ai_gateway_status = dict(ai_gateway_status)
            ai_gateway_status["configured"] = self.ai_provider_configured
            ai_gateway_status["semantic_ai_tasks_enabled"] = self.ai_provider_configured
            if not self.ai_provider_configured:
                ai_gateway_status["disabled_reason"] = "external AI provider is not configured"
        cache_key = _snapshot_cache_key(
            project_id=project_id,
            project_label=config.project_label,
            listing_path=listing_path,
            protocol_path=protocol_path,
            supplemental_paths=supplemental_paths,
            ai_gateway_status=ai_gateway_status,
        )
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            inflight = self._inflight.get(cache_key)
            if cached is None and inflight is None:
                inflight = Future()
                self._inflight[cache_key] = inflight
                owns_load = True
            else:
                owns_load = False
        if cached is not None:
            return cached
        if not owns_load:
            assert inflight is not None
            return inflight.result()

        assert inflight is not None
        try:
            parsed_sheets = parse_listing_file(
                listing_path.name,
                listing_path.read_bytes(),
            )
            listing_summary = self._listing_summary(
                listing_path,
                parsed_sheets,
                supplemental_paths,
            )
            protocol_summary = self._protocol_summary(protocol_path)
            domain_groups, unclassified_sheet_names = self._domain_groups(parsed_sheets)

            snapshot = MonitoringRawProjectSnapshot(
                project_id=project_id,
                project_label=config.project_label,
                source_system=RAW_MONITORING_SOURCE_SYSTEM,
                listing=listing_summary,
                protocol=protocol_summary,
                domain_groups=domain_groups,
                unclassified_sheet_names=unclassified_sheet_names,
                ai_task_plan=self._ai_task_plan(ai_gateway_status),
                forbidden_legacy_inputs=list(FORBIDDEN_MONITORING_INPUTS),
                ai_gateway_status=ai_gateway_status,
            )
        except BaseException as exc:
            with self._cache_lock:
                self._inflight.pop(cache_key, None)
            inflight.set_exception(exc)
            raise
        with self._cache_lock:
            self._cache[cache_key] = snapshot
            self._inflight.pop(cache_key, None)
        inflight.set_result(snapshot)
        return snapshot

    def _listing_summary(self, listing_path: Path, parsed_sheets: List[Any], supplemental_paths: List[Path]) -> MonitoringListingSummary:
        subjects = set()
        sites = set()
        subject_fields = set()
        site_fields = set()
        sheet_row_counts: Dict[str, int] = {}
        for sheet in parsed_sheets:
            sheet_row_counts[sheet.sheet_name] = len(sheet.rows)
            for row in sheet.rows:
                subject_value, subject_field = _first_value(row, SUBJECT_ID_FIELDS)
                if subject_value:
                    subjects.add(subject_value)
                    subject_fields.add(subject_field)
                site_value, site_field = _first_value(row, SITE_ID_FIELDS)
                if site_value:
                    sites.add(site_value)
                    site_fields.add(site_field)

        return MonitoringListingSummary(
            filename=listing_path.name,
            sheet_count=len(parsed_sheets),
            row_count=sum(len(sheet.rows) for sheet in parsed_sheets),
            subject_count=len(subjects),
            site_count=len(sites),
            subject_id_fields=sorted(subject_fields),
            site_id_fields=sorted(site_fields),
            sheet_row_counts=dict(sorted(sheet_row_counts.items())),
            supplemental_file_count=len(supplemental_paths),
        )

    def _protocol_summary(self, protocol_path: Path) -> MonitoringProtocolSummary:
        document = parse_protocol_docx(protocol_path.name, protocol_path.read_bytes())
        return MonitoringProtocolSummary(
            filename=document.filename,
            title=document.title,
            paragraph_count=len(document.paragraphs),
            table_count=len(document.tables),
            span_count=len(document.spans),
        )

    def _domain_groups(
        self,
        parsed_sheets: List[Any],
    ) -> tuple[Dict[str, MonitoringDomainGroup], List[str]]:
        grouped_rows: Dict[str, int] = Counter()
        grouped_sheets: Dict[str, set[str]] = defaultdict(set)
        grouped_domains: Dict[str, set[str]] = defaultdict(set)
        grouped_subjects: Dict[str, set[str]] = defaultdict(set)
        unclassified_sheet_names: list[str] = []

        for sheet in parsed_sheets:
            domain_code = _dominant_domain_code(sheet.sheet_name, sheet.rows)
            group_key = _domain_group_key(domain_code, sheet.sheet_name, sheet.rows)
            if not group_key:
                unclassified_sheet_names.append(str(sheet.sheet_name))
                continue
            grouped_rows[group_key] += len(sheet.rows)
            grouped_sheets[group_key].add(sheet.sheet_name)
            if domain_code:
                grouped_domains[group_key].add(domain_code)
            for row in sheet.rows:
                subject_value, _ = _first_value(row, SUBJECT_ID_FIELDS)
                if subject_value:
                    grouped_subjects[group_key].add(subject_value)

        return (
            {
                key: MonitoringDomainGroup(
                    group_key=key,
                    label=DOMAIN_LABELS[key],
                    sheet_names=sorted(grouped_sheets[key]),
                    source_domains=sorted(grouped_domains[key]),
                    row_count=grouped_rows[key],
                    subject_count=len(grouped_subjects[key]),
                )
                for key in sorted(grouped_rows)
            },
            sorted(set(unclassified_sheet_names)),
        )

    def _ai_task_plan(self, ai_gateway_status: Dict[str, Any]) -> List[MonitoringRawAiTaskPlanItem]:
        status = "ready_external_ai_configured"
        if _strict_bool(
            ai_gateway_status.get("semantic_ai_tasks_enabled"),
            "ai_gateway_status.semantic_ai_tasks_enabled",
        ) is not True:
            status = "blocked_external_ai_not_ready"
        task_specs = [
            (AiTaskType.LISTING_SEMANTIC_MAPPING.value, "listing_semantic_mapping_v0_1", ["listing_sheet_headers", "listing_sample_rows"]),
            (AiTaskType.PROTOCOL_RULE_EXTRACTION.value, "monitoring_protocol_rule_extraction_v0_1", ["protocol_docx_spans"]),
            (AiTaskType.MONITORING_RISK_INTERPRETATION.value, "monitoring_risk_interpretation_v0_1", ["normalized_listing_rows", "protocol_rules_pending"]),
            (AiTaskType.SUBJECT_TIMELINE_DERIVATION.value, "subject_timeline_derivation_v0_1", ["visit_axis", "domain_grouped_events"]),
            (AiTaskType.PATIENT_PROFILE_DERIVATION.value, "patient_profile_derivation_v0_1", ["efficacy_trends", "safety_trends", "source_event_index"]),
        ]
        return [
            MonitoringRawAiTaskPlanItem(
                task_type=task_type,
                module="medical_monitoring",
                prompt_version=prompt_version,
                status=status,
                input_source_scopes=scopes,
                forbidden_source_ids=list(FORBIDDEN_MONITORING_INPUTS),
            )
            for task_type, prompt_version, scopes in task_specs
        ]

    def _resolve_existing_file(self, path: PathLike, allowed_roots: Sequence[PathLike]) -> Path:
        resolved = Path(path).expanduser().resolve()
        self._validate_allowed_root(resolved, allowed_roots)
        if not resolved.exists():
            raise FileNotFoundError(str(resolved))
        if not resolved.is_file():
            raise IsADirectoryError(str(resolved))
        return resolved

    def _validate_allowed_root(self, resolved_path: Path, allowed_roots: Sequence[PathLike]) -> None:
        if not allowed_roots:
            return
        allowed = [Path(root).expanduser().resolve() for root in allowed_roots]
        if not any(_is_relative_to(resolved_path, root) for root in allowed):
            raise PermissionError(f"path is outside allowed roots: {resolved_path.name}")


DOMAIN_LABELS = {
    "adverse_event": "AE/安全性事件",
    "medical_history": "MH/疾病史",
    "lab": "实验室检查",
    "efficacy": "疗效评价",
    "visit": "访视轴",
    "concomitant_medication": "CM/非试验用药",
    "non_drug_treatment": "非药物治疗",
    "study_drug_change": "试验药物变更",
    "protocol_deviation": "方案偏离/Query",
}

# Header-shape fallback for workbooks whose sheet names and DOMAIN values are
# project-specific.  Each domain requires two independent signature groups;
# ties remain unclassified instead of being guessed.
_HEADER_DOMAIN_SIGNATURES = {
    "adverse_event": (
        {"AETERM", "AE_TERM", "ADVERSE_EVENT", "ADVERSE_EVENT_TERM"},
        {"AESTDTC", "AEENDTC", "AESEV", "AEREL", "AEOUT"},
    ),
    "medical_history": (
        {"MHTERM", "MH_TERM", "MEDICAL_HISTORY", "MEDICAL_HISTORY_TERM"},
        {"MHSTDTC", "MHENDTC", "MHONGO", "MHCAT"},
    ),
    "lab": (
        {"LBTEST", "LB_TEST", "LAB_TEST", "LABORATORY_TEST"},
        {"LBORRES", "LBSTRESN", "LBSTRESC", "LBORRESU", "LBSTRESU"},
    ),
    "efficacy": (
        {"QSTEST", "QS_TEST", "SCALE_TEST", "SCORE_TEST"},
        {"QSORRES", "QSSTRESN", "QSSTRESC", "QSDTC", "SCORE_VALUE"},
    ),
    "visit": (
        {"VISIT", "VISITNUM", "VISIT_NAME", "VISIT_NUMBER"},
        {"SVSTDTC", "SVENDTC", "VISIT_DATE", "VISIT_WINDOW"},
    ),
    "concomitant_medication": (
        {"CMTRT", "CM_TRT", "CONMED", "CONCOMITANT_MEDICATION"},
        {"CMSTDTC", "CMENDTC", "CMDOSE", "CMROUTE", "CMONGO"},
    ),
    "non_drug_treatment": (
        {"PRTRT", "PR_TRT", "NON_DRUG_TREATMENT", "PROCEDURE"},
        {"PRSTDTC", "PRENDTC", "PRDOSE", "PRINDC"},
    ),
    "study_drug_change": (
        {"EXTRT", "EX_TRT", "STUDY_DRUG", "IP_NAME", "TREATMENT"},
        {"EXDOSE", "EXSTDTC", "EXENDTC", "EXROUTE", "DOSE_CHANGE"},
    ),
    "protocol_deviation": (
        {"PDTERM", "PD_TERM", "DEVIATION", "QUERY_TERM", "DVCODE"},
        {"PDSTDTC", "PDENDTC", "PDSEV", "PDSTATUS", "QUERY_STATUS"},
    ),
}


def _first_value(row: Dict[str, Any], fields: List[str]) -> tuple[str, str]:
    for field in fields:
        value = _text(row.get(field))
        if value:
            return value, field
    return "", ""


def _dominant_domain_code(sheet_name: str, rows: List[Dict[str, Any]]) -> str:
    domain_counts = Counter(_text(row.get("DOMAIN")).upper() for row in rows if _text(row.get("DOMAIN")))
    if domain_counts:
        return domain_counts.most_common(1)[0][0]
    prefix = sheet_name.split("--", 1)[0].strip().upper()
    return prefix


def _domain_group_key(
    domain_code: str,
    sheet_name: str,
    rows: Optional[List[Dict[str, Any]]] = None,
) -> str:
    code = (domain_code or "").upper()
    sheet = sheet_name.upper()
    if code.startswith("AE") or sheet.startswith("AE"):
        return "adverse_event"
    if code.startswith("MH") or sheet.startswith("MH") or "病史" in sheet:
        return "medical_history"
    if code.startswith("LB") or sheet.startswith("LB") or "实验室" in sheet:
        return "lab"
    if code in {"BSA", "IGA", "EASI", "SR", "QS", "QS1", "QS2", "QS3"} or sheet.startswith(("BSA", "IGA", "EASI", "SR", "QS")):
        return "efficacy"
    if code == "SV" or sheet.startswith("SV"):
        return "visit"
    if code.startswith("CM") or sheet.startswith("CM"):
        return "concomitant_medication"
    if code.startswith("PR") or sheet.startswith("PR"):
        return "non_drug_treatment"
    if code in {"DA", "DAA", "DAB", "ECB", "ECA", "EX", "EX2", "EX3"} or sheet.startswith(("DA", "ECB", "ECA", "EX")):
        return "study_drug_change"
    if code.startswith(("PD", "DV", "QUERY")) or sheet.startswith(("PD", "DV", "QUERY")):
        return "protocol_deviation"
    return _header_inferred_domain_group(rows or [])


def _header_inferred_domain_group(rows: List[Dict[str, Any]]) -> str:
    """Infer one domain only from two matching header-shape signatures."""

    headers = {
        re.sub(r"[^A-Z0-9]", "_", str(field).strip().upper())
        for row in rows
        if isinstance(row, dict)
        for field in row
    }
    if not headers:
        return ""
    scores = {
        group_key: sum(bool(headers.intersection(signature)) for signature in signatures)
        for group_key, signatures in _HEADER_DOMAIN_SIGNATURES.items()
    }
    eligible = [(score, group_key) for group_key, score in scores.items() if score >= 2]
    if not eligible:
        return ""
    highest = max(score for score, _group_key in eligible)
    winners = sorted(group_key for score, group_key in eligible if score == highest)
    return winners[0] if len(winners) == 1 else ""


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _strict_bool(value: Any, field: str, *, default: bool = False) -> bool:
    """Accept an actual Boolean and reject truthy strings/numbers."""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise ValueError(f"{field} must be boolean")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _snapshot_cache_key(
    project_id: str,
    project_label: str,
    listing_path: Path,
    protocol_path: Path,
    supplemental_paths: List[Path],
    ai_gateway_status: Dict[str, Any],
) -> tuple[Any, ...]:
    return (
        project_id,
        project_label,
        _file_fingerprint(listing_path),
        _file_fingerprint(protocol_path),
        tuple(_file_fingerprint(path) for path in supplemental_paths),
        _strict_bool(ai_gateway_status.get("configured"), "ai_gateway_status.configured"),
        _strict_bool(
            ai_gateway_status.get("semantic_ai_tasks_enabled"),
            "ai_gateway_status.semantic_ai_tasks_enabled",
        ),
        str(ai_gateway_status.get("provider", "")),
        str(ai_gateway_status.get("model", "")),
        str(ai_gateway_status.get("transport", "")),
        str(ai_gateway_status.get("deployment_profile", "")),
        _strict_bool(
            ai_gateway_status.get("deployment_profile_approved"),
            "ai_gateway_status.deployment_profile_approved",
        ),
        tuple(ai_gateway_status.get("route_validation_errors", [])),
        tuple(ai_gateway_status.get("missing_env", [])),
    )


def _file_fingerprint(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return (str(path), int(stat.st_mtime_ns), int(stat.st_size))
