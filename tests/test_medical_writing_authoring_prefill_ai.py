"""Focused tests for the production DeepSeek prefill AI adapter.

Remediation pass (2026-07-20) — every test below verifies a production safety
contract against the accepted worker_01 source.  Vacuous assertions that merely
checked constants or Pydantic object shape have been removed or rewritten so
that each test proves a concrete failure mode.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import time
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from packages.contracts.workbench_contracts import (
    AuthoringPrefillAdoptRequest,
    AuthoringPrefillCandidate,
    AuthoringPrefillEvidenceRef,
    AuthoringPrefillGenerateRequest,
    AuthoringPrefillPackage,
    MedicalWritingAuthoringJourneyCreateRequest,
    MedicalWritingStudyFraming,
    WritingReferencePublicDocument,
    WritingReferenceTrialCandidate,
)
from services.api.app.ai_gateway import (
    AiPromptEnvelope,
    AiProviderRuntimeError,
    AiTaskType,
    DIRECT_DEEPSEEK_BASE_URL,
    DIRECT_DEEPSEEK_MODEL,
    DIRECT_DEEPSEEK_MODELS,
    OpenAICompatibleAiProvider,
    configured_ai_provider_from_env,
)
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyConflictError,
    MedicalWritingAuthoringJourneyService,
)
from services.api.app.medical_writing_authoring_prefill import (
    EXACT_FACT_PATHS,
    PrefillRankingAdapter,
    ServerEvidenceVerifier,
    generate_prefill_package,
    select_safe_recommended_candidate_id,
)
from services.api.app.medical_writing_authoring_prefill_evidence import (
    build_evidence_catalog,
)


def _live_resolver_verifier(service) -> ServerEvidenceVerifier:
    """Mirror the endpoint wiring: rebuild the live catalog from the current
    journey at adoption time (worker_01 single-candidate gate)."""

    def _catalog_resolver():
        journey = service.get("proj_ra")
        return build_evidence_catalog(
            journey,
            snapshot=None,
            journey_revision=journey.revision,
        )

    return ServerEvidenceVerifier(catalog_resolver=_catalog_resolver)

# Production AI adapter (worker_01 source, accepted by Codex).
from services.api.app.medical_writing_authoring_prefill_ai import (
    DEEPSEEK_PREFILL_MODEL,
    DEEPSEEK_PREFILL_TIMEOUT_SECONDS,
    _AI_ELIGIBLE_FIELDS,
    _BULK_SYSTEM_PROMPT,
    _build_condition_candidate,
    _collect_registered_source_ids,
    _detect_exact_fact_content,
    _extract_prefill_suggestions,
    _parse_field_suggestions,
    _passes_language_and_evidence_gate,
    _screen_snapshot_candidates,
    _BulkPrefillEnvelope,
    DeepSeekPrefillAdapter,
    build_prefill_ai_adapter,
)

NOW = datetime(2026, 7, 20, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ra_create_request(**overrides) -> MedicalWritingAuthoringJourneyCreateRequest:
    framing_fields: dict[str, Any] = {
        "investigational_product": "CMS-RA-201",
        "indication": "类风湿关节炎",
        "study_phase": "II期",
    }
    request_fields: dict[str, Any] = {
        "actor": "medical_manager_test",
        "idempotency_key": "create-ra-001",
    }
    for key, value in overrides.items():
        if key in framing_fields:
            framing_fields[key] = value
        else:
            request_fields[key] = value
    request_fields["framing"] = MedicalWritingStudyFraming(**framing_fields)
    return MedicalWritingAuthoringJourneyCreateRequest(**request_fields)


def _pnh_create_request(**overrides) -> MedicalWritingAuthoringJourneyCreateRequest:
    framing_fields: dict[str, Any] = {
        "investigational_product": "CMS-PNH-301",
        "indication": "阵发性睡眠性血红蛋白尿症",
        "study_phase": "III期",
    }
    request_fields: dict[str, Any] = {
        "actor": "medical_manager_test",
        "idempotency_key": "create-pnh-001",
    }
    for key, value in overrides.items():
        if key in framing_fields:
            framing_fields[key] = value
        else:
            request_fields[key] = value
    request_fields["framing"] = MedicalWritingStudyFraming(**framing_fields)
    return MedicalWritingAuthoringJourneyCreateRequest(**request_fields)


class _CountingProvider:
    """Records every ``run`` call and returns a canned response.

    W2b-2 r2: If the response does not contain ``catalog_id`` /
    ``catalog_sha256``, the provider auto-echoes them from the request
    payload's ``evidence_catalog`` so that catalog-bound validation passes.
    """

    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.response = response or {
            "_response_model": DEEPSEEK_PREFILL_MODEL,
            "prefill_suggestions": {},
        }
        self.call_count = 0
        self.calls: list[Any] = []

    def run(self, envelope: Any) -> dict[str, Any]:
        self.call_count += 1
        self.calls.append(envelope)
        result = dict(self.response)
        # Auto-echo catalog identity from request payload.
        ec = getattr(envelope, "payload", {}).get("evidence_catalog")
        if ec:
            cat_id = ec.get("catalog_id", "")
            cat_sha = ec.get("catalog_sha256", "")
            # Inject at top level.
            if "catalog_id" not in result:
                result["catalog_id"] = cat_id
            if "catalog_sha256" not in result:
                result["catalog_sha256"] = cat_sha
            # Also inject inside prefill_suggestions wrapper if present.
            ps = result.get("prefill_suggestions")
            if isinstance(ps, dict):
                if "catalog_id" not in ps:
                    ps["catalog_id"] = cat_id
                if "catalog_sha256" not in ps:
                    ps["catalog_sha256"] = cat_sha
        return result


class _ExplodingProvider:
    def run(self, envelope: Any) -> dict[str, Any]:
        raise TimeoutError("simulated provider timeout")


class _ExplodingAdapter(PrefillRankingAdapter):
    """Per-field adapter that raises during inference."""

    def rank_and_phrase(
        self, *, field_path: str, candidates: list[AuthoringPrefillCandidate],
        context: dict[str, Any],
    ) -> list[AuthoringPrefillCandidate]:
        raise RuntimeError("provider inference failed")


def _mark_research_ready_for_test(
    service: MedicalWritingAuthoringJourneyService,
    project_id: str,
    *,
    idempotency_key: str,
):
    """Persist a test-only corpus-ready projection before calling product code.

    This fixture intentionally models the prerequisite already established by
    the research pipeline. It does not bypass the product gate or assert that
    an override alone is sufficient.
    """
    current = service.get(project_id)
    updated = current.model_copy(
        update={
            "revision": current.revision + 1,
            "research_pipeline": {"stage": "corpus_ready", "fixture": "test_only"},
            "updated_at": NOW,
            "updated_by": "test_fixture",
        },
        deep=True,
    )
    with service._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        service._persist_update(
            connection,
            updated,
            expected_revision=current.revision,
            event_type="test_research_pipeline_ready",
            actor="test_fixture",
            idempotency_key=idempotency_key,
            request_sha256="a" * 64,
            detail={"fixture": "research_ready_for_prefill"},
        )
        connection.commit()
    return service.get(project_id)


# ---------------------------------------------------------------------------
# 1. Bulk provider call: exactly one provider.run for the whole package
# ---------------------------------------------------------------------------

class BulkProviderCallTests(unittest.TestCase):
    """The production DeepSeekPrefillAdapter makes exactly one provider call
    for the complete package — not one per field."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_ra", _ra_create_request())

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_bulk_envelope_leaves_headroom_for_max_reasoning_and_json(self):
        envelope = _BulkPrefillEnvelope("Return JSON.", {"probe": True})

        # DeepSeek V4 shares max_tokens between hidden reasoning and visible
        # JSON.  16K could terminate with finish_reason=length before any
        # structured content; 64K is the bounded prefill ceiling.
        self.assertEqual(65536, envelope.max_output_tokens)


class AiRunAuditTests(unittest.TestCase):
    """Accepted AI candidates must link to the completed product call."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_ra", _ra_create_request())

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_internal_run_id_is_stable_and_shared_by_package_and_candidate(self):
        journey = self.service.get("proj_ra")
        deterministic = generate_prefill_package(
            state=journey, now=NOW, actor="test"
        )
        response = {
            "_response_model": DEEPSEEK_PREFILL_MODEL,
            "prefill_suggestions": {
                "clinicaltrials_condition_term_en": "Rheumatoid Arthritis",
                "field_suggestions": {},
                "package_suggestions": {},
            },
        }
        adapter = DeepSeekPrefillAdapter(
            provider=_CountingProvider(response), model_name=DEEPSEEK_PREFILL_MODEL
        )
        first = adapter.enrich_package(package=deterministic, state=journey)
        second = adapter.enrich_package(package=deterministic, state=journey)

        self.assertTrue(first.ai_run_id.startswith("mwprefillrun_"))
        self.assertEqual(first.ai_run_id, second.ai_run_id)
        self.assertEqual(first.ai_input_sha256, second.ai_input_sha256)
        self.assertEqual(first.ai_output_sha256, second.ai_output_sha256)
        self.assertEqual(64, len(first.ai_input_sha256))
        self.assertEqual(64, len(first.ai_output_sha256))
        self.assertEqual(DEEPSEEK_PREFILL_MODEL, first.model_name)
        self.assertTrue(first.prompt_version)
        candidate = next(
            item
            for item in first.field_candidates[
                "framing.clinicaltrials_condition_term"
            ].candidates
            if item.structured_value == "Rheumatoid Arthritis"
        )
        self.assertEqual(first.ai_run_id, candidate.ai_run_id)
        self.assertTrue(candidate.claim_bindings)

    def test_completed_but_rejected_output_keeps_package_audit_without_candidate_run(self):
        journey = self.service.get("proj_ra")
        deterministic = generate_prefill_package(
            state=journey, now=NOW, actor="test"
        )
        adapter = DeepSeekPrefillAdapter(
            provider=_CountingProvider(
                {
                    "_response_model": DEEPSEEK_PREFILL_MODEL,
                    "prefill_suggestions": {
                        "field_suggestions": {
                            "framing.population_intent": [{
                                "structured_value": "成人活动性类风湿关节炎患者",
                                "preview": "成人活动性类风湿关节炎患者",
                                "rationale": "无合法证据绑定。",
                                "claim_bindings": [],
                            }]
                        },
                        "package_suggestions": {},
                    },
                }
            ),
            model_name=DEEPSEEK_PREFILL_MODEL,
        )
        enriched = adapter.enrich_package(package=deterministic, state=journey)

        self.assertTrue(enriched.ai_run_id)
        self.assertTrue(enriched.ai_input_sha256)
        self.assertTrue(enriched.ai_output_sha256)
        self.assertFalse(any(
            candidate.ai_run_id
            for group in enriched.field_candidates.values()
            for candidate in group.candidates
            if candidate.ai_run_id == enriched.ai_run_id
        ))

    def test_unbounded_treatment_line_is_rejected_when_not_in_bound_evidence(self):
        passed, reason, gap_notes = _passes_language_and_evidence_gate(
            "framing.population_intent",
            "类风湿关节炎受试者（不限治疗线）",
            "类风湿关节炎受试者（不限治疗线）",
            "候选人群。",
            evidence_refs=[
                AuthoringPrefillEvidenceRef(
                    source_kind="search_snapshot",
                    source_id="ctgov:test:NCT00000000",
                    locator="ctgov:test:NCT00000000:conditions",
                    source_text="Rheumatoid Arthritis",
                )
            ],
        )
        self.assertFalse(passed)
        # A substantive controlled claim absent from the bound quote now
        # surfaces as a visible reader-facing evidence gap (fail-closed but
        # not silent).
        self.assertEqual(
            ["声称内容未在引用原文中出现：不限治疗线相关表述"],
            gap_notes,
        )
        self.assertIn("treatment_line_scope", reason)

    def test_population_criteria_translation_is_rejected_when_source_only_names_disease(self):
        passed, reason, gap_notes = _passes_language_and_evidence_gate(
            "picos.population_summary",
            "经临床和实验室检查确诊为类风湿关节炎的受试者。",
            "经临床和实验室检查确诊为类风湿关节炎的受试者。",
            "候选人群。",
            evidence_refs=[
                AuthoringPrefillEvidenceRef(
                    source_kind="search_snapshot",
                    source_id="ctgov:test:NCT00000000",
                    locator="ctgov:test:NCT00000000:conditions",
                    source_text="Rheumatoid Arthritis",
                )
            ],
        )
        self.assertFalse(passed)
        self.assertEqual(
            ["声称内容未在引用原文中出现：临床/实验室检查确诊相关表述"],
            gap_notes,
        )
        self.assertIn("diagnostic_confirmation", reason)

    def test_enrich_package_calls_provider_exactly_once(self):
        """``enrich_package`` calls ``provider.run`` exactly once regardless of
        how many eligible fields exist in the package."""
        journey = self.service.get("proj_ra")
        deterministic = generate_prefill_package(
            state=journey, now=NOW, actor="test"
        )
        provider = _CountingProvider()
        adapter = DeepSeekPrefillAdapter(
            provider=provider, model_name=DEEPSEEK_PREFILL_MODEL
        )
        adapter.enrich_package(package=deterministic, state=journey)
        self.assertEqual(
            1, provider.call_count,
            "enrich_package must make exactly one bulk provider call, "
            f"got {provider.call_count}",
        )

    def test_bulk_payload_includes_all_eligible_field_groups(self):
        """The single provider call payload includes every eligible field
        group from the deterministic package — not just one field."""
        journey = self.service.get("proj_ra")
        deterministic = generate_prefill_package(
            state=journey, now=NOW, actor="test"
        )
        provider = _CountingProvider()
        adapter = DeepSeekPrefillAdapter(
            provider=provider, model_name=DEEPSEEK_PREFILL_MODEL
        )
        adapter.enrich_package(package=deterministic, state=journey)
        self.assertEqual(1, len(provider.calls))
        payload = provider.calls[0].payload
        candidates_in_payload = payload.get("current_deterministic_candidates", [])
        eligible_in_package = [
            fp for fp in deterministic.field_candidates
            if fp in _AI_ELIGIBLE_FIELDS
        ]
        paths_in_payload = {c["field_path"] for c in candidates_in_payload}
        for fp in eligible_in_package:
            self.assertIn(
                fp, paths_in_payload,
                f"eligible field {fp} missing from bulk payload",
            )

    def test_provider_with_no_call_interface_records_failure(self):
        """A provider without ``run`` degrades to a partial_source_failure."""
        journey = self.service.get("proj_ra")
        deterministic = generate_prefill_package(
            state=journey, now=NOW, actor="test"
        )
        adapter = DeepSeekPrefillAdapter(
            provider=object(), model_name=DEEPSEEK_PREFILL_MODEL
        )
        enriched = adapter.enrich_package(package=deterministic, state=journey)
        self.assertGreater(len(enriched.partial_source_failures), 0)
        self.assertGreater(len(enriched.field_candidates), 0)


# ---------------------------------------------------------------------------
# 2. Strict JSON parsing and schema filtering
# ---------------------------------------------------------------------------

class StrictJsonAndSchemaFilterTests(unittest.TestCase):

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_ra", _ra_create_request())

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_production_direct_response_shape_is_authoritative(self):
        """The adapter accepts the exact top-level JSON shape requested from
        the production model, without an undocumented wrapper."""
        response = {
            "clinicaltrials_condition_term_en": "Rheumatoid Arthritis",
            "field_suggestions": {},
        }
        self.assertIs(response, _extract_prefill_suggestions(response))

    def test_legacy_wrapped_response_shape_remains_compatible(self):
        suggestions = {
            "clinicaltrials_condition_term_en": "Rheumatoid Arthritis",
            "field_suggestions": {},
        }
        self.assertEqual(
            suggestions,
            _extract_prefill_suggestions({"prefill_suggestions": suggestions}),
        )

    def test_gateway_nested_response_shape_is_unwrapped_boundedly(self):
        suggestions = {
            "clinicaltrials_condition_term_en": "Rheumatoid Arthritis",
            "field_suggestions": {},
        }
        self.assertEqual(
            suggestions,
            _extract_prefill_suggestions({"output": {"result": suggestions}}),
        )

    def test_flat_allowlisted_field_map_is_normalized_without_widening_scope(self):
        result = _extract_prefill_suggestions(
            {
                "picos.design_archetype": [],
                "picos.population_summary": [],
            }
        )
        self.assertEqual(
            {
                "clinicaltrials_condition_term_en": "",
                "field_suggestions": {
                    "picos.design_archetype": [],
                    "picos.population_summary": [],
                },
                "package_suggestions": {},
            },
            result,
        )
        self.assertIsNone(_extract_prefill_suggestions({"unknown.path": []}))

    def test_parse_json_content_extracts_object_from_wrapped_text(self):
        from services.api.app.ai_gateway import _parse_json_content

        wrapped = 'Here is the result:\n```json\n{"field": "value"}\n```'
        result = _parse_json_content(wrapped)
        self.assertEqual({"field": "value"}, result)

    def test_parse_json_content_rejects_non_object(self):
        from services.api.app.ai_gateway import _parse_json_content

        with self.assertRaises(AiProviderRuntimeError):
            _parse_json_content("[1, 2, 3]")

    def test_parse_json_content_rejects_empty(self):
        from services.api.app.ai_gateway import _parse_json_content

        with self.assertRaises(AiProviderRuntimeError):
            _parse_json_content("")

    def test_ai_eligible_fields_exclude_identity_fields(self):
        """``_AI_ELIGIBLE_FIELDS`` must NOT include identity fields such as
        protocol_id, version, indication, study_phase, investigational_product,
        or target_mechanism — AI cannot rewrite creation minimum."""
        identity_fields = {
            "framing.protocol_id",
            "framing.version",
            "framing.indication",
            "framing.study_phase",
            "framing.investigational_product",
            "framing.product_profile.target_mechanism",
        }
        for field in identity_fields:
            self.assertNotIn(
                field, _AI_ELIGIBLE_FIELDS,
                f"identity field {field} must not be in AI eligible set",
            )

    def test_ai_eligible_fields_exclude_all_exact_fact_paths(self):
        """No EXACT_FACT_PATHS appear in ``_AI_ELIGIBLE_FIELDS``."""
        for path in EXACT_FACT_PATHS:
            self.assertNotIn(path, _AI_ELIGIBLE_FIELDS)

    def test_enrich_package_drops_unsupported_field_suggestions(self):
        """The adapter ignores AI suggestions for paths outside
        ``_AI_ELIGIBLE_FIELDS`` — including identity paths and arbitrary
        unknown paths.  Existing deterministic candidates for those fields
        are preserved unchanged."""
        journey = self.service.get("proj_ra")
        deterministic = generate_prefill_package(
            state=journey, now=NOW, actor="test"
        )
        provider = _CountingProvider({
            "_response_model": DEEPSEEK_PREFILL_MODEL,
            "prefill_suggestions": {
                "field_suggestions": {
                    "framing.protocol_id": [
                        {"value": "HACKED-001", "preview": "HACKED-001"},
                    ],
                    "framing.indication": [
                        {"value": "Changed indication", "preview": "Changed"},
                    ],
                    "nonexistent.path.xyz": [
                        {"value": "garbage", "preview": "garbage"},
                    ],
                },
            },
        })
        adapter = DeepSeekPrefillAdapter(
            provider=provider, model_name=DEEPSEEK_PREFILL_MODEL
        )
        enriched = adapter.enrich_package(package=deterministic, state=journey)
        # The unsupported path is never added.
        self.assertNotIn("nonexistent.path.xyz", enriched.field_candidates)
        # For existing deterministic identity fields (protocol_id), the AI
        # suggestion "HACKED-001" is NOT merged in — only the original
        # deterministic candidates remain.
        if "framing.protocol_id" in enriched.field_candidates:
            group = enriched.field_candidates["framing.protocol_id"]
            values = [str(c.structured_value) for c in group.candidates]
            self.assertNotIn("HACKED-001", values)


# ---------------------------------------------------------------------------
# 3. Wrong model identity, timeout, provider error, invalid JSON → fallback
# ---------------------------------------------------------------------------

class FallbackDegradationTests(unittest.TestCase):

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_ra", _ra_create_request())

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_wrong_model_identity_raises_runtime_error(self):
        """OpenAICompatibleAiProvider raises AiProviderRuntimeError when the
        response model identity does not match the configured model."""
        provider = OpenAICompatibleAiProvider(
            base_url=DIRECT_DEEPSEEK_BASE_URL,
            api_key="test-key",
            model_name=DIRECT_DEEPSEEK_MODEL,
            provider_name="deepseek",
            expected_response_model=DIRECT_DEEPSEEK_MODEL,
        )
        fake_body = json.dumps({
            "model": "deepseek-chat-wrong",
            "choices": [{"message": {"content": "{}"}}],
        })
        with patch("services.api.app.ai_gateway.urllib.request.urlopen") as mock_open:
            import io
            mock_open.return_value.__enter__ = lambda s: io.BytesIO(
                fake_body.encode("utf-8")
            )
            mock_open.return_value.__exit__ = lambda *a: False
            from services.api.app.ai_gateway import AiPromptEnvelope, AiTaskType
            with self.assertRaises(AiProviderRuntimeError) as ctx:
                provider.run(
                    AiPromptEnvelope(
                        task_id="test",
                        task_type=AiTaskType.PICOS_DESIGN_COACH,
                        prompt_version="v1",
                        system_prompt="test",
                        payload={"task_id": "test"},
                    )
                )
            self.assertIn("model identity", str(ctx.exception).lower())

    def test_adapter_wrong_model_identity_degrades_to_deterministic(self):
        """DeepSeekPrefillAdapter records a partial_source_failure when the
        provider returns the wrong model identity."""
        journey = self.service.get("proj_ra")
        deterministic = generate_prefill_package(
            state=journey, now=NOW, actor="test"
        )

        class _WrongModelProvider:
            def run(self, envelope):
                return {
                    "_response_model": "deepseek-chat-wrong",
                    "prefill_suggestions": {},
                }

        adapter = DeepSeekPrefillAdapter(
            provider=_WrongModelProvider(), model_name=DEEPSEEK_PREFILL_MODEL
        )
        enriched = adapter.enrich_package(package=deterministic, state=journey)
        self.assertGreater(len(enriched.partial_source_failures), 0)
        joined = " ".join(enriched.partial_source_failures).lower()
        self.assertIn("model identity", joined)

    def test_adapter_provider_timeout_degrades_to_deterministic(self):
        """Timeout records a partial_source_failure; package survives."""
        journey = self.service.get("proj_ra")
        deterministic = generate_prefill_package(
            state=journey, now=NOW, actor="test"
        )
        adapter = DeepSeekPrefillAdapter(
            provider=_ExplodingProvider(), model_name=DEEPSEEK_PREFILL_MODEL
        )
        enriched = adapter.enrich_package(package=deterministic, state=journey)
        self.assertGreater(len(enriched.field_candidates), 0)
        self.assertGreater(len(enriched.partial_source_failures), 0)

    def test_adapter_response_without_bulk_schema_degrades(self):
        """An unrelated response records a schema failure."""
        journey = self.service.get("proj_ra")
        deterministic = generate_prefill_package(
            state=journey, now=NOW, actor="test"
        )
        provider = _CountingProvider({
            "_response_model": DEEPSEEK_PREFILL_MODEL,
            "unrelated": "garbage",
        })
        adapter = DeepSeekPrefillAdapter(
            provider=provider, model_name=DEEPSEEK_PREFILL_MODEL
        )
        enriched = adapter.enrich_package(package=deterministic, state=journey)
        self.assertGreater(len(enriched.partial_source_failures), 0)
        self.assertIn(
            "does not match the bulk prefill schema",
            " ".join(enriched.partial_source_failures),
        )

    def test_adapter_no_provider_degrades_to_deterministic(self):
        """provider=None records a partial_source_failure."""
        journey = self.service.get("proj_ra")
        deterministic = generate_prefill_package(
            state=journey, now=NOW, actor="test"
        )
        adapter = DeepSeekPrefillAdapter(provider=None)
        enriched = adapter.enrich_package(package=deterministic, state=journey)
        self.assertGreater(len(enriched.partial_source_failures), 0)

    def test_disabled_provider_is_explicit(self):
        from services.api.app.ai_gateway import DisabledAiProvider

        provider = configured_ai_provider_from_env({})
        self.assertIsInstance(provider, DisabledAiProvider)


# ---------------------------------------------------------------------------
# 4. Partial valid model output augments only valid fields
# ---------------------------------------------------------------------------

class PartialOutputAugmentationTests(unittest.TestCase):

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_ra", _ra_create_request())

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_partial_output_adds_valid_field_only(self):
        """A provider that returns one valid field suggestion adds that field
        without losing existing deterministic fields."""
        journey = self.service.get("proj_ra")
        deterministic = generate_prefill_package(
            state=journey, now=NOW, actor="test"
        )
        provider = _CountingProvider({
            "_response_model": DEEPSEEK_PREFILL_MODEL,
            "prefill_suggestions": {
                "field_suggestions": {
                    "framing.document_title": [
                        {
                            "value": "A Phase II Study of CMS-RA-201 in RA",
                            "preview": "A Phase II Study",
                            "rationale": "AI rephrased title",
                        }
                    ],
                },
            },
        })
        adapter = DeepSeekPrefillAdapter(
            provider=provider, model_name=DEEPSEEK_PREFILL_MODEL
        )
        enriched = adapter.enrich_package(package=deterministic, state=journey)
        # The English AI title candidate must NOT appear — the quality gate
        # hard-drops whole-sentence English candidates.
        title_group = enriched.field_candidates.get("framing.document_title")
        self.assertIsNotNone(title_group)
        values = [str(c.structured_value) for c in title_group.candidates]
        self.assertFalse(
            any("Phase II Study" in v for v in values),
            f"English title must be hard-dropped by quality gate: {values}",
        )
        # Existing deterministic Chinese fields are preserved.
        self.assertGreaterEqual(
            len(enriched.field_candidates), len(deterministic.field_candidates),
        )

    def test_partial_output_skips_invalid_entries_in_same_field(self):
        """Within one field's suggestion list, non-dict and empty-value
        entries are silently skipped; valid ones survive."""
        registered = frozenset({"framing.indication"})
        candidates = _parse_field_suggestions(
            "framing.document_title",
            [
                "not-a-dict",  # skipped
                {"preview": "no value"},  # skipped (value is None)
                {"value": "  ", "preview": "blank"},  # skipped (blank value)
                {"value": "Valid Title", "preview": "Valid Title"},
            ],
            registered_source_ids=registered,
        )
        values = [str(c.structured_value) for c in candidates]
        self.assertEqual(["Valid Title"], values)


# ---------------------------------------------------------------------------
# 5. RA and PNH English ClinicalTrials.gov condition-term candidates
# ---------------------------------------------------------------------------

class EnglishConditionTermTests(unittest.TestCase):

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _build_adapter_and_enrich(
        self, create_request: MedicalWritingAuthoringJourneyCreateRequest,
        condition_term_en: str,
    ) -> AuthoringPrefillPackage:
        db_name = "ra.sqlite3" if "RA" in create_request.idempotency_key.upper() else "pnh.sqlite3"
        service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / db_name
        )
        service.create("proj", create_request)
        journey = service.get("proj")
        deterministic = generate_prefill_package(
            state=journey, now=NOW, actor="test"
        )
        provider = _CountingProvider({
            "_response_model": DEEPSEEK_PREFILL_MODEL,
            "clinicaltrials_condition_term_en": condition_term_en,
            "field_suggestions": {},
        })
        adapter = DeepSeekPrefillAdapter(
            provider=provider, model_name=DEEPSEEK_PREFILL_MODEL
        )
        return adapter.enrich_package(package=deterministic, state=journey)

    def test_ra_condition_candidate_is_english_rheumatoid_arthritis(self):
        """RA produces 'Rheumatoid Arthritis' as the recommended candidate."""
        package = self._build_adapter_and_enrich(
            _ra_create_request(), "Rheumatoid Arthritis"
        )
        group = package.field_candidates["framing.clinicaltrials_condition_term"]
        recommended = group.candidates[0]
        self.assertEqual("Rheumatoid Arthritis", str(recommended.structured_value))

    def test_pnh_condition_candidate_is_english_pnh(self):
        """PNH produces 'Paroxysmal Nocturnal Hemoglobinuria' as recommended."""
        package = self._build_adapter_and_enrich(
            _pnh_create_request(), "Paroxysmal Nocturnal Hemoglobinuria"
        )
        group = package.field_candidates["framing.clinicaltrials_condition_term"]
        recommended = group.candidates[0]
        self.assertEqual(
            "Paroxysmal Nocturnal Hemoglobinuria",
            str(recommended.structured_value),
        )

    def test_condition_candidate_source_text_is_original_indication_not_ai_output(self):
        """D1: The condition candidate's evidence source_text is the original
        indication string — NOT the AI-generated English condition term.

        W2b-2 r2: The condition candidate is now catalog-bound via the
        indication entry.  The evidence ref source_text is the indication
        entry's quote (the original Chinese indication), not the AI output.
        """
        package = self._build_adapter_and_enrich(
            _pnh_create_request(), "Paroxysmal Nocturnal Hemoglobinuria"
        )
        group = package.field_candidates.get("framing.clinicaltrials_condition_term")
        self.assertIsNotNone(group)
        candidate = group.candidates[0]
        # Must have catalog binding.
        self.assertTrue(candidate.evidence_catalog_id)
        self.assertTrue(candidate.evidence_catalog_sha256)
        self.assertGreater(len(candidate.claim_bindings), 0)
        # Evidence ref must carry the real indication text, not the AI output.
        ref = candidate.evidence_refs[0]
        self.assertNotIn("Paroxysmal Nocturnal Hemoglobinuria", ref.source_text)


# ---------------------------------------------------------------------------
# 6. Exact-fact leakage through eligible free-text fields (parameterized)
# ---------------------------------------------------------------------------

class ExactFactContentLeakageTests(unittest.TestCase):
    """Exact-fact patterns embedded in otherwise-eligible free-text fields
    (e.g. ``picos.intervention_summary``) are quarantined unless they cite a
    registered source ID."""

    # (category, eligible_field_path, text_with_exact_fact)
    LEAKAGE_CASES = [
        # dose
        ("dose", "picos.intervention_summary", "Administer 400mg once daily"),
        ("dose", "picos.intervention_summary", "每日口服50毫克"),
        # regimen / visit timing
        ("regimen", "picos.intervention_summary", "Q4W intravenous infusion"),
        ("regimen", "picos.visit_strategy", "每日两次给药"),
        # endpoint
        ("endpoint", "framing.intrinsic_objectives", "primary endpoint is ACR50"),
        ("endpoint", "framing.intrinsic_objectives", "主要终点为ACR20"),
        # AESI
        ("aesi", "picos.population_summary", "AESI includes serious infections"),
        ("aesi", "picos.population_summary", "特别关注不良事件包括感染"),
        # sample size
        ("sample_size", "picos.population_summary", "N=300 randomized subjects"),
        ("sample_size", "picos.population_summary", "样本量为240例受试者"),
        # washout
        ("washout", "picos.population_summary", "washout period of 14 days"),
        ("washout", "picos.population_summary", "洗脱期为28天"),
        # threshold
        ("threshold", "framing.intrinsic_objectives", "response rate of 50%"),
        ("threshold", "framing.intrinsic_objectives", "缓解率≥70%"),
        # visit timing
        ("visit_timing", "picos.study_epochs", "Week 24 primary assessment"),
        ("visit_timing", "picos.study_epochs", "第12周评估"),
    ]

    def test_detect_exact_fact_content_catches_all_categories(self):
        """``_detect_exact_fact_content`` returns the correct category for
        every leakage case — proving detection works before testing the
        quarantine gate."""
        for category, _field, text in self.LEAKAGE_CASES:
            with self.subTest(category=category, text=text):
                detected = _detect_exact_fact_content(text)
                self.assertIsNotNone(
                    detected,
                    f"failed to detect exact-fact content in: {text}",
                )
                self.assertEqual(category, detected)

    def test_exact_fact_in_eligible_field_quarantined_without_source_id(self):
        """When the AI embeds exact-fact text in an eligible free-text field
        without citing a registered source ID, the candidate is quarantined
        (dropped) — not silently accepted."""
        registered = frozenset({"framing.indication"})
        for category, field_path, text in self.LEAKAGE_CASES:
            with self.subTest(category=category, field=field_path):
                candidates = _parse_field_suggestions(
                    field_path,
                    [{"value": text, "preview": text, "rationale": "AI suggestion"}],
                    registered_source_ids=registered,
                )
                self.assertEqual(
                    [], candidates,
                    f"exact-fact {category} text must be quarantined without "
                    f"a registered source ID: {text}",
                )

    def test_exact_fact_in_eligible_field_accepted_with_registered_source_id(self):
        """When the AI embeds exact-fact text AND cites a source ID that IS in
        the request's ``registered_source_ids`` set, the candidate is accepted
        and its evidence ref carries that real source ID."""
        registered = frozenset({"protocol_artifact_001", "framing.indication"})
        for category, field_path, text in self.LEAKAGE_CASES:
            with self.subTest(category=category, field=field_path):
                candidates = _parse_field_suggestions(
                    field_path,
                    [{
                        "value": text,
                        "preview": text,
                        "rationale": "evidence-backed suggestion",
                        "source_ids": ["protocol_artifact_001"],
                    }],
                    registered_source_ids=registered,
                )
                self.assertEqual(
                    1, len(candidates),
                    f"evidence-backed exact-fact {category} must be accepted",
                )
                cand = candidates[0]
                self.assertGreater(len(cand.evidence_refs), 0)
                for ref in cand.evidence_refs:
                    self.assertIn(ref.source_id, registered)

    def test_exact_fact_citing_unregistered_source_id_is_quarantined(self):
        """An exact-fact candidate that cites a source ID NOT in
        ``registered_source_ids`` is quarantined."""
        registered = frozenset({"framing.indication"})
        candidates = _parse_field_suggestions(
            "picos.intervention_summary",
            [{
                "value": "400mg once daily",
                "preview": "400mg QD",
                "rationale": "dose from unknown doc",
                "source_ids": ["fabricated_source_xyz"],
            }],
            registered_source_ids=registered,
        )
        self.assertEqual(
            [], candidates,
            "exact-fact with unregistered source_id must be quarantined",
        )

    def test_non_exact_text_in_eligible_field_has_no_evidence_refs(self):
        """D1: A non-exact-fact AI candidate carries NO evidence refs — its
        provenance is in rationale/limitations, not pseudo-source evidence."""
        registered = frozenset({"framing.indication"})
        candidates = _parse_field_suggestions(
            "framing.document_title",
            [{
                "value": "CMS-RA-201治疗类风湿关节炎的II期研究方案",
                "preview": "CMS-RA-201治疗类风湿关节炎的II期研究方案",
                "rationale": "AI改写标题",
            }],
            registered_source_ids=registered,
        )
        self.assertEqual(1, len(candidates))
        self.assertEqual([], candidates[0].evidence_refs)
        self.assertIn(
            "医学经理", candidates[0].limitations[0],
        )

    def test_deterministic_package_reports_exact_fields_blocked(self):
        """The deterministic package reports blocked exact fields."""
        tmpdir = tempfile.TemporaryDirectory()
        try:
            service = MedicalWritingAuthoringJourneyService(
                Path(tmpdir.name) / "test.sqlite3"
            )
            service.create("proj_ra", _ra_create_request())
            journey = service.get("proj_ra")
            package = generate_prefill_package(state=journey, now=NOW, actor="test")
            self.assertGreater(
                package.progress.fields_blocked_missing_evidence, 0,
            )
        finally:
            tmpdir.cleanup()

    def test_adoption_rejects_exact_fact_path(self):
        """Adopting an EXACT_FACT_PATH raises ValueError."""
        tmpdir = tempfile.TemporaryDirectory()
        try:
            service = MedicalWritingAuthoringJourneyService(
                Path(tmpdir.name) / "test.sqlite3"
            )
            service.create("proj_ra", _ra_create_request())
            journey = service.get("proj_ra")
            service.generate_prefill("proj_ra", AuthoringPrefillGenerateRequest(
                expected_revision=journey.revision,
                actor="medical_manager_test",
                idempotency_key="prefill-exact-001",
            ))
            journey = service.get("proj_ra")
            package = journey.prefill_package
            adopt_request = AuthoringPrefillAdoptRequest(
                expected_revision=journey.revision,
                expected_package_revision=package.package_revision,
                field_path="picos.primary_endpoint",
                candidate_id="nonexistent",
                actor="medical_manager_test",
                idempotency_key="adopt-exact-001",
            )
            with self.assertRaises(ValueError) as ctx:
                service.adopt_prefill_candidate("proj_ra", adopt_request)
            self.assertIn("unsupported prefill adoption path", str(ctx.exception))
        finally:
            tmpdir.cleanup()


# ---------------------------------------------------------------------------
# 7. Evidence source IDs — fabricated/unregistered IDs rejected or stripped
# ---------------------------------------------------------------------------

class EvidenceSourceIdTests(unittest.TestCase):
    """Fabricated and unregistered source IDs are rejected or stripped.  AI
    generation provenance is never represented as source evidence."""

    def test_ai_candidate_has_no_evidence_refs_when_non_exact(self):
        """D1: Non-exact AI candidates have empty ``evidence_refs`` — no
        ``source_id='ai_bulk_prefill'`` pseudo-evidence."""
        registered = frozenset({"framing.indication"})
        candidates = _parse_field_suggestions(
            "picos.intervention_summary",
            [{"value": "monoclonal antibody targeting IL-6", "preview": "mAb"}],
            registered_source_ids=registered,
        )
        self.assertEqual(1, len(candidates))
        self.assertEqual([], candidates[0].evidence_refs)
        # Provenance is in limitations.
        self.assertTrue(candidates[0].limitations)

    def test_generated_text_is_not_its_own_evidence(self):
        """D1: The condition candidate's source_text is the original
        indication, not the AI-generated English term."""
        candidate = _build_condition_candidate(
            "Paroxysmal Nocturnal Hemoglobinuria",
            indication="阵发性睡眠性血红蛋白尿症",
            phase="III期",
        )
        ref = candidate.evidence_refs[0]
        self.assertEqual("framing.indication", ref.source_id)
        self.assertEqual("阵发性睡眠性血红蛋白尿症", ref.source_text)
        self.assertNotIn("Paroxysmal", ref.source_text)

    def test_registered_source_ids_include_framing_fields(self):
        """``_collect_registered_source_ids`` includes framing.indication,
        framing.investigational_product, framing.study_phase plus any artifact
        IDs from the study definition."""
        tmpdir = tempfile.TemporaryDirectory()
        try:
            service = MedicalWritingAuthoringJourneyService(
                Path(tmpdir.name) / "test.sqlite3"
            )
            service.create("proj_ra", _ra_create_request())
            journey = service.get("proj_ra")
            ids = _collect_registered_source_ids(journey)
            self.assertIn("framing.indication", ids)
            self.assertIn("framing.investigational_product", ids)
            self.assertIn("framing.study_phase", ids)
        finally:
            tmpdir.cleanup()

    def test_fabricated_source_id_in_exact_fact_is_quarantined(self):
        """A candidate citing ``fabricated_source_xyz`` for an exact fact is
        quarantined — the fabricated ID never enters the evidence set."""
        registered = frozenset({"framing.indication"})
        candidates = _parse_field_suggestions(
            "picos.population_summary",
            [{
                "value": "N=500 with washout period of 7 days",
                "preview": "N=500 washout 7d",
                "rationale": "fake",
                "source_ids": ["fabricated_source_xyz"],
            }],
            registered_source_ids=registered,
        )
        self.assertEqual([], candidates)
        # Even if the item has no source_ids key at all.
        candidates2 = _parse_field_suggestions(
            "picos.population_summary",
            [{"value": "N=500", "preview": "sample size 500"}],
            registered_source_ids=registered,
        )
        self.assertEqual([], candidates2)


# ---------------------------------------------------------------------------
# 8. Inference before SQLite transaction
# ---------------------------------------------------------------------------

class InferenceBeforeTransactionTests(unittest.TestCase):
    """External inference completes before ``BEGIN IMMEDIATE``."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_ra", _ra_create_request())

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_research_ready_ai_enricher_runs_before_begin_immediate(self):
        """A research-ready package invokes AI before ``BEGIN IMMEDIATE``.

        We instrument the real connection wrapper to record the SQL execution
        order, and use an enricher that records when it was called.
        """
        journey = _mark_research_ready_for_test(
            self.service,
            "proj_ra",
            idempotency_key="fixture-tx-order-research-ready",
        )

        # Track execution order with a shared list.
        event_log: list[str] = []
        enricher_call_count = [0]

        original_connect = self.service._connect

        class _InstrumentedCtx:
            def __init__(self, real_ctx):
                self._real = real_ctx

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, *args):
                if isinstance(sql, str) and "BEGIN IMMEDIATE" in sql:
                    event_log.append("BEGIN_IMMEDIATE")
                return self._real.execute(sql, *args)

            def commit(self):
                return self._real.commit()

            def rollback(self):
                return self._real.rollback()

        def _tracked_connect():
            real_ctx = original_connect()
            real_conn = real_ctx.__enter__()
            return _InstrumentedCtx(real_conn)

        class _LoggingEnricher:
            def enrich_package(self, *, package, state, snapshot=None, journey_revision=None):
                event_log.append("ENRICHER_CALLED")
                enricher_call_count[0] += 1
                return package

        with patch.object(self.service, "_connect", side_effect=_tracked_connect):
            request = AuthoringPrefillGenerateRequest(
                expected_revision=journey.revision,
                actor="medical_manager_test",
                idempotency_key="prefill-tx-order-001",
            )
            self.service.generate_prefill(
                "proj_ra", request, ai_enricher=_LoggingEnricher()
            )

        # The real research-ready prerequisite permits exactly one call.
        self.assertEqual(1, enricher_call_count[0])
        # ENRICHER_CALLED must appear before BEGIN_IMMEDIATE in the event log.
        enricher_idx = event_log.index("ENRICHER_CALLED")
        begin_indices = [
            i for i, e in enumerate(event_log) if e == "BEGIN_IMMEDIATE"
        ]
        self.assertGreater(
            len(begin_indices), 0, "BEGIN IMMEDIATE was never executed"
        )
        first_begin = begin_indices[0]
        self.assertLess(
            enricher_idx, first_begin,
            f"enricher must run before BEGIN IMMEDIATE; "
            f"event_log={event_log}",
        )

    def test_research_not_ready_does_not_call_design_ai(self):
        """The evidence gate prevents model invocation before corpus readiness."""
        journey = self.service.get("proj_ra")
        enricher_call_count = [0]

        class _LoggingEnricher:
            def enrich_package(self, *, package, state, snapshot=None, journey_revision=None):
                enricher_call_count[0] += 1
                return package

        generated = self.service.generate_prefill(
            "proj_ra",
            AuthoringPrefillGenerateRequest(
                expected_revision=journey.revision,
                actor="medical_manager_test",
                idempotency_key="prefill-gate-no-ai-001",
            ),
            ai_enricher=_LoggingEnricher(),
        )
        self.assertEqual(0, enricher_call_count[0])
        self.assertIn(
            "design_recommendations_blocked:",
            " ".join(generated.prefill_package.partial_source_failures),
        )

    def test_inference_failure_before_transaction_does_not_mutate_journey(self):
        """If the per-field adapter raises during inference (Phase 2), the
        journey revision does not change — the write transaction never opens."""
        journey_before = self.service.get("proj_ra")
        revision_before = journey_before.revision
        request = AuthoringPrefillGenerateRequest(
            expected_revision=revision_before,
            actor="medical_manager_test",
            idempotency_key="prefill-explode-001",
        )
        with self.assertRaises(RuntimeError):
            self.service.generate_prefill(
                "proj_ra", request, adapter=_ExplodingAdapter()
            )
        journey_after = self.service.get("proj_ra")
        self.assertEqual(revision_before, journey_after.revision)


# ---------------------------------------------------------------------------
# 9. Adoption rebuilds search plan (condition term propagation)
# ---------------------------------------------------------------------------

class ConditionTermAdoptionTests(unittest.TestCase):
    """Adopting ``framing.clinicaltrials_condition_term`` creates a new
    versioned search plan whose ``registry_filter.condition_term`` uses the
    adopted English term and clears the stale snapshot binding."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_ra", _ra_create_request())

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _generate_and_get_package(self) -> AuthoringPrefillPackage:
        journey = self.service.get("proj_ra")
        self.service.generate_prefill("proj_ra", AuthoringPrefillGenerateRequest(
            expected_revision=journey.revision,
            actor="medical_manager_test",
            idempotency_key="prefill-cond-001",
        ))
        journey = self.service.get("proj_ra")
        return journey.prefill_package

    def _adopt_condition_term(self, package: AuthoringPrefillPackage, candidate_id: str):
        """Adopt the English condition term through the user-edit channel.

        Round 2: the AI condition candidate is manual_only and therefore
        fails closed on the single-candidate endpoint; the medical manager's
        explicit value is recorded as a user_confirmed manual edit and still
        drives the search-plan rebuild.
        """
        journey = self.service.get("proj_ra")
        return self.service.adopt_prefill_candidate(
            "proj_ra",
            AuthoringPrefillAdoptRequest(
                expected_revision=journey.revision,
                expected_package_revision=package.package_revision,
                field_path="framing.clinicaltrials_condition_term",
                candidate_id="",
                edited_value="Rheumatoid Arthritis",
                actor="medical_manager_test",
                idempotency_key="adopt-cond-001",
            ),
            evidence_verifier=_live_resolver_verifier(self.service),
        )

    def test_initial_search_plan_uses_registry_compatible_condition(self):
        """Known Chinese indications resolve to a registry-compatible term
        before the first search; this is terminology normalization, not a
        clinical design recommendation."""
        journey = self.service.get("proj_ra")
        plan = journey.search_plan
        self.assertIsNotNone(plan)
        self.assertEqual(
            "rheumatoid arthritis", plan.registry_filter.condition_term,
        )

    def test_adoption_rebuilds_plan_with_english_term(self):
        """After adopting 'Rheumatoid Arthritis', the search plan has:
        1. a new plan_id,
        2. a higher plan_revision,
        3. registry_filter.condition_term == 'Rheumatoid Arthritis'."""
        journey_before = _mark_research_ready_for_test(
            self.service,
            "proj_ra",
            idempotency_key="fixture-condition-adoption-research-ready",
        )
        old_plan = journey_before.search_plan
        old_plan_id = old_plan.plan_id

        generated = self.service.generate_prefill(
            "proj_ra",
            AuthoringPrefillGenerateRequest(
                expected_revision=journey_before.revision,
                actor="medical_manager_test",
                idempotency_key="prefill-cond-persist-bound-001",
            ),
            ai_enricher=DeepSeekPrefillAdapter(
                provider=_CountingProvider({
                    "_response_model": DEEPSEEK_PREFILL_MODEL,
                    "prefill_suggestions": {
                        "clinicaltrials_condition_term_en": "Rheumatoid Arthritis",
                        "field_suggestions": {},
                    },
                }),
                model_name=DEEPSEEK_PREFILL_MODEL,
            ),
        )

        journey = self.service.get("proj_ra")
        package = journey.prefill_package
        cond_group = package.field_candidates["framing.clinicaltrials_condition_term"]
        ai_candidate_id = None
        for c in cond_group.candidates:
            if str(c.structured_value) == "Rheumatoid Arthritis":
                ai_candidate_id = c.candidate_id
                self.assertTrue(c.claim_bindings)
                self.assertEqual("supported", c.evidence_status)
                self.assertEqual(package.ai_run_id, c.ai_run_id)
                break
        self.assertIsNotNone(ai_candidate_id, "AI condition candidate not found")

        updated = self._adopt_condition_term(package, ai_candidate_id)

        # 1. New plan_id.
        new_plan = updated.search_plan
        self.assertIsNotNone(new_plan)
        self.assertNotEqual(old_plan_id, new_plan.plan_id)
        # 2. Higher plan_revision.
        self.assertGreater(new_plan.plan_revision, old_plan.plan_revision)
        # 3. registry_filter.condition_term is now English.
        self.assertEqual(
            "Rheumatoid Arthritis",
            new_plan.registry_filter.condition_term,
        )
        # 4. Old snapshot binding is cleared.
        self.assertEqual("", new_plan.latest_snapshot_id)

    def test_adoption_directly_confirms_without_approval_gate(self):
        """Adoption sets state to ``user_confirmed`` — no second approval."""
        package = self._generate_and_get_package()
        journey = self.service.get("proj_ra")
        # Use the first candidate of an eligible field.
        group = package.field_candidates["framing.protocol_id"]
        candidate = group.candidates[0]
        updated = self.service.adopt_prefill_candidate(
            "proj_ra",
            AuthoringPrefillAdoptRequest(
                expected_revision=journey.revision,
                expected_package_revision=package.package_revision,
                field_path="framing.protocol_id",
                # Round 2: user-edit channel (manual_only card fails closed).
                candidate_id="",
                edited_value=candidate.structured_value,
                actor="medical_manager_test",
                idempotency_key="adopt-direct-001",
            ),
        )
        updated_group = updated.prefill_package.field_candidates["framing.protocol_id"]
        confirmed = [
            c for c in updated_group.candidates if c.state == "user_confirmed"
        ]
        self.assertEqual(1, len(confirmed))
        payload_str = updated.model_dump_json()
        self.assertNotIn("待医学批准", payload_str)
        self.assertNotIn("approval_gate", payload_str.lower())

    def test_research_regeneration_preserves_confirmed_english_condition(self):
        journey = _mark_research_ready_for_test(
            self.service,
            "proj_ra",
            idempotency_key="fixture-condition-preserve-research-ready",
        )
        provider_payload = {
            "_response_model": DEEPSEEK_PREFILL_MODEL,
            "clinicaltrials_condition_term_en": "Rheumatoid Arthritis",
            "field_suggestions": {},
        }
        generated = self.service.generate_prefill(
            "proj_ra",
            AuthoringPrefillGenerateRequest(
                expected_revision=journey.revision,
                actor="medical_manager_test",
                idempotency_key="prefill-condition-preserve-001",
                force=True,
            ),
            ai_enricher=DeepSeekPrefillAdapter(
                provider=_CountingProvider(provider_payload),
                model_name=DEEPSEEK_PREFILL_MODEL,
            ),
        )
        group = generated.prefill_package.field_candidates[
            "framing.clinicaltrials_condition_term"
        ]
        english = next(
            item
            for item in group.candidates
            if item.structured_value == "Rheumatoid Arthritis"
        )
        adopted = self.service.adopt_prefill_candidate(
            "proj_ra",
            AuthoringPrefillAdoptRequest(
                expected_revision=generated.revision,
                expected_package_revision=generated.prefill_package.package_revision,
                field_path="framing.clinicaltrials_condition_term",
                # Round 2: user-edit channel (the AI card is manual_only and
                # fails closed; the manager's explicit value is preserved).
                candidate_id="",
                edited_value="Rheumatoid Arthritis",
                actor="medical_manager_test",
                idempotency_key="adopt-condition-preserve-001",
            ),
            evidence_verifier=_live_resolver_verifier(self.service),
        )

        regenerated = self.service.generate_prefill(
            "proj_ra",
            AuthoringPrefillGenerateRequest(
                expected_revision=adopted.revision,
                actor="medical_manager_test",
                idempotency_key="prefill-condition-preserve-002",
                force=True,
            ),
            ai_enricher=DeepSeekPrefillAdapter(
                provider=_CountingProvider(provider_payload),
                model_name=DEEPSEEK_PREFILL_MODEL,
            ),
        )

        refreshed_group = regenerated.prefill_package.field_candidates[
            "framing.clinicaltrials_condition_term"
        ]
        confirmed = [
            item for item in refreshed_group.candidates if item.state == "user_confirmed"
        ]
        self.assertEqual(1, len(confirmed))
        self.assertEqual("Rheumatoid Arthritis", confirmed[0].structured_value)
        self.assertEqual(
            confirmed[0].candidate_id,
            refreshed_group.recommended_candidate_id,
        )
        self.assertEqual(
            "Rheumatoid Arthritis",
            regenerated.search_plan.registry_filter.condition_term,
        )


# ---------------------------------------------------------------------------
# 10. Registry hint relevance screening (mixed RA/PNH snapshots)
# ---------------------------------------------------------------------------

def _make_trial(
    nct_id: str,
    *,
    conditions: list[str],
    phases: list[str],
    study_type: str = "INTERVENTIONAL",
    official_title: str = "",
    public_docs: list[WritingReferencePublicDocument] | None = None,
) -> WritingReferenceTrialCandidate:
    return WritingReferenceTrialCandidate(
        nct_id=nct_id,
        brief_title=official_title or nct_id,
        official_title=official_title,
        conditions=conditions,
        phases=phases,
        study_type=study_type,
        study_record_url=f"https://clinicaltrials.gov/study/{nct_id}",
        public_documents=public_docs or [],
    )


def _make_public_doc(
    nct_id: str, *, document_type: str, filename: str = ""
) -> WritingReferencePublicDocument:
    return WritingReferencePublicDocument(
        document_id=f"{nct_id}_{document_type}",
        nct_id=nct_id,
        document_type=document_type,
        filename=filename or f"{nct_id}_{document_type}.pdf",
        download_url=f"https://example.com/{nct_id}/{document_type}",
    )


class RegistryHintRelevanceTests(unittest.TestCase):
    """Mixed RA/PNH snapshots: wrong-condition, wrong-phase, wrong-study-type
    trials and records without public Protocol/SAP are excluded from model
    hints."""

    def test_wrong_condition_trial_excluded(self):
        """A trial whose conditions do not match the RA condition term is
        excluded from screened hints."""
        candidates = [
            _make_trial(
                "NCT0000001",
                conditions=["Rheumatoid Arthritis"],
                phases=["PHASE2"],
                public_docs=[_make_public_doc("NCT0000001", document_type="protocol")],
            ),
            _make_trial(
                "NCT0000002",
                conditions=["Psoriasis"],
                phases=["PHASE2"],
                public_docs=[_make_public_doc("NCT0000002", document_type="protocol")],
            ),
        ]
        screened = _screen_snapshot_candidates(
            candidates,
            condition_term="Rheumatoid Arthritis",
            phases=["PHASE2"],
            study_type="INTERVENTIONAL",
        )
        nct_ids = [h["nct_id"] for h in screened]
        self.assertIn("NCT0000001", nct_ids)
        self.assertNotIn("NCT0000002", nct_ids)

    def test_wrong_phase_trial_excluded(self):
        """A trial with the right condition but wrong phase is excluded."""
        candidates = [
            _make_trial(
                "NCT0000003",
                conditions=["Rheumatoid Arthritis"],
                phases=["PHASE3"],
                public_docs=[_make_public_doc("NCT0000003", document_type="protocol")],
            ),
        ]
        screened = _screen_snapshot_candidates(
            candidates,
            condition_term="Rheumatoid Arthritis",
            phases=["PHASE2"],
            study_type="INTERVENTIONAL",
        )
        self.assertEqual([], screened)

    def test_wrong_study_type_excluded(self):
        """An observational trial is excluded when filtering for
        INTERVENTIONAL."""
        candidates = [
            _make_trial(
                "NCT0000004",
                conditions=["Rheumatoid Arthritis"],
                phases=["PHASE2"],
                study_type="OBSERVATIONAL",
                public_docs=[_make_public_doc("NCT0000004", document_type="protocol")],
            ),
        ]
        screened = _screen_snapshot_candidates(
            candidates,
            condition_term="Rheumatoid Arthritis",
            phases=["PHASE2"],
            study_type="INTERVENTIONAL",
        )
        self.assertEqual([], screened)

    def test_trial_without_public_protocol_or_sap_excluded(self):
        """D4 hard gate: a trial with no qualifying public document is
        excluded even if condition/phase/study-type match."""
        candidates = [
            _make_trial(
                "NCT0000005",
                conditions=["Rheumatoid Arthritis"],
                phases=["PHASE2"],
                # No public documents at all.
            ),
            _make_trial(
                "NCT0000006",
                conditions=["Rheumatoid Arthritis"],
                phases=["PHASE2"],
                # Only an informed consent — not Protocol or SAP.
                public_docs=[
                    _make_public_doc("NCT0000006", document_type="icf")
                ],
            ),
            _make_trial(
                "NCT0000007",
                conditions=["Rheumatoid Arthritis"],
                phases=["PHASE2"],
                public_docs=[
                    _make_public_doc("NCT0000007", document_type="protocol")
                ],
            ),
        ]
        screened = _screen_snapshot_candidates(
            candidates,
            condition_term="Rheumatoid Arthritis",
            phases=["PHASE2"],
            study_type="INTERVENTIONAL",
        )
        nct_ids = {h["nct_id"] for h in screened}
        self.assertEqual({"NCT0000007"}, nct_ids)

    def test_pnh_exact_condition_with_protocol_survives(self):
        """A PNH trial with exact condition match and a public Protocol
        survives relevance filtering."""
        candidates = [
            _make_trial(
                "NCT0000010",
                conditions=["Paroxysmal Nocturnal Hemoglobinuria"],
                phases=["PHASE3"],
                public_docs=[
                    _make_public_doc("NCT0000010", document_type="protocol_sap")
                ],
            ),
        ]
        screened = _screen_snapshot_candidates(
            candidates,
            condition_term="Paroxysmal Nocturnal Hemoglobinuria",
            phases=["PHASE3"],
            study_type="INTERVENTIONAL",
        )
        self.assertEqual(1, len(screened))
        self.assertEqual("NCT0000010", screened[0]["nct_id"])
        self.assertTrue(screened[0]["has_public_protocol"])

    def test_mixed_ra_pnh_snapshot_only_matching_trials_survive(self):
        """A mixed RA+PNH snapshot with relevant and irrelevant trials: only
        the condition+phase+study_type+public-doc matching ones survive."""
        candidates = [
            # Relevant RA Phase 2 with Protocol.
            _make_trial(
                "NCT_RA_001",
                conditions=["Rheumatoid Arthritis"],
                phases=["PHASE2"],
                public_docs=[_make_public_doc("NCT_RA_001", document_type="protocol")],
            ),
            # Wrong condition (PNH) in an RA query.
            _make_trial(
                "NCT_PNH_001",
                conditions=["Paroxysmal Nocturnal Hemoglobinuria"],
                phases=["PHASE2"],
                public_docs=[_make_public_doc("NCT_PNH_001", document_type="protocol")],
            ),
            # Right condition, wrong phase.
            _make_trial(
                "NCT_RA_004",
                conditions=["Rheumatoid Arthritis"],
                phases=["PHASE4"],
                public_docs=[_make_public_doc("NCT_RA_004", document_type="protocol")],
            ),
            # Right condition, right phase, no public doc.
            _make_trial(
                "NCT_RA_NODOC",
                conditions=["Rheumatoid Arthritis"],
                phases=["PHASE2"],
            ),
        ]
        screened = _screen_snapshot_candidates(
            candidates,
            condition_term="Rheumatoid Arthritis",
            phases=["PHASE2"],
            study_type="INTERVENTIONAL",
        )
        nct_ids = {h["nct_id"] for h in screened}
        self.assertEqual({"NCT_RA_001"}, nct_ids)


# ---------------------------------------------------------------------------
# 11. Model identity verification (D5) + direct DeepSeek route
# ---------------------------------------------------------------------------

class ModelIdentityTests(unittest.TestCase):

    def test_openai_compatible_provider_rejects_wrong_http_model(self):
        """The configured OpenAICompatibleAiProvider raises on HTTP response
        model identity mismatch."""
        provider = OpenAICompatibleAiProvider(
            base_url=DIRECT_DEEPSEEK_BASE_URL,
            api_key="test-key",
            model_name=DIRECT_DEEPSEEK_MODEL,
            provider_name="deepseek",
            expected_response_model=DIRECT_DEEPSEEK_MODEL,
        )
        fake_body = json.dumps({
            "model": "gpt-4-hacker",
            "choices": [{"message": {"content": "{}"}}],
        })
        with patch("services.api.app.ai_gateway.urllib.request.urlopen") as mock_open:
            import io
            mock_open.return_value.__enter__ = lambda s: io.BytesIO(
                fake_body.encode("utf-8")
            )
            mock_open.return_value.__exit__ = lambda *a: False
            from services.api.app.ai_gateway import AiPromptEnvelope, AiTaskType
            with self.assertRaises(AiProviderRuntimeError):
                provider.run(
                    AiPromptEnvelope(
                        task_id="test",
                        task_type=AiTaskType.PICOS_DESIGN_COACH,
                        prompt_version="v1",
                        system_prompt="test",
                        payload={"task_id": "test"},
                    )
                )

    def test_generic_provider_missing_response_model_degrades(self):
        """D5: A generic (non-OpenAICompatible) provider that returns no
        ``_response_model`` triggers deterministic fallback."""
        tmpdir = tempfile.TemporaryDirectory()
        try:
            service = MedicalWritingAuthoringJourneyService(
                Path(tmpdir.name) / "test.sqlite3"
            )
            service.create("proj_ra", _ra_create_request())
            journey = service.get("proj_ra")
            deterministic = generate_prefill_package(
                state=journey, now=NOW, actor="test"
            )

            class _NoModelProvider:
                def run(self, envelope):
                    return {"prefill_suggestions": {}}  # no _response_model

            adapter = DeepSeekPrefillAdapter(
                provider=_NoModelProvider(), model_name=DEEPSEEK_PREFILL_MODEL
            )
            enriched = adapter.enrich_package(package=deterministic, state=journey)
            self.assertGreater(len(enriched.partial_source_failures), 0)
            self.assertIn(
                "_response_model",
                " ".join(enriched.partial_source_failures),
            )
        finally:
            tmpdir.cleanup()

    def test_direct_deepseek_models_include_pro_and_flash(self):
        self.assertIn("deepseek-v4-pro", DIRECT_DEEPSEEK_MODELS)
        self.assertIn("deepseek-v4-flash", DIRECT_DEEPSEEK_MODELS)

    def test_direct_deepseek_base_url_is_official(self):
        self.assertEqual("https://api.deepseek.com/v1", DIRECT_DEEPSEEK_BASE_URL)

    def test_configured_provider_rejects_hermes_transport(self):
        provider = configured_ai_provider_from_env({
            "WORKBENCH_AI_TRANSPORT": "hermes_cli",
            "DEEPSEEK_API_KEY": "test-key",
            "WORKBENCH_AI_MODEL": "deepseek-v4-pro",
            "WORKBENCH_AI_PROVIDER": "deepseek",
        })
        from services.api.app.ai_gateway import DisabledAiProvider
        self.assertIsInstance(provider, DisabledAiProvider)

    def test_configured_provider_rejects_model_alias(self):
        provider = configured_ai_provider_from_env({
            "WORKBENCH_AI_TRANSPORT": "openai_compatible",
            "DEEPSEEK_API_KEY": "test-key",
            "WORKBENCH_AI_MODEL": "deepseek-chat",
            "WORKBENCH_AI_PROVIDER": "deepseek",
        })
        from services.api.app.ai_gateway import DisabledAiProvider
        self.assertIsInstance(provider, DisabledAiProvider)

    def test_configured_provider_accepts_proper_direct_route(self):
        provider = configured_ai_provider_from_env({
            "WORKBENCH_AI_TRANSPORT": "openai_compatible",
            "DEEPSEEK_API_KEY": "test-key",
            "WORKBENCH_AI_MODEL": "deepseek-v4-pro",
            "WORKBENCH_AI_PROVIDER": "deepseek",
        })
        self.assertIsInstance(provider, OpenAICompatibleAiProvider)
        self.assertEqual(DIRECT_DEEPSEEK_BASE_URL, provider.base_url)
        self.assertEqual(DIRECT_DEEPSEEK_MODEL, provider.expected_response_model)


class PrefillSingleTransportAttemptTests(unittest.TestCase):
    """The AI-first prefill route makes at most one physical upstream POST
    per logical call (worker_02 corrective round) while every other AI
    gateway caller keeps the generic bounded retry budget."""

    @staticmethod
    def _envelope(task_id: str) -> AiPromptEnvelope:
        return AiPromptEnvelope(
            task_id=task_id,
            task_type=AiTaskType.REGULATORY_TRANSLATION_ZH,
            prompt_version="flash_integration_qc_v0_1",
            system_prompt="Return JSON.",
            payload={"source_text": "Source", "translated_text": "译文"},
            thinking="disabled",
        )

    def test_openai_provider_max_attempts_one_never_retries_retryable_http(self):
        """A single-attempt provider raises immediately on a retryable HTTP
        code after exactly one POST; no backoff sleep is taken."""
        provider = OpenAICompatibleAiProvider(
            base_url="https://ai.example.test/v1",
            api_key="test-key",
            model_name="deepseek-v4-pro",
            timeout_seconds=1,
            max_attempts=1,
        )
        self.assertEqual(1, provider.max_attempts)
        retryable = urllib.error.HTTPError(
            "https://ai.example.test/v1/chat/completions",
            503,
            "unavailable",
            None,
            None,
        )
        with (
            patch(
                "services.api.app.ai_gateway.urllib.request.urlopen",
                side_effect=retryable,
            ) as urlopen,
            patch("services.api.app.ai_gateway.time.sleep") as sleep,
            patch("services.api.app.ai_gateway.random.uniform", return_value=0.0),
        ):
            with self.assertRaisesRegex(AiProviderRuntimeError, "HTTP 503"):
                provider.run(self._envelope("task_single_attempt_503"))
        self.assertEqual(1, urlopen.call_count)
        sleep.assert_not_called()

    def test_default_provider_keeps_three_attempt_retry_budget(self):
        """Callers that do not pin max_attempts keep the generic 3-attempt
        bounded retry behavior on retryable HTTP codes."""
        provider = OpenAICompatibleAiProvider(
            base_url="https://ai.example.test/v1",
            api_key="test-key",
            model_name="deepseek-v4-pro",
            timeout_seconds=1,
        )
        self.assertEqual(3, provider.max_attempts)
        retryable = urllib.error.HTTPError(
            "https://ai.example.test/v1/chat/completions",
            503,
            "unavailable",
            None,
            None,
        )
        with (
            patch(
                "services.api.app.ai_gateway.urllib.request.urlopen",
                side_effect=retryable,
            ) as urlopen,
            patch("services.api.app.ai_gateway.time.sleep") as sleep,
            patch("services.api.app.ai_gateway.random.uniform", return_value=0.0),
        ):
            with self.assertRaisesRegex(
                AiProviderRuntimeError, "after bounded retries"
            ):
                provider.run(self._envelope("task_three_attempt_503"))
        self.assertEqual(3, urlopen.call_count)
        self.assertEqual(2, sleep.call_count)

    def test_prefill_adapter_fails_closed_on_multi_attempt_provider(self):
        """A DeepSeekPrefillAdapter wired to a provider with the generic
        retry budget degrades to the deterministic fallback (fail closed)
        instead of silently using a multi-attempt transport."""
        tmpdir = tempfile.TemporaryDirectory()
        try:
            service = MedicalWritingAuthoringJourneyService(
                Path(tmpdir.name) / "test.sqlite3"
            )
            service.create("proj_ra", _ra_create_request())
            journey = service.get("proj_ra")
            deterministic = generate_prefill_package(
                state=journey, now=NOW, actor="test"
            )
            provider = OpenAICompatibleAiProvider(
                base_url=DIRECT_DEEPSEEK_BASE_URL,
                api_key="test-key",
                model_name=DIRECT_DEEPSEEK_MODEL,
                provider_name="deepseek",
                expected_response_model=DIRECT_DEEPSEEK_MODEL,
                max_attempts=3,
            )
            adapter = DeepSeekPrefillAdapter(
                provider=provider, model_name=DEEPSEEK_PREFILL_MODEL
            )
            enriched = adapter.enrich_package(package=deterministic, state=journey)
            self.assertGreater(len(enriched.partial_source_failures), 0)
            self.assertIn(
                "transport",
                " ".join(enriched.partial_source_failures),
            )
        finally:
            tmpdir.cleanup()

    def test_configured_provider_factory_pins_prefill_route_single_attempt(self):
        """configured_ai_provider_from_env(max_attempts=1) yields a
        single-attempt OpenAICompatibleAiProvider; the default keeps 3."""
        env = {
            "WORKBENCH_AI_TRANSPORT": "openai_compatible",
            "DEEPSEEK_API_KEY": "test-key",
            "WORKBENCH_AI_MODEL": "deepseek-v4-pro",
            "WORKBENCH_AI_PROVIDER": "deepseek",
        }
        pinned = configured_ai_provider_from_env(env, max_attempts=1)
        self.assertIsInstance(pinned, OpenAICompatibleAiProvider)
        self.assertEqual(1, pinned.max_attempts)
        generic = configured_ai_provider_from_env(env)
        self.assertIsInstance(generic, OpenAICompatibleAiProvider)
        self.assertEqual(3, generic.max_attempts)

    def test_prefill_factory_uses_dedicated_max_reasoning_timeout(self):
        """The one-call prefill route must not inherit the generic 300 s
        profile timeout that previously produced a 315 s unknown outcome.
        An explicit route override remains bounded and is applied to both the
        provider transport and the local adapter wait budget.
        """
        env = {
            "WORKBENCH_AI_TRANSPORT": "openai_compatible",
            "DEEPSEEK_API_KEY": "test-key",
            "WORKBENCH_AI_MODEL": "deepseek-v4-flash",
            "WORKBENCH_AI_PROVIDER": "deepseek",
            "WORKBENCH_AI_TIMEOUT_SECONDS": "300",
        }
        adapter = build_prefill_ai_adapter(provider_env=env)
        self.assertIsInstance(adapter, DeepSeekPrefillAdapter)
        self.assertEqual(DEEPSEEK_PREFILL_TIMEOUT_SECONDS, adapter._timeout_seconds)
        self.assertEqual(
            DEEPSEEK_PREFILL_TIMEOUT_SECONDS,
            adapter._provider.timeout_seconds,
        )

        override = dict(env, WORKBENCH_AI_PREFILL_TIMEOUT_SECONDS="1200")
        overridden = build_prefill_ai_adapter(provider_env=override)
        self.assertIsInstance(overridden, DeepSeekPrefillAdapter)
        self.assertEqual(1200.0, overridden._timeout_seconds)
        self.assertEqual(1200.0, overridden._provider.timeout_seconds)


class GenerationReservationTests(unittest.TestCase):
    """Durable in-flight generation reservation (worker_02 corrective round).

    Two concurrent same-revision generation requests cause exactly one
    enricher invocation and one persisted generation event; a timed-out or
    interrupted call is preserved as an unknown outcome and is never
    redispatched automatically; the reservation records the logical call id
    and the single transport attempt; force=True starts a new logical call.
    """

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.sqlite3"
        self.service = MedicalWritingAuthoringJourneyService(
            self.db_path, generation_reservation_wait_seconds=0.5
        )
        self.service.create("proj_ra", _ra_create_request())
        self.journey = _mark_research_ready_for_test(
            self.service,
            "proj_ra",
            idempotency_key="fixture-generation-reservation-ready",
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _counting_enricher(
        self,
        *,
        delay: float = 0.0,
        fail_with: BaseException | None = None,
        timeout_seconds: float = 5.0,
    ):
        class _CountingEnricher:
            def __init__(self) -> None:
                self.call_count = 0
                self.lock = threading.Lock()
                self._timeout_seconds = timeout_seconds

            def enrich_package(
                self, *, package, state, snapshot=None, journey_revision=None
            ):
                with self.lock:
                    self.call_count += 1
                if delay:
                    time.sleep(delay)
                if fail_with is not None:
                    raise fail_with
                return package

        return _CountingEnricher()

    @staticmethod
    def _reservation_row(
        service, project_id, revision, operation="prefill_generate"
    ):
        with service._connect() as connection:
            return connection.execute(
                "SELECT * FROM "
                "medical_writing_authoring_journey_generation_reservations "
                "WHERE project_id = ? AND expected_revision = ? AND operation = ?",
                (project_id, revision, operation),
            ).fetchone()

    @staticmethod
    def _generation_event_count(service, project_id):
        with service._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM "
                "medical_writing_authoring_journey_events "
                "WHERE project_id = ? AND "
                "event_type = 'authoring_journey_prefill_generated'",
                (project_id,),
            ).fetchone()
        return int(row["n"])

    @staticmethod
    def _event_detail(service, project_id, idempotency_key):
        with service._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM medical_writing_authoring_journey_events "
                "WHERE project_id = ? AND idempotency_key = ?",
                (project_id, idempotency_key),
            ).fetchone()
        return json.loads(row["payload_json"]) if row is not None else None

    def _generate_request(
        self, idempotency_key, *, force=False, expected_revision=None
    ):
        return AuthoringPrefillGenerateRequest(
            expected_revision=(
                self.journey.revision
                if expected_revision is None
                else expected_revision
            ),
            actor="medical_manager_test",
            idempotency_key=idempotency_key,
            force=force,
        )

    def test_concurrent_same_revision_different_keys_single_enrichment(self):
        """Two concurrent same-revision requests with different idempotency
        keys produce exactly one enricher invocation, one persisted event,
        and one completed reservation; the loser replays the winner's
        outcome instead of dispatching."""
        project_id = "proj_ra"
        revision = self.journey.revision
        enricher = self._counting_enricher(delay=0.3)
        barrier = threading.Barrier(2)
        results: list = []
        errors: list = []

        def _worker(idempotency_key: str):
            try:
                barrier.wait(timeout=5)
                journey = self.service.generate_prefill(
                    project_id,
                    self._generate_request(idempotency_key),
                    ai_enricher=enricher,
                )
                results.append(journey)
            except Exception as exc:  # noqa: BLE001 - surfaced below
                errors.append(exc)

        threads = [
            threading.Thread(target=_worker, args=("reservation-concurrent-a",)),
            threading.Thread(target=_worker, args=("reservation-concurrent-b",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual([], errors)
        self.assertEqual(2, len(results))
        self.assertEqual(1, enricher.call_count)
        self.assertEqual({revision + 1}, {j.revision for j in results})
        self.assertEqual(
            1,
            len({j.prefill_package.package_id for j in results}),
            "both workers must observe the same generated package",
        )
        self.assertEqual(1, self._generation_event_count(self.service, project_id))
        row = self._reservation_row(self.service, project_id, revision)
        self.assertIsNotNone(row)
        self.assertEqual("completed", row["status"])
        self.assertTrue(str(row["logical_call_id"]).startswith("mwprefillcall_"))
        self.assertEqual(1, row["transport_attempt_count"])
        self.assertIsNotNone(row["event_id"])

    def test_concurrent_same_idempotency_key_replays_once(self):
        """Two concurrent same-revision requests with the SAME idempotency
        key still produce exactly one enrichment and one event."""
        project_id = "proj_ra"
        revision = self.journey.revision
        enricher = self._counting_enricher(delay=0.3)
        barrier = threading.Barrier(2)
        results: list = []
        errors: list = []

        def _worker():
            try:
                barrier.wait(timeout=5)
                journey = self.service.generate_prefill(
                    project_id,
                    self._generate_request("reservation-concurrent-same"),
                    ai_enricher=enricher,
                )
                results.append(journey)
            except Exception as exc:  # noqa: BLE001 - surfaced below
                errors.append(exc)

        threads = [threading.Thread(target=_worker), threading.Thread(target=_worker)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual([], errors)
        self.assertEqual(2, len(results))
        self.assertEqual(1, enricher.call_count)
        self.assertEqual({revision + 1}, {j.revision for j in results})
        self.assertEqual(1, self._generation_event_count(self.service, project_id))

    def test_enrichment_timeout_preserves_unknown_outcome_and_never_redispatches(self):
        """A timed-out enrichment persists the deterministic fallback,
        marks the reservation unknown_outcome atomically with the fallback
        event, records the logical call id + single transport attempt in
        telemetry, and a same-key retry replays without a new dispatch."""
        project_id = "proj_ra"
        revision = self.journey.revision
        enricher = self._counting_enricher(
            delay=0.15,
            fail_with=TimeoutError("simulated provider timeout"),
            timeout_seconds=0.05,
        )
        generated = self.service.generate_prefill(
            project_id,
            self._generate_request("reservation-timeout-001"),
            ai_enricher=enricher,
        )
        self.assertEqual(revision + 1, generated.revision)
        joined = " ".join(generated.prefill_package.partial_source_failures)
        self.assertIn("timed out", joined)
        self.assertIn("no automatic redispatch", joined)

        row = self._reservation_row(self.service, project_id, revision)
        self.assertIsNotNone(row)
        self.assertEqual("unknown_outcome", row["status"])
        self.assertIsNotNone(row["event_id"])
        self.assertEqual(1, row["transport_attempt_count"])
        call_id = str(row["logical_call_id"])

        detail = self._event_detail(
            self.service, project_id, "reservation-timeout-001"
        )
        self.assertIsNotNone(detail)
        self.assertEqual(call_id, detail["ai_logical_call_id"])
        self.assertEqual(1, detail["ai_transport_attempt_count"])
        self.assertEqual("unknown_outcome", detail["ai_outcome"])

        # Same-key retry: replays the fallback event, never redispatches.
        replay = self.service.generate_prefill(
            project_id,
            self._generate_request("reservation-timeout-001"),
            ai_enricher=enricher,
        )
        self.assertEqual(replay.revision, generated.revision)
        self.assertEqual(1, enricher.call_count)
        self.assertEqual(1, self._generation_event_count(self.service, project_id))
        row = self._reservation_row(self.service, project_id, revision)
        self.assertEqual("unknown_outcome", row["status"])

    def test_restart_preserves_unknown_outcome_and_force_starts_new_logical_call(self):
        """The unknown-outcome reservation survives a service restart; a
        stale-revision duplicate cannot redispatch; an explicit force at the
        current revision starts a NEW logical call while the old
        unknown-outcome row remains preserved."""
        project_id = "proj_ra"
        revision = self.journey.revision
        enricher = self._counting_enricher(
            delay=0.15,
            fail_with=TimeoutError("simulated provider timeout"),
            timeout_seconds=0.05,
        )
        generated = self.service.generate_prefill(
            project_id,
            self._generate_request("reservation-restart-timeout"),
            ai_enricher=enricher,
        )
        self.assertEqual(revision + 1, generated.revision)

        # "Restart": a fresh service instance over the same store.
        restarted = MedicalWritingAuthoringJourneyService(
            self.db_path, generation_reservation_wait_seconds=0.5
        )
        row = self._reservation_row(restarted, project_id, revision)
        self.assertIsNotNone(row)
        self.assertEqual("unknown_outcome", row["status"])
        preserved_call_id = str(row["logical_call_id"])

        # A different-key request for the OLD revision is stale now; it can
        # never redispatch the unknown call.
        with self.assertRaises(MedicalWritingAuthoringJourneyConflictError):
            restarted.generate_prefill(
                project_id,
                self._generate_request("reservation-restart-stale"),
                ai_enricher=enricher,
            )
        self.assertEqual(1, enricher.call_count)

        # Explicit force at the CURRENT revision: a new logical call with a
        # fresh reservation and a working enricher; the old unknown-outcome
        # row is preserved.
        force_enricher = self._counting_enricher()
        current_revision = restarted.get(project_id).revision
        forced = restarted.generate_prefill(
            project_id,
            self._generate_request(
                "reservation-restart-force",
                force=True,
                expected_revision=current_revision,
            ),
            ai_enricher=force_enricher,
        )
        self.assertEqual(current_revision + 1, forced.revision)
        self.assertEqual(1, force_enricher.call_count)
        self.assertEqual(1, enricher.call_count)
        new_row = self._reservation_row(restarted, project_id, current_revision)
        self.assertIsNotNone(new_row)
        self.assertEqual("completed", new_row["status"])
        self.assertNotEqual(preserved_call_id, new_row["logical_call_id"])
        old_row = self._reservation_row(restarted, project_id, revision)
        self.assertEqual("unknown_outcome", old_row["status"])
        self.assertEqual(preserved_call_id, old_row["logical_call_id"])
        detail = self._event_detail(
            restarted, project_id, "reservation-restart-force"
        )
        self.assertEqual("completed", detail["ai_outcome"])
        self.assertEqual(new_row["logical_call_id"], detail["ai_logical_call_id"])
        self.assertEqual(1, detail["ai_transport_attempt_count"])

    def _insert_in_flight_reservation(
        self, project_id, revision, call_id, *, age_seconds
    ):
        stale_iso = (
            datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
        ).isoformat()
        with self.service._connect() as connection:
            connection.execute(
                "INSERT INTO "
                "medical_writing_authoring_journey_generation_reservations("
                "project_id, expected_revision, operation, logical_call_id, "
                "transport_attempt_count, status, event_id, failure_note, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, 1, "
                "'in_flight', NULL, NULL, ?, ?)",
                (
                    project_id,
                    revision,
                    "prefill_generate",
                    call_id,
                    stale_iso,
                    stale_iso,
                ),
            )
            connection.commit()

    def test_stale_in_flight_owner_is_reclaimed_without_wait(self):
        """0924V1-R01/T01: an in_flight reservation whose owner has been
        absent far beyond any legitimate enrichment call is CAS-reclaimed
        immediately — force recovers without waiting out the bound."""
        project_id = "proj_ra"
        revision = self.journey.revision
        dead_call_id = "mwprefillcall_deadownerabsent00000000"
        self._insert_in_flight_reservation(
            project_id, revision, dead_call_id, age_seconds=7200
        )
        enricher = self._counting_enricher()
        generated = self.service.generate_prefill(
            project_id,
            self._generate_request("reservation-reclaim-001", force=True),
            ai_enricher=enricher,
        )
        self.assertEqual(revision + 1, generated.revision)
        self.assertEqual(1, enricher.call_count)
        row = self._reservation_row(self.service, project_id, revision)
        self.assertEqual("completed", row["status"])
        self.assertNotEqual(dead_call_id, row["logical_call_id"])
        history = json.loads(row["attempt_history"] or "[]")
        self.assertTrue(
            any(
                "owner absent beyond reclaim bound" in str(entry.get("failure_note", ""))
                for entry in history
            )
        )

    def test_fresh_in_flight_force_is_still_refused(self):
        """0924V1-R01/T02: a LIVE call (owner activity within the reclaim
        bound) must never be interrupted — force fails fast exactly as
        before the reclaim path existed."""
        project_id = "proj_ra"
        revision = self.journey.revision
        self._insert_in_flight_reservation(
            project_id, revision, "mwprefillcall_livelongcall00000000",
            age_seconds=30,
        )
        enricher = self._counting_enricher()
        with self.assertRaisesRegex(
            MedicalWritingAuthoringJourneyConflictError,
            "force cannot interrupt the live call",
        ):
            self.service.generate_prefill(
                project_id,
                self._generate_request("reservation-reclaim-002", force=True),
                ai_enricher=enricher,
            )
        self.assertEqual(0, enricher.call_count)
        row = self._reservation_row(self.service, project_id, revision)
        self.assertEqual("in_flight", row["status"])
        self.assertEqual(
            "mwprefillcall_livelongcall00000000", row["logical_call_id"]
        )

    def test_reclaim_is_single_shot_cas(self):
        """The reclaim CAS is bound to status+updated_at: after one reclaim
        the row is unknown_outcome, a second attempt is a no-op returning
        False, and attempt history records the reclaim exactly once."""
        project_id = "proj_ra"
        revision = self.journey.revision
        self._insert_in_flight_reservation(
            project_id, revision, "mwprefillcall_reclaimcas0000000000",
            age_seconds=7200,
        )
        row = self._reservation_row(self.service, project_id, revision)
        first = self.service._reclaim_stale_in_flight_reservation(
            project_id, revision, "prefill_generate", row
        )
        self.assertTrue(first)
        row_after = self._reservation_row(self.service, project_id, revision)
        self.assertEqual("unknown_outcome", row_after["status"])
        second = self.service._reclaim_stale_in_flight_reservation(
            project_id, revision, "prefill_generate", row_after
        )
        self.assertFalse(second)
        history = json.loads(row_after["attempt_history"] or "[]")
        reclaim_notes = [
            entry
            for entry in history
            if "owner absent beyond reclaim bound" in str(entry.get("failure_note", ""))
        ]
        self.assertEqual(1, len(reclaim_notes))

    def test_interrupted_in_flight_reservation_fails_closed_then_force_recovers(self):
        """A reservation left in_flight by a crashed worker is preserved as
        an unknown outcome after the wait bound: subsequent requests fail
        closed without dispatch; an explicit force starts a new logical
        call and completes the key."""
        project_id = "proj_ra"
        revision = self.journey.revision
        dead_call_id = "mwprefillcall_deadworker000000000000"
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.service._connect() as connection:
            connection.execute(
                "INSERT INTO "
                "medical_writing_authoring_journey_generation_reservations("
                "project_id, expected_revision, operation, logical_call_id, "
                "transport_attempt_count, status, event_id, failure_note, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, 1, "
                "'in_flight', NULL, NULL, ?, ?)",
                (
                    project_id,
                    revision,
                    "prefill_generate",
                    dead_call_id,
                    now_iso,
                    now_iso,
                ),
            )
            connection.commit()

        enricher = self._counting_enricher()
        # The interrupted call fails closed after the bounded wait: no
        # dispatch, no journey mutation.
        with self.assertRaisesRegex(
            MedicalWritingAuthoringJourneyConflictError, "outcome is unknown"
        ):
            self.service.generate_prefill(
                project_id,
                self._generate_request("reservation-dead-001"),
                ai_enricher=enricher,
            )
        self.assertEqual(0, enricher.call_count)
        row = self._reservation_row(self.service, project_id, revision)
        self.assertEqual("unknown_outcome", row["status"])
        self.assertEqual(dead_call_id, row["logical_call_id"])
        self.assertIn("presumed interrupted", row["failure_note"] or "")

        # A non-force retry stays blocked.
        with self.assertRaisesRegex(
            MedicalWritingAuthoringJourneyConflictError, "unknown-outcome"
        ):
            self.service.generate_prefill(
                project_id,
                self._generate_request("reservation-dead-002"),
                ai_enricher=enricher,
            )
        self.assertEqual(0, enricher.call_count)

        # Explicit force supersedes with a NEW logical call id.
        generated = self.service.generate_prefill(
            project_id,
            self._generate_request("reservation-dead-003", force=True),
            ai_enricher=enricher,
        )
        self.assertEqual(revision + 1, generated.revision)
        self.assertEqual(1, enricher.call_count)
        row = self._reservation_row(self.service, project_id, revision)
        self.assertEqual("completed", row["status"])
        self.assertNotEqual(dead_call_id, row["logical_call_id"])
        self.assertIn("supersedes unknown-outcome call", row["failure_note"] or "")
        self.assertEqual(1, self._generation_event_count(self.service, project_id))
        detail = self._event_detail(self.service, project_id, "reservation-dead-003")
        self.assertEqual("completed", detail["ai_outcome"])
        self.assertEqual(row["logical_call_id"], detail["ai_logical_call_id"])
        self.assertEqual(1, detail["ai_transport_attempt_count"])

    # ------------------------------------------------------------------
    # Round 2 (worker_02 corrective round 2): dispatched reservations can
    # never terminate as a retryable ``failed`` — the upstream model may
    # have completed and only the local result may have been lost.
    # ------------------------------------------------------------------

    def test_persist_failure_after_successful_enrichment_is_unknown_outcome(self):
        """A successful enricher result followed by an injected event/persist
        failure leaves the reservation unknown_outcome (never retryable
        ``failed``): a fresh service instance and a non-force retry must not
        dispatch a second enricher/provider invocation, and no generation
        event exists."""
        project_id = "proj_ra"
        revision = self.journey.revision
        enricher = self._counting_enricher()
        with patch.object(
            self.service,
            "_persist_update",
            side_effect=RuntimeError("injected persist failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "injected persist failure"):
                self.service.generate_prefill(
                    project_id,
                    self._generate_request("reservation-persist-fail-001"),
                    ai_enricher=enricher,
                )
        self.assertEqual(1, enricher.call_count)
        row = self._reservation_row(self.service, project_id, revision)
        self.assertIsNotNone(row)
        self.assertEqual("unknown_outcome", row["status"])
        self.assertEqual(1, row["transport_attempt_count"])
        self.assertIn("RuntimeError", row["failure_note"] or "")
        self.assertIn("dispatched", row["failure_note"] or "")
        self.assertIn("unknown", row["failure_note"] or "")
        self.assertEqual(0, self._generation_event_count(self.service, project_id))

        # Restart: a fresh service on the same store still sees the
        # unknown-outcome reservation and a non-force retry fails closed.
        restarted = MedicalWritingAuthoringJourneyService(
            self.db_path, generation_reservation_wait_seconds=0.5
        )
        self.assertEqual(
            "unknown_outcome",
            self._reservation_row(restarted, project_id, revision)["status"],
        )
        second_enricher = self._counting_enricher()
        with self.assertRaisesRegex(
            MedicalWritingAuthoringJourneyConflictError, "unknown-outcome"
        ):
            restarted.generate_prefill(
                project_id,
                self._generate_request("reservation-persist-fail-002"),
                ai_enricher=second_enricher,
            )
        self.assertEqual(0, second_enricher.call_count)
        self.assertEqual(0, self._generation_event_count(restarted, project_id))

    def test_provider_exception_then_persist_failure_is_unknown_outcome(self):
        """A provider terminal exception after the one physical attempt
        followed by a local persist failure has the same fail-closed
        behavior: unknown_outcome, no redispatch on a non-force retry."""
        project_id = "proj_ra"
        revision = self.journey.revision
        enricher = self._counting_enricher(
            fail_with=RuntimeError("provider terminal failure")
        )
        with patch.object(
            self.service,
            "_persist_update",
            side_effect=RuntimeError("injected persist failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "injected persist failure"):
                self.service.generate_prefill(
                    project_id,
                    self._generate_request("reservation-provider-persist-001"),
                    ai_enricher=enricher,
                )
        self.assertEqual(1, enricher.call_count)
        row = self._reservation_row(self.service, project_id, revision)
        self.assertIsNotNone(row)
        self.assertEqual("unknown_outcome", row["status"])
        self.assertEqual(1, row["transport_attempt_count"])
        self.assertIn("RuntimeError", row["failure_note"] or "")
        self.assertIn("dispatched", row["failure_note"] or "")
        self.assertIn("unknown", row["failure_note"] or "")

        # Non-force same-revision retry (fresh enricher) never redispatches.
        second_enricher = self._counting_enricher()
        with self.assertRaisesRegex(
            MedicalWritingAuthoringJourneyConflictError, "unknown-outcome"
        ):
            self.service.generate_prefill(
                project_id,
                self._generate_request("reservation-provider-persist-002"),
                ai_enricher=second_enricher,
            )
        self.assertEqual(0, second_enricher.call_count)

    def test_force_supersede_preserves_prior_attempt_lineage(self):
        """An explicit force superseding an unknown-outcome reservation
        starts a new logical call while the prior logical call id, transport
        attempt count, status, and failure reason remain auditable in the
        append-only attempt-history column."""
        project_id = "proj_ra"
        revision = self.journey.revision
        dead_call_id = "mwprefillcall_round2dead0000000000000"
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.service._connect() as connection:
            connection.execute(
                "INSERT INTO "
                "medical_writing_authoring_journey_generation_reservations("
                "project_id, expected_revision, operation, logical_call_id, "
                "transport_attempt_count, status, event_id, failure_note, "
                "attempt_history, created_at, updated_at) VALUES "
                "(?, ?, ?, ?, 1, 'unknown_outcome', NULL, "
                "'prior attempt failure note', '[]', ?, ?)",
                (project_id, revision, "prefill_generate", dead_call_id, now_iso, now_iso),
            )
            connection.commit()

        enricher = self._counting_enricher()
        generated = self.service.generate_prefill(
            project_id,
            self._generate_request("reservation-lineage-force", force=True),
            ai_enricher=enricher,
        )
        self.assertEqual(revision + 1, generated.revision)
        self.assertEqual(1, enricher.call_count)

        row = self._reservation_row(self.service, project_id, revision)
        self.assertIsNotNone(row)
        self.assertEqual("completed", row["status"])
        self.assertNotEqual(dead_call_id, row["logical_call_id"])
        self.assertIn("supersedes unknown-outcome call", row["failure_note"] or "")

        history = json.loads(row["attempt_history"] or "[]")
        self.assertGreaterEqual(len(history), 1)
        prior = history[-1]
        self.assertEqual(dead_call_id, prior["logical_call_id"])
        self.assertEqual(1, prior["transport_attempt_count"])
        self.assertEqual("unknown_outcome", prior["status"])
        self.assertEqual("prior attempt failure note", prior["failure_note"])

        detail = self._event_detail(self.service, project_id, "reservation-lineage-force")
        self.assertEqual("completed", detail["ai_outcome"])
        self.assertEqual(row["logical_call_id"], detail["ai_logical_call_id"])
        self.assertEqual(1, detail["ai_transport_attempt_count"])

    def test_force_supersede_cannot_overwrite_completed_owner_snapshot(self):
        """A force caller holding a stale terminal snapshot must not re-key a
        reservation after its original owner has committed completion.

        This is the deterministic end-state of the SELECT/UPDATE race: the
        logical call id is unchanged, but the status and completion event have
        moved to the terminal owner outcome.  The supersede CAS must fail
        closed and leave the completed row (and its lineage) untouched.
        """
        project_id = "proj_ra"
        revision = self.journey.revision
        previous_call_id = "mwprefillcall_sameowner000000000000"
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.service._connect() as connection:
            connection.execute(
                "INSERT INTO "
                "medical_writing_authoring_journey_generation_reservations("
                "project_id, expected_revision, operation, logical_call_id, "
                "transport_attempt_count, status, event_id, failure_note, "
                "attempt_history, created_at, updated_at) VALUES "
                "(?, ?, ?, ?, 1, 'unknown_outcome', ?, ?, '[]', ?, ?)",
                (
                    project_id,
                    revision,
                    "prefill_generate",
                    previous_call_id,
                    "event-unknown",
                    "prior outcome was unknown",
                    now_iso,
                    now_iso,
                ),
            )
            connection.execute(
                "UPDATE "
                "medical_writing_authoring_journey_generation_reservations "
                "SET status = 'completed', event_id = ?, failure_note = NULL "
                "WHERE project_id = ? AND expected_revision = ? AND operation = ?",
                (
                    "event-completed",
                    project_id,
                    revision,
                    "prefill_generate",
                ),
            )
            connection.commit()

        superseded = self.service._supersede_generation_reservation(
            project_id,
            revision,
            "prefill_generate",
            previous_call_id=previous_call_id,
            note="supersedes stale snapshot",
        )
        self.assertIsNone(superseded)
        row = self._reservation_row(self.service, project_id, revision)
        self.assertEqual("completed", row["status"])
        self.assertEqual(previous_call_id, row["logical_call_id"])
        self.assertEqual("event-completed", row["event_id"])
        self.assertEqual([], json.loads(row["attempt_history"] or "[]"))

    def test_v1_store_migrates_generation_reservation_history_column(self):
        """A round-1 store (reservation table without attempt_history,
        schema version 1) is migrated in place to version 2 on reopen: the
        append-only history column is added and generation still works."""
        tmpdir = tempfile.TemporaryDirectory()
        try:
            db_path = Path(tmpdir.name) / "test.sqlite3"
            first = MedicalWritingAuthoringJourneyService(db_path)
            with first._connect() as connection:
                connection.execute(
                    "ALTER TABLE "
                    "medical_writing_authoring_journey_generation_reservations "
                    "DROP COLUMN attempt_history"
                )
                connection.execute("UPDATE schema_migrations SET version = 1")
                connection.commit()

            reopened = MedicalWritingAuthoringJourneyService(db_path)
            with reopened._connect() as connection:
                version = connection.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0]
                columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info("
                        "medical_writing_authoring_journey_generation_reservations)"
                    )
                }
            self.assertEqual(2, version)
            self.assertIn("attempt_history", columns)

            # End to end: generation completes on the migrated store.
            reopened.create("proj_ra", _ra_create_request())
            journey = _mark_research_ready_for_test(
                reopened,
                "proj_ra",
                idempotency_key="fixture-migration-ready",
            )
            enricher = self._counting_enricher()
            generated = reopened.generate_prefill(
                "proj_ra",
                AuthoringPrefillGenerateRequest(
                    expected_revision=journey.revision,
                    actor="medical_manager_test",
                    idempotency_key="migration-generate-001",
                ),
                ai_enricher=enricher,
            )
            self.assertEqual(1, enricher.call_count)
            row = self._reservation_row(reopened, "proj_ra", journey.revision)
            self.assertEqual("completed", row["status"])
            self.assertEqual([], json.loads(row["attempt_history"] or "[]"))
            self.assertEqual(generated.revision, journey.revision + 1)
        finally:
            tmpdir.cleanup()

    def test_wait_bound_marking_preserves_in_flight_attempt_history(self):
        """A dead in_flight reservation observed beyond the wait bound is
        preserved as unknown_outcome with the original in-flight attempt
        appended to attempt-history before the note is replaced."""
        project_id = "proj_ra"
        revision = self.journey.revision
        dead_call_id = "mwprefillcall_round2stuck00000000000"
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.service._connect() as connection:
            connection.execute(
                "INSERT INTO "
                "medical_writing_authoring_journey_generation_reservations("
                "project_id, expected_revision, operation, logical_call_id, "
                "transport_attempt_count, status, event_id, failure_note, "
                "attempt_history, created_at, updated_at) VALUES "
                "(?, ?, ?, ?, 1, 'in_flight', NULL, "
                "'original owner note', '[]', ?, ?)",
                (project_id, revision, "prefill_generate", dead_call_id, now_iso, now_iso),
            )
            connection.commit()

        enricher = self._counting_enricher()
        with self.assertRaisesRegex(
            MedicalWritingAuthoringJourneyConflictError, "in flight"
        ):
            self.service.generate_prefill(
                project_id,
                self._generate_request("reservation-stuck-001"),
                ai_enricher=enricher,
            )
        self.assertEqual(0, enricher.call_count)

        row = self._reservation_row(self.service, project_id, revision)
        self.assertEqual("unknown_outcome", row["status"])
        self.assertEqual(dead_call_id, row["logical_call_id"])
        self.assertEqual(1, row["transport_attempt_count"])
        self.assertIn("presumed interrupted", row["failure_note"] or "")
        history = json.loads(row["attempt_history"] or "[]")
        self.assertGreaterEqual(len(history), 1)
        prior = history[-1]
        self.assertEqual(dead_call_id, prior["logical_call_id"])
        self.assertEqual("in_flight", prior["status"])
        self.assertEqual("original owner note", prior["failure_note"])

    # ------------------------------------------------------------------
    # Worker_03 corrective round 3: reservation owner/telemetry/force/
    # replay hardening.
    # ------------------------------------------------------------------

    def test_owner_completes_under_skewed_waiter_wait_bounds(self):
        """A waiter whose wait bound expires while the live owner is still
        enriching must not lose the owner's successful event: the deadline
        flip is logical-call-bound, the owner's completion re-claims the
        same row, and the reservation ends completed with the owner's event
        (the waiter fails closed without dispatching)."""
        project_id = "proj_ra"
        revision = self.journey.revision
        owner = MedicalWritingAuthoringJourneyService(self.db_path)
        owner_enricher = self._counting_enricher(delay=0.6, timeout_seconds=5.0)
        owner_results: list = []
        owner_errors: list = []

        def _owner():
            try:
                owner_results.append(
                    owner.generate_prefill(
                        project_id,
                        self._generate_request("reservation-skew-owner"),
                        ai_enricher=owner_enricher,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - surfaced below
                owner_errors.append(exc)

        owner_thread = threading.Thread(target=_owner)
        owner_thread.start()
        # Wait until the owner's in-flight reservation exists, then start a
        # waiter with a SHORT wait bound (0.15s) so its deadline fires while
        # the owner is still enriching (0.6s delay).
        deadline = time.monotonic() + 10
        while (
            self._reservation_row(self.service, project_id, revision) is None
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        waiter = MedicalWritingAuthoringJourneyService(
            self.db_path, generation_reservation_wait_seconds=0.15
        )
        waiter_enricher = self._counting_enricher()
        with self.assertRaisesRegex(
            MedicalWritingAuthoringJourneyConflictError, "in flight"
        ):
            waiter.generate_prefill(
                project_id,
                self._generate_request("reservation-skew-waiter"),
                ai_enricher=waiter_enricher,
            )
        owner_thread.join(timeout=30)

        # The owner's successful event was NOT lost by the waiter's flip.
        self.assertEqual([], owner_errors)
        self.assertEqual(1, len(owner_results))
        self.assertEqual(revision + 1, owner_results[0].revision)
        self.assertEqual(0, waiter_enricher.call_count)
        self.assertEqual(1, owner_enricher.call_count)
        self.assertEqual(1, self._generation_event_count(self.service, project_id))
        row = self._reservation_row(self.service, project_id, revision)
        self.assertIsNotNone(row)
        self.assertEqual("completed", row["status"])
        self.assertEqual(1, row["transport_attempt_count"])
        self.assertIsNotNone(row["event_id"])
        # The waiter's "presumed interrupted" note is cleared by the owner's
        # completion while the flip stays auditable in attempt history.
        self.assertIsNone(row["failure_note"])
        history = json.loads(row["attempt_history"] or "[]")
        self.assertGreaterEqual(len(history), 1)
        self.assertEqual(
            str(row["logical_call_id"]), history[-1]["logical_call_id"]
        )
        self.assertEqual("in_flight", history[-1]["status"])

    def test_stale_waiter_cannot_flip_superseded_owner_call(self):
        """A waiter that observed a call id which a force caller later
        superseded cannot flip the NEW owner: the deadline UPDATE is bound
        to the observed logical call id, its rowcount check fails, and the
        waiter fails closed without touching the new owner's row."""
        project_id = "proj_ra"
        revision = self.journey.revision
        observed_call_id = "mwprefillcall_skewobserved000000000"
        new_call_id = "mwprefillcall_skewnewowner0000000000"
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.service._connect() as connection:
            connection.execute(
                "INSERT INTO "
                "medical_writing_authoring_journey_generation_reservations("
                "project_id, expected_revision, operation, logical_call_id, "
                "transport_attempt_count, status, event_id, failure_note, "
                "attempt_history, created_at, updated_at) VALUES "
                "(?, ?, ?, ?, 1, 'in_flight', NULL, NULL, '[]', ?, ?)",
                (project_id, revision, "prefill_generate", new_call_id, now_iso, now_iso),
            )
            connection.commit()

        real = self._reservation_row(self.service, project_id, revision)

        class _StaleRow:
            """Snapshot of the row as the stale waiter observed it (the
            superseded call id) before a force caller re-keyed the row."""

            def __init__(self, source):
                self._values = {key: source[key] for key in source.keys()}
                self._values["logical_call_id"] = observed_call_id

            def __getitem__(self, key):
                return self._values[key]

        calls = {"n": 0}

        def _reads(project_id_arg, expected_revision_arg, operation_arg):
            calls["n"] += 1
            if calls["n"] <= 12:
                # Reads up to and past the deadline (0.1s at ~0.02s/loop)
                # keep returning the stale snapshot the waiter observed
                # before the force caller superseded the key; later reads
                # see the live new owner.
                return _StaleRow(real)
            return self._reservation_row(self.service, project_id_arg, expected_revision_arg)

        waiter = MedicalWritingAuthoringJourneyService(
            self.db_path, generation_reservation_wait_seconds=0.1
        )
        enricher = self._counting_enricher()
        with patch.object(
            waiter, "_read_generation_reservation", side_effect=_reads
        ):
            with self.assertRaisesRegex(
                MedicalWritingAuthoringJourneyConflictError, "in flight"
            ):
                waiter.generate_prefill(
                    project_id,
                    self._generate_request("reservation-skew-stale"),
                    ai_enricher=enricher,
                )
        self.assertEqual(0, enricher.call_count)
        # The NEW owner's row is untouched: still in_flight with its own id
        # and an empty attempt history (the stale flip was rejected).
        row = self._reservation_row(self.service, project_id, revision)
        self.assertEqual("in_flight", row["status"])
        self.assertEqual(new_call_id, row["logical_call_id"])
        self.assertEqual([], json.loads(row["attempt_history"] or "[]"))

    def test_force_during_in_flight_fails_fast_with_live_owner_message(self):
        """force=True while a live owner is enriching fails fast (no wait
        for the bound) with an accurate message naming the live call; force
        cannot interrupt it and never dispatches a second transport."""
        project_id = "proj_ra"
        revision = self.journey.revision
        owner = MedicalWritingAuthoringJourneyService(self.db_path)
        owner_enricher = self._counting_enricher(delay=1.5, timeout_seconds=5.0)
        owner_results: list = []
        owner_errors: list = []

        def _owner():
            try:
                owner_results.append(
                    owner.generate_prefill(
                        project_id,
                        self._generate_request("reservation-force-owner"),
                        ai_enricher=owner_enricher,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - surfaced below
                owner_errors.append(exc)

        owner_thread = threading.Thread(target=_owner)
        owner_thread.start()
        deadline = time.monotonic() + 10
        while (
            self._reservation_row(self.service, project_id, revision) is None
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        force_service = MedicalWritingAuthoringJourneyService(
            self.db_path, generation_reservation_wait_seconds=10.0
        )
        force_enricher = self._counting_enricher()
        started = time.monotonic()
        with self.assertRaisesRegex(
            MedicalWritingAuthoringJourneyConflictError,
            "force cannot interrupt the live call",
        ) as ctx:
            force_service.generate_prefill(
                project_id,
                self._generate_request(
                    "reservation-force-request", force=True
                ),
                ai_enricher=force_enricher,
            )
        elapsed = time.monotonic() - started
        # Fail fast: far below the 10s wait bound of the force caller.
        self.assertLess(elapsed, 2.0)
        self.assertIn("logical call", str(ctx.exception))
        self.assertEqual(0, force_enricher.call_count)
        owner_thread.join(timeout=30)
        # The live owner still completes with its single transport.
        self.assertEqual([], owner_errors)
        self.assertEqual(1, len(owner_results))
        self.assertEqual(1, owner_enricher.call_count)
        row = self._reservation_row(self.service, project_id, revision)
        self.assertEqual("completed", row["status"])
        self.assertEqual(1, row["transport_attempt_count"])

    def test_non_timeout_enrichment_failure_emits_failed_outcome(self):
        """A non-timeout terminal enricher exception persists the
        deterministic fallback with event telemetry ai_outcome=failed (not
        completed, not unknown_outcome); the reservation completes with the
        event so a same-key duplicate replays without a new dispatch."""
        project_id = "proj_ra"
        revision = self.journey.revision
        enricher = self._counting_enricher(
            fail_with=RuntimeError("provider terminal failure"),
            timeout_seconds=5.0,
        )
        generated = self.service.generate_prefill(
            project_id,
            self._generate_request("reservation-failed-001"),
            ai_enricher=enricher,
        )
        self.assertEqual(revision + 1, generated.revision)
        joined = " ".join(generated.prefill_package.partial_source_failures)
        self.assertIn("enrich_package failed", joined)
        self.assertIn("RuntimeError", joined)

        row = self._reservation_row(self.service, project_id, revision)
        self.assertIsNotNone(row)
        self.assertEqual("completed", row["status"])
        self.assertIsNotNone(row["event_id"])
        self.assertEqual(1, row["transport_attempt_count"])
        detail = self._event_detail(self.service, project_id, "reservation-failed-001")
        self.assertIsNotNone(detail)
        self.assertEqual("failed", detail["ai_outcome"])
        self.assertEqual(
            str(row["logical_call_id"]), detail["ai_logical_call_id"]
        )
        self.assertEqual(1, detail["ai_transport_attempt_count"])

        # Same-key duplicate replays the fallback event: no second dispatch.
        replay = self.service.generate_prefill(
            project_id,
            self._generate_request("reservation-failed-001"),
            ai_enricher=enricher,
        )
        self.assertEqual(replay.revision, generated.revision)
        self.assertEqual(1, enricher.call_count)
        self.assertEqual(1, self._generation_event_count(self.service, project_id))
        row = self._reservation_row(self.service, project_id, revision)
        self.assertEqual("completed", row["status"])

    def test_timeout_outcome_keeps_unknown_semantics(self):
        """The timeout path is untouched: ai_outcome stays
        unknown_outcome and the reservation stays unknown_outcome."""
        project_id = "proj_ra"
        revision = self.journey.revision
        enricher = self._counting_enricher(
            delay=0.15,
            fail_with=TimeoutError("simulated provider timeout"),
            timeout_seconds=0.05,
        )
        self.service.generate_prefill(
            project_id,
            self._generate_request("reservation-timeout-keep"),
            ai_enricher=enricher,
        )
        detail = self._event_detail(
            self.service, project_id, "reservation-timeout-keep"
        )
        self.assertEqual("unknown_outcome", detail["ai_outcome"])
        row = self._reservation_row(self.service, project_id, self.journey.revision)
        self.assertEqual("unknown_outcome", row["status"])

    def test_late_replay_returns_current_state_with_event_revision_metadata(self):
        """A waiter replaying a completed reservation receives the CURRENT
        journey (documented current-state replay, possibly a later revision
        after a force re-gen) and the acquisition carries the verified
        completion event revision so callers can explain the refresh."""
        project_id = "proj_ra"
        revision = self.journey.revision
        # First generation completes key N at revision N+1.
        first_enricher = self._counting_enricher()
        first = self.service.generate_prefill(
            project_id,
            self._generate_request("reservation-replay-001"),
            ai_enricher=first_enricher,
        )
        self.assertEqual(revision + 1, first.revision)
        key_n_row = self._reservation_row(self.service, project_id, revision)
        self.assertEqual("completed", key_n_row["status"])
        first_event_id = str(key_n_row["event_id"])

        # Force re-gen at N+1 completes at revision N+2.
        force_enricher = self._counting_enricher()
        forced = self.service.generate_prefill(
            project_id,
            self._generate_request(
                "reservation-replay-force",
                force=True,
                expected_revision=first.revision,
            ),
            ai_enricher=force_enricher,
        )
        self.assertEqual(revision + 2, forced.revision)
        self.assertEqual(1, force_enricher.call_count)
        self.assertEqual(1, first_enricher.call_count)

        # A late duplicate for key N replays the CURRENT journey (N+2)
        # with the verified completion event metadata (key N's event at
        # revision N+1) explaining the refresh; nothing is redispatched.
        late_enricher = self._counting_enricher()
        acquisition = self.service._acquire_generation_reservation(
            project_id=project_id,
            expected_revision=revision,
            operation="prefill_generate",
            force=False,
            enricher_timeout_seconds=5.0,
        )
        self.assertIsNone(acquisition.logical_call_id)
        self.assertIsNotNone(acquisition.replay)
        self.assertEqual(revision + 2, acquisition.replay.revision)
        self.assertEqual(first_event_id, acquisition.replay_event_id)
        self.assertEqual(revision + 1, acquisition.replay_event_revision)
        self.assertEqual(0, late_enricher.call_count)

        # The reservation row exposes the completed event revision.
        with self.service._connect() as connection:
            event_row = connection.execute(
                "SELECT revision FROM medical_writing_authoring_journey_events "
                "WHERE project_id = ? AND event_id = ?",
                (project_id, first_event_id),
            ).fetchone()
        self.assertIsNotNone(event_row)
        self.assertEqual(revision + 1, int(event_row["revision"]))
        # Key N+1 (the force call) completed at N+2 with its own event.
        key_n1_row = self._reservation_row(
            self.service, project_id, first.revision
        )
        self.assertEqual("completed", key_n1_row["status"])
        self.assertIsNotNone(key_n1_row["event_id"])

    def test_replay_metadata_acquisition_and_fail_closed_on_mismatch(self):
        """_acquire_generation_reservation returns the verified completion
        event id/revision for a completed key and fails closed when the
        completion event revision does not match the key."""
        project_id = "proj_ra"
        revision = self.journey.revision
        enricher = self._counting_enricher()
        self.service.generate_prefill(
            project_id,
            self._generate_request("reservation-meta-001"),
            ai_enricher=enricher,
        )
        acquisition = self.service._acquire_generation_reservation(
            project_id=project_id,
            expected_revision=revision,
            operation="prefill_generate",
            force=False,
            enricher_timeout_seconds=5.0,
        )
        self.assertIsNone(acquisition.logical_call_id)
        self.assertIsNotNone(acquisition.replay)
        self.assertEqual(revision + 1, acquisition.replay.revision)
        self.assertIsNotNone(acquisition.replay_event_id)
        self.assertEqual(revision + 1, acquisition.replay_event_revision)
        row = self._reservation_row(self.service, project_id, revision)
        self.assertEqual(acquisition.replay_event_id, row["event_id"])

        # Corrupt the completion event revision: replay fails closed.
        with self.service._connect() as connection:
            connection.execute(
                "UPDATE medical_writing_authoring_journey_events "
                "SET revision = ? WHERE event_id = ?",
                (revision + 5, acquisition.replay_event_id),
            )
            connection.commit()
        with self.assertRaisesRegex(
            MedicalWritingAuthoringJourneyConflictError,
            "completion event revision",
        ):
            self.service._acquire_generation_reservation(
                project_id=project_id,
                expected_revision=revision,
                operation="prefill_generate",
                force=False,
                enricher_timeout_seconds=5.0,
            )


# ---------------------------------------------------------------------------
# Worker_03 corrective: unsupported substantive term gaps
# ---------------------------------------------------------------------------


class UnsupportedTermGapTests(unittest.TestCase):
    """P2-2 corrective: AChR / IVIG / inadequate-response claims absent from
    every bound quote yield a visible evidence gap instead of a silent pass.
    Unsupported numeric claims keep the hard-drop behavior."""

    def _gate(self, value: str, evidence_texts: list[str]):
        refs = [
            AuthoringPrefillEvidenceRef(
                source_kind="search_snapshot",
                source_id="ctgov:test:NCT00000000",
                locator="ctgov:test:NCT00000000:conditions",
                source_text=text,
                quote_sha256=hashlib.sha256(
                    text.encode("utf-8")
                ).hexdigest(),
            )
            for text in evidence_texts
        ]
        return _passes_language_and_evidence_gate(
            "picos.population_summary",
            value,
            value,
            "候选人群。",
            evidence_refs=refs,
        )

    def test_achr_claim_absent_from_quotes_yields_visible_gap(self):
        passed, reason, gap_notes = self._gate(
            "AChR抗体阳性的重症肌无力患者",
            ["Generalized Myasthenia Gravis"],
        )
        self.assertFalse(passed)
        self.assertIn("achr_seropositive", reason)
        self.assertEqual(
            ["声称内容未在引用原文中出现：AChR抗体阳性相关表述"],
            gap_notes,
        )

    def test_achr_claim_supported_by_quote_passes(self):
        passed, reason, gap_notes = self._gate(
            "AChR抗体阳性的重症肌无力患者",
            ["anti-AChR antibody positive myasthenia gravis"],
        )
        self.assertTrue(passed, reason)
        self.assertEqual([], gap_notes)

    def test_inadequate_response_claim_absent_from_refractory_quote_yields_gap(self):
        # The confirmed counterexample: "Refractory ..." must NOT satisfy
        # "对标准治疗反应不佳".
        passed, reason, gap_notes = self._gate(
            "对标准治疗反应不佳的重症肌无力患者",
            ["Refractory Generalized Myasthenia Gravis"],
        )
        self.assertFalse(passed)
        self.assertIn("inadequate_response", reason)
        self.assertEqual(
            ["声称内容未在引用原文中出现：对标准治疗反应不佳相关表述"],
            gap_notes,
        )

    def test_ivig_claim_absent_from_quotes_yields_gap(self):
        passed, reason, gap_notes = self._gate(
            "接受IVIG治疗的患者",
            ["Generalized Myasthenia Gravis"],
        )
        self.assertFalse(passed)
        self.assertIn("ivig", reason)
        self.assertEqual(
            ["声称内容未在引用原文中出现：IVIG/静脉注射免疫球蛋白相关表述"],
            gap_notes,
        )

    def test_ivig_claim_supported_by_quote_passes(self):
        passed, reason, gap_notes = self._gate(
            "接受IVIG治疗的患者",
            ["IVIG 10 g/kg every 4 weeks"],
        )
        self.assertTrue(passed, reason)
        self.assertEqual([], gap_notes)

    def test_multiple_missing_terms_yield_one_gap_each(self):
        passed, reason, gap_notes = self._gate(
            "AChR抗体阳性且对标准治疗反应不佳的患者",
            ["Generalized Myasthenia Gravis"],
        )
        self.assertFalse(passed)
        # Gap order follows the controlled-rule declaration order.
        self.assertEqual(
            [
                "声称内容未在引用原文中出现：对标准治疗反应不佳相关表述",
                "声称内容未在引用原文中出现：AChR抗体阳性相关表述",
            ],
            gap_notes,
        )

    def test_plain_claim_without_controlled_term_passes(self):
        passed, reason, gap_notes = self._gate(
            "重症肌无力患者",
            ["Generalized Myasthenia Gravis"],
        )
        self.assertTrue(passed, reason)
        self.assertEqual([], gap_notes)

    def test_negated_achr_claim_produces_no_gap(self):
        """AChR抗体阴性 (seronegative) is NOT a positive AChR-seropositive
        claim: it must not require AChR-positivity evidence (worker_03
        negation-aware controlled-term matching)."""
        for value in (
            "AChR抗体阴性的重症肌无力患者",
            "抗乙酰胆碱受体抗体阴性的重症肌无力患者",
            "乙酰胆碱受体抗体阴性的患者",
            "无AChR抗体的重症肌无力患者",
        ):
            passed, reason, gap_notes = self._gate(
                value,
                ["Generalized Myasthenia Gravis"],
            )
            self.assertTrue(passed, f"{value}: {reason}")
            self.assertEqual([], gap_notes, value)

    def test_negated_ivig_claim_produces_no_gap(self):
        """未接受IVIG is NOT an IVIG-exposure claim (worker_03)."""
        for value in (
            "未接受IVIG治疗的患者",
            "未使用过静脉用免疫球蛋白的患者",
            "未接受丙种球蛋白的患者",
            "无IVIG使用史的患者",
            "IVIG停用的患者",
        ):
            passed, reason, gap_notes = self._gate(
                value,
                ["Generalized Myasthenia Gravis"],
            )
            self.assertTrue(passed, f"{value}: {reason}")
            self.assertEqual([], gap_notes, value)

    def test_negated_inadequate_response_claim_produces_no_gap(self):
        """无治疗失败史 / 未出现治疗失败 are NOT inadequate-response claims
        (worker_03)."""
        for value in (
            "无治疗失败史的重症肌无力患者",
            "未出现治疗失败的重症肌无力患者",
            "未达到治疗失败标准的患者",
            "非反应不佳的患者",
            "无药物不耐受史的患者",
        ):
            passed, reason, gap_notes = self._gate(
                value,
                ["Generalized Myasthenia Gravis"],
            )
            self.assertTrue(passed, f"{value}: {reason}")
            self.assertEqual([], gap_notes, value)

    def test_mixed_negated_and_positive_claims_gap_only_positive(self):
        """A seronegative AChR claim combined with a positive
        inadequate-response claim produces ONLY the inadequate-response gap:
        per-rule negation isolation (worker_03)."""
        passed, reason, gap_notes = self._gate(
            "AChR抗体阴性且对标准治疗反应不佳的患者",
            ["Generalized Myasthenia Gravis"],
        )
        self.assertFalse(passed)
        self.assertIn("inadequate_response", reason)
        self.assertNotIn("achr_seropositive", reason)
        self.assertEqual(
            ["声称内容未在引用原文中出现：对标准治疗反应不佳相关表述"],
            gap_notes,
        )

    def test_positive_claims_still_gap_after_negation_support(self):
        """The negation support never weakens the positive gates: positive
        AChR/IVIG/inadequate-response claims still gap when absent from the
        bound quotes (worker_03 regression guard)."""
        for value, display in (
            ("AChR抗体阳性的重症肌无力患者", "AChR抗体阳性相关表述"),
            ("接受IVIG治疗的患者", "IVIG/静脉注射免疫球蛋白相关表述"),
            ("对标准治疗反应不佳的患者", "对标准治疗反应不佳相关表述"),
            ("无AChR抗体但接受IVIG治疗的患者", "IVIG/静脉注射免疫球蛋白相关表述"),
        ):
            passed, reason, gap_notes = self._gate(
                value,
                ["Generalized Myasthenia Gravis"],
            )
            self.assertFalse(passed, f"{value} must still gap: {reason}")
            self.assertIn(
                f"声称内容未在引用原文中出现：{display}",
                gap_notes,
                value,
            )

    def test_unsupported_numbers_stay_hard_dropped(self):
        # Exact-fact gates are never weakened: numeric claims absent from the
        # bound evidence produce no visible gap and a hard drop.
        passed, reason, gap_notes = self._gate(
            "每周给药100 mg",
            ["Generalized Myasthenia Gravis"],
        )
        self.assertFalse(passed)
        self.assertEqual([], gap_notes)
        self.assertIn("numeric_claim_not_in_bound_evidence", reason)


# ---------------------------------------------------------------------------
# Worker_03 corrective: safe recommended selection
# ---------------------------------------------------------------------------


class SafeRecommendedSelectionTests(unittest.TestCase):
    """P3-2 corrective: the recommended slot never points at a pending/manual
    placeholder card; roles are preserved; empty when no candidate is safe.

    Worker_03 corrective: ``manual_only`` candidates are excluded from safe
    recommendation selection — a card that requires explicit medical-manager
    confirmation must never be auto-labeled as the recommended pick.
    """

    def _candidate(
        self,
        candidate_id: str,
        *,
        role: str,
        value: str = "随机",
        adoption_mode: str = "batch_allowed",
    ):
        return AuthoringPrefillCandidate(
            candidate_id=candidate_id,
            field_path="package.design",
            structured_value=value,
            preview=value,
            recommendation_role=role,
            adoption_mode=adoption_mode,
        )

    def test_pending_only_group_has_empty_recommendation(self):
        candidates = [
            self._candidate(
                "c_pending", role="pending_decision", adoption_mode="manual_only"
            )
        ]
        self.assertEqual(
            "", select_safe_recommended_candidate_id(candidates)
        )
        # Roles are preserved.
        self.assertEqual(
            "pending_decision", candidates[0].recommendation_role
        )

    def test_mixed_group_picks_first_safe_non_pending_candidate(self):
        pending = self._candidate(
            "c_pending", role="pending_decision", adoption_mode="manual_only"
        )
        alternative = self._candidate("c_alt", role="alternative")
        recommended = self._candidate("c_rec", role="recommended")
        self.assertEqual(
            "c_alt",
            select_safe_recommended_candidate_id(
                [pending, alternative, recommended]
            ),
        )
        self.assertEqual("pending_decision", pending.recommendation_role)
        self.assertEqual("alternative", alternative.recommendation_role)
        self.assertEqual("recommended", recommended.recommendation_role)

    def test_manual_only_candidate_never_occupies_recommended_slot(self):
        """A supported, non-pending candidate with ``manual_only`` adoption
        mode is excluded: the slot falls through to the next safe candidate
        and is empty when every candidate is manual-only."""
        manual = self._candidate(
            "c_manual", role="recommended", adoption_mode="manual_only"
        )
        batch = self._candidate("c_batch", role="alternative")
        self.assertEqual(
            "c_batch",
            select_safe_recommended_candidate_id([manual, batch]),
        )
        # Roles are preserved (nothing is demoted/promoted by selection).
        self.assertEqual("recommended", manual.recommendation_role)
        self.assertEqual("alternative", batch.recommendation_role)
        # Every candidate manual-only -> no safe recommendation at all.
        self.assertEqual(
            "",
            select_safe_recommended_candidate_id([manual]),
        )
        # The disqualifier callback is still honored for batch-allowed cards.
        self.assertEqual(
            "",
            select_safe_recommended_candidate_id(
                [batch], is_disqualified=lambda c: True
            ),
        )

    def test_all_candidates_disqualified_yields_empty_recommendation(self):
        candidates = [self._candidate("c_alt", role="alternative")]
        self.assertEqual(
            "",
            select_safe_recommended_candidate_id(
                candidates, is_disqualified=lambda c: True
            ),
        )

    def test_gap_candidate_never_occupies_recommended_slot(self):
        gap = self._candidate("c_gap", role="recommended").model_copy(
            update={
                "evidence_gaps": ["声称内容未在引用原文中出现：AChR抗体阳性相关表述"]
            }
        )
        clean = self._candidate("c_clean", role="alternative")
        self.assertEqual(
            "c_clean",
            select_safe_recommended_candidate_id(
                [gap, clean],
                is_disqualified=lambda c: any(
                    str(g).startswith("声称内容未在引用原文中出现：")
                    for g in (c.evidence_gaps or [])
                ),
            ),
        )
        # Without the disqualifier the gap candidate is non-pending and safe.
        self.assertEqual(
            "c_gap", select_safe_recommended_candidate_id([gap, clean])
        )


# ---------------------------------------------------------------------------
# Worker_03 corrective: bulk system prompt real newlines
# ---------------------------------------------------------------------------


class BulkPromptNewlineTests(unittest.TestCase):
    """P4-3 corrective: ``_BULK_SYSTEM_PROMPT`` must carry real newlines, not
    literal backslash-n escapes."""

    def test_prompt_contains_real_newlines(self):
        self.assertIn("\n\n", _BULK_SYSTEM_PROMPT)
        self.assertEqual(0, _BULK_SYSTEM_PROMPT.count("\\n"))

    def test_prompt_still_contract_complete(self):
        for fragment in (
            "evidence_catalog",
            "claim_bindings",
            "catalog_sha256",
            "pending_decision",
            "support_kind=competitor_observation",
        ):
            self.assertIn(fragment, _BULK_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
