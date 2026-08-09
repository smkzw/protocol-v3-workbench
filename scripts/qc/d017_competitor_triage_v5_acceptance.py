#!/usr/bin/env python3
"""Deterministic medical-QC gate for a new D017 competitor-triage run.

The tool is deliberately independent from the running API and product AI.  It
reads a frozen ClinicalTrials.gov search snapshot plus a persisted triage run,
recomputes the accepted server-side invariants, and emits one JSON report.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


REPORT_VERSION = "d017_competitor_triage_v11_acceptance_1"
EXPECTED_PROVIDER = "deepseek"
EXPECTED_MODEL = "deepseek-v4-pro"
EXPECTED_PROMPT_VERSION = (
    "competitor_triage_deepseek_v13_controlled_condition_qualifiers"
)
EXPECTED_SCHEMA_VERSION = "competitor_triage_v1"
EXPECTED_CHUNK_COUNT = 5
EXPECTED_CANDIDATE_COUNT = 67
D017_PROJECT_INDICATION = "阵发性睡眠性血红蛋白尿症（PNH）"

ALLOWED_CLASSIFICATIONS = {
    "direct_competitor",
    "indirect_reference",
    "excluded",
}
PHARMACOLOGIC_TYPES = {
    "DRUG",
    "BIOLOGICAL",
    "COMBINATION_PRODUCT",
}
PROTECTED_DIMENSIONS = ("modality", "route", "target_mechanism")
DOCUMENT_ROLES = {
    (True, True): "已提供公开方案与统计分析计划",
    (True, False): "已提供公开方案",
    (False, True): "已提供公开统计分析计划",
    (False, False): "无公开方案或统计分析计划",
}
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
NCT_RE = re.compile(r"^NCT\d{8}$")
PAREN_ABBREV_RE = re.compile(r"[\(（]([A-Z]{2,8})[\)）]")
CONTROLLED_SUBGROUP_PREFIXES = frozenset({"with", "without"})
SUBGROUP_RELATION_TOKENS = frozenset(
    {"and", "or", "nor", "plus", "versus", "vs"}
)

# High-risk clinical assertions that can be checked deterministically against
# the supplied snapshot text. This is intentionally conservative: it catches
# unsupported route, mechanism, modality and design claims without pretending
# to replace medical review of arbitrary prose.
CLAIM_ANCHORS: dict[str, tuple[str, ...]] = {
    "口服": ("oral", "tablet", "capsule"),
    "静脉": ("intravenous", " iv ", "infusion"),
    "皮下": ("subcutaneous",),
    "吸入": ("inhal",),
    "鼻喷": ("nasal", "intranasal"),
    "外用": ("topical",),
    "补体": ("complement",),
    "B因子": ("factor b",),
    "C3": ("c3",),
    "C5": ("c5",),
    "抑制剂": ("inhibitor",),
    "单抗": ("monoclonal antibody",),
    "抗体": ("antibody",),
    "剂量递增": ("dose escalation", "ascending dose", "dose-ranging"),
    "初治": ("treatment-naive", "treatment naïve", "naive"),
}


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _hash_value(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    """Reproduce the accepted service's frozen snapshot hash exactly."""
    candidates = []
    for candidate in snapshot.get("candidates", []):
        candidates.append(
            {
                "nct_id": candidate.get("nct_id", ""),
                "brief_summary": candidate.get("brief_summary", ""),
                "conditions": candidate.get("conditions", []),
                "phases": candidate.get("phases", []),
                "study_type": candidate.get("study_type", ""),
                "interventions": [
                    {
                        "name": item.get("name", ""),
                        "intervention_type": item.get("intervention_type", ""),
                    }
                    for item in candidate.get("interventions", [])
                    if isinstance(item, dict)
                ],
                "design_allocation": candidate.get("design_allocation", ""),
                "design_intervention_model": candidate.get(
                    "design_intervention_model", ""
                ),
                "design_masking": candidate.get("design_masking", ""),
                "enrollment_count": candidate.get("enrollment_count"),
                "lead_sponsor": candidate.get("lead_sponsor", ""),
                "overall_status": candidate.get("overall_status", ""),
            }
        )
    material = {
        "snapshot_id": snapshot.get("snapshot_id", ""),
        "query_url": snapshot.get("query_url", ""),
        "api_version": snapshot.get("api_version", ""),
        "data_timestamp": snapshot.get("data_timestamp", ""),
        "total_count": snapshot.get("total_count", 0),
        "returned_count": snapshot.get("returned_count", 0),
        "candidates": sorted(candidates, key=lambda item: item["nct_id"]),
    }
    return _hash_value(material)


def _normalize_condition_orthography_token(token: str) -> str:
    """Normalize only the British/American ``haem-``/``hem-`` word family."""
    normalized = token.lower()
    if normalized.startswith("haem") and len(normalized) > 4:
        return "hem" + normalized[4:]
    return normalized


def normalize_indication_tokens(text: str) -> frozenset[str]:
    """Mirror the accepted exact-token-set normalization."""
    if not text:
        return frozenset()
    abbreviations = PAREN_ABBREV_RE.findall(text)
    normalized = text.lower()
    for separator in [",", ";", "（", "）", "(", ")", "，", "、", "。", "/"]:
        normalized = normalized.replace(separator, " ")
    normalized = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", normalized)
    tokens: set[str] = set()
    for raw in normalized.split():
        token = raw.strip()
        if not token:
            continue
        if re.fullmatch(r"[a-z]+", token):
            if len(token) >= 3:
                tokens.add(_normalize_condition_orthography_token(token))
        elif re.fullmatch(r"[\u4e00-\u9fff]+", token):
            if len(token) >= 2:
                tokens.add(token)
        elif len(token) >= 3:
            tokens.add(token)
    tokens.update(value.lower() for value in abbreviations)
    return frozenset(tokens)


def _english_condition_token_spans(text: str) -> list[tuple[str, int, int]]:
    return [
        (
            _normalize_condition_orthography_token(match.group(0)),
            match.start(),
            match.end(),
        )
        for match in re.finditer(r"[A-Za-z]+", text or "")
    ]


def _parenthetical_abbreviations(text: str) -> frozenset[str]:
    return frozenset(value.lower() for value in PAREN_ABBREV_RE.findall(text or ""))


def _condition_alias_pair_matches_project(
    condition: str,
    project_token_sets: list[frozenset[str]],
    project_abbreviations: frozenset[str],
) -> bool:
    """Match only a strict ``ABBR - full disease name`` condition alias."""
    segments = re.split(r"\s+[-\u2013\u2014]\s+", condition.strip())
    if len(segments) != 2:
        return False
    left, right = (segment.strip() for segment in segments)
    for abbreviation, full_name in ((left, right), (right, left)):
        if not re.fullmatch(r"[A-Z]{2,8}", abbreviation):
            continue
        if abbreviation.lower() not in project_abbreviations:
            continue
        full_name_tokens = normalize_indication_tokens(full_name)
        if full_name_tokens and any(
            full_name_tokens == project_tokens
            for project_tokens in project_token_sets
        ):
            return True
    return False


def _condition_full_name_with_controlled_subgroup_matches_project(
    condition: str,
    project_full_name_sequences: list[tuple[str, ...]],
    project_abbreviations: frozenset[str],
) -> bool:
    """Mirror the service's exact-full-name controlled subgroup rule."""
    candidate_spans = _english_condition_token_spans(condition)
    if not candidate_spans:
        return False

    for project_sequence in project_full_name_sequences:
        token_count = len(project_sequence)
        if token_count < 3 or len(candidate_spans) < token_count:
            continue
        if condition[: candidate_spans[0][1]].strip():
            continue
        candidate_prefix = tuple(
            token for token, _, _ in candidate_spans[:token_count]
        )
        if candidate_prefix != project_sequence:
            continue

        tail = condition[candidate_spans[token_count - 1][2] :].strip()
        abbreviation_match = re.match(
            r"^[\(（]([A-Z]{2,8})[\)）](.*)$",
            tail,
            flags=re.DOTALL,
        )
        if abbreviation_match:
            if (
                abbreviation_match.group(1).lower()
                not in project_abbreviations
            ):
                continue
            tail = abbreviation_match.group(2).strip()
        if not tail:
            return True
        if re.search(r"[\(\)（）,，;；:/\\&+|]", tail):
            continue
        if re.search(r"\s+[-\u2013\u2014]\s+", tail):
            continue
        if re.search(r"[^A-Za-z\s'\-]", tail):
            continue

        subgroup_tokens = tuple(
            token for token, _, _ in _english_condition_token_spans(tail)
        )
        if not 2 <= len(subgroup_tokens) <= 16:
            continue
        if subgroup_tokens[0] not in CONTROLLED_SUBGROUP_PREFIXES:
            continue
        if SUBGROUP_RELATION_TOKENS.intersection(subgroup_tokens):
            continue
        return True
    return False


def _parenthetical_alias_full_name_matches_project(
    condition: str,
    project_token_sets: list[frozenset[str]],
    project_abbreviations: frozenset[str],
) -> bool:
    """Reject a shared parenthetical abbreviation without an exact full name."""
    candidate_abbreviations = _parenthetical_abbreviations(condition)
    if not (project_abbreviations & candidate_abbreviations):
        return False
    full_name = re.sub(r"[\(（][A-Z]{2,8}[\)）]", "", condition).strip()
    full_name_tokens = normalize_indication_tokens(full_name)
    return bool(full_name_tokens) and any(
        full_name_tokens == project_tokens for project_tokens in project_token_sets
    )


def same_indication(
    conditions: Iterable[Any],
    *,
    project_indication: str,
    clinicaltrials_condition_term: str,
) -> bool:
    """Exact set equality or a provable parenthetical abbreviation only."""
    project_terms = [
        value.strip()
        for value in (project_indication, clinicaltrials_condition_term)
        if isinstance(value, str) and value.strip()
    ]
    project_token_sets = [
        tokens
        for tokens in (normalize_indication_tokens(value) for value in project_terms)
        if tokens
    ]
    if not project_token_sets:
        return False
    project_full_name_sequences = [
        tuple(token for token, _, _ in _english_condition_token_spans(value))
        for value in project_terms
    ]
    project_abbreviations = frozenset().union(
        *(_parenthetical_abbreviations(value) for value in project_terms)
    )

    for raw_condition in conditions:
        if not isinstance(raw_condition, str) or not raw_condition.strip():
            continue
        condition = raw_condition.strip()
        candidate_tokens = normalize_indication_tokens(condition)
        if candidate_tokens and any(
            candidate_tokens == project_tokens
            for project_tokens in project_token_sets
        ):
            return True

        standalone = condition.upper()
        if (
            2 <= len(standalone) <= 8
            and standalone.isalpha()
            and condition == standalone
            and standalone.lower() in project_abbreviations
        ):
            return True
        if _condition_alias_pair_matches_project(
            condition, project_token_sets, project_abbreviations
        ):
            return True
        if _parenthetical_alias_full_name_matches_project(
            condition, project_token_sets, project_abbreviations
        ):
            return True
        if _condition_full_name_with_controlled_subgroup_matches_project(
            condition,
            project_full_name_sequences,
            project_abbreviations,
        ):
            return True
    return False


def has_pharmacologic_intervention(candidate: dict[str, Any]) -> bool:
    interventions = candidate.get("interventions")
    if not isinstance(interventions, list):
        return False
    return any(
        isinstance(item, dict)
        and str(item.get("intervention_type", "")).strip().upper()
        in PHARMACOLOGIC_TYPES
        for item in interventions
    )


def _meaningfully_known(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip()) and value.strip().lower() != "unknown"
    if isinstance(value, (list, tuple)):
        return any(_meaningfully_known(item) for item in value)
    return bool(value)


def _document_expectation(candidate: dict[str, Any]) -> tuple[bool, bool, str]:
    document_types = {
        str(item.get("document_type", "")).strip().lower()
        for item in candidate.get("public_documents", [])
        if isinstance(item, dict)
    }
    has_protocol = bool(document_types & {"protocol", "protocol_sap"})
    has_sap = bool(document_types & {"sap", "protocol_sap"})
    return has_protocol, has_sap, DOCUMENT_ROLES[(has_protocol, has_sap)]


def _candidate_source_text(candidate: dict[str, Any]) -> str:
    values: list[str] = [
        str(candidate.get("brief_title", "")),
        str(candidate.get("official_title", "")),
        str(candidate.get("brief_summary", "")),
        *(str(value) for value in candidate.get("conditions", [])),
        *(str(value) for value in candidate.get("phases", [])),
        str(candidate.get("study_type", "")),
        str(candidate.get("design_allocation", "")),
        str(candidate.get("design_intervention_model", "")),
        str(candidate.get("design_masking", "")),
        str(candidate.get("enrollment_count", "")),
        str(candidate.get("lead_sponsor", "")),
        str(candidate.get("overall_status", "")),
    ]
    for intervention in candidate.get("interventions", []):
        if isinstance(intervention, dict):
            values.extend(
                [
                    str(intervention.get("name", "")),
                    str(intervention.get("intervention_type", "")),
                ]
            )
    for document in candidate.get("public_documents", []):
        if isinstance(document, dict):
            values.extend(
                [
                    str(document.get("document_type", "")),
                    str(document.get("label", "")),
                    str(document.get("filename", "")),
                    str(document.get("document_date", "")),
                ]
            )
    return f" {' '.join(values).lower()} "


def _result_text(result: dict[str, Any]) -> str:
    dimensions = result.get("matching_dimensions", [])
    details = [
        str(item.get("detail", ""))
        for item in dimensions
        if isinstance(item, dict)
    ]
    suitability = result.get("document_suitability")
    role = suitability.get("document_role", "") if isinstance(suitability, dict) else ""
    return " ".join(
        [
            str(result.get("reason", "")),
            *(str(value) for value in result.get("evidence_gaps", [])),
            *details,
            str(role),
        ]
    )


def _valid_https_url(
    value: Any,
    *,
    nct_id: str | None = None,
    require_ctgov: bool = True,
) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        return False
    if require_ctgov and parsed.hostname not in {
        "clinicaltrials.gov",
        "www.clinicaltrials.gov",
    }:
        return False
    if nct_id and nct_id not in value:
        return False
    return True


def _dimension_map(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("dimension", "")): item
        for item in result.get("matching_dimensions", [])
        if isinstance(item, dict) and item.get("dimension")
    }


def _candidate_dimension_value(candidate: dict[str, Any], dimension: str) -> Any:
    aliases = {
        "modality": ("modality", "technology_type"),
        "route": ("route", "administration_routes"),
        "target_mechanism": ("target_mechanism",),
    }
    for key in aliases[dimension]:
        if key in candidate and _meaningfully_known(candidate[key]):
            return candidate[key]
    return None


def _project_dimension_values(project_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "modality": project_context.get("technology_type", ""),
        "route": project_context.get("administration_routes", []),
        "target_mechanism": project_context.get("target_mechanism", ""),
    }


def _check_record(
    check_id: str,
    issues: list[dict[str, Any]],
    *,
    expected: Any,
    observed: Any,
) -> dict[str, Any]:
    relevant = [issue for issue in issues if issue["check_id"] == check_id]
    return {
        "id": check_id,
        "passed": not relevant,
        "expected": expected,
        "observed": observed,
        "issue_count": len(relevant),
    }


def build_report(
    snapshot: dict[str, Any],
    run_payload: dict[str, Any],
    *,
    project_indication: str = D017_PROJECT_INDICATION,
    clinicaltrials_condition_term: str | None = None,
    project_technology_type: str = "",
    project_administration_routes: Iterable[str] = (),
    project_target_mechanism: str = "",
) -> dict[str, Any]:
    """Return a deterministic acceptance report without mutating either input."""
    run = run_payload.get("run", run_payload)
    if not isinstance(run, dict):
        raise ValueError("run JSON must be a run object or contain a 'run' object")
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot JSON must be an object")

    ct_term = (
        clinicaltrials_condition_term
        if clinicaltrials_condition_term is not None
        else str(snapshot.get("request", {}).get("indication", ""))
    )
    project_routes = list(project_administration_routes)
    project_context = {
        "technology_type": project_technology_type,
        "administration_routes": project_routes,
        "target_mechanism": project_target_mechanism,
    }
    project_dimensions = _project_dimension_values(project_context)
    issues: list[dict[str, Any]] = []

    def issue(
        check_id: str,
        code: str,
        message: str,
        *,
        nct_id: str = "",
        chunk_id: str = "",
        evidence: Any = None,
    ) -> None:
        item: dict[str, Any] = {
            "check_id": check_id,
            "code": code,
            "severity": "error",
            "message": message,
        }
        if nct_id:
            item["nct_id"] = nct_id
        if chunk_id:
            item["chunk_id"] = chunk_id
        if evidence is not None:
            item["evidence"] = evidence
        issues.append(item)

    snapshot_candidates = snapshot.get("candidates", [])
    if not isinstance(snapshot_candidates, list):
        snapshot_candidates = []
        issue(
            "candidate_completeness",
            "snapshot_candidates_not_list",
            "snapshot.candidates必须为数组",
        )
    candidates: dict[str, dict[str, Any]] = {}
    snapshot_ids: list[str] = []
    for candidate in snapshot_candidates:
        if not isinstance(candidate, dict):
            issue(
                "candidate_completeness",
                "invalid_snapshot_candidate",
                "snapshot候选项必须为对象",
            )
            continue
        nct_id = str(candidate.get("nct_id", "")).strip()
        snapshot_ids.append(nct_id)
        if not NCT_RE.fullmatch(nct_id):
            issue(
                "candidate_completeness",
                "invalid_snapshot_nct_id",
                "snapshot包含非法NCT编号",
                nct_id=nct_id,
            )
        if nct_id in candidates:
            issue(
                "candidate_completeness",
                "duplicate_snapshot_nct_id",
                "snapshot包含重复NCT编号",
                nct_id=nct_id,
            )
        candidates[nct_id] = candidate

    chunks = run.get("chunks", [])
    if not isinstance(chunks, list):
        chunks = []
        issue("chunk_completeness", "chunks_not_list", "run.chunks必须为数组")
    results: list[dict[str, Any]] = []
    result_chunk: dict[str, str] = {}
    chunk_statuses: list[dict[str, Any]] = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            issue("chunk_completeness", "invalid_chunk", "chunk必须为对象")
            continue
        chunk_id = str(chunk.get("chunk_id", ""))
        nct_ids = [str(value) for value in chunk.get("nct_ids", [])]
        chunk_results = [
            value for value in chunk.get("results", []) if isinstance(value, dict)
        ]
        chunk_result_ids = [str(value.get("nct_id", "")) for value in chunk_results]
        chunk_statuses.append(
            {
                "chunk_id": chunk_id,
                "status": chunk.get("status"),
                "candidate_count": len(nct_ids),
                "result_count": len(chunk_results),
            }
        )
        if chunk.get("status") != "succeeded":
            issue(
                "chunk_completeness",
                "chunk_not_succeeded",
                "所有chunk必须成功",
                chunk_id=chunk_id,
                evidence={"status": chunk.get("status")},
            )
        if Counter(nct_ids) != Counter(chunk_result_ids):
            issue(
                "chunk_completeness",
                "chunk_result_permutation_mismatch",
                "chunk结果必须与chunk NCT集合完全一致且无重复",
                chunk_id=chunk_id,
                evidence={
                    "nct_ids": nct_ids,
                    "result_ids": chunk_result_ids,
                },
            )
        provenance = chunk.get("provenance")
        if not isinstance(provenance, dict):
            issue(
                "identity_and_prompt",
                "missing_chunk_provenance",
                "成功chunk缺少provenance",
                chunk_id=chunk_id,
            )
        else:
            for field, expected in (
                ("provider", EXPECTED_PROVIDER),
                ("response_model", EXPECTED_MODEL),
                ("prompt_version", EXPECTED_PROMPT_VERSION),
                ("schema_version", EXPECTED_SCHEMA_VERSION),
            ):
                if provenance.get(field) != expected:
                    issue(
                        "identity_and_prompt",
                        f"chunk_{field}_mismatch",
                        f"chunk provenance {field}不匹配",
                        chunk_id=chunk_id,
                        evidence={
                            "expected": expected,
                            "observed": provenance.get(field),
                        },
                    )
            for hash_field in ("canonical_input_hash", "canonical_output_hash"):
                if not HEX64_RE.fullmatch(str(provenance.get(hash_field, ""))):
                    issue(
                        "identity_and_prompt",
                        f"invalid_chunk_{hash_field}",
                        f"chunk provenance {hash_field}必须为64位十六进制",
                        chunk_id=chunk_id,
                    )
        for result in chunk_results:
            nct_id = str(result.get("nct_id", ""))
            results.append(result)
            result_chunk[nct_id] = chunk_id

    result_ids = [str(result.get("nct_id", "")) for result in results]
    if len(chunks) != EXPECTED_CHUNK_COUNT:
        issue(
            "chunk_completeness",
            "unexpected_chunk_count",
            "D017新run必须完成5个chunk",
            evidence={"expected": EXPECTED_CHUNK_COUNT, "observed": len(chunks)},
        )
    if len(candidates) != EXPECTED_CANDIDATE_COUNT:
        issue(
            "candidate_completeness",
            "unexpected_snapshot_candidate_count",
            "D017快照必须包含67个唯一候选",
            evidence={"expected": EXPECTED_CANDIDATE_COUNT, "observed": len(candidates)},
        )
    if len(results) != EXPECTED_CANDIDATE_COUNT:
        issue(
            "candidate_completeness",
            "unexpected_result_count",
            "D017新run必须返回67个结果",
            evidence={"expected": EXPECTED_CANDIDATE_COUNT, "observed": len(results)},
        )
    for nct_id, count in Counter(result_ids).items():
        if count > 1:
            issue(
                "candidate_completeness",
                "duplicate_result_nct_id",
                "run包含重复NCT结果",
                nct_id=nct_id,
                evidence={"count": count},
            )
    for nct_id in sorted(set(candidates) - set(result_ids)):
        issue(
            "candidate_completeness",
            "missing_result_nct_id",
            "snapshot候选在run中缺失",
            nct_id=nct_id,
        )
    for nct_id in sorted(set(result_ids) - set(candidates)):
        issue(
            "candidate_completeness",
            "unknown_result_nct_id",
            "run包含snapshot之外的NCT",
            nct_id=nct_id,
        )

    for field, expected in (
        ("provider", EXPECTED_PROVIDER),
        ("response_model", EXPECTED_MODEL),
        ("prompt_version", EXPECTED_PROMPT_VERSION),
        ("schema_version", EXPECTED_SCHEMA_VERSION),
    ):
        if run.get(field) != expected:
            issue(
                "identity_and_prompt",
                f"run_{field}_mismatch",
                f"run {field}不匹配",
                evidence={"expected": expected, "observed": run.get(field)},
            )
    if run.get("status") != "review_ready":
        issue(
            "identity_and_prompt",
            "run_not_review_ready",
            "医学QC仅接受review_ready的新run",
            evidence={"observed": run.get("status")},
        )
    expected_snapshot_hash = snapshot_hash(snapshot)
    if run.get("snapshot_hash") != expected_snapshot_hash:
        issue(
            "snapshot_identity",
            "snapshot_hash_mismatch",
            "run.snapshot_hash与接受服务算法重算值不一致",
            evidence={
                "expected": expected_snapshot_hash,
                "observed": run.get("snapshot_hash"),
            },
        )
    if run.get("snapshot_id") != snapshot.get("snapshot_id"):
        issue(
            "snapshot_identity",
            "snapshot_id_mismatch",
            "run.snapshot_id与输入snapshot不一致",
            evidence={
                "expected": snapshot.get("snapshot_id"),
                "observed": run.get("snapshot_id"),
            },
        )

    query_url = snapshot.get("query_url")
    if not _valid_https_url(query_url):
        issue(
            "source_locators",
            "invalid_snapshot_query_url",
            "snapshot必须保留ClinicalTrials.gov HTTPS查询URL",
            evidence={"query_url": query_url},
        )

    source_inventory: list[dict[str, Any]] = []
    for nct_id, candidate in sorted(candidates.items()):
        study_url = candidate.get("study_record_url")
        document_sources: list[dict[str, Any]] = []
        if not _valid_https_url(study_url, nct_id=nct_id):
            issue(
                "source_locators",
                "invalid_study_record_url",
                "候选必须包含可定位到自身NCT的HTTPS study_record_url",
                nct_id=nct_id,
                evidence={"study_record_url": study_url},
            )
        documents = candidate.get("public_documents", [])
        if not isinstance(documents, list):
            documents = []
            issue(
                "source_locators",
                "public_documents_not_list",
                "public_documents必须为数组",
                nct_id=nct_id,
            )
        for document in documents:
            if not isinstance(document, dict):
                issue(
                    "source_locators",
                    "invalid_public_document",
                    "公开文档记录必须为对象",
                    nct_id=nct_id,
                )
                continue
            locator = str(document.get("document_id", "")).strip()
            download_url = document.get("download_url")
            document_type = str(document.get("document_type", "")).strip().lower()
            if not locator:
                issue(
                    "source_locators",
                    "missing_document_locator",
                    "公开文档缺少document_id定位符",
                    nct_id=nct_id,
                )
            if not document_type:
                issue(
                    "source_locators",
                    "missing_document_type",
                    "公开文档缺少document_type",
                    nct_id=nct_id,
                )
            if not _valid_https_url(download_url, nct_id=nct_id):
                issue(
                    "source_locators",
                    "invalid_document_source_url",
                    "公开文档必须包含可定位到自身NCT的HTTPS download_url",
                    nct_id=nct_id,
                    evidence={"download_url": download_url, "locator": locator},
                )
            document_sources.append(
                {
                    "locator": locator,
                    "document_type": document_type,
                    "source_url": download_url,
                }
            )
        source_inventory.append(
            {
                "nct_id": nct_id,
                "study_record_url": study_url,
                "public_documents": document_sources,
            }
        )

    classification_distribution: Counter[str] = Counter()
    invalid_indirect = 0
    direct_ids: list[str] = []
    for result in results:
        nct_id = str(result.get("nct_id", ""))
        chunk_id = result_chunk.get(nct_id, "")
        candidate = candidates.get(nct_id)
        if candidate is None:
            continue
        classification = str(result.get("classification", ""))
        classification_distribution[classification] += 1
        if classification not in ALLOWED_CLASSIFICATIONS:
            issue(
                "classification_eligibility",
                "invalid_classification",
                "classification不在允许集合内",
                nct_id=nct_id,
                chunk_id=chunk_id,
                evidence={"classification": classification},
            )
            continue
        indication_match = same_indication(
            candidate.get("conditions", []),
            project_indication=project_indication,
            clinicaltrials_condition_term=ct_term,
        )
        pharmacologic = has_pharmacologic_intervention(candidate)

        if classification == "indirect_reference":
            if not indication_match or not pharmacologic:
                invalid_indirect += 1
                issue(
                    "classification_eligibility",
                    "invalid_indirect_reference",
                    "indirect_reference必须同时满足同适应症和显式药理学干预",
                    nct_id=nct_id,
                    chunk_id=chunk_id,
                    evidence={
                        "same_indication": indication_match,
                        "intervention_types": sorted(
                            {
                                str(item.get("intervention_type", "")).upper()
                                for item in candidate.get("interventions", [])
                                if isinstance(item, dict)
                            }
                        ),
                    },
                )
        elif classification == "direct_competitor":
            direct_ids.append(nct_id)
            all_project_dimensions_known = all(
                _meaningfully_known(project_dimensions[dimension])
                for dimension in PROTECTED_DIMENSIONS
            )
            dimension_results = _dimension_map(result)
            candidate_dimensions_verifiable = all(
                _meaningfully_known(_candidate_dimension_value(candidate, dimension))
                and dimension_results.get(dimension, {}).get("match") != "unknown"
                for dimension in PROTECTED_DIMENSIONS
            )
            if (
                not indication_match
                or not pharmacologic
                or not all_project_dimensions_known
                or not candidate_dimensions_verifiable
                or not _valid_https_url(candidate.get("study_record_url"), nct_id=nct_id)
            ):
                issue(
                    "classification_eligibility",
                    "invalid_direct_competitor",
                    "direct必须同适应症、含显式药理学干预，且项目三维已知、候选三维有可核查来源",
                    nct_id=nct_id,
                    chunk_id=chunk_id,
                    evidence={
                        "same_indication": indication_match,
                        "pharmacologic": pharmacologic,
                        "project_dimensions_known": all_project_dimensions_known,
                        "candidate_dimensions_verifiable": candidate_dimensions_verifiable,
                    },
                )

        dimensions = _dimension_map(result)
        for dimension, project_value in project_dimensions.items():
            if _meaningfully_known(project_value):
                continue
            observed = dimensions.get(dimension)
            if not observed or observed.get("match") != "unknown":
                issue(
                    "unknown_dimension_protection",
                    "unknown_project_dimension_not_protected",
                    "项目未知维度必须在结果中显式标记unknown",
                    nct_id=nct_id,
                    chunk_id=chunk_id,
                    evidence={"dimension": dimension, "observed": observed},
                )

        expected_protocol, expected_sap, expected_role = _document_expectation(candidate)
        suitability = result.get("document_suitability")
        if not isinstance(suitability, dict) or (
            bool(suitability.get("has_public_protocol")) != expected_protocol
            or bool(suitability.get("has_public_sap")) != expected_sap
            or suitability.get("document_role") != expected_role
        ):
            issue(
                "document_determinism",
                "document_suitability_mismatch",
                "document flags/role必须由snapshot public_documents确定性生成",
                nct_id=nct_id,
                chunk_id=chunk_id,
                evidence={
                    "expected": {
                        "has_public_protocol": expected_protocol,
                        "has_public_sap": expected_sap,
                        "document_role": expected_role,
                    },
                    "observed": suitability,
                },
            )

        reason = str(result.get("reason", ""))
        if classification == "indirect_reference":
            same_indication_token = (
                "适应症一致" in reason
                or (
                    "候选完整登记条件包含项目适应症" in reason
                    and "可作为同适应症药物研究参考" in reason
                )
            )
            if (
                not same_indication_token
                or "可作为同适应症药物研究参考" not in reason
                or "适应症不同" in reason
                or "不纳入竞品篮子" in reason
            ):
                issue(
                    "reason_consistency",
                    "indirect_reason_inconsistent",
                    "indirect_reference理由必须明确同适应症参照且不得出现排除结论",
                    nct_id=nct_id,
                    chunk_id=chunk_id,
                    evidence={"reason": reason},
                )
        elif classification == "excluded":
            if "不纳入竞品篮子" not in reason:
                issue(
                    "reason_consistency",
                    "excluded_reason_missing_conclusion",
                    "excluded理由必须明确不纳入竞品篮子",
                    nct_id=nct_id,
                    chunk_id=chunk_id,
                    evidence={"reason": reason},
                )
            if indication_match and "适应症不同" in reason:
                issue(
                    "reason_consistency",
                    "reason_false_indication_mismatch",
                    "服务端判为同适应症时理由不得写适应症不同",
                    nct_id=nct_id,
                    chunk_id=chunk_id,
                    evidence={"reason": reason},
                )
            if not indication_match and (
                "适应症一致" in reason or "同适应症药物研究参考" in reason
            ):
                issue(
                    "reason_consistency",
                    "reason_false_indication_match",
                    "服务端判为非同适应症时理由不得声称适应症一致",
                    nct_id=nct_id,
                    chunk_id=chunk_id,
                    evidence={"reason": reason},
                )
        elif classification == "direct_competitor" and (
            "不纳入竞品篮子" in reason or "可作为同适应症药物研究参考" in reason
        ):
            issue(
                "reason_consistency",
                "direct_reason_inconsistent",
                "direct理由不得包含间接参照或排除结论",
                nct_id=nct_id,
                chunk_id=chunk_id,
                evidence={"reason": reason},
            )

        source_text = _candidate_source_text(candidate)
        output_text = _result_text(result)
        for claim, anchors in CLAIM_ANCHORS.items():
            if claim in output_text and not any(anchor in source_text for anchor in anchors):
                issue(
                    "unsupported_factual_claims",
                    "unsupported_high_risk_claim",
                    "输出包含snapshot显式文本无法支持的高风险事实主张",
                    nct_id=nct_id,
                    chunk_id=chunk_id,
                    evidence={"claim": claim, "output_text": output_text},
                )

    checks = [
        _check_record(
            "identity_and_prompt",
            issues,
            expected={
                "provider": EXPECTED_PROVIDER,
                "model": EXPECTED_MODEL,
                "prompt_version": EXPECTED_PROMPT_VERSION,
                "schema_version": EXPECTED_SCHEMA_VERSION,
                "status": "review_ready",
            },
            observed={
                "provider": run.get("provider"),
                "model": run.get("response_model"),
                "prompt_version": run.get("prompt_version"),
                "schema_version": run.get("schema_version"),
                "status": run.get("status"),
            },
        ),
        _check_record(
            "snapshot_identity",
            issues,
            expected={
                "snapshot_id": snapshot.get("snapshot_id"),
                "snapshot_hash": expected_snapshot_hash,
            },
            observed={
                "snapshot_id": run.get("snapshot_id"),
                "snapshot_hash": run.get("snapshot_hash"),
            },
        ),
        _check_record(
            "chunk_completeness",
            issues,
            expected={"chunks": 5, "all_status": "succeeded"},
            observed={"chunks": len(chunks), "statuses": chunk_statuses},
        ),
        _check_record(
            "candidate_completeness",
            issues,
            expected={"snapshot_unique_nct": 67, "run_unique_nct": 67},
            observed={
                "snapshot_unique_nct": len(set(snapshot_ids)),
                "run_unique_nct": len(set(result_ids)),
            },
        ),
        _check_record(
            "classification_eligibility",
            issues,
            expected={
                "indirect": "same indication + explicit permitted intervention",
                "direct": "indirect rules + project/candidate tech-route-target verified",
            },
            observed={
                "distribution": dict(sorted(classification_distribution.items())),
                "invalid_indirect": invalid_indirect,
                "direct_ids": sorted(direct_ids),
            },
        ),
        _check_record(
            "unknown_dimension_protection",
            issues,
            expected={
                dimension: (
                    "known" if _meaningfully_known(value) else "unknown-protected"
                )
                for dimension, value in project_dimensions.items()
            },
            observed="per-result matching_dimensions",
        ),
        _check_record(
            "document_determinism",
            issues,
            expected="flags and exact Chinese role derived from public_documents",
            observed="per-result document_suitability",
        ),
        _check_record(
            "reason_consistency",
            issues,
            expected="reason conclusion agrees with reconciled classification",
            observed="per-result reason",
        ),
        _check_record(
            "unsupported_factual_claims",
            issues,
            expected="zero unsupported high-risk route/mechanism/modality/design claims",
            observed="bounded deterministic claim-anchor scan",
        ),
        _check_record(
            "source_locators",
            issues,
            expected="all study and public-document HTTPS URLs/locators present",
            observed={
                "candidate_sources": len(source_inventory),
                "document_sources": sum(
                    len(item["public_documents"]) for item in source_inventory
                ),
            },
        ),
    ]

    return {
        "report_version": REPORT_VERSION,
        "accepted": not issues,
        "run_identity": {
            "run_id": run.get("run_id"),
            "snapshot_id": run.get("snapshot_id"),
            "provider": run.get("provider"),
            "response_model": run.get("response_model"),
            "prompt_version": run.get("prompt_version"),
            "status": run.get("status"),
        },
        "project_matching_context": {
            "project_indication": project_indication,
            "clinicaltrials_condition_term": ct_term,
            "technology_type": project_technology_type,
            "administration_routes": project_routes,
            "target_mechanism": project_target_mechanism,
        },
        "summary": {
            "snapshot_candidate_count": len(candidates),
            "result_count": len(results),
            "unique_result_count": len(set(result_ids)),
            "chunk_count": len(chunks),
            "classification_distribution": dict(
                sorted(classification_distribution.items())
            ),
            "error_count": len(issues),
        },
        "checks": checks,
        "issues": issues,
        "snapshot_source": {
            "snapshot_id": snapshot.get("snapshot_id"),
            "query_url": query_url,
            "api_version": snapshot.get("api_version"),
            "data_timestamp": snapshot.get("data_timestamp"),
        },
        "source_inventory": source_inventory,
        "residual_boundaries": [
            "工具验证结构化来源、已接受的失败关闭分类语义及高风险词锚定；不能证明任意自然语言主张的完整语义蕴含。",
            "工具不访问网络，不验证ClinicalTrials.gov链接当前可达性，仅验证快照内HTTPS URL及定位符完整性。",
            "D017默认项目技术类型、给药途径和靶点/机制未知；若未来三项均已确认，须通过命令行显式提供。",
        ],
    }


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a new D017 competitor-triage snapshot/run pair."
    )
    parser.add_argument("snapshot_json", type=Path)
    parser.add_argument("run_json", type=Path)
    parser.add_argument(
        "--project-indication",
        default=D017_PROJECT_INDICATION,
        help="Chinese project indication used as an independent exact-match term.",
    )
    parser.add_argument(
        "--clinicaltrials-condition-term",
        default=None,
        help="English CT.gov condition term; defaults to snapshot.request.indication.",
    )
    parser.add_argument("--project-technology-type", default="")
    parser.add_argument(
        "--project-route",
        action="append",
        default=[],
        help="Confirmed project route; repeat for multiple routes.",
    )
    parser.add_argument("--project-target-mechanism", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        report = build_report(
            _load_json(args.snapshot_json),
            _load_json(args.run_json),
            project_indication=args.project_indication,
            clinicaltrials_condition_term=args.clinicaltrials_condition_term,
            project_technology_type=args.project_technology_type,
            project_administration_routes=args.project_route,
            project_target_mechanism=args.project_target_mechanism,
        )
    except Exception as exc:
        report = {
            "report_version": REPORT_VERSION,
            "accepted": False,
            "fatal_error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["accepted"] else 1


if __name__ == "__main__":
    sys.exit(main())
