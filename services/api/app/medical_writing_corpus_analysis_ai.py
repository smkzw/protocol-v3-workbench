"""Evidence-bound independent-AI analysis for competitor Protocol corpora.

The service freezes the active product AI profile before a research-pipeline
job starts, resolves only that exact profile when the job reaches round 1,
builds a bounded evidence catalog from current Protocol source spans, and
persists an immutable analysis artifact in the writing-reference database.

Model output is treated as a proposal, not authority. Every finding must bind
registered evidence IDs; the server attaches the immutable source excerpt and
locator. Numeric claims, cross-indication transfer scope, source/sponsor
support, conflicts, and confidence are validated or derived deterministically
before persistence.
"""
from __future__ import annotations

import json
import os
import re
import socket
import sqlite3
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Callable, Iterable

from .medical_writing_corpus_policy import (
    CORPUS_PATTERN_KINDS,
    _canonical_phase_components,
    _phase_tokens_explicit_in_text,
    assess_corpus_support,
    corpus_generalization_prompt_contract,
    cross_indication_transfer_scope,
)
from .writing_reference_repository import TENANT_ID
from .writing_reference_protocol_scope import protocol_corpus_span_scope


CORPUS_ANALYSIS_PROMPT_VERSION = "competitor_protocol_corpus_analysis_v12"
CORPUS_ANALYSIS_SCHEMA_VERSION = "competitor_protocol_corpus_analysis_v4"
CORPUS_ANALYSIS_ROUTE_SCHEMA_VERSION = "corpus_analysis_ai_route_v1"
CORPUS_ANALYSIS_RESPONSE_REPAIR_POLICY_VERSION = "single_finding_root_repair_v1"
CORPUS_ANALYSIS_TABLE = "writing_reference_corpus_analysis_runs"
INDICATION_ALIGNMENT_POLICY_VERSION = "controlled_indication_aliases_v2"
_CLINICALTRIALS_STUDY_ID_PATTERN = re.compile(r"^NCT\d{8}$", re.I)

_CONTROLLED_INDICATION_ALIASES = {
    "pnh": (
        "阵发性睡眠性血红蛋白尿症",
        "paroxysmal nocturnal hemoglobinuria",
        "paroxysmal nocturnal haemoglobinuria",
        "pnh",
    ),
    "rheumatoid_arthritis": (
        "类风湿关节炎",
        "rheumatoid arthritis",
        "ra",
    ),
}

_ANALYSIS_MODULES = frozenset(
    {
        "objectives_endpoints",
        "eligibility",
        "intervention",
        "comparator",
        "safety",
        "schedule",
        "statistics",
        "design",
        "structure",
        "regulatory_commonality",
    }
)
_TRANSFER_SCOPES = frozenset(
    {"same_indication", "cross_indication_structure_only"}
)
_CROSS_INDICATION_MODULES = frozenset({"structure", "regulatory_commonality"})
_LAYER_KEYS = (
    "indications",
    "phases",
    "research_purposes",
    "mechanisms",
    "technology_types",
    "dosage_forms",
    "administration_routes",
    "design_modules",
)
_ROOT_KEYS = frozenset(
    {
        "schema_version",
        "analysis_id",
        "project_context_hash",
        "findings",
        "evidence_gaps",
        "global_conflicts",
    }
)
_FINDING_KEYS = frozenset(
    {
        "finding_id",
        "module",
        "pattern_kind",
        "statement_zh",
        "transfer_scope",
        "layer",
        "evidence_bindings",
        "conflicts",
        "unresolved_gaps",
    }
)
_BINDING_KEYS = frozenset({"evidence_id"})
_CONFLICT_KEYS = frozenset({"claim_value_zh", "evidence_bindings"})
_GLOBAL_CONFLICT_KEYS = frozenset({"description_zh", "evidence_bindings"})
_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)*(?:%|％)?")
_MULTI_SOURCE_ASSERTION_PATTERN = re.compile(
    r"(?:两|二|多)(?:份|项|个)(?:方案|研究|来源|文档)"
    r"|(?:各|所有)(?:方案|研究|来源|文档)"
    r"|(?:方案|研究|来源|文档).{0,12}均(?:采用|设置|要求|使用|报告|规定|显示)"
)
_GENERALIZED_USAGE_ASSERTION_PATTERN = re.compile(
    r"常用|通常|普遍(?:采用|设置|要求|使用|存在)?|"
    r"(?:一般|多)(?:采用|设置|要求|使用)|惯例|标准做法"
)
_PROTOCOL_DOCUMENT_TYPES = frozenset({"protocol", "protocol_sap"})
_CRITICAL_ANCHORS = frozenset(
    {"objectives_endpoints", "eligibility", "schedule", "safety"}
)
_CONTENT_ROLE_BY_PATTERN_AND_MODULE = {
    ("regulatory_common_structure", "structure"): "structure_template",
    (
        "regulatory_common_structure",
        "regulatory_commonality",
    ): "regulatory_fixed_wording",
    ("wording_convention", "*"): "indication_specific_wording",
    ("clinical_design_requirement", "*"): "project_fact_reference",
}


class CorpusAnalysisAiError(ValueError):
    """Raised when the independent-AI route, evidence, or output is invalid."""

    def __init__(self, message: str, *, diagnostics: dict[str, Any] | None = None):
        super().__init__(message)
        self.diagnostics: dict[str, Any] = dict(diagnostics or {})


@dataclass(frozen=True)
class FrozenCorpusAnalysisAiRoute:
    profile_id: str
    profile_revision: int
    provider: str
    model: str
    base_url: str
    transport: str
    expected_response_model: str
    deployment_profile: str
    thinking: str = ""
    reasoning_effort: str = ""
    identity_hash: str = ""
    schema_version: str = CORPUS_ANALYSIS_ROUTE_SCHEMA_VERSION

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "profile_revision": self.profile_revision,
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url.rstrip("/"),
            "transport": self.transport,
            "expected_response_model": self.expected_response_model,
            "deployment_profile": self.deployment_profile,
        }
        # Keep v1 route hashes backward-compatible for frozen jobs created
        # before role-level thinking controls were auditable.  New routes
        # include the effective options in the identity hash so changing
        # xhigh/max cannot be hidden behind the same provider/model tuple.
        if self.thinking:
            payload["thinking"] = self.thinking
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        return payload

    def with_hash(self) -> "FrozenCorpusAnalysisAiRoute":
        digest = _hash_json(self.identity_payload())
        return FrozenCorpusAnalysisAiRoute(
            **self.identity_payload(),
            identity_hash=digest,
        )

    def audit_payload(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["identity_hash"] = self.identity_hash
        return payload

    @classmethod
    def parse(cls, payload: Any) -> "FrozenCorpusAnalysisAiRoute":
        if not isinstance(payload, dict):
            raise CorpusAnalysisAiError(
                "research pipeline has no frozen independent-AI route; rerun the pipeline"
            )
        try:
            route = cls(
                profile_id=str(payload["profile_id"]).strip(),
                profile_revision=int(payload["profile_revision"]),
                provider=str(payload["provider"]).strip(),
                model=str(payload["model"]).strip(),
                base_url=str(payload["base_url"]).strip().rstrip("/"),
                transport=str(payload["transport"]).strip(),
                expected_response_model=str(
                    payload["expected_response_model"]
                ).strip(),
                deployment_profile=str(payload["deployment_profile"]).strip(),
                thinking=str(payload.get("thinking", "")).strip().lower(),
                reasoning_effort=str(
                    payload.get("reasoning_effort", "")
                ).strip().lower(),
                identity_hash=str(payload["identity_hash"]).strip(),
                schema_version=str(payload["schema_version"]).strip(),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CorpusAnalysisAiError(
                "frozen independent-AI route is incomplete or malformed"
            ) from exc
        if (
            route.schema_version != CORPUS_ANALYSIS_ROUTE_SCHEMA_VERSION
            or not route.profile_id
            or route.profile_revision < 1
            or not route.provider
            or not route.model
            or not route.base_url
            or route.transport != "openai_compatible"
            or route.expected_response_model != route.model
        ):
            raise CorpusAnalysisAiError(
                "frozen independent-AI route has unsupported identity fields"
            )
        if route.identity_hash != route.with_hash().identity_hash:
            raise CorpusAnalysisAiError(
                "frozen independent-AI route identity hash mismatch"
            )
        return route


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _hash_json(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _model_dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return dict(value)
    return {}


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _semantic_project_condition_terms(
    project_context: dict[str, Any],
) -> list[str]:
    """Keep registry study IDs out of indication-alignment semantics."""

    terms = [_clean_text(project_context.get("indication"))]
    registry_query = _clean_text(
        project_context.get("clinicaltrials_condition_term")
    )
    if (
        registry_query
        and not _CLINICALTRIALS_STUDY_ID_PATTERN.fullmatch(registry_query)
    ):
        terms.append(registry_query)
    return [term for term in terms if term]


def _unique_clean_values(values: Any) -> list[str]:
    if values is None:
        return []
    material = (
        values
        if isinstance(values, (list, tuple, set))
        else [values]
    )
    result: list[str] = []
    seen: set[str] = set()
    for value in material:
        cleaned = _clean_text(value)
        normalized = cleaned.casefold()
        if not cleaned or normalized in {
            "unknown",
            "not provided",
            "not_provided",
            "待确认",
            "未知",
        }:
            continue
        if normalized not in seen:
            result.append(cleaned)
            seen.add(normalized)
    return result


def _flatten_explicit_values(value: Any) -> list[str]:
    flattened: list[Any] = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for nested in item.values():
                visit(nested)
            return
        if isinstance(item, (list, tuple, set)):
            for nested in item:
                visit(nested)
            return
        if item is not None:
            flattened.append(item)

    visit(value)
    return _unique_clean_values(flattened)


def _compact_term(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.casefold())


def _contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", value))


def _matches_controlled_alias(value: str, alias: str) -> bool:
    value_clean = _clean_text(value).casefold()
    alias_clean = _clean_text(alias).casefold()
    if not value_clean or not alias_clean:
        return False
    if re.fullmatch(r"[a-z0-9]{2,8}", alias_clean):
        return bool(
            re.search(
                rf"(?<![a-z0-9]){re.escape(alias_clean)}(?![a-z0-9])",
                value_clean,
            )
        )
    value_compact = _compact_term(value_clean)
    alias_compact = _compact_term(alias_clean)
    return bool(
        value_compact == alias_compact
        or (len(alias_compact) >= 5 and alias_compact in value_compact)
    )


def _controlled_concept_matches(
    values: Iterable[str],
) -> dict[str, list[str]]:
    matches: dict[str, list[str]] = {}
    for value in values:
        original = _clean_text(value)
        if not original:
            continue
        for concept_id, aliases in _CONTROLLED_INDICATION_ALIASES.items():
            if any(_matches_controlled_alias(original, alias) for alias in aliases):
                matches.setdefault(concept_id, []).append(original)
    return matches


def _candidate_indication_relation(
    project_terms: Iterable[str], candidate_conditions: Iterable[str]
) -> dict[str, Any]:
    project_original = [
        _clean_text(item) for item in project_terms if _clean_text(item)
    ]
    source_original = [
        _clean_text(item) for item in candidate_conditions if _clean_text(item)
    ]
    expected = [_compact_term(item) for item in project_original]
    observed = [_compact_term(item) for item in source_original]
    if not expected or not observed:
        return {
            "relation": "unresolved",
            "status": "pending_medical_confirmation",
            "proof_type": "missing_project_or_source_condition",
            "policy_version": INDICATION_ALIGNMENT_POLICY_VERSION,
            "project_terms": project_original,
            "source_conditions": source_original,
        }
    if any(
        left == right
        for left in expected
        for right in observed
    ):
        return {
            "relation": "same",
            "status": "verified_same",
            "proof_type": "normalized_lexical_equivalence",
            "policy_version": INDICATION_ALIGNMENT_POLICY_VERSION,
            "project_terms": project_original,
            "source_conditions": source_original,
        }

    project_concepts = _controlled_concept_matches(project_original)
    source_concepts = _controlled_concept_matches(source_original)
    shared_concepts = sorted(set(project_concepts) & set(source_concepts))
    if shared_concepts:
        concept_id = shared_concepts[0]
        return {
            "relation": "same_controlled_alias",
            "status": "verified_controlled_alias",
            "proof_type": "controlled_translation_or_acronym",
            "policy_version": INDICATION_ALIGNMENT_POLICY_VERSION,
            "concept_id": concept_id,
            "project_terms": project_original,
            "source_conditions": source_original,
            "matched_project_terms": project_concepts[concept_id],
            "matched_source_conditions": source_concepts[concept_id],
        }

    project_scripts = {
        "cjk" if _contains_cjk(item) else "latin_or_other"
        for item in project_original
    }
    source_scripts = {
        "cjk" if _contains_cjk(item) else "latin_or_other"
        for item in source_original
    }
    if project_scripts.isdisjoint(source_scripts):
        return {
            "relation": "unresolved_cross_language",
            "status": "pending_medical_confirmation",
            "proof_type": "cross_language_lexical_non_match",
            "policy_version": INDICATION_ALIGNMENT_POLICY_VERSION,
            "project_terms": project_original,
            "source_conditions": source_original,
        }
    return {
        "relation": "unresolved",
        "status": "pending_medical_confirmation",
        "proof_type": "lexical_non_match",
        "policy_version": INDICATION_ALIGNMENT_POLICY_VERSION,
        "project_terms": project_original,
        "source_conditions": source_original,
    }


def _exact_numeric_tokens(text: str) -> set[str]:
    return {
        match.group(0).replace("，", ",").replace("％", "%")
        for match in _NUMBER_PATTERN.finditer(text)
    }


class MedicalWritingCorpusAnalysisAiService:
    """Runs and persists round-1 competitor Protocol corpus analysis."""

    def __init__(
        self,
        repository: Any,
        *,
        runtime_settings_store: Any | None = None,
        profile_provider_factory: Callable[[Any], Any] | None = None,
        active_profile_resolver: Callable[[], Any] | None = None,
        max_evidence_entries: int = 12,
        max_evidence_characters: int = 28_000,
        max_source_documents: int = 6,
    ) -> None:
        self.repository = repository
        if runtime_settings_store is None:
            from .ai_runtime_settings import runtime_ai_settings_store

            runtime_settings_store = runtime_ai_settings_store()
        self.runtime_settings_store = runtime_settings_store
        self.profile_provider_factory = profile_provider_factory
        self.active_profile_resolver = active_profile_resolver
        self.max_evidence_entries = max(1, int(max_evidence_entries))
        self.max_evidence_characters = max(10_000, int(max_evidence_characters))
        self.max_source_documents = max(1, int(max_source_documents))
        self._initialize_store()

    def freeze_active_route(self) -> dict[str, Any]:
        profile = (
            self.active_profile_resolver()
            if self.active_profile_resolver is not None
            else self.runtime_settings_store.active_profile()
        )
        if profile is None or not bool(getattr(profile, "enabled", False)):
            raise CorpusAnalysisAiError(
                "active product independent-AI profile is unavailable"
            )
        provider = self._provider_for_profile(profile)
        route = self._route_from_profile(profile)
        route = replace(
            route,
            thinking=str(getattr(provider, "default_thinking", "") or "").strip().lower(),
            reasoning_effort=str(
                getattr(provider, "default_reasoning_effort", "") or ""
            ).strip().lower(),
        ).with_hash()
        self._assert_provider_matches_route(provider, route)
        return route.audit_payload()

    def analyze(
        self,
        *,
        project_id: str,
        pipeline_id: str,
        snapshot_id: str,
        journey: Any,
        actor: str,
        frozen_route: dict[str, Any],
    ) -> dict[str, Any]:
        route = FrozenCorpusAnalysisAiRoute.parse(frozen_route)
        provider = self._resolve_frozen_provider(route)
        project_context = self._project_context(journey)
        evidence_catalog = self._evidence_catalog(
            project_id=project_id,
            snapshot_id=snapshot_id,
            project_context=project_context,
        )
        if not evidence_catalog:
            raise CorpusAnalysisAiError(
                "round-1 analysis requires current extracted Protocol source spans"
            )

        input_payload = {
            "schema_version": CORPUS_ANALYSIS_SCHEMA_VERSION,
            "prompt_version": CORPUS_ANALYSIS_PROMPT_VERSION,
            "project_id": project_id,
            "pipeline_id": pipeline_id,
            "snapshot_id": snapshot_id,
            "project_context": project_context,
            "project_context_hash": _hash_json(project_context),
            "project_target_layer": self._project_target_layer(project_context),
            "generalization_rules": corpus_generalization_prompt_contract(),
            "evidence_catalog": evidence_catalog,
            "required_output": self._output_contract(),
        }
        input_hash = _hash_json(input_payload)
        analysis_id = "mwca_" + sha256(
            (
                input_hash
                + "|"
                + route.identity_hash
                + "|"
                + CORPUS_ANALYSIS_PROMPT_VERSION
            ).encode("utf-8")
        ).hexdigest()[:24]

        existing = self.get_analysis(project_id, analysis_id)
        if existing is not None:
            return existing

        input_payload["analysis_id"] = analysis_id
        provider_output = self._run_provider(
            provider=provider,
            route=route,
            analysis_id=analysis_id,
            payload=input_payload,
        )
        raw_output, response_normalization = self._normalize_response_root(
            provider_output,
            analysis_id=analysis_id,
            project_context_hash=input_payload["project_context_hash"],
        )
        validated_output = self._validate_and_enrich(
            raw_output=raw_output,
            analysis_id=analysis_id,
            project_context_hash=input_payload["project_context_hash"],
            project_context=project_context,
            evidence_catalog=evidence_catalog,
        )
        if not validated_output["findings"]:
            rejection_reasons = "; ".join(
                str(item.get("reason") or "")
                for item in validated_output["validation_rejections"][:3]
                if str(item.get("reason") or "")
            )
            raise CorpusAnalysisAiError(
                "independent AI produced no evidence-bound corpus findings"
                + (f"; rejected: {rejection_reasons}" if rejection_reasons else ""),
                diagnostics={
                    "failure_code": "corpus_findings_rejected",
                    "validated_finding_count": 0,
                    "validation_rejection_count": len(
                        validated_output["validation_rejections"]
                    ),
                    "validation_rejections": validated_output[
                        "validation_rejections"
                    ][:8],
                    "raw_output_sha256": _hash_json(provider_output),
                    "normalized_output_sha256": _hash_json(raw_output),
                    "response_normalization": response_normalization,
                },
            )

        result = {
            "analysis_id": analysis_id,
            "project_id": project_id,
            "pipeline_id": pipeline_id,
            "snapshot_id": snapshot_id,
            "status": "completed",
            "prompt_version": CORPUS_ANALYSIS_PROMPT_VERSION,
            "schema_version": CORPUS_ANALYSIS_SCHEMA_VERSION,
            "input_hash": input_hash,
            "output_hash": _hash_json(validated_output),
            "ai_route": route.audit_payload(),
            "response_model": route.model,
            "evidence_summary_ids": [
                str(item["finding_id"]) for item in validated_output["findings"]
            ],
            "validation_rejection_count": len(
                validated_output["validation_rejections"]
            ),
            "source_inventory": self._source_inventory(evidence_catalog),
            "analysis": validated_output,
            "raw_model_output": provider_output,
            "normalized_model_output": raw_output,
            "response_normalization": response_normalization,
            "created_by": actor or "medical_manager",
            "created_at": _utc_now_iso(),
        }
        self._persist_analysis(result=result, input_payload=input_payload)
        return result

    @staticmethod
    def _normalize_response_root(
        raw_output: dict[str, Any],
        *,
        analysis_id: str,
        project_context_hash: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Repair one narrowly identified provider shape without weakening validation.

        A production DeepSeek run returned a single strict ``finding`` object
        instead of the required analysis envelope.  Treating that response as
        a terminal failure strands an otherwise evidence-bound one-finding
        analysis and repeatedly consumes the durable-job retry budget.  The
        only tolerated repair is an object whose keys are *exactly* the
        server-owned finding keys; all finding-level validation still runs
        unchanged, and the repair is persisted as an auditable response
        normalization event.  Partial roots, arrays, or objects with any
        other shape remain fail-closed.
        """
        if not isinstance(raw_output, dict):
            return raw_output, {
                "policy_version": CORPUS_ANALYSIS_RESPONSE_REPAIR_POLICY_VERSION,
                "status": "strict_root_required",
            }
        if set(raw_output) != _FINDING_KEYS:
            return raw_output, {
                "policy_version": CORPUS_ANALYSIS_RESPONSE_REPAIR_POLICY_VERSION,
                "status": "strict_root_required",
                "observed_root_keys": sorted(str(key) for key in raw_output),
            }
        return (
            {
                "schema_version": CORPUS_ANALYSIS_SCHEMA_VERSION,
                "analysis_id": analysis_id,
                "project_context_hash": project_context_hash,
                "findings": [raw_output],
                "evidence_gaps": [
                    "本批次独立AI仅返回一条已绑定发现；本轮结果不代表已穷尽全部语料模块。"
                ],
                "global_conflicts": [],
            },
            {
                "policy_version": CORPUS_ANALYSIS_RESPONSE_REPAIR_POLICY_VERSION,
                "status": "single_finding_root_repaired",
                "observed_root_keys": sorted(str(key) for key in raw_output),
                "derived_root_keys": sorted(_ROOT_KEYS),
            },
        )

    def get_analysis(
        self, project_id: str, analysis_id: str
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT result_json
                FROM {CORPUS_ANALYSIS_TABLE}
                WHERE tenant_id=? AND project_id=? AND analysis_id=?
                """,
                (TENANT_ID, project_id, analysis_id),
            ).fetchone()
        if row is None:
            return None
        return json.loads(str(row["result_json"]))

    def find_completed_analysis(
        self,
        project_id: str,
        *,
        pipeline_id: str,
        snapshot_id: str,
        route_identity_hash: str = "",
    ) -> dict[str, Any] | None:
        """Find one immutable completed analysis for an exact pipeline lineage.

        This is a read-only recovery lookup.  It intentionally keys on the
        persisted pipeline, snapshot, and (when available) frozen route
        identity so a restart or a late parent projection write can bind an
        already-completed artifact without invoking the model again.  Round-2
        artifacts are excluded by the exact pipeline-id predicate (they carry
        the ``:round2`` suffix).
        """
        clean_project = str(project_id or "").strip()
        clean_pipeline = str(pipeline_id or "").strip()
        clean_snapshot = str(snapshot_id or "").strip()
        if not clean_project or not clean_pipeline or not clean_snapshot:
            return None
        predicates = [
            "tenant_id=?",
            "project_id=?",
            "pipeline_id=?",
            "snapshot_id=?",
            "status='completed'",
        ]
        params: list[str] = [
            TENANT_ID,
            clean_project,
            clean_pipeline,
            clean_snapshot,
        ]
        clean_route = str(route_identity_hash or "").strip()
        if clean_route:
            predicates.append("route_identity_hash=?")
            params.append(clean_route)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT result_json
                FROM {CORPUS_ANALYSIS_TABLE}
                WHERE {' AND '.join(predicates)}
                ORDER BY created_at DESC, analysis_id DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        if row is None:
            return None
        try:
            result = json.loads(str(row["result_json"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return result if isinstance(result, dict) else None

    def _route_from_profile(self, profile: Any) -> FrozenCorpusAnalysisAiRoute:
        return FrozenCorpusAnalysisAiRoute(
            profile_id=str(profile.profile_id),
            profile_revision=int(profile.revision),
            provider=str(profile.provider),
            model=str(profile.model),
            base_url=str(profile.base_url).rstrip("/"),
            transport=str(profile.transport),
            expected_response_model=str(
                profile.expected_response_model or profile.model
            ),
            deployment_profile=str(profile.deployment_profile),
        ).with_hash()

    def _provider_for_profile(self, profile: Any) -> Any:
        if self.profile_provider_factory is not None:
            return self.profile_provider_factory(profile)
        from .ai_gateway import configured_ai_provider_from_env

        base_env: dict[str, str] = {}
        api_key_env = str(getattr(profile, "api_key_env", "") or "")
        if api_key_env and os.environ.get(api_key_env):
            base_env[api_key_env] = os.environ[api_key_env]
        return configured_ai_provider_from_env(
            self.runtime_settings_store.profile_env(profile, base_env)
        )

    def _resolve_frozen_provider(
        self, route: FrozenCorpusAnalysisAiRoute
    ) -> Any:
        try:
            profile = self.runtime_settings_store.profile(route.profile_id)
        except KeyError as exc:
            raise CorpusAnalysisAiError(
                f"frozen product independent-AI profile was deleted: {route.profile_id}"
            ) from exc
        if int(profile.revision) != route.profile_revision:
            raise CorpusAnalysisAiError(
                "frozen product independent-AI profile revision changed "
                f"(expected {route.profile_revision}, current {profile.revision})"
            )
        provider = self._provider_for_profile(profile)
        base_route = self._route_from_profile(profile)
        current_route = replace(
            base_route,
            thinking=str(getattr(provider, "default_thinking", "") or "")
            .strip()
            .lower(),
            reasoning_effort=str(
                getattr(provider, "default_reasoning_effort", "") or ""
            )
            .strip()
            .lower(),
        ).with_hash()
        expected_identity_hash = (
            current_route.identity_hash
            if route.thinking or route.reasoning_effort
            else base_route.identity_hash
        )
        if expected_identity_hash != route.identity_hash:
            raise CorpusAnalysisAiError(
                "frozen product independent-AI profile identity changed"
            )
        self._assert_provider_matches_route(provider, route)
        return provider

    @staticmethod
    def _assert_provider_matches_route(
        provider: Any, route: FrozenCorpusAnalysisAiRoute
    ) -> None:
        provider_name = str(getattr(provider, "provider_name", ""))
        model_name = str(getattr(provider, "model_name", ""))
        base_url = str(getattr(provider, "base_url", "")).rstrip("/")
        transport = str(getattr(provider, "transport_name", ""))
        expected_response_model = str(
            getattr(provider, "expected_response_model", "") or model_name
        )
        if (
            provider_name != route.provider
            or model_name != route.model
            or base_url != route.base_url
            or transport != route.transport
            or expected_response_model != route.expected_response_model
        ):
            raise CorpusAnalysisAiError(
                "resolved provider identity does not match frozen product route"
            )
        if route.thinking and str(
            getattr(provider, "default_thinking", "") or ""
        ).strip().lower() != route.thinking:
            raise CorpusAnalysisAiError(
                "resolved provider thinking mode does not match frozen product route"
            )
        if route.reasoning_effort and str(
            getattr(provider, "default_reasoning_effort", "") or ""
        ).strip().lower() != route.reasoning_effort:
            raise CorpusAnalysisAiError(
                "resolved provider reasoning effort does not match frozen product route"
            )

    def _run_provider(
        self,
        *,
        provider: Any,
        route: FrozenCorpusAnalysisAiRoute,
        analysis_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        from .ai_gateway import AiPromptEnvelope, AiTaskType

        envelope = AiPromptEnvelope(
            task_id=analysis_id,
            task_type=AiTaskType.COMPETITIVE_INTELLIGENCE,
            prompt_version=CORPUS_ANALYSIS_PROMPT_VERSION,
            system_prompt=self._system_prompt(),
            payload=payload,
            reasoning_effort="low",
            max_output_tokens=32_768,
        )
        try:
            result = provider.run(envelope)
        except Exception as exc:
            # Keep the provider boundary fail-closed, but carry only the
            # gateway's sanitized shape/transport diagnostics into the
            # durable pipeline context. Raw response bodies and credentials
            # must never be persisted or shown to the user.
            from .ai_gateway import AiProviderRuntimeError

            if isinstance(exc, AiProviderRuntimeError):
                diagnostics = getattr(exc, "diagnostics", {}) or {}
                failure_code = str(diagnostics.get("failure_code") or "")
                detail = failure_code or str(exc)
                raise CorpusAnalysisAiError(
                    "independent AI provider response was not valid: " + detail,
                    diagnostics=diagnostics,
                ) from exc
            if isinstance(exc, (TimeoutError, socket.timeout)):
                raise CorpusAnalysisAiError(
                    "product independent-AI corpus analysis timed out without a validated result"
                ) from exc
            raise
        if not isinstance(result, dict):
            raise CorpusAnalysisAiError(
                "independent AI returned a non-object corpus analysis"
            )
        response_model = str(getattr(provider, "response_model", "") or "")
        if response_model != route.model:
            raise CorpusAnalysisAiError(
                "independent AI response model does not match the frozen route"
            )
        return result

    def _project_context(self, journey: Any) -> dict[str, Any]:
        framing = getattr(journey, "framing", None)
        if framing is None:
            raise CorpusAnalysisAiError("authoring journey framing is required")
        profile = getattr(framing, "product_profile", None)
        structured_design = getattr(framing, "structured_design", None)
        return {
            "indication": _clean_text(getattr(framing, "indication", "")),
            "clinicaltrials_condition_term": _clean_text(
                getattr(framing, "clinicaltrials_condition_term", "")
            ),
            "study_phase": _clean_text(getattr(framing, "study_phase", "")),
            "research_purposes": [
                _clean_text(item)
                for item in (getattr(framing, "intrinsic_objectives", None) or [])
                if _clean_text(item)
            ],
            "investigational_product": _clean_text(
                getattr(framing, "investigational_product", "")
            ),
            "target_mechanism": _clean_text(
                getattr(framing, "target_mechanism", "")
            ),
            "technology_type": _clean_text(
                getattr(profile, "technology_type", "")
            ),
            "technology_description": _clean_text(
                getattr(profile, "technology_description", "")
            ),
            "dosage_forms": [
                _clean_text(item)
                for item in (getattr(profile, "dosage_forms", None) or [])
                if _clean_text(item)
            ],
            "administration_routes": [
                _clean_text(item)
                for item in (getattr(profile, "administration_routes", None) or [])
                if _clean_text(item)
            ],
            "design": _model_dump(structured_design),
        }

    @staticmethod
    def _project_target_layer(
        project_context: dict[str, Any],
    ) -> dict[str, list[str]]:
        indication_values = _unique_clean_values(
            [
                project_context.get("indication"),
                project_context.get("clinicaltrials_condition_term"),
            ]
        )
        for aliases in _CONTROLLED_INDICATION_ALIASES.values():
            if any(
                _matches_controlled_alias(project_term, alias)
                for project_term in indication_values
                for alias in aliases
            ):
                indication_values = _unique_clean_values(
                    [*indication_values, *aliases]
                )
        design_values = _flatten_explicit_values(
            project_context.get("design")
        )
        return {
            "indication": indication_values,
            "phase": _unique_clean_values(
                [project_context.get("study_phase")]
            ),
            "research_purpose": _unique_clean_values(
                project_context.get("research_purposes")
            ),
            "mechanism": _unique_clean_values(
                [project_context.get("target_mechanism")]
            ),
            "technology_type": _unique_clean_values(
                [project_context.get("technology_type")]
            ),
            "dosage_form": _unique_clean_values(
                project_context.get("dosage_forms")
            ),
            "administration_route": _unique_clean_values(
                project_context.get("administration_routes")
            ),
            "design_module": design_values,
        }

    def _evidence_catalog(
        self,
        *,
        project_id: str,
        snapshot_id: str,
        project_context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        snapshot = self.repository.search_snapshot(project_id, snapshot_id)
        candidate_by_nct = {
            str(candidate.nct_id): candidate for candidate in snapshot.candidates
        }
        translations_by_span: dict[str, list[Any]] = {}
        for translation in self.repository.translations(project_id):
            translations_by_span.setdefault(str(translation.span_id), []).append(
                translation
            )

        project_terms = _semantic_project_condition_terms(project_context)
        per_artifact: list[list[dict[str, Any]]] = []
        for artifact in self.repository.document_artifacts(
            project_id, snapshot_id=snapshot_id
        ):
            if not bool(getattr(artifact, "source_current", False)):
                continue
            if (
                str(getattr(artifact, "document_type", "") or "")
                .strip()
                .casefold()
                not in _PROTOCOL_DOCUMENT_TYPES
            ):
                continue
            try:
                revision = self.repository.latest_extraction_revision(
                    project_id, artifact.artifact_id
                )
                extraction_reader = getattr(
                    self.repository, "extraction_result", None
                )
                if extraction_reader is not None:
                    extraction = extraction_reader(
                        project_id,
                        artifact.artifact_id,
                        revision,
                    )
                    ocr_projection = (
                        self.repository.effective_ocr_consistency_qc(
                            project_id,
                            artifact.artifact_id,
                            revision,
                        )
                    )
                    if ocr_projection.effective_status not in {
                        "pass",
                        "medical_confirmed_with_residual_issue",
                    }:
                        continue
                spans = self.repository.source_spans(
                    project_id,
                    artifact.artifact_id,
                    extraction_revision=revision,
                )
                protocol_span_ids, _ = protocol_corpus_span_scope(artifact, spans)
                spans = [
                    span
                    for span in spans
                    if str(getattr(span, "span_id", "") or "")
                    in protocol_span_ids
                ]
            except KeyError:
                continue
            candidate = candidate_by_nct.get(str(artifact.nct_id))
            candidate_payload = _model_dump(candidate)
            candidate_conditions = list(candidate_payload.get("conditions") or [])
            indication_alignment = _candidate_indication_relation(
                project_terms, candidate_conditions
            )
            ranked_spans = sorted(
                spans,
                key=lambda span: (
                    0
                    if str(getattr(span, "ich_m11_anchor", ""))
                    in _CRITICAL_ANCHORS
                    else 1,
                    int(getattr(span, "physical_page", 0) or 0),
                    int(getattr(span, "block_index", 0) or 0),
                ),
            )
            artifact_entries: list[dict[str, Any]] = []
            for span in ranked_spans[:8]:
                source_text = _clean_text(getattr(span, "source_text", ""))
                if not source_text:
                    continue
                translated_text = ""
                translations = sorted(
                    translations_by_span.get(str(span.span_id), []),
                    key=lambda item: int(getattr(item, "revision", 0) or 0),
                    reverse=True,
                )
                for translation in translations:
                    if (
                        str(getattr(translation, "fidelity_status", ""))
                        == "passed"
                        and not str(getattr(translation, "status", "")).startswith(
                            "invalidated"
                        )
                    ):
                        translated_text = _clean_text(
                            getattr(translation, "translated_text", "")
                        )
                        break
                evidence_text = source_text
                if translated_text:
                    evidence_text += "\n受控中文译文：" + translated_text
                evidence_text = evidence_text[:3_200]
                evidence_id = "cae_" + sha256(
                    (
                        str(artifact.artifact_id)
                        + "|"
                        + str(span.span_id)
                        + "|"
                        + str(getattr(span, "source_text_sha256", ""))
                    ).encode("utf-8")
                ).hexdigest()[:24]
                artifact_entries.append(
                    {
                        "evidence_id": evidence_id,
                        "nct_id": str(artifact.nct_id),
                        "source_id": str(artifact.artifact_id),
                        "source_file": str(artifact.filename),
                        "document_type": str(artifact.document_type),
                        "document_sha256": str(artifact.content_sha256),
                        "span_id": str(span.span_id),
                        "source_text_sha256": str(span.source_text_sha256),
                        "locator": str(span.source_locator),
                        "physical_page": int(span.physical_page),
                        "section_heading": str(span.section_heading),
                        "ich_m11_anchor": str(span.ich_m11_anchor),
                        "lead_sponsor": str(
                            candidate_payload.get("lead_sponsor") or ""
                        ),
                        "conditions": candidate_conditions,
                        "phases": list(candidate_payload.get("phases") or []),
                        "interventions": list(
                            candidate_payload.get("interventions") or []
                        ),
                        "design": {
                            "allocation": str(
                                candidate_payload.get("design_allocation") or ""
                            ),
                            "intervention_model": str(
                                candidate_payload.get("design_intervention_model")
                                or ""
                            ),
                            "masking": str(
                                candidate_payload.get("design_masking") or ""
                            ),
                        },
                        "indication_relation": indication_alignment["relation"],
                        "indication_alignment": indication_alignment,
                        "evidence_text": evidence_text,
                    }
                )
            if artifact_entries:
                per_artifact.append(artifact_entries)

        # Round 1 is a bounded, breadth-first analysis rather than an
        # unbounded whole-document dump. Prefer sponsor diversity, then fill
        # remaining document slots deterministically. The persisted source
        # inventory and evidence gaps make the sampled boundary visible.
        selected_groups: list[list[dict[str, Any]]] = []
        seen_sponsors: set[str] = set()
        for entries in per_artifact:
            sponsor = _clean_text(entries[0].get("lead_sponsor"))
            sponsor_key = sponsor.casefold()
            if sponsor_key and sponsor_key not in seen_sponsors:
                selected_groups.append(entries)
                seen_sponsors.add(sponsor_key)
                if len(selected_groups) >= self.max_source_documents:
                    break
        if len(selected_groups) < self.max_source_documents:
            selected_source_ids = {
                str(entries[0]["source_id"]) for entries in selected_groups
            }
            for entries in per_artifact:
                if str(entries[0]["source_id"]) in selected_source_ids:
                    continue
                selected_groups.append(entries)
                if len(selected_groups) >= self.max_source_documents:
                    break
        per_artifact = selected_groups

        selected: list[dict[str, Any]] = []
        char_count = 0
        position = 0
        while len(selected) < self.max_evidence_entries:
            added = False
            for entries in per_artifact:
                if position >= len(entries):
                    continue
                item = entries[position]
                size = len(str(item["evidence_text"]))
                if selected and char_count + size > self.max_evidence_characters:
                    return selected
                selected.append(item)
                char_count += size
                added = True
                if len(selected) >= self.max_evidence_entries:
                    break
            if not added:
                break
            position += 1
        return selected

    @staticmethod
    def _source_inventory(
        evidence_catalog: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        inventory: dict[str, dict[str, Any]] = {}
        for evidence in evidence_catalog:
            source_id = str(evidence["source_id"])
            inventory.setdefault(
                source_id,
                {
                    "source_id": source_id,
                    "nct_id": evidence["nct_id"],
                    "source_file": evidence["source_file"],
                    "document_type": evidence["document_type"],
                    "document_sha256": evidence["document_sha256"],
                    "lead_sponsor": evidence["lead_sponsor"],
                    "conditions": evidence["conditions"],
                    "phases": evidence["phases"],
                    "span_count_in_analysis": 0,
                },
            )
            inventory[source_id]["span_count_in_analysis"] += 1
        return sorted(inventory.values(), key=lambda item: item["source_id"])

    def _validate_and_enrich(
        self,
        *,
        raw_output: dict[str, Any],
        analysis_id: str,
        project_context_hash: str,
        project_context: dict[str, Any],
        evidence_catalog: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if set(raw_output) != _ROOT_KEYS:
            missing = sorted(_ROOT_KEYS - set(raw_output))
            unexpected = sorted(set(raw_output) - _ROOT_KEYS)
            raise CorpusAnalysisAiError(
                "corpus analysis root keys do not match the strict schema "
                f"(missing={missing}, unexpected={unexpected})"
            )
        if raw_output.get("schema_version") != CORPUS_ANALYSIS_SCHEMA_VERSION:
            raise CorpusAnalysisAiError("corpus analysis schema_version mismatch")
        if raw_output.get("analysis_id") != analysis_id:
            raise CorpusAnalysisAiError("corpus analysis_id mismatch")
        if raw_output.get("project_context_hash") != project_context_hash:
            raise CorpusAnalysisAiError(
                "corpus analysis project_context_hash mismatch"
            )
        if not isinstance(raw_output.get("findings"), list):
            raise CorpusAnalysisAiError("corpus analysis findings must be an array")
        if not isinstance(raw_output.get("evidence_gaps"), list):
            raise CorpusAnalysisAiError(
                "corpus analysis evidence_gaps must be an array"
            )
        if not isinstance(raw_output.get("global_conflicts"), list):
            raise CorpusAnalysisAiError(
                "corpus analysis global_conflicts must be an array"
            )

        evidence_by_id = {
            str(item["evidence_id"]): item for item in evidence_catalog
        }
        findings: list[dict[str, Any]] = []
        validation_rejections: list[dict[str, str]] = []
        seen_finding_ids: set[str] = set()
        for raw_finding in raw_output["findings"]:
            raw_finding_id = (
                _clean_text(raw_finding.get("finding_id"))
                if isinstance(raw_finding, dict)
                else ""
            )
            try:
                finding = self._validate_finding(
                    raw_finding,
                    evidence_by_id,
                    project_context=project_context,
                )
            except CorpusAnalysisAiError as exc:
                validation_rejections.append(
                    {
                        "item_type": "finding",
                        "item_id": raw_finding_id or "unidentified_finding",
                        "reason": str(exc),
                    }
                )
                continue
            finding_id = str(finding["finding_id"])
            if finding_id in seen_finding_ids:
                raise CorpusAnalysisAiError(
                    f"duplicate corpus finding_id: {finding_id}"
                )
            seen_finding_ids.add(finding_id)
            findings.append(finding)

        global_conflicts = []
        for index, item in enumerate(raw_output["global_conflicts"]):
            try:
                global_conflicts.append(
                    self._validate_global_conflict(item, evidence_by_id)
                )
            except CorpusAnalysisAiError as exc:
                validation_rejections.append(
                    {
                        "item_type": "global_conflict",
                        "item_id": f"global_conflict_{index + 1}",
                        "reason": str(exc),
                    }
                )
        gaps = []
        for item in raw_output["evidence_gaps"]:
            text = _clean_text(item)
            if not text:
                raise CorpusAnalysisAiError(
                    "corpus analysis evidence gaps must be non-empty strings"
                )
            gaps.append(text)
        return {
            "schema_version": CORPUS_ANALYSIS_SCHEMA_VERSION,
            "analysis_id": analysis_id,
            "project_context_hash": project_context_hash,
            "findings": findings,
            "evidence_gaps": gaps,
            "global_conflicts": global_conflicts,
            "validation_rejections": validation_rejections,
        }

    def _validate_finding(
        self,
        raw_finding: Any,
        evidence_by_id: dict[str, dict[str, Any]],
        *,
        project_context: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(raw_finding, dict) or set(raw_finding) != _FINDING_KEYS:
            raise CorpusAnalysisAiError(
                "corpus finding keys do not match the strict schema"
            )
        finding_id = _clean_text(raw_finding["finding_id"])
        statement = _clean_text(raw_finding["statement_zh"])
        module = _clean_text(raw_finding["module"])
        pattern_kind = _clean_text(raw_finding["pattern_kind"])
        transfer_scope = _clean_text(raw_finding["transfer_scope"])
        if not finding_id or not statement:
            raise CorpusAnalysisAiError(
                "corpus finding_id and statement_zh are required"
            )
        if module not in _ANALYSIS_MODULES:
            raise CorpusAnalysisAiError(f"unsupported corpus module: {module}")
        if pattern_kind not in CORPUS_PATTERN_KINDS:
            raise CorpusAnalysisAiError(
                f"unsupported corpus pattern_kind: {pattern_kind}"
            )
        if transfer_scope not in _TRANSFER_SCOPES:
            raise CorpusAnalysisAiError(
                f"unsupported corpus transfer_scope: {transfer_scope}"
            )
        if pattern_kind == "regulatory_common_structure":
            if module not in _CROSS_INDICATION_MODULES:
                raise CorpusAnalysisAiError(
                    "regulatory_common_structure requires structure or "
                    "regulatory_commonality module"
                )
        elif module in _CROSS_INDICATION_MODULES:
            raise CorpusAnalysisAiError(
                "structure and regulatory_commonality modules require "
                "regulatory_common_structure pattern_kind"
            )
        if (
            transfer_scope == "cross_indication_structure_only"
            and pattern_kind != "regulatory_common_structure"
        ):
            raise CorpusAnalysisAiError(
                "cross-indication transfer requires "
                "regulatory_common_structure pattern_kind"
            )
        layer = self._validate_layer(raw_finding["layer"])
        bindings = self._validate_bindings(
            raw_finding["evidence_bindings"], evidence_by_id
        )
        layer, layer_rejections = self._sanitize_layer_source_binding(
            layer, bindings, evidence_by_id
        )
        indication_alignments = [
            evidence_by_id[item["evidence_id"]]["indication_alignment"]
            for item in bindings
        ]
        pending_cross_language_alignment = False
        if transfer_scope == "same_indication":
            permitted_relations = {
                "same",
                "same_controlled_alias",
                "unresolved_cross_language",
            }
            invalid_relations = [
                str(item.get("relation") or "")
                for item in indication_alignments
                if str(item.get("relation") or "") not in permitted_relations
            ]
            if invalid_relations:
                raise CorpusAnalysisAiError(
                    "same-indication finding has an unverified source binding"
                )
            pending_alignments = [
                item
                for item in indication_alignments
                if item.get("relation") == "unresolved_cross_language"
            ]
            if pending_alignments:
                project_terms = _semantic_project_condition_terms(
                    project_context
                )
                if not any(project_terms) or any(
                    not item.get("source_conditions")
                    for item in pending_alignments
                ):
                    raise CorpusAnalysisAiError(
                        "cross-language same-indication proposal lacks bound "
                        "source condition text or project context"
                    )
                pending_cross_language_alignment = True
        if transfer_scope == "cross_indication_structure_only":
            if module not in _CROSS_INDICATION_MODULES:
                raise CorpusAnalysisAiError(
                    "cross-indication findings may only cover structure or regulatory commonality"
                )
            policy_scope, blocked = cross_indication_transfer_scope(statement)
            if policy_scope != "structure_or_regulatory_common_only" or blocked:
                raise CorpusAnalysisAiError(
                    "cross-indication finding contains non-transferable clinical logic"
                )
        self._validate_numeric_claims(statement, bindings, evidence_by_id)

        conflicts = [
            self._validate_conflict(item, evidence_by_id)
            for item in raw_finding["conflicts"]
        ]
        unresolved_gaps = []
        if not isinstance(raw_finding["unresolved_gaps"], list):
            raise CorpusAnalysisAiError("unresolved_gaps must be an array")
        for item in raw_finding["unresolved_gaps"]:
            text = _clean_text(item)
            if not text:
                raise CorpusAnalysisAiError(
                    "unresolved_gaps must contain non-empty strings"
                )
            unresolved_gaps.append(text)

        support_records = self._support_records(
            statement=statement,
            pattern_kind=pattern_kind,
            layer=layer,
            bindings=bindings,
            evidence_by_id=evidence_by_id,
        )
        for conflict in conflicts:
            support_records.extend(
                self._support_records(
                    statement=conflict["claim_value_zh"],
                    pattern_kind=pattern_kind,
                    layer=layer,
                    bindings=conflict["evidence_bindings"],
                    evidence_by_id=evidence_by_id,
                )
            )
        target_layer = self._project_target_layer(project_context)
        assessment = assess_corpus_support(
            support_records,
            pattern_kind=pattern_kind,
            target_layer=target_layer,
        )
        support = asdict(assessment)
        self._validate_generalization_claim(
            statement=statement,
            support=support,
            bound_source_count=len(
                {
                    evidence_by_id[item["evidence_id"]]["document_sha256"]
                    or evidence_by_id[item["evidence_id"]]["source_id"]
                    for item in bindings
                }
            ),
        )
        if pending_cross_language_alignment:
            support["high_confidence_eligible"] = False
            support["reasons"] = list(support.get("reasons") or [])
            if "same_indication_cross_language_alignment_pending" not in support[
                "reasons"
            ]:
                support["reasons"].append(
                    "same_indication_cross_language_alignment_pending"
                )
        if not self._single_binding_substantiates(
            statement=statement,
            layer=layer,
            bindings=bindings,
            evidence_by_id=evidence_by_id,
        ):
            if support["high_confidence_eligible"]:
                support["high_confidence_eligible"] = False
            support["reasons"] = list(support.get("reasons") or [])
            if "single_binding_co_observability_not_met" not in support["reasons"]:
                support["reasons"].append(
                    "single_binding_co_observability_not_met"
                )
        self._append_server_evidence_gaps(
            unresolved_gaps=unresolved_gaps,
            support=support,
        )
        target_layer_confirmation_required = any(
            str(reason).startswith(
                (
                    "target_layer_incomplete:",
                    "target_layer_metadata_missing:",
                )
            )
            for reason in support.get("reasons") or []
        )
        if pending_cross_language_alignment or target_layer_confirmation_required:
            confidence = "requires_medical_review"
        elif support["high_confidence_eligible"]:
            confidence = "high"
        elif assessment.conflicting_values:
            confidence = "requires_medical_review"
        elif assessment.source_count >= 2:
            confidence = "moderate"
        else:
            confidence = "low"
        content_role = self._content_role(
            pattern_kind=pattern_kind,
            module=module,
        )
        evidence_tier = self._evidence_tier(
            transfer_scope=transfer_scope,
            layer=layer,
            target_layer=target_layer,
        )
        reuse_decision = self._reuse_decision(
            content_role=content_role,
            confidence=confidence,
            support=support,
        )

        return {
            "finding_id": finding_id,
            "module": module,
            "pattern_kind": pattern_kind,
            "content_role": content_role,
            "evidence_tier": evidence_tier,
            "reuse_decision": reuse_decision,
            "statement_zh": statement,
            "transfer_scope": transfer_scope,
            "layer": layer,
            "layer_rejections": layer_rejections,
            "evidence_bindings": self._enrich_bindings(
                bindings, evidence_by_id
            ),
            "conflicts": [
                {
                    **item,
                    "evidence_bindings": self._enrich_bindings(
                        item["evidence_bindings"], evidence_by_id
                    ),
                }
                for item in conflicts
            ],
            "unresolved_gaps": unresolved_gaps,
            "indication_alignment_status": (
                "pending_medical_confirmation"
                if pending_cross_language_alignment
                else (
                    "verified_controlled_alias"
                    if any(
                        item.get("relation") == "same_controlled_alias"
                        for item in indication_alignments
                    )
                    else "verified_same"
                )
                if transfer_scope == "same_indication"
                else "not_applicable"
            ),
            "indication_alignment_proofs": indication_alignments,
            "support": support,
            "confidence": confidence,
        }

    @staticmethod
    def _content_role(*, pattern_kind: str, module: str) -> str:
        exact = _CONTENT_ROLE_BY_PATTERN_AND_MODULE.get(
            (pattern_kind, module)
        )
        if exact is not None:
            return exact
        return _CONTENT_ROLE_BY_PATTERN_AND_MODULE[(pattern_kind, "*")]

    @staticmethod
    def _evidence_tier(
        *,
        transfer_scope: str,
        layer: dict[str, list[str]],
        target_layer: dict[str, list[str]],
    ) -> str:
        if transfer_scope == "same_indication":
            return "tier1_same_indication_layered"
        source_design = {
            _clean_text(item).casefold()
            for item in layer.get("design_modules", [])
            if _clean_text(item)
        }
        target_design = {
            _clean_text(item).casefold()
            for item in target_layer.get("design_module", [])
            if _clean_text(item)
        }
        if source_design and target_design and source_design & target_design:
            return "tier2_related_domain_or_design_structure_reference"
        return "tier3_cross_indication_structure_only"

    @staticmethod
    def _reuse_decision(
        *,
        content_role: str,
        confidence: str,
        support: dict[str, Any],
    ) -> str:
        if support.get("conflicting_values"):
            return "conflict_preserved_do_not_select"
        if (
            int(support.get("source_count") or 0) < 2
            or int(support.get("sponsor_count") or 0) < 2
        ):
            return "insufficient_support_do_not_generalize"
        if content_role == "project_fact_reference":
            return "project_fact_reference_only"
        if confidence == "high":
            return "evidence_supported_candidate"
        return "medical_review_required"

    @staticmethod
    def _validate_generalization_claim(
        *,
        statement: str,
        support: dict[str, Any],
        bound_source_count: int,
    ) -> None:
        source_count = int(support.get("source_count") or 0)
        sponsor_count = int(support.get("sponsor_count") or 0)
        if (
            bound_source_count < 2
            and _MULTI_SOURCE_ASSERTION_PATTERN.search(statement)
        ):
            raise CorpusAnalysisAiError(
                "corpus statement claims multiple sources but fewer than two "
                "independent sources substantiate it"
            )
        if (
            _GENERALIZED_USAGE_ASSERTION_PATTERN.search(statement)
            and (
                source_count < 2
                or sponsor_count < 2
                or not bool(support.get("high_confidence_eligible"))
            )
        ):
            raise CorpusAnalysisAiError(
                "corpus statement uses generalized usage wording without "
                "high-confidence same-layer multi-source support"
            )

    @staticmethod
    def _append_server_evidence_gaps(
        *,
        unresolved_gaps: list[str],
        support: dict[str, Any],
    ) -> None:
        source_count = int(support.get("source_count") or 0)
        sponsor_count = int(support.get("sponsor_count") or 0)
        derived: list[str] = []
        if source_count < 2:
            derived.append(
                "服务器校验：独立来源不足（当前"
                f"{source_count}，至少需要2）；不得据此归纳适应症常用措辞或设计规则。"
            )
        if sponsor_count < 2:
            derived.append(
                "服务器校验：独立申办方不足（当前"
                f"{sponsor_count}，至少需要2）；需补充其他申办方证据后再评估可迁移性。"
            )
        existing = {item.casefold() for item in unresolved_gaps}
        unresolved_gaps.extend(
            item for item in derived if item.casefold() not in existing
        )

    @staticmethod
    def _validate_layer(raw_layer: Any) -> dict[str, list[str]]:
        if not isinstance(raw_layer, dict) or set(raw_layer) != set(_LAYER_KEYS):
            raise CorpusAnalysisAiError(
                "corpus finding layer must contain every required dimension"
            )
        result: dict[str, list[str]] = {}
        for key in _LAYER_KEYS:
            if not isinstance(raw_layer[key], list):
                raise CorpusAnalysisAiError(f"layer.{key} must be an array")
            values = [_clean_text(item) for item in raw_layer[key]]
            if any(not item for item in values) or len(values) != len(set(values)):
                raise CorpusAnalysisAiError(
                    f"layer.{key} must contain unique non-empty strings"
                )
            result[key] = values
        return result

    @staticmethod
    def _validate_bindings(
        raw_bindings: Any,
        evidence_by_id: dict[str, dict[str, Any]],
    ) -> list[dict[str, str]]:
        if not isinstance(raw_bindings, list) or not raw_bindings:
            raise CorpusAnalysisAiError(
                "every corpus claim requires at least one evidence binding"
            )
        bindings: list[dict[str, str]] = []
        seen: set[str] = set()
        for raw in raw_bindings:
            if not isinstance(raw, dict) or set(raw) != _BINDING_KEYS:
                raise CorpusAnalysisAiError(
                    "evidence binding keys do not match the strict schema"
                )
            evidence_id = _clean_text(raw["evidence_id"])
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                raise CorpusAnalysisAiError(
                    f"unknown corpus evidence_id: {evidence_id}"
                )
            if evidence_id in seen:
                raise CorpusAnalysisAiError("duplicate corpus evidence binding")
            seen.add(evidence_id)
            bindings.append({"evidence_id": evidence_id})
        return bindings

    def _validate_conflict(
        self,
        raw_conflict: Any,
        evidence_by_id: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        if (
            not isinstance(raw_conflict, dict)
            or set(raw_conflict) != _CONFLICT_KEYS
        ):
            raise CorpusAnalysisAiError(
                "corpus conflict keys do not match the strict schema"
            )
        value = _clean_text(raw_conflict["claim_value_zh"])
        if not value:
            raise CorpusAnalysisAiError("conflict claim_value_zh is required")
        bindings = self._validate_bindings(
            raw_conflict["evidence_bindings"], evidence_by_id
        )
        self._validate_numeric_claims(value, bindings, evidence_by_id)
        return {"claim_value_zh": value, "evidence_bindings": bindings}

    def _validate_global_conflict(
        self,
        raw_conflict: Any,
        evidence_by_id: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        if (
            not isinstance(raw_conflict, dict)
            or set(raw_conflict) != _GLOBAL_CONFLICT_KEYS
        ):
            raise CorpusAnalysisAiError(
                "global conflict keys do not match the strict schema"
            )
        description = _clean_text(raw_conflict["description_zh"])
        if not description:
            raise CorpusAnalysisAiError(
                "global conflict description_zh is required"
            )
        bindings = self._validate_bindings(
            raw_conflict["evidence_bindings"], evidence_by_id
        )
        self._validate_numeric_claims(description, bindings, evidence_by_id)
        return {
            "description_zh": description,
            "evidence_bindings": self._enrich_bindings(
                bindings, evidence_by_id
            ),
        }

    @staticmethod
    def _validate_numeric_claims(
        statement: str,
        bindings: list[dict[str, str]],
        evidence_by_id: dict[str, dict[str, Any]],
    ) -> None:
        claim_numbers = _exact_numeric_tokens(statement)
        if not claim_numbers:
            return
        evidence_text = "\n".join(
            MedicalWritingCorpusAnalysisAiService._binding_support_text(
                evidence_by_id[item["evidence_id"]]
            )
            for item in bindings
        )
        evidence_numbers = _exact_numeric_tokens(evidence_text)
        missing = sorted(claim_numbers - evidence_numbers)
        if missing:
            raise CorpusAnalysisAiError(
                "numeric corpus claim is not present in bound evidence: "
                + ",".join(missing)
            )

    @staticmethod
    def _binding_support_text(evidence: dict[str, Any]) -> str:
        return "\n".join(
            [
                str(evidence["evidence_text"]),
                str(evidence["nct_id"]),
                str(evidence["source_file"]),
                str(evidence["locator"]),
                str(evidence["section_heading"]),
                " ".join(str(item) for item in evidence["phases"]),
            ]
        )

    @staticmethod
    def _single_binding_substantiates(
        statement: str,
        layer: dict[str, list[str]],
        bindings: list[dict[str, str]],
        evidence_by_id: dict[str, dict[str, Any]],
    ) -> bool:
        """Return True if at least one binding independently substantiates
        all numeric claims in *statement* and all non-empty values in
        *layer* within its own evidence text.

        Deterministic single-binding co-observability guard for Cluster A
        (G1/G2/G7).  Prevents a composite finding whose atomic facts are
        scattered across separate bindings from reaching high confidence,
        without restructuring the layer tuple schema.
        """
        claim_numbers = _exact_numeric_tokens(statement)
        for binding in bindings:
            evidence = evidence_by_id[binding["evidence_id"]]
            support_text = (
                MedicalWritingCorpusAnalysisAiService._binding_support_text(
                    evidence
                )
            )
            if claim_numbers:
                binding_numbers = _exact_numeric_tokens(support_text)
                if not claim_numbers.issubset(binding_numbers):
                    continue
            binding_context = _compact_term(support_text)
            all_present = True
            for values in layer.values():
                for value in values:
                    compact = _compact_term(value)
                    if compact and compact not in binding_context:
                        all_present = False
                        break
                if not all_present:
                    break
            if all_present:
                return True
        return False

    @staticmethod
    def _sanitize_layer_source_binding(
        layer: dict[str, list[str]],
        bindings: list[dict[str, str]],
        evidence_by_id: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, list[str]], list[str]]:
        bound_parts: list[str] = []
        for binding in bindings:
            evidence = evidence_by_id[binding["evidence_id"]]
            bound_parts.extend(
                [
                    str(evidence["evidence_text"]),
                    " ".join(str(item) for item in evidence["conditions"]),
                    " ".join(str(item) for item in evidence["phases"]),
                    _canonical_json(evidence["interventions"]),
                    _canonical_json(evidence["design"]),
                ]
            )
        bound_context = _compact_term(" ".join(bound_parts))
        sanitized: dict[str, list[str]] = {}
        unsupported: list[str] = []
        for axis, values in layer.items():
            accepted_values: list[str] = []
            for value in values:
                compact = _compact_term(value)
                if compact and compact in bound_context:
                    accepted_values.append(value)
                elif compact:
                    unsupported.append(f"{axis}:{value}")
            sanitized[axis] = accepted_values
        return sanitized, unsupported

    @staticmethod
    def _support_records(
        *,
        statement: str,
        pattern_kind: str,
        layer: dict[str, list[str]],
        bindings: list[dict[str, str]],
        evidence_by_id: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for item in bindings:
            evidence = evidence_by_id[item["evidence_id"]]
            source_layer = (
                MedicalWritingCorpusAnalysisAiService._source_layer_for_evidence(
                    layer, evidence
                )
            )
            records.append(
                {
                    "source_id": evidence["source_id"],
                    "source_file": evidence["source_file"],
                    "document_sha256": evidence["document_sha256"],
                    "lead_sponsor": evidence["lead_sponsor"],
                    "pattern_kind": pattern_kind,
                    "claim_value": statement,
                    "layer": source_layer,
                }
            )
        return records

    @staticmethod
    def _source_layer_for_evidence(
        finding_layer: dict[str, list[str]],
        evidence: dict[str, Any],
    ) -> dict[str, list[str]]:
        # G8 fix: the indication axis must be checked against the span's own
        # evidence_text, NOT the artifact-level conditions list (which for
        # basket trials may include the target indication even though the
        # span text only supports a different one).
        span_text_compact = _compact_term(str(evidence["evidence_text"]))
        bound_context = _compact_term(
            " ".join(
                [
                    str(evidence["evidence_text"]),
                    " ".join(str(item) for item in evidence["conditions"]),
                    " ".join(str(item) for item in evidence["phases"]),
                    _canonical_json(evidence["interventions"]),
                    _canonical_json(evidence["design"]),
                ]
            )
        )
        source_layer = {key: [] for key in _LAYER_KEYS}
        artifact_phases = _unique_clean_values(evidence["phases"])
        artifact_phase_components = {
            component
            for value in artifact_phases
            for component in _canonical_phase_components(value)
        }
        if len(artifact_phase_components) <= 1:
            source_layer["phases"] = artifact_phases
        else:
            explicit_phase_tokens = _phase_tokens_explicit_in_text(
                str(evidence["evidence_text"])
            )
            bound_phase_values: list[str] = []
            for token in explicit_phase_tokens:
                if token.startswith("combined:"):
                    components = token.removeprefix("combined:").split("+")
                    if set(components).issubset(artifact_phase_components):
                        bound_phase_values.append(
                            "PHASE"
                            + "/".join(
                                component.upper() for component in components
                            )
                        )
                elif token in artifact_phase_components:
                    bound_phase_values.append(f"PHASE{token.upper()}")
            source_layer["phases"] = sorted(
                bound_phase_values,
                key=lambda value: (
                    len(_canonical_phase_components(value)),
                    value,
                ),
            )
        source_layer["design_modules"] = _flatten_explicit_values(
            evidence["design"]
        )
        source_conditions = _unique_clean_values(evidence["conditions"])
        source_layer["indications"] = _unique_clean_values(
            [
                condition
                for condition in source_conditions
                if _compact_term(condition) in span_text_compact
            ]
        )
        condition_concepts = _controlled_concept_matches(source_conditions)
        # Controlled acronym/translation expansion requires both an
        # artifact-level condition match and span-level text support. This
        # prevents ambiguous short aliases such as "RA" from relabelling an
        # unrelated study.
        for concept_id, aliases in _CONTROLLED_INDICATION_ALIASES.items():
            if concept_id not in condition_concepts:
                continue
            if any(
                _matches_controlled_alias(
                    str(evidence["evidence_text"]),
                    alias,
                )
                for alias in aliases
            ):
                source_layer["indications"] = _unique_clean_values(
                    [*source_layer["indications"], *aliases]
                )
        for axis in _LAYER_KEYS:
            for value in finding_layer.get(axis, []):
                compact = _compact_term(value)
                if not compact:
                    continue
                if axis == "indications":
                    # G8: only accept indication values that are textually
                    # present in the span's own evidence_text, not the
                    # artifact-level bound_context which may include
                    # unrelated basket conditions.
                    value_concepts = _controlled_concept_matches([value])
                    controlled_condition_matches = (
                        not value_concepts
                        or bool(set(value_concepts) & set(condition_concepts))
                    )
                    if (
                        compact in span_text_compact
                        and controlled_condition_matches
                    ):
                        source_layer[axis] = _unique_clean_values(
                            [*source_layer[axis], value]
                        )
                elif axis == "phases":
                    if compact in {
                        _compact_term(item)
                        for item in source_layer["phases"]
                    }:
                        source_layer[axis] = _unique_clean_values(
                            [*source_layer[axis], value]
                        )
                elif compact in bound_context:
                    source_layer[axis] = _unique_clean_values(
                        [*source_layer[axis], value]
                    )
        return source_layer

    @staticmethod
    def _enrich_bindings(
        bindings: list[dict[str, str]],
        evidence_by_id: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        result = []
        for binding in bindings:
            evidence = evidence_by_id[binding["evidence_id"]]
            result.append(
                {
                    **binding,
                    "source_excerpt": evidence["evidence_text"],
                    "nct_id": evidence["nct_id"],
                    "source_id": evidence["source_id"],
                    "source_file": evidence["source_file"],
                    "document_sha256": evidence["document_sha256"],
                    "span_id": evidence["span_id"],
                    "source_text_sha256": evidence["source_text_sha256"],
                    "locator": evidence["locator"],
                    "physical_page": evidence["physical_page"],
                    "lead_sponsor": evidence["lead_sponsor"],
                    "conditions": evidence["conditions"],
                    "phases": evidence["phases"],
                    "indication_relation": evidence["indication_relation"],
                    "indication_alignment": evidence["indication_alignment"],
                }
            )
        return result

    @staticmethod
    def _output_contract() -> dict[str, Any]:
        layer = {key: ["string"] for key in _LAYER_KEYS}
        binding = {"evidence_id": "one evidence_catalog.evidence_id"}
        return {
            "additional_properties": False,
            "root_keys": sorted(_ROOT_KEYS),
            "finding": {
                "additional_properties": False,
                "keys": sorted(_FINDING_KEYS),
                "server_derived_fields": {
                    "content_role": [
                        "structure_template",
                        "regulatory_fixed_wording",
                        "indication_specific_wording",
                        "project_fact_reference",
                    ],
                    "evidence_tier": [
                        "tier1_same_indication_layered",
                        "tier2_related_domain_or_design_structure_reference",
                        "tier3_cross_indication_structure_only",
                    ],
                    "reuse_decision": [
                        "evidence_supported_candidate",
                        "project_fact_reference_only",
                        "medical_review_required",
                        "insufficient_support_do_not_generalize",
                        "conflict_preserved_do_not_select",
                    ],
                },
                "module": sorted(_ANALYSIS_MODULES),
                "pattern_kind": sorted(CORPUS_PATTERN_KINDS),
                "transfer_scope": sorted(_TRANSFER_SCOPES),
                "layer": layer,
                "evidence_bindings": [binding],
                "conflicts": [
                    {
                        "claim_value_zh": "source-faithful alternative claim",
                        "evidence_bindings": [binding],
                    }
                ],
                "unresolved_gaps": ["string"],
            },
            "global_conflict": {
                "description_zh": "string",
                "evidence_bindings": [binding],
            },
        }

    @staticmethod
    def _system_prompt() -> str:
        return (
            "你是医学写作工作台内部的竞品Protocol语料分析器。"
            "你不是Codex、外部会商模型或医学批准者，只能分析payload.evidence_catalog。"
            "输出必须是严格JSON对象，不得输出Markdown或解释文字。"
            "根对象必须且只能包含schema_version、analysis_id、project_context_hash、"
            "findings、evidence_gaps、global_conflicts六个键；不得增加summary、"
            "metadata、support或其他顶层字段。"
            "每条finding必须绑定一个或多个已提供的evidence_id；不得生成新ID。"
            "服务器将依据evidence_id自动附加原文、定位和哈希，模型不得复述或改写引文"
            "来代替来源绑定。"
            "所有数字、阈值、时间点、剂量、样本量和比例必须逐字存在于绑定证据，"
            "不允许用常识补齐。"
            "每条finding必须且只能选择一种pattern_kind："
            "wording_convention表示同适应症、同分层下的表达措辞惯例；"
            "clinical_design_requirement表示由疾病、分期、研究目的、机制/技术、"
            "剂型/途径和设计共同约束的临床设计要求；"
            "regulatory_common_structure仅表示可受限迁移的监管共性或章节结构。"
            "三类不得混合、替代或用监管结构标签包装临床设计结论。"
            "服务器硬性映射规则如下，必须逐字遵守：module=structure或"
            "module=regulatory_commonality时，pattern_kind必须是"
            "regulatory_common_structure；这两个module不得使用wording_convention或"
            "clinical_design_requirement。其余module不得使用"
            "regulatory_common_structure；若结论是疾病/分期/设计共同约束的临床要求，"
            "使用clinical_design_requirement；若只是同适应症分层下的表达惯例，使用"
            "wording_convention。该字段不可省略、不可留空、不可由服务器猜测。"
            "分析顺序必须遵循三级证据层级：第一层优先归纳同适应症且其他设计维度匹配的"
            "证据；第二层同疾病领域或相近研究设计只用于提出结构参照、备选假设和反例，"
            "不得据此制造该适应症的常用措辞或临床规则；第三层其他适应症仅可用于监管共性"
            "和章节结构。不得因为研究设计相似而越过适应症边界迁移疾病特异内容。"
            "模型输出的每条finding还必须在语义上只承担一种内容角色：章节结构模板、"
            "监管固定语、适应症特异措辞或项目事实参照；服务器将根据pattern_kind和module"
            "派生并持久化content_role、evidence_tier和reuse_decision，模型不得在statement_zh"
            "中混写这些角色，也不得自行在finding中输出这三个服务器派生字段。"
            "必须按适应症、分期、研究目的、作用机制/技术类型、剂型、给药途径、"
            "设计模块八个维度显式分层。layer描述的是绑定竞品来源，不是当前项目目标；"
            "每个非空层值必须逐字存在于绑定evidence_text或其登记元数据，"
            "未知维度使用空数组，不得把project_context值复制为竞品事实。"
            "跨适应症只允许pattern_kind=regulatory_common_structure且module为"
            "structure或regulatory_commonality；不同适应症的表达措辞惯例和临床设计"
            "逻辑均不得泛化，不得迁移疾病活动度、量表阈值、终点、背景治疗、洗脱、"
            "安全性风险、访视或时间窗。"
            "跨语言字面不匹配不等于不同适应症：若项目中文适应症与来源英文conditions"
            "可能为同一疾病，可提出same_indication，但必须绑定含原始conditions的"
            "evidence_id并以project_context为项目依据；服务器将用版本化受控同义词/"
            "缩写证明，无法证明时保守标记待医学确认，绝不得静默改为跨适应症临床迁移。"
            "同适应症也必须按分期、研究目的、机制、技术类型、剂型、途径和设计继续分层。"
            "当前是Round 1分层抽样分析；只总结已提供证据，并在evidence_gaps列出"
            "本批次未覆盖的来源、章节或设计维度，不得声称已穷尽全部竞品方案。"
            "发现来源差异时必须保留conflicts，不得多数表决消除。"
            "不得从单个项目、单份方案或单一申办方总结“常用”“通常”“普遍采用”等"
            "措辞规律；只有至少两个独立文档且来自至少两个申办方、关键含义一致时，"
            "才可提出多来源支持的候选模式。证据不足时必须降级为低置信参考并在"
            "unresolved_gaps说明缺失的独立来源、申办方和分层证据；不得用“多份方案”、"
            "“均采用”“常用”“通常”或“普遍采用”等措辞扩大证据范围。"
            "不得自行声明高置信；系统将根据独立来源数、申办方数和冲突重新计算。"
            "单一来源、单一申办方、骨架、placeholder、corpus override或无证据内容"
            "均不得成为PASS或高置信结论。"
            "再次强调：最外层必须是完整的analysis envelope；即使只有一条发现，"
            "也必须返回包含六个根键的对象，不能直接返回finding对象，不能把finding的"
            "finding_id、statement_zh、layer或evidence_bindings提升为根键。"
            "请把最终可解析的JSON对象放在assistant message.content中；reasoning_content"
            "仅用于思考，不能作为最终结果，也不能只返回思考内容。"
            "输出形状示例（仅示意，必须替换为本次真实值）："
            "{\"schema_version\":\"...\",\"analysis_id\":\"...\","
            "\"project_context_hash\":\"...\",\"findings\":[],"
            "\"evidence_gaps\":[],\"global_conflicts\":[]}。"
            "即使没有可用发现也不得返回空字符串；应返回完整对象并让服务器拒绝无证据结果。"
        )

    def _connect(self) -> sqlite3.Connection:
        db_path = getattr(self.repository, "db_path", None)
        if db_path is None:
            raise CorpusAnalysisAiError(
                "writing-reference repository does not expose a durable database"
            )
        connection = sqlite3.connect(str(db_path), timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize_store(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {CORPUS_ANALYSIS_TABLE} (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    analysis_id TEXT NOT NULL,
                    pipeline_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status='completed'),
                    prompt_version TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    output_hash TEXT NOT NULL,
                    route_identity_hash TEXT NOT NULL,
                    route_json TEXT NOT NULL,
                    input_payload_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, analysis_id)
                );
                CREATE TRIGGER IF NOT EXISTS trg_wref_corpus_analysis_no_update
                BEFORE UPDATE ON {CORPUS_ANALYSIS_TABLE} BEGIN
                    SELECT RAISE(
                        ABORT,
                        'writing reference corpus analysis runs are immutable'
                    );
                END;
                CREATE TRIGGER IF NOT EXISTS trg_wref_corpus_analysis_no_delete
                BEFORE DELETE ON {CORPUS_ANALYSIS_TABLE} BEGIN
                    SELECT RAISE(
                        ABORT,
                        'writing reference corpus analysis runs are immutable'
                    );
                END;
                """
            )

    def _persist_analysis(
        self,
        *,
        result: dict[str, Any],
        input_payload: dict[str, Any],
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                f"""
                SELECT input_hash, output_hash
                FROM {CORPUS_ANALYSIS_TABLE}
                WHERE tenant_id=? AND project_id=? AND analysis_id=?
                """,
                (TENANT_ID, result["project_id"], result["analysis_id"]),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["input_hash"]) != result["input_hash"]
                    or str(existing["output_hash"]) != result["output_hash"]
                ):
                    connection.rollback()
                    raise CorpusAnalysisAiError(
                        "immutable corpus analysis artifact changed"
                    )
                connection.rollback()
                return
            connection.execute(
                f"""
                INSERT INTO {CORPUS_ANALYSIS_TABLE}(
                    tenant_id, project_id, analysis_id, pipeline_id,
                    snapshot_id, status, prompt_version, schema_version,
                    input_hash, output_hash, route_identity_hash, route_json,
                    input_payload_json, result_json, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_ID,
                    result["project_id"],
                    result["analysis_id"],
                    result["pipeline_id"],
                    result["snapshot_id"],
                    result["status"],
                    result["prompt_version"],
                    result["schema_version"],
                    result["input_hash"],
                    result["output_hash"],
                    result["ai_route"]["identity_hash"],
                    _canonical_json(result["ai_route"]),
                    _canonical_json(input_payload),
                    _canonical_json(result),
                    result["created_by"],
                    result["created_at"],
                ),
            )
            append_audit = getattr(self.repository, "_append_audit", None)
            if callable(append_audit):
                append_audit(
                    connection,
                    result["project_id"],
                    "competitor_protocol_corpus_analysis_completed",
                    result["analysis_id"],
                    result["created_by"],
                    {
                        "pipeline_id": result["pipeline_id"],
                        "snapshot_id": result["snapshot_id"],
                        "prompt_version": result["prompt_version"],
                        "schema_version": result["schema_version"],
                        "input_hash": result["input_hash"],
                        "output_hash": result["output_hash"],
                        "route_identity_hash": result["ai_route"][
                            "identity_hash"
                        ],
                        "provider": result["ai_route"]["provider"],
                        "model": result["ai_route"]["model"],
                        "finding_count": len(result["analysis"]["findings"]),
                    },
                )
            connection.commit()
