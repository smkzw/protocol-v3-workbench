#!/usr/bin/env python3
"""Read-only cross-job audit for medical-monitoring mapping candidates.

The formal semantic quality gate evaluates one assembled mapping draft. This
tool adds an observation layer over independent-AI candidate jobs so that role
drift and lineage inconsistencies can be found before draft assembly. It never
writes to the source SQLite database.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.api.app.monitoring_mapping_semantic_quality import (  # noqa: E402
    ROLE_CATALOG_V1,
)


SCHEMA_VERSION = "monitoring_mapping_candidate_cross_job_audit_v1"
DEFAULT_JOB_STATUSES = ("completed",)
DEFAULT_CANDIDATE_STATUSES = ("accepted", "proposed")
SEVERITY_ORDER = {"error": 0, "warning": 1, "observation": 2}

BUSINESS_KEY_RE = re.compile(
    r"^listing-field-mapping:(?P<batch>.+):(?P<domain>[^:]+):"
    r"(?P<index>\d+)-of-(?P<total>\d+)$"
)
PARTIAL_DATE_RE = re.compile(
    r"(?:^|[-/])(?:uk|unk|unknown|xx|00)(?:$|[-/])",
    re.IGNORECASE,
)
YEAR_MONTH_RE = re.compile(r"^\d{4}(?:[-/]\d{1,2})?$")
DATE_FIELD_RE = re.compile(
    r"(?:date|datetime|start|end|onset|stop|datd?|dtc?|dttm)",
    re.IGNORECASE,
)
SCALE_RE = re.compile(
    r"(?:scale|questionnaire|dlqi|cdlqi|easi|bsa|nrs|vas|score|评分|量表)",
    re.IGNORECASE,
)
NON_SPECIFIC_CODING_RE = re.compile(
    r"(?:unknown|unspecified|pending|field.?name|term.?code|"
    r"project.?dictionary|local.?dictionary|待确认|未指定|不明确|不详|"
    r"项目(?:字典|词典)|本地(?:字典|词典)|未明确(?:的)?(?:项目)?(?:字典|词典))",
    re.IGNORECASE,
)
IP_ACTION_MARKERS: Mapping[str, tuple[str, ...]] = {
    "administration": ("administration", "actual.dose", "actual.exposure", "实际给药"),
    "dose_adjustment": ("dose.adjustment", "dose.change", "剂量调整"),
    "interruption": ("interruption", "temporary.discontinuation", "暂时停药"),
    "discontinuation": ("permanent.discontinuation", "永久停药"),
    "restart": ("restart", "resume", "恢复给药", "重启"),
    "dispense": ("dispense", "dispensing", "发放"),
    "return": ("return", "returned", "回收"),
    "compliance": ("compliance", "adherence", "依从"),
}
IP_ACCOUNTABILITY_MARKERS: tuple[str, ...] = (
    "drug.accountability",
    "drug.amount.presented",
    "drug.weight",
    "withdrawn.dose",
    "study.drug.inventory",
    "investigational.product.inventory",
    "试验药物盘点",
    "试验药物责任",
)


def _token(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", ".", str(value).casefold()).strip(".")


ROLE_ALIASES: dict[str, tuple[str, str]] = {}
for _concept in ROLE_CATALOG_V1:
    for _alias in (_concept.role_concept_id, *_concept.aliases):
        ROLE_ALIASES[_token(_alias)] = (
            _concept.role_concept_id,
            _concept.role_family,
        )


@dataclass(frozen=True)
class CandidateRecord:
    job_id: str
    project_id: str
    business_key: str
    prompt_version: str
    job_status: str
    candidate_status: str
    created_at: str
    updated_at: str
    candidate: Mapping[str, Any]

    @property
    def parsed_key(self) -> Mapping[str, Any]:
        match = BUSINESS_KEY_RE.match(self.business_key)
        if not match:
            return {"batch_id": "", "domain": "", "chunk_index": 0, "chunk_total": 0}
        return {
            "batch_id": match.group("batch"),
            "domain": match.group("domain"),
            "chunk_index": int(match.group("index")),
            "chunk_total": int(match.group("total")),
        }


@dataclass(frozen=True)
class FieldOccurrence:
    record: CandidateRecord
    mapping: Mapping[str, Any]
    domain: str
    source_field: str
    role: str
    canonical_role: str
    role_family: str
    field_kind: str
    deterministic: bool

    @property
    def locator(self) -> str:
        return (
            f"{self.record.project_id}/{self.record.business_key}/"
            f"{self.domain}.{self.source_field}"
        )

    @property
    def signature(self) -> str:
        return f"{self.canonical_role or _token(self.role)}|{self.field_kind}"


def _json_hash(value: Any) -> str:
    rendered = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(rendered.encode("utf-8")).hexdigest()


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _decode_candidate(value: Any) -> Mapping[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise ValueError("candidate_json must decode to an object")
    return value


def _candidate_record(
    candidate: Mapping[str, Any],
    metadata: Mapping[str, Any],
    *,
    ordinal: int,
) -> CandidateRecord:
    project_id = str(
        metadata.get("project_id") or candidate.get("project_id") or "unknown-project"
    ).strip()
    job_id = str(
        metadata.get("job_id") or candidate.get("job_id") or f"json-job-{ordinal:06d}"
    ).strip()
    mappings = _field_mappings(candidate)
    domain = str(mappings[0].get("domain", "")).strip() if mappings else ""
    business_key = str(
        metadata.get("business_key")
        or candidate.get("business_key")
        or f"json:{domain or 'unknown'}:{ordinal:06d}"
    ).strip()
    return CandidateRecord(
        job_id=job_id,
        project_id=project_id,
        business_key=business_key,
        prompt_version=str(
            metadata.get("prompt_version") or candidate.get("prompt_version") or ""
        ).strip(),
        job_status=str(metadata.get("job_status") or metadata.get("status") or "").strip(),
        candidate_status=str(
            metadata.get("candidate_status") or candidate.get("status") or ""
        ).strip(),
        created_at=str(
            metadata.get("candidate_created_at")
            or candidate.get("created_at")
            or metadata.get("created_at")
            or ""
        ).strip(),
        updated_at=str(metadata.get("updated_at") or "").strip(),
        candidate=candidate,
    )


def _records_from_json_node(
    node: Any,
    *,
    inherited: Mapping[str, Any] | None = None,
) -> list[CandidateRecord]:
    inherited = inherited or {}
    records: list[CandidateRecord] = []
    if isinstance(node, list):
        for index, item in enumerate(node, start=1):
            child = _records_from_json_node(item, inherited=inherited)
            if child:
                records.extend(child)
            elif isinstance(item, Mapping):
                records.append(_candidate_record(item, inherited, ordinal=index))
        return records
    if not isinstance(node, Mapping):
        return records
    if "candidate_json" in node:
        candidate = _decode_candidate(node["candidate_json"])
        records.append(_candidate_record(candidate, node, ordinal=1))
        return records
    if _field_mappings(node):
        records.append(_candidate_record(node, inherited, ordinal=1))
        return records
    metadata = {**inherited, **{key: value for key, value in node.items() if key != "candidates"}}
    if isinstance(node.get("candidates"), list):
        for index, candidate in enumerate(node["candidates"], start=1):
            if isinstance(candidate, Mapping) and _field_mappings(candidate):
                records.append(_candidate_record(candidate, metadata, ordinal=index))
            else:
                records.extend(_records_from_json_node(candidate, inherited=metadata))
        return records
    for key in ("records", "jobs", "items", "results"):
        if isinstance(node.get(key), list):
            records.extend(_records_from_json_node(node[key], inherited=metadata))
            return records
    return records


def load_candidate_json(path: Path) -> list[CandidateRecord]:
    data = json.loads(path.read_text(encoding="utf-8"))
    records = _records_from_json_node(data)
    if not records:
        raise ValueError(f"no listing field-mapping candidates found in {path}")
    return records


def load_candidate_sqlite(
    path: Path,
    *,
    prompt_versions: Sequence[str] = (),
    project_ids: Sequence[str] = (),
    job_statuses: Sequence[str] = DEFAULT_JOB_STATUSES,
    candidate_statuses: Sequence[str] = DEFAULT_CANDIDATE_STATUSES,
) -> list[CandidateRecord]:
    """Read candidates from SQLite without creating or mutating database files."""

    if not path.is_file():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        clauses = ["j.task_type = 'listing_field_mapping'"]
        parameters: list[str] = []
        for column, values in (
            ("j.prompt_version", prompt_versions),
            ("j.project_id", project_ids),
            ("j.status", job_statuses),
            ("c.status", candidate_statuses),
        ):
            cleaned = tuple(str(value).strip() for value in values if str(value).strip())
            if cleaned:
                clauses.append(f"{column} IN ({','.join('?' for _ in cleaned)})")
                parameters.extend(cleaned)
        rows = connection.execute(
            f"""
            SELECT
                j.job_id,
                j.project_id,
                j.business_key,
                j.prompt_version,
                j.status AS job_status,
                j.updated_at,
                c.status AS candidate_status,
                c.created_at AS candidate_created_at,
                c.candidate_json
            FROM monitoring_ai_jobs AS j
            JOIN monitoring_ai_candidates AS c ON c.job_id = j.job_id
            WHERE {' AND '.join(clauses)}
            ORDER BY j.project_id, j.business_key, c.created_at, c.candidate_id
            """,
            parameters,
        ).fetchall()
    finally:
        connection.close()
    latest: dict[str, CandidateRecord] = {}
    for row in rows:
        candidate = _decode_candidate(row["candidate_json"])
        latest[row["job_id"]] = _candidate_record(
            candidate,
            dict(row),
            ordinal=1,
        )
    return [latest[key] for key in sorted(latest)]


def _field_mappings(candidate: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    structured = _as_mapping(candidate.get("structured_payload"))
    return [
        item
        for item in _as_list(structured.get("field_mappings"))
        if isinstance(item, Mapping)
    ]


def _deterministic_keys(candidate: Mapping[str, Any]) -> frozenset[tuple[str, str]]:
    structured = _as_mapping(candidate.get("structured_payload"))
    provenance = _as_mapping(structured.get("mapping_provenance"))
    origins = _as_list(provenance.get("field_origins"))
    return frozenset(
        (
            str(item.get("domain", "")).strip().casefold(),
            str(item.get("source_field", "")).strip().casefold(),
        )
        for item in origins
        if isinstance(item, Mapping)
        and str(item.get("origin", "")).strip() == "deterministic_rule"
    )


def _canonical_role(role: str) -> tuple[str, str]:
    return ROLE_ALIASES.get(_token(role), ("", ""))


def _expected_fields(candidate: Mapping[str, Any]) -> set[tuple[str, str]]:
    expected: set[tuple[str, str]] = set()
    for evidence in _as_list(candidate.get("evidence")):
        raw = _as_mapping(_as_mapping(evidence).get("raw_fields"))
        domain = str(raw.get("domain", "")).strip()
        field = str(raw.get("field", "")).strip()
        if domain and field:
            expected.add((domain, field))
    return expected


def _evidence_by_field(
    candidate: Mapping[str, Any],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    for evidence in _as_list(candidate.get("evidence")):
        raw = _as_mapping(_as_mapping(evidence).get("raw_fields"))
        domain = str(raw.get("domain", "")).strip()
        field = str(raw.get("field", "")).strip()
        if domain and field:
            result[(domain.casefold(), field.casefold())] = raw
    return result


def _make_occurrences(
    records: Sequence[CandidateRecord],
) -> tuple[list[FieldOccurrence], list[dict[str, Any]]]:
    occurrences: list[FieldOccurrence] = []
    job_summaries: list[dict[str, Any]] = []
    for record in records:
        mappings = _field_mappings(record.candidate)
        deterministic = _deterministic_keys(record.candidate)
        actual_pairs = [
            (
                str(item.get("domain", "")).strip(),
                str(item.get("source_field", "")).strip(),
            )
            for item in mappings
        ]
        counts = Counter(actual_pairs)
        actual = set(actual_pairs)
        expected = _expected_fields(record.candidate)
        parsed = record.parsed_key
        job_summaries.append(
            {
                "project_id": record.project_id,
                "job_id": record.job_id,
                "business_key": record.business_key,
                "batch_id": parsed["batch_id"],
                "domain": parsed["domain"]
                or (actual_pairs[0][0] if actual_pairs else ""),
                "chunk_index": parsed["chunk_index"],
                "chunk_total": parsed["chunk_total"],
                "field_count": len(mappings),
                "expected_field_count": len(expected),
                "missing_fields": [
                    f"{domain}.{field}" for domain, field in sorted(expected - actual)
                ],
                "unexpected_fields": [
                    f"{domain}.{field}" for domain, field in sorted(actual - expected)
                ]
                if expected
                else [],
                "duplicate_fields": [
                    f"{domain}.{field}"
                    for (domain, field), count in sorted(counts.items())
                    if count > 1
                ],
                "candidate_sha256": _json_hash(record.candidate),
            }
        )
        for mapping in mappings:
            domain = str(mapping.get("domain", "")).strip()
            source_field = str(mapping.get("source_field", "")).strip()
            role = str(mapping.get("recommended_role", "")).strip()
            canonical_role, role_family = _canonical_role(role)
            occurrences.append(
                FieldOccurrence(
                    record=record,
                    mapping=mapping,
                    domain=domain,
                    source_field=source_field,
                    role=role,
                    canonical_role=canonical_role,
                    role_family=role_family,
                    field_kind=str(mapping.get("field_kind", "")).strip(),
                    deterministic=(
                        (domain.casefold(), source_field.casefold()) in deterministic
                    ),
                )
            )
    return occurrences, job_summaries


def _finding(
    *,
    category: str,
    severity: str,
    code: str,
    title: str,
    detail: str,
    locators: Iterable[str],
    variants: Iterable[str] = (),
) -> dict[str, Any]:
    locator_list = sorted(set(locators))
    variant_list = sorted(set(variants))
    identity = {
        "category": category,
        "code": code,
        "locators": locator_list,
        "variants": variant_list,
    }
    return {
        "finding_id": f"mca_{_json_hash(identity)[:16]}",
        "severity": severity,
        "category": category,
        "code": code,
        "title": title,
        "detail": detail,
        "variants": variant_list,
        "locators": locator_list,
    }


def _technical_signature(item: FieldOccurrence) -> str:
    normalized_roles = {
        "FORM": "metadata.form_name",
        "PAGE": "metadata.page_name",
        "LINE": "metadata.source_row_number",
    }
    source_field = item.source_field.strip().upper()
    if source_field in normalized_roles:
        return f"{normalized_roles[source_field]}|source_metadata"
    if source_field == "LBNAM" and item.domain.strip().upper().startswith("LB"):
        return "metadata.lab_configuration_name|source_metadata"
    return item.signature


def _technical_drift_findings(
    occurrences: Sequence[FieldOccurrence],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_field: dict[str, list[FieldOccurrence]] = defaultdict(list)
    for item in occurrences:
        if item.source_field:
            by_field[item.source_field.casefold()].append(item)
    findings: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []
    for source_key, group in sorted(by_field.items()):
        mapped_group = [
            item for item in group if item.field_kind != "unmapped"
        ]
        if not mapped_group:
            continue
        is_technical = any(
            item.deterministic
            or item.field_kind == "source_metadata"
            or item.role_family == "metadata"
            for item in mapped_group
        )
        if not is_technical:
            continue
        signatures = sorted(
            {_technical_signature(item) for item in mapped_group}
        )
        inventory.append(
            {
                "source_field": sorted({item.source_field for item in group})[0],
                "occurrence_count": len(group),
                "project_count": len({item.record.project_id for item in group}),
                "signatures": signatures,
            }
        )
        if len(signatures) > 1:
            findings.append(
                _finding(
                    category="technical_role_consistency",
                    severity="error",
                    code="XJOB-TECH-ROLE-DRIFT",
                    title="稳定技术字段在候选作业间发生角色或字段性质漂移",
                    detail=(
                        f"来源字段 {source_key} 出现多个技术签名；稳定技术元数据"
                        "必须跨分块、跨域和跨项目保持同一角色概念与字段性质。"
                    ),
                    variants=signatures,
                    locators=(item.locator for item in mapped_group),
                )
            )
    return findings, inventory


def _cm_ip_family(role: str) -> str:
    token = _token(role)
    cm = token.startswith(("cm.", "concomitant.medication.", "non.ip."))
    ip = token.startswith(("ip.", "investigational.", "study.drug."))
    if cm and ip:
        return "mixed"
    if cm:
        return "cm"
    if ip:
        return "ip"
    return ""


def _occurrence_cm_ip_family(item: FieldOccurrence) -> str:
    if item.role_family.startswith("ip."):
        return "ip"
    if item.role_family == "cm":
        return "cm"
    return _cm_ip_family(item.role)


def _cm_ip_findings(
    occurrences: Sequence[FieldOccurrence],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    by_semantic_key: dict[tuple[str, str], list[FieldOccurrence]] = defaultdict(list)
    for item in occurrences:
        family = _occurrence_cm_ip_family(item)
        if family == "mixed" or (
            item.domain.casefold() == "cm" and family == "ip"
        ):
            findings.append(
                _finding(
                    category="cm_ip_boundary",
                    severity="error",
                    code="XJOB-CM-IP-BOUNDARY",
                    title="CM 与试验药物语义越界",
                    detail=(
                        "CM 仅表示非试验用药或治疗；试验药物给药及变更必须"
                        "单列，不能写入 CM 角色。"
                    ),
                    locators=(item.locator,),
                    variants=(item.role,),
                )
            )
        token = _token(item.role)
        actions = sorted(
            action
            for action, markers in IP_ACTION_MARKERS.items()
            if any(marker in token for marker in markers)
        )
        if len(actions) > 1:
            findings.append(
                _finding(
                    category="cm_ip_boundary",
                    severity="warning",
                    code="XJOB-IP-ACTION-COLLAPSE",
                    title="一个角色合并了多个试验药物动作",
                    detail=(
                        "实际给药、剂量调整、暂时停药、永久停药、恢复给药、"
                        "发放、回收和依从性必须保持独立语义；正式 draft "
                        "assembly 会将该角色确定性隔离为闭合来源值角色并"
                        "显式阻止单一动作使用，任何单一动作能力均不可就绪。"
                    ),
                    locators=(item.locator,),
                    variants=(
                        *actions,
                        "resolution=draft_assembly_multi_action_quarantine",
                    ),
                )
            )
        elif (
            len(actions) == 1
            and family not in {"ip", "cm"}
        ):
            findings.append(
                _finding(
                    category="cm_ip_boundary",
                    severity="warning",
                    code="XJOB-IP-ACTION-ROLE-UNRESOLVED",
                    title="试验药物动作尚未进入闭合角色",
                    detail=(
                        "来源角色已表达回收、依从性或其他试验药物动作，"
                        "但尚未进入独立 IP 角色；原始值可保留，"
                        "暴露和依从性结论必须受限。"
                    ),
                    locators=(item.locator,),
                    variants=actions,
                )
            )
        if (
            any(marker in token for marker in IP_ACCOUNTABILITY_MARKERS)
            and family not in {"ip", "cm"}
        ):
            findings.append(
                _finding(
                    category="cm_ip_boundary",
                    severity="warning",
                    code="XJOB-IP-ACCOUNTABILITY-ROLE-UNRESOLVED",
                    title="试验药物责任或盘点语义尚未进入闭合角色",
                    detail=(
                        "来源角色疑似表达试验药物称量、呈交、撤回剂量或库存责任，"
                        "但未显式进入独立 IP 责任/盘点角色；原始值可保留，"
                        "给药、回收和依从性结论必须受限。"
                    ),
                    locators=(item.locator,),
                    variants=("ip_accountability_candidate",),
                )
            )
        by_semantic_key[
            (item.domain.casefold(), item.source_field.casefold())
        ].append(item)
    for key, group in sorted(by_semantic_key.items()):
        families = {_occurrence_cm_ip_family(item) for item in group} - {""}
        projects = {item.record.project_id for item in group}
        if families == {"cm", "ip"} and len(projects) > 1:
            findings.append(
                _finding(
                    category="cm_ip_boundary",
                    severity="warning",
                    code="XPROJ-CM-IP-VARIANT",
                    title="同名来源字段在不同项目间分属 CM 与试验药物语义",
                    detail=(
                        f"{key[0]}.{key[1]} 的跨项目角色边界不同；可能是供应商"
                        "口径差异，也可能是候选过拟合，需结合数据字典复核。"
                    ),
                    locators=(item.locator for item in group),
                    variants=families,
                )
            )
    return findings


def _lineage(mapping: Mapping[str, Any]) -> Mapping[str, Any]:
    return _as_mapping(
        mapping.get("coding_lineage") or mapping.get("derivation_lineage")
    )


def _coding_system(item: FieldOccurrence) -> str:
    lineage = _lineage(item.mapping)
    reference = _as_mapping(item.mapping.get("standards_reference"))
    role_token = _token(item.role)
    combined = " ".join(
        (
            item.role,
            str(lineage.get("coding_system", "")),
            str(reference.get("reference_name", "")),
            str(reference.get("ctcae_version", "")),
        )
    ).casefold()
    if "meddra" in combined and (
        item.field_kind == "standardized_coded"
        or item.canonical_role.startswith("coding.meddra.")
        or re.search(
            r"meddra.(?:llt|pt|hlt|hlgt|soc).(?:code|term)",
            role_token,
        )
    ):
        return "MedDRA"
    if re.search(r"(?:^|[._\s])atc(?:[._\s]|$)", combined):
        return "ATC"
    if "who drug" in combined or "whodrug" in combined or "who-drug" in combined:
        return "WHO Drug"
    if "ctcae" in combined:
        return "CTCAE"
    if (
        item.canonical_role.startswith("coding.drug.")
        or re.search(r"(?:drug|药品).*(?:code|term|dictionary|字典|词典)", combined)
    ):
        return "Drug dictionary"
    if item.field_kind == "standardized_coded":
        return str(lineage.get("coding_system", "")).strip() or "unspecified"
    return ""


def _is_coding_support_field(item: FieldOccurrence) -> bool:
    return (
        item.field_kind == "source_metadata"
        and _is_declared_coding_support_role(item)
    )


def _is_declared_coding_support_role(item: FieldOccurrence) -> bool:
    if item.canonical_role in {
        "coding.meddra.dictionary_version",
        "coding.meddra.dictionary_language",
        "coding.drug.dictionary_version",
        "coding.drug.dictionary_language",
    }:
        return True
    role = _token(item.role)
    return any(
        marker in role
        for marker in (
            "dictionary.version",
            "coding.version",
            "coding.language",
            "dictionary.language",
            "ctcae.version",
            "grading.definition.version",
        )
    )


_CODING_SUPPORT_ROLE_CONCEPT_IDS = frozenset(
    {
        "coding.meddra.dictionary_version",
        "coding.meddra.dictionary_language",
        "coding.drug.dictionary_version",
        "coding.drug.dictionary_language",
    }
)
_DRAFT_QUARANTINE_RESOLUTIONS = {
    "multi_action": "draft_assembly_multi_action_quarantine",
    "coding_downgrade": "draft_assembly_incomplete_coding_downgrade",
}
_FORMAL_GATE_RESOLUTIONS = {
    "partial_coding": "formal_semantic_quality_partial_coding_restriction",
}


def _intrinsic_standardized_downgrade(item: FieldOccurrence) -> bool:
    """Downgrade reasons that no unobserved chunk field can repair.

    Mirrors the draft-assembly lineage checks that depend only on the claim
    itself (coding system, source-field list, version-field name).
    """

    lineage = _lineage(item.mapping)
    coding_system = str(lineage.get("coding_system", "")).strip()
    source_fields = [
        str(value).strip()
        for value in _as_list(lineage.get("source_fields"))
        if str(value).strip()
    ]
    version_name = str(lineage.get("dictionary_version_field", "")).strip()
    return bool(
        not coding_system
        or NON_SPECIFIC_CODING_RE.search(coding_system)
        or not source_fields
        or item.source_field.casefold()
        in {source.casefold() for source in source_fields}
        or not version_name
        or version_name.casefold() == item.source_field.casefold()
    )


def _assembly_downgrades_standardized(
    item: FieldOccurrence,
    available: Mapping[tuple[str, str, str], FieldOccurrence],
) -> bool:
    """Complete-domain mirror of the draft-assembly whole-source-set downgrade.

    True when draft assembly deterministically downgrades this standardized
    claim to source_collected: the claim must name a non-generic coding
    system, real same-domain source fields (never itself) and a separate
    declared dictionary-version support field that resolves to a closed
    support role and is (or becomes) source metadata.
    """

    if _intrinsic_standardized_downgrade(item):
        return True
    lineage = _lineage(item.mapping)
    source_fields = [
        str(value).strip()
        for value in _as_list(lineage.get("source_fields"))
        if str(value).strip()
    ]
    version_name = str(lineage.get("dictionary_version_field", "")).strip()
    if any(
        (
            item.record.project_id,
            item.domain.casefold(),
            source.casefold(),
        )
        not in available
        for source in source_fields
    ):
        return True
    version_support = available.get(
        (
            item.record.project_id,
            item.domain.casefold(),
            version_name.casefold(),
        )
    )
    if version_support is None:
        return True
    canonical, _ = _canonical_role(version_support.role)
    if canonical not in _CODING_SUPPORT_ROLE_CONCEPT_IDS:
        return True
    # Assembly normalizes canonical declared support fields to source_metadata;
    # any other field kind fails the assembled version-support contract.
    return version_support.field_kind not in {
        "source_metadata",
        "source_collected",
    }


def _coding_findings(
    occurrences: Sequence[FieldOccurrence],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    inventory: dict[str, dict[str, Any]] = {}
    chains: dict[tuple[str, str, str, str], list[FieldOccurrence]] = defaultdict(list)
    available = {
        (
            item.record.project_id,
            item.domain.casefold(),
            item.source_field.casefold(),
        ): item
        for item in occurrences
    }
    domain_chunks: dict[tuple[str, str], tuple[int, set[int]]] = {}
    for item in occurrences:
        parsed = item.record.parsed_key
        key = (item.record.project_id, item.domain.casefold())
        total = int(parsed.get("chunk_total") or 0)
        index = int(parsed.get("chunk_index") or 0)
        prior_total, prior_indexes = domain_chunks.get(key, (0, set()))
        domain_chunks[key] = (
            max(prior_total, total),
            {*prior_indexes, *({index} if index else set())},
        )
    for item in occurrences:
        system = _coding_system(item)
        if not system:
            continue
        declared_support = _is_declared_coding_support_role(item)
        if declared_support:
            entry = inventory.setdefault(
                system,
                {
                    "coding_system": system,
                    "field_count": 0,
                    "complete_lineage_count": 0,
                    "incomplete_lineage_count": 0,
                    "support_field_count": 0,
                    "support_fields": set(),
                    "versions": set(),
                    "field_kinds": set(),
                },
            )
            entry["field_count"] += 1
            entry["support_field_count"] += 1
            entry["support_fields"].add(item.source_field)
            entry["field_kinds"].add(item.field_kind)
            if item.field_kind != "source_metadata":
                findings.append(
                    _finding(
                        category="coding_lineage",
                        severity="warning",
                        code="XJOB-CODING-SUPPORT-METADATA-NORMALIZATION",
                        title="词典支持字段需要确定性归一为来源元数据",
                        detail=(
                            "候选已明确声明词典版本或语言角色，但字段性质不是"
                            "source_metadata；正式 draft assembly 将保留候选审计并"
                            "确定性归一，归一前不得形成正式编码血缘。"
                        ),
                        locators=(item.locator,),
                        variants=(
                            f"field_kind={item.field_kind}",
                            "resolution=draft_assembly_coding_support_metadata",
                        ),
                    )
                )
            continue
        lineage = _lineage(item.mapping)
        reference = _as_mapping(item.mapping.get("standards_reference"))
        source_fields = [
            str(value).strip()
            for value in _as_list(lineage.get("source_fields"))
            if str(value).strip()
        ]
        coding_system = str(lineage.get("coding_system", "")).strip()
        version_field = str(
            lineage.get("dictionary_version_field")
            or reference.get("ctcae_version")
            or reference.get("grading_definition_version")
            or ""
        ).strip()
        version = version_field or str(
            lineage.get("dictionary_version") or ""
        ).strip()
        sources_exist = bool(source_fields) and all(
            (
                item.record.project_id,
                item.domain.casefold(),
                source.casefold(),
            )
            in available
            for source in source_fields
        )
        version_support = (
            available.get(
                (
                    item.record.project_id,
                    item.domain.casefold(),
                    version_field.casefold(),
                )
            )
            if version_field
            else None
        )
        independent_version = (
            version_support is not None
            and version_support.source_field.casefold()
            != item.source_field.casefold()
            and _is_declared_coding_support_role(version_support)
        )
        if system == "CTCAE":
            complete = bool(version)
        else:
            complete = bool(
                coding_system
                and not NON_SPECIFIC_CODING_RE.search(coding_system)
                and sources_exist
                and independent_version
            )
        entry = inventory.setdefault(
            system,
            {
                "coding_system": system,
                "field_count": 0,
                "complete_lineage_count": 0,
                "incomplete_lineage_count": 0,
                "support_field_count": 0,
                "support_fields": set(),
                "versions": set(),
                "field_kinds": set(),
            },
        )
        entry["field_count"] += 1
        if _is_coding_support_field(item):
            entry["support_field_count"] += 1
            entry["support_fields"].add(item.source_field)
            entry["field_kinds"].add(item.field_kind)
            continue
        entry["complete_lineage_count" if complete else "incomplete_lineage_count"] += 1
        if version:
            entry["versions"].add(version)
        entry["field_kinds"].add(item.field_kind)
        if not complete:
            total_chunks, observed_chunks = domain_chunks.get(
                (item.record.project_id, item.domain.casefold()),
                (0, set()),
            )
            domain_incomplete = (
                total_chunks > 0 and len(observed_chunks) < total_chunks
            )
            pending_cross_chunk_support = bool(
                domain_incomplete
                and coding_system
                and not NON_SPECIFIC_CODING_RE.search(coding_system)
                and source_fields
                and version_field
            )
            guaranteed_downgrade = (
                _intrinsic_standardized_downgrade(item)
                or (
                    not domain_incomplete
                    and _assembly_downgrades_standardized(item, available)
                )
            )
            if item.field_kind != "standardized_coded":
                severity = "warning"
            elif pending_cross_chunk_support or guaranteed_downgrade:
                # Pending cross-chunk support stays a plain warning; only
                # shapes the draft assembly deterministically downgrades
                # carry the resolution marker.
                severity = "warning"
            else:
                severity = "error"
            variants = [
                f"field_kind={item.field_kind}",
                f"coding_system={coding_system or '<missing>'}",
                f"version={version or '<missing>'}",
                f"source_fields={'present' if sources_exist else '<missing>'}",
                (
                    "domain_chunks=incomplete"
                    if domain_incomplete
                    else "domain_chunks=complete"
                ),
            ]
            if (
                severity == "warning"
                and item.field_kind == "standardized_coded"
                and guaranteed_downgrade
            ):
                variants.append(
                    "resolution="
                    + _DRAFT_QUARANTINE_RESOLUTIONS["coding_downgrade"]
                )
            findings.append(
                _finding(
                    category="coding_lineage",
                    severity=severity,
                    code=(
                        "XJOB-CODING-FALSE-STANDARDIZED"
                        if severity == "error"
                        else "XJOB-CODING-LINEAGE-INCOMPLETE"
                    ),
                    title=(
                        "标准编码声明缺少完整血缘"
                        if severity == "error"
                        else "来源编码角色缺少可核验血缘"
                    ),
                    detail=(
                        f"{system} 字段需要明确编码体系、真实来源字段及独立版本字段；"
                        "CTCAE 分级至少需明确版本或分级定义。"
                    ),
                    locators=(item.locator,),
                    variants=variants,
                )
            )
        chain_id = str(lineage.get("coding_chain_id", "")).strip()
        chains[
            (
                item.record.project_id,
                item.domain.casefold(),
                system,
                chain_id or "default",
            )
        ].append(item)
    for key, group in sorted(chains.items()):
        versions = {
            str(
                _lineage(item.mapping).get("dictionary_version")
                or _lineage(item.mapping).get("dictionary_version_field")
                or _as_mapping(item.mapping.get("standards_reference")).get(
                    "ctcae_version", ""
                )
            ).strip()
            for item in group
        } - {""}
        systems = {
            str(_lineage(item.mapping).get("coding_system", "")).strip().casefold()
            for item in group
        } - {""}
        kinds = {item.field_kind for item in group}
        material_kind_drift = (
            len(kinds) > 1 and "standardized_coded" in kinds
        )
        if len(versions) > 1 or len(systems) > 1 or material_kind_drift:
            total_chunks, observed_chunks = domain_chunks.get(
                (key[0], key[1]),
                (0, set()),
            )
            domain_incomplete = (
                total_chunks > 0 and len(observed_chunks) < total_chunks
            )
            kept = [
                member
                for member in group
                if not (
                    member.field_kind == "standardized_coded"
                    and (
                        _intrinsic_standardized_downgrade(member)
                        or (
                            not domain_incomplete
                            and _assembly_downgrades_standardized(
                                member,
                                available,
                            )
                        )
                    )
                )
            ]
            kept_versions = {
                str(
                    _lineage(member.mapping).get("dictionary_version")
                    or _lineage(member.mapping).get("dictionary_version_field")
                    or _as_mapping(
                        member.mapping.get("standards_reference")
                    ).get("ctcae_version", "")
                ).strip()
                for member in kept
            } - {""}
            kept_systems = {
                str(
                    _lineage(member.mapping).get("coding_system", "")
                )
                .strip()
                .casefold()
                for member in kept
            } - {""}
            kept_kinds = {member.field_kind for member in kept}
            post_downgrade_drift = (
                len(kept_versions) > 1
                or len(kept_systems) > 1
                or len(kept_kinds) > 1
            )
            # Without an explicit coding_chain_id, the "default" bucket is
            # only a same-domain/same-system inventory. Different hierarchy
            # levels may legitimately have different evidence strength:
            # complete HLT/HLGT/SOC claims can remain standardized while an
            # unclosed PT source value stays source_collected. The formal
            # semantic-quality gate converts that partial availability into a
            # coding capability blocker; it is not an internally inconsistent
            # declared chain. Explicit version/system drift, or drift inside a
            # named chain, remains an error.
            implicit_partial_coding = bool(
                key[3] == "default"
                and len(kept_kinds) > 1
                and len(kept_versions) <= 1
                and len(kept_systems) <= 1
            )
            severity = (
                "error"
                if post_downgrade_drift and not implicit_partial_coding
                else "warning"
            )
            variants = [
                *(f"version={value}" for value in versions),
                *(f"system={value}" for value in systems),
                *(f"field_kind={value}" for value in kinds),
            ]
            if implicit_partial_coding:
                variants.extend(
                    (
                        "scope=implicit_default_chain",
                        "resolution="
                        + _FORMAL_GATE_RESOLUTIONS["partial_coding"],
                    )
                )
            elif severity == "warning":
                variants.append(
                    "resolution="
                    + _DRAFT_QUARANTINE_RESOLUTIONS["coding_downgrade"]
                )
            findings.append(
                _finding(
                    category="coding_lineage",
                    severity=severity,
                    code="XJOB-CODING-CHAIN-DRIFT",
                    title=(
                        "同一编码链在候选作业间定义不一致"
                        if severity == "error"
                        else (
                            "同域编码层级仅部分具备标准化血缘"
                            if implicit_partial_coding
                            else "同一编码链的标准化声明将由草稿装配确定性降级"
                        )
                    ),
                    detail=(
                        (
                            f"{key[0]}/{key[1]}/{key[2]} 未声明统一 coding_chain_id；"
                            "部分层级具备完整标准化血缘，另一些层级仅保留来源值。"
                            "正式语义质量门必须限制标准编码能力，不得把来源值提升为"
                            "标准编码；该形状不等于一个显式编码链内部自相矛盾。"
                        )
                        if implicit_partial_coding
                        else
                        f"{key[0]}/{key[1]}/{key[2]}/{key[3]} 的编码体系、"
                        "版本或字段性质发生漂移；正式 draft assembly 将把"
                        "血缘无法闭合的标准化字段确定性降级为来源值，"
                        "降级后该链不再构成不一致的标准编码链。"
                        if severity == "warning"
                        else f"{key[0]}/{key[1]}/{key[2]}/{key[3]} 的编码体系、"
                        "版本或字段性质发生漂移。"
                    ),
                    locators=(item.locator for item in group),
                    variants=variants,
                )
            )
    by_project_domain: dict[
        tuple[str, str],
        list[FieldOccurrence],
    ] = defaultdict(list)
    for item in occurrences:
        by_project_domain[
            (item.record.project_id, item.domain.casefold())
        ].append(item)
    for (project_id, domain), group in sorted(by_project_domain.items()):
        reported = [
            item
            for item in group
            if item.canonical_role in {"ae.verbatim_term", "mh.verbatim_term"}
        ]
        meddra = [
            item
            for item in group
            if _coding_system(item) == "MedDRA"
            and item.field_kind == "standardized_coded"
        ]
        if not reported or not meddra:
            continue
        reported_keys = {item.source_field.casefold() for item in reported}
        anchored = any(
            reported_keys.intersection(
                str(value).strip().casefold()
                for value in _as_list(_lineage(item.mapping).get("source_fields"))
            )
            for item in meddra
        )
        if not anchored:
            findings.append(
                _finding(
                    category="coding_lineage",
                    severity="warning",
                    code="XJOB-AE-CODING-SOURCE-ANCHOR-MISSING",
                    title="报告术语与 MedDRA 编码链缺少来源锚点",
                    detail=(
                        f"{project_id}/{domain} 的代码-术语链未引用报告术语；"
                        "不能据此执行来源术语到标准术语的确定性追踪。"
                    ),
                    locators=(
                        item.locator for item in (*reported, *meddra)
                    ),
                    variants=(
                        "reported_term_not_in_source_fields",
                        "resolution=draft_assembly_cross_chunk_anchor",
                    ),
                )
            )
    rendered_inventory = []
    for system, entry in sorted(inventory.items()):
        rendered_inventory.append(
            {
                **entry,
                "support_fields": sorted(entry["support_fields"]),
                "versions": sorted(entry["versions"]),
                "field_kinds": sorted(entry["field_kinds"]),
            }
        )
    return findings, rendered_inventory


def _ae_mh_findings(
    occurrences: Sequence[FieldOccurrence],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for item in occurrences:
        domain = item.domain.casefold()
        if (
            domain == "ae"
            and item.role_family == "mh"
        ) or (
            domain == "mh"
            and item.role_family == "ae"
        ):
            findings.append(
                _finding(
                    category="ae_mh_boundary",
                    severity="error",
                    code="XJOB-AE-MH-DOMAIN-SWAP",
                    title="AE 与 MH 来源角色发生互换",
                    detail="AE 与 MH 报告事实必须保持来源域边界。",
                    locators=(item.locator,),
                    variants=(item.role,),
                )
            )
        token = _token(item.role)
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
            findings.append(
                _finding(
                    category="ae_mh_boundary",
                    severity="error",
                    code="XJOB-AE-SERIOUSNESS-SEVERITY-COLLAPSE",
                    title="AE 严重性与严重程度未分离",
                    detail=(
                        "SAE 严重性判定与 AE 严重程度/毒性分级不得合并"
                        "为同一正式角色。"
                    ),
                    locators=(item.locator,),
                    variants=(item.role,),
                )
            )
    return findings


def _derived_findings(
    occurrences: Sequence[FieldOccurrence],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    derived = [
        item for item in occurrences if item.field_kind == "deterministic_derived"
    ]
    available: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for item in occurrences:
        parsed = item.record.parsed_key
        available[
            (item.record.project_id, str(parsed["batch_id"]), item.domain.casefold())
        ].add(item.source_field.casefold())
    by_role: dict[tuple[str, str], list[FieldOccurrence]] = defaultdict(list)
    inventory: list[dict[str, Any]] = []
    for item in derived:
        lineage = _lineage(item.mapping)
        sources = [
            str(value).strip()
            for value in _as_list(lineage.get("source_fields"))
            if str(value).strip()
        ]
        formula = str(lineage.get("formula", "")).strip()
        confirmed = lineage.get("user_confirmed") is True
        parsed = item.record.parsed_key
        known = available[
            (item.record.project_id, str(parsed["batch_id"]), item.domain.casefold())
        ]
        missing_sources = sorted(
            source for source in sources if source.casefold() not in known
        )
        inventory.append(
            {
                "locator": item.locator,
                "source_fields": sources,
                "formula": formula,
                "user_confirmed": confirmed,
                "missing_source_fields": missing_sources,
            }
        )
        if not sources or not formula or not confirmed or missing_sources:
            findings.append(
                _finding(
                    category="derived_lineage",
                    severity="error",
                    code="XJOB-DERIVED-LINEAGE-INCOMPLETE",
                    title="确定性派生值缺少可复算血缘",
                    detail=(
                        "派生字段必须声明真实来源字段、明确公式、用户确认状态，"
                        "且来源字段必须存在于同一项目、批次和数据域。"
                    ),
                    locators=(item.locator,),
                    variants=(
                        f"source_fields={','.join(sources) or '<missing>'}",
                        f"formula={formula or '<missing>'}",
                        f"user_confirmed={confirmed}",
                        f"missing_sources={','.join(missing_sources) or '<none>'}",
                    ),
                )
            )
        by_role[(item.domain.casefold(), item.source_field.casefold())].append(item)
    for key, group in sorted(by_role.items()):
        formulas = {
            str(_lineage(item.mapping).get("formula", "")).strip()
            for item in group
        } - {""}
        if len(formulas) > 1:
            findings.append(
                _finding(
                    category="derived_lineage",
                    severity="warning",
                    code="XPROJ-DERIVED-FORMULA-VARIANT",
                    title="同名派生字段在不同候选中的公式不一致",
                    detail=(
                        f"{key[0]}.{key[1]} 可能存在项目特异计算规则；"
                        "不得未经数据字典或规则版本核验直接跨项目复用。"
                    ),
                    locators=(item.locator for item in group),
                    variants=formulas,
                )
            )
    return findings, inventory


def _field_has_partial_date_evidence(
    item: FieldOccurrence,
    evidence: Mapping[str, Any],
) -> bool:
    values: list[str] = []
    values.extend(str(value) for value in _as_list(evidence.get("representative_values")))
    values.extend(
        str(_as_mapping(value).get("value", ""))
        for value in _as_list(evidence.get("top_values"))
    )
    values.extend(str(value) for value in _as_list(evidence.get("anomaly_examples")))
    return any(
        PARTIAL_DATE_RE.search(value.strip())
        or bool(YEAR_MONTH_RE.fullmatch(value.strip()))
        for value in values
        if value.strip()
    )


def _date_findings(
    occurrences: Sequence[FieldOccurrence],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []
    evidence_cache: dict[str, dict[tuple[str, str], Mapping[str, Any]]] = {}
    for item in occurrences:
        evidence_cache.setdefault(
            item.record.job_id,
            _evidence_by_field(item.record.candidate),
        )
    for item in occurrences:
        if item.field_kind == "source_metadata":
            continue
        evidence = evidence_cache[item.record.job_id].get(
            (item.domain.casefold(), item.source_field.casefold()),
            {},
        )
        inferred_type = str(evidence.get("inferred_type", "")).casefold()
        looks_date = (
            inferred_type in {"date", "datetime"}
            or bool(DATE_FIELD_RE.search(item.role))
            or bool(DATE_FIELD_RE.search(item.source_field))
        )
        if not looks_date:
            continue
        reference = _as_mapping(item.mapping.get("standards_reference"))
        precision = str(reference.get("date_precision", "")).strip()
        exact = reference.get("supports_exact_date")
        partial_evidence = _field_has_partial_date_evidence(item, evidence)
        inventory.append(
            {
                "locator": item.locator,
                "inferred_type": inferred_type,
                "declared_precision": precision,
                "supports_exact_date": exact,
                "partial_value_evidence": partial_evidence,
            }
        )
        normalized_precision = _token(precision)
        safely_bounded = normalized_precision in {
            "year",
            "month",
            "partial",
            "unknown",
            "year.month",
        } or exact is False
        if partial_evidence and not safely_bounded:
            findings.append(
                _finding(
                    category="date_precision",
                    severity="error" if exact is True else "warning",
                    code=(
                        "XJOB-DATE-FALSE-EXACT"
                        if exact is True
                        else "XJOB-DATE-PRECISION-UNDECLARED"
                    ),
                    title=(
                        "部分日期被声明为精确日期"
                        if exact is True
                        else "部分日期证据未形成日期精度边界"
                    ),
                    detail=(
                        "来源值含未知或缺失日期组件；必须保留原文并声明精度或"
                        "上下界，不能直接用于精确访视窗、洗脱期或持续时间判断。"
                    ),
                    locators=(item.locator,),
                    variants=(
                        f"date_precision={precision or '<missing>'}",
                        f"supports_exact_date={exact}",
                    ),
                )
            )
    return findings, inventory


def _scale_class(item: FieldOccurrence) -> str:
    text = f"{item.role} {item.source_field}"
    if not SCALE_RE.search(text):
        return ""
    parts = set(_token(text).split("."))
    has_total = bool(
        {"total", "overall", "sum", "aggregate"}.intersection(parts)
        or re.search(r"(?:总分|合计)", text)
    )
    has_item = bool(
        {"item", "question", "subscore"}.intersection(parts)
        or any(re.fullmatch(r"q\d+", part) for part in parts)
        or re.search(r"(?:条目|题目|分项)", text)
    )
    has_score_number_merge = (
        "score" in parts
        and bool(
            {"number", "record", "procedure", "sequence"}.intersection(parts)
        )
    )
    if has_score_number_merge:
        return "ambiguous"
    if has_total and has_item:
        return "ambiguous"
    if has_total:
        return "total"
    if has_item:
        return "item"
    return "other"


def _scale_findings(
    occurrences: Sequence[FieldOccurrence],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str, str], list[tuple[FieldOccurrence, str]]] = defaultdict(
        list
    )
    for item in occurrences:
        classification = _scale_class(item)
        if not classification:
            continue
        parsed = item.record.parsed_key
        grouped[
            (item.record.project_id, str(parsed["batch_id"]), item.domain)
        ].append((item, classification))
        if classification == "ambiguous":
            findings.append(
                _finding(
                    category="scale_roles",
                    severity="error",
                    code="XJOB-SCALE-ROLE-AMBIGUOUS",
                    title="量表总分与条目角色未分离",
                    detail="同一来源字段不能同时被解释为量表总分和条目/分项。",
                    locators=(item.locator,),
                    variants=(item.role,),
                )
            )
    inventory: list[dict[str, Any]] = []
    for (project_id, batch_id, domain), group in sorted(grouped.items()):
        totals = [item for item, kind in group if kind == "total"]
        items = [item for item, kind in group if kind == "item"]
        source_totals = [
            item for item in totals if item.field_kind == "source_collected"
        ]
        inventory.append(
            {
                "project_id": project_id,
                "batch_id": batch_id,
                "domain": domain,
                "total_fields": sorted(item.source_field for item in totals),
                "item_fields": sorted(item.source_field for item in items),
                "other_scale_fields": sorted(
                    item.source_field
                    for item, kind in group
                    if kind in {"other", "ambiguous"}
                ),
                "source_total_fields": sorted(
                    item.source_field for item in source_totals
                ),
            }
        )
        if source_totals:
            findings.append(
                _finding(
                    category="scale_roles",
                    severity="observation",
                    code="XJOB-SCALE-SOURCE-TOTAL",
                    title="量表总分目前仅作为来源值保留",
                    detail=(
                        "来源总分可以展示；在版本、条目、分支、缺失计分规则和"
                        "公式未绑定前，不应声称为工作台复算结果。"
                    ),
                    locators=(item.locator for item in source_totals),
                    variants=(item.role for item in source_totals),
                )
            )
    return findings, inventory


def _semantic_variant_findings(
    occurrences: Sequence[FieldOccurrence],
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[FieldOccurrence]] = defaultdict(list)
    for item in occurrences:
        if item.field_kind != "source_metadata":
            groups[(item.domain.casefold(), item.source_field.casefold())].append(item)
    findings: list[dict[str, Any]] = []
    for key, group in sorted(groups.items()):
        projects = {item.record.project_id for item in group}
        signatures = {item.signature for item in group}
        if len(projects) > 1 and len(signatures) > 1:
            findings.append(
                _finding(
                    category="cross_project_semantic_variation",
                    severity="observation",
                    code="XPROJ-CLINICAL-ROLE-VARIANT",
                    title="同名临床字段在不同项目间存在角色差异",
                    detail=(
                        f"{key[0]}.{key[1]} 的差异不自动判错；该清单用于识别"
                        "项目特异语义、供应商差异或提示词过拟合。"
                    ),
                    locators=(item.locator for item in group),
                    variants=signatures,
                )
            )
    return findings


def audit_candidates(
    records: Sequence[CandidateRecord],
    *,
    source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not records:
        raise ValueError("no candidate records to audit")
    occurrences, job_summaries = _make_occurrences(records)
    findings: list[dict[str, Any]] = []
    technical_findings, technical_inventory = _technical_drift_findings(occurrences)
    coding_findings, coding_inventory = _coding_findings(occurrences)
    derived_findings, derived_inventory = _derived_findings(occurrences)
    date_findings, date_inventory = _date_findings(occurrences)
    scale_findings, scale_inventory = _scale_findings(occurrences)
    findings.extend(technical_findings)
    findings.extend(_cm_ip_findings(occurrences))
    findings.extend(_ae_mh_findings(occurrences))
    findings.extend(coding_findings)
    findings.extend(derived_findings)
    findings.extend(date_findings)
    findings.extend(scale_findings)
    findings.extend(_semantic_variant_findings(occurrences))
    for job in job_summaries:
        if job["missing_fields"] or job["unexpected_fields"] or job["duplicate_fields"]:
            findings.append(
                _finding(
                    category="field_coverage",
                    severity="error",
                    code="XJOB-FIELD-COVERAGE",
                    title="候选作业字段覆盖不完整",
                    detail=(
                        "候选映射与其冻结字段画像证据之间存在遗漏、越界或重复。"
                    ),
                    locators=(f"{job['project_id']}/{job['business_key']}",),
                    variants=(
                        *job["missing_fields"],
                        *job["unexpected_fields"],
                        *job["duplicate_fields"],
                    ),
                )
            )
    findings.sort(
        key=lambda item: (
            SEVERITY_ORDER[item["severity"]],
            item["category"],
            item["code"],
            item["finding_id"],
        )
    )
    by_project_domain: dict[tuple[str, str], dict[str, Any]] = {}
    for item in occurrences:
        key = (item.record.project_id, item.domain)
        entry = by_project_domain.setdefault(
            key,
            {
                "project_id": item.record.project_id,
                "domain": item.domain,
                "job_ids": set(),
                "fields": set(),
                "field_kinds": Counter(),
            },
        )
        entry["job_ids"].add(item.record.job_id)
        entry["fields"].add(item.source_field)
        entry["field_kinds"][item.field_kind] += 1
    domain_summaries = [
        {
            "project_id": entry["project_id"],
            "domain": entry["domain"],
            "job_count": len(entry["job_ids"]),
            "unique_field_count": len(entry["fields"]),
            "field_kinds": dict(sorted(entry["field_kinds"].items())),
        }
        for _, entry in sorted(by_project_domain.items())
    ]
    counts = Counter(item["severity"] for item in findings)
    observed_through = max(
        (record.updated_at or record.created_at for record in records),
        default="",
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source": dict(source or {}),
        "observed_through": observed_through,
        "summary": {
            "project_count": len({record.project_id for record in records}),
            "job_count": len(records),
            "domain_count": len(
                {(item.record.project_id, item.domain) for item in occurrences}
            ),
            "field_occurrence_count": len(occurrences),
            "error_count": counts["error"],
            "warning_count": counts["warning"],
            "observation_count": counts["observation"],
        },
        "domain_summaries": domain_summaries,
        "job_summaries": sorted(
            job_summaries,
            key=lambda item: (
                item["project_id"],
                item["domain"],
                item["chunk_index"],
                item["business_key"],
            ),
        ),
        "inventories": {
            "technical_roles": technical_inventory,
            "coding_lineage": coding_inventory,
            "derived_lineage": sorted(
                derived_inventory,
                key=lambda item: item["locator"],
            ),
            "date_precision": sorted(
                date_inventory,
                key=lambda item: item["locator"],
            ),
            "scale_roles": sorted(
                scale_inventory,
                key=lambda item: (
                    item["project_id"],
                    item["domain"],
                    item["batch_id"],
                ),
            ),
        },
        "findings": findings,
    }
    payload["report_sha256"] = _json_hash(payload)
    return payload


def render_markdown(report: Mapping[str, Any]) -> str:
    summary = _as_mapping(report.get("summary"))
    lines = [
        "# 医学监查字段映射候选跨作业审计",
        "",
        "> 本报告是只读观察层，不替代完整 mapping draft 的正式语义质量门，"
        "也不自动批准、拒绝或激活任何映射。",
        "",
        "## 审计摘要",
        "",
        "| 项目 | 作业 | 项目-数据域 | 字段出现次数 | 错误 | 警告 | 观察 |",
        "|---:|---:|---:|---:|---:|---:|---:|",
        (
            f"| {summary.get('project_count', 0)} | {summary.get('job_count', 0)} "
            f"| {summary.get('domain_count', 0)} "
            f"| {summary.get('field_occurrence_count', 0)} "
            f"| {summary.get('error_count', 0)} "
            f"| {summary.get('warning_count', 0)} "
            f"| {summary.get('observation_count', 0)} |"
        ),
        "",
        f"- 观察截止：`{report.get('observed_through') or '未提供'}`",
        f"- 报告 SHA-256：`{report.get('report_sha256', '')}`",
        "",
        "## 项目与数据域覆盖",
        "",
        "| 项目 | 数据域 | 作业数 | 唯一字段数 | 字段性质 |",
        "|---|---|---:|---:|---|",
    ]
    for item in _as_list(report.get("domain_summaries")):
        kinds = ", ".join(
            f"{key}:{value}"
            for key, value in _as_mapping(item.get("field_kinds")).items()
        )
        lines.append(
            f"| {item.get('project_id', '')} | {item.get('domain', '')} "
            f"| {item.get('job_count', 0)} | {item.get('unique_field_count', 0)} "
            f"| {kinds or '-'} |"
        )
    lines.extend(["", "## 发现", ""])
    findings = _as_list(report.get("findings"))
    if not findings:
        lines.append("未发现跨作业一致性问题或需单列观察项。")
    else:
        labels = {"error": "错误", "warning": "警告", "observation": "观察"}
        for severity in ("error", "warning", "observation"):
            current = [item for item in findings if item.get("severity") == severity]
            if not current:
                continue
            lines.extend([f"### {labels[severity]}（{len(current)}）", ""])
            for item in current:
                lines.append(
                    f"- **{item.get('code')}｜{item.get('title')}**："
                    f"{item.get('detail')}"
                )
                variants = _as_list(item.get("variants"))
                locators = _as_list(item.get("locators"))
                if variants:
                    lines.append(f"  - 变体：`{'`、`'.join(str(v) for v in variants)}`")
                if locators:
                    preview = locators[:8]
                    suffix = f"；另 {len(locators) - 8} 处" if len(locators) > 8 else ""
                    lines.append(
                        f"  - 定位：`{'`、`'.join(str(v) for v in preview)}`{suffix}"
                    )
            lines.append("")
    lines.extend(["## 编码血缘概览", ""])
    coding = _as_list(_as_mapping(report.get("inventories")).get("coding_lineage"))
    if not coding:
        lines.append("本次候选未声明 MedDRA、WHO Drug、CTCAE 或其他标准编码。")
    else:
        lines.extend(
            [
                "| 体系 | 字段数 | 完整血缘 | 不完整血缘 | 支撑字段 | 版本/版本字段 | 字段性质 |",
                "|---|---:|---:|---:|---:|---|---|",
            ]
        )
        for item in coding:
            lines.append(
                f"| {item.get('coding_system')} | {item.get('field_count')} "
                f"| {item.get('complete_lineage_count')} "
                f"| {item.get('incomplete_lineage_count')} "
                f"| {item.get('support_field_count', 0)} "
                f"| {', '.join(item.get('versions', [])) or '-'} "
                f"| {', '.join(item.get('field_kinds', [])) or '-'} |"
            )
    lines.extend(
        [
            "",
            "## 使用边界",
            "",
            "- 错误表示候选层已观察到违反稳定不变量的证据，不能直接汇总为正式映射。",
            "- 警告表示血缘不足或跨项目差异，需要在 draft 汇总时复核。",
            "- 带 `resolution=draft_assembly_*` 标记的警告表示正式 draft assembly 会"
            "确定性隔离或降级该形状；候选审计据此不再计为错误，但正式映射仍须"
            "通过服务端完整语义质量门。",
            "- 带 `resolution=formal_semantic_quality_*` 标记的警告表示候选层只观察到"
            "部分能力可用；draft 不会升级缺失血缘，正式语义质量门必须将相应能力"
            "限制或阻断。",
            "- 观察项用于提示项目特异性，不自动判定为错误。",
            "- 正式确认与激活仍必须调用服务端完整 draft 语义质量门。",
            "",
        ]
    )
    return "\n".join(lines)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--sqlite", type=Path, help="monitoring_ai.sqlite3 path")
    source.add_argument("--candidate-json", type=Path, help="exported candidate JSON")
    parser.add_argument("--prompt-version", action="append", default=[])
    parser.add_argument("--project-id", action="append", default=[])
    parser.add_argument("--job-status", action="append", default=[])
    parser.add_argument("--candidate-status", action="append", default=[])
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-markdown", type=Path)
    parser.add_argument(
        "--fail-on",
        choices=("none", "error", "warning"),
        default="none",
        help="optional CI exit threshold; report generation always completes",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.sqlite:
        job_statuses = args.job_status or list(DEFAULT_JOB_STATUSES)
        candidate_statuses = args.candidate_status or list(
            DEFAULT_CANDIDATE_STATUSES
        )
        records = load_candidate_sqlite(
            args.sqlite,
            prompt_versions=args.prompt_version,
            project_ids=args.project_id,
            job_statuses=job_statuses,
            candidate_statuses=candidate_statuses,
        )
        source = {
            "kind": "sqlite_read_only",
            "path": str(args.sqlite.resolve()),
            "prompt_versions": sorted(args.prompt_version),
            "project_ids": sorted(args.project_id),
            "job_statuses": sorted(job_statuses),
            "candidate_statuses": sorted(candidate_statuses),
        }
    else:
        records = load_candidate_json(args.candidate_json)
        source = {
            "kind": "candidate_json",
            "path": str(args.candidate_json.resolve()),
        }
    report = audit_candidates(records, source=source)
    json_text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    markdown_text = render_markdown(report)
    if args.output_json:
        _write_text(args.output_json, json_text)
    if args.output_markdown:
        _write_text(args.output_markdown, markdown_text)
    if not args.output_json and not args.output_markdown:
        print(markdown_text)
    summary = _as_mapping(report.get("summary"))
    if args.fail_on == "error" and summary.get("error_count", 0):
        return 2
    if args.fail_on == "warning" and (
        summary.get("error_count", 0) or summary.get("warning_count", 0)
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
