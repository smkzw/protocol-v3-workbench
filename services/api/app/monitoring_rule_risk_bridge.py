from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any, Iterable, Mapping

from packages.contracts.workbench_contracts.models import (
    RiskCase,
    RiskEvidenceFragmentSnapshot,
    RiskSeverity,
    RiskStatus,
)

from .monitoring_batch_rule_runner import BatchRuleCandidate, BatchRuleRunResult
from .medical_monitoring_risk_taxonomy import (
    MedicalRiskCategoryDefinition,
    classify_rule_risk_category,
)


_STUDY_TREATMENT_DOMAINS = frozenset({"EX", "EC", "DA", "IP"})
_CONFIDENCE_VALUES = {
    "low": 0.40,
    "medium": 0.65,
    "high": 0.85,
    "deterministic": 1.00,
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
class MonitoringRuleRiskBridgeError(ValueError):
    pass


class MonitoringRuleRiskBridge:
    @staticmethod
    def convert(
        result: BatchRuleRunResult,
        *,
        engine_version: str,
        source_revision: str,
        created_at: datetime | None = None,
    ) -> tuple[RiskCase, ...]:
        """Convert matched deterministic-rule candidates into review-only risks.

        Diagnostics remain on ``BatchRuleRunResult`` and are intentionally not
        converted. An empty tuple therefore means only "no matched candidates
        were bridged"; it is not a declaration that the batch is risk-free.
        """

        source_revision_value = _required_text(
            source_revision,
            "source_revision",
        )
        engine_version_value = _required_text(engine_version, "engine_version")
        created_at_value = created_at or datetime.now(timezone.utc)
        if not isinstance(created_at_value, datetime):
            raise MonitoringRuleRiskBridgeError("created_at must be a datetime")

        risks = [
            _candidate_to_risk(
                result,
                candidate,
                source_revision=source_revision_value,
                engine_version=engine_version_value,
                created_at=created_at_value,
            )
            for candidate in result.candidates
        ]
        return tuple(
            sorted(
                risks,
                key=lambda item: (item.risk_key, item.risk_instance_id),
            )
        )


def _candidate_to_risk(
    result: BatchRuleRunResult,
    candidate: BatchRuleCandidate,
    *,
    source_revision: str,
    engine_version: str,
    created_at: datetime,
) -> RiskCase:
    _validate_candidate_binding(result, candidate)

    domain = _required_text(candidate.current_domain, "current_domain").upper()
    subject_id = _required_text(candidate.subject_id, "subject_id")
    business_key = _required_text(
        candidate.current_business_key,
        "current_business_key",
    )
    episode_key = f"{domain}:{business_key}"
    try:
        category = classify_rule_risk_category(
            rule_key=candidate.rule_key,
            current_domain=domain,
            evaluation=_mapping(candidate.evaluation),
        )
    except ValueError as exc:
        raise MonitoringRuleRiskBridgeError(str(exc)) from exc
    candidate_label = _candidate_label(category.label)
    risk_type = (
        f"{category.label}规则候选"
        if category.label.endswith("复核")
        else f"{category.label}规则复核候选"
    )
    evidence = _mapping(candidate.evaluation.get("evidence"))
    protocol_source = _mapping(candidate.evaluation.get("protocol_source"))
    evidence_span_ids = _evidence_span_ids(evidence, protocol_source)
    raw_record = _public_raw_record(
        _mapping(_mapping(evidence.get("current_record")).get("raw_data"))
    )
    previous_record = _public_raw_record(
        _mapping(_mapping(evidence.get("previous_record")).get("raw_data"))
    )
    evidence_summary = _evidence_summary(candidate, raw_record)

    stable_payload = {
        "project_id": result.project_id,
        "rule_key": candidate.rule_key,
        "scope_type": "subject",
        "scope_id": subject_id,
        "episode_key": episode_key,
    }
    risk_key_digest = _digest(stable_payload)
    risk_key = f"riskkey_{risk_key_digest[:24]}"
    instance_payload = {
        "risk_key": risk_key,
        "batch_id": result.batch_id,
        "batch_version": result.batch_version,
        "mapping_revision": result.mapping_revision,
        "rule_pack_id": result.rule_pack_id,
        "rule_revision_id": candidate.rule_revision_id,
        "candidate_id": candidate.candidate_id,
        "source_revision": source_revision,
        "engine_version": engine_version,
        "evidence_span_ids": evidence_span_ids,
        "evidence_summary": evidence_summary,
    }
    instance_digest = _digest(instance_payload)
    lineage_fragment = {
        "candidate_id": candidate.candidate_id,
        "batch_id": result.batch_id,
        "batch_version": result.batch_version,
        "mapping_revision": result.mapping_revision,
        "rule_pack_id": result.rule_pack_id,
        "rule_revision_id": candidate.rule_revision_id,
        "rule_key": candidate.rule_key,
        "engine_version": engine_version,
        "source_revision": source_revision,
        "current_domain": domain,
        "current_business_key": business_key,
        "raw_value_summary": evidence_summary,
        "current_raw_data": raw_record,
        "previous_raw_data": previous_record or None,
        "protocol_source_text": str(protocol_source.get("source_text") or "").strip(),
        "medical_review_candidate_only": True,
    }
    primary_locator = (
        evidence_span_ids[0]
        if evidence_span_ids
        else f"batch:{result.batch_id}:candidate:{candidate.candidate_id}"
    )

    severity = _severity(candidate.severity)
    return RiskCase(
        risk_id=f"risk_{instance_digest[:24]}",
        risk_key=risk_key,
        risk_instance_id=f"riskinst_{instance_digest[:24]}",
        project_id=result.project_id,
        module="medical_monitoring",
        risk_type=risk_type,
        primary_category=category.code.value,
        tags=_tags(category, domain),
        title=f"{subject_id} {candidate_label}候选",
        subject_id=subject_id,
        site_id=_site_id(raw_record),
        scope_type="subject",
        scope_id=subject_id,
        aggregation_scope="episode",
        episode_key=episode_key,
        severity=severity,
        inspection_priority=_inspection_priority(severity),
        action_priority="medical_review_required",
        confidence=_confidence(candidate.confidence),
        status=RiskStatus.IN_REVIEW,
        source_batch_id=result.batch_id,
        source_revision=source_revision,
        rule_profile_revision=result.rule_pack_id,
        engine_version=engine_version,
        batch_delta="unclassified",
        rule_id=candidate.rule_key,
        evidence_span_ids=evidence_span_ids,
        evidence_snapshots=[
            RiskEvidenceFragmentSnapshot(
                locator=primary_locator,
                source_revision=source_revision,
                captured_at=created_at,
                fragment=lineage_fragment,
            )
        ],
        rationale=(
            f"原始数据触发摘要（待医学复核）：{evidence_summary}。"
            "该结果仅表示已发布规则的确定性条件命中，不代表已确认诊断、"
            "漏报、方案违背或需发出 Query。"
        ),
        recommended_action=(
            "请结合原始记录、方案条款及受试者上下文完成医学复核，"
            "再决定是否需要处置或形成 Query。"
        ),
        owner="medical_manager",
        created_at=created_at,
    )


def _validate_candidate_binding(
    result: BatchRuleRunResult,
    candidate: BatchRuleCandidate,
) -> None:
    expected = {
        "project_id": (result.project_id, candidate.project_id),
        "batch_id": (result.batch_id, candidate.batch_id),
        "batch_version": (result.batch_version, candidate.batch_version),
        "mapping_revision": (result.mapping_revision, candidate.mapping_revision),
        "rule_pack_id": (result.rule_pack_id, candidate.rule_pack_id),
    }
    mismatches = [
        field_name
        for field_name, (run_value, candidate_value) in expected.items()
        if run_value != candidate_value
    ]
    if mismatches:
        raise MonitoringRuleRiskBridgeError(
            "candidate lineage does not match its batch rule result: "
            + ", ".join(mismatches)
        )
    if candidate.rule_revision_id not in result.rule_revision_ids:
        raise MonitoringRuleRiskBridgeError(
            "candidate rule revision is outside the executed rule pack"
        )
    evaluation = _mapping(candidate.evaluation)
    if evaluation.get("matched") is not True:
        raise MonitoringRuleRiskBridgeError(
            "only matched candidates may be converted to RiskCase"
        )
    evidence = _mapping(evaluation.get("evidence"))
    if evidence.get("medical_review_candidate_only") is not True:
        raise MonitoringRuleRiskBridgeError(
            "candidate is missing the medical-review-only evidence boundary"
        )


def _tags(
    category: MedicalRiskCategoryDefinition,
    domain: str,
) -> list[str]:
    values = {
        "medical_review_candidate",
        "deterministic_rule",
        "cfdi_review_candidate",
        category.code.value,
        f"source_domain:{domain.lower()}",
    }
    if category.safety_pv_flag:
        values.add("safety_pv")
    if domain == "CM":
        values.add("non_study_concomitant_medication")
    elif domain in _STUDY_TREATMENT_DOMAINS:
        values.add("study_treatment_record")
    return sorted(values)


def _candidate_label(category_label: str) -> str:
    return category_label if category_label.endswith("复核") else f"{category_label}复核"


def _severity(value: str) -> RiskSeverity:
    try:
        return RiskSeverity(str(value).strip().lower())
    except ValueError as exc:
        raise MonitoringRuleRiskBridgeError(
            f"unsupported candidate severity: {value}"
        ) from exc


def _confidence(value: str) -> float:
    normalized = str(value or "").strip().lower()
    if normalized not in _CONFIDENCE_VALUES:
        raise MonitoringRuleRiskBridgeError(
            f"unsupported candidate confidence: {value}"
        )
    return _CONFIDENCE_VALUES[normalized]


def _inspection_priority(severity: RiskSeverity) -> str:
    return {
        RiskSeverity.CRITICAL: "critical",
        RiskSeverity.HIGH: "high",
        RiskSeverity.MEDIUM: "medium",
        RiskSeverity.LOW: "routine",
    }[severity]


def _site_id(raw_record: Mapping[str, Any]) -> str | None:
    for field_name in (
        "SITEID",
        "SITE_ID",
        "CENTERID",
        "CENTER_ID",
        "STUDYSITE",
        "中心编号",
    ):
        value = raw_record.get(field_name)
        if value not in (None, ""):
            normalized = str(value).strip()
            if normalized:
                return normalized
    return None


def _evidence_summary(
    candidate: BatchRuleCandidate,
    raw_record: Mapping[str, Any],
) -> str:
    summary = " ".join(str(candidate.evidence_summary or "").split())
    if summary:
        return summary
    visible = [
        f"{key}={_display_scalar(value)}"
        for key, value in sorted(raw_record.items())
        if value not in (None, "", [], {})
    ]
    return "；".join(visible[:12]) or "原始记录满足规则条件"


def _public_raw_record(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): item
        for key, item in value.items()
        if not str(key).startswith("__")
        and str(key).lower()
        not in {
            "source_locator",
            "source_locators",
            "evidence_span_ids",
            "locator",
        }
    }


def _evidence_span_ids(
    evidence: Mapping[str, Any],
    protocol_source: Mapping[str, Any],
) -> list[str]:
    locators: list[Any] = []
    current = _mapping(evidence.get("current_record"))
    previous = _mapping(evidence.get("previous_record"))
    locators.extend(_iterable(current.get("source_locators")))
    locators.extend(_iterable(previous.get("source_locators")))

    for query in _iterable(evidence.get("missing_record_queries")):
        query_value = _mapping(query)
        locators.extend(_iterable(query_value.get("matching_source_locators")))
        locators.extend(_iterable(query_value.get("searched_source_locators")))

    if not locators:
        for records in _mapping(evidence.get("related_records")).values():
            for record in _iterable(records):
                locators.extend(
                    _iterable(_mapping(record).get("source_locators"))
                )

    source_locator = str(protocol_source.get("source_locator") or "").strip()
    if source_locator:
        source_entry_id = str(
            protocol_source.get("source_entry_id") or "protocol"
        ).strip()
        locators.append(f"protocol:{source_entry_id}:{source_locator}")

    values: list[str] = []
    seen: set[str] = set()
    for locator in locators:
        locator_value = _locator_id(locator)
        if locator_value and locator_value not in seen:
            seen.add(locator_value)
            values.append(locator_value)
    return values


def _locator_id(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, Mapping):
        return _canonical_json(value)
    source_entry_id = str(value.get("source_entry_id") or "").strip()
    source_hash_value = value.get("source_content_sha256")
    if source_hash_value in (None, ""):
        source_hash = ""
    elif not isinstance(source_hash_value, str) or not _SHA256_RE.fullmatch(
        source_hash_value
    ):
        raise MonitoringRuleRiskBridgeError(
            "source_content_sha256 must be an exact lowercase SHA-256"
        )
    else:
        source_hash = source_hash_value
    sheet = str(value.get("sheet") or "").strip()
    row = value.get("row")
    column = str(value.get("column") or "").strip()
    if source_entry_id or source_hash or sheet or row not in (None, "") or column:
        parts = ["source"]
        if source_entry_id:
            parts.extend(("entry", source_entry_id))
        if source_hash:
            parts.extend(("sha256", source_hash))
        if sheet:
            parts.extend(("sheet", sheet))
        if row not in (None, ""):
            parts.extend(("row", str(row)))
        if column:
            parts.extend(("column", column))
        return ":".join(parts)
    return _canonical_json(value)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _iterable(value: Any) -> Iterable[Any]:
    if value in (None, "", [], {}):
        return ()
    if isinstance(value, (list, tuple)):
        return value
    return (value,)


def _display_scalar(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        return _canonical_json(value)
    return str(value)


def _required_text(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise MonitoringRuleRiskBridgeError(f"{field_name} is required")
    return normalized


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _digest(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()
