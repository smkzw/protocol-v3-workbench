from __future__ import annotations

from datetime import datetime
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

from .monitoring_ai_contracts import (
    MonitoringAiCandidate,
    MonitoringAiCandidateStatus,
    MonitoringAiClaimKind,
    MonitoringAiEvidence,
    MonitoringAiTaskType,
)
from .medical_monitoring_risk_taxonomy import (
    MedicalRiskCategoryDefinition,
    classify_ai_risk_category,
)


_STUDY_TREATMENT_DOMAINS = frozenset({"EX", "EC", "DA", "IP"})
_SUBJECT_FIELDS = (
    "USUBJID",
    "SUBJID",
    "SUBJECT_ID",
    "SUBJECTID",
    "受试者编号",
)
_SITE_FIELDS = (
    "SITEID",
    "SITE_ID",
    "CENTERID",
    "CENTER_ID",
    "STUDYSITE",
    "中心编号",
)
_NEGATION_MARKERS = (
    "不代表",
    "不得",
    "不能",
    "不可",
    "尚不能",
    "未能",
    "无需",
    "不应",
    "并非",
    "not ",
    "cannot",
    "must not",
    "does not",
)
_DEFINITIVE_PATTERNS = (
    re.compile(r"(?:AE|MH|不良事件|病史).{0,8}漏报", re.IGNORECASE),
    re.compile(r"(?:漏报).{0,8}(?:AE|MH|不良事件|病史)", re.IGNORECASE),
    re.compile(r"(?:确定|确认|判定|属于|构成|存在|发生|提示|疑似|可能存在)"
               r".{0,12}(?:方案违背|protocol\s+deviation)", re.IGNORECASE),
    re.compile(r"(?:导致|引起|造成|归因于|因果关系明确|caused\s+by|"
               r"attributable\s+to)", re.IGNORECASE),
    re.compile(r"(?:应|需|必须|建议|立即).{0,8}(?:发出|提出|生成)?\s*query",
               re.IGNORECASE),
    re.compile(r"(?:可直接|自动).{0,8}(?:形成|生成|发出)\s*query", re.IGNORECASE),
)


class MonitoringAiRiskBridgeError(ValueError):
    pass


class MonitoringAiRiskBridge:
    @staticmethod
    def convert(
        candidate: MonitoringAiCandidate,
        *,
        batch_id: str,
        source_revision: str,
        rule_pack_revision: str,
        engine_version: str,
        created_at: datetime,
    ) -> tuple[RiskCase, ...]:
        """Convert one AI cross-table clue into a review-only risk.

        Rejected and superseded candidates are intentionally ignored. Every
        other validation failure rejects the whole conversion; an empty result
        never means that the source batch is risk-free.
        """

        if not isinstance(candidate, MonitoringAiCandidate):
            raise MonitoringAiRiskBridgeError(
                "candidate must be a MonitoringAiCandidate"
            )
        if candidate.status in {
            MonitoringAiCandidateStatus.REJECTED,
            MonitoringAiCandidateStatus.SUPERSEDED,
        }:
            return ()
        if candidate.status not in {
            MonitoringAiCandidateStatus.PROPOSED,
            MonitoringAiCandidateStatus.ACCEPTED,
        }:
            raise MonitoringAiRiskBridgeError(
                f"unsupported candidate status: {candidate.status}"
            )
        if candidate.task_type is not MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS:
            raise MonitoringAiRiskBridgeError(
                "only CROSS_TABLE_CLUE_SYNTHESIS candidates may enter the risk ledger"
            )

        batch_id_value = _required_text(batch_id, "batch_id")
        source_revision_value = _required_text(
            source_revision,
            "source_revision",
        )
        rule_pack_revision_value = _required_text(
            rule_pack_revision,
            "rule_pack_revision",
        )
        engine_version_value = _required_text(engine_version, "engine_version")
        if not isinstance(created_at, datetime):
            raise MonitoringAiRiskBridgeError("created_at must be a datetime")
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise MonitoringAiRiskBridgeError("created_at must include a timezone")

        payload = _mapping(candidate.structured_payload)
        subject_id = _subject_id(payload)
        selected_evidence = _validate_evidence_graph(candidate, payload)
        domains = _actual_domains(selected_evidence)
        _validate_declared_domains(payload, domains)
        _validate_subject_binding(subject_id, selected_evidence)
        _validate_language_boundary(candidate)

        all_locators = _all_locators(candidate.evidence)
        stable_evidence_identity = _stable_evidence_identity(selected_evidence)
        stable_payload = {
            "project_id": candidate.project_id,
            "subject_id": subject_id,
            "evidence_source_identity": stable_evidence_identity,
        }
        risk_key_digest = _digest(stable_payload)
        risk_key = f"riskkey_{risk_key_digest[:24]}"
        instance_payload = {
            "risk_key": risk_key,
            "candidate_id": candidate.candidate_id,
            "job_id": candidate.job_id,
            "input_revision_sha256": candidate.input_revision_sha256,
            "prompt_version": candidate.prompt_version,
            "batch_id": batch_id_value,
            "source_revision": source_revision_value,
            "rule_pack_revision": rule_pack_revision_value,
            "engine_version": engine_version_value,
            "evidence": [
                {
                    "source_entry_id": item.source_entry_id,
                    "source_content_sha256": item.source_content_sha256,
                    "locator": item.locator,
                }
                for item in candidate.evidence
            ],
        }
        instance_digest = _digest(instance_payload)
        primary_locator = (
            all_locators[0]
            if all_locators
            else f"monitoring-ai:{candidate.job_id}:{candidate.candidate_id}"
        )
        try:
            category = classify_ai_risk_category(
                explicit_code=payload.get("risk_category_code"),
                evidence_domains=domains,
            )
        except ValueError as exc:
            raise MonitoringAiRiskBridgeError(str(exc)) from exc
        domain_label = "/".join(sorted(domains))
        facts = _claim_texts(candidate, MonitoringAiClaimKind.FACT)
        inferences = _claim_texts(candidate, MonitoringAiClaimKind.INFERENCE)
        data_gaps = _claim_texts(candidate, MonitoringAiClaimKind.DATA_GAP)
        recommendations = _claim_texts(
            candidate,
            MonitoringAiClaimKind.RECOMMENDATION,
        )
        observations = _string_list(payload.get("observations"))
        temporal_relationships = _string_list(
            payload.get("temporal_relationships")
        )
        payload_gaps = _string_list(payload.get("data_gaps"))
        recommended_review = str(payload.get("recommended_review") or "").strip()
        raw_summaries = _raw_evidence_summaries(selected_evidence)
        rationale = _rationale(
            raw_summaries=raw_summaries,
            facts=facts,
            observations=observations,
            inferences=inferences,
            temporal_relationships=temporal_relationships,
            data_gaps=_unique((*data_gaps, *payload_gaps)),
        )
        recommended_action = _recommended_action(
            recommended_review,
            recommendations,
        )
        confidence = min(
            0.65,
            max((claim.confidence for claim in candidate.claims), default=0.5),
        )
        evidence_fragment = {
            "candidate_id": candidate.candidate_id,
            "candidate_status": candidate.status.value,
            "job_id": candidate.job_id,
            "input_revision_sha256": candidate.input_revision_sha256,
            "prompt_version": candidate.prompt_version,
            "batch_id": batch_id_value,
            "source_revision": source_revision_value,
            "rule_pack_revision": rule_pack_revision_value,
            "engine_version": engine_version_value,
            "subject_id": subject_id,
            "domains": sorted(domains),
            "risk_category_code": category.code.value,
            "structured_payload": payload,
            "facts": facts,
            "inferences": inferences,
            "data_gaps": _unique((*data_gaps, *payload_gaps)),
            "recommendations": recommendations,
            "evidence": [_evidence_snapshot(item) for item in candidate.evidence],
            "medical_review_candidate_only": True,
        }

        risk = RiskCase(
            risk_id=f"risk_{instance_digest[:24]}",
            risk_key=risk_key,
            risk_instance_id=f"riskinst_{instance_digest[:24]}",
            project_id=candidate.project_id,
            module="medical_monitoring",
            risk_type="AI跨域医学复核线索",
            primary_category=category.code.value,
            tags=_tags(domains, category),
            title=f"{subject_id} {domain_label} 跨域医学复核线索",
            subject_id=subject_id,
            site_id=_site_id(candidate.evidence),
            scope_type="subject",
            scope_id=subject_id,
            aggregation_scope="episode",
            episode_key=f"ai-clue:{risk_key_digest[:20]}",
            severity=RiskSeverity.MEDIUM,
            inspection_priority="medium",
            action_priority="medical_review_required",
            confidence=confidence,
            status=RiskStatus.IN_REVIEW,
            source_batch_id=batch_id_value,
            source_revision=source_revision_value,
            rule_profile_revision=rule_pack_revision_value,
            engine_version=engine_version_value,
            batch_delta="unclassified",
            rule_id="monitoring_ai.cross_table_clue_synthesis",
            evidence_span_ids=all_locators,
            evidence_snapshots=[
                RiskEvidenceFragmentSnapshot(
                    locator=primary_locator,
                    source_revision=source_revision_value,
                    captured_at=created_at,
                    fragment=evidence_fragment,
                )
            ],
            rationale=rationale,
            recommended_action=recommended_action,
            owner="medical_manager",
            created_at=created_at,
        )
        return (risk,)


def _validate_evidence_graph(
    candidate: MonitoringAiCandidate,
    payload: Mapping[str, Any],
) -> tuple[MonitoringAiEvidence, ...]:
    evidence_ids = _string_list(payload.get("evidence_ids"))
    if not evidence_ids or len(evidence_ids) != len(set(evidence_ids)):
        raise MonitoringAiRiskBridgeError(
            "cross-table clue requires unique structured evidence_ids"
        )
    by_id = {item.evidence_id: item for item in candidate.evidence}
    if any(evidence_id not in by_id for evidence_id in evidence_ids):
        raise MonitoringAiRiskBridgeError(
            "structured evidence graph references missing evidence"
        )
    selected_ids = set(evidence_ids)
    if any(
        not set(claim.evidence_ids).issubset(selected_ids)
        for claim in candidate.claims
    ):
        raise MonitoringAiRiskBridgeError(
            "claim evidence is outside the structured cross-table evidence graph"
        )
    selected = tuple(by_id[evidence_id] for evidence_id in evidence_ids)
    if any(
        item.input_revision_sha256 != candidate.input_revision_sha256
        for item in selected
    ):
        raise MonitoringAiRiskBridgeError(
            "candidate evidence belongs to another input revision"
        )
    return selected


def _actual_domains(
    evidence: Iterable[MonitoringAiEvidence],
) -> frozenset[str]:
    domains: set[str] = set()
    for item in evidence:
        raw_fields = _mapping(item.raw_fields)
        if raw_fields.get("evidence_kind") != "original_data":
            continue
        direct_domain = str(raw_fields.get("domain") or "").strip().upper()
        if direct_domain:
            domains.add(direct_domain)
        fields = raw_fields.get("fields")
        if isinstance(fields, list):
            for field in fields:
                field_value = _mapping(field)
                if str(field_value.get("field") or "").strip().upper() != "DOMAIN":
                    continue
                value = str(field_value.get("value") or "").strip().upper()
                if value and not value.startswith("<"):
                    domains.add(value)
        match = re.search(
            r"(?:^|:)sheet:([^:/]+)",
            item.locator,
            re.IGNORECASE,
        )
        if match:
            domains.add(match.group(1).strip().upper())
    if len(domains) < 2:
        raise MonitoringAiRiskBridgeError(
            "cross-table clue requires original data from at least two real domains"
        )
    return frozenset(domains)


def _validate_declared_domains(
    payload: Mapping[str, Any],
    actual_domains: frozenset[str],
) -> None:
    declared = frozenset(
        value.upper() for value in _string_list(payload.get("domains"))
    )
    if declared != actual_domains:
        raise MonitoringAiRiskBridgeError(
            "declared domains do not match the original-data evidence domains"
        )


def _subject_id(payload: Mapping[str, Any]) -> str:
    value = _required_text(payload.get("subject_id"), "subject_id")
    if value.startswith("<") or value.endswith(">"):
        raise MonitoringAiRiskBridgeError(
            "subject_id placeholder cannot enter the risk ledger"
        )
    return value


def _validate_subject_binding(
    subject_id: str,
    evidence: Iterable[MonitoringAiEvidence],
) -> None:
    observed: set[str] = set()
    for item in evidence:
        for field_name, value in _raw_values(item):
            if field_name.upper() in _SUBJECT_FIELDS and value not in (None, ""):
                observed.add(str(value).strip())
    if observed and observed != {subject_id}:
        raise MonitoringAiRiskBridgeError(
            "subject_id conflicts with original-data evidence"
        )


def _validate_language_boundary(candidate: MonitoringAiCandidate) -> None:
    payload = _mapping(candidate.structured_payload)
    text = "\n".join(
        (
            candidate.title,
            candidate.text,
            *(
                f"{claim.text}\n{claim.user_action}"
                for claim in candidate.claims
            ),
            *_string_list(payload.get("observations")),
            *_string_list(payload.get("temporal_relationships")),
            *_string_list(payload.get("data_gaps")),
            str(payload.get("recommended_review") or ""),
        )
    )
    for sentence in re.split(r"[\n。！？；;，,]+", text):
        normalized = sentence.strip()
        if not normalized:
            continue
        lowered = normalized.casefold()
        if any(marker in lowered for marker in _NEGATION_MARKERS):
            continue
        if any(pattern.search(normalized) for pattern in _DEFINITIVE_PATTERNS):
            raise MonitoringAiRiskBridgeError(
                "candidate contains an unauthorized definitive medical conclusion"
            )


def _raw_evidence_summaries(
    evidence: Iterable[MonitoringAiEvidence],
) -> tuple[str, ...]:
    summaries: list[str] = []
    for item in evidence:
        visible_fields = [
            f"{field_name}={_display(value)}"
            for field_name, value in _raw_values(item)
            if field_name.lower()
            not in {
                "evidence_kind",
                "source_locator",
                "source_locators",
                "locator",
            }
            and value not in (None, "", [], {})
        ]
        if visible_fields:
            content = "；".join(visible_fields[:16])
        else:
            content = " ".join(item.quote.split())
        if content:
            summaries.append(content)
    if not summaries:
        raise MonitoringAiRiskBridgeError(
            "cross-table clue is missing visible original values"
        )
    return _unique(summaries)


def _raw_values(evidence: MonitoringAiEvidence) -> tuple[tuple[str, Any], ...]:
    raw_fields = _mapping(evidence.raw_fields)
    values: list[tuple[str, Any]] = []
    fields = raw_fields.get("fields")
    if isinstance(fields, list):
        for item in fields:
            field = _mapping(item)
            name = str(field.get("field") or "").strip()
            if name:
                values.append((name, field.get("value")))
    for key, value in raw_fields.items():
        if key not in {"fields", "evidence_kind"}:
            values.append((str(key), value))
    return tuple(values)


def _rationale(
    *,
    raw_summaries: tuple[str, ...],
    facts: tuple[str, ...],
    observations: tuple[str, ...],
    inferences: tuple[str, ...],
    temporal_relationships: tuple[str, ...],
    data_gaps: tuple[str, ...],
) -> str:
    parts = ["原始数据：" + "；".join(raw_summaries)]
    if facts:
        parts.append("事实：" + "；".join(facts))
    if observations:
        parts.append("观察线索：" + "；".join(observations))
    inferred = _unique((*inferences, *temporal_relationships))
    if inferred:
        parts.append("推断（待医学复核）：" + "；".join(inferred))
    if data_gaps:
        parts.append("证据缺口：" + "；".join(data_gaps))
    parts.append(
        "边界：以上仅为跨域复核线索，不代表已确认漏报、方案违背、因果关系"
        "或需发出 Query。"
    )
    return "。".join(parts)


def _recommended_action(
    recommended_review: str,
    recommendations: tuple[str, ...],
) -> str:
    values = _unique(
        (
            *([recommended_review] if recommended_review else []),
            *recommendations,
        )
    )
    detail = "；".join(values) if values else "核对相关原始记录和上下文"
    return (
        f"建议复核：{detail}。由医学经理复核后决定是否处置；"
        "系统不自动形成 Query 或确定性结论。"
    )


def _claim_texts(
    candidate: MonitoringAiCandidate,
    kind: MonitoringAiClaimKind,
) -> tuple[str, ...]:
    return _unique(
        claim.text.strip()
        for claim in candidate.claims
        if claim.kind is kind and claim.text.strip()
    )


def _stable_evidence_identity(
    evidence: Iterable[MonitoringAiEvidence],
) -> tuple[dict[str, str], ...]:
    return tuple(
        sorted(
            (
                {
                    "source_entry_id": item.source_entry_id,
                    "locator": item.locator,
                }
                for item in evidence
            ),
            key=lambda item: (item["source_entry_id"], item["locator"]),
        )
    )


def _all_locators(
    evidence: Iterable[MonitoringAiEvidence],
) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for item in evidence:
        locator = item.locator.strip()
        if locator and locator not in seen:
            seen.add(locator)
            values.append(locator)
    return values


def _evidence_snapshot(evidence: MonitoringAiEvidence) -> dict[str, Any]:
    return {
        "evidence_id": evidence.evidence_id,
        "source_entry_id": evidence.source_entry_id,
        "source_content_sha256": evidence.source_content_sha256,
        "locator": evidence.locator,
        "quote": evidence.quote,
        "raw_fields": evidence.raw_fields,
        "input_revision_sha256": evidence.input_revision_sha256,
    }


def _site_id(evidence: Iterable[MonitoringAiEvidence]) -> str | None:
    values: set[str] = set()
    for item in evidence:
        for field_name, value in _raw_values(item):
            if field_name.upper() in _SITE_FIELDS and value not in (None, ""):
                values.add(str(value).strip())
    if len(values) > 1:
        raise MonitoringAiRiskBridgeError(
            "candidate evidence contains conflicting site identifiers"
        )
    return next(iter(values), None)


def _tags(
    domains: frozenset[str],
    category: MedicalRiskCategoryDefinition,
) -> list[str]:
    values = {
        "medical_review_candidate",
        "independent_ai_candidate",
        "cross_table_clue",
        category.code.value,
        *(f"source_domain:{domain.lower()}" for domain in domains),
    }
    if "CM" in domains:
        values.add("non_study_concomitant_medication")
    if domains & _STUDY_TREATMENT_DOMAINS:
        values.add("study_treatment_record")
    if category.safety_pv_flag or domains & {
        "AE",
        "SAE",
        "AESI",
        "MH",
        "LB",
        "VS",
        "EG",
    }:
        values.add("safety_pv")
    return sorted(values)


def _string_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        cleaned
        for item in value
        if (cleaned := str(item or "").strip())
    )


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return tuple(result)


def _required_text(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise MonitoringAiRiskBridgeError(f"{field_name} is required")
    return normalized


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _display(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        return _canonical_json(value)
    return str(value)


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
