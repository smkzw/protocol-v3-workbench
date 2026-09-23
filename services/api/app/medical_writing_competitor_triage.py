"""Product-owned independent-AI competitor Protocol relevance triage.

This service implements an audited, chunk-based batch AI triage between the
frozen ClinicalTrials.gov snapshot and deterministic document preparation.

Key invariants:
- Uses the existing direct OpenAI-compatible provider abstraction.
- Exact configured-model identity verification on every response.
- One versioned JSON prompt/schema.
- Hash canonical input and validated canonical output.
- Never allows model-created NCTs or documents.
- Deterministic chunking. Each response validated as a complete exact
  permutation of its chunk.
- Allowed classes only: direct_competitor, indirect_reference, excluded.
- Persists run/chunk/result/provenance in writing_reference.sqlite3.
- Partial failure preserves successful chunks; retry only failed chunks.
- Stale detection from snapshot identity/hash, journey revision, and material
  fact hash.
- One basket-confirm command: atomically persist the authoritative confirmation
  and every selected/excluded relevance decision; then project to authoring
  journey corpus triage. If projection fails, persist ``projection_pending``;
  retry projection without a second user approval.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import sqlite3
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple

from packages.contracts.workbench_contracts import (
    CompetitorTriageBasketConfirmationRequest,
    CompetitorTriageBasketReconfirmationRequest,
    CompetitorTriageCandidateResult,
    CompetitorTriageChunkRecord,
    CompetitorTriageChunkStatus,
    CompetitorTriageClassification,
    CompetitorTriageConfirmationRecord,
    CompetitorTriageCreateRequest,
    CompetitorTriageMatchingDimension,
    CompetitorTriageProjectionRetryRequest,
    CompetitorTriageReconfirmationStatus,
    CompetitorTriageProvenance,
    CompetitorTriageRetryRequest,
    CompetitorTriageRun,
    CompetitorTriageRunResponse,
    CompetitorTriageRunStatus,
    CompetitorTriageRunSummary,
    DurableJobCreateRequest,
    DurableJobProgressPayload,
    DurableJobRecord,
    DurableJobRequestConflict,
    MedicalWritingAuthoringJourney,
    MedicalWritingCompetitorSearchExecuteRequest,
    MedicalWritingCorpusTriageFinalizeRequest,
    WritingReferenceSearchSnapshot,
    WritingReferenceTrialCandidate,
)

from .writing_reference_repository import (
    TENANT_ID,
    WritingReferenceConflictError,
    WritingReferenceRepository,
    _canonical_json,
    _utc_now as _repo_utc_now,
)
from .medical_writing_authoring_prefill import effective_authoring_values

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TRIAGE_PROMPT_VERSION = (
    "competitor_triage_v20_derived_full_name_abbreviations"
)
TRIAGE_SCHEMA_VERSION = "competitor_triage_v1"
TRIAGE_MODEL_NAME = "deepseek-v4-pro"
TRIAGE_PROVIDER_NAME = "deepseek"
TRIAGE_TRANSPORT_NAME = "openai_compatible"
TRIAGE_BASE_URL = "https://api.deepseek.com/v1"
MAX_CANDIDATES_PER_CHUNK = 8
# The old 15-item batch remains the compatibility default for the public
# deterministic-chunk helper.  New production runs first remove only
# source-proven corpus-ineligible records and then use a separately bounded
# AI batch.  Both bounds are deliberate: item count constrains response
# completeness and serialized input size constrains Token Plan latency.
MAX_AI_CANDIDATES_PER_CHUNK = 5
MAX_AI_CHUNK_INPUT_CHARS = 25_000
MAX_AI_CHUNK_OUTPUT_TOKENS = 24_000
MAX_DETERMINISTIC_RESULTS_PER_CHUNK = 250
TRIAGE_DETERMINISTIC_POLICY_VERSION = "competitor_triage_registry_gate_v2"
_DETERMINISTIC_CHUNK_PREFIX = "ct_det_"
TRIAGE_DURABLE_JOB_TYPE = "competitor_triage"
TRIAGE_ROUTE_SNAPSHOT_VERSION = "competitor_triage_ai_route_v2"
TRIAGE_LEGACY_ROUTE_SNAPSHOT_VERSION = "competitor_triage_ai_route_v1"
TRIAGE_ROUTE_CHAIN_VERSION = "competitor_triage_ai_route_chain_v1"
TRIAGE_FALLBACK_HTTP_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
TRIAGE_LEGACY_ROUTE_ERROR = (
    "legacy competitor-triage durable job has no frozen AI route; "
    "cancel it and submit an explicit retry to create a versioned route snapshot"
)

_ALLOWED_CLASSIFICATIONS = frozenset(
    {c.value for c in CompetitorTriageClassification}
)
_MATCH_DIMENSIONS = (
    "indication",
    "phase",
    "modality",
    "route",
    "target_mechanism",
    "design",
)


class CompetitorTriageError(ValueError):
    """Raised for triage validation or state errors."""


class CompetitorTriageStaleError(CompetitorTriageError):
    """Raised when a run is stale and cannot be confirmed."""


class CompetitorTriageConflictError(CompetitorTriageError):
    """Raised for duplicate or concurrent-write conflicts."""


@dataclass(frozen=True)
class FrozenTriageAiRoute:
    """Auditable, secret-free independent-AI route captured at job creation."""

    profile_id: str
    profile_revision: int
    provider: str
    model: str
    base_url: str
    transport: str
    expected_response_model: str
    deployment_profile: str
    source: str
    thinking: str = ""
    reasoning_effort: str = ""
    identity_hash: str = ""
    schema_version: str = TRIAGE_ROUTE_SNAPSHOT_VERSION

    def identity_payload(self) -> Dict[str, Any]:
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
            "source": self.source,
        }
        if self.schema_version == TRIAGE_ROUTE_SNAPSHOT_VERSION:
            payload.update(
                {
                    "thinking": self.thinking,
                    "reasoning_effort": self.reasoning_effort,
                }
            )
        return payload

    def with_hash(self) -> "FrozenTriageAiRoute":
        identity_hash = sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()
        return FrozenTriageAiRoute(
            **self.identity_payload(),
            identity_hash=identity_hash,
        )

    def audit_payload(self) -> Dict[str, Any]:
        payload = self.identity_payload()
        payload["identity_hash"] = self.identity_hash
        return payload

    @classmethod
    def parse(cls, payload: Any) -> "FrozenTriageAiRoute":
        if not isinstance(payload, dict):
            raise CompetitorTriageError(TRIAGE_LEGACY_ROUTE_ERROR)
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
                source=str(payload["source"]).strip(),
                thinking=str(payload.get("thinking", "")).strip().lower(),
                reasoning_effort=str(
                    payload.get("reasoning_effort", "")
                ).strip().lower(),
                identity_hash=str(payload["identity_hash"]).strip(),
                schema_version=str(payload["schema_version"]).strip(),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CompetitorTriageError(
                "durable AI route snapshot is incomplete or malformed"
            ) from exc
        if (
            route.schema_version not in {
                TRIAGE_LEGACY_ROUTE_SNAPSHOT_VERSION,
                TRIAGE_ROUTE_SNAPSHOT_VERSION,
            }
            or not route.profile_id
            or route.profile_revision < 1
            or not route.provider
            or not route.model
            or not route.base_url
            or route.source not in {"runtime_profile", "test_override"}
            or route.thinking not in {"", "enabled", "disabled"}
            or route.reasoning_effort not in {
                "", "low", "medium", "high", "xhigh", "max"
            }
        ):
            raise CompetitorTriageError(
                "durable AI route snapshot has unsupported identity fields"
            )
        expected_hash = route.with_hash().identity_hash
        if route.identity_hash != expected_hash:
            raise CompetitorTriageError(
                "durable AI route snapshot identity hash mismatch"
            )
        return route


# ---------------------------------------------------------------------------
# Provider protocol
# ---------------------------------------------------------------------------


class TriageProvider(Protocol):
    """Minimal provider contract that every injected provider must satisfy.

    Production: built from configured_ai_provider_from_env(), wrapped to expose
    the verified identity. Tests: a strict fake returning canned responses.
    """

    provider_name: str
    model_name: str
    response_model: str

    def triage_run(
        self, system_prompt: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Run the model with the given system prompt + JSON payload.

        Must return the parsed JSON dict from the model response.
        Implementations are responsible for verifying response_model identity.
        """
        ...


class VerifiedTriageProvider:
    """Wraps the existing AiProvider to expose the triage-specific contract.

    Uses AiPromptEnvelope internally with the active product-owned independent
    AI provider. Production calls fail closed unless the configured model is
    also the exact response-model identity returned by that provider.
    """

    def __init__(self, inner: Any, *, test_only_injection: bool = False) -> None:
        self._inner = inner
        self.provider_name = getattr(inner, "provider_name", "")
        configured_model = getattr(inner, "model_name", "")
        self.base_url = str(getattr(inner, "base_url", "")).rstrip("/")
        self.transport_name = getattr(inner, "transport_name", "") or (
            TRIAGE_TRANSPORT_NAME if self.base_url else ""
        )
        self.expected_response_model = getattr(
            inner, "expected_response_model", ""
        )
        self.default_thinking = getattr(inner, "default_thinking", "") or ""
        self.default_reasoning_effort = (
            getattr(inner, "default_reasoning_effort", "") or ""
        )
        if test_only_injection:
            if self.provider_name != TRIAGE_PROVIDER_NAME:
                raise CompetitorTriageError(
                    f"provider_name must be exactly '{TRIAGE_PROVIDER_NAME}', "
                    f"got '{self.provider_name}'"
                )
            if configured_model != TRIAGE_MODEL_NAME:
                raise CompetitorTriageError(
                    f"provider model_name must be exactly '{TRIAGE_MODEL_NAME}', "
                    f"got '{configured_model}'"
                )
        elif not self.provider_name or not configured_model:
            raise CompetitorTriageError(
                "production triage provider and model identity are required"
            )
        self.model_name = configured_model
        self._test_only_injection = bool(test_only_injection)
        if not self._test_only_injection:
            from .ai_gateway import (
                ALIBABA_TOKEN_PLAN_BASE_URL,
                ALIBABA_TOKEN_PLAN_MODEL,
                ALIBABA_TOKEN_PLAN_PROVIDER,
                DEEPSEEK_COMPATIBLE_GATEWAY_BASE_URLS,
                DEEPSEEK_COMPATIBLE_GATEWAY_MODELS,
                DIRECT_DEEPSEEK_BASE_URL,
                DIRECT_DEEPSEEK_MODELS,
            )

            base_url = self.base_url
            if self.transport_name != TRIAGE_TRANSPORT_NAME:
                raise CompetitorTriageError(
                    f"provider transport must be exactly '{TRIAGE_TRANSPORT_NAME}', "
                    f"got '{self.transport_name}'"
                )
            if not base_url:
                raise CompetitorTriageError(
                    "production triage provider base_url is required"
                )
            if self.provider_name == "deepseek":
                direct_route = (
                    base_url == DIRECT_DEEPSEEK_BASE_URL
                    and configured_model in DIRECT_DEEPSEEK_MODELS
                )
                gateway_route = (
                    base_url in DEEPSEEK_COMPATIBLE_GATEWAY_BASE_URLS
                    and configured_model in DEEPSEEK_COMPATIBLE_GATEWAY_MODELS
                )
                if not direct_route and not gateway_route:
                    raise CompetitorTriageError(
                        "provider base_url/model does not match the configured DeepSeek product route"
                    )
            pinned_routes = {
                ALIBABA_TOKEN_PLAN_PROVIDER: (
                    ALIBABA_TOKEN_PLAN_BASE_URL,
                    frozenset({ALIBABA_TOKEN_PLAN_MODEL}),
                ),
            }
            pinned_route = pinned_routes.get(self.provider_name)
            if pinned_route is not None:
                expected_base_url, allowed_models = pinned_route
                if base_url != expected_base_url or configured_model not in allowed_models:
                    raise CompetitorTriageError(
                        "provider base_url/model does not match the pinned product route"
                    )
            # The provider may serve a renamed response id (DeepSeek serves
            # 'deepseek-flash' for v4-flash requests): accept the calibrated
            # expectation as long as both ids belong to the pinned route's
            # model family (requirements-v2 T17 round-1 finding).
            _deepseek_family = {
                "deepseek-v4-flash",
                "deepseek-flash",
                "deepseek-latest-cloud",
            }
            if (
                self.expected_response_model != configured_model
                and not (
                    configured_model in _deepseek_family
                    and self.expected_response_model in _deepseek_family
                )
            ):
                raise CompetitorTriageError(
                    "provider expected_response_model must match configured model "
                    f"'{configured_model}', got '{self.expected_response_model}'"
                )
        self._response_model = ""

    def triage_run(
        self, system_prompt: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        from .ai_gateway import AiPromptEnvelope, AiTaskType

        envelope = AiPromptEnvelope(
            task_id=str(payload.get("run_id", payload.get("chunk_id", "triage"))),
            task_type=AiTaskType.COMPETITIVE_INTELLIGENCE,
            prompt_version=TRIAGE_PROMPT_VERSION,
            system_prompt=system_prompt,
            payload=payload,
            max_output_tokens=MAX_AI_CHUNK_OUTPUT_TOKENS,
        )
        result = self._inner.run(envelope)
        if not isinstance(result, dict):
            raise CompetitorTriageError("provider returned a non-dict response")
        # The OpenAICompatibleAiProvider verifies response model identity via
        # expected_response_model (the profile's calibrated response id —
        # DeepSeek renamed the served v4-flash id to deepseek-flash).  The
        # check below accepts either the request name or the calibrated
        # response name; anything else stays rejected.
        response_model = getattr(self._inner, "response_model", "") or ""
        _acceptable = {
            identity
            for identity in (
                self.model_name,
                getattr(self._inner, "expected_response_model", "") or "",
            )
            if identity
        }
        if response_model not in _acceptable:
            raise CompetitorTriageError(
                f"provider response_model must be exactly '{self.model_name}', "
                f"got '{response_model}'"
            )
        self._response_model = response_model
        return result

    @property
    def response_model(self) -> str:
        return self._response_model


class FallbackTriageProvider:
    """Run a frozen ordered provider chain without changing business input."""

    def __init__(
        self,
        providers: List[Tuple[FrozenTriageAiRoute, VerifiedTriageProvider]],
        *,
        frozen_route_hashes: List[str] | None = None,
    ) -> None:
        if not providers:
            raise CompetitorTriageError("triage provider chain is empty")
        self._providers = providers
        self._active_index = 0
        self._attempted_index = 0
        self.fallback_reason = ""
        self.fallback_chain_id = "ctfb_" + sha256(
            _canonical_json(
                frozen_route_hashes
                or [route.identity_hash for route, _provider in providers]
            ).encode("utf-8")
        ).hexdigest()[:24]

    @staticmethod
    def _fallback_reason(exc: Exception) -> str:
        from .ai_gateway import AiProviderRuntimeError

        if not isinstance(exc, AiProviderRuntimeError):
            return ""
        diagnostics = dict(exc.diagnostics or {})
        failure_code = str(diagnostics.get("failure_code") or "")
        if failure_code == "provider_http_error":
            try:
                status = int(diagnostics.get("http_status"))
            except (TypeError, ValueError):
                return ""
            # Every 5xx is a server-side condition (R13: the local MTPLX
            # saturates under concurrent triage load and answers 507) — the
            # fallback chain must absorb it instead of failing the chunk.
            if 500 <= status <= 599 or status in TRIAGE_FALLBACK_HTTP_STATUSES:
                return f"{failure_code}:{status}"
            return ""
        if failure_code in {"provider_transport_error", "provider_response_empty"}:
            return failure_code
        return ""

    @property
    def _active(self) -> Tuple[FrozenTriageAiRoute, VerifiedTriageProvider]:
        return self._providers[self._attempted_index]

    @property
    def provider_name(self) -> str:
        return self._active[1].provider_name

    @property
    def response_model(self) -> str:
        return self._active[1].response_model

    @property
    def route_profile_id(self) -> str:
        return self._active[0].profile_id

    @property
    def route_identity_hash(self) -> str:
        return self._active[0].identity_hash

    @property
    def fallback_depth(self) -> int:
        return self._active_index

    def triage_run(
        self, system_prompt: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        last_error: Exception | None = None
        for index in range(self._active_index, len(self._providers)):
            _route, provider = self._providers[index]
            self._attempted_index = index
            try:
                result = provider.triage_run(system_prompt, payload)
            except Exception as exc:
                reason = self._fallback_reason(exc)
                if not reason or index == len(self._providers) - 1:
                    raise
                self.fallback_reason = reason
                last_error = exc
                continue
            self._active_index = index
            self._attempted_index = index
            return result
        assert last_error is not None
        raise last_error


# ---------------------------------------------------------------------------
# Hash / canonical helpers
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json_local(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _hash_value(value: Any) -> str:
    return sha256(_canonical_json_local(value).encode("utf-8")).hexdigest()


def _snapshot_hash(snapshot: WritingReferenceSearchSnapshot) -> str:
    """Deterministic hash of the snapshot identity and candidates."""
    material = {
        "snapshot_id": snapshot.snapshot_id,
        "query_url": snapshot.query_url,
        "api_version": snapshot.api_version,
        "data_timestamp": snapshot.data_timestamp,
        "total_count": snapshot.total_count,
        "returned_count": snapshot.returned_count,
        "candidates": sorted(
            [
                {
                    "nct_id": c.nct_id,
                    "brief_summary": c.brief_summary,
                    "conditions": c.conditions,
                    "phases": c.phases,
                    "study_type": c.study_type,
                    "interventions": [
                        {
                            "name": intervention.name,
                            "intervention_type": intervention.intervention_type,
                        }
                        for intervention in c.interventions
                    ],
                    "design_allocation": c.design_allocation,
                    "design_intervention_model": c.design_intervention_model,
                    "design_masking": c.design_masking,
                    "enrollment_count": c.enrollment_count,
                    "lead_sponsor": c.lead_sponsor,
                    "overall_status": c.overall_status,
                    "public_documents": [
                        {
                            "document_id": doc.document_id,
                            "nct_id": doc.nct_id,
                            "document_type": doc.document_type,
                            "label": doc.label,
                            "filename": doc.filename,
                            "document_date": doc.document_date,
                            "upload_date": doc.upload_date,
                            "declared_size": doc.declared_size,
                            "download_url": doc.download_url,
                            "source_status": doc.source_status,
                            "rights_status": doc.rights_status,
                        }
                        for doc in c.public_documents
                    ],
                }
                for c in snapshot.candidates
            ],
            key=lambda x: x["nct_id"],
        ),
    }
    return _hash_value(material)


def _material_facts_hash(journey: MedicalWritingAuthoringJourney) -> str:
    """Hash of the project material facts that drive relevance."""
    framing, picos = effective_authoring_values(journey)
    condition_term, condition_term_source, search_condition_term = (
        _effective_clinicaltrials_condition_term(journey)
    )
    material = {
        "investigational_product": framing.investigational_product,
        "indication": framing.indication,
        "study_phase": framing.study_phase,
        "intrinsic_objectives": framing.intrinsic_objectives,
        "design_pattern": framing.design_pattern,
        "target_mechanism": framing.target_mechanism,
        "competitor_target_scope": framing.competitor_target_scope,
        "product_profile": {
            "technology_type": framing.product_profile.technology_type,
            "administration_routes": framing.product_profile.administration_routes,
            "dosage_forms": framing.product_profile.dosage_forms,
            "exposure_scope": framing.product_profile.exposure_scope,
        },
        "population_intent": framing.population_intent,
        "picos": {
            "population_summary": picos.population_summary if picos else "",
            "intervention_summary": picos.intervention_summary if picos else "",
            "comparator_summary": picos.comparator_summary if picos else "",
            "primary_endpoint": picos.primary_endpoint if picos else "",
        },
        "clinicaltrials_condition_term": condition_term,
        "clinicaltrials_condition_term_source": condition_term_source,
        "clinicaltrials_search_condition_term": search_condition_term,
        "journey_revision": journey.revision,
    }
    return _hash_value(material)


def _triage_retry_business_key(
    business_key: str,
    idempotency_key: str,
    incomplete_chunk_ids: List[str],
) -> str:
    """Bound a retry identity without embedding an arbitrarily long chunk set."""
    incomplete_set_hash = sha256(
        ":".join(sorted(incomplete_chunk_ids)).encode("utf-8")
    ).hexdigest()[:24]
    return f"{business_key}:retry:{idempotency_key}:{incomplete_set_hash}"


def _effective_clinicaltrials_condition_term(
    journey: MedicalWritingAuthoringJourney,
) -> Tuple[str, str, str]:
    """Return the auditable condition term used for registry-label matching.

    A user-confirmed framing term is authoritative. When it is absent, the
    exact registry condition term already used by the journey's bound search
    plan is the only safe fallback: it is retrieval provenance, not a newly
    inferred translation or disease alias.
    """
    framing, _ = effective_authoring_values(journey)
    framing_term = str(framing.clinicaltrials_condition_term or "").strip()
    search_condition_term = ""
    search_plan = getattr(journey, "search_plan", None)
    registry_filter = getattr(search_plan, "registry_filter", None)
    if registry_filter is not None:
        search_condition_term = str(
            getattr(registry_filter, "condition_term", "") or ""
        ).strip()
    if framing_term:
        return framing_term, "authoring_framing", search_condition_term
    if search_condition_term:
        return (
            search_condition_term,
            "bound_search_plan_registry_filter",
            search_condition_term,
        )
    return "", "unavailable", ""


def _deterministic_chunks(
    candidates: List[WritingReferenceTrialCandidate],
    chunk_size: int = MAX_CANDIDATES_PER_CHUNK,
) -> List[List[WritingReferenceTrialCandidate]]:
    """Split candidates into deterministic ordered chunks by sorted NCT ID."""
    ordered = sorted(candidates, key=lambda c: c.nct_id)
    if not ordered:
        return []
    num_chunks = max(1, math.ceil(len(ordered) / chunk_size))
    actual_size = math.ceil(len(ordered) / num_chunks)
    chunks: List[List[WritingReferenceTrialCandidate]] = []
    for i in range(num_chunks):
        start = i * actual_size
        end = start + actual_size
        batch = ordered[start:end]
        if batch:
            chunks.append(batch)
    return chunks


@dataclass(frozen=True)
class DeterministicTriageDisposition:
    """A source-bounded disposition made before any model call.

    ``excluded`` never means a model judged the trial clinically irrelevant.
    It means the immutable registry snapshot does not provide a candidate that
    can enter the Protocol corpus under the stated deterministic gate.  The
    candidate remains in the run with its exact source-derived reason.
    """

    nct_id: str
    action: str
    reason_code: str
    reason: str


@dataclass(frozen=True)
class TriageReductionPlan:
    """Full, auditable partition of a frozen snapshot before AI triage."""

    deterministic_chunks: List[CompetitorTriageChunkRecord]
    ai_candidate_chunks: List[List[WritingReferenceTrialCandidate]]
    disposition_counts: Dict[str, int]

    @property
    def deterministic_candidate_count(self) -> int:
        return sum(len(chunk.nct_ids) for chunk in self.deterministic_chunks)

    @property
    def ai_candidate_count(self) -> int:
        return sum(len(chunk) for chunk in self.ai_candidate_chunks)


def _candidate_payload_for_reduction(
    journey: MedicalWritingAuthoringJourney,
    candidate: WritingReferenceTrialCandidate,
) -> Dict[str, Any]:
    """Build the same canonical candidate shape sent to the AI later."""
    return _build_chunk_input(journey, [candidate], 0)["candidates"][0]


def _deterministic_triage_disposition(
    candidate: Dict[str, Any],
    project_facts: Dict[str, Any],
) -> DeterministicTriageDisposition:
    """Return the only safe no-AI dispositions for corpus triage.

    Absence is handled conservatively.  Missing intervention metadata,
    mixed populations, phase mismatch, and unspecified route/mechanism are
    retained for AI review.  We exclude only when an explicit source fact
    proves the record cannot enter a Protocol corpus.
    """
    nct_id = str(candidate.get("nct_id", "")).strip()
    intervention_state = _candidate_intervention_evidence_state(candidate)
    if intervention_state == "non_pharmacologic":
        return DeterministicTriageDisposition(
            nct_id=nct_id,
            action="excluded",
            reason_code="explicit_non_pharmacologic_intervention",
            reason=(
                "确定性未进入语料：登记的全部明确干预类型均非药物/生物制剂；"
                "未调用AI。"
            ),
        )

    document_suitability = _derive_document_suitability(candidate, "")
    if not document_suitability["has_public_protocol"]:
        return DeterministicTriageDisposition(
            nct_id=nct_id,
            action="excluded",
            reason_code="no_public_protocol",
            reason=(
                "确定性未进入语料：同适应症候选未提供公开Protocol，"
                "不能进入竞品方案语料；独立SAP不作为本语料库输入。未调用AI。"
                "该结论不等同于"
                "否定其临床研究价值。"
            ),
        )

    # Indication equivalence is deliberately not a deterministic exclusion
    # gate. Project facts are often Chinese while registry conditions are
    # English or use disease acronyms (for example PNH), and a lexical
    # non-match is not evidence of clinical mismatch. Candidates with a
    # usable Protocol therefore proceed to the independent AI even when
    # the local matcher cannot establish the relation.
    return DeterministicTriageDisposition(
        nct_id=nct_id,
        action="requires_ai",
        reason_code="requires_source_bounded_ai_triage",
        reason=(
            "候选具同适应症关系且提供公开Protocol；保留至独立AI"
            "分诊，不作确定性竞争性推断。"
        ),
    )


def _deterministic_result(
    candidate: Dict[str, Any],
    project_facts: Dict[str, Any],
    disposition: DeterministicTriageDisposition,
) -> CompetitorTriageCandidateResult:
    """Materialize a deterministic exclusion as a normal auditable result."""
    gaps: List[str] = []
    dimensions = _enforce_matching_dimensions(
        [], candidate, project_facts, gaps
    )
    dimensions = _reconcile_source_truth_dimensions(
        dimensions, candidate, project_facts
    )
    gaps.append("确定性分诊原因：" + disposition.reason_code)
    return CompetitorTriageCandidateResult(
        nct_id=disposition.nct_id,
        classification=CompetitorTriageClassification.EXCLUDED,
        confidence=1.0,
        matching_dimensions=dimensions,
        document_suitability=_derive_document_suitability(candidate, ""),
        reason=disposition.reason,
        evidence_gaps=list(dict.fromkeys(gaps)),
    )


def _ai_chunk_priority(
    candidate: Dict[str, Any],
    project_facts: Dict[str, Any],
) -> Tuple[int, int, int, str]:
    """Order, but never drop, AI candidates using explicit registry fields."""
    relation = _candidate_indication_relation(candidate, project_facts)
    relation_rank = 0 if relation == "exact" else 1
    project_phases = _normalized_phase_codes(project_facts.get("study_phase", ""))
    candidate_phases = _normalized_phase_codes(candidate.get("phases", []))
    phase_rank = (
        0
        if project_phases and candidate_phases and project_phases & candidate_phases
        else 1
        if not project_phases or not candidate_phases
        else 2
    )
    docs = _derive_document_suitability(candidate, "")
    document_rank = 0 if docs["has_public_protocol"] else 1
    return (relation_rank, phase_rank, document_rank, str(candidate["nct_id"]))


def _bounded_ai_chunks(
    journey: MedicalWritingAuthoringJourney,
    candidates: List[WritingReferenceTrialCandidate],
    project_facts: Dict[str, Any],
) -> List[List[WritingReferenceTrialCandidate]]:
    """Create deterministic, size-bounded batches for real AI calls.

    The serialized-input cap protects the configured Token Plan route from a
    large outlier brief summary.  A single oversized candidate is still sent
    alone rather than dropped.
    """
    annotated = [
        (_candidate_payload_for_reduction(journey, candidate), candidate)
        for candidate in candidates
    ]
    annotated.sort(key=lambda item: _ai_chunk_priority(item[0], project_facts))
    chunks: List[List[WritingReferenceTrialCandidate]] = []
    current: List[WritingReferenceTrialCandidate] = []
    for _, candidate in annotated:
        proposed = [*current, candidate]
        proposed_input = _build_chunk_input(journey, proposed, len(chunks))
        exceeds_count = len(proposed) > MAX_AI_CANDIDATES_PER_CHUNK
        exceeds_size = len(_canonical_json_local(proposed_input)) > MAX_AI_CHUNK_INPUT_CHARS
        if current and (exceeds_count or exceeds_size):
            chunks.append(current)
            current = [candidate]
        else:
            current = proposed
    if current:
        chunks.append(current)
    return chunks


def _build_triage_reduction_plan(
    journey: MedicalWritingAuthoringJourney,
    snapshot: WritingReferenceSearchSnapshot,
    snapshot_hash: str,
    material_facts_hash: str,
) -> TriageReductionPlan:
    """Partition every frozen NCT into deterministic or AI-required work."""
    project_facts = _build_chunk_input(journey, [], 0)["project_facts"]
    deterministic: Dict[str, List[Tuple[Dict[str, Any], DeterministicTriageDisposition]]] = {}
    ai_candidates: List[WritingReferenceTrialCandidate] = []
    counts: Dict[str, int] = {}

    for candidate in sorted(snapshot.candidates, key=lambda item: item.nct_id):
        payload = _candidate_payload_for_reduction(journey, candidate)
        disposition = _deterministic_triage_disposition(payload, project_facts)
        counts[disposition.reason_code] = counts.get(disposition.reason_code, 0) + 1
        if disposition.action == "requires_ai":
            ai_candidates.append(candidate)
            continue
        deterministic.setdefault(disposition.reason_code, []).append(
            (payload, disposition)
        )

    deterministic_chunks: List[CompetitorTriageChunkRecord] = []
    chunk_index = 0
    for reason_code in sorted(deterministic):
        entries = deterministic[reason_code]
        for start in range(0, len(entries), MAX_DETERMINISTIC_RESULTS_PER_CHUNK):
            batch = entries[start : start + MAX_DETERMINISTIC_RESULTS_PER_CHUNK]
            nct_ids = [entry[1].nct_id for entry in batch]
            input_material = {
                "policy_version": TRIAGE_DETERMINISTIC_POLICY_VERSION,
                "reason_code": reason_code,
                "snapshot_id": snapshot.snapshot_id,
                "snapshot_hash": snapshot_hash,
                "journey_revision": journey.revision,
                "material_facts_hash": material_facts_hash,
                "nct_ids": nct_ids,
            }
            input_hash = _hash_value(input_material)
            results = [
                _deterministic_result(payload, project_facts, disposition)
                for payload, disposition in batch
            ]
            deterministic_chunks.append(
                CompetitorTriageChunkRecord(
                    chunk_id=f"{_DETERMINISTIC_CHUNK_PREFIX}{input_hash[:20]}",
                    chunk_index=chunk_index,
                    nct_ids=nct_ids,
                    input_hash=input_hash,
                    status=CompetitorTriageChunkStatus.SUCCEEDED,
                    attempt=0,
                    error_message=(
                        "deterministic corpus disposition: " + reason_code
                    ),
                    provenance=CompetitorTriageProvenance(
                        provider="deterministic_registry_rules",
                        response_model="not_applicable",
                        prompt_version=TRIAGE_DETERMINISTIC_POLICY_VERSION,
                        schema_version=TRIAGE_SCHEMA_VERSION,
                        canonical_input_hash=input_hash,
                        canonical_output_hash=_hash_value(
                            [result.model_dump(mode="json") for result in results]
                        ),
                        snapshot_id=snapshot.snapshot_id,
                        snapshot_hash=snapshot_hash,
                        journey_revision=journey.revision,
                        material_facts_hash=material_facts_hash,
                        created_at=_utc_now(),
                    ),
                    results=results,
                )
            )
            chunk_index += 1

    deterministic_ids = {
        nct_id
        for chunk in deterministic_chunks
        for nct_id in chunk.nct_ids
    }
    ai_ids = {candidate.nct_id for candidate in ai_candidates}
    snapshot_ids = [candidate.nct_id for candidate in snapshot.candidates]
    if len(snapshot_ids) != len(set(snapshot_ids)):
        raise CompetitorTriageError(
            "frozen snapshot contains duplicate NCT identifiers; cannot build an auditable triage partition"
        )
    if deterministic_ids & ai_ids or deterministic_ids | ai_ids != set(snapshot_ids):
        raise CompetitorTriageError(
            "deterministic triage reduction did not produce an exact snapshot NCT partition"
        )

    return TriageReductionPlan(
        deterministic_chunks=deterministic_chunks,
        ai_candidate_chunks=_bounded_ai_chunks(
            journey, ai_candidates, project_facts
        ),
        disposition_counts=counts,
    )


def _build_chunk_input(
    journey: MedicalWritingAuthoringJourney,
    chunk: List[WritingReferenceTrialCandidate],
    chunk_index: int,
) -> Dict[str, Any]:
    """Build the canonical model input for one chunk."""
    framing, picos = effective_authoring_values(journey)
    condition_term, condition_term_source, search_condition_term = (
        _effective_clinicaltrials_condition_term(journey)
    )
    project_facts = {
        "investigational_product": framing.investigational_product,
        "indication": framing.indication,
        "clinicaltrials_condition_term": condition_term,
        "clinicaltrials_condition_term_source": condition_term_source,
        "clinicaltrials_search_condition_term": search_condition_term,
        "study_phase": framing.study_phase,
        "intrinsic_objectives": framing.intrinsic_objectives,
        "design_pattern": framing.design_pattern,
        "target_mechanism": framing.target_mechanism,
        "competitor_target_scope": framing.competitor_target_scope,
        "product_profile": {
            "technology_type": framing.product_profile.technology_type,
            "administration_routes": framing.product_profile.administration_routes,
            "dosage_forms": framing.product_profile.dosage_forms,
            "exposure_scope": framing.product_profile.exposure_scope,
        },
        "population_intent": framing.population_intent,
        "picos": {
            "population_summary": picos.population_summary if picos else "",
            "intervention_summary": picos.intervention_summary if picos else "",
            "comparator_summary": picos.comparator_summary if picos else "",
            "primary_endpoint": picos.primary_endpoint if picos else "",
        },
    }
    candidates_data = []
    for trial in chunk:
        docs = []
        for doc in trial.public_documents:
            docs.append(
                {
                    "document_id": doc.document_id,
                    "nct_id": doc.nct_id,
                    "document_type": doc.document_type,
                    "label": doc.label,
                    "filename": doc.filename,
                    "document_date": doc.document_date,
                    "upload_date": doc.upload_date,
                    "declared_size": doc.declared_size,
                    "download_url": doc.download_url,
                    "source_status": doc.source_status,
                    "rights_status": doc.rights_status,
                }
            )
        full_conditions = [value for value in trial.conditions if value]
        candidate_data = {
            "nct_id": trial.nct_id,
            "official_title": (trial.official_title or trial.brief_title or "")[
                :300
            ],
            "brief_title": (trial.brief_title or "")[:300],
            "conditions": full_conditions,
        }
        matching_conditions = _candidate_indication_matching_condition_labels(
            candidate_data,
            project_facts,
        )
        indication_relation = _candidate_indication_relation(
            candidate_data,
            project_facts,
        )
        candidates_data.append(
            {
                **candidate_data,
                # The complete registry condition set is decision evidence.
                # Truncating it caused cross-language false negatives when the
                # project indication appeared after the first five labels.
                # `_bounded_ai_chunks` already constrains request size.
                "conditions": full_conditions,
                "condition_count": len(full_conditions),
                "matching_conditions": matching_conditions[:5],
                "project_indication_relation": indication_relation,
                "project_indication_match": _candidate_indication_matches_project(
                    candidate_data,
                    project_facts,
                ),
                "project_indication_relation_scope": (
                    "cross_language_unresolved"
                    if _is_cross_language_indication_unresolved(
                        candidate_data,
                        project_facts,
                    )
                    else "deterministic_lexical"
                ),
                "phases": trial.phases,
                "study_type": trial.study_type,
                "brief_summary": trial.brief_summary,
                "interventions": [
                    {
                        "name": intervention.name,
                        "intervention_type": intervention.intervention_type,
                    }
                    for intervention in trial.interventions
                ],
                "design_allocation": trial.design_allocation,
                "design_intervention_model": trial.design_intervention_model,
                "design_masking": trial.design_masking,
                "enrollment_count": trial.enrollment_count,
                "lead_sponsor": trial.lead_sponsor,
                "overall_status": trial.overall_status,
                "public_documents": docs,
            }
        )
    return {
        "project_facts": project_facts,
        "chunk_index": chunk_index,
        "candidates": candidates_data,
        "allowed_classifications": sorted(_ALLOWED_CLASSIFICATIONS),
        "matching_dimensions": list(_MATCH_DIMENSIONS),
    }


def _build_system_prompt() -> str:
    return (
        "You are a senior clinical-development medical writer performing "
        "competitor relevance triage for a Chinese clinical-trial protocol.\n"
        "You receive a JSON object containing minimum project facts and a chunk "
        "of ClinicalTrials.gov trial candidates with their public Protocol "
        "metadata.\n\n"
        "STRICT RULES:\n"
        "1. You MUST classify every candidate in the input chunk. Your output "
        "must contain exactly the same set of nct_ids as the input chunk — no "
        "more, no less, no duplicates, no invented NCTs.\n"
        "2. Allowed classification values are exactly: "
        "direct_competitor, indirect_reference, excluded.\n"
        "3. You MUST NOT invent NCT IDs, documents, sponsors, or trial designs "
        "that are not in the provided input.\n"
        "4. For each candidate, assess relevance across these dimensions: "
        + ", ".join(_MATCH_DIMENSIONS)
        + ".\n"
        "5. direct_competitor requires the same indication plus explicit supplied "
        "evidence of a directly comparable investigational modality/route/target "
        "or a highly similar phase and core design. Never infer mechanism, route, "
        "dosage form, or drug class from a development code alone. If the project "
        "target, technology, or administration route is unknown, say it is "
        "unknown, lower confidence, and do not classify the candidate as a direct "
        "competitor or claim a mechanism match.\n"
        "6. indirect_reference means a drug or biologic study in the same "
        "indication that can inform population, endpoints, safety, dosing, visit "
        "schedule, statistical design, or long-term follow-up but is not directly "
        "comparable. A long-term extension of a direct competitor is normally an "
        "indirect reference, not a direct dose-finding competitor. A different "
        "route or masking design alone does not make an otherwise useful "
        "same-indication pharmacologic study irrelevant. Missing project modality, "
        "route, or target evidence blocks direct_competitor but does not by itself "
        "justify excluded; retain an otherwise relevant same-indication study as "
        "indirect_reference.\n"
        "7. excluded means the study cannot materially support this drug-protocol "
        "design. Transplantation, surgery, device, radiotherapy, or other "
        "non-pharmacologic treatment is excluded unless the project itself uses "
        "that modality. Trials for another indication are excluded. Historical "
        "supportive treatment is excluded when it does not provide transferable "
        "protocol-design evidence.\n"
        "8. Clinical relevance and document suitability are separate. Populate "
        "document_suitability only from supplied public document metadata. The "
        "absence of a public Protocol may reduce corpus utility, but must not "
        "cause an invented clinical classification rationale.\n"
        "9. Every reason and matching-dimension detail must cite only facts "
        "explicitly present in the input. Phrases such as 'likely oral', 'likely "
        "same pathway', or unsupported target assumptions are forbidden. When "
        "classifying and explaining a candidate, prioritize its supplied brief "
        "summary, intervention names/types, allocation, intervention model, "
        "masking, and enrollment count. When any needed evidence is missing, "
        "record the missing fact in evidence_gaps and lower confidence; never "
        "infer target, route, or modality from an absent field.\n"
        "9a. project_indication_relation, project_indication_match, "
        "matching_conditions, and project_indication_relation_scope are "
        "server-calculated lexical evidence from the candidate's complete "
        "ClinicalTrials.gov condition list plus controlled authoritative-title "
        "corroboration. exact and mixed are authoritative positive evidence. "
        "relation=exact means the candidate explicitly contains the project "
        "disease, including a trailing registered acronym or bounded "
        "severity/activity/age qualifier; do not describe it as an indication "
        "mismatch. A same-indication pharmacologic study must be retained at "
        "least as indirect_reference when direct-comparator facts are absent. "
        "relation=none with relation_scope=deterministic_lexical means the "
        "project disease was not established and must not be repaired by medical "
        "inference. relation=none with "
        "relation_scope=cross_language_unresolved is not an exclusion fact: "
        "independently determine whether the literal project indication and a "
        "literal candidate condition are standard Chinese/English names for the "
        "same disease. You may mark the indication dimension as match only when "
        "its detail quotes the complete project indication and at least one "
        "complete candidate condition verbatim, then explicitly states their "
        "bilingual or established-acronym equivalence. Do not use shared symptoms, "
        "organs, biomarkers, or therapeutic area as equivalence. When exact "
        "disease equivalence cannot be established, mark mismatch or unknown and "
        "exclude. The conditions field contains the complete registered condition "
        "set and condition_count must equal its length; inspect every condition "
        "rather than assuming the first labels define the population. "
        "relation=mixed means the complete "
        "registered condition list establishes the project disease but also "
        "contains at least one unmatched condition/population; "
        "a pharmacologic mixed-population study must be indirect_reference, never "
        "direct_competitor. Indication-specific spelling, acronym, composite-label, "
        "and mixed-population rules have already been applied by the server; do "
        "not recreate or broaden them. The server never uses edit distance, "
        "token-overlap percentage, or fuzzy matching for these relation fields. "
        "Treat the supplied relation fields and complete conditions list as "
        "authoritative.\n"
        "10. Write reason, matching-dimension detail, evidence_gaps, and "
        "document_role in concise, natural Chinese suitable for review by a "
        "Chinese medical manager.\n"
        "11. confidence must be a number between 0.0 and 1.0.\n"
        "12. Your response must be a single JSON object with this exact shape:\n"
        '{"results": [{"nct_id": "...", "classification": "...", '
        '"confidence": 0.0, "reason": "...", "matching_dimensions": '
        '[{"dimension": "...", "match": "match|partial|mismatch|unknown", '
        '"detail": "..."}], "evidence_gaps": ["..."], '
        '"document_suitability": {"has_public_protocol": false, '
        '"has_public_sap": false, "document_role": "..."}}]}\n\n'
        "Return only the JSON object. No markdown, no explanation."
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# v4 source-truth enforcement functions
# ---------------------------------------------------------------------------

# Dimensions whose match state must be forced to ``unknown`` when either the
# project fact or the candidate explicit field is absent.  Inference from drug
# codes, tablet/capsule names, or medical priors is never allowed here.
_PROTECTED_DIMENSIONS = ("modality", "route", "target_mechanism")

# Chinese labels for protected dimensions, used in detail text and evidence gaps.
_DIM_CHINESE_LABELS = {
    "modality": "技术类型",
    "route": "给药途径",
    "target_mechanism": "靶点/机制",
}


def _project_fact_non_empty(value: Any) -> bool:
    """Return True when a project fact is meaningfully present.

    Placeholder or scope-only values are treated as absent. In particular,
    ``全部`` describes an unrestricted competitor search scope; it is not a
    supplied target/mechanism fact.
    """
    unknown_values = {
        "unknown",
        "all",
        "any",
        "全部",
        "不限",
        "未提供",
        "未明确",
        "待确认",
        "待定",
        "不详",
    }
    if value is None:
        return False
    if isinstance(value, str):
        normalized = value.strip().lower()
        return bool(normalized) and normalized not in unknown_values
    if isinstance(value, (list, tuple)):
        return any(
            v for v in value
            if isinstance(v, str)
            and v.strip()
            and v.strip().lower() not in unknown_values
        )
    return bool(value)


def _candidate_has_explicit_dimension(
    candidate: Optional[Dict[str, Any]], dimension: str
) -> bool:
    """Check whether the *explicit* candidate input contains the dimension.

    For ``route`` the candidate may carry a route inside the brief summary or
    intervention, but we only accept it as explicit when the model output
    already cited a concrete route from the input — never inferred.  The
    evidence gate therefore only needs to know that *some* explicit value
    existed in the canonical input.  Because the canonical input (built by
    ``_build_chunk_input``) does not include a dedicated ``route`` /
    ``target_mechanism`` / ``modality`` field for the candidate, any route or
    mechanism claim that the model makes is treated as unsupported unless it
    appears in the brief_summary or intervention name text.
    """
    if candidate is None:
        return False
    # The canonical candidate input never includes structured modality, route,
    # or target_mechanism fields.  The only place these *might* appear is
    # inside free-text fields (brief_summary, intervention names), but even
    # then the model is expected to quote, not infer.  For the evidence gate we
    # treat the protected dimensions as not explicitly provided unless the
    # candidate dict has a dedicated key for them — which it never does in the
    # current canonical input shape.
    return dimension in candidate and _project_fact_non_empty(candidate[dimension])


def _derive_document_suitability(
    candidate: Optional[Dict[str, Any]],
    model_document_role: str,
) -> Dict[str, Any]:
    """Deterministically derive document_suitability from public_documents.

    The ``document_type`` values in the candidate's ``public_documents`` are
    the authoritative source for ``has_public_protocol`` and
    ``has_public_sap``.  The model's booleans are never trusted.

    - ``protocol``       -> has_public_protocol = True
    - ``sap``            -> has_public_sap = True
    - ``protocol_sap``   -> both True

    ``document_role`` is ALWAYS generated deterministically from the
    document availability — model free text is never kept, because it
    may introduce unsourced route/target/modality claims.
    """
    has_protocol = False
    has_sap = False

    if candidate is not None:
        docs = candidate.get("public_documents")
        if isinstance(docs, list):
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                doc_type = str(doc.get("document_type", "")).strip().lower()
                if doc_type == "protocol":
                    has_protocol = True
                elif doc_type == "sap":
                    has_sap = True
                elif doc_type == "protocol_sap":
                    has_protocol = True
                    has_sap = True

    if has_protocol and has_sap:
        role = "已提供公开方案与统计分析计划"
    elif has_protocol:
        role = "已提供公开方案"
    elif has_sap:
        role = "已提供公开统计分析计划"
    else:
        role = "无公开方案或统计分析计划"

    return {
        "has_public_protocol": has_protocol,
        "has_public_sap": has_sap,
        "document_role": role,
    }


def _enforce_matching_dimensions(
    dims: List[CompetitorTriageMatchingDimension],
    candidate: Optional[Dict[str, Any]],
    project_facts: Optional[Dict[str, Any]],
    new_gaps: List[str],
) -> List[CompetitorTriageMatchingDimension]:
    """Force ``unknown`` on protected dimensions lacking explicit evidence.

    For ``modality``, ``route``, and ``target_mechanism``:
    - If the project fact for the dimension is absent, force ``match=unknown``.
    - If the candidate's explicit input does not contain the dimension, force
      ``match=unknown``.
    - Replace the detail with a concise Chinese explanation and add a
      deduplicated evidence gap.

    Non-protected dimensions (``indication``, ``phase``, ``design``) are left
    unchanged.
    """
    if project_facts is None:
        # No project context available — cannot enforce.  Return as-is.
        return dims

    pp = project_facts.get("product_profile") or {}
    project_values = {
        "modality": pp.get("technology_type", ""),
        "route": pp.get("administration_routes", []),
        "target_mechanism": project_facts.get("target_mechanism", ""),
    }

    dim_map: Dict[str, CompetitorTriageMatchingDimension] = {}
    for dim in dims:
        dim_map[dim.dimension] = dim

    for dim_name in _PROTECTED_DIMENSIONS:
        dim = dim_map.get(dim_name)
        project_val = project_values.get(dim_name)
        project_has = _project_fact_non_empty(project_val)
        candidate_has = _candidate_has_explicit_dimension(candidate, dim_name)
        label = _DIM_CHINESE_LABELS.get(dim_name, dim_name)

        if project_has and candidate_has:
            # Both sides have explicit values — leave the model assessment.
            continue

        if not project_has and not candidate_has:
            gap_msg = (
                f"当前项目及候选均未提供{label}信息，不能判断匹配性"
            )
        elif not project_has:
            gap_msg = (
                f"当前项目未提供{label}信息，不能判断匹配性"
            )
        else:
            gap_msg = (
                f"候选未提供{label}信息，不能判断匹配性"
            )

        if gap_msg not in new_gaps:
            new_gaps.append(gap_msg)

        if dim is None:
            dim_map[dim_name] = CompetitorTriageMatchingDimension(
                dimension=dim_name,
                match="unknown",
                detail=gap_msg,
            )
        else:
            dim_map[dim_name] = dim.model_copy(
                update={"match": "unknown", "detail": gap_msg}
            )

    # Rebuild list preserving original order, then append any new dims
    seen_names = {d.dimension for d in dims}
    result = [dim_map.get(d.dimension, d) for d in dims]
    for dim_name in _PROTECTED_DIMENSIONS:
        if dim_name not in seen_names:
            result.append(dim_map[dim_name])
    return result


# Intervention types that represent pharmacologic drug/biologic interventions
# eligible for indirect_reference retention.  Everything else (DEVICE,
# PROCEDURE, RADIATION, transplant, surgery, etc.) is excluded.
_PHARMACOLOGIC_INTERVENTION_TYPES = frozenset({
    "DRUG",
    "BIOLOGICAL",
    "COMBINATION_PRODUCT",
})

_CONTROLLED_SUBGROUP_PREFIXES = frozenset({"with", "without"})
_SUBGROUP_RELATION_TOKENS = frozenset(
    {"and", "or", "nor", "plus", "versus", "vs"}
)
_CONTROLLED_PRE_DISEASE_QUALIFIER_TOKENS = frozenset(
    {
        "active",
        "acute",
        "adult",
        "adults",
        "adolescent",
        "adolescents",
        "chronic",
        "distal",
        "early",
        "extensive",
        "late",
        "left",
        "mild",
        "mildly",
        "moderate",
        "moderately",
        "newly",
        "diagnosed",
        "paediatric",
        "pancolitis",
        "patient",
        "patients",
        "pediatric",
        "proximal",
        "refractory",
        "relapsed",
        "relapsing",
        "remitting",
        "right",
        "severe",
        "severely",
        "sided",
        "to",
        "with",
    }
)
_CONTROLLED_POST_DISEASE_QUALIFIER_SEQUENCES = frozenset(
    {
        ("acute",),
        ("acute", "severe"),
        ("active", "mild"),
        ("active", "moderate"),
        ("active", "severe"),
        ("chronic",),
        ("chronic", "mild"),
        ("chronic", "moderate"),
        ("chronic", "severe"),
        ("exacerbation",),
        ("flare",),
        ("in", "adult", "patients"),
        ("in", "adults"),
        ("in", "adolescent", "patients"),
        ("in", "adolescents"),
        ("in", "children"),
        ("in", "paediatric", "patients"),
        ("in", "pediatric", "patients"),
        ("in", "remission"),
        ("mild",),
        ("moderate",),
        ("severe",),
        ("unspecified",),
    }
)
_CRSWNP_ABBREVIATIONS = frozenset({"crswnp"})
_CRSWNP_FULL_ENGLISH_SEQUENCES = frozenset(
    {
        ("chronic", "rhinosinusitis", "with", "nasal", "polyps"),
        (
            "chronic",
            "rhinosinusitis",
            "phenotype",
            "with",
            "nasal",
            "polyps",
        ),
        ("chronic", "rhinosinusitis", "with", "nasal", "polyposis"),
    }
)
_CRSWNP_MIXED_ENGLISH_SEQUENCES = frozenset(
    {
        (
            "chronic",
            "sinusitis",
            "with",
            "or",
            "without",
            "nasal",
            "polyps",
        ),
        (
            "chronic",
            "sinusitis",
            "with",
            "and",
            "without",
            "nasal",
            "polyps",
        ),
        (
            "chronic",
            "rhinosinusitis",
            "with",
            "or",
            "without",
            "nasal",
            "polyps",
        ),
        (
            "chronic",
            "rhinosinusitis",
            "with",
            "and",
            "without",
            "nasal",
            "polyps",
        ),
        (
            "chronic",
            "rhinosinusitis",
            "with",
            "or",
            "without",
            "the",
            "presence",
            "of",
            "nasal",
            "polyps",
        ),
        (
            "chronic",
            "rhinosinusitis",
            "with",
            "and",
            "without",
            "the",
            "presence",
            "of",
            "nasal",
            "polyps",
        ),
    }
)
_CRSWNP_DISTINCT_DISEASE_EXCLUSION_SEQUENCES = frozenset(
    {
        ("allergic", "fungal", "rhinosinusitis"),
    }
)
_CRSWNP_WITHOUT_ENGLISH_SEQUENCES = frozenset(
    {
        ("chronic", "rhinosinusitis", "without", "nasal", "polyps"),
        ("chronic", "rhinosinusitis", "without", "nasal", "polyposis"),
        (
            "chronic",
            "rhinosinusitis",
            "without",
            "the",
            "presence",
            "of",
            "nasal",
            "polyps",
        ),
    }
)
_CRSWNP_ELLIPTIC_ENGLISH_SEQUENCES = frozenset(
    {
        ("chronic", "rhinosinusitis", "with", "polyps"),
        ("chronic", "sinusitis", "with", "polyps"),
    }
)
_CRSWNP_COMBINED_CONDITION_SEQUENCES = frozenset(
    {
        ("chronic", "sinusitis", "nasal", "polyps"),
        ("chronic", "rhinosinusitis", "nasal", "polyps"),
    }
)
_CRSWNP_GENERIC_COMBINED_CONDITION_SEQUENCES = frozenset(
    {("sinusitis", "nasal", "polyps")}
)
_CRSWNP_CHRONIC_SINUS_CONDITION_SEQUENCES = frozenset(
    {
        ("chronic", "sinusitis"),
        ("chronic", "rhinosinusitis"),
    }
)
_CRSWNP_GENERIC_SINUS_CONDITION_SEQUENCES = frozenset({("sinusitis",)})
_CRSWNP_ACUTE_SINUS_CONDITION_SEQUENCES = frozenset(
    {
        ("acute", "sinusitis"),
        ("acute", "rhinosinusitis"),
    }
)
_CRSWNP_POLYP_CONDITION_SEQUENCES = frozenset(
    {
        ("nasal", "polyp"),
        ("nasal", "polyps"),
        ("nasal", "polyposis"),
    }
)
_CRSWNP_FULL_CHINESE_LABELS = frozenset(
    {
        "慢性鼻窦炎伴鼻息肉",
        "慢性鼻窦炎伴有鼻息肉",
        "慢性鼻窦炎合并鼻息肉",
        "慢性鼻鼻窦炎伴鼻息肉",
        "慢性鼻鼻窦炎伴有鼻息肉",
        "慢性鼻鼻窦炎合并鼻息肉",
    }
)
_CRSWNP_CHRONIC_SINUS_CHINESE_LABELS = frozenset(
    {"慢性鼻窦炎", "慢性鼻鼻窦炎"}
)
_CRSWNP_GENERIC_SINUS_CHINESE_LABELS = frozenset({"鼻窦炎"})
_CRSWNP_ACUTE_SINUS_CHINESE_LABELS = frozenset(
    {"急性鼻窦炎", "急性鼻鼻窦炎"}
)
_CRSWNP_POLYP_CHINESE_LABELS = frozenset({"鼻息肉"})

# UC / IBD closed helpers -------------------------------------------------
_COPD_CHINESE_LABELS = frozenset(
    {
        "慢性阻塞性肺疾病",
        "慢性阻塞性肺病",
    }
)
_COPD_ENGLISH_SEQUENCES = frozenset(
    {
        ("chronic", "obstructive", "pulmonary", "disease"),
    }
)
_COPD_ABBREVIATIONS = frozenset({"copd"})

_UC_CHINESE_LABELS = frozenset({"溃疡性结肠炎", "溃疡性大腸炎", "溃疡性大肠炎"})
_UC_ENGLISH_SEQUENCES = frozenset(
    {
        ("ulcerative", "colitis"),
    }
)
_UC_ABBREVIATIONS = frozenset({"uc"})
_IBD_UMBRELLA_ENGLISH_SEQUENCES = frozenset(
    {
        ("inflammatory", "bowel", "disease"),
        ("inflammatory", "bowel", "diseases"),
    }
)
_IBD_UMBRELLA_ABBREVIATIONS = frozenset({"ibd"})
_CROHN_ENGLISH_SEQUENCES = frozenset(
    {
        ("crohn", "disease"),
        ("crohns", "disease"),
        ("crohn",),
        ("crohns",),
    }
)
_ONTOLOGY_PAREN_QUALIFIERS = frozenset(
    {"disorder", "disease", "finding", "condition"}
)
_UC_ASC_CONDITION_SEQUENCES = frozenset(
    {
        ("acute", "severe", "colitis"),
        ("acute", "severe", "ulcerative", "colitis"),
    }
)
_UC_ASC_ABBREVIATIONS = frozenset({"asc"})


def _strip_ontology_condition_qualifiers(condition: str) -> str:
    """Remove trailing SNOMED-style ``(Disorder)`` ontology parentheses."""
    text = str(condition or "").strip()
    if not text:
        return ""
    return re.sub(
        r"\s*[\(（]("
        + "|".join(sorted(_ONTOLOGY_PAREN_QUALIFIERS))
        + r")[\)）]\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()


def _copd_chinese_label(text: str) -> str:
    """Return a label suitable only for the closed COPD concept mapping."""
    without_abbreviation = re.sub(
        r"[\(（]\s*COPD\s*[\)）]",
        "",
        str(text or ""),
        flags=re.IGNORECASE,
    )
    return re.sub(
        r"[^\u4e00-\u9fff]",
        "",
        without_abbreviation,
    )


def _copd_english_sequence(text: str) -> tuple[str, ...]:
    """Tokenize a COPD label after removing only the exact COPD acronym."""
    without_abbreviation = re.sub(
        r"[\(（]\s*COPD\s*[\)）]",
        "",
        str(text or ""),
        flags=re.IGNORECASE,
    )
    return _condition_english_sequence(without_abbreviation)


def _project_establishes_copd(project_facts: Dict[str, Any]) -> bool:
    """Recognize COPD only from an explicit closed Chinese/English label."""
    for key in ("indication", "clinicaltrials_condition_term"):
        term = _strip_ontology_condition_qualifiers(
            str(project_facts.get(key, "")).strip()
        )
        if not term:
            continue
        if _copd_chinese_label(term) in _COPD_CHINESE_LABELS:
            return True
        if _copd_english_sequence(term) in _COPD_ENGLISH_SEQUENCES:
            return True
        if term.casefold() in _COPD_ABBREVIATIONS:
            return True
    return False


def _condition_is_exact_copd_label(condition: str) -> bool:
    """Match the same closed COPD concept without substring/fuzzy expansion."""
    term = _strip_ontology_condition_qualifiers(condition)
    if not term:
        return False
    if _copd_chinese_label(term) in _COPD_CHINESE_LABELS:
        return True
    if _copd_english_sequence(term) in _COPD_ENGLISH_SEQUENCES:
        return True
    return term.casefold() in _COPD_ABBREVIATIONS


def _project_establishes_uc(project_facts: Dict[str, Any]) -> bool:
    """Recognize ulcerative colitis from controlled Chinese/English labels."""
    for key in ("indication", "clinicaltrials_condition_term"):
        term = str(project_facts.get(key, "")).strip()
        if not term:
            continue
        chinese = _condition_chinese_label(term)
        if chinese in _UC_CHINESE_LABELS or "溃疡性结肠炎" in chinese:
            return True
        sequence = _condition_english_sequence(term)
        if sequence in _UC_ENGLISH_SEQUENCES:
            return True
        if term.strip().lower() in _UC_ABBREVIATIONS:
            return True
        abbrevs = _extract_parenthetical_abbrevs(term)
        if abbrevs & _UC_ABBREVIATIONS:
            return True
    return False


def _text_establishes_uc_population(text: str) -> bool:
    """True when free text clearly names UC as the studied population."""
    raw = str(text or "").strip()
    if not raw:
        return False
    if "溃疡性结肠炎" in raw:
        return True
    sequence = _condition_english_sequence(raw)
    if not sequence:
        # Keep parenthetical UC / title phrases with punctuation.
        lowered = raw.lower()
        if re.search(r"\bulcerative\s+colitis\b", lowered):
            return True
        if re.search(r"\buc\b", lowered) and "colitis" in lowered:
            return True
        return False
    if any(
        sequence[index : index + len(uc_seq)] == uc_seq
        for uc_seq in _UC_ENGLISH_SEQUENCES
        for index in range(len(sequence) - len(uc_seq) + 1)
    ):
        return True
    return False


def _text_establishes_crohn_only_population(text: str) -> bool:
    """True when text is Crohn-focused without UC naming."""
    if _text_establishes_uc_population(text):
        return False
    raw = str(text or "").strip()
    if not raw:
        return False
    sequence = _condition_english_sequence(raw)
    lowered = raw.lower()
    if "crohn" in lowered or "克隆恩" in raw or "克罗恩" in raw:
        return True
    return any(
        sequence[index : index + len(crohn_seq)] == crohn_seq
        for crohn_seq in _CROHN_ENGLISH_SEQUENCES
        for index in range(max(0, len(sequence) - len(crohn_seq) + 1))
    )


def _condition_is_ibd_umbrella_label(condition: str) -> bool:
    cleaned = _strip_ontology_condition_qualifiers(condition)
    sequence = _condition_english_sequence(cleaned)
    if sequence in _IBD_UMBRELLA_ENGLISH_SEQUENCES:
        return True
    if cleaned.strip().lower() in _IBD_UMBRELLA_ABBREVIATIONS:
        return True
    abbrevs = _extract_parenthetical_abbrevs(cleaned)
    if abbrevs & _IBD_UMBRELLA_ABBREVIATIONS and sequence in {
        ("inflammatory", "bowel", "disease"),
        ("inflammatory", "bowel", "diseases"),
        tuple(),
    }:
        return True
    # ``Inflammatory Bowel Diseases (IBD)``
    if abbrevs & _IBD_UMBRELLA_ABBREVIATIONS:
        tokens = _normalize_indication_tokens(cleaned)
        if tokens <= {"inflammatory", "bowel", "disease", "diseases", "ibd"}:
            return True
    return False


def _condition_is_uc_asc_alias(condition: str) -> bool:
    cleaned = _strip_ontology_condition_qualifiers(condition)
    sequence = _condition_english_sequence(cleaned)
    if sequence in _UC_ASC_CONDITION_SEQUENCES:
        return True
    if cleaned.strip().upper() in {item.upper() for item in _UC_ASC_ABBREVIATIONS}:
        return True
    abbrevs = _extract_parenthetical_abbrevs(cleaned)
    if abbrevs & _UC_ASC_ABBREVIATIONS:
        return True
    return False


def _candidate_uc_title_corroboration(
    candidate: Dict[str, Any],
) -> tuple[bool, str]:
    """Return whether title/summary corroborates a UC population."""
    for key in ("official_title", "brief_title", "brief_summary"):
        text = str(candidate.get(key, "") or "").strip()
        if not text:
            continue
        if _text_establishes_crohn_only_population(text):
            continue
        if _text_establishes_uc_population(text):
            return True, key
    return False, ""


def _candidate_uc_semantic_evidence(
    candidate: Dict[str, Any],
    project_facts: Dict[str, Any],
) -> tuple[str, List[str], str]:
    """Closed UC evidence: ontology cleanup, anatomic UC, IBD+title, ASC+title.

    Does not loosen the reject list for mixed Crohn+UC registry labels that
    already fail exact condition matching — those stay ``none`` unless a
    separate condition label itself matches UC.
    """
    if not _project_establishes_uc(project_facts):
        return "none", [], ""
    conditions = candidate.get("conditions")
    if not isinstance(conditions, list):
        return "none", [], ""
    labels = [
        str(value).strip()
        for value in conditions
        if isinstance(value, str) and value.strip()
    ]
    if not labels:
        return "none", [], ""

    # First: ontology-stripped / anatomic / controlled descriptor matches.
    matching_labels: List[str] = []
    for label in labels:
        cleaned = _strip_ontology_condition_qualifiers(label)
        probe = {"conditions": [cleaned or label]}
        if _candidate_indication_matches_project_conditions_only(
            probe,
            project_facts,
        ):
            matching_labels.append(label)
    if matching_labels:
        return (
            "mixed" if len(matching_labels) < len(labels) else "exact",
            matching_labels,
            "condition_exact_or_descriptor",
        )

    title_ok, title_source = _candidate_uc_title_corroboration(candidate)
    if not title_ok:
        return "none", [], ""

    # IBD umbrella alone + UC title/summary → exact (same-indication filter).
    if all(_condition_is_ibd_umbrella_label(label) for label in labels):
        return "exact", labels[:1], f"{title_source}_ibd_umbrella"

    # ASC / acute severe colitis alias + UC title.
    if any(_condition_is_uc_asc_alias(label) for label in labels):
        return (
            "exact",
            [label for label in labels if _condition_is_uc_asc_alias(label)][:1],
            f"{title_source}_asc_alias",
        )
    return "none", [], ""


def _candidate_indication_matches_project_conditions_only(
    candidate: Optional[Dict[str, Any]],
    project_facts: Optional[Dict[str, Any]],
) -> bool:
    """Condition-label matching without UC title corroboration recursion."""
    if candidate is None or project_facts is None:
        return False
    indication = str(project_facts.get("indication", "")).strip()
    ct_term = str(project_facts.get("clinicaltrials_condition_term", "")).strip()
    if not indication and not ct_term:
        return False
    conds = candidate.get("conditions")
    if not isinstance(conds, list):
        return False
    cand_conditions = [
        _strip_ontology_condition_qualifiers(str(c))
        for c in conds
        if isinstance(c, str) and str(c).strip()
    ]
    cand_conditions = [c for c in cand_conditions if c]
    if not cand_conditions:
        return False
    if _project_establishes_crswnp(project_facts):
        relation, _, _ = _candidate_crswnp_semantic_evidence(
            candidate,
            project_facts,
        )
        return relation in {"exact", "mixed"}
    if _project_establishes_copd(project_facts):
        return any(
            _condition_is_exact_copd_label(condition)
            for condition in cand_conditions
        )

    project_term_tokens: List[frozenset[str]] = []
    for term in [indication, ct_term]:
        if term:
            tokens = _normalize_indication_tokens(term)
            if tokens:
                project_term_tokens.append(tokens)
    if not project_term_tokens:
        return False
    project_full_name_sequences = [
        tuple(token for token, _, _ in _english_condition_token_spans(term))
        for term in [indication, ct_term]
        if term
    ]
    project_abbrevs = (
        _extract_parenthetical_abbrevs(indication)
        | _extract_parenthetical_abbrevs(ct_term)
        | _derive_project_full_name_abbreviations(
            project_full_name_sequences
        )
    )
    for c in cand_conditions:
        cand_tokens = _normalize_indication_tokens(c)
        for pt_tokens in project_term_tokens:
            if cand_tokens and cand_tokens == pt_tokens:
                return True
        c_upper = c.strip().upper()
        if (
            2 <= len(c_upper) <= 8
            and c_upper.isalpha()
            and c_upper == c.strip()
            and c_upper.lower() in project_abbrevs
        ):
            return True
        if _condition_alias_pair_matches_project(
            c, project_term_tokens, project_abbrevs
        ):
            return True
        if _condition_comma_inverted_full_name_matches_project(
            c, project_term_tokens
        ):
            return True
        if _parenthetical_alias_full_name_matches_project(
            c, project_term_tokens, project_abbrevs
        ):
            return True
        if _condition_full_name_with_controlled_descriptors_matches_project(
            c,
            project_full_name_sequences,
        ):
            return True
        if _condition_full_name_with_controlled_subgroup_matches_project(
            c, project_full_name_sequences, project_abbrevs
        ):
            return True
    return False


def _normalize_condition_orthography_token(token: str) -> str:
    """Normalize a closed set of medical orthography/registry variants."""
    normalized = token.lower()
    controlled_registry_typos = {
        "rhinosinustis": "rhinosinusitis",
        "poplyposis": "polyposis",
    }
    if normalized in controlled_registry_typos:
        return controlled_registry_typos[normalized]
    if normalized.startswith("haem") and len(normalized) > 4:
        return "hem" + normalized[4:]
    return normalized


def _condition_english_sequence(text: str) -> tuple[str, ...]:
    """Return a lowercased English token sequence with known acronyms removed."""
    without_known_abbrev = re.sub(
        r"[\(（]\s*CRSwNP\s*[\)）]",
        "",
        text or "",
        flags=re.IGNORECASE,
    )
    return tuple(
        token for token, _, _ in _english_condition_token_spans(
            without_known_abbrev
        )
    )


def _crswnp_english_sequence(text: str) -> tuple[str, ...]:
    """Tokenize CRSwNP evidence after removing only known CRS acronyms."""
    without_known_abbrev = re.sub(
        r"[\(（]\s*(?:CRSwNP|CRS)\s*[\)）]",
        "",
        text or "",
        flags=re.IGNORECASE,
    )
    return tuple(
        token
        for token, _, _ in _english_condition_token_spans(
            without_known_abbrev
        )
    )


def _condition_chinese_label(text: str) -> str:
    """Return a punctuation-free CJK label for exact controlled matching."""
    without_known_abbrev = re.sub(
        r"[\(（]\s*CRSwNP\s*[\)）]",
        "",
        text or "",
        flags=re.IGNORECASE,
    )
    return "".join(re.findall(r"[\u4e00-\u9fff]+", without_known_abbrev))


def _sequence_contains(
    tokens: tuple[str, ...],
    expected: tuple[str, ...],
) -> bool:
    """Return True when an exact controlled token sequence occurs contiguously."""
    width = len(expected)
    if not width or len(tokens) < width:
        return False
    return any(
        tokens[index : index + width] == expected
        for index in range(len(tokens) - width + 1)
    )


def _contains_any_sequence(
    tokens: tuple[str, ...],
    expected_sequences: frozenset[tuple[str, ...]],
) -> bool:
    return any(
        _sequence_contains(tokens, expected)
        for expected in expected_sequences
    )


def _project_establishes_crswnp(project_facts: Dict[str, Any]) -> bool:
    """Recognize CRSwNP only from a controlled full label or its fixed acronym."""
    for key in ("indication", "clinicaltrials_condition_term"):
        term = str(project_facts.get(key, "")).strip()
        if not term:
            continue
        if term.lower() in _CRSWNP_ABBREVIATIONS:
            return True
        if _condition_chinese_label(term) in _CRSWNP_FULL_CHINESE_LABELS:
            return True
        if _condition_english_sequence(term) in _CRSWNP_FULL_ENGLISH_SEQUENCES:
            return True
    return False


def _candidate_crswnp_semantic_evidence(
    candidate: Dict[str, Any],
    project_facts: Dict[str, Any],
) -> tuple[str, List[str], str]:
    """Classify controlled CRSwNP evidence as exact, mixed, or none.

    The rule is intentionally closed:
    - exact full Chinese/English labels and the fixed ``CRSwNP`` acronym match;
    - exact chronic-sinusitis and nasal-polyp labels may compose across the
      complete authoritative condition list;
    - a single registry label may compose only controlled chronic
      rhinosinusitis and nasal polyposis sequences;
    - the two observed ClinicalTrials.gov misspellings are normalized only
      through a fixed token map and still require nasal-polyp title evidence
      when the condition omits ``nasal``;
    - a CRS-only condition may be corroborated by an exact controlled CRSwNP
      title, while ``with or/and without nasal polyps`` is a mixed population;
    - generic ``Sinusitis`` plus ``Nasal Polyps``, or ``Nasal Polyps`` alone,
      matches only when an authoritative registry title contains an exact
      controlled CRSwNP full-name sequence;
    - explicit ``without nasal polyps`` remains none unless a separate
      explicit CRSwNP condition proves a mixed population;
    - acute sinusitis never qualifies for title-corroborated composition.

    No token subset percentage, edit distance, stemming, or fuzzy search is
    used. Acute sinusitis, other diseases with polyps, and isolated nasal
    polyps without title corroboration remain non-matches.
    """
    if not _project_establishes_crswnp(project_facts):
        return "none", [], ""
    raw_conditions = candidate.get("conditions")
    if not isinstance(raw_conditions, list):
        return "none", [], ""
    conditions = [
        str(value).strip()
        for value in raw_conditions
        if isinstance(value, str) and value.strip()
    ]
    if not conditions:
        return "none", [], ""

    exact_full: List[str] = []
    explicit_without: List[str] = []
    explicit_mixed: List[str] = []
    distinct_disease_components: List[str] = []
    elliptic_with_polyps: List[str] = []
    chronic_sinus_components: List[str] = []
    generic_sinus_components: List[str] = []
    polyp_components: List[str] = []
    has_acute_sinusitis = False
    for condition in conditions:
        english = _crswnp_english_sequence(condition)
        chinese = _condition_chinese_label(condition)
        if _contains_any_sequence(
            english,
            _CRSWNP_DISTINCT_DISEASE_EXCLUSION_SEQUENCES,
        ):
            distinct_disease_components.append(condition)
        if _contains_any_sequence(
            english,
            _CRSWNP_MIXED_ENGLISH_SEQUENCES,
        ):
            explicit_mixed.append(condition)
            continue
        if _contains_any_sequence(
            english,
            _CRSWNP_WITHOUT_ENGLISH_SEQUENCES,
        ):
            explicit_without.append(condition)
            continue
        if (
            condition.lower() in _CRSWNP_ABBREVIATIONS
            or english in _CRSWNP_FULL_ENGLISH_SEQUENCES
            or _contains_any_sequence(
                english,
                _CRSWNP_FULL_ENGLISH_SEQUENCES,
            )
            or english in _CRSWNP_COMBINED_CONDITION_SEQUENCES
            or chinese in _CRSWNP_FULL_CHINESE_LABELS
        ):
            exact_full.append(condition)
            continue
        if _contains_any_sequence(
            english,
            _CRSWNP_ELLIPTIC_ENGLISH_SEQUENCES,
        ):
            elliptic_with_polyps.append(condition)
            chronic_sinus_components.append(condition)
            continue
        if (
            english in _CRSWNP_GENERIC_COMBINED_CONDITION_SEQUENCES
        ):
            generic_sinus_components.append(condition)
            polyp_components.append(condition)
            continue
        if (
            _contains_any_sequence(
                english,
                _CRSWNP_CHRONIC_SINUS_CONDITION_SEQUENCES,
            )
            or chinese in _CRSWNP_CHRONIC_SINUS_CHINESE_LABELS
        ):
            chronic_sinus_components.append(condition)
        if (
            _contains_any_sequence(
                english,
                _CRSWNP_GENERIC_SINUS_CONDITION_SEQUENCES,
            )
            or chinese in _CRSWNP_GENERIC_SINUS_CHINESE_LABELS
        ):
            generic_sinus_components.append(condition)
        if (
            _contains_any_sequence(
                english,
                _CRSWNP_ACUTE_SINUS_CONDITION_SEQUENCES,
            )
            or chinese in _CRSWNP_ACUTE_SINUS_CHINESE_LABELS
        ):
            has_acute_sinusitis = True
        if (
            _contains_any_sequence(
                english,
                _CRSWNP_POLYP_CONDITION_SEQUENCES,
            )
            or chinese in _CRSWNP_POLYP_CHINESE_LABELS
        ):
            polyp_components.append(condition)

    title_exact = False
    title_mixed = False
    title_has_nasal_polyps = False
    title_source = ""
    for title_key in ("official_title", "brief_title"):
        title = str(candidate.get(title_key, "")).strip()
        title_tokens = _crswnp_english_sequence(title)
        if not title_tokens:
            continue
        if _contains_any_sequence(
            title_tokens,
            _CRSWNP_MIXED_ENGLISH_SEQUENCES,
        ):
            title_mixed = True
            title_source = title_key
            break
        if _contains_any_sequence(
            title_tokens,
            _CRSWNP_FULL_ENGLISH_SEQUENCES,
        ):
            title_exact = True
            title_source = title_key
        if _contains_any_sequence(
            title_tokens,
            _CRSWNP_POLYP_CONDITION_SEQUENCES,
        ):
            title_has_nasal_polyps = True
            title_source = title_source or title_key

    if explicit_mixed:
        return "mixed", explicit_mixed[:1], "condition_mixed_population"
    if exact_full and explicit_without:
        return (
            "mixed",
            [exact_full[0], explicit_without[0]],
            "separate_with_and_without_conditions",
        )
    if exact_full:
        return "exact", exact_full, "condition_exact"
    if explicit_without:
        return "none", [], "condition_explicit_without_polyps"
    if has_acute_sinusitis:
        return "none", [], "condition_acute_sinusitis"
    if title_mixed and chronic_sinus_components:
        return (
            "mixed",
            chronic_sinus_components[:1],
            f"{title_source}_mixed_population",
        )
    if title_exact and chronic_sinus_components:
        return (
            "exact",
            chronic_sinus_components[:1],
            f"{title_source}_exact_crswnp",
        )
    if distinct_disease_components and not title_exact and not title_mixed:
        return (
            "none",
            [],
            "condition_distinct_named_disease",
        )
    if chronic_sinus_components and polyp_components:
        return (
            "exact",
            list(
                dict.fromkeys(
                    [chronic_sinus_components[0], polyp_components[0]]
                )
            ),
            "condition_bounded_composition",
        )
    if elliptic_with_polyps and title_has_nasal_polyps:
        return (
            "exact",
            elliptic_with_polyps[:1],
            f"{title_source}_nasal_polyp_corroboration",
        )
    if title_exact and polyp_components:
        contributors = [
            *generic_sinus_components[:1],
            polyp_components[0],
        ]
        return (
            "exact",
            list(dict.fromkeys(contributors)),
            f"{title_source}_exact_crswnp",
        )
    return "none", [], ""


def _candidate_crswnp_matching_condition_labels(
    candidate: Dict[str, Any],
    project_facts: Dict[str, Any],
) -> List[str]:
    _, labels, _ = _candidate_crswnp_semantic_evidence(
        candidate,
        project_facts,
    )
    return labels


def _candidate_indication_relation(
    candidate: Optional[Dict[str, Any]],
    project_facts: Optional[Dict[str, Any]],
) -> str:
    """Return exact, mixed, or none for reviewer-facing indication relevance."""
    if candidate is None or project_facts is None:
        return "none"
    authoritative_relation = candidate.get("project_indication_relation")
    if authoritative_relation in {"exact", "mixed", "none"}:
        return str(authoritative_relation)
    authoritative_match = candidate.get("project_indication_match")
    if isinstance(authoritative_match, bool):
        if not authoritative_match:
            return "none"
        matching_conditions = [
            str(value).strip()
            for value in candidate.get("matching_conditions", [])
            if isinstance(value, str) and value.strip()
        ]
        try:
            condition_count = int(candidate.get("condition_count", 0))
        except (TypeError, ValueError):
            condition_count = 0
        return (
            "mixed"
            if condition_count > max(1, len(matching_conditions))
            else "exact"
        )
    if _project_establishes_crswnp(project_facts):
        relation, _, _ = _candidate_crswnp_semantic_evidence(
            candidate,
            project_facts,
        )
        return relation
    if _project_establishes_uc(project_facts):
        relation, _, _ = _candidate_uc_semantic_evidence(
            candidate,
            project_facts,
        )
        if relation != "none":
            return relation
    conditions = candidate.get("conditions")
    if not isinstance(conditions, list):
        return "none"
    labels = [
        str(value).strip()
        for value in conditions
        if isinstance(value, str) and value.strip()
    ]
    if not labels:
        return "none"
    matching_labels = [
        label
        for label in labels
        if _candidate_indication_matches_project_conditions_only(
            {"conditions": [_strip_ontology_condition_qualifiers(label) or label]},
            project_facts,
        )
    ]
    if not matching_labels:
        return "none"
    return "mixed" if len(matching_labels) < len(labels) else "exact"


def _normalize_indication_tokens(text: str) -> frozenset[str]:
    """Extract a normalized set of meaningful tokens from an indication string.

    Handles both Chinese and English text:
    - Lowercases, strips punctuation
    - Splits on whitespace, commas, semicolons, Chinese commas/periods
    - Extracts parenthetical abbreviations like (PNH) as standalone tokens
    - Filters very short tokens (≤2 chars) that cause false matches,
      except for known abbreviation patterns like PNH, RA, SLE etc.
    """
    if not text:
        return frozenset()
    import re

    # Extract parenthetical abbreviations first
    abbrevs = re.findall(r'\(([A-Z]{2,8})\)', text)
    # Normalize: lowercase, replace various separators with spaces
    normalized = text.lower()
    for sep in [',', ';', '（', '）', '(', ')', '，', '、', '。', '/']:
        normalized = normalized.replace(sep, ' ')
    # Remove remaining non-alphanumeric/non-CJK chars
    normalized = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', normalized)
    raw_tokens = normalized.split()
    # Keep tokens that are: English words ≥3 chars, CJK tokens ≥2 chars,
    # or known abbreviations
    tokens = set()
    for t in raw_tokens:
        t = t.strip()
        if not t:
            continue
        if re.match(r'^[a-z]+$', t):
            if len(t) >= 3:
                tokens.add(_normalize_condition_orthography_token(t))
        elif re.match(r'^[\u4e00-\u9fff]+$', t):
            if len(t) >= 2:
                tokens.add(t)
        else:
            # Mixed or numeric — keep if long enough
            if len(t) >= 3:
                tokens.add(t)
    # Add abbreviations
    for abbr in abbrevs:
        tokens.add(abbr.lower())
    return frozenset(tokens)


def _english_condition_token_spans(
    text: str,
) -> List[tuple[str, int, int]]:
    """Return ordered English condition tokens with source spans."""
    return [
        (
            _normalize_condition_orthography_token(match.group(0)),
            match.start(),
            match.end(),
        )
        for match in re.finditer(r"[A-Za-z]+", text or "")
    ]


def _extract_parenthetical_abbrevs(text: str) -> frozenset[str]:
    """Extract uppercase abbreviations from parenthetical expressions.

    Handles both ASCII ``()`` and full-width ``（）`` parentheses.
    Returns lowercase abbreviations (e.g. ``pnh``).
    """
    if not text:
        return frozenset()
    # Match both ASCII and full-width parentheses
    pattern = r'[\(（]([A-Z]{2,8})[\)）]'
    return frozenset(a.lower() for a in re.findall(pattern, text))


def _derive_project_full_name_abbreviations(
    project_full_name_sequences: List[tuple[str, ...]],
) -> frozenset[str]:
    """Derive only exact initialisms from bound English disease full names.

    This lets a registry's standalone ``PNH`` or strict
    ``PNH - Paroxysmal Nocturnal Hemoglobinuria`` condition remain linked to
    the exact bound full name even when the user did not type ``(PNH)``.
    No synonym, fuzzy alias, stop-word omission, or disease-specific table is
    used: every full-name token contributes one initial and the result must be
    2–8 ASCII letters.
    """
    abbreviations: set[str] = set()
    for sequence in project_full_name_sequences:
        if not 2 <= len(sequence) <= 8:
            continue
        if any(not re.fullmatch(r"[a-z]+", token) for token in sequence):
            continue
        abbreviation = "".join(token[0] for token in sequence)
        if 2 <= len(abbreviation) <= 8:
            abbreviations.add(abbreviation)
    return frozenset(abbreviations)


def _condition_alias_pair_matches_project(
    condition: str,
    project_term_tokens: List[frozenset[str]],
    project_abbrevs: frozenset[str],
) -> bool:
    """Match only a strict ``ABBR - full disease name`` alias pair.

    ClinicalTrials.gov commonly records a condition as ``PNH - Paroxysmal
    Nocturnal Hemoglobinuria`` (or the reverse order).  This is deliberately
    narrower than a substring rule: there must be exactly two dash-delimited
    segments, one must be a proven project abbreviation, and the other must
    have exact normalized token-set equality with one project term.
    """
    segments = re.split(r"\s+[-\u2013\u2014]\s+", condition.strip())
    if len(segments) != 2:
        return False
    left, right = (segment.strip() for segment in segments)
    for abbreviation, full_name in ((left, right), (right, left)):
        if not re.fullmatch(r"[A-Z]{2,8}", abbreviation):
            continue
        if abbreviation.lower() not in project_abbrevs:
            continue
        full_name_tokens = _normalize_indication_tokens(full_name)
        if full_name_tokens and any(
            full_name_tokens == project_tokens
            for project_tokens in project_term_tokens
        ):
            return True
    return False


def _condition_comma_inverted_full_name_matches_project(
    condition: str,
    project_term_tokens: List[frozenset[str]],
) -> bool:
    """Match a strict comma-inverted controlled disease label.

    Registries and medical ontologies may render a disease as
    ``Hemoglobinuria, Paroxysmal Nocturnal (PNH)`` while the search contract
    uses ``Paroxysmal Nocturnal Hemoglobinuria``. Only one English comma,
    exactly two non-empty name segments, an optional trailing uppercase
    abbreviation, and exact full-name token equality are accepted. Extra
    diseases, qualifiers, aliases, or unmatched tokens therefore fail closed.
    """
    normalized = str(condition or "").strip()
    if not normalized:
        return False
    normalized = re.sub(
        r"\s*[\(（][A-Z]{2,8}[\)）]\s*$",
        "",
        normalized,
    ).strip()
    if not re.fullmatch(
        r"[A-Za-z][A-Za-z'\- ]*\s*[,，]\s*"
        r"[A-Za-z][A-Za-z'\- ]*",
        normalized,
    ):
        return False
    segments = re.split(r"[,，]", normalized)
    if len(segments) != 2:
        return False
    if any(not _english_condition_token_spans(segment) for segment in segments):
        return False
    full_name_tokens = _normalize_indication_tokens(normalized)
    return bool(full_name_tokens) and any(
        full_name_tokens == project_tokens
        for project_tokens in project_term_tokens
    )


def _condition_full_name_with_controlled_subgroup_matches_project(
    condition: str,
    project_full_name_sequences: List[tuple[str, ...]],
    project_abbrevs: frozenset[str],
) -> bool:
    """Match an exact disease full name followed by a narrow subgroup suffix.

    The disease full name must begin the condition and match an English project
    term token-for-token after the medical orthography normalization above.
    It may be followed immediately by one proven parenthetical abbreviation.
    The remaining suffix must start with ``with`` or ``without`` and may not
    introduce conjunctions, alternatives, aliases, or extra parentheticals.
    """
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
            if abbreviation_match.group(1).lower() not in project_abbrevs:
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
        if subgroup_tokens[0] not in _CONTROLLED_SUBGROUP_PREFIXES:
            continue
        if _SUBGROUP_RELATION_TOKENS.intersection(subgroup_tokens):
            continue
        return True
    return False


def _parenthetical_alias_full_name_matches_project(
    condition: str,
    project_term_tokens: List[frozenset[str]],
    project_abbrevs: frozenset[str],
) -> bool:
    """Require a parenthetical disease abbreviation to retain its full match.

    A shared parenthetical abbreviation alone is not enough: ``Other disease
    (PNH)`` must not be treated as PNH.  The text outside the abbreviation has
    to exactly match a project indication term after deterministic tokenization.
    """
    candidate_abbrevs = _extract_parenthetical_abbrevs(condition)
    if not (project_abbrevs & candidate_abbrevs):
        return False
    full_name = re.sub(r"[\(（][A-Z]{2,8}[\)）]", "", condition).strip()
    full_name_tokens = _normalize_indication_tokens(full_name)
    return bool(full_name_tokens) and any(
        full_name_tokens == project_tokens for project_tokens in project_term_tokens
    )


def _condition_full_name_with_controlled_descriptors_matches_project(
    condition: str,
    project_full_name_sequences: List[tuple[str, ...]],
) -> bool:
    """Match a full disease name with bounded severity/activity/age wording.

    ClinicalTrials.gov condition labels commonly add a trailing acronym
    (``Ulcerative Colitis (UC)``), a leading severity/activity descriptor
    (``Moderately to Severely Active Ulcerative Colitis``), or a narrow age
    qualifier (``Ulcerative Colitis in Adults``). These labels still identify
    the same disease.

    This is deliberately not substring or fuzzy matching. The project disease
    sequence must be contiguous and every remaining token must belong to a
    closed descriptor vocabulary or one exact age-qualifier sequence. Labels
    with conjunctions, another disease, an ``associated`` condition, or other
    uncontrolled suffixes remain unmatched.
    """
    normalized_condition = condition.strip()
    if not normalized_condition:
        return False
    trailing_abbreviation_match = re.search(
        r"[\(（]([A-Z]{2,8})[\)）]\s*$",
        normalized_condition,
    )
    trailing_abbreviation = ""
    if trailing_abbreviation_match:
        trailing_abbreviation = trailing_abbreviation_match.group(1).lower()
        normalized_condition = normalized_condition[
            : trailing_abbreviation_match.start()
        ].strip()
    if re.search(r"[\(\)（）;；:/\\&+|]", normalized_condition):
        return False
    if re.search(r"\s+[-\u2013\u2014]\s+", normalized_condition):
        return False

    candidate_tokens = tuple(
        token
        for token, _, _ in _english_condition_token_spans(normalized_condition)
    )
    if not candidate_tokens:
        return False

    for project_sequence in project_full_name_sequences:
        width = len(project_sequence)
        if width < 2 or len(candidate_tokens) < width:
            continue
        expected_abbreviation = "".join(
            token[0] for token in project_sequence if token
        )
        if (
            trailing_abbreviation
            and trailing_abbreviation != expected_abbreviation
        ):
            continue
        for index in range(len(candidate_tokens) - width + 1):
            if candidate_tokens[index : index + width] != project_sequence:
                continue
            prefix = candidate_tokens[:index]
            suffix = candidate_tokens[index + width :]
            prefix_allowed = not prefix or (
                len(prefix) <= 8
                and all(
                    token in _CONTROLLED_PRE_DISEASE_QUALIFIER_TOKENS
                    for token in prefix
                )
                and any(
                    token != "to"
                    for token in prefix
                )
            )
            suffix_allowed = (
                not suffix
                or suffix in _CONTROLLED_POST_DISEASE_QUALIFIER_SEQUENCES
            )
            if prefix_allowed and suffix_allowed:
                return True
    return False


def _candidate_indication_matching_condition_labels(
    candidate: Optional[Dict[str, Any]],
    project_facts: Optional[Dict[str, Any]],
) -> List[str]:
    """Return complete-list condition labels supporting a deterministic match."""
    if candidate is None or project_facts is None:
        return []
    conditions = candidate.get("conditions")
    if not isinstance(conditions, list):
        return []
    labels = [
        str(value).strip()
        for value in conditions
        if isinstance(value, str) and value.strip()
    ]
    if not labels:
        return []

    crswnp_labels = _candidate_crswnp_matching_condition_labels(
        candidate,
        project_facts,
    )
    if crswnp_labels:
        return crswnp_labels

    if _project_establishes_uc(project_facts):
        relation, labels, _ = _candidate_uc_semantic_evidence(
            candidate,
            project_facts,
        )
        if relation in {"exact", "mixed"} and labels:
            return labels

    return [
        label
        for label in labels
        if _candidate_indication_matches_project_conditions_only(
            {"conditions": [_strip_ontology_condition_qualifiers(label) or label]},
            project_facts,
        )
    ]


def _candidate_indication_matches_project(
    candidate: Optional[Dict[str, Any]],
    project_facts: Optional[Dict[str, Any]],
) -> bool:
    """Return True only when the candidate's explicit conditions clearly match
    the project indication.

    Uses three deterministic strategies only — no fuzzy token overlap:

    1. Exact token-set equivalence: the candidate condition's normalized
       token set must be identical to one of the project's non-empty
       terms (``indication`` or ``clinicaltrials_condition_term``).
       This handles word-order and punctuation differences but NOT
       partial disease name overlap.

    2. Proven abbreviation match: a standalone abbreviation or an exact
       full-name alias pair.  For ``ABBR - full disease name`` (or reverse),
       the abbreviation must be a separate dash-delimited segment and the
       full-name token set must exactly match a project term.  A parenthetical
       abbreviation also requires the surrounding full name to match exactly.

    3. Exact full-name prefix plus a controlled subgroup qualifier beginning
       with ``with`` or ``without``.  A proven parenthetical abbreviation may
       appear between the full name and qualifier.  Conjunctions, alternatives,
       extra aliases, and arbitrary suffixes are rejected.

    British/American medical ``haem-``/``hem-`` orthography is normalized only
    while tokenizing condition terms.

    No edit distance, fuzzy search, subset, or percentage-overlap
    matching is used.  Fail-closed for all other cases.
    """
    if candidate is None or project_facts is None:
        return False
    authoritative_relation = candidate.get("project_indication_relation")
    if authoritative_relation in {"exact", "mixed", "none"}:
        return authoritative_relation in {"exact", "mixed"}
    authoritative_match = candidate.get("project_indication_match")
    if isinstance(authoritative_match, bool):
        return authoritative_match
    indication = str(project_facts.get("indication", "")).strip()
    ct_term = str(project_facts.get("clinicaltrials_condition_term", "")).strip()
    if not indication and not ct_term:
        return False
    conds = candidate.get("conditions")
    if not isinstance(conds, list):
        return False
    cand_conditions = [str(c).strip() for c in conds if isinstance(c, str) and c.strip()]
    if not cand_conditions:
        return False
    if _project_establishes_crswnp(project_facts):
        relation, _, _ = _candidate_crswnp_semantic_evidence(
            candidate,
            project_facts,
        )
        return relation in {"exact", "mixed"}
    if _project_establishes_copd(project_facts):
        return any(
            _condition_is_exact_copd_label(condition)
            for condition in cand_conditions
        )
    if _project_establishes_uc(project_facts):
        relation, _, _ = _candidate_uc_semantic_evidence(
            candidate,
            project_facts,
        )
        if relation in {"exact", "mixed"}:
            return True

    # Build separate token sets for each project term (NOT merged)
    project_term_tokens: List[frozenset[str]] = []
    for term in [indication, ct_term]:
        if term:
            tokens = _normalize_indication_tokens(term)
            if tokens:
                project_term_tokens.append(tokens)
    if not project_term_tokens:
        return False
    project_full_name_sequences = [
        tuple(token for token, _, _ in _english_condition_token_spans(term))
        for term in [indication, ct_term]
        if term
    ]

    # Extract proven abbreviations from project raw text
    project_abbrevs = (
        _extract_parenthetical_abbrevs(indication)
        | _extract_parenthetical_abbrevs(ct_term)
        | _derive_project_full_name_abbreviations(
            project_full_name_sequences
        )
    )

    for c in cand_conditions:
        cleaned = _strip_ontology_condition_qualifiers(c) or c
        cand_tokens = _normalize_indication_tokens(cleaned)

        # Strategy 1: exact token-set equivalence with ANY single project term
        for pt_tokens in project_term_tokens:
            if cand_tokens and cand_tokens == pt_tokens:
                return True

        # Strategy 2: proven abbreviation match
        # Candidate condition IS a standalone uppercase abbreviation
        c_upper = cleaned.strip().upper()
        if (
            2 <= len(c_upper) <= 8
            and c_upper.isalpha()
            and c_upper == cleaned.strip()
            and c_upper.lower() in project_abbrevs
        ):
            return True
        if _condition_alias_pair_matches_project(
            cleaned, project_term_tokens, project_abbrevs
        ):
            return True
        if _condition_comma_inverted_full_name_matches_project(
            cleaned, project_term_tokens
        ):
            return True
        if _parenthetical_alias_full_name_matches_project(
            cleaned, project_term_tokens, project_abbrevs
        ):
            return True
        if _condition_full_name_with_controlled_descriptors_matches_project(
            cleaned,
            project_full_name_sequences,
        ):
            return True
        if _condition_full_name_with_controlled_subgroup_matches_project(
            cleaned, project_full_name_sequences, project_abbrevs
        ):
            return True

    return False


def _contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", value))


def _contains_latin_word(value: str) -> bool:
    return bool(re.search(r"[A-Za-z]{2,}", value))


def _is_cross_language_indication_unresolved(
    candidate: Optional[Dict[str, Any]],
    project_facts: Optional[Dict[str, Any]],
) -> bool:
    """Identify a lexical mismatch that still requires bilingual AI review.

    This does not assert clinical equivalence. It only distinguishes a
    Chinese-versus-English naming boundary from a same-language mismatch so
    the independent AI can assess exact disease-name equivalence with explicit
    source strings.
    """
    if candidate is None or project_facts is None:
        return False
    if _candidate_indication_relation(candidate, project_facts) != "none":
        return False
    project_indication = str(project_facts.get("indication", "")).strip()
    registry_term = str(
        project_facts.get("clinicaltrials_condition_term", "")
    ).strip()
    candidate_terms = [
        str(value).strip()
        for value in candidate.get("conditions", [])
        if isinstance(value, str) and value.strip()
    ]
    # The user-facing indication is the cross-language boundary. An unrelated
    # or overly broad registry retrieval term must not turn a Chinese-versus-
    # English unresolved case into a same-language mismatch. The registry term
    # is used only when no project indication text exists.
    project_text = project_indication or registry_term
    candidate_text = " ".join(candidate_terms)
    if not project_text or not candidate_text:
        return False
    return (
        _contains_cjk(project_text)
        and not _contains_latin_word(project_text)
        and _contains_latin_word(candidate_text)
        and not _contains_cjk(candidate_text)
    ) or (
        _contains_latin_word(project_text)
        and not _contains_cjk(project_text)
        and _contains_cjk(candidate_text)
        and not _contains_latin_word(candidate_text)
    )


def _model_supplies_cross_language_indication_evidence(
    dims: List[CompetitorTriageMatchingDimension],
    candidate: Optional[Dict[str, Any]],
    project_facts: Optional[Dict[str, Any]],
) -> bool:
    """Accept AI bilingual equivalence only with both literal source strings."""
    if not _is_cross_language_indication_unresolved(candidate, project_facts):
        return False
    indication_dim = next(
        (item for item in dims if item.dimension == "indication"),
        None,
    )
    if indication_dim is None or indication_dim.match != "match":
        return False
    detail = indication_dim.detail.strip()
    project_indication = str(project_facts.get("indication", "")).strip()
    if not project_indication or project_indication not in detail:
        return False
    candidate_conditions = [
        str(value).strip()
        for value in candidate.get("conditions", [])
        if isinstance(value, str) and value.strip()
    ]
    detail_folded = detail.casefold()
    return any(
        condition.casefold() in detail_folded
        for condition in candidate_conditions
    )


def _normalized_phase_codes(value: Any) -> frozenset[str]:
    """Normalize common Chinese and CT.gov phase labels without inference."""
    if value is None:
        return frozenset()
    values = value if isinstance(value, (list, tuple)) else [value]
    aliases = {
        "I期": "PHASE1",
        "1期": "PHASE1",
        "一期": "PHASE1",
        "II期": "PHASE2",
        "2期": "PHASE2",
        "二期": "PHASE2",
        "III期": "PHASE3",
        "3期": "PHASE3",
        "三期": "PHASE3",
        "IV期": "PHASE4",
        "4期": "PHASE4",
        "四期": "PHASE4",
    }
    codes: set[str] = set()
    for raw in values:
        text = str(raw).strip().upper().replace(" ", "")
        if not text:
            continue
        if text in {"PHASE1", "PHASE2", "PHASE3", "PHASE4", "EARLY_PHASE1"}:
            codes.add(text)
            continue
        for label, code in aliases.items():
            if label.upper() in text:
                codes.add(code)
    return frozenset(codes)


def _reconcile_source_truth_dimensions(
    dims: List[CompetitorTriageMatchingDimension],
    candidate: Optional[Dict[str, Any]],
    project_facts: Optional[Dict[str, Any]],
    *,
    ai_cross_language_equivalence: bool = False,
) -> List[CompetitorTriageMatchingDimension]:
    """Replace free-text dimension narratives with source-bounded summaries.

    The model may propose a relevance judgment, but the reviewer-visible text
    must be reproducible from the canonical candidate/project payload. This
    also prevents an apparently harmless design explanation from introducing
    unsupported claims such as dose escalation.
    """
    if candidate is None or project_facts is None:
        return dims

    existing = {item.dimension: item for item in dims}
    reconciled: Dict[str, CompetitorTriageMatchingDimension] = {}

    indication = str(project_facts.get("indication", "")).strip()
    ct_term = str(project_facts.get("clinicaltrials_condition_term", "")).strip()
    project_indication = indication or ct_term
    matching_conditions = [
        str(value).strip()
        for value in candidate.get("matching_conditions", [])
        if isinstance(value, str) and value.strip()
    ]
    displayed_conditions = [
        str(value).strip()
        for value in candidate.get("conditions", [])
        if isinstance(value, str) and value.strip()
    ]
    indication_relation = _candidate_indication_relation(
        candidate,
        project_facts,
    )
    indication_match = indication_relation in {"exact", "mixed"}
    if project_indication and (displayed_conditions or matching_conditions):
        if indication_relation == "mixed":
            source_labels = matching_conditions or displayed_conditions
            if _project_establishes_crswnp(project_facts):
                indication_detail = (
                    "候选登记条件或权威标题明确包含CRSwNP人群，"
                    "同时包含无鼻息肉/未限定鼻息肉亚组；按混合人群处理"
                )
            elif _project_establishes_uc(project_facts):
                indication_detail = (
                    "候选完整登记条件明确包含溃疡性结肠炎相关证据，"
                    "同时包含其他未匹配的疾病或人群标签；按混合人群处理"
                )
            else:
                indication_detail = (
                    "候选完整登记条件明确包含项目适应症，"
                    "同时包含其他未匹配的疾病或人群标签；按混合人群处理"
                )
            if source_labels:
                indication_detail += "：" + "、".join(source_labels[:3])
            indication_state = "partial"
        elif indication_match:
            source_labels = matching_conditions or [project_indication]
            indication_detail = (
                "候选完整登记事实支持与项目适应症一致："
                + "、".join(source_labels[:3])
            )
            indication_state = "match"
        elif ai_cross_language_equivalence:
            source_labels = displayed_conditions
            indication_detail = (
                "独立AI基于原始中英文疾病名称判定等价；"
                f"项目适应症：{project_indication}；候选登记条件："
                + "、".join(source_labels[:3])
            )
            indication_state = "match"
        else:
            indication_detail = (
                f"项目适应症为{project_indication}；候选登记条件未发现一致条目"
            )
            if displayed_conditions:
                indication_detail += "（已展示：" + "、".join(displayed_conditions[:3]) + "）"
            indication_state = "mismatch"
    else:
        indication_detail = "项目或候选未提供足够的适应症条件，不能判断匹配性"
        indication_state = "unknown"
    reconciled["indication"] = CompetitorTriageMatchingDimension(
        dimension="indication",
        match=indication_state,  # type: ignore[arg-type]
        detail=indication_detail,
    )

    project_phase = str(project_facts.get("study_phase", "")).strip()
    candidate_phases = [
        str(value).strip()
        for value in candidate.get("phases", [])
        if isinstance(value, str) and value.strip()
    ]
    project_phase_codes = _normalized_phase_codes(project_phase)
    candidate_phase_codes = _normalized_phase_codes(candidate_phases)
    if project_phase_codes and candidate_phase_codes:
        phase_state = (
            "match" if project_phase_codes & candidate_phase_codes else "mismatch"
        )
        phase_detail = (
            f"项目分期：{project_phase}；候选登记分期："
            + "、".join(candidate_phases)
        )
    else:
        phase_state = "unknown"
        phase_detail = (
            f"项目分期：{project_phase or '未提供'}；候选登记分期："
            + ("、".join(candidate_phases) if candidate_phases else "未提供")
        )
    reconciled["phase"] = CompetitorTriageMatchingDimension(
        dimension="phase",
        match=phase_state,  # type: ignore[arg-type]
        detail=phase_detail,
    )

    for dimension in _PROTECTED_DIMENSIONS:
        if dimension in existing:
            reconciled[dimension] = existing[dimension]

    design_pattern = project_facts.get("design_pattern")
    if isinstance(design_pattern, str):
        project_design = design_pattern.strip()
    elif design_pattern:
        project_design = _canonical_json(design_pattern)
    else:
        project_design = ""
    design_parts: List[str] = []
    for key, label in (
        ("design_allocation", "随机化"),
        ("design_intervention_model", "干预模型"),
        ("design_masking", "盲法"),
    ):
        value = str(candidate.get(key, "")).strip()
        if value:
            design_parts.append(f"{label}={value}")
    candidate_design = "，".join(design_parts)
    design_detail = (
        f"项目设计：{project_design or '待确认'}；"
        f"候选登记设计：{candidate_design or '未提供'}"
    )
    reconciled["design"] = CompetitorTriageMatchingDimension(
        dimension="design",
        match="unknown",
        detail=design_detail,
    )

    return [
        reconciled.get(
            name,
            existing.get(
                name,
                CompetitorTriageMatchingDimension(
                    dimension=name,
                    match="unknown",
                    detail="缺少可核查信息",
                ),
            ),
        )
        for name in _MATCH_DIMENSIONS
    ]


def _candidate_intervention_evidence_state(
    candidate: Optional[Dict[str, Any]],
) -> str:
    """Return pharmacologic, non_pharmacologic, or unknown from explicit types.

    Missing intervention types are evidence gaps, not proof that a study is
    non-pharmacologic. This distinction prevents absent registry fields from
    manufacturing an exclusion while preserving fail-closed handling for an
    explicitly supplied DEVICE/PROCEDURE/RADIATION-only study.
    """
    if candidate is None:
        return "unknown"
    interventions = candidate.get("interventions")
    if not isinstance(interventions, list):
        return "unknown"
    explicit_types = {
        str(intervention.get("intervention_type", "")).strip().upper()
        for intervention in interventions
        if isinstance(intervention, dict)
        and str(intervention.get("intervention_type", "")).strip()
    }
    if not explicit_types:
        return "unknown"
    if explicit_types & _PHARMACOLOGIC_INTERVENTION_TYPES:
        return "pharmacologic"
    return "non_pharmacologic"


def _sanitize_reason(
    model_reason: str,
    candidate: Optional[Dict[str, Any]],
    project_facts: Optional[Dict[str, Any]],
    dims: List[CompetitorTriageMatchingDimension],
    doc_suitability: Dict[str, Any],
    final_classification: Optional[CompetitorTriageClassification] = None,
    *,
    ai_cross_language_equivalence: bool = False,
) -> str:
    """Generate a conservative reviewer-facing reason from explicit input.

    Model free text is never exposed as the authoritative reason. The service
    regenerates a compact summary from indication, phase, intervention,
    design and document fields, then appends a conclusion consistent with the
    server-reconciled classification.

    The conclusion is consistent with the *final* classification:
    - ``indirect_reference`` + same indication + pharmacologic → "可作为同适应症药物研究参考"
    - ``excluded`` → "不纳入竞品篮子"
    - other → no trailing conclusion

    """
    if project_facts is None:
        return model_reason

    parts: List[str] = []

    # Indication — use the same server-side matching function as classification
    indication = str(project_facts.get("indication", "")).strip()
    cand_conditions: List[str] = []
    if candidate is not None:
        conds = candidate.get("conditions")
        if isinstance(conds, list):
            cand_conditions = [str(c) for c in conds if isinstance(c, str) and c]
    if indication:
        if cand_conditions:
            indication_relation = _candidate_indication_relation(
                candidate,
                project_facts,
            )
            if indication_relation == "mixed":
                # Keep the literal gate token "适应症一致" required by D017/UC
                # reason_consistency acceptance, while stating mixed labels.
                parts.append(
                    f"适应症一致（混合登记标签；项目：{indication}；"
                    "候选完整登记条件同时包含其他未匹配的疾病或人群标签）"
                )
            elif indication_relation == "exact":
                parts.append(f"适应症一致（{indication}）")
            elif ai_cross_language_equivalence:
                parts.append(
                    f"适应症一致（独立AI核对原始中英文疾病名称；"
                    f"项目：{indication}；候选："
                    f"{'、'.join(cand_conditions[:3])}）"
                )
            else:
                parts.append(
                    f"适应症不同（项目：{indication}；候选："
                    f"{'、'.join(cand_conditions[:3])}）"
                )
        else:
            parts.append(f"项目适应症：{indication}")

    # Phase
    study_phase = project_facts.get("study_phase", "")
    cand_phases: List[str] = []
    if candidate is not None:
        phs = candidate.get("phases")
        if isinstance(phs, list):
            cand_phases = [str(p) for p in phs if isinstance(p, str) and p]
    if cand_phases:
        parts.append(f"候选分期：{'、'.join(cand_phases)}")
    if study_phase:
        parts.append(f"项目分期：{study_phase}")

    # Intervention names / types
    if candidate is not None:
        interventions = candidate.get("interventions")
        if isinstance(interventions, list):
            iv_names: List[str] = []
            iv_types: List[str] = []
            for iv in interventions:
                if isinstance(iv, dict):
                    name = str(iv.get("name", "")).strip()
                    itype = str(iv.get("intervention_type", "")).strip()
                    if name:
                        iv_names.append(name)
                    if itype and itype not in iv_types:
                        iv_types.append(itype)
            if iv_names:
                parts.append(f"候选干预：{'、'.join(iv_names[:3])}")
            if iv_types:
                parts.append(f"干预类型：{'、'.join(iv_types)}")

    # Design fields
    if candidate is not None:
        allocation = str(candidate.get("design_allocation", "")).strip()
        model = str(candidate.get("design_intervention_model", "")).strip()
        masking = str(candidate.get("design_masking", "")).strip()
        enrollment = candidate.get("enrollment_count")
        design_bits: List[str] = []
        if allocation:
            design_bits.append(f"随机化={allocation}")
        if model:
            design_bits.append(f"干预模型={model}")
        if masking:
            design_bits.append(f"盲法={masking}")
        if design_bits:
            parts.append("候选设计：" + "，".join(design_bits))
        if enrollment is not None:
            parts.append(f"样本量：{enrollment}")

    # Document availability
    if doc_suitability.get("has_public_protocol") and doc_suitability.get("has_public_sap"):
        parts.append("公开文档：方案与统计分析计划")
    elif doc_suitability.get("has_public_protocol"):
        parts.append("公开文档：方案")
    elif doc_suitability.get("has_public_sap"):
        parts.append("仅公开统计分析计划（不进入竞品方案语料库）")
    else:
        parts.append("无公开方案或统计分析计划")

    # Protected dimensions unknown
    unknown_dims = [
        d.dimension for d in dims
        if d.dimension in _PROTECTED_DIMENSIONS and d.match == "unknown"
    ]
    if unknown_dims:
        labels = [_DIM_CHINESE_LABELS.get(d, d) for d in unknown_dims]
        parts.append(
            "因当前项目"
            + "、".join(labels)
            + "未知，不能判断直接竞争性"
        )

    if final_classification == CompetitorTriageClassification.INDIRECT_REFERENCE:
        intervention_state = _candidate_intervention_evidence_state(candidate)
        if intervention_state == "pharmacologic":
            parts.append("可作为同适应症药物研究参考")
        else:
            parts.append("候选干预类型待核实，可作为同适应症研究参考")
    elif final_classification == CompetitorTriageClassification.EXCLUDED:
        parts.append("不纳入竞品篮子")
    elif final_classification == CompetitorTriageClassification.DIRECT_COMPETITOR:
        parts.append("可作为直接竞品候选供医学审阅")

    return "。".join(parts) + "。"


def _enforce_classification_eligibility(
    classification: CompetitorTriageClassification,
    confidence: float,
    project_facts: Optional[Dict[str, Any]],
    candidate: Optional[Dict[str, Any]],
    reason: str,
    *,
    ai_cross_language_equivalence: bool = False,
) -> tuple:
    """Server-side classification eligibility reconciliation for ALL model
    classifications.

    Rules:
    - ``excluded`` is reconciled to ``indirect_reference`` when deterministic
      same-indication evidence is present, no explicit non-pharmacologic type
      is supplied, and either critical project facts are missing or useful
      Protocol evidence is available. This prevents unknown facts from
      manufacturing exclusion while preserving explicit contrary evidence.
    - ``direct_competitor`` requires all three critical project dimensions
      (technology_type, administration_routes, target_mechanism) to be known
      to be preserved.  When any is unknown, downgrade based on candidate's
      explicit input:
        - Same indication without explicit non-pharmacologic evidence
          → indirect_reference
        - Otherwise → excluded
    - ``indirect_reference`` is ALWAYS re-validated regardless of project
      facts: it must have the same indication and must not have only explicit
      non-pharmacologic intervention types. Missing intervention type remains
      an evidence gap and lowers confidence; it does not prove exclusion.

    Returns a ``(classification, confidence)`` tuple.
    """
    if project_facts is None:
        return classification, confidence

    pp = project_facts.get("product_profile") or {}
    tech = pp.get("technology_type", "")
    routes = pp.get("administration_routes", [])
    target = project_facts.get("target_mechanism", "")

    tech_known = _project_fact_non_empty(tech)
    route_known = _project_fact_non_empty(routes)
    target_known = _project_fact_non_empty(target)

    all_critical_known = tech_known and route_known and target_known
    indication_relation = _candidate_indication_relation(
        candidate,
        project_facts,
    )
    same_indication = (
        indication_relation in {"exact", "mixed"}
        or ai_cross_language_equivalence
    )
    intervention_state = _candidate_intervention_evidence_state(candidate)
    explicitly_non_pharmacologic = intervention_state == "non_pharmacologic"
    doc_suitability = _derive_document_suitability(candidate, "")
    has_useful_documents = bool(doc_suitability["has_public_protocol"])

    if indication_relation == "mixed":
        if explicitly_non_pharmacologic:
            return (
                CompetitorTriageClassification.EXCLUDED,
                min(confidence, 0.3),
            )
        confidence_cap = (
            0.75 if intervention_state == "pharmacologic" else 0.6
        )
        return (
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            min(confidence, confidence_cap),
        )

    if classification == CompetitorTriageClassification.EXCLUDED:
        if (
            same_indication
            and not explicitly_non_pharmacologic
            and (not all_critical_known or has_useful_documents)
        ):
            confidence_cap = (
                0.5 if intervention_state == "pharmacologic" else 0.4
            )
            return (
                CompetitorTriageClassification.INDIRECT_REFERENCE,
                min(confidence, confidence_cap),
            )
        return classification, confidence

    # indirect_reference is ALWAYS re-validated, even when all project
    # critical facts are known.  The model's indirect classification
    # does not prove the candidate has the right indication. An absent
    # intervention type is unknown; only an explicit non-pharmacologic type
    # rules out this drug-protocol reference category.
    if classification == CompetitorTriageClassification.INDIRECT_REFERENCE:
        if same_indication and not explicitly_non_pharmacologic:
            confidence_cap = (
                0.8 if intervention_state == "pharmacologic" else 0.6
            )
            return classification, min(confidence, confidence_cap)
        new_conf = min(confidence, 0.3)
        return CompetitorTriageClassification.EXCLUDED, new_conf

    # direct_competitor: only preserved when all critical facts known
    if all_critical_known:
        return classification, confidence

    # At least one critical dimension is unknown — cannot allow
    # direct_competitor.  Downgrade based on candidate's explicit input.
    if same_indication and not explicitly_non_pharmacologic:
        confidence_cap = (
            0.5 if intervention_state == "pharmacologic" else 0.4
        )
        new_conf = min(confidence, confidence_cap)
        return CompetitorTriageClassification.INDIRECT_REFERENCE, new_conf

    # Different indication or explicit non-pharmacologic intervention
    # → excluded. Missing conditions also fail closed because same_indication
    # cannot be established.
    new_conf = min(confidence, 0.3)
    return CompetitorTriageClassification.EXCLUDED, new_conf


def _validate_chunk_response(
    response: Dict[str, Any],
    expected_nct_ids: List[str],
    chunk_input: Optional[Dict[str, Any]] = None,
) -> List[CompetitorTriageCandidateResult]:
    """Validate a model response as a complete exact permutation of the chunk.

    Failures (all raise CompetitorTriageError):
    - response is not a dict or missing "results"
    - results is not a list
    - nct_id set does not exactly match expected (unknown, missing, duplicate)
    - invalid classification enum
    - confidence out of [0, 1]
    """
    if not isinstance(response, dict):
        raise CompetitorTriageError("response is not a JSON object")
    results_raw = response.get("results")
    if not isinstance(results_raw, list):
        raise CompetitorTriageError("response missing 'results' array")

    expected_set = set(expected_nct_ids)
    seen: Dict[str, CompetitorTriageCandidateResult] = {}

    for item in results_raw:
        if not isinstance(item, dict):
            raise CompetitorTriageError("each result must be a JSON object")
        nct_id = item.get("nct_id")
        if not isinstance(nct_id, str) or not nct_id:
            raise CompetitorTriageError("result missing non-empty nct_id")
        if nct_id not in expected_set:
            raise CompetitorTriageError(
                f"unknown nct_id in response: {nct_id}"
            )
        if nct_id in seen:
            raise CompetitorTriageError(
                f"duplicate nct_id in response: {nct_id}"
            )

        classification = item.get("classification")
        if classification not in _ALLOWED_CLASSIFICATIONS:
            raise CompetitorTriageError(
                f"invalid classification for {nct_id}: {classification}"
            )

        confidence = item.get("confidence")
        try:
            confidence_float = float(confidence)
        except (TypeError, ValueError):
            raise CompetitorTriageError(
                f"invalid confidence for {nct_id}: {confidence}"
            )
        if confidence_float < 0.0 or confidence_float > 1.0:
            raise CompetitorTriageError(
                f"confidence out of range for {nct_id}: {confidence_float}"
            )

        matching_dims: List[CompetitorTriageMatchingDimension] = []
        dims_raw = item.get("matching_dimensions", [])
        if isinstance(dims_raw, list):
            for dim in dims_raw:
                if not isinstance(dim, dict):
                    continue
                dim_name = str(dim.get("dimension", "")).strip()
                if not dim_name:
                    continue
                match_val = str(dim.get("match", "unknown")).strip()
                if match_val not in {"match", "partial", "mismatch", "unknown"}:
                    match_val = "unknown"
                matching_dims.append(
                    CompetitorTriageMatchingDimension(
                        dimension=dim_name,
                        match=match_val,  # type: ignore[arg-type]
                        detail=str(dim.get("detail", "")),
                    )
                )

        # --- v4 source-truth enforcement ---
        candidate_explicit: Optional[Dict[str, Any]] = None
        project_facts: Optional[Dict[str, Any]] = None
        if chunk_input is not None:
            project_facts = chunk_input.get("project_facts")
            candidates_list = chunk_input.get("candidates")
            if isinstance(candidates_list, list):
                for cand in candidates_list:
                    if (
                        isinstance(cand, dict)
                        and cand.get("nct_id") == nct_id
                    ):
                        candidate_explicit = cand
                        break

        # A. Document suitability: deterministic from document_type
        doc_raw = item.get("document_suitability", {})
        model_doc_role = ""
        if isinstance(doc_raw, dict):
            model_doc_role = str(doc_raw.get("document_role", ""))
        doc_suitability_data = _derive_document_suitability(
            candidate_explicit, model_doc_role
        )

        # B. Matching dimension evidence gate
        new_gaps: List[str] = []
        matching_dims = _enforce_matching_dimensions(
            matching_dims, candidate_explicit, project_facts, new_gaps
        )
        ai_cross_language_equivalence = (
            _model_supplies_cross_language_indication_evidence(
                matching_dims,
                candidate_explicit,
                project_facts,
            )
        )
        matching_dims = _reconcile_source_truth_dimensions(
            matching_dims,
            candidate_explicit,
            project_facts,
            ai_cross_language_equivalence=ai_cross_language_equivalence,
        )

        # Reviewer-visible evidence gaps are deterministic. Model free text can
        # otherwise smuggle unsupported route, mechanism or design claims back
        # into an output whose classification has already been reconciled.
        evidence_gaps = list(dict.fromkeys(new_gaps))

        # C/D. Apply classification enforcement BEFORE reason sanitization
        # so the reason conclusion is consistent with the final classification.
        model_reason = str(item.get("reason", ""))
        classification_enum = CompetitorTriageClassification(classification)

        # D. Classification eligibility reconciliation for ALL classifications
        classification_enum, confidence_float = (
            _enforce_classification_eligibility(
                classification_enum,
                confidence_float,
                project_facts,
                candidate_explicit,
                model_reason,
                ai_cross_language_equivalence=ai_cross_language_equivalence,
            )
        )

        # C. Reason failure closure (uses final classification for conclusion)
        reason = _sanitize_reason(
            model_reason, candidate_explicit, project_facts,
            matching_dims, doc_suitability_data,
            final_classification=classification_enum,
            ai_cross_language_equivalence=ai_cross_language_equivalence,
        )

        seen[nct_id] = CompetitorTriageCandidateResult(
            nct_id=nct_id,
            classification=classification_enum,
            confidence=round(confidence_float, 4),
            matching_dimensions=matching_dims,
            document_suitability=doc_suitability_data,  # type: ignore[arg-type]
            reason=reason,
            evidence_gaps=evidence_gaps,
        )

    missing = expected_set - set(seen.keys())
    if missing:
        raise CompetitorTriageError(
            f"response is missing nct_ids: {sorted(missing)}"
        )

    # Return in the deterministic NCT-sorted order of the expected list.
    return [seen[nct_id] for nct_id in expected_nct_ids]


def _repairable_present_nct_ids(
    response: Dict[str, Any],
    expected_nct_ids: List[str],
) -> Optional[List[str]]:
    """Return the valid expected-ID subset when only output coverage is short.

    Shape errors, unknown IDs and duplicate IDs are not repairable. Other
    semantic validation remains the responsibility of
    ``_validate_chunk_response`` before any repair call is made.
    """
    if not isinstance(response, dict):
        return None
    results_raw = response.get("results")
    if not isinstance(results_raw, list):
        return None

    expected_set = set(expected_nct_ids)
    seen: set[str] = set()
    for item in results_raw:
        if not isinstance(item, dict):
            return None
        nct_id = item.get("nct_id")
        if (
            not isinstance(nct_id, str)
            or not nct_id
            or nct_id not in expected_set
            or nct_id in seen
        ):
            return None
        seen.add(nct_id)

    if seen == expected_set:
        return None
    return [nct_id for nct_id in expected_nct_ids if nct_id in seen]


def _missing_only_chunk_input(
    chunk_input: Dict[str, Any],
    missing_nct_ids: List[str],
) -> Dict[str, Any]:
    """Build one bounded repair payload without changing the stored input."""
    missing_set = set(missing_nct_ids)
    candidates = chunk_input.get("candidates")
    filtered_candidates = [
        candidate
        for candidate in candidates
        if isinstance(candidate, dict) and candidate.get("nct_id") in missing_set
    ] if isinstance(candidates, list) else []
    return {
        **chunk_input,
        "candidates": filtered_candidates,
        "repair_mode": "missing_nct_ids_only",
        "required_nct_ids": list(missing_nct_ids),
        "expected_result_count": len(missing_nct_ids),
    }


# ---------------------------------------------------------------------------
# Durable job result
# ---------------------------------------------------------------------------


@dataclass
class TriageDurableStartResult:
    """Return value from create_run / retry_run when durable mode is enabled.

    Contains both the triage business ``run_id`` and the durable ``job_id``
    so the HTTP layer can return 202 + both locators.  The caller must NOT
    call ``_execute_run`` — the durable worker owns the long AI path.
    """

    run_id: str
    project_id: str
    job_id: str
    reused: bool = False


# ---------------------------------------------------------------------------
# Durable executor for competitor triage
# ---------------------------------------------------------------------------


class CompetitorTriageExecutor:
    """Durable-job executor that runs the existing chunk AI loop under the
    shared claim/lease/heartbeat/cancel contract.

    The executor reuses successful chunks, calls the product AI for each
    pending/failed chunk, writes results to ``writing_reference`` store, and
    completes the durable job with ``artifact_locator = {run_id, snapshot_id}``.
    """

    job_type = TRIAGE_DURABLE_JOB_TYPE

    def __init__(
        self,
        service: "CompetitorTriageService",
    ) -> None:
        self._service = service

    def execute(
        self,
        job: DurableJobRecord,
        claim_token: str,
        cancel_check: Callable[[], bool],
        heartbeat: Callable[[DurableJobProgressPayload], bool],
    ) -> "DurableJobResult":
        """Run the triage chunk loop under the durable contract.

        Returns a DurableJobResult. On error, sets ``error`` and ``retryable``.

        Old-owner isolation invariant: if ``cancel_check()`` or
        ``heartbeat()`` reports loss of ownership at any point, the executor
        returns immediately WITHOUT any repository write — not even a
        "no-change" persist — because that could overwrite a new owner's
        progress.
        """
        from services.api.app.medical_writing_durable_jobs import DurableJobResult

        payload = json.loads(job.payload_json or "{}")
        run_id = payload.get("run_id", "")
        project_id = job.project_id
        if not run_id:
            return DurableJobResult(
                error="durable payload missing run_id",
                retryable=False,
            )
        try:
            frozen_route = FrozenTriageAiRoute.parse(payload.get("ai_route"))
            if (
                job.provider != frozen_route.provider
                or job.model != frozen_route.model
            ):
                raise CompetitorTriageError(
                    "durable job provider/model columns do not match "
                    "the frozen AI route"
                )
            provider = self._service._build_provider_for_durable_run(
                project_id, run_id, frozen_route
            )
            primary_verified = (
                provider
                if isinstance(provider, VerifiedTriageProvider)
                else VerifiedTriageProvider(
                    provider,
                    test_only_injection=bool(
                        getattr(provider, "test_only_injection", False)
                    ),
                )
            )
            frozen_fallback_routes: List[FrozenTriageAiRoute] = []
            route_chain = payload.get("ai_route_chain")
            if route_chain is not None:
                if (
                    not isinstance(route_chain, dict)
                    or route_chain.get("schema_version")
                    != TRIAGE_ROUTE_CHAIN_VERSION
                    or not isinstance(route_chain.get("fallback_routes"), list)
                ):
                    raise CompetitorTriageError(
                        "durable AI fallback route chain is malformed"
                    )
                try:
                    frozen_fallback_routes = [
                        FrozenTriageAiRoute.parse(item)
                        for item in route_chain["fallback_routes"]
                    ]
                except CompetitorTriageError as exc:
                    raise CompetitorTriageError(
                        "durable AI fallback route entry is malformed"
                    ) from exc
                profile_ids = [
                    frozen_route.profile_id,
                    *(item.profile_id for item in frozen_fallback_routes),
                ]
                if len(profile_ids) != len(set(profile_ids)):
                    raise CompetitorTriageError(
                        "durable AI fallback route chain contains duplicates"
                    )
            provider_chain = [(frozen_route, primary_verified)]
            for fallback_route in frozen_fallback_routes:
                try:
                    fallback_provider = (
                        self._service._build_provider_for_durable_run(
                            project_id, run_id, fallback_route
                        )
                    )
                    fallback_verified = (
                        fallback_provider
                        if isinstance(fallback_provider, VerifiedTriageProvider)
                        else VerifiedTriageProvider(fallback_provider)
                    )
                except CompetitorTriageError:
                    logger.warning(
                        "frozen triage fallback route is unavailable: profile=%s identity=%s",
                        fallback_route.profile_id,
                        fallback_route.identity_hash,
                    )
                    continue
                provider_chain.append((fallback_route, fallback_verified))
            verified = FallbackTriageProvider(
                provider_chain,
                frozen_route_hashes=[
                    frozen_route.identity_hash,
                    *(item.identity_hash for item in frozen_fallback_routes),
                ],
            )
        except CompetitorTriageError as exc:
            return DurableJobResult(error=str(exc), retryable=False)

        run = self._service.repository.triage_run(project_id, run_id)
        if run is None:
            return DurableJobResult(
                error=f"triage run not found: {run_id}",
                retryable=False,
            )

        snapshot = self._service.repository.search_snapshot(
            project_id, run.snapshot_id
        )
        journey = self._service.journey_service.get(project_id)
        candidate_map = {c.nct_id: c for c in snapshot.candidates}

        # Count how many chunks still need work
        chunks_to_run = [
            ch
            for ch in run.chunks
            if ch.status != CompetitorTriageChunkStatus.SUCCEEDED
        ]
        total_to_run = len(chunks_to_run)
        total_chunks = len(run.chunks)
        completed_this_pass = sum(
            1
            for chunk in run.chunks
            if chunk.status == CompetitorTriageChunkStatus.SUCCEEDED
        )
        deterministic_candidate_count = sum(
            len(chunk.nct_ids)
            for chunk in run.chunks
            if chunk.chunk_id.startswith(_DETERMINISTIC_CHUNK_PREFIX)
        )
        ai_chunk_total = sum(
            1
            for chunk in run.chunks
            if not chunk.chunk_id.startswith(_DETERMINISTIC_CHUNK_PREFIX)
        )

        # Publish the real workload before the first provider call. Large
        # snapshots can spend minutes in their first chunk; without this
        # heartbeat the UI can only show 0/0 even though the durable run
        # already knows its complete chunk count.
        if total_to_run and not self._heartbeat_progress(
            heartbeat,
            completed_this_pass,
            total_chunks,
            deterministic_candidate_count=deterministic_candidate_count,
            ai_chunk_total=ai_chunk_total,
        ):
            return self._lost_ownership_result(
                completed_this_pass, total_chunks
            )

        # Defect 1 (v1): maintain the FULL ordered chunk list so unprocessed
        # tail chunks survive a crash/cancel.  We replace each processed
        # index in-place rather than building a partial list.
        current_chunks: List[CompetitorTriageChunkRecord] = list(run.chunks)

        for idx, chunk in enumerate(current_chunks):
            if chunk.status == CompetitorTriageChunkStatus.SUCCEEDED:
                continue

            # Cooperative cancel: stop between chunks.  NO repository write
            # — we may have lost ownership and must not overwrite a new
            # owner's progress (P0 defect 2).
            if cancel_check():
                return DurableJobResult(
                    error="cancelled",
                    retryable=True,
                    progress=DurableJobProgressPayload(
                        phase="cancelled",
                        percent=min(1.0, completed_this_pass / max(1, total_chunks)),
                        step=completed_this_pass,
                        step_total=total_chunks,
                        message="triage cancelled between chunks",
                    ),
                )

            chunk_candidates = [
                candidate_map[nct]
                for nct in chunk.nct_ids
                if nct in candidate_map
            ]
            if not chunk_candidates:
                chunk = chunk.model_copy(
                    update={
                        "status": CompetitorTriageChunkStatus.FAILED,
                        "error_message": "no candidates found for chunk nct_ids",
                        "attempt": chunk.attempt + 1,
                    }
                )
                current_chunks[idx] = chunk
                completed_this_pass += 1
                # P0 defect 3: check ownership before any business write.
                if not self._heartbeat_progress(
                    heartbeat,
                    completed_this_pass,
                    total_chunks,
                    deterministic_candidate_count=deterministic_candidate_count,
                    ai_chunk_total=ai_chunk_total,
                ):
                    return self._lost_ownership_result(
                        completed_this_pass, total_chunks
                    )
                continue

            chunk_input = _build_chunk_input(
                journey, chunk_candidates, chunk.chunk_index
            )
            input_hash = _hash_value(chunk_input)
            if input_hash != chunk.input_hash:
                chunk = chunk.model_copy(
                    update={
                        "status": CompetitorTriageChunkStatus.FAILED,
                        "error_message": "input hash drift detected",
                        "attempt": chunk.attempt + 1,
                    }
                )
                current_chunks[idx] = chunk
                completed_this_pass += 1
                # P0 defect 3: check ownership before any business write.
                if not self._heartbeat_progress(
                    heartbeat,
                    completed_this_pass,
                    total_chunks,
                    deterministic_candidate_count=deterministic_candidate_count,
                    ai_chunk_total=ai_chunk_total,
                ):
                    return self._lost_ownership_result(
                        completed_this_pass, total_chunks
                    )
                continue

            updated_chunk = self._service._execute_chunk(
                verified, chunk, chunk_input, chunk.nct_ids
            )

            # P0 defect 2: after the provider call returns, recheck
            # cancellation / claim ownership BEFORE any business write.
            # If lost, return immediately with NO repository write — not
            # even persisting current_chunks, because a new owner may have
            # already committed progress.
            if cancel_check():
                return DurableJobResult(
                    error="cancelled",
                    retryable=True,
                    progress=DurableJobProgressPayload(
                        phase="cancelled",
                        percent=min(1.0, completed_this_pass / max(1, total_chunks)),
                        step=completed_this_pass,
                        step_total=total_chunks,
                        message="triage cancelled after provider call",
                    ),
                )

            current_chunks[idx] = updated_chunk
            completed_this_pass += 1

            # P0 defect 2: the heartbeat RENEWS THE LEASE and proves
            # ownership.  It must succeed BEFORE the business write.
            # If it returns False, the lease was lost — return immediately
            # with NO repository write.
            if not self._heartbeat_progress(
                heartbeat,
                completed_this_pass,
                total_chunks,
                deterministic_candidate_count=deterministic_candidate_count,
                ai_chunk_total=ai_chunk_total,
            ):
                return self._lost_ownership_result(
                    completed_this_pass, total_chunks
                )

            # Ownership confirmed — safe to persist business progress.
            run_partial = run.model_copy(update={"chunks": current_chunks})
            self._service.repository.store_triage_run(run_partial)

        # P0 defect 3: ownership check immediately before finalization.
        if cancel_check():
            return DurableJobResult(
                error="cancelled",
                retryable=True,
                progress=DurableJobProgressPayload(
                    phase="cancelled",
                    percent=min(1.0, completed_this_pass / max(1, total_chunks)),
                    step=completed_this_pass,
                    step_total=total_chunks,
                    message="triage cancelled before finalize",
                ),
            )

        # All chunks processed — finalize the run
        run = run.model_copy(update={"chunks": current_chunks})
        run = self._service._finalize_run_status(run)
        if ai_chunk_total > 0 and (
            not run.provider
            or run.provider == "deterministic_registry_rules"
            or not run.response_model
            or run.response_model == "not_applicable"
        ):
            # A failed AI call may have no response provenance, but the durable
            # job still owns an immutable configured route. Keep run-level
            # attribution on that route instead of mislabeling a mixed partial
            # run as deterministic-only.
            run = run.model_copy(
                update={
                    "provider": frozen_route.provider,
                    "response_model": frozen_route.model,
                }
            )
        # The terminal status (review_ready / partial_failed / failed) must
        # reach the store: the parent pipeline reconciles against THIS record
        # when the child job completes. Leaving the last intermediate write
        # (which still carries the stale queued status) as the visible state
        # made the parent read a phantom in-progress run and froze journeys.
        run = run.model_copy(update={"updated_at": _utc_now()})
        self._service.repository.store_triage_run(run)

        # Build artifact locator
        artifact_locator = json.dumps(
            {"run_id": run.run_id, "snapshot_id": run.snapshot_id}
        )
        output_hash = run.canonical_input_hash  # stable identity

        # Determine outcome
        if run.status == CompetitorTriageRunStatus.FAILED:
            return DurableJobResult(
                error="all chunks failed",
                retryable=True,
                artifact_locator=artifact_locator,
                provider=run.provider or frozen_route.provider,
                model=run.response_model or frozen_route.model,
                progress=DurableJobProgressPayload(
                    phase="failed",
                    percent=1.0,
                    step=len(run.chunks),
                    step_total=len(run.chunks),
                    message="triage completed with failures",
                ),
            )

        return DurableJobResult(
            output_hash=output_hash,
            artifact_locator=artifact_locator,
            provider=run.provider or frozen_route.provider,
            model=run.response_model or frozen_route.model,
            progress=DurableJobProgressPayload(
                phase=(
                    "completed"
                    if run.status == CompetitorTriageRunStatus.REVIEW_READY
                    else "partial"
                ),
                percent=1.0,
                step=len(run.chunks),
                step_total=len(run.chunks),
                message=f"triage {run.status.value}",
            ),
        )

    @staticmethod
    def _lost_ownership_result(
        completed: int, total_to_run: int
    ) -> "DurableJobResult":
        """Build a standard result for when ownership is lost mid-execution.

        No repository write should have occurred before calling this.
        """
        from services.api.app.medical_writing_durable_jobs import DurableJobResult

        return DurableJobResult(
            error="ownership lost during chunk execution",
            retryable=True,
            progress=DurableJobProgressPayload(
                phase="cancelled",
                percent=min(1.0, completed / max(1, total_to_run)),
                step=completed,
                step_total=total_to_run,
                message="triage ownership lost",
            ),
        )

    @staticmethod
    def _heartbeat_progress(
        heartbeat: Callable[[DurableJobProgressPayload], bool],
        completed: int,
        total_chunks: int,
        *,
        deterministic_candidate_count: int = 0,
        ai_chunk_total: int = 0,
    ) -> bool:
        """Send monotonic progress and return ownership status.

        Returns True only when the heartbeat call succeeded AND renewed the
        lease.  Returns False when the heartbeat returned False (lease lost)
        OR when the heartbeat call itself raised an exception (ownership
        could not be proven).  In both cases the caller must fail closed:
        stop execution and perform no later business write or finalization.

        A heartbeat exception means ownership could not be proven.  The old
        owner must never convert an unknown lease state into success.
        """
        if total_chunks <= 0:
            return True
        try:
            message = f"triage chunk {completed}/{total_chunks}"
            if deterministic_candidate_count:
                ai_completed = max(0, completed - (total_chunks - ai_chunk_total))
                message = (
                    f"已确定性处理{deterministic_candidate_count}项；"
                    f"AI分诊批次 {ai_completed}/{ai_chunk_total}"
                )
            return heartbeat(
                DurableJobProgressPayload(
                    phase="running",
                    percent=min(
                        1.0, completed / max(1, total_chunks)
                    ),
                    step=completed,
                    step_total=total_chunks,
                    message=message,
                )
            )
        except Exception:
            return False  # P0 v3: fail closed on unprovable ownership


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class CompetitorTriageService:
    """Product-owned batch competitor relevance triage service."""

    def __init__(
        self,
        repository: WritingReferenceRepository,
        journey_service: Any,
        durable_store: Any = None,
        durable_worker: Any = None,
        provider_factory: Optional[Callable[[], Any]] = None,
        runtime_settings_store: Any = None,
        profile_provider_factory: Optional[Callable[[Any], Any]] = None,
        active_profile_resolver: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.repository = repository
        self.journey_service = journey_service
        self._durable_store = durable_store
        self._durable_worker = durable_worker
        # Retained for inline/legacy call compatibility. Versioned durable jobs
        # do not use this dynamic factory; they resolve their frozen profile.
        self._provider_factory: Optional[Callable[[], Any]] = provider_factory
        if runtime_settings_store is None:
            from .ai_runtime_settings import runtime_ai_settings_store

            runtime_settings_store = runtime_ai_settings_store()
        self._runtime_settings_store = runtime_settings_store
        self._profile_provider_factory = profile_provider_factory
        self._active_profile_resolver = active_profile_resolver
        self._test_provider_overrides: Dict[str, Any] = {}
        self._test_override_lock = threading.Lock()
        if durable_worker is not None:
            try:
                executor = CompetitorTriageExecutor(self)
                durable_worker.register_executor(executor)
            except Exception:
                pass  # executor already registered or worker unavailable

    # ------------------------------------------------------------------
    # Create run
    # ------------------------------------------------------------------

    def create_run(
        self,
        project_id: str,
        request: CompetitorTriageCreateRequest,
        provider: Any,
    ) -> Any:
        """Create a triage run.

        **Durable mode** (``durable_store`` provided): persists the run and
        chunks as today, then creates or reuses a ``competitor_triage`` durable
        job and returns a :class:`TriageDurableStartResult` with ``run_id`` +
        ``job_id`` **without** calling ``_execute_run``.  The long AI work runs
        only in the registered durable executor.

        **Legacy mode** (no ``durable_store``): executes inline and returns a
        full :class:`CompetitorTriageRunResponse` (backward compatibility for
        existing tests that do not supply a durable store).
        """
        journey = self.journey_service.get(project_id)
        if journey.revision != request.expected_journey_revision:
            raise CompetitorTriageConflictError(
                f"stale journey revision: expected "
                f"{request.expected_journey_revision}, current {journey.revision}"
            )
        requested_snapshot_id = str(request.snapshot_id or "").strip()
        if not requested_snapshot_id:
            requested_snapshot_id = str(
                (journey.search_plan.latest_snapshot_id if journey.search_plan else "")
                or ""
            ).strip()
            # Mutate request so downstream hashes/logs see the resolved id.
            try:
                request.snapshot_id = requested_snapshot_id
            except Exception:
                pass
        if (
            journey.search_plan is None
            or journey.search_plan.latest_snapshot_id != requested_snapshot_id
            or not requested_snapshot_id
        ):
            next_hint = (
                "请先在语料门点击「执行检索」锁定公开检索快照，"
                "再发起分诊（也可省略 snapshot_id，系统将自动使用已绑定快照）。"
            )
            if journey.search_plan is None:
                next_hint = (
                    "当前尚无检索计划：请先完成研究框架最小事实以生成 "
                    "search_plan，再执行公开检索。"
                )
            elif not journey.search_plan.latest_snapshot_id:
                next_hint = (
                    "检索计划已存在但尚未锁定快照：请先 POST "
                    "authoring-journey/competitor-search 执行公开检索。"
                )
            elif requested_snapshot_id and (
                requested_snapshot_id != journey.search_plan.latest_snapshot_id
            ):
                next_hint = (
                    "请使用当前绑定快照 "
                    f"{journey.search_plan.latest_snapshot_id}，"
                    f"而不是 {requested_snapshot_id}；"
                    "或省略 snapshot_id 以自动绑定。"
                )
            raise CompetitorTriageError(
                "snapshot must be the immutable snapshot bound to the journey；"
                f"{next_hint}"
            )
        snapshot = self.repository.search_snapshot(project_id, requested_snapshot_id)
        if not snapshot.candidates:
            raise CompetitorTriageError("snapshot has no candidates to triage")

        snap_hash = _snapshot_hash(snapshot)
        facts_hash = _material_facts_hash(journey)

        reduction_plan = _build_triage_reduction_plan(
            journey,
            snapshot,
            snap_hash,
            facts_hash,
        )
        chunk_records: List[CompetitorTriageChunkRecord] = list(
            reduction_plan.deterministic_chunks
        )
        canonical_input_parts: List[Dict[str, Any]] = []
        for chunk in chunk_records:
            canonical_input_parts.append(
                {
                    "chunk_index": chunk.chunk_index,
                    "kind": "deterministic",
                    "input_hash": chunk.input_hash,
                }
            )
        ai_chunk_start_index = len(chunk_records)
        for offset, chunk in enumerate(reduction_plan.ai_candidate_chunks):
            idx = ai_chunk_start_index + offset
            chunk_input = _build_chunk_input(journey, chunk, idx)
            input_hash = _hash_value(chunk_input)
            canonical_input_parts.append(
                {
                    "chunk_index": idx,
                    "kind": "independent_ai",
                    "input_hash": input_hash,
                }
            )
            chunk_records.append(
                CompetitorTriageChunkRecord(
                    chunk_id=f"ct_chunk_{input_hash[:20]}",
                    chunk_index=idx,
                    nct_ids=[c.nct_id for c in chunk],
                    input_hash=input_hash,
                )
            )

        canonical_input_hash = _hash_value(
            {
                "snapshot_id": snapshot.snapshot_id,
                "snapshot_hash": snap_hash,
                "material_facts_hash": facts_hash,
                "prompt_version": TRIAGE_PROMPT_VERSION,
                "schema_version": TRIAGE_SCHEMA_VERSION,
                "deterministic_policy_version": TRIAGE_DETERMINISTIC_POLICY_VERSION,
                "deterministic_disposition_counts": reduction_plan.disposition_counts,
                "chunks": canonical_input_parts,
            }
        )

        now = _utc_now()
        run_id = f"ct_run_{canonical_input_hash[:20]}"
        existing_run = self.repository.triage_run(project_id, run_id)
        if existing_run is not None:
            # Deterministic re-entry (e.g. a parent durable-job retry
            # replaying execute_stages with unchanged inputs regenerates the
            # same run_id). Overwriting would erase chunk progress the
            # durable executor already committed and strand the run at its
            # initial state forever, because the terminal durable job is
            # reused by business_key and never re-executes.
            run = existing_run
        else:
            run = CompetitorTriageRun(
                run_id=run_id,
                project_id=project_id,
                journey_id=journey.journey_id,
                snapshot_id=snapshot.snapshot_id,
                status=CompetitorTriageRunStatus.QUEUED,
                prompt_version=TRIAGE_PROMPT_VERSION,
                schema_version=TRIAGE_SCHEMA_VERSION,
                canonical_input_hash=canonical_input_hash,
                snapshot_hash=snap_hash,
                journey_revision=journey.revision,
                material_facts_hash=facts_hash,
                chunks=chunk_records,
                created_at=now,
                updated_at=now,
            )
        frozen_route = None
        frozen_fallback_routes: List[FrozenTriageAiRoute] = []
        if self._durable_store is not None:
            frozen_route = self._freeze_route_for_creation(provider)
            frozen_fallback_routes = self._freeze_fallback_routes_for_creation(
                frozen_route
            )
        if existing_run is None:
            self.repository.store_triage_run(run)

        # --- Durable path: return immediately with job_id ---
        if self._durable_store is not None:
            assert frozen_route is not None
            if frozen_route.source == "test_override":
                self._set_test_provider_override(project_id, run.run_id, provider)

            business_key = f"{snapshot.snapshot_id}:{run.run_id}"
            request_hash = self._durable_request_hash(
                canonical_input_hash, frozen_route, frozen_fallback_routes
            )
            payload_json = self._durable_payload(
                run.run_id, frozen_route, frozen_fallback_routes
            )
            durable_request = DurableJobCreateRequest(
                project_id=project_id,
                job_type=TRIAGE_DURABLE_JOB_TYPE,
                business_key=business_key,
                request_hash=request_hash,
                input_hash=canonical_input_hash[:64],
                payload_json=payload_json,
                created_by="triage_service",
                max_attempts=3,
                provider=frozen_route.provider,
                model=frozen_route.model,
            )
            start_resp = self._create_or_reuse_durable_job(durable_request)
            # Wake the durable worker if available
            if self._durable_worker is not None:
                try:
                    self._durable_worker.wake(project_id, start_resp.job_id)
                except Exception:
                    pass
            return TriageDurableStartResult(
                run_id=run.run_id,
                project_id=project_id,
                job_id=start_resp.job_id,
                reused=start_resp.reused,
            )

        # --- Legacy path: inline execution ---
        return self._execute_run(project_id, run, provider, snapshot, journey)

    def _freeze_route_for_creation(self, provider: Any) -> FrozenTriageAiRoute:
        test_only = bool(
            getattr(provider, "test_only_injection", False)
            or getattr(provider, "_test_only_injection", False)
        )
        if test_only:
            route = FrozenTriageAiRoute(
                profile_id=(
                    "test_override:"
                    f"{getattr(provider, 'provider_name', TRIAGE_PROVIDER_NAME)}:"
                    f"{getattr(provider, 'model_name', TRIAGE_MODEL_NAME)}"
                ),
                profile_revision=1,
                provider=getattr(
                    provider, "provider_name", TRIAGE_PROVIDER_NAME
                ),
                model=getattr(provider, "model_name", TRIAGE_MODEL_NAME),
                base_url=(
                    str(getattr(provider, "base_url", "")).rstrip("/")
                    or "test://injected-provider"
                ),
                transport=(
                    getattr(provider, "transport_name", "")
                    or TRIAGE_TRANSPORT_NAME
                ),
                expected_response_model=(
                    getattr(provider, "expected_response_model", "")
                    or getattr(provider, "model_name", TRIAGE_MODEL_NAME)
                ),
                deployment_profile="test",
                source="test_override",
                thinking=str(
                    getattr(provider, "default_thinking", "") or ""
                ).strip().lower(),
                reasoning_effort=str(
                    getattr(provider, "default_reasoning_effort", "") or ""
                ).strip().lower(),
            ).with_hash()
            return route

        profile = (
            self._active_profile_resolver()
            if self._active_profile_resolver is not None
            else self._runtime_settings_store.active_profile()
        )
        if profile is None or not profile.enabled:
            raise CompetitorTriageError(
                "active independent-AI profile is unavailable at durable job creation"
            )
        route = self._route_from_profile(profile)
        self._assert_provider_matches_route(provider, route)
        return route

    def _freeze_fallback_routes_for_creation(
        self,
        primary: FrozenTriageAiRoute,
    ) -> List[FrozenTriageAiRoute]:
        if primary.source == "test_override":
            return []
        routes: List[FrozenTriageAiRoute] = []
        seen = {primary.profile_id}
        for fallback in self._runtime_settings_store.fallback_chain():
            if fallback.profile_id in seen:
                continue
            seen.add(fallback.profile_id)
            try:
                profile = self._runtime_settings_store.profile(
                    fallback.profile_id
                )
            except KeyError:
                continue
            if not profile.enabled:
                continue
            effective = replace(
                profile,
                thinking=fallback.thinking,
                reasoning_effort=fallback.reasoning_effort,
            )
            routes.append(self._route_from_profile(effective))
        return routes

    @staticmethod
    def _route_from_profile(
        profile: Any,
        *,
        schema_version: str = TRIAGE_ROUTE_SNAPSHOT_VERSION,
    ) -> FrozenTriageAiRoute:
        return FrozenTriageAiRoute(
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
            source="runtime_profile",
            thinking=str(getattr(profile, "thinking", "") or "").strip().lower(),
            reasoning_effort=str(
                getattr(profile, "reasoning_effort", "") or ""
            ).strip().lower(),
            schema_version=schema_version,
        ).with_hash()

    @staticmethod
    def _assert_provider_matches_route(
        provider: Any, route: FrozenTriageAiRoute
    ) -> None:
        provider_name = str(getattr(provider, "provider_name", ""))
        model_name = str(getattr(provider, "model_name", ""))
        base_url = str(getattr(provider, "base_url", "")).rstrip("/")
        if route.source == "test_override" and not base_url:
            base_url = "test://injected-provider"
        transport = str(
            getattr(provider, "transport_name", "")
            or (
                TRIAGE_TRANSPORT_NAME
                if base_url or route.source == "test_override"
                else ""
            )
        )
        expected_response_model = str(
            getattr(provider, "expected_response_model", "") or model_name
        )
        thinking = str(
            getattr(provider, "default_thinking", route.thinking) or ""
        ).strip().lower()
        reasoning_effort = str(
            getattr(
                provider,
                "default_reasoning_effort",
                route.reasoning_effort,
            )
            or ""
        ).strip().lower()
        if (
            provider_name != route.provider
            or model_name != route.model
            or base_url != route.base_url
            or transport != route.transport
            or expected_response_model != route.expected_response_model
            or (
                route.schema_version == TRIAGE_ROUTE_SNAPSHOT_VERSION
                and (
                    thinking != route.thinking
                    or reasoning_effort != route.reasoning_effort
                )
            )
        ):
            raise CompetitorTriageError(
                "resolved provider identity does not match the frozen durable route: "
                f"resolved=(provider={provider_name!r}, model={model_name!r}, "
                f"base_url={base_url!r}, transport={transport!r}, "
                f"expected={expected_response_model!r}, thinking={thinking!r}, "
                f"reasoning_effort={reasoning_effort!r}) "
                f"frozen=(provider={route.provider!r}, model={route.model!r}, "
                f"base_url={route.base_url!r}, transport={getattr(route, 'transport', '')!r}, "
                f"expected={route.expected_response_model!r}, thinking={route.thinking!r}, "
                f"reasoning_effort={route.reasoning_effort!r})"
            )

    @staticmethod
    def _durable_payload(
        run_id: str,
        route: FrozenTriageAiRoute,
        fallback_routes: List[FrozenTriageAiRoute] | None = None,
    ) -> str:
        return json.dumps(
            {
                "run_id": run_id,
                "ai_route": route.audit_payload(),
                "ai_route_chain": {
                    "schema_version": TRIAGE_ROUTE_CHAIN_VERSION,
                    "fallback_routes": [
                        item.audit_payload()
                        for item in (fallback_routes or [])
                    ],
                },
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _durable_request_hash(
        canonical_input_hash: str,
        route: FrozenTriageAiRoute,
        fallback_routes: List[FrozenTriageAiRoute] | None = None,
        *,
        idempotency_key: str = "",
    ) -> str:
        return sha256(
            _canonical_json(
                {
                    "canonical_input_hash": canonical_input_hash,
                    "ai_route_identity_hash": route.identity_hash,
                    "fallback_route_identity_hashes": [
                        item.identity_hash for item in (fallback_routes or [])
                    ],
                    "idempotency_key": idempotency_key,
                }
            ).encode("utf-8")
        ).hexdigest()

    def _create_or_reuse_durable_job(
        self,
        request: DurableJobCreateRequest,
    ) -> Any:
        try:
            return self._durable_store.create_or_reuse(request)
        except DurableJobRequestConflict as exc:
            raise CompetitorTriageConflictError(str(exc)) from exc

    def _build_provider_for_durable_run(
        self,
        project_id: str,
        run_id: str,
        route: Optional[FrozenTriageAiRoute] = None,
    ) -> Any:
        """Resolve only the route frozen in the durable payload."""
        if route is None:
            key = f"{project_id}:{run_id}"
            with self._test_override_lock:
                provider = self._test_provider_overrides.get(key)
            if provider is not None and bool(
                getattr(provider, "test_only_injection", False)
                or getattr(provider, "_test_only_injection", False)
            ):
                return provider
            raise CompetitorTriageError(
                "frozen durable AI route is required for provider resolution"
            )
        if route.source == "test_override":
            key = f"{project_id}:{run_id}"
            with self._test_override_lock:
                provider = self._test_provider_overrides.get(key)
            if provider is None:
                raise CompetitorTriageError(
                    "test durable route override is unavailable after restart"
                )
            self._assert_provider_matches_route(provider, route)
            return provider

        try:
            profile = self._runtime_settings_store.profile(route.profile_id)
        except KeyError as exc:
            raise CompetitorTriageError(
                f"frozen independent-AI profile was deleted: {route.profile_id}"
            ) from exc
        if int(profile.revision) != route.profile_revision:
            raise CompetitorTriageError(
                "frozen independent-AI profile revision changed "
                f"(expected {route.profile_revision}, current {profile.revision})"
            )
        effective_profile = replace(
            profile,
            thinking=route.thinking or profile.thinking,
            reasoning_effort=(
                route.reasoning_effort or profile.reasoning_effort
            ),
        )
        current_route = self._route_from_profile(
            effective_profile,
            schema_version=route.schema_version,
        )
        if current_route.identity_hash != route.identity_hash:
            raise CompetitorTriageError(
                "frozen independent-AI profile identity changed"
            )

        if self._profile_provider_factory is not None:
            provider = self._profile_provider_factory(effective_profile)
        else:
            from .ai_gateway import configured_ai_provider_from_env

            base_env: Dict[str, str] = {}
            if profile.api_key_env and os.environ.get(profile.api_key_env):
                base_env[profile.api_key_env] = os.environ[profile.api_key_env]
            provider = configured_ai_provider_from_env(
                self._runtime_settings_store.profile_env(
                    effective_profile, base_env
                )
            )
        self._assert_provider_matches_route(provider, route)
        return provider

    def _set_test_provider_override(
        self, project_id: str, run_id: str, provider: Any
    ) -> None:
        """Set a project/run-scoped test-only provider override."""
        key = f"{project_id}:{run_id}"
        with self._test_override_lock:
            self._test_provider_overrides[key] = provider

    def _clear_test_provider_override(
        self, project_id: str, run_id: str
    ) -> None:
        """Clear a project/run-scoped test-only provider override."""
        key = f"{project_id}:{run_id}"
        with self._test_override_lock:
            self._test_provider_overrides.pop(key, None)

    def _finalize_run_status(
        self, run: CompetitorTriageRun
    ) -> CompetitorTriageRun:
        """Derive run status from chunk statuses and build recommended baskets.

        This is the pure status-derivation portion of ``_execute_run``, factored
        out so the durable executor can call it without re-executing chunks.
        """
        succeeded = [
            c for c in run.chunks
            if c.status == CompetitorTriageChunkStatus.SUCCEEDED
        ]
        failed = [
            c for c in run.chunks
            if c.status == CompetitorTriageChunkStatus.FAILED
        ]

        if failed and succeeded:
            run_status = CompetitorTriageRunStatus.PARTIAL_FAILED
        elif failed:
            run_status = CompetitorTriageRunStatus.FAILED
        else:
            run_status = CompetitorTriageRunStatus.REVIEW_READY

        run = run.model_copy(
            update={"status": run_status, "updated_at": _utc_now()}
        )

        retain: List[str] = []
        exclude: List[str] = []
        for chunk in succeeded:
            for result in chunk.results:
                if result.classification in (
                    CompetitorTriageClassification.DIRECT_COMPETITOR,
                    CompetitorTriageClassification.INDIRECT_REFERENCE,
                ):
                    retain.append(result.nct_id)
                else:
                    exclude.append(result.nct_id)

        # Deterministic registry dispositions are part of the audit trail but
        # are not the independent-AI route.  Prefer a real provider provenance
        # whenever at least one AI batch executed so run-level route fields do
        # not falsely claim ``not_applicable`` for a mixed run.
        ai_provenances = [
            chunk.provenance
            for chunk in succeeded
            if not chunk.chunk_id.startswith(_DETERMINISTIC_CHUNK_PREFIX)
            and chunk.provenance is not None
        ]
        first_prov = ai_provenances[0] if ai_provenances else None
        if first_prov is None:
            first_prov = next(
                (
                    chunk.provenance
                    for chunk in succeeded
                    if chunk.provenance is not None
                ),
                None,
            )
        update_fields: Dict[str, Any] = {
            "recommended_retain": sorted(retain),
            "recommended_exclude": sorted(exclude),
            "updated_at": _utc_now(),
        }
        if first_prov:
            route_identities = {
                (item.provider, item.response_model)
                for item in ai_provenances
            }
            if len(route_identities) > 1:
                update_fields["provider"] = "mixed"
                update_fields["response_model"] = "mixed"
                update_fields["canonical_output_hash"] = _hash_value(
                    [item.canonical_output_hash for item in ai_provenances]
                )
            else:
                update_fields["provider"] = first_prov.provider
                update_fields["response_model"] = first_prov.response_model
                update_fields["canonical_output_hash"] = first_prov.canonical_output_hash

        run = run.model_copy(update=update_fields)
        self.repository.store_triage_run(run)
        return run

    # ------------------------------------------------------------------
    # Execute / retry
    # ------------------------------------------------------------------

    def _execute_run(
        self,
        project_id: str,
        run: CompetitorTriageRun,
        provider: Any,
        snapshot: WritingReferenceSearchSnapshot,
        journey: MedicalWritingAuthoringJourney,
    ) -> CompetitorTriageRunResponse:
        verified = (
            provider
            if isinstance(provider, VerifiedTriageProvider)
            else VerifiedTriageProvider(
                provider,
                test_only_injection=bool(
                    getattr(provider, "test_only_injection", False)
                ),
            )
        )
        candidate_map = {c.nct_id: c for c in snapshot.candidates}
        updated_chunks: List[CompetitorTriageChunkRecord] = []

        for chunk in run.chunks:
            if chunk.status == CompetitorTriageChunkStatus.SUCCEEDED:
                updated_chunks.append(chunk)
                continue

            chunk_candidates = [
                candidate_map[nct] for nct in chunk.nct_ids if nct in candidate_map
            ]
            if not chunk_candidates:
                chunk = chunk.model_copy(
                    update={
                        "status": CompetitorTriageChunkStatus.FAILED,
                        "error_message": "no candidates found for chunk nct_ids",
                        "attempt": chunk.attempt + 1,
                    }
                )
                updated_chunks.append(chunk)
                continue

            chunk_input = _build_chunk_input(journey, chunk_candidates, chunk.chunk_index)
            input_hash = _hash_value(chunk_input)
            # Verify deterministic input hash matches what was recorded
            if input_hash != chunk.input_hash:
                chunk = chunk.model_copy(
                    update={
                        "status": CompetitorTriageChunkStatus.FAILED,
                        "error_message": "input hash drift detected",
                        "attempt": chunk.attempt + 1,
                    }
                )
                updated_chunks.append(chunk)
                continue

            updated_chunk = self._execute_chunk(
                verified, chunk, chunk_input, chunk.nct_ids
            )
            updated_chunks.append(updated_chunk)

        run = run.model_copy(update={"chunks": updated_chunks})

        # Inline and durable paths share finalization so deterministic chunks
        # cannot mask the independent-AI provider at run level.
        run = self._finalize_run_status(run)
        return CompetitorTriageRunResponse(
            run=run, summary=self._summarize(run)
        )

    def _execute_chunk(
        self,
        verified: Any,
        chunk: CompetitorTriageChunkRecord,
        chunk_input: Dict[str, Any],
        expected_nct_ids: List[str],
    ) -> CompetitorTriageChunkRecord:
        system_prompt = _build_system_prompt()
        def route_fields() -> Dict[str, Any]:
            return {
                "route_profile_id": str(
                    getattr(verified, "route_profile_id", "") or ""
                ),
                "route_identity_hash": str(
                    getattr(verified, "route_identity_hash", "") or ""
                ),
                "fallback_chain_id": str(
                    getattr(verified, "fallback_chain_id", "") or ""
                ),
                "fallback_depth": int(
                    getattr(verified, "fallback_depth", 0) or 0
                ),
                "fallback_reason": str(
                    getattr(verified, "fallback_reason", "") or ""
                ),
            }
        try:
            raw_response = verified.triage_run(system_prompt, chunk_input)
        except Exception as exc:
            logger.warning(
                "triage chunk %s provider call failed: %s", chunk.chunk_id, exc
            )
            return chunk.model_copy(
                update={
                    "status": CompetitorTriageChunkStatus.FAILED,
                    "error_message": f"provider error: {type(exc).__name__}: {exc}",
                    "attempt": chunk.attempt + 1,
                }
            )

        output_material: Dict[str, Any] = {"initial_response": raw_response}
        try:
            results = _validate_chunk_response(
                raw_response, expected_nct_ids, chunk_input=chunk_input
            )
        except CompetitorTriageError as exc:
            present_nct_ids = _repairable_present_nct_ids(
                raw_response, expected_nct_ids
            )
            missing_nct_ids = [
                nct_id
                for nct_id in expected_nct_ids
                if present_nct_ids is not None and nct_id not in present_nct_ids
            ]
            if present_nct_ids is None or not missing_nct_ids:
                return chunk.model_copy(
                    update={
                        "status": CompetitorTriageChunkStatus.FAILED,
                        "error_message": str(exc),
                        "attempt": chunk.attempt + 1,
                        "provenance": CompetitorTriageProvenance(
                            provider=verified.provider_name,
                            response_model=verified.response_model,
                            prompt_version=TRIAGE_PROMPT_VERSION,
                            schema_version=TRIAGE_SCHEMA_VERSION,
                            canonical_input_hash=chunk.input_hash,
                            canonical_output_hash=_hash_value(raw_response),
                            snapshot_id="",
                            **route_fields(),
                            created_at=_utc_now(),
                        ),
                    }
                )

            try:
                present_results = _validate_chunk_response(
                    raw_response,
                    present_nct_ids,
                    chunk_input=chunk_input,
                )
                repair_input = _missing_only_chunk_input(
                    chunk_input, missing_nct_ids
                )
                repair_response = verified.triage_run(
                    system_prompt, repair_input
                )
                output_material["repair_response"] = repair_response
                output_material["repair_missing_nct_ids"] = missing_nct_ids
                repaired_results = _validate_chunk_response(
                    repair_response,
                    missing_nct_ids,
                    chunk_input=repair_input,
                )
                by_nct_id = {
                    item.nct_id: item
                    for item in [*present_results, *repaired_results]
                }
                results = [by_nct_id[nct_id] for nct_id in expected_nct_ids]
            except Exception as repair_exc:
                output_material.setdefault(
                    "repair_missing_nct_ids", missing_nct_ids
                )
                return chunk.model_copy(
                    update={
                        "status": CompetitorTriageChunkStatus.FAILED,
                        "error_message": (
                            f"{exc}; bounded missing-ID repair failed: "
                            f"{type(repair_exc).__name__}: {repair_exc}"
                        ),
                        "attempt": chunk.attempt + 1,
                        "provenance": CompetitorTriageProvenance(
                            provider=verified.provider_name,
                            response_model=verified.response_model,
                            prompt_version=TRIAGE_PROMPT_VERSION,
                            schema_version=TRIAGE_SCHEMA_VERSION,
                            canonical_input_hash=chunk.input_hash,
                            canonical_output_hash=_hash_value(output_material),
                            snapshot_id="",
                            **route_fields(),
                            created_at=_utc_now(),
                        ),
                    }
                )

        provenance = CompetitorTriageProvenance(
            provider=verified.provider_name,
            response_model=verified.response_model,
            prompt_version=TRIAGE_PROMPT_VERSION,
            schema_version=TRIAGE_SCHEMA_VERSION,
            canonical_input_hash=chunk.input_hash,
            canonical_output_hash=(
                _hash_value(output_material)
                if "repair_response" in output_material
                else _hash_value(raw_response)
            ),
            snapshot_id="",
            **route_fields(),
            created_at=_utc_now(),
        )

        return chunk.model_copy(
            update={
                "status": CompetitorTriageChunkStatus.SUCCEEDED,
                "attempt": chunk.attempt + 1,
                "provenance": provenance,
                "results": results,
            }
        )

    def retry_run(
        self,
        project_id: str,
        run_id: str,
        request: CompetitorTriageRetryRequest,
        provider: Any,
    ) -> Any:
        """Retry a triage run.

        **Durable mode**: resets failed chunks, stores the run, then retries
        or creates a retry durable job and wakes the worker. Returns a
        :class:`TriageDurableStartResult` immediately.

        **Legacy mode**: executes inline and returns a full response.
        """
        run = self.repository.triage_run(project_id, run_id)
        if run is None:
            raise KeyError(run_id)

        # Check stale before retry
        self._check_stale(project_id, run)

        snapshot = self.repository.search_snapshot(project_id, run.snapshot_id)
        journey = self.journey_service.get(project_id)

        # --- Durable path ---
        if self._durable_store is not None:
            business_key = f"{snapshot.snapshot_id}:{run.run_id}"

            # Look up the existing durable job for this triage run.
            existing_job = None
            try:
                existing_job = self._durable_store.get_by_business_key(
                    project_id,
                    TRIAGE_DURABLE_JOB_TYPE,
                    business_key,
                )
            except Exception:
                pass

            # Defect 5 fix: If the existing job is in a terminal state
            # (completed/failed/cancelled), we cannot just call retry() on
            # it — for 'completed' that is a no-op.  We need to create a NEW
            # retry job keyed by idempotency_key + frozen failed-chunk set so
            # duplicate retries are deduplicated and the business run is not
            # mutated to RUNNING until the durable transition succeeds.
            job_id: Optional[str] = None

            if existing_job is not None and existing_job.status == "running":
                # Live-running retry must be rejected with an explicit
                # conflict — cannot retry a job that is currently executing.
                # Do NOT mutate business state (P0 follow-up).
                raise CompetitorTriageConflictError(
                    f"triage run {run_id} has a durable job "
                    f"{existing_job.job_id} that is currently running; "
                    f"cannot retry until it reaches a terminal state"
                )

            if existing_job is not None and existing_job.status in (
                "retry_wait",
                "queued",
            ):
                try:
                    existing_payload = json.loads(
                        existing_job.payload_json or "{}"
                    )
                    FrozenTriageAiRoute.parse(existing_payload.get("ai_route"))
                except (json.JSONDecodeError, CompetitorTriageError) as exc:
                    raise CompetitorTriageConflictError(
                        TRIAGE_LEGACY_ROUTE_ERROR
                    ) from exc
                # Non-terminal, non-running: reuse core retry.
                retry_result = self._durable_store.retry(
                    project_id, existing_job.job_id
                )
                if not retry_result.requeued:
                    # Retry was rejected (shouldn't happen for retry_wait/
                    # queued, but handle defensively).
                    pass
                job_id = existing_job.job_id
            elif existing_job is not None and existing_job.status in (
                "completed",
                "failed",
                "cancelled",
            ):
                # Terminal state: create a new retry job keyed by
                # idempotency_key + frozen failed-chunk set.
                incomplete_chunk_ids = sorted(
                    ch.chunk_id
                    for ch in run.chunks
                    if ch.status != CompetitorTriageChunkStatus.SUCCEEDED
                )
                retry_business_key = _triage_retry_business_key(
                    business_key,
                    request.idempotency_key,
                    incomplete_chunk_ids,
                )
                frozen_route = self._freeze_route_for_creation(provider)
                frozen_fallback_routes = self._freeze_fallback_routes_for_creation(
                    frozen_route
                )
                if frozen_route.source == "test_override":
                    self._set_test_provider_override(
                        project_id, run.run_id, provider
                    )
                retry_request_hash = self._durable_request_hash(
                    run.canonical_input_hash,
                    frozen_route,
                    frozen_fallback_routes,
                    idempotency_key=request.idempotency_key,
                )
                payload_json = self._durable_payload(
                    run.run_id, frozen_route, frozen_fallback_routes
                )
                durable_request = DurableJobCreateRequest(
                    project_id=project_id,
                    job_type=TRIAGE_DURABLE_JOB_TYPE,
                    business_key=retry_business_key,
                    request_hash=retry_request_hash,
                    input_hash=run.canonical_input_hash[:64],
                    payload_json=payload_json,
                    created_by="triage_service",
                    max_attempts=3,
                    provider=frozen_route.provider,
                    model=frozen_route.model,
                )
                start_resp = self._create_or_reuse_durable_job(durable_request)
                # If reused (idempotent duplicate), don't mutate the run.
                if not start_resp.reused:
                    # New retry job — mutate the business run to reset
                    # failed chunks and set RUNNING.
                    run = self._reset_failed_chunks_for_retry(
                        run, request
                    )
                job_id = start_resp.job_id
            else:
                # No existing job — create a new one.
                frozen_route = self._freeze_route_for_creation(provider)
                frozen_fallback_routes = self._freeze_fallback_routes_for_creation(
                    frozen_route
                )
                if frozen_route.source == "test_override":
                    self._set_test_provider_override(
                        project_id, run.run_id, provider
                    )
                request_hash = self._durable_request_hash(
                    run.canonical_input_hash,
                    frozen_route,
                    frozen_fallback_routes,
                )
                payload_json = self._durable_payload(
                    run.run_id, frozen_route, frozen_fallback_routes
                )
                durable_request = DurableJobCreateRequest(
                    project_id=project_id,
                    job_type=TRIAGE_DURABLE_JOB_TYPE,
                    business_key=business_key,
                    request_hash=request_hash,
                    input_hash=run.canonical_input_hash[:64],
                    payload_json=payload_json,
                    created_by="triage_service",
                    max_attempts=3,
                    provider=frozen_route.provider,
                    model=frozen_route.model,
                )
                start_resp = self._create_or_reuse_durable_job(durable_request)
                job_id = start_resp.job_id

            # Defect 5 fix: perform durable transition BEFORE mutating the
            # business run.  The _reset_failed_chunks_for_retry was already
            # called above only for the new-retry-job case.  For the
            # non-terminal case, the business run was not yet mutated —
            # do it now only if job_id is secured.
            if existing_job is not None and existing_job.status in (
                "retry_wait",
                "queued",
            ):
                run = self._reset_failed_chunks_for_retry(run, request)

            # Wake the durable worker
            if self._durable_worker is not None and job_id is not None:
                try:
                    self._durable_worker.wake(project_id, job_id)
                except Exception:
                    pass
            return TriageDurableStartResult(
                run_id=run.run_id,
                project_id=project_id,
                job_id=job_id or "",
                reused=existing_job is not None,
            )

        # --- Legacy path: inline execution ---
        chunk_filter = set(request.chunk_ids) if request.chunk_ids else None

        # Reset only failed chunks (or specified chunks) to pending
        updated_chunks: List[CompetitorTriageChunkRecord] = []
        for chunk in run.chunks:
            should_retry = chunk.status == CompetitorTriageChunkStatus.FAILED
            if chunk_filter:
                should_retry = should_retry and chunk.chunk_id in chunk_filter
            if should_retry:
                updated_chunks.append(
                    chunk.model_copy(
                        update={
                            "status": CompetitorTriageChunkStatus.PENDING,
                            "error_message": "",
                        }
                    )
                )
            else:
                updated_chunks.append(chunk)

        run = run.model_copy(
            update={
                "chunks": updated_chunks,
                "status": CompetitorTriageRunStatus.RUNNING,
                "updated_at": _utc_now(),
            }
        )
        self.repository.store_triage_run(run)
        return self._execute_run(project_id, run, provider, snapshot, journey)

    def _reset_failed_chunks_for_retry(
        self,
        run: CompetitorTriageRun,
        request: CompetitorTriageRetryRequest,
    ) -> CompetitorTriageRun:
        """Reset selected incomplete chunks to pending and set RUNNING.

        Successful chunks are immutable across recovery. Without an explicit
        filter, both pending and failed chunks are eligible so a parent
        pipeline timeout can resume a never-claimed tail without replaying
        completed provider work. Called only after the durable transition has
        succeeded.
        """
        chunk_filter = set(request.chunk_ids) if request.chunk_ids else None
        updated_chunks: List[CompetitorTriageChunkRecord] = []
        for chunk in run.chunks:
            should_retry = chunk.status != CompetitorTriageChunkStatus.SUCCEEDED
            if chunk_filter:
                should_retry = should_retry and chunk.chunk_id in chunk_filter
            if should_retry:
                updated_chunks.append(
                    chunk.model_copy(
                        update={
                            "status": CompetitorTriageChunkStatus.PENDING,
                            "error_message": "",
                        }
                    )
                )
            else:
                updated_chunks.append(chunk)
        run = run.model_copy(
            update={
                "chunks": updated_chunks,
                "status": CompetitorTriageRunStatus.RUNNING,
                "updated_at": _utc_now(),
            }
        )
        self.repository.store_triage_run(run)
        return run

    # ------------------------------------------------------------------
    # Get
    # ------------------------------------------------------------------

    def get_run(
        self, project_id: str, run_id: str
    ) -> CompetitorTriageRunResponse:
        run = self.repository.triage_run(project_id, run_id)
        if run is None:
            raise KeyError(run_id)
        # Re-check stale on read
        run = self._check_and_mark_stale(project_id, run)
        return CompetitorTriageRunResponse(
            run=run,
            summary=self._summarize(run),
            reconfirmation=self._reconfirmation_status(project_id, run),
        )

    # ------------------------------------------------------------------
    # Stale detection
    # ------------------------------------------------------------------

    def _check_stale(
        self, project_id: str, run: CompetitorTriageRun
    ) -> None:
        """Raise if the run is stale relative to current snapshot/journey/facts."""
        reason = self._stale_reason(project_id, run)
        if reason:
            raise CompetitorTriageStaleError(reason)

    def _stale_reason(self, project_id: str, run: CompetitorTriageRun) -> str:
        if run.prompt_version != TRIAGE_PROMPT_VERSION:
            return (
                "competitor triage prompt version changed: "
                f"run={run.prompt_version}, current={TRIAGE_PROMPT_VERSION}"
            )
        if run.schema_version != TRIAGE_SCHEMA_VERSION:
            return (
                "competitor triage schema version changed: "
                f"run={run.schema_version}, current={TRIAGE_SCHEMA_VERSION}"
            )

        try:
            snapshot = self.repository.search_snapshot(project_id, run.snapshot_id)
        except KeyError:
            return f"snapshot {run.snapshot_id} no longer exists"

        current_snap_hash = _snapshot_hash(snapshot)
        if current_snap_hash != run.snapshot_hash:
            return "snapshot content has changed since the run was created"

        try:
            journey = self.journey_service.get(project_id)
        except KeyError:
            return "authoring journey no longer exists"

        # Authoring revision is a CAS/version for the whole journey, not every
        # revision-bearing field a triage run consumes.  A safe derived
        # identity adoption (for example, a document title built solely from
        # the immutable product/indication/phase facts) legitimately advances
        # the journey revision after this frozen search/triage run was created.
        # Compare material facts at the run's revision so such revision-only
        # changes do not invalidate an otherwise identical triage run.  Any
        # change to the relevance-driving fields below still changes the hash
        # and remains fail-closed.
        comparable_journey = journey
        if journey.revision != run.journey_revision:
            try:
                comparable_journey = journey.model_copy(
                    update={"revision": run.journey_revision}
                )
            except (AttributeError, TypeError, ValueError):
                comparable_journey = journey

        current_facts_hash = _material_facts_hash(comparable_journey)
        if current_facts_hash != run.material_facts_hash:
            return "project material facts have changed since the run was created"

        return ""

    def _check_and_mark_stale(
        self, project_id: str, run: CompetitorTriageRun
    ) -> CompetitorTriageRun:
        """Check staleness and persist stale status if detected."""
        if run.status in (
            CompetitorTriageRunStatus.CONFIRMED,
            CompetitorTriageRunStatus.PROJECTION_PENDING,
        ):
            return run
        reason = self._stale_reason(project_id, run)
        if reason and run.status != CompetitorTriageRunStatus.STALE:
            run = run.model_copy(
                update={
                    "status": CompetitorTriageRunStatus.STALE,
                    "stale_reason": reason,
                    "updated_at": _utc_now(),
                }
            )
            self.repository.store_triage_run(run)
        return run

    def _reconfirmation_status(
        self, project_id: str, run: CompetitorTriageRun
    ) -> CompetitorTriageReconfirmationStatus:
        confirmation = self.repository.triage_confirmation_for_run(
            project_id, run.run_id
        )
        if confirmation is None:
            return CompetitorTriageReconfirmationStatus()
        try:
            journey = self.journey_service.get(project_id)
        except KeyError:
            return CompetitorTriageReconfirmationStatus()
        comparison_revision = (
            confirmation.journey_revision
            if confirmation.confirmation_kind == "human_reconfirmation"
            else run.journey_revision
        )
        comparable_journey = journey.model_copy(
            update={"revision": comparison_revision}
        )
        current_facts_hash = _material_facts_hash(comparable_journey)
        confirmed_facts_hash = (
            confirmation.confirmed_material_facts_hash
            or run.material_facts_hash
        )
        required = (
            journey.search_plan is None
            or current_facts_hash != confirmed_facts_hash
        )
        return CompetitorTriageReconfirmationStatus(
            required=required,
            reason=(
                "当前研究信息已更新，请核对既有分类后确认；系统不会重复调用AI分诊。"
                if required
                else ""
            ),
            source_confirmation_id=confirmation.confirmation_id,
            snapshot_id=confirmation.snapshot_id,
            current_journey_revision=journey.revision,
            retained_nct_ids=confirmation.retained_nct_ids,
            excluded_nct_ids=confirmation.excluded_nct_ids,
            final_classifications=confirmation.final_classifications,
            current_triage_criteria=(
                journey.search_plan.triage_criteria
                if journey.search_plan is not None
                else []
            ),
        )

    def _confirmation_stale_reason(
        self,
        project_id: str,
        run: CompetitorTriageRun,
        confirmation: CompetitorTriageConfirmationRecord,
    ) -> str:
        if confirmation.confirmation_kind != "human_reconfirmation":
            return self._stale_reason(project_id, run)
        try:
            snapshot = self.repository.search_snapshot(project_id, run.snapshot_id)
        except KeyError:
            return f"snapshot {run.snapshot_id} no longer exists"
        if _snapshot_hash(snapshot) != run.snapshot_hash:
            return "snapshot content has changed since the run was created"
        try:
            journey = self.journey_service.get(project_id)
        except KeyError:
            return "authoring journey no longer exists"
        comparable_journey = journey.model_copy(
            update={"revision": confirmation.journey_revision}
        )
        if (
            _material_facts_hash(comparable_journey)
            != confirmation.confirmed_material_facts_hash
        ):
            return "project material facts changed after the human re-review"
        return ""

    # ------------------------------------------------------------------
    # Basket confirm
    # ------------------------------------------------------------------

    def confirm_basket(
        self,
        project_id: str,
        run_id: str,
        request: CompetitorTriageBasketConfirmationRequest,
    ) -> CompetitorTriageConfirmationRecord:
        """Confirm the AI-recommended discovery basket.

        This is a single user decision action. It does NOT call AI. The
        medical manager's confirmation IS the medical decision; no second
        approval state is introduced.

        Requirements:
        - Run must be REVIEW_READY with every chunk SUCCEEDED (no PARTIAL_FAILED).
        - retained + excluded must form an exact, non-overlapping partition of
          ALL snapshot NCT IDs — complete coverage, no overlap, no duplicates,
          no unknown IDs.
        - Failed/untriaged candidates must never default to direct_competitor;
          each retained NCT must have a known classification from the run.
        """
        run = self.repository.triage_run(project_id, run_id)
        if run is None:
            raise KeyError(run_id)

        # The expected_run_revision is the run's canonical_input_hash
        # (stable identity)
        if run.canonical_input_hash != request.expected_run_revision:
            raise CompetitorTriageConflictError(
                "expected_run_revision does not match the run's canonical "
                "input hash"
            )

        snapshot = self.repository.search_snapshot(project_id, run.snapshot_id)
        candidate_ids = {c.nct_id for c in snapshot.candidates}
        final_classifications = {
            nct_id: (
                classification.value
                if isinstance(classification, CompetitorTriageClassification)
                else str(classification)
            )
            for nct_id, classification in request.final_classifications.items()
        }

        # Build confirmation hash from the request material. This is the
        # canonical idempotency identity: same request → same hash → same
        # confirmation_id.
        confirmation_material = {
            "run_id": run.run_id,
            "project_id": project_id,
            "snapshot_id": run.snapshot_id,
            "retained_nct_ids": sorted(request.retained_nct_ids),
            "excluded_nct_ids": sorted(request.excluded_nct_ids),
            "final_classifications": {
                nct_id: final_classifications[nct_id]
                for nct_id in sorted(final_classifications)
            },
            "no_suitable_competitor_reason": (
                request.no_suitable_competitor_reason.strip()
            ),
            "actor": request.actor,
            "reason": request.reason.strip(),
            "journey_revision": request.expected_journey_revision,
            "canonical_input_hash": run.canonical_input_hash,
        }
        confirmation_hash = _hash_value(confirmation_material)
        confirmation_id = f"ct_conf_{confirmation_hash[:20]}"
        idempotency_operation = "confirm_competitor_triage_basket"

        # Idempotency-key replay/conflict detection must precede the mutable
        # run-status guard. A confirmed run can replay the same request, while
        # reuse of the key with a different final classification must fail.
        try:
            with self.repository._connect() as connection:
                replay_id = self.repository.triage_idempotent_replay(
                    connection,
                    project_id,
                    idempotency_operation,
                    request.idempotency_key,
                    confirmation_hash,
                )
        except WritingReferenceConflictError as exc:
            raise CompetitorTriageConflictError(str(exc)) from exc
        if replay_id is not None:
            existing = self.repository.triage_confirmation(
                project_id, replay_id
            )
            if existing is None:
                raise CompetitorTriageConflictError(
                    "idempotent confirmation record is missing"
                )
            return existing

        # Preserve material-idempotent replay when a caller uses a fresh key
        # for the exact same request. Record the alias so that key is also
        # protected against later reuse with different classifications.
        existing = self.repository.triage_confirmation(project_id, confirmation_id)
        if existing is not None:
            try:
                with self.repository._connect() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    replay_id = self.repository.triage_idempotent_replay(
                        connection,
                        project_id,
                        idempotency_operation,
                        request.idempotency_key,
                        confirmation_hash,
                    )
                    if replay_id is None:
                        self.repository.triage_record_idempotency(
                            connection,
                            project_id,
                            idempotency_operation,
                            request.idempotency_key,
                            confirmation_hash,
                            confirmation_id,
                        )
                    connection.commit()
            except WritingReferenceConflictError as exc:
                raise CompetitorTriageConflictError(str(exc)) from exc
            return existing

        # Reject PARTIAL_FAILED — a one-click AI recommendation cannot be
        # authoritative while any chunk failed. Only reached for first-time
        # confirmations; idempotent replays return above.
        if run.status != CompetitorTriageRunStatus.REVIEW_READY:
            raise CompetitorTriageError(
                f"run must be fully REVIEW_READY to confirm "
                f"(every chunk succeeded); current status: {run.status.value}"
            )

        # Build classification map from SUCCEEDED chunks only
        classification_map: Dict[str, str] = {}
        for chunk in run.chunks:
            if chunk.status != CompetitorTriageChunkStatus.SUCCEEDED:
                continue
            for result in chunk.results:
                classification_map[result.nct_id] = result.classification.value

        # --- Exact partition validation ---
        retained_set = set(request.retained_nct_ids)
        excluded_set = set(request.excluded_nct_ids)

        # No duplicates within lists
        if len(request.retained_nct_ids) != len(retained_set):
            raise CompetitorTriageError(
                "retained_nct_ids contains duplicate entries"
            )
        if len(request.excluded_nct_ids) != len(excluded_set):
            raise CompetitorTriageError(
                "excluded_nct_ids contains duplicate entries"
            )

        # No overlap between retained and excluded
        overlap = sorted(retained_set & excluded_set)
        if overlap:
            raise CompetitorTriageError(
                "retained and excluded lists overlap: " + ", ".join(overlap)
            )

        # No unknown IDs
        all_selected = retained_set | excluded_set
        unknown = sorted(all_selected - candidate_ids)
        if unknown:
            raise CompetitorTriageError(
                f"confirmation references NCTs not in snapshot: "
                f"{', '.join(unknown)}"
            )

        # Complete coverage — every snapshot NCT must be in retained or excluded
        missing = sorted(candidate_ids - all_selected)
        if missing:
            raise CompetitorTriageError(
                "confirmation does not cover all snapshot NCTs; missing: "
                + ", ".join(missing)
            )

        final_ids = set(final_classifications)
        unknown_final = sorted(final_ids - candidate_ids)
        if unknown_final:
            raise CompetitorTriageError(
                "final_classifications references NCTs not in snapshot: "
                + ", ".join(unknown_final)
            )
        missing_final = sorted(candidate_ids - final_ids)
        if missing_final:
            raise CompetitorTriageError(
                "final_classifications must cover every snapshot NCT; missing: "
                + ", ".join(missing_final)
            )

        invalid_final = sorted(
            nct_id
            for nct_id, classification in final_classifications.items()
            if classification not in _ALLOWED_CLASSIFICATIONS
        )
        if invalid_final:
            raise CompetitorTriageError(
                "final_classifications contains invalid values for: "
                + ", ".join(invalid_final)
            )

        retained_from_final = {
            nct_id
            for nct_id, classification in final_classifications.items()
            if classification
            in {
                CompetitorTriageClassification.DIRECT_COMPETITOR.value,
                CompetitorTriageClassification.INDIRECT_REFERENCE.value,
            }
        }
        excluded_from_final = {
            nct_id
            for nct_id, classification in final_classifications.items()
            if classification == CompetitorTriageClassification.EXCLUDED.value
        }
        if retained_from_final != retained_set or excluded_from_final != excluded_set:
            inconsistent = sorted(
                (retained_from_final ^ retained_set)
                | (excluded_from_final ^ excluded_set)
            )
            raise CompetitorTriageError(
                "final_classifications conflicts with retained/excluded "
                "partition for: "
                + ", ".join(inconsistent)
            )

        # REVIEW_READY should already guarantee this, but confirmation remains
        # fail-closed if a persisted run is incomplete or corrupt.
        unclassified_candidates = sorted(candidate_ids - set(classification_map))
        if unclassified_candidates:
            raise CompetitorTriageError(
                "snapshot NCTs have no classification from the run: "
                + ", ".join(unclassified_candidates)
            )

        # Check stale — stale runs cannot be confirmed (only replayed)
        stale_reason = self._stale_reason(project_id, run)
        if stale_reason:
            raise CompetitorTriageStaleError(stale_reason)

        now = _utc_now()
        effective_reason = (
            request.reason.strip()
            if retained_set
            else request.no_suitable_competitor_reason.strip()
            or "医学经理确认本次候选均不适合作为竞品或间接参照。"
        )
        confirmation_journey = self.journey_service.get(project_id)
        confirmation = CompetitorTriageConfirmationRecord(
            confirmation_id=confirmation_id,
            run_id=run.run_id,
            project_id=project_id,
            snapshot_id=run.snapshot_id,
            retained_nct_ids=sorted(request.retained_nct_ids),
            excluded_nct_ids=sorted(request.excluded_nct_ids),
            final_classifications={
                nct_id: CompetitorTriageClassification(
                    final_classifications[nct_id]
                )
                for nct_id in sorted(final_classifications)
            },
            no_suitable_competitor_reason=(
                request.no_suitable_competitor_reason.strip()
            ),
            actor=request.actor,
            reason=effective_reason,
            confirmation_hash=confirmation_hash,
            journey_revision=request.expected_journey_revision,
            confirmation_kind="initial_ai_assisted",
            confirmed_material_facts_hash=run.material_facts_hash,
            confirmed_search_plan_id=(
                confirmation_journey.search_plan.plan_id
                if confirmation_journey.search_plan is not None
                else ""
            ),
            projection_status="pending",
            created_at=now,
        )

        # Step 1: Atomically persist confirmation, final decisions, run state,
        # and the idempotency identity in writing_reference.sqlite3.
        replay_id = self._atomic_confirm_and_decisions(
            project_id=project_id,
            run=run,
            confirmation=confirmation,
            request=request,
            classification_map=classification_map,
            idempotency_operation=idempotency_operation,
        )
        if replay_id is not None:
            replay = self.repository.triage_confirmation(project_id, replay_id)
            if replay is None:
                raise CompetitorTriageConflictError(
                    "idempotent confirmation record is missing"
                )
            return replay

        # The same transaction persisted this run payload and status.
        run = run.model_copy(
            update={
                "status": CompetitorTriageRunStatus.CONFIRMED,
                "updated_at": _utc_now(),
            }
        )

        # Step 2: Project discovery basket to authoring journey.
        # This is a separate, replayable write — NOT a cross-database
        # atomic transaction. If projection fails, the authoritative
        # confirmation remains intact; retry replays without second approval.
        confirmation = self._project_discovery_basket(
            project_id, run, confirmation, request
        )

        return confirmation

    def reconfirm_basket(
        self,
        project_id: str,
        run_id: str,
        request: CompetitorTriageBasketReconfirmationRequest,
    ) -> CompetitorTriageConfirmationRecord:
        """Create a new human confirmation against current medical facts.

        The immutable registry snapshot and old AI evidence are reused for
        review only. No provider, search, download, OCR, or translation call is
        made. The complete current user partition becomes a new confirmation
        identity with explicit lineage to the superseded confirmation.
        """
        run = self.repository.triage_run(project_id, run_id)
        if run is None:
            raise KeyError(run_id)
        source = self.repository.triage_confirmation(
            project_id, request.source_confirmation_id
        )
        if (
            source is None
            or source.run_id != run_id
            or source.snapshot_id != run.snapshot_id
        ):
            raise CompetitorTriageConflictError(
                "source confirmation does not belong to this triage run and snapshot"
            )
        current = self.journey_service.get(project_id)
        if current.search_plan is None:
            raise CompetitorTriageConflictError(
                "current competitor search plan is missing"
            )
        snapshot = self.repository.search_snapshot(project_id, run.snapshot_id)
        expected_search = self.journey_service.build_competitor_search_request(
            project_id,
            MedicalWritingCompetitorSearchExecuteRequest(
                search_plan_id=current.search_plan.plan_id,
                actor=request.actor,
                idempotency_key=f"{request.idempotency_key}:validate",
            ),
        ).search
        if snapshot.request != expected_search:
            raise CompetitorTriageConflictError(
                "the immutable snapshot no longer matches the current registry search contract"
            )
        candidate_ids = {candidate.nct_id for candidate in snapshot.candidates}
        retained = set(request.retained_nct_ids)
        excluded = set(request.excluded_nct_ids)
        classifications = {
            nct_id: (
                value.value
                if isinstance(value, CompetitorTriageClassification)
                else str(value)
            )
            for nct_id, value in request.final_classifications.items()
        }
        if (
            len(retained) != len(request.retained_nct_ids)
            or len(excluded) != len(request.excluded_nct_ids)
        ):
            raise CompetitorTriageError("reconfirmation contains duplicate candidate ids")
        if retained & excluded or retained | excluded != candidate_ids:
            raise CompetitorTriageError(
                "reconfirmation must classify every snapshot candidate exactly once"
            )
        if set(classifications) != candidate_ids:
            raise CompetitorTriageError(
                "final classifications must cover every snapshot candidate"
            )
        if any(
            value not in _ALLOWED_CLASSIFICATIONS
            for value in classifications.values()
        ):
            raise CompetitorTriageError("reconfirmation contains an invalid classification")
        classified_retained = {
            nct_id
            for nct_id, value in classifications.items()
            if value in {
                CompetitorTriageClassification.DIRECT_COMPETITOR.value,
                CompetitorTriageClassification.INDIRECT_REFERENCE.value,
            }
        }
        classified_excluded = {
            nct_id
            for nct_id, value in classifications.items()
            if value == CompetitorTriageClassification.EXCLUDED.value
        }
        if classified_retained != retained or classified_excluded != excluded:
            raise CompetitorTriageError(
                "final classifications conflict with the retained/excluded basket"
            )

        comparable_current = current.model_copy(
            update={"revision": request.expected_journey_revision}
        )
        current_facts_hash = _material_facts_hash(comparable_current)
        reason = request.reason.strip() or (
            "医学经理已按当前研究信息重新核对既有竞品篮子。"
        )
        material = {
            "run_id": run_id,
            "project_id": project_id,
            "snapshot_id": run.snapshot_id,
            "source_confirmation_id": source.confirmation_id,
            "current_material_facts_hash": current_facts_hash,
            "current_search_plan_id": current.search_plan.plan_id,
            "retained_nct_ids": sorted(retained),
            "excluded_nct_ids": sorted(excluded),
            "final_classifications": {
                nct_id: classifications[nct_id]
                for nct_id in sorted(classifications)
            },
            "reason": reason,
        }
        confirmation_hash = _hash_value(material)
        confirmation_id = f"ct_reconf_{confirmation_hash[:20]}"
        confirmation = CompetitorTriageConfirmationRecord(
            confirmation_id=confirmation_id,
            run_id=run_id,
            project_id=project_id,
            snapshot_id=run.snapshot_id,
            retained_nct_ids=sorted(retained),
            excluded_nct_ids=sorted(excluded),
            final_classifications={
                nct_id: CompetitorTriageClassification(classifications[nct_id])
                for nct_id in sorted(classifications)
            },
            no_suitable_competitor_reason=(
                request.no_suitable_competitor_reason.strip()
            ),
            actor=request.actor,
            reason=reason,
            confirmation_hash=confirmation_hash,
            journey_revision=request.expected_journey_revision,
            confirmation_kind="human_reconfirmation",
            source_confirmation_id=source.confirmation_id,
            confirmed_material_facts_hash=current_facts_hash,
            confirmed_search_plan_id=current.search_plan.plan_id,
            projection_status="pending",
            created_at=_utc_now(),
        )
        if current.revision != request.expected_journey_revision:
            with self.repository._connect() as connection:
                replay_id = self.repository.triage_idempotent_replay(
                    connection,
                    project_id,
                    "reconfirm_competitor_triage_basket",
                    request.idempotency_key,
                    confirmation.confirmation_hash,
                )
            if replay_id is not None:
                replay = self.repository.triage_confirmation(
                    project_id, replay_id
                )
                if replay is None:
                    raise CompetitorTriageConflictError(
                        "reconfirmed basket replay is missing"
                    )
                return replay
            raise CompetitorTriageConflictError(
                "stale authoring journey revision: "
                f"expected {request.expected_journey_revision}, "
                f"current {current.revision}"
            )
        replay = self._atomic_human_reconfirmation(
            project_id=project_id,
            run=run,
            confirmation=confirmation,
            request=request,
        )
        if replay is not None:
            return replay
        try:
            journey = self.journey_service.project_human_reconfirmed_basket(
                project_id,
                snapshot,
                confirmation_id=confirmation.confirmation_id,
                confirmation_hash=confirmation.confirmation_hash,
                source_confirmation_id=source.confirmation_id,
                run_id=run.run_id,
                retained_nct_ids=confirmation.retained_nct_ids,
                excluded_nct_ids=confirmation.excluded_nct_ids,
                expected_revision=current.revision,
                actor=request.actor,
                reason=confirmation.reason,
                idempotency_key=f"triage_reconfirm_project_{confirmation.confirmation_id}",
            )
            confirmation = confirmation.model_copy(
                update={"projection_status": "discovery_projected"}
            )
            if journey.picos_complete:
                confirmation = self._project_corpus(
                    project_id, run, confirmation, journey
                )
            self.repository.store_triage_run(
                run.model_copy(
                    update={
                        "status": (
                            CompetitorTriageRunStatus.CONFIRMED
                            if confirmation.projection_status
                            in {"discovery_projected", "corpus_projected"}
                            else CompetitorTriageRunStatus.PROJECTION_PENDING
                        ),
                        "updated_at": _utc_now(),
                    }
                )
            )
        except Exception as exc:
            confirmation = confirmation.model_copy(
                update={
                    "projection_status": "failed",
                    "projection_error": f"{type(exc).__name__}: {exc}",
                    "projection_attempts": confirmation.projection_attempts + 1,
                }
            )
            self.repository.store_triage_run(
                run.model_copy(
                    update={
                        "status": CompetitorTriageRunStatus.PROJECTION_PENDING,
                        "updated_at": _utc_now(),
                    }
                )
            )
        self.repository.store_triage_confirmation(confirmation)
        return confirmation

    def _atomic_human_reconfirmation(
        self,
        *,
        project_id: str,
        run: CompetitorTriageRun,
        confirmation: CompetitorTriageConfirmationRecord,
        request: CompetitorTriageBasketReconfirmationRequest,
    ) -> Optional[CompetitorTriageConfirmationRecord]:
        operation = "reconfirm_competitor_triage_basket"
        existing = self.repository.triage_confirmation(
            project_id, confirmation.confirmation_id
        )
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay_id = self.repository.triage_idempotent_replay(
                connection,
                project_id,
                operation,
                request.idempotency_key,
                confirmation.confirmation_hash,
            )
            if replay_id is not None:
                connection.commit()
                replay = self.repository.triage_confirmation(project_id, replay_id)
                if replay is None:
                    raise CompetitorTriageConflictError(
                        "reconfirmed basket replay is missing"
                    )
                return replay
            if existing is not None:
                self.repository.triage_record_idempotency(
                    connection,
                    project_id,
                    operation,
                    request.idempotency_key,
                    confirmation.confirmation_hash,
                    confirmation.confirmation_id,
                )
                connection.commit()
                return existing
            connection.execute(
                """
                INSERT INTO competitor_triage_confirmations(
                    tenant_id, project_id, confirmation_id, run_id, snapshot_id,
                    confirmation_hash, projection_status, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_ID,
                    project_id,
                    confirmation.confirmation_id,
                    run.run_id,
                    run.snapshot_id,
                    confirmation.confirmation_hash,
                    confirmation.projection_status,
                    _canonical_json(confirmation.model_dump(mode="json")),
                    confirmation.created_at.isoformat(),
                ),
            )
            classification_map = {
                result.nct_id: result.classification.value
                for chunk in run.chunks
                for result in chunk.results
            }
            for nct_id in sorted(confirmation.final_classifications):
                final_status = confirmation.final_classifications[nct_id].value
                ai_status = classification_map.get(nct_id, "unknown")
                decision_reason = (
                    f"医学经理按当前研究事实复核既有分诊；来源确认 {confirmation.source_confirmation_id}。"
                    f"原AI分类 {ai_status}，本次确认 {final_status}。"
                )
                if confirmation.reason:
                    decision_reason += f"复核说明：{confirmation.reason}"
                self._write_relevance_decision_in_tx(
                    connection,
                    project_id=project_id,
                    snapshot_id=run.snapshot_id,
                    nct_id=nct_id,
                    relevance_status=final_status,
                    reason=decision_reason,
                    actor=request.actor,
                )
            self.repository.triage_record_idempotency(
                connection,
                project_id,
                operation,
                request.idempotency_key,
                confirmation.confirmation_hash,
                confirmation.confirmation_id,
            )
            connection.commit()
        return None

    def _atomic_confirm_and_decisions(
        self,
        *,
        project_id: str,
        run: CompetitorTriageRun,
        confirmation: CompetitorTriageConfirmationRecord,
        request: CompetitorTriageBasketConfirmationRequest,
        classification_map: Dict[str, str],
        idempotency_operation: str,
    ) -> Optional[str]:
        """Atomically persist confirmation, final decisions, run, idempotency.

        This is a single SQLite transaction in writing_reference.sqlite3.
        The medical manager's final classifications are authoritative; the AI
        classifications remain available on the immutable run for comparison.
        """
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                replay_id = self.repository.triage_idempotent_replay(
                    connection,
                    project_id,
                    idempotency_operation,
                    request.idempotency_key,
                    confirmation.confirmation_hash,
                )
                if replay_id is not None:
                    connection.commit()
                    return replay_id

                connection.execute(
                    """
                    INSERT INTO competitor_triage_confirmations(
                        tenant_id, project_id, confirmation_id, run_id, snapshot_id,
                        confirmation_hash, projection_status, payload_json,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        TENANT_ID,
                        project_id,
                        confirmation.confirmation_id,
                        confirmation.run_id,
                        confirmation.snapshot_id,
                        confirmation.confirmation_hash,
                        "pending",
                        _canonical_json(confirmation.model_dump(mode="json")),
                        confirmation.created_at.isoformat(),
                    ),
                )

                for nct_id in sorted(confirmation.final_classifications):
                    status = confirmation.final_classifications[nct_id].value
                    ai_status = classification_map.get(nct_id)
                    decision_reason = (
                        f"医学经理确认竞品AI分诊 {confirmation.confirmation_id}。"
                    )
                    if ai_status != status:
                        decision_reason += (
                            f"最终分类由AI建议 {ai_status} 调整为 {status}。"
                        )
                    if confirmation.reason:
                        decision_reason += f"确认说明：{confirmation.reason}"
                    self._write_relevance_decision_in_tx(
                        connection,
                        project_id=project_id,
                        snapshot_id=confirmation.snapshot_id,
                        nct_id=nct_id,
                        relevance_status=status,
                        reason=decision_reason,
                        actor=request.actor,
                    )

                confirmed_run = run.model_copy(
                    update={
                        "status": CompetitorTriageRunStatus.CONFIRMED,
                        "updated_at": _utc_now(),
                    }
                )
                cursor = connection.execute(
                    """
                    UPDATE competitor_triage_runs
                    SET status = ?, payload_json = ?, updated_at = ?
                    WHERE tenant_id = ? AND project_id = ? AND run_id = ?
                    """,
                    (
                        CompetitorTriageRunStatus.CONFIRMED.value,
                        _canonical_json(confirmed_run.model_dump(mode="json")),
                        confirmed_run.updated_at.isoformat(),
                        TENANT_ID,
                        project_id,
                        run.run_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise CompetitorTriageConflictError(
                        "triage run disappeared during confirmation"
                    )

                self.repository.triage_record_idempotency(
                    connection,
                    project_id,
                    idempotency_operation,
                    request.idempotency_key,
                    confirmation.confirmation_hash,
                    confirmation.confirmation_id,
                )
                connection.commit()
                return None
            except WritingReferenceConflictError as exc:
                connection.rollback()
                raise CompetitorTriageConflictError(str(exc)) from exc
            except Exception:
                connection.rollback()
                raise

    def _write_relevance_decision_in_tx(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        snapshot_id: str,
        nct_id: str,
        relevance_status: str,
        reason: str,
        actor: str,
    ) -> None:
        """Write a single relevance decision within an existing transaction."""
        from packages.contracts.workbench_contracts import (
            WritingReferenceRelevanceDecision,
        )

        state = connection.execute(
            """
            SELECT revision FROM writing_reference_relevance_state
            WHERE tenant_id = ? AND project_id = ? AND snapshot_id = ?
              AND nct_id = ?
            """,
            (TENANT_ID, project_id, snapshot_id, nct_id),
        ).fetchone()
        actual_revision = int(state["revision"]) if state is not None else 0
        revision = actual_revision + 1
        created_at = _repo_utc_now()
        decision_id = "wref_rel_" + sha256(
            _canonical_json(
                {
                    "project_id": project_id,
                    "snapshot_id": snapshot_id,
                    "nct_id": nct_id,
                    "relevance_status": relevance_status,
                    "revision": revision,
                }
            ).encode("utf-8")
        ).hexdigest()[:20]
        decision = WritingReferenceRelevanceDecision(
            decision_id=decision_id,
            project_id=project_id,
            snapshot_id=snapshot_id,
            nct_id=nct_id,
            relevance_status=relevance_status,
            reason=reason,
            revision=revision,
            actor=actor,
            created_at=created_at,
        )
        connection.execute(
            """
            INSERT INTO writing_reference_relevance_records(
                tenant_id, project_id, snapshot_id, nct_id, decision_id,
                revision, relevance_status, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                TENANT_ID,
                project_id,
                snapshot_id,
                nct_id,
                decision_id,
                revision,
                relevance_status,
                _canonical_json(decision.model_dump(mode="json")),
                created_at.isoformat(),
            ),
        )
        if state is None:
            connection.execute(
                """
                INSERT INTO writing_reference_relevance_state(
                    tenant_id, project_id, snapshot_id, nct_id, revision,
                    decision_id, relevance_status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_ID,
                    project_id,
                    snapshot_id,
                    nct_id,
                    revision,
                    decision_id,
                    relevance_status,
                    created_at.isoformat(),
                ),
            )
        else:
            connection.execute(
                """
                UPDATE writing_reference_relevance_state
                SET revision = ?, decision_id = ?, relevance_status = ?,
                    updated_at = ?
                WHERE tenant_id = ? AND project_id = ? AND snapshot_id = ?
                  AND nct_id = ? AND revision = ?
                """,
                (
                    revision,
                    decision_id,
                    relevance_status,
                    created_at.isoformat(),
                    TENANT_ID,
                    project_id,
                    snapshot_id,
                    nct_id,
                    actual_revision,
                ),
            )

    def _project_discovery_basket(
        self,
        project_id: str,
        run: CompetitorTriageRun,
        confirmation: CompetitorTriageConfirmationRecord,
        request: CompetitorTriageBasketConfirmationRequest,
    ) -> CompetitorTriageConfirmationRecord:
        """Project the confirmed discovery basket to the authoring journey.

        This writes a ``discovery_basket_projection`` reference on the journey
        — NOT final corpus triage. It does NOT require PICOS completion.

        If projection fails, persist projection_status=failed and mark the run
        as projection_pending. The projection can be retried without a second
        user approval.
        """
        try:
            self.journey_service.project_discovery_basket(
                project_id,
                confirmation_id=confirmation.confirmation_id,
                confirmation_hash=confirmation.confirmation_hash,
                snapshot_id=run.snapshot_id,
                retained_nct_ids=sorted(confirmation.retained_nct_ids),
                excluded_nct_ids=sorted(confirmation.excluded_nct_ids),
                run_id=run.run_id,
                actor=request.actor,
                reason=confirmation.reason,
                expected_journey_revision=request.expected_journey_revision,
                idempotency_key=f"triage_disc_{confirmation.confirmation_id}",
            )
            # Check if PICOS is already complete — if so, also project corpus
            journey = self.journey_service.get(project_id)
            if journey.picos_complete:
                confirmation = self._project_corpus(
                    project_id, run, confirmation, journey
                )
            else:
                confirmation = confirmation.model_copy(
                    update={"projection_status": "discovery_projected"}
                )
        except Exception as exc:
            logger.warning(
                "discovery basket projection failed for confirmation %s: %s",
                confirmation.confirmation_id,
                exc,
            )
            confirmation = confirmation.model_copy(
                update={
                    "projection_status": "failed",
                    "projection_error": f"{type(exc).__name__}: {exc}",
                    "projection_attempts": confirmation.projection_attempts + 1,
                }
            )
            run_updated = run.model_copy(
                update={
                    "status": CompetitorTriageRunStatus.PROJECTION_PENDING,
                    "updated_at": _utc_now(),
                }
            )
            self.repository.store_triage_run(run_updated)

        self.repository.store_triage_confirmation(confirmation)
        return confirmation

    def _project_corpus(
        self,
        project_id: str,
        run: CompetitorTriageRun,
        confirmation: CompetitorTriageConfirmationRecord,
        journey: MedicalWritingAuthoringJourney,
    ) -> CompetitorTriageConfirmationRecord:
        """Project the confirmed basket to final corpus triage (PICOS must be
        complete). This is idempotent — uses the confirmation_id as
        idempotency key so repeated calls are safe.
        """
        try:
            if not confirmation.retained_nct_ids:
                corpus_reason = (
                    confirmation.no_suitable_competitor_reason
                    or confirmation.reason
                    or "医学经理确认本次候选均不适合作为竞品或间接参照。"
                )
            elif confirmation.confirmation_kind == "human_reconfirmation":
                corpus_reason = (
                    f"Human basket reconfirmation {confirmation.confirmation_id}"
                )
            else:
                corpus_reason = (
                    f"AI triage confirmation {confirmation.confirmation_id}"
                )
            finalize_request = MedicalWritingCorpusTriageFinalizeRequest(
                expected_revision=journey.revision,
                snapshot_id=run.snapshot_id,
                retained_candidate_ids=sorted(confirmation.retained_nct_ids),
                reason=corpus_reason,
                actor=confirmation.actor,
                idempotency_key=f"triage_corpus_{confirmation.confirmation_id}",
            )
            self.journey_service.finalize_corpus_triage(
                project_id, finalize_request
            )
            confirmation = confirmation.model_copy(
                update={"projection_status": "corpus_projected"}
            )
        except Exception as exc:
            logger.warning(
                "corpus projection failed for confirmation %s: %s",
                confirmation.confirmation_id,
                exc,
            )
            confirmation = confirmation.model_copy(
                update={
                    "projection_status": "deferred_until_picos",
                    "projection_error": f"{type(exc).__name__}: {exc}",
                }
            )

        self.repository.store_triage_confirmation(confirmation)
        return confirmation

    def retry_projection(
        self,
        project_id: str,
        confirmation_id: str,
        request: CompetitorTriageProjectionRetryRequest,
    ) -> CompetitorTriageConfirmationRecord:
        """Retry projection without a second user approval.

        If the confirmation is in discovery_projected/failed state and PICOS
        is now complete, projects to corpus. Otherwise retries the discovery
        projection.
        """
        confirmation = self.repository.triage_confirmation(
            project_id, confirmation_id
        )
        if confirmation is None:
            raise KeyError(confirmation_id)

        # Already corpus-projected — idempotent return
        if confirmation.projection_status == "corpus_projected":
            return confirmation

        run = self.repository.triage_run(project_id, confirmation.run_id)
        if run is None:
            raise KeyError(confirmation.run_id)

        journey = self.journey_service.get(project_id)
        confirmation = confirmation.model_copy(
            update={
                "projection_attempts": confirmation.projection_attempts + 1
            }
        )

        # If discovery projection hasn't succeeded yet, retry that first
        if confirmation.projection_status in ("pending", "failed"):
            try:
                journey = self._retry_discovery_projection(
                    project_id=project_id,
                    run=run,
                    confirmation=confirmation,
                    journey=journey,
                    request=request,
                )
                if journey.picos_complete:
                    confirmation = self._project_corpus(
                        project_id, run, confirmation, journey
                    )
                else:
                    confirmation = confirmation.model_copy(
                        update={
                            "projection_status": "discovery_projected",
                            "projection_error": "",
                        }
                    )
            except Exception as exc:
                confirmation = confirmation.model_copy(
                    update={
                        "projection_error": f"{type(exc).__name__}: {exc}",
                    }
                )
        elif confirmation.projection_status in (
            "discovery_projected",
            "deferred_until_picos",
        ):
            # Discovery is projected; try corpus projection if PICOS is complete
            if journey.picos_complete:
                try:
                    stale_reason = self._confirmation_stale_reason(
                        project_id, run, confirmation
                    )
                    if stale_reason:
                        raise CompetitorTriageStaleError(stale_reason)
                    if (
                        journey.search_plan is not None
                        and not journey.search_plan.latest_snapshot_id
                        and journey.discovery_basket_projection.snapshot_id
                        == run.snapshot_id
                    ):
                        snapshot = self.repository.search_snapshot(
                            project_id, run.snapshot_id
                        )
                        journey = self.journey_service.restore_confirmed_search_snapshot_binding(
                            project_id,
                            snapshot,
                            confirmation_id=confirmation.confirmation_id,
                            confirmation_hash=confirmation.confirmation_hash,
                            run_id=run.run_id,
                            expected_revision=journey.revision,
                            actor=request.actor,
                            idempotency_key=(
                                f"{request.idempotency_key}:restore-search-binding"
                            ),
                        )
                    confirmation = self._project_corpus(
                        project_id, run, confirmation, journey
                    )
                except Exception as exc:
                    confirmation = confirmation.model_copy(
                        update={
                            "projection_status": "deferred_until_picos",
                            "projection_error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    self.repository.store_triage_confirmation(confirmation)
            else:
                # PICOS still not complete — nothing to do
                confirmation = confirmation.model_copy(
                    update={"projection_status": "discovery_projected"}
                )

        # Restore run to CONFIRMED if projection succeeded
        if confirmation.projection_status in (
            "discovery_projected",
            "corpus_projected",
        ):
            run_updated = run.model_copy(
                update={
                    "status": CompetitorTriageRunStatus.CONFIRMED,
                    "updated_at": _utc_now(),
                }
            )
            self.repository.store_triage_run(run_updated)

        self.repository.store_triage_confirmation(confirmation)
        return confirmation

    def _retry_discovery_projection(
        self,
        *,
        project_id: str,
        run: CompetitorTriageRun,
        confirmation: CompetitorTriageConfirmationRecord,
        journey: MedicalWritingAuthoringJourney,
        request: CompetitorTriageProjectionRetryRequest,
    ) -> MedicalWritingAuthoringJourney:
        stale_reason = self._confirmation_stale_reason(
            project_id, run, confirmation
        )
        if stale_reason:
            raise CompetitorTriageStaleError(stale_reason)
        if confirmation.confirmation_kind == "human_reconfirmation":
            snapshot = self.repository.search_snapshot(project_id, run.snapshot_id)
            return self.journey_service.project_human_reconfirmed_basket(
                project_id,
                snapshot,
                confirmation_id=confirmation.confirmation_id,
                confirmation_hash=confirmation.confirmation_hash,
                source_confirmation_id=confirmation.source_confirmation_id,
                run_id=run.run_id,
                retained_nct_ids=confirmation.retained_nct_ids,
                excluded_nct_ids=confirmation.excluded_nct_ids,
                expected_revision=journey.revision,
                actor=request.actor,
                reason=confirmation.reason,
                idempotency_key=(
                    f"triage_reconfirm_project_{confirmation.confirmation_id}"
                ),
            )
        self.journey_service.project_discovery_basket(
            project_id,
            confirmation_id=confirmation.confirmation_id,
            confirmation_hash=confirmation.confirmation_hash,
            snapshot_id=run.snapshot_id,
            retained_nct_ids=sorted(confirmation.retained_nct_ids),
            excluded_nct_ids=sorted(confirmation.excluded_nct_ids),
            run_id=run.run_id,
            actor=request.actor,
            reason=confirmation.reason,
            expected_journey_revision=journey.revision,
            idempotency_key=f"triage_disc_{confirmation.confirmation_id}",
        )
        return self.journey_service.get(project_id)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _summarize(self, run: CompetitorTriageRun) -> CompetitorTriageRunSummary:
        succeeded = [
            c for c in run.chunks
            if c.status == CompetitorTriageChunkStatus.SUCCEEDED
        ]
        failed = [
            c for c in run.chunks
            if c.status == CompetitorTriageChunkStatus.FAILED
        ]
        total_candidates = sum(len(c.results) for c in succeeded)
        confirmation = self.repository.triage_confirmation_for_run(
            run.project_id, run.run_id
        )
        return CompetitorTriageRunSummary(
            run_id=run.run_id,
            project_id=run.project_id,
            status=run.status,
            snapshot_id=run.snapshot_id,
            total_chunks=len(run.chunks),
            succeeded_chunks=len(succeeded),
            failed_chunks=len(failed),
            total_candidates=total_candidates,
            recommended_retain_count=len(run.recommended_retain),
            recommended_exclude_count=len(run.recommended_exclude),
            provider=run.provider,
            response_model=run.response_model,
            prompt_version=run.prompt_version,
            canonical_input_hash=run.canonical_input_hash,
            canonical_output_hash=run.canonical_output_hash,
            stale_reason=run.stale_reason,
            confirmation_id=(
                confirmation.confirmation_id if confirmation else ""
            ),
            created_at=run.created_at,
            updated_at=run.updated_at,
        )
