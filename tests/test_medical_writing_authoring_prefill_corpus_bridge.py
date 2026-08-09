"""Focused tests for the read-only round-1 corpus-analysis → prefill bridge.

Covers the worker_01 slice:
- Journey-bound identity extraction (unbound vs partial vs complete).
- Fail-closed verification: project / pipeline / snapshot / analysis id /
  frozen route / output-hash drift, missing row, altered payload.
- Deterministic conversion of eligible source bindings into immutable
  catalog entries with source id, locator, source hash, finding id and
  analysis lineage.
- Competitor semantics: entries are competitor_observation only, never
  current_project_fact; exact-fact text (dose / AESI / sample size /
  washout) stays competitor evidence.
- Conservative module→target-path allowlist: cross-indication structure
  only, wording conventions, and analysis-declared non-reusable findings
  support NO target paths; unknown modules fail closed.
- Generation and adoption rebuild identical catalog identity.

NOTE: binding-validator integration (corpus entries as claim bind targets)
belongs to worker_02; this file covers the catalog-side contract only.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from packages.contracts.workbench_contracts import (
    MedicalWritingAuthoringJourney,
    MedicalWritingStudyFraming,
)

from services.api.app.medical_writing_authoring_prefill_corpus_bridge import (
    CONFLICT_PRESERVED_REUSE_DECISIONS,
    CORPUS_ANALYSIS_LINEAGE,
    CORPUS_EVIDENCE_SOURCE_KIND,
    INSUFFICIENT_SUPPORT_REUSE_DECISION,
    CorpusPrefillBridgeError,
    analysis_output_hash,
    bound_round1_analysis_identity,
    build_corpus_analysis_entries,
    corpus_module_target_paths,
    load_bound_round1_analysis,
    read_only_analysis_reader,
    read_only_source_binding_reader,
    verify_analysis_source_bindings,
    verify_round1_analysis,
)
from services.api.app.writing_reference_repository import TENANT_ID
from services.api.app.medical_writing_authoring_prefill import (
    generate_prefill_package,
)
from services.api.app.medical_writing_authoring_prefill_ai import (
    DEEPSEEK_PREFILL_MODEL,
    DeepSeekPrefillAdapter,
)
from services.api.app.medical_writing_authoring_prefill_evidence import (
    build_evidence_catalog,
)
from services.api.app.medical_writing_authoring_prefill_evidence_binding import (
    build_round1_corpus_review_candidates,
    project_catalog_for_model,
    server_candidate_requires_pending_decision,
    validate_and_rebind_candidates,
)
from services.api.app.medical_writing_corpus_analysis_ai import _hash_json

NOW = datetime(2026, 7, 30, 9, 0, 0, tzinfo=timezone.utc)

PROJECT_ID = "proj_corpus_01"
PIPELINE_ID = "pipe_round1_01"
SNAPSHOT_ID = "snap_round1_01"
ANALYSIS_ID = "mwca_1234567890abcdef12345678"
ROUTE_HASH = "c" * 64
DOC_HASH = "d" * 64
SPAN_HASH = "e" * 64
SCHEMA_VERSION = "competitor_protocol_corpus_analysis_v4"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _ai_route() -> dict:
    return {
        "schema_version": "corpus_analysis_ai_route_v1",
        "profile_id": "product_independent_ai",
        "profile_revision": 3,
        "provider": "alibaba_token_plan",
        "model": "qwen3.8-max-preview",
        "base_url": "https://example.invalid/v1",
        "transport": "openai_compatible",
        "expected_response_model": "qwen3.8-max-preview",
        "deployment_profile": "default",
        "identity_hash": ROUTE_HASH,
    }


def _binding(
    *,
    evidence_id: str = "cae_abc",
    source_id: str = "art_protocol_1",
    excerpt: str = (
        "The protocol randomizes 1:1 to active drug or placebo with a "
        "double-blind design.\n受控中文译文：方案按1:1随机分配至试验药或安慰剂，采用双盲设计。"
    ),
    locator: str = "page-12",
    span_id: str = "span_001",
) -> dict:
    return {
        "evidence_id": evidence_id,
        "source_excerpt": excerpt,
        "nct_id": "NCT00000001",
        "source_id": source_id,
        "source_file": "protocol.pdf",
        "document_sha256": DOC_HASH,
        "span_id": span_id,
        "source_text_sha256": SPAN_HASH,
        "locator": locator,
        "physical_page": 12,
        "lead_sponsor": "Competitor Pharma",
        "conditions": ["Paroxysmal Nocturnal Hemoglobinuria"],
        "phases": ["PHASE2"],
        "indication_relation": "same",
        "indication_alignment": {"relation": "same", "status": "verified_same"},
    }


def _finding(
    *,
    finding_id: str = "f_design_001",
    module: str = "design",
    statement: str = "竞品方案均采用随机双盲安慰剂对照设计。",
    pattern_kind: str = "clinical_design_requirement",
    transfer_scope: str = "same_indication",
    reuse_decision: str = "evidence_supported_candidate",
    confidence: str = "high",
    bindings: list | None = None,
    unresolved_gaps: list | None = None,
) -> dict:
    return {
        "finding_id": finding_id,
        "module": module,
        "pattern_kind": pattern_kind,
        "content_role": "project_fact_reference",
        "evidence_tier": "tier1_same_indication_layered",
        "reuse_decision": reuse_decision,
        "statement_zh": statement,
        "transfer_scope": transfer_scope,
        "layer": {"design_modules": ["randomized"]},
        "layer_rejections": [],
        "evidence_bindings": bindings or [_binding()],
        "conflicts": [],
        "unresolved_gaps": list(unresolved_gaps) if unresolved_gaps else [],
        "indication_alignment_status": "verified_same",
        "indication_alignment_proofs": [],
        "support": {"source_count": 2, "sponsor_count": 2},
        "confidence": confidence,
    }


def _analysis_payload(*findings: dict) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "analysis_id": ANALYSIS_ID,
        "project_context_hash": "a" * 64,
        "findings": list(findings),
        "evidence_gaps": [],
        "global_conflicts": [],
        "validation_rejections": [],
    }


def _analysis_row(
    *,
    payload: dict | None = None,
    output_hash: str | None = None,
    **overrides,
) -> dict:
    payload = payload if payload is not None else _analysis_payload(_finding())
    output_hash = output_hash or _hash_json(payload)
    row = {
        "analysis_id": ANALYSIS_ID,
        "project_id": PROJECT_ID,
        "pipeline_id": PIPELINE_ID,
        "snapshot_id": SNAPSHOT_ID,
        "status": "completed",
        "prompt_version": "competitor_protocol_corpus_analysis_v9",
        "schema_version": SCHEMA_VERSION,
        "input_hash": "b" * 64,
        "output_hash": output_hash,
        "ai_route": _ai_route(),
        "response_model": "qwen3.8-max-preview",
        "evidence_summary_ids": ["f_design_001"],
        "validation_rejection_count": 0,
        "source_inventory": [],
        "analysis": payload,
        "raw_model_output": {},
        "created_by": "medical_manager",
        "created_at": "2026-07-30T09:00:00+00:00",
    }
    row.update(overrides)
    return row


def _research_pipeline(**overrides) -> dict:
    state = {
        "pipeline_id": PIPELINE_ID,
        "snapshot_id": SNAPSHOT_ID,
        "round1_analysis_id": ANALYSIS_ID,
        "round1_analysis_output_hash": _hash_json(
            _analysis_payload(_finding())
        ),
        "round1_ai_route": _ai_route(),
    }
    state.update(overrides)
    return state


def _journey(
    research_pipeline: dict | None = None,
    project_id: str = PROJECT_ID,
) -> MedicalWritingAuthoringJourney:
    return MedicalWritingAuthoringJourney(
        journey_id="jour_corpus_01",
        project_id=project_id,
        revision=1,
        framing=MedicalWritingStudyFraming(
            investigational_product="CMS-CORPUS-01",
            indication="阵发性睡眠性血红蛋白尿症",
            study_phase="II期",
        ),
        research_pipeline=research_pipeline or {},
        created_at=NOW,
        updated_at=NOW,
        updated_by="test",
    )


def _memory_reader(row: dict | None):
    def _reader(project_id: str, analysis_id: str) -> dict | None:
        if row is None:
            return None
        return row

    return _reader


def _source_composite(
    *,
    artifact_content_sha256: str = DOC_HASH,
    source_current: bool = True,
    span_artifact_id: Optional[str] = None,
    span_source_text_sha256: str = SPAN_HASH,
    span_source_locator: str = "page-12",
) -> dict:
    """Valid composite source-binding record; ``span_artifact_id`` defaults
    to the requested source_id at read time.  ``span_source_locator`` is the
    immutable span's own locator and must equal the binding locator."""
    return {
        "artifact_content_sha256": artifact_content_sha256,
        "source_current": source_current,
        "span_artifact_id": span_artifact_id,
        "span_source_text_sha256": span_source_text_sha256,
        "span_source_locator": span_source_locator,
    }


def _memory_source_reader(
    composite: Optional[dict] = None,
    *,
    missing: tuple = (),
    locators_by_span: Optional[dict] = None,
) -> Callable[[str, str, str], Optional[dict]]:
    """Read-only span/artifact composite reader over an in-memory map.
    ``missing`` is a sequence of ``(source_id, span_id)`` pairs that resolve
    to nothing (missing artifact/span/state row).  ``locators_by_span`` maps
    span_id to the span's own immutable locator (mirrors the SQLite reader,
    where locator and span_id come from the same span row)."""
    composite = _source_composite() if composite is None else composite
    locators_by_span = dict(locators_by_span or {})

    def _reader(
        project_id: str, source_id: str, span_id: str
    ) -> Optional[dict]:
        if (source_id, span_id) in missing:
            return None
        data = dict(composite)
        if data.get("span_artifact_id") is None:
            data["span_artifact_id"] = source_id
        if span_id in locators_by_span:
            data["span_source_locator"] = locators_by_span[span_id]
        return data

    return _reader


def _entry_by_finding(entries, finding_id: str):
    return [
        e for e in entries if e.provenance.get("finding_id") == finding_id
    ]


# ---------------------------------------------------------------------------
# Identity extraction
# ---------------------------------------------------------------------------


class BoundIdentityTests(unittest.TestCase):

    def test_unbound_journey_returns_none(self):
        self.assertIsNone(bound_round1_analysis_identity(_journey()))
        self.assertIsNone(
            bound_round1_analysis_identity(
                _journey(research_pipeline={"pipeline_id": PIPELINE_ID})
            )
        )

    def test_partial_binding_fails_closed(self):
        journey = _journey(
            research_pipeline={
                "pipeline_id": PIPELINE_ID,
                "snapshot_id": SNAPSHOT_ID,
                "round1_analysis_id": ANALYSIS_ID,
                # missing output hash / route
            }
        )
        with self.assertRaises(CorpusPrefillBridgeError):
            bound_round1_analysis_identity(journey)

    def test_complete_binding_extracts_identity(self):
        identity = bound_round1_analysis_identity(
            _journey(research_pipeline=_research_pipeline())
        )
        self.assertIsNotNone(identity)
        assert identity is not None
        self.assertEqual(ANALYSIS_ID, identity["analysis_id"])
        self.assertEqual(PIPELINE_ID, identity["pipeline_id"])
        self.assertEqual(SNAPSHOT_ID, identity["snapshot_id"])
        self.assertEqual(ROUTE_HASH, identity["ai_route"]["identity_hash"])


# ---------------------------------------------------------------------------
# Verification fail-closed matrix
# ---------------------------------------------------------------------------


class VerificationFailClosedTests(unittest.TestCase):

    def _identity(self) -> dict:
        identity = bound_round1_analysis_identity(
            _journey(research_pipeline=_research_pipeline())
        )
        assert identity is not None
        identity["project_id"] = PROJECT_ID
        return identity

    def _verify(self, row: dict, identity: dict | None = None):
        verify_round1_analysis(row, identity or self._identity(), PROJECT_ID)

    def test_valid_row_verifies(self):
        self._verify(_analysis_row())

    def test_project_id_mismatch_rejected(self):
        with self.assertRaises(CorpusPrefillBridgeError):
            self._verify(_analysis_row(project_id="proj_other"))

    def test_analysis_id_mismatch_rejected(self):
        with self.assertRaises(CorpusPrefillBridgeError):
            self._verify(_analysis_row(analysis_id="mwca_other"))

    def test_pipeline_id_mismatch_rejected(self):
        with self.assertRaises(CorpusPrefillBridgeError):
            self._verify(_analysis_row(pipeline_id="pipe_other"))

    def test_snapshot_id_mismatch_rejected(self):
        with self.assertRaises(CorpusPrefillBridgeError):
            self._verify(_analysis_row(snapshot_id="snap_other"))

    def test_non_completed_status_rejected(self):
        with self.assertRaises(CorpusPrefillBridgeError):
            self._verify(_analysis_row(status="failed"))

    def test_missing_keys_rejected(self):
        row = _analysis_row()
        del row["analysis"]
        with self.assertRaises(CorpusPrefillBridgeError):
            self._verify(row)

    def test_ai_route_drift_rejected(self):
        route = _ai_route()
        route["identity_hash"] = "f" * 64
        with self.assertRaises(CorpusPrefillBridgeError):
            self._verify(_analysis_row(ai_route=route))

    def test_journey_bound_output_hash_drift_rejected(self):
        identity = self._identity()
        identity["output_hash"] = "9" * 64
        with self.assertRaises(CorpusPrefillBridgeError):
            self._verify(_analysis_row(), identity)

    def test_persisted_output_hash_drift_rejected(self):
        with self.assertRaises(CorpusPrefillBridgeError):
            self._verify(_analysis_row(output_hash="9" * 64))

    def test_tampered_payload_rejected(self):
        tampered = _analysis_payload(_finding())
        tampered["findings"][0]["statement_zh"] = "被篡改的陈述。"
        # (a) Row self-hash consistent with the tampered payload, but the
        # journey is bound to the original hash → output_hash mismatch.
        row = _analysis_row(payload=tampered, output_hash=_hash_json(tampered))
        with self.assertRaises(CorpusPrefillBridgeError):
            self._verify(row)
        # (b) Row claims the original hash while the payload was altered →
        # recomputation mismatch.
        row2 = _analysis_row(
            payload=tampered,
            output_hash=_hash_json(_analysis_payload(_finding())),
        )
        with self.assertRaises(CorpusPrefillBridgeError):
            self._verify(row2)

    def test_payload_analysis_id_mismatch_rejected(self):
        payload = _analysis_payload(_finding())
        payload["analysis_id"] = "mwca_other"
        row = _analysis_row(payload=payload, output_hash=_hash_json(payload))
        with self.assertRaises(CorpusPrefillBridgeError):
            self._verify(row)

    def test_schema_version_drift_rejected(self):
        payload = _analysis_payload(_finding())
        payload["schema_version"] = "competitor_protocol_corpus_analysis_v3"
        row = _analysis_row(payload=payload, output_hash=_hash_json(payload))
        with self.assertRaises(CorpusPrefillBridgeError):
            self._verify(row)

    def test_non_object_row_rejected(self):
        with self.assertRaises(CorpusPrefillBridgeError):
            self._verify(["not", "a", "dict"])


# ---------------------------------------------------------------------------
# Catalog integration
# ---------------------------------------------------------------------------


class CatalogIntegrationTests(unittest.TestCase):

    def test_unbound_journey_without_reader_unchanged(self):
        catalog = build_evidence_catalog(_journey())
        self.assertEqual(3, len(catalog.entries))
        self.assertEqual({"project_fact"}, {e.source_kind for e in catalog.entries})

    def test_bound_journey_without_reader_fails_closed(self):
        journey = _journey(research_pipeline=_research_pipeline())
        with self.assertRaises(CorpusPrefillBridgeError):
            build_evidence_catalog(journey)
        # Partial binding also fails closed.
        partial = _journey(
            research_pipeline={
                "pipeline_id": PIPELINE_ID,
                "round1_analysis_id": ANALYSIS_ID,
            }
        )
        with self.assertRaises(CorpusPrefillBridgeError):
            build_evidence_catalog(partial)

    def test_bound_journey_with_analysis_reader_but_no_source_reader_fails_closed(self):
        journey = _journey(research_pipeline=_research_pipeline())
        with self.assertRaises(CorpusPrefillBridgeError):
            build_evidence_catalog(
                journey,
                corpus_analysis_reader=_memory_reader(_analysis_row()),
            )

    def test_missing_analysis_row_fails_closed(self):
        journey = _journey(research_pipeline=_research_pipeline())
        with self.assertRaises(CorpusPrefillBridgeError):
            build_evidence_catalog(
                journey,
                corpus_analysis_reader=_memory_reader(None),
                corpus_source_reader=_memory_source_reader(),
            )

    def test_valid_bridge_produces_lineage_bound_entries(self):
        journey = _journey(research_pipeline=_research_pipeline())
        catalog = build_evidence_catalog(
            journey,
            corpus_analysis_reader=_memory_reader(_analysis_row()),
            corpus_source_reader=_memory_source_reader(),
        )
        corpus_entries = [
            e for e in catalog.entries if e.source_kind == CORPUS_EVIDENCE_SOURCE_KIND
        ]
        self.assertEqual(1, len(corpus_entries))
        entry = corpus_entries[0]

        binding = _binding()
        self.assertEqual(CORPUS_EVIDENCE_SOURCE_KIND, entry.source_kind)
        self.assertEqual("competitor_observation", entry.support_scope)
        self.assertEqual("art_protocol_1", entry.source_id)
        self.assertEqual("page-12", entry.locator)
        self.assertEqual(binding["source_excerpt"], entry.quote)
        self.assertEqual(
            hashlib.sha256(binding["source_excerpt"].encode()).hexdigest(),
            entry.quote_sha256,
        )
        self.assertIn(ANALYSIS_ID, entry.source_revision)
        self.assertIn(DOC_HASH[:16], entry.source_revision)

        prov = entry.provenance
        self.assertEqual(CORPUS_ANALYSIS_LINEAGE, prov["analysis_lineage"])
        self.assertEqual(ANALYSIS_ID, prov["analysis_id"])
        self.assertEqual("f_design_001", prov["finding_id"])
        self.assertEqual("design", prov["module"])
        self.assertEqual(SPAN_HASH, prov["source_text_sha256"])
        self.assertEqual(DOC_HASH, prov["document_sha256"])
        self.assertEqual("competitor_observation", entry.support_scope)

        # Design module allowlist applies.
        self.assertEqual(
            list(corpus_module_target_paths(
                "design",
                transfer_scope="same_indication",
                pattern_kind="clinical_design_requirement",
                reuse_decision="evidence_supported_candidate",
            )),
            entry.supported_target_paths,
        )
        self.assertIn("design.randomization", entry.supported_target_paths)
        self.assertIn("design.blinding", entry.supported_target_paths)

    def test_generation_and_adoption_reconstruct_identical_catalog(self):
        journey = _journey(research_pipeline=_research_pipeline())
        reader = _memory_reader(_analysis_row())
        source_reader = _memory_source_reader()
        first = build_evidence_catalog(
            journey,
            corpus_analysis_reader=reader,
            corpus_source_reader=source_reader,
        )
        second = build_evidence_catalog(
            journey,
            corpus_analysis_reader=reader,
            corpus_source_reader=source_reader,
        )
        self.assertEqual(first.catalog_id, second.catalog_id)
        self.assertEqual(first.catalog_sha256, second.catalog_sha256)
        self.assertEqual(
            first.model_dump(mode="json"),
            second.model_dump(mode="json"),
        )

    def test_different_analysis_changes_catalog_identity(self):
        base_journey = _journey(research_pipeline=_research_pipeline())
        base = build_evidence_catalog(
            base_journey,
            corpus_analysis_reader=_memory_reader(_analysis_row()),
            corpus_source_reader=_memory_source_reader(),
        )
        other_payload = _analysis_payload(
            _finding(finding_id="f_other", statement="另一条竞品观察。")
        )
        other_payload["analysis_id"] = "mwca_other000000000000000"
        other_journey = _journey(
            research_pipeline=_research_pipeline(
                round1_analysis_id="mwca_other000000000000000",
                round1_analysis_output_hash=_hash_json(other_payload),
            )
        )
        other = build_evidence_catalog(
            other_journey,
            corpus_analysis_reader=_memory_reader(
                _analysis_row(
                    payload=other_payload,
                    analysis_id="mwca_other000000000000000",
                    output_hash=_hash_json(other_payload),
                )
            ),
            corpus_source_reader=_memory_source_reader(),
        )
        self.assertNotEqual(base.catalog_sha256, other.catalog_sha256)
        self.assertEqual(other.catalog_id, base.catalog_id)  # same journey/snapshot

    def test_same_quote_two_findings_two_entries(self):
        binding = _binding()
        payload = _analysis_payload(
            _finding(finding_id="f_design_001"),
            _finding(
                finding_id="f_design_002",
                module="statistics",
                statement="统计方法。",
            ),
        )
        # Both findings bind the same source excerpt.
        payload["findings"][1]["evidence_bindings"] = [binding]
        row = _analysis_row(payload=payload, output_hash=_hash_json(payload))
        entries = build_corpus_analysis_entries(row, "catalog_1")
        self.assertEqual(2, len(entries))
        self.assertEqual(
            {e.provenance["finding_id"] for e in entries},
            {"f_design_001", "f_design_002"},
        )
        self.assertNotEqual(entries[0].catalog_entry_id, entries[1].catalog_entry_id)

    def test_prebuilt_entries_catalog_id_mismatch_rejected(self):
        journey = _journey()
        from packages.contracts.workbench_contracts import (
            AuthoringPrefillEvidenceCatalogEntry,
        )

        foreign = AuthoringPrefillEvidenceCatalogEntry(
            catalog_entry_id="x" * 32,
            catalog_id="other_catalog",
            source_kind=CORPUS_EVIDENCE_SOURCE_KIND,
            source_id="s",
            quote="quote",
            quote_sha256=hashlib.sha256(b"quote").hexdigest(),
            support_scope="competitor_observation",
        )
        with self.assertRaises(CorpusPrefillBridgeError):
            build_evidence_catalog(journey, corpus_entries=[foreign])


# ---------------------------------------------------------------------------
# Conservative target-path allowlist
# ---------------------------------------------------------------------------


class TargetPathAllowlistTests(unittest.TestCase):

    def test_cross_indication_structure_only_supports_nothing(self):
        self.assertEqual(
            (),
            corpus_module_target_paths(
                "structure",
                transfer_scope="cross_indication_structure_only",
                pattern_kind="regulatory_common_structure",
                reuse_decision="evidence_supported_candidate",
            ),
        )
        # Even a normally clinical module is blocked when the finding is
        # cross-indication structure only.
        self.assertEqual(
            (),
            corpus_module_target_paths(
                "design",
                transfer_scope="cross_indication_structure_only",
            ),
        )

    def test_wording_convention_supports_nothing(self):
        self.assertEqual(
            (),
            corpus_module_target_paths(
                "intervention",
                transfer_scope="same_indication",
                pattern_kind="wording_convention",
            ),
        )

    def test_conflict_preserved_finding_supports_nothing(self):
        for decision in CONFLICT_PRESERVED_REUSE_DECISIONS:
            self.assertEqual(
                (),
                corpus_module_target_paths(
                    "eligibility",
                    transfer_scope="same_indication",
                    pattern_kind="clinical_design_requirement",
                    reuse_decision=decision,
                ),
            )

    def test_insufficient_support_finding_keeps_bounded_paths(self):
        # Single-source competitor observations stay available as limited
        # review candidates with the module's bounded paths.
        paths = corpus_module_target_paths(
            "eligibility",
            transfer_scope="same_indication",
            pattern_kind="clinical_design_requirement",
            reuse_decision=INSUFFICIENT_SUPPORT_REUSE_DECISION,
        )
        self.assertIn("picos.population_summary", paths)
        self.assertIn("picos.washout_rules", paths)
        self.assertNotIn("picos.aesi_definitions", paths)

    def test_structure_entries_created_but_unsupported(self):
        payload = _analysis_payload(
            _finding(
                finding_id="f_struct_001",
                module="structure",
                pattern_kind="regulatory_common_structure",
                transfer_scope="cross_indication_structure_only",
                reuse_decision="medical_review_required",
                confidence="low",
            )
        )
        row = _analysis_row(payload=payload, output_hash=_hash_json(payload))
        entries = build_corpus_analysis_entries(row, "catalog_1")
        self.assertEqual(1, len(entries))
        self.assertEqual([], entries[0].supported_target_paths)
        self.assertEqual("competitor_observation", entries[0].support_scope)

    def test_conflict_entries_created_but_unsupported(self):
        payload = _analysis_payload(
            _finding(reuse_decision="conflict_preserved_do_not_select")
        )
        row = _analysis_row(payload=payload, output_hash=_hash_json(payload))
        entries = build_corpus_analysis_entries(row, "catalog_1")
        self.assertEqual(1, len(entries))
        self.assertEqual([], entries[0].supported_target_paths)

    def test_insufficient_support_entries_created_with_bounded_paths(self):
        payload = _analysis_payload(
            _finding(reuse_decision=INSUFFICIENT_SUPPORT_REUSE_DECISION)
        )
        row = _analysis_row(payload=payload, output_hash=_hash_json(payload))
        entries = build_corpus_analysis_entries(row, "catalog_1")
        self.assertEqual(1, len(entries))
        self.assertIn("design.randomization", entries[0].supported_target_paths)
        self.assertEqual("competitor_observation", entries[0].support_scope)

    def test_unknown_module_fails_closed(self):
        payload = _analysis_payload(_finding(module="bogus_module"))
        row = _analysis_row(payload=payload, output_hash=_hash_json(payload))
        with self.assertRaises(CorpusPrefillBridgeError):
            build_corpus_analysis_entries(row, "catalog_1")

    def test_missing_binding_fields_fail_closed(self):
        binding = _binding()
        binding.pop("source_id")
        payload = _analysis_payload(_finding(bindings=[binding]))
        row = _analysis_row(payload=payload, output_hash=_hash_json(payload))
        with self.assertRaises(CorpusPrefillBridgeError):
            build_corpus_analysis_entries(row, "catalog_1")


# ---------------------------------------------------------------------------
# Competitor-option semantics and exact-fact preservation
# ---------------------------------------------------------------------------


class CompetitorSemanticsTests(unittest.TestCase):

    def test_exact_fact_text_stays_competitor_observation(self):
        """Dose / AESI / sample-size / washout text in competitor findings
        never promotes to current_project_fact; all corpus entries remain
        competitor_observation."""
        dose_excerpt = (
            "Arm A receives 600mg Q2W.\n受控中文译文：A组接受600mg每两周一次给药。"
        )
        payload = _analysis_payload(
            _finding(
                finding_id="f_intervention_001",
                module="intervention",
                statement="竞品采用600mg每两周给药方案。",
                bindings=[_binding(excerpt=dose_excerpt, evidence_id="cae_dose")],
            ),
            _finding(
                finding_id="f_safety_001",
                module="safety",
                statement="竞品将溶血危象列为AESI并监测样本量计划。",
                bindings=[
                    _binding(
                        excerpt="AESI monitoring with 200 enrolled.",
                        evidence_id="cae_aesi",
                    )
                ],
            ),
        )
        row = _analysis_row(payload=payload, output_hash=_hash_json(payload))
        entries = build_corpus_analysis_entries(row, "catalog_1")
        self.assertEqual(2, len(entries))
        for entry in entries:
            self.assertEqual("competitor_observation", entry.support_scope)
            self.assertNotEqual("current_project_fact", entry.support_scope)

        by_finding = {
            e.provenance["finding_id"]: e for e in entries
        }
        intervention = by_finding["f_intervention_001"]
        # Dose text is surfaced as competitor evidence; the exact-fact gate
        # lives in binding semantics (competitor_option only), never here.
        self.assertIn("600mg", intervention.quote)
        self.assertIn("picos.intervention_dose_regimen", intervention.supported_target_paths)

        safety = by_finding["f_safety_001"]
        self.assertIn("AESI", safety.quote)
        self.assertIn("picos.aesi_definitions", safety.supported_target_paths)
        # Sample size and washout paths may be informed only as
        # competitor_option; scope is competitor_observation by construction.
        stats = _finding(
            finding_id="f_stats_001",
            module="statistics",
            statement="竞品样本量估算。",
            bindings=[
                _binding(
                    excerpt="Sample size 240 assumed 15% dropout.",
                    evidence_id="cae_stats",
                )
            ],
        )
        stats_payload = _analysis_payload(stats)
        stats_row = _analysis_row(
            payload=stats_payload, output_hash=_hash_json(stats_payload)
        )
        stats_entries = build_corpus_analysis_entries(stats_row, "catalog_1")
        self.assertEqual("competitor_observation", stats_entries[0].support_scope)
        self.assertIn(
            "picos.sample_size_strategy",
            stats_entries[0].supported_target_paths,
        )


# ---------------------------------------------------------------------------
# Hash equivalence and read-only reader
# ---------------------------------------------------------------------------


class HashAndReaderTests(unittest.TestCase):

    def test_analysis_output_hash_matches_corpus_service_hash(self):
        payload = _analysis_payload(_finding())
        self.assertEqual(_hash_json(payload), analysis_output_hash(payload))

    def test_read_only_reader_reads_persisted_row(self):
        row = _analysis_row()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "writing_reference.sqlite3"
            connection = sqlite3.connect(db_path)
            connection.execute(
                """
                CREATE TABLE writing_reference_corpus_analysis_runs (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    analysis_id TEXT NOT NULL,
                    pipeline_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    status TEXT NOT NULL,
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
                )
                """
            )
            connection.execute(
                """
                INSERT INTO writing_reference_corpus_analysis_runs(
                    tenant_id, project_id, analysis_id, pipeline_id,
                    snapshot_id, status, prompt_version, schema_version,
                    input_hash, output_hash, route_identity_hash, route_json,
                    input_payload_json, result_json, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "kangzhe_local",
                    PROJECT_ID,
                    ANALYSIS_ID,
                    PIPELINE_ID,
                    SNAPSHOT_ID,
                    "completed",
                    "v9",
                    SCHEMA_VERSION,
                    "b" * 64,
                    row["output_hash"],
                    ROUTE_HASH,
                    json.dumps(row["ai_route"]),
                    "{}",
                    json.dumps(row, ensure_ascii=False),
                    "medical_manager",
                    "2026-07-30T09:00:00+00:00",
                ),
            )
            connection.commit()
            connection.close()

            reader = read_only_analysis_reader(db_path)
            loaded = reader(PROJECT_ID, ANALYSIS_ID)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(ANALYSIS_ID, loaded["analysis_id"])
            self.assertEqual(
                row["output_hash"], loaded["output_hash"]
            )
            self.assertIsNone(reader(PROJECT_ID, "mwca_missing"))

            # The store must be byte-identical after reads: read-only bridge.
            before = db_path.read_bytes()
            reader(PROJECT_ID, ANALYSIS_ID)
            self.assertEqual(before, db_path.read_bytes())

    def test_missing_table_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "empty.sqlite3"
            sqlite3.connect(db_path).close()
            reader = read_only_analysis_reader(db_path)
            with self.assertRaises(CorpusPrefillBridgeError):
                reader(PROJECT_ID, ANALYSIS_ID)

    def test_load_bound_round1_analysis_roundtrip(self):
        journey = _journey(research_pipeline=_research_pipeline())
        row = _analysis_row()
        verified = load_bound_round1_analysis(
            journey, _memory_reader(row)
        )
        self.assertIsNotNone(verified)
        assert verified is not None
        self.assertEqual(row, verified.analysis_row)
        self.assertEqual(PROJECT_ID, verified.identity["project_id"])

    def test_load_unbound_journey_returns_none(self):
        self.assertIsNone(
            load_bound_round1_analysis(_journey(), _memory_reader(None))
        )

    def test_load_bound_with_source_verification(self):
        journey = _journey(research_pipeline=_research_pipeline())
        row = _analysis_row()
        verified = load_bound_round1_analysis(
            journey,
            _memory_reader(row),
            source_reader=_memory_source_reader(),
        )
        self.assertIsNotNone(verified)

    def test_load_bound_with_unverifiable_source_fails_closed(self):
        journey = _journey(research_pipeline=_research_pipeline())
        row = _analysis_row()
        with self.assertRaises(CorpusPrefillBridgeError):
            load_bound_round1_analysis(
                journey,
                _memory_reader(row),
                source_reader=_memory_source_reader(
                    missing=(("art_protocol_1", "span_001"),)
                ),
            )


# ---------------------------------------------------------------------------
# Single-source (insufficient-support) competitor semantics
# ---------------------------------------------------------------------------


class SingleSourceOptionTests(unittest.TestCase):
    """Real round-1 analyses are dominated by
    insufficient_support_do_not_generalize findings.  Single-source
    competitor observations stay available as EXPLICITLY LIMITED review
    candidates with bounded module paths — never zero-path context-only."""

    def test_insufficient_support_supports_module_bounded_paths(self):
        paths = corpus_module_target_paths(
            "design",
            transfer_scope="same_indication",
            pattern_kind="clinical_design_requirement",
            reuse_decision=INSUFFICIENT_SUPPORT_REUSE_DECISION,
        )
        self.assertIn("design.randomization", paths)
        self.assertIn("picos.design_archetype", paths)
        self.assertNotIn("picos.aesi_definitions", paths)

    def test_conflict_preserved_remains_unbindable(self):
        self.assertEqual(
            (),
            corpus_module_target_paths(
                "design",
                transfer_scope="same_indication",
                pattern_kind="clinical_design_requirement",
                reuse_decision="conflict_preserved_do_not_select",
            ),
        )

    def test_insufficient_support_entries_carry_limitation_fields(self):
        payload = _analysis_payload(
            _finding(
                finding_id="f_design_001",
                module="design",
                reuse_decision=INSUFFICIENT_SUPPORT_REUSE_DECISION,
                bindings=[_binding(evidence_id="cae_single")],
            )
        )
        row = _analysis_row(payload=payload, output_hash=_hash_json(payload))
        entries = build_corpus_analysis_entries(row, "catalog_1")
        self.assertEqual(1, len(entries))
        entry = entries[0]
        self.assertEqual("competitor_observation", entry.support_scope)
        self.assertIn("design.randomization", entry.supported_target_paths)
        prov = entry.provenance
        self.assertEqual(
            INSUFFICIENT_SUPPORT_REUSE_DECISION, prov["reuse_decision"]
        )
        self.assertTrue(prov["limitation_note"])
        self.assertEqual(2, prov["source_count"])
        self.assertEqual(2, prov["sponsor_count"])
        self.assertIsInstance(prov["unresolved_gaps"], list)
        self.assertEqual("verified_same", prov["indication_alignment_status"])

    def test_real_shape_all_insufficient_support_keeps_bounded_paths(self):
        """Mirror of the real round-1 shape (7 findings, design/eligibility/
        statistics, all insufficient-support): every corpus entry must keep
        bounded module paths instead of collapsing to zero."""
        payload = _analysis_payload(
            _finding(
                finding_id="f1",
                module="design",
                reuse_decision=INSUFFICIENT_SUPPORT_REUSE_DECISION,
                bindings=[_binding(evidence_id="e1")],
            ),
            _finding(
                finding_id="f2",
                module="design",
                reuse_decision=INSUFFICIENT_SUPPORT_REUSE_DECISION,
                bindings=[
                    _binding(evidence_id="e2a", locator="page-12"),
                    _binding(
                        evidence_id="e2b",
                        locator="page-20",
                        span_id="span_002",
                    ),
                ],
            ),
            _finding(
                finding_id="f3",
                module="eligibility",
                reuse_decision=INSUFFICIENT_SUPPORT_REUSE_DECISION,
                bindings=[_binding(evidence_id="e3")],
            ),
            _finding(
                finding_id="f4",
                module="statistics",
                reuse_decision=INSUFFICIENT_SUPPORT_REUSE_DECISION,
                bindings=[_binding(evidence_id="e4")],
            ),
        )
        row = _analysis_row(payload=payload, output_hash=_hash_json(payload))
        journey = _journey(
            research_pipeline=_research_pipeline(
                round1_analysis_output_hash=_hash_json(payload)
            )
        )
        catalog = build_evidence_catalog(
            journey,
            corpus_analysis_reader=_memory_reader(row),
            corpus_source_reader=_memory_source_reader(
                locators_by_span={"span_001": "page-12", "span_002": "page-20"}
            ),
        )
        corpus_entries = [
            e
            for e in catalog.entries
            if e.source_kind == CORPUS_EVIDENCE_SOURCE_KIND
        ]
        self.assertEqual(5, len(corpus_entries))
        for entry in corpus_entries:
            self.assertTrue(
                entry.supported_target_paths,
                f"entry {entry.catalog_entry_id} must keep bounded paths",
            )
            self.assertEqual("competitor_observation", entry.support_scope)


# ---------------------------------------------------------------------------
# pending_decision enforcement for limited corpus candidates
# ---------------------------------------------------------------------------


class PendingDecisionEnforcementTests(unittest.TestCase):

    def setUp(self):
        self.payload = _analysis_payload(
            _finding(
                finding_id="f_design_001",
                module="design",
                reuse_decision=INSUFFICIENT_SUPPORT_REUSE_DECISION,
                bindings=[_binding(evidence_id="cae_limited")],
            ),
            _finding(
                finding_id="f_conflict_001",
                module="design",
                reuse_decision="conflict_preserved_do_not_select",
                bindings=[_binding(evidence_id="cae_conflict")],
            ),
        )
        self.row = _analysis_row(
            payload=self.payload, output_hash=_hash_json(self.payload)
        )
        self.journey = _journey(
            research_pipeline=_research_pipeline(
                round1_analysis_output_hash=_hash_json(self.payload)
            )
        )
        self.catalog = build_evidence_catalog(
            self.journey,
            corpus_analysis_reader=_memory_reader(self.row),
            corpus_source_reader=_memory_source_reader(),
        )
        by_finding: dict[str, Any] = {}
        for entry in self.catalog.entries:
            if entry.source_kind == CORPUS_EVIDENCE_SOURCE_KIND:
                by_finding.setdefault(
                    entry.provenance["finding_id"], []
                ).append(entry)
        self.limited = by_finding["f_design_001"][0]
        self.conflict = by_finding["f_conflict_001"][0]

    def _rebind(
        self,
        entry,
        target_path: str,
        support_kind: str = "competitor_option",
        role: str = "pending_decision",
    ):
        return validate_and_rebind_candidates(
            catalog=self.catalog,
            sent_entry_ids={e.catalog_entry_id for e in self.catalog.entries},
            model_output={
                "catalog_id": self.catalog.catalog_id,
                "catalog_sha256": self.catalog.catalog_sha256,
                "field_suggestions": {
                    target_path: [
                        {
                            "structured_value": "randomized",
                            "preview": "randomized",
                            "rationale": "test",
                            "recommendation_role": role,
                            "claim_bindings": [
                                {
                                    "target_path": target_path,
                                    "value_pointer": "",
                                    "catalog_entry_id": entry.catalog_entry_id,
                                    "support_kind": support_kind,
                                }
                            ],
                        }
                    ]
                },
            },
            condition_term_path="framing.clinicaltrials_condition_term",
            eligible_field_paths={target_path},
            package_target_paths={},
        )

    def test_pending_decision_accepted(self):
        out = self._rebind(self.limited, "design.randomization")
        cands = out[3].get("design.randomization", [])
        self.assertEqual(1, len(cands), out[4])
        self.assertEqual("pending_decision", cands[0].recommendation_role)
        self.assertEqual(
            "competitor_option", cands[0].claim_bindings[0].support_kind
        )
        self.assertTrue(cands[0].evidence_gaps)
        self.assertTrue(
            any(
                "不得视为当前项目事实" in gap
                for gap in cands[0].evidence_gaps
            )
        )
        self.assertIn(
            self.limited.provenance["limitation_note"],
            cands[0].evidence_gaps,
        )

    def test_omitted_role_defaults_to_pending_decision(self):
        out = self._rebind(self.limited, "design.randomization", role="")
        cands = out[3].get("design.randomization", [])
        self.assertEqual(1, len(cands), out[4])
        self.assertEqual("pending_decision", cands[0].recommendation_role)

    def test_recommended_role_rejected(self):
        out = self._rebind(self.limited, "design.randomization", role="recommended")
        self.assertEqual([], out[3].get("design.randomization", []))
        self.assertTrue(any("pending_decision" in e for e in out[4]))

    def test_alternative_role_rejected(self):
        out = self._rebind(self.limited, "design.randomization", role="alternative")
        self.assertEqual([], out[3].get("design.randomization", []))
        self.assertTrue(any("pending_decision" in e for e in out[4]))

    def test_exact_fact_never_allowed_on_limited_entry(self):
        out = self._rebind(
            self.limited, "design.randomization", support_kind="exact_fact"
        )
        self.assertEqual([], out[3].get("design.randomization", []))
        self.assertTrue(any("competitor_option" in e for e in out[4]))

    def test_conflict_entry_unbindable_even_as_pending(self):
        out = self._rebind(self.conflict, "design.randomization")
        self.assertEqual([], out[3].get("design.randomization", []))
        self.assertTrue(any("supports no target paths" in e for e in out[4]))

    def test_limited_entry_not_eligible_for_other_modules(self):
        proj = project_catalog_for_model(
            self.catalog,
            deterministic_field_paths=set(),
            package_target_paths={},
        )
        self.assertIn(
            self.limited.catalog_entry_id,
            proj["eligible_entry_ids_by_target_path"].get(
                "design.randomization", []
            ),
        )
        self.assertNotIn(
            self.limited.catalog_entry_id,
            proj["eligible_entry_ids_by_target_path"].get(
                "picos.aesi_definitions", []
            ),
        )
        # Limitation fields are forwarded to the model projection.
        projected = {
            e["catalog_entry_id"]: e
            for e in proj["evidence_entries"]
        }
        prov = projected[self.limited.catalog_entry_id]["provenance"]
        self.assertEqual(
            INSUFFICIENT_SUPPORT_REUSE_DECISION, prov["reuse_decision"]
        )
        self.assertTrue(prov["limitation_note"])
        self.assertIn("source_count", prov)

    def test_large_registry_snapshot_cannot_starve_round1_corpus_projection(self):
        registry_entries = []
        for index in range(250):
            quote = f"Registry summary {index}"
            registry_entries.append(
                self.limited.model_copy(
                    update={
                        "catalog_entry_id": f"ctgov_{index:03d}",
                        "source_kind": "ctgov_snapshot",
                        "source_id": f"ctgov:snapshot:NCT{index:08d}",
                        "source_revision": "snapshot:large",
                        "locator": f"ctgov:NCT{index:08d}:brief_summary",
                        "quote": quote,
                        "quote_sha256": hashlib.sha256(
                            quote.encode("utf-8")
                        ).hexdigest(),
                        "title": f"Registry entry {index}",
                        "supported_target_paths": [
                            "picos.population_summary"
                        ],
                        "provenance": {
                            "field_key": "brief_summary",
                            "nct_id": f"NCT{index:08d}",
                            "snapshot_id": "snapshot:large",
                        },
                    }
                )
            )
        flooded = self.catalog.model_copy(
            update={"entries": registry_entries + list(self.catalog.entries)}
        )

        projection = project_catalog_for_model(
            flooded,
            deterministic_field_paths=set(),
            package_target_paths={},
        )

        self.assertEqual(200, len(projection["evidence_entries"]))
        self.assertIn(
            self.limited.catalog_entry_id, projection["sent_entry_ids"]
        )
        self.assertIn(
            self.conflict.catalog_entry_id, projection["sent_entry_ids"]
        )
        self.assertIn(
            self.limited.catalog_entry_id,
            projection["eligible_entry_ids_by_target_path"][
                "design.randomization"
            ],
        )

    def test_verified_design_quote_always_materializes_review_only_option(self):
        design_paths = [
            "design.randomization",
            "design.blinding",
            "design.comparator_type",
            "design.assignment_model",
            "design.center_model",
            "design.adaptive_design",
        ]
        candidates, errors = build_round1_corpus_review_candidates(
            catalog=self.catalog,
            sent_entry_ids={
                entry.catalog_entry_id for entry in self.catalog.entries
            },
            package_target_paths={"package.design": design_paths},
        )

        self.assertEqual([], errors)
        self.assertEqual(1, len(candidates))
        candidate = candidates[0]
        self.assertEqual("pending_decision", candidate.recommendation_role)
        self.assertEqual(
            "partially_supported", candidate.evidence_status
        )
        self.assertEqual(
            "随机", candidate.structured_value["design.randomization"]
        )
        self.assertEqual(
            "双盲", candidate.structured_value["design.blinding"]
        )
        self.assertEqual(
            "安慰剂对照",
            candidate.structured_value["design.comparator_type"],
        )
        self.assertTrue(candidate.evidence_gaps)
        self.assertTrue(
            all(
                binding.catalog_entry_id == self.limited.catalog_entry_id
                and binding.support_kind == "competitor_option"
                for binding in candidate.claim_bindings
            )
        )
        self.assertFalse(
            {
                "picos.primary_endpoint",
                "picos.sample_size_strategy",
                "picos.washout_rules",
            }.intersection(candidate.structured_value)
        )

    def test_adoption_helper_detects_limited_candidates(self):
        from packages.contracts.workbench_contracts import (
            AuthoringPrefillCandidate,
            AuthoringPrefillClaimBinding,
        )

        entry_lookup = {e.catalog_entry_id: e for e in self.catalog.entries}

        def _candidate(role: str) -> AuthoringPrefillCandidate:
            return AuthoringPrefillCandidate(
                candidate_id="c1",
                field_path="design.randomization",
                structured_value="randomized",
                preview="randomized",
                recommendation_role=role,
                claim_bindings=[
                    AuthoringPrefillClaimBinding(
                        target_path="design.randomization",
                        value_pointer="",
                        catalog_entry_id=self.limited.catalog_entry_id,
                        source_id=self.limited.source_id,
                        locator=self.limited.locator,
                        quote_sha256=self.limited.quote_sha256,
                        support_kind="competitor_option",
                    )
                ],
            )

        self.assertTrue(
            server_candidate_requires_pending_decision(
                _candidate("recommended"), entry_lookup
            )
        )
        self.assertTrue(
            server_candidate_requires_pending_decision(
                _candidate("pending_decision"), entry_lookup
            )
        )
        # A candidate bound only to project facts is not limited.
        fact_entry = next(
            e
            for e in self.catalog.entries
            if e.support_scope == "current_project_fact"
        )
        plain = _candidate("recommended").model_copy(
            update={
                "claim_bindings": [
                    AuthoringPrefillClaimBinding(
                        target_path="framing.population_intent",
                        value_pointer="",
                        catalog_entry_id=fact_entry.catalog_entry_id,
                        source_id=fact_entry.source_id,
                        locator=fact_entry.locator,
                        quote_sha256=fact_entry.quote_sha256,
                        support_kind="exact_fact",
                    )
                ]
            }
        )
        self.assertFalse(
            server_candidate_requires_pending_decision(plain, entry_lookup)
        )

    def test_adoption_verifier_rejects_promoted_limited_candidate(self):
        from datetime import datetime as _datetime

        from packages.contracts.workbench_contracts import (
            AuthoringPrefillCandidate,
            AuthoringPrefillClaimBinding,
            AuthoringPrefillPackage,
        )
        from services.api.app.medical_writing_authoring_prefill import (
            ServerEvidenceVerifier,
        )

        entry_lookup = {e.catalog_entry_id: e for e in self.catalog.entries}
        package = AuthoringPrefillPackage(
            package_id="pkg_1",
            project_id=self.journey.project_id,
            package_revision=1,
            journey_revision=self.journey.revision,
            search_snapshot_id=self.catalog.snapshot_id,
            input_fingerprint="a" * 64,
            search_fingerprint="a" * 64,
            corpus_fingerprint="a" * 64,
            evidence_catalog=self.catalog,
            generated_at=_datetime.now(),
            updated_at=_datetime.now(),
        )
        candidate = AuthoringPrefillCandidate(
            candidate_id="c1",
            field_path="design.randomization",
            structured_value={"design.randomization": "randomized"},
            preview="randomized",
            recommendation_role="recommended",
            candidate_scope="module",
            target_paths=["design.randomization"],
            evidence_catalog_id=self.catalog.catalog_id,
            evidence_catalog_sha256=self.catalog.catalog_sha256,
            claim_bindings=[
                AuthoringPrefillClaimBinding(
                    target_path="design.randomization",
                    value_pointer="/design.randomization",
                    catalog_entry_id=self.limited.catalog_entry_id,
                    source_id=self.limited.source_id,
                    locator=self.limited.locator,
                    quote_sha256=self.limited.quote_sha256,
                    support_kind="competitor_option",
                )
            ],
        )
        verifier = ServerEvidenceVerifier(
            catalog_resolver=lambda: self.catalog
        )
        self.assertFalse(
            verifier.verify_candidate_path(
                project_id=self.journey.project_id,
                package=package,
                candidate=candidate,
                target_path="design.randomization",
                proposed_value="randomized",
            )
        )
        # Same candidate with pending_decision passes the role gate (rest of
        # the verification is exercised by the composite-adopt suites).
        pending = candidate.model_copy(
            update={"recommendation_role": "pending_decision"}
        )
        self.assertTrue(
            verifier.verify_candidate_path(
                project_id=self.journey.project_id,
                package=package,
                candidate=pending,
                target_path="design.randomization",
                proposed_value="randomized",
            )
        )


# ---------------------------------------------------------------------------
# Source-binding integrity verification (read-only)
# ---------------------------------------------------------------------------


class SourceBindingVerificationTests(unittest.TestCase):

    def _build(self, source_reader, payload=None):
        payload = payload or _analysis_payload(_finding())
        row = _analysis_row(payload=payload, output_hash=_hash_json(payload))
        journey = _journey(
            research_pipeline=_research_pipeline(
                round1_analysis_output_hash=_hash_json(payload)
            )
        )
        return build_evidence_catalog(
            journey,
            corpus_analysis_reader=_memory_reader(row),
            corpus_source_reader=source_reader,
        )

    def test_valid_source_bindings_admitted(self):
        catalog = self._build(_memory_source_reader())
        self.assertEqual(1, len(catalog.entries) - 3)

    def test_missing_span_or_artifact_fails_closed(self):
        with self.assertRaises(CorpusPrefillBridgeError):
            self._build(
                _memory_source_reader(
                    missing=(("art_protocol_1", "span_001"),)
                )
            )

    def test_document_hash_mismatch_fails_closed(self):
        with self.assertRaises(CorpusPrefillBridgeError):
            self._build(
                _memory_source_reader(
                    _source_composite(artifact_content_sha256="9" * 64)
                )
            )

    def test_span_text_hash_mismatch_fails_closed(self):
        with self.assertRaises(CorpusPrefillBridgeError):
            self._build(
                _memory_source_reader(
                    _source_composite(span_source_text_sha256="9" * 64)
                )
            )

    def test_span_artifact_identity_mismatch_fails_closed(self):
        with self.assertRaises(CorpusPrefillBridgeError):
            self._build(
                _memory_source_reader(
                    _source_composite(span_artifact_id="other_artifact")
                )
            )

    def test_invalidated_source_fails_closed(self):
        with self.assertRaises(CorpusPrefillBridgeError):
            self._build(
                _memory_source_reader(
                    _source_composite(source_current=False)
                )
            )

    def test_binding_missing_hash_fields_fail_closed(self):
        binding = _binding()
        binding.pop("source_text_sha256")
        payload = _analysis_payload(_finding(bindings=[binding]))
        with self.assertRaises(CorpusPrefillBridgeError):
            self._build(_memory_source_reader(), payload=payload)

    def test_read_only_source_reader_over_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "writing_reference.sqlite3"
            connection = sqlite3.connect(db_path)
            connection.execute(
                """
                CREATE TABLE writing_reference_document_artifacts (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    nct_id TEXT NOT NULL,
                    source_document_id TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    storage_relpath TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, artifact_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE writing_reference_document_state (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    source_current INTEGER NOT NULL,
                    invalidation_reason TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, artifact_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE writing_reference_source_spans (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    span_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    extraction_revision TEXT NOT NULL,
                    ich_m11_anchor TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, span_id)
                )
                """
            )
            connection.execute(
                """
                INSERT INTO writing_reference_document_artifacts(
                    tenant_id, project_id, artifact_id, snapshot_id, nct_id,
                    source_document_id, content_sha256, storage_relpath,
                    payload_hash, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_ID,
                    PROJECT_ID,
                    "art_protocol_1",
                    SNAPSHOT_ID,
                    "NCT00000001",
                    "protocol.pdf",
                    DOC_HASH,
                    "path",
                    "payload_hash",
                    "{}",
                    "2026-07-30T09:00:00+00:00",
                ),
            )
            connection.execute(
                """
                INSERT INTO writing_reference_document_state(
                    tenant_id, project_id, artifact_id, revision,
                    source_current, invalidation_reason, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (TENANT_ID, PROJECT_ID, "art_protocol_1", 3, 1, "", "2026-07-30T09:00:00+00:00"),
            )
            span_payload = json.dumps(
                {
                    "span_id": "span_001",
                    "project_id": PROJECT_ID,
                    "artifact_id": "art_protocol_1",
                    "extraction_revision": "r3",
                    "physical_page": 12,
                    "block_index": 0,
                    "source_locator": "page-12",
                    "source_text": "text",
                    "source_text_sha256": SPAN_HASH,
                },
                ensure_ascii=False,
            )
            connection.execute(
                """
                INSERT INTO writing_reference_source_spans(
                    tenant_id, project_id, span_id, artifact_id,
                    extraction_revision, ich_m11_anchor, payload_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_ID,
                    PROJECT_ID,
                    "span_001",
                    "art_protocol_1",
                    "r3",
                    "unmapped",
                    span_payload,
                    "2026-07-30T09:00:00+00:00",
                ),
            )
            connection.commit()
            connection.close()

            source_reader = read_only_source_binding_reader(db_path)
            composite = source_reader(PROJECT_ID, "art_protocol_1", "span_001")
            self.assertIsNotNone(composite)
            assert composite is not None
            self.assertEqual(DOC_HASH, composite["artifact_content_sha256"])
            self.assertTrue(composite["source_current"])
            self.assertEqual("art_protocol_1", composite["span_artifact_id"])
            self.assertEqual(SPAN_HASH, composite["span_source_text_sha256"])
            # The immutable span's own locator is exposed and must equal the
            # persisted binding locator ("page-12").
            self.assertEqual("page-12", composite["span_source_locator"])
            # Missing span -> None (bridge then fails closed).
            self.assertIsNone(source_reader(PROJECT_ID, "art_protocol_1", "span_missing"))
            # Missing artifact -> None.
            self.assertIsNone(source_reader(PROJECT_ID, "art_missing", "span_001"))

            # End-to-end: the SQLite-backed source reader + analysis reader
            # reconstruct the catalog (the analysis row comes from the
            # analysis-runs table created by the analysis-reader test; here
            # the memory reader stands in for it).
            row = _analysis_row()
            journey = _journey(research_pipeline=_research_pipeline())
            catalog = build_evidence_catalog(
                journey,
                corpus_analysis_reader=_memory_reader(row),
                corpus_source_reader=source_reader,
            )
            self.assertEqual(4, len(catalog.entries))

            # A persisted binding whose locator drifted from the immutable
            # span locator fails closed end to end over the SQLite reader.
            bad_payload = _analysis_payload(
                _finding(bindings=[_binding(locator="page-99")])
            )
            bad_row = _analysis_row(
                payload=bad_payload, output_hash=_hash_json(bad_payload)
            )
            bad_journey = _journey(
                research_pipeline=_research_pipeline(
                    round1_analysis_output_hash=_hash_json(bad_payload)
                )
            )
            with self.assertRaises(CorpusPrefillBridgeError):
                build_evidence_catalog(
                    bad_journey,
                    corpus_analysis_reader=_memory_reader(bad_row),
                    corpus_source_reader=source_reader,
                )

            # Read-only: the store must be byte-identical after reads.
            before = db_path.read_bytes()
            source_reader(PROJECT_ID, "art_protocol_1", "span_001")
            self.assertEqual(before, db_path.read_bytes())

    def test_read_only_source_reader_fails_closed_on_missing_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "empty.sqlite3"
            sqlite3.connect(db_path).close()
            source_reader = read_only_source_binding_reader(db_path)
            with self.assertRaises(CorpusPrefillBridgeError):
                source_reader(PROJECT_ID, "art_protocol_1", "span_001")


# ---------------------------------------------------------------------------
# Immutable span-locator binding (adversarial gap: the persisted binding
# locator must equal the immutable span's source_locator — in addition to
# artifact/span/hash/current-source checks)
# ---------------------------------------------------------------------------


class LocatorBindingVerificationTests(unittest.TestCase):

    def _build(self, source_reader, payload=None):
        payload = payload or _analysis_payload(_finding())
        row = _analysis_row(payload=payload, output_hash=_hash_json(payload))
        journey = _journey(
            research_pipeline=_research_pipeline(
                round1_analysis_output_hash=_hash_json(payload)
            )
        )
        return build_evidence_catalog(
            journey,
            corpus_analysis_reader=_memory_reader(row),
            corpus_source_reader=source_reader,
        )

    def test_valid_locator_admitted(self):
        catalog = self._build(_memory_source_reader())
        self.assertEqual(4, len(catalog.entries))

    def test_span_locator_mismatch_fails_closed(self):
        # Binding locator is "page-12"; the immutable span's own locator is
        # a different page — the whole load must be rejected.
        with self.assertRaises(CorpusPrefillBridgeError):
            self._build(
                _memory_source_reader(
                    _source_composite(span_source_locator="page-99")
                )
            )

    def test_empty_binding_locator_fails_closed(self):
        binding = _binding()
        binding["locator"] = ""
        payload = _analysis_payload(_finding(bindings=[binding]))
        with self.assertRaises(CorpusPrefillBridgeError):
            self._build(_memory_source_reader(), payload=payload)

    def test_missing_span_locator_fails_closed(self):
        # Schema drift: the span payload has no source_locator at all.
        composite = _source_composite()
        del composite["span_source_locator"]
        with self.assertRaises(CorpusPrefillBridgeError):
            self._build(_memory_source_reader(composite))


# ---------------------------------------------------------------------------
# Single-source design narrative package semantics (adversarial gap: a
# design PACKAGE candidate bound to insufficient-support corpus evidence
# survives only as pending_decision / competitor_option)
# ---------------------------------------------------------------------------


class SingleSourceDesignPackageTests(unittest.TestCase):
    """A single-source design narrative without prohibited exact facts may
    survive as a design package candidate only as
    ``recommendation_role="pending_decision"`` with
    ``support_kind="competitor_option"`` — never recommended/alternative,
    never exact_fact."""

    def setUp(self):
        self.payload = _analysis_payload(
            _finding(
                finding_id="f_design_001",
                module="design",
                reuse_decision=INSUFFICIENT_SUPPORT_REUSE_DECISION,
                statement="单一来源竞品方案采用随机、双盲设计。",
                bindings=[_binding(evidence_id="cae_design_single")],
            )
        )
        self.row = _analysis_row(
            payload=self.payload, output_hash=_hash_json(self.payload)
        )
        self.journey = _journey(
            research_pipeline=_research_pipeline(
                round1_analysis_output_hash=_hash_json(self.payload)
            )
        )
        self.catalog = build_evidence_catalog(
            self.journey,
            corpus_analysis_reader=_memory_reader(self.row),
            corpus_source_reader=_memory_source_reader(),
        )
        self.entry = next(
            e
            for e in self.catalog.entries
            if e.source_kind == CORPUS_EVIDENCE_SOURCE_KIND
        )
        self.target_paths = ["design.randomization", "design.blinding"]

    def _rebind_package(self, role: str, support_kind: str = "competitor_option"):
        return validate_and_rebind_candidates(
            catalog=self.catalog,
            sent_entry_ids={e.catalog_entry_id for e in self.catalog.entries},
            model_output={
                "catalog_id": self.catalog.catalog_id,
                "catalog_sha256": self.catalog.catalog_sha256,
                "package_suggestions": {
                    "package.design": [
                        {
                            "structured_value": {
                                "design.randomization": "randomized",
                                "design.blinding": "double-blind",
                            },
                            "preview": "随机双盲设计",
                            "rationale": "参考单一来源竞品方案。",
                            "recommendation_role": role,
                            "target_paths": list(self.target_paths),
                            "claim_bindings": [
                                {
                                    "target_path": target_path,
                                    "value_pointer": f"/{target_path}",
                                    "catalog_entry_id": self.entry.catalog_entry_id,
                                    "support_kind": support_kind,
                                }
                                for target_path in self.target_paths
                            ],
                        }
                    ]
                },
            },
            condition_term_path="framing.clinicaltrials_condition_term",
            eligible_field_paths=set(),
            package_target_paths={"package.design": list(self.target_paths)},
        )

    def test_design_package_survives_only_as_pending_decision(self):
        out = self._rebind_package("pending_decision")
        cands = out[2].get("package.design", [])
        self.assertEqual(1, len(cands), out[4])
        cand = cands[0]
        self.assertEqual("pending_decision", cand.recommendation_role)
        self.assertEqual("manual_only", cand.adoption_mode)
        self.assertEqual("partially_supported", cand.evidence_status)
        for binding in cand.claim_bindings:
            self.assertEqual("competitor_option", binding.support_kind)
            self.assertEqual(self.entry.source_id, binding.source_id)
            self.assertEqual(self.entry.locator, binding.locator)
            self.assertEqual(self.entry.quote_sha256, binding.quote_sha256)

    def test_design_package_recommended_rejected(self):
        out = self._rebind_package("recommended")
        self.assertEqual([], out[2].get("package.design", []))
        self.assertTrue(any("pending_decision" in e for e in out[4]))

    def test_design_package_alternative_rejected(self):
        out = self._rebind_package("alternative")
        self.assertEqual([], out[2].get("package.design", []))
        self.assertTrue(any("pending_decision" in e for e in out[4]))

    def test_design_package_exact_fact_rejected(self):
        out = self._rebind_package("pending_decision", support_kind="exact_fact")
        self.assertEqual([], out[2].get("package.design", []))
        self.assertTrue(any("competitor_option" in e for e in out[4]))


# ---------------------------------------------------------------------------
# Exact-fact quality gate preservation (adversarial gap: a corpus candidate
# carrying dose / regimen / endpoint / AESI / sample size / washout /
# threshold / visit-timing exact facts stays rejected even when the
# competitor excerpt contains that value)
# ---------------------------------------------------------------------------


class ExactFactGatePreservationTests(unittest.TestCase):
    """The existing exact-fact content gate must never be relaxed by the
    corpus bridge: the presence of an exact-fact value in a competitor
    excerpt does not register the value as a project fact, does not satisfy
    the D2 registered-source contract, and a catalog-bound candidate for the
    value survives only as a pending competitor option."""

    # (category, exact-fact value, bindable target path, finding module)
    CATEGORY_CASES = [
        ("dose", "试验药剂量为600mg。", "picos.intervention_dose_regimen", "intervention"),
        ("regimen", "给药频次为每日一次。", "picos.intervention_summary", "intervention"),
        ("endpoint", "主要终点为溶血缓解率。", "picos.primary_endpoint", "objectives_endpoints"),
        ("aesi", "特别关注不良事件为溶血危象。", "picos.aesi_definitions", "safety"),
        ("sample_size", "样本量为240例受试者。", "picos.sample_size_strategy", "statistics"),
        ("washout", "洗脱期为2周。", "picos.washout_rules", "eligibility"),
        ("threshold", "有效阈值为≥30%。", "picos.key_secondary_endpoints", "objectives_endpoints"),
        ("visit_timing", "第12周进行主要评估。", "picos.visit_strategy", "schedule"),
    ]

    def test_d3_gate_detects_every_category(self):
        from services.api.app.medical_writing_authoring_prefill_ai import (
            _detect_exact_fact_content,
        )

        for category, value, _path, _module in self.CATEGORY_CASES:
            self.assertEqual(category, _detect_exact_fact_content(value))

    def test_ai_parse_quarantines_exact_facts_from_corpus_excerpts(self):
        from services.api.app.medical_writing_authoring_prefill_ai import (
            _collect_registered_source_ids,
            _parse_field_suggestions,
        )

        # A competitor protocol artifact is never a registered current-
        # project source; citing it cannot satisfy the D2 exemption.
        journey = _journey(research_pipeline=_research_pipeline())
        registered = _collect_registered_source_ids(journey)
        self.assertNotIn("art_protocol_1", registered)
        self.assertEqual(
            {
                "framing.indication",
                "framing.investigational_product",
                "framing.study_phase",
            },
            set(registered),
        )
        for category, value, field_path, _module in self.CATEGORY_CASES:
            with self.subTest(category=category):
                # Even when the suggestion cites the competitor artifact
                # whose excerpt contains the value, the D3 gate quarantines
                # the candidate.
                out = _parse_field_suggestions(
                    field_path,
                    [
                        {
                            "value": value,
                            "preview": value,
                            "rationale": "参考竞品方案中的表述。",
                            "source_ids": ["art_protocol_1"],
                        }
                    ],
                    registered_source_ids=registered,
                )
                self.assertEqual([], out)
        # A non-exact control suggestion passes the same path.
        control = _parse_field_suggestions(
            "design.randomization",
            [
                {
                    "value": "随机双盲设计",
                    "preview": "随机双盲设计",
                    "rationale": "参考竞品方案。",
                    "source_ids": ["art_protocol_1"],
                }
            ],
            registered_source_ids=registered,
        )
        self.assertEqual(1, len(control))

    def _catalog_with_exact_fact_entry(self, category, value, module):
        payload = _analysis_payload(
            _finding(
                finding_id=f"f_{category}_001",
                module=module,
                reuse_decision=INSUFFICIENT_SUPPORT_REUSE_DECISION,
                statement=value,
                bindings=[_binding(excerpt=value, evidence_id=f"cae_{category}")],
            )
        )
        row = _analysis_row(payload=payload, output_hash=_hash_json(payload))
        journey = _journey(
            research_pipeline=_research_pipeline(
                round1_analysis_output_hash=_hash_json(payload)
            )
        )
        return build_evidence_catalog(
            journey,
            corpus_analysis_reader=_memory_reader(row),
            corpus_source_reader=_memory_source_reader(),
        )

    def test_catalog_bound_exact_fact_stays_competitor_option_only(self):
        for category, value, field_path, module in self.CATEGORY_CASES:
            with self.subTest(category=category):
                catalog = self._catalog_with_exact_fact_entry(
                    category, value, module
                )
                entry = next(
                    e
                    for e in catalog.entries
                    if e.source_kind == CORPUS_EVIDENCE_SOURCE_KIND
                )
                self.assertIn(field_path, entry.supported_target_paths)
                self.assertEqual(value, entry.quote)
                sent = {e.catalog_entry_id for e in catalog.entries}

                def _rebind(support_kind, role):
                    return validate_and_rebind_candidates(
                        catalog=catalog,
                        sent_entry_ids=sent,
                        model_output={
                            "catalog_id": catalog.catalog_id,
                            "catalog_sha256": catalog.catalog_sha256,
                            "field_suggestions": {
                                field_path: [
                                    {
                                        "structured_value": value,
                                        "preview": value,
                                        "rationale": "参考竞品方案。",
                                        "recommendation_role": role,
                                        "claim_bindings": [
                                            {
                                                "target_path": field_path,
                                                "value_pointer": "",
                                                "catalog_entry_id": entry.catalog_entry_id,
                                                "support_kind": support_kind,
                                            }
                                        ],
                                    }
                                ]
                            },
                        },
                        condition_term_path="framing.clinicaltrials_condition_term",
                        eligible_field_paths={field_path},
                        package_target_paths={},
                    )

                # exact_fact promotion is rejected even though the value
                # exists verbatim in the competitor excerpt.
                out = _rebind("exact_fact", "pending_decision")
                self.assertEqual([], out[3].get(field_path, []), out[4])
                self.assertTrue(any("competitor_option" in e for e in out[4]))
                # recommended/alternative promotion is rejected on a
                # single-source finding.
                out = _rebind("competitor_option", "recommended")
                self.assertEqual([], out[3].get(field_path, []), out[4])
                out = _rebind("competitor_option", "alternative")
                self.assertEqual([], out[3].get(field_path, []), out[4])
                # Only pending_decision competitor_option survives, and it
                # is never fully-supported project evidence.
                out = _rebind("competitor_option", "pending_decision")
                cands = out[3].get(field_path, [])
                self.assertEqual(1, len(cands), out[4])
                cand = cands[0]
                self.assertEqual("pending_decision", cand.recommendation_role)
                self.assertEqual(
                    "competitor_option", cand.claim_bindings[0].support_kind
                )
                self.assertEqual("partially_supported", cand.evidence_status)
                self.assertEqual(value, cand.structured_value)


# ---------------------------------------------------------------------------
# Adoption-time promotion rejection (adversarial gap: a persisted limited
# candidate promoted to recommended/alternative is rejected during adoption
# in both resolver modes)
# ---------------------------------------------------------------------------


class AdoptionPromotionRejectionTests(unittest.TestCase):

    def setUp(self):
        from datetime import datetime as _datetime

        from packages.contracts.workbench_contracts import (
            AuthoringPrefillPackage,
        )

        self.payload = _analysis_payload(
            _finding(
                finding_id="f_design_001",
                module="design",
                reuse_decision=INSUFFICIENT_SUPPORT_REUSE_DECISION,
                bindings=[_binding(evidence_id="cae_limited")],
            )
        )
        self.row = _analysis_row(
            payload=self.payload, output_hash=_hash_json(self.payload)
        )
        self.journey = _journey(
            research_pipeline=_research_pipeline(
                round1_analysis_output_hash=_hash_json(self.payload)
            )
        )
        self.catalog = build_evidence_catalog(
            self.journey,
            corpus_analysis_reader=_memory_reader(self.row),
            corpus_source_reader=_memory_source_reader(),
        )
        self.limited = next(
            e
            for e in self.catalog.entries
            if e.source_kind == CORPUS_EVIDENCE_SOURCE_KIND
        )
        self.package = AuthoringPrefillPackage(
            package_id="pkg_promote",
            project_id=self.journey.project_id,
            package_revision=1,
            journey_revision=self.journey.revision,
            search_snapshot_id=self.catalog.snapshot_id,
            input_fingerprint="a" * 64,
            search_fingerprint="a" * 64,
            corpus_fingerprint="a" * 64,
            evidence_catalog=self.catalog,
            generated_at=_datetime.now(),
            updated_at=_datetime.now(),
        )

    def _candidate(self, role: str):
        from packages.contracts.workbench_contracts import (
            AuthoringPrefillCandidate,
            AuthoringPrefillClaimBinding,
        )

        return AuthoringPrefillCandidate(
            candidate_id="c_promoted",
            field_path="design.randomization",
            structured_value={"design.randomization": "randomized"},
            preview="randomized",
            recommendation_role=role,
            candidate_scope="module",
            target_paths=["design.randomization"],
            evidence_catalog_id=self.catalog.catalog_id,
            evidence_catalog_sha256=self.catalog.catalog_sha256,
            claim_bindings=[
                AuthoringPrefillClaimBinding(
                    target_path="design.randomization",
                    value_pointer="/design.randomization",
                    catalog_entry_id=self.limited.catalog_entry_id,
                    source_id=self.limited.source_id,
                    locator=self.limited.locator,
                    quote_sha256=self.limited.quote_sha256,
                    support_kind="competitor_option",
                )
            ],
        )

    def _verify(self, candidate):
        from services.api.app.medical_writing_authoring_prefill import (
            ServerEvidenceVerifier,
        )

        no_resolver = ServerEvidenceVerifier()
        resolver = ServerEvidenceVerifier(
            catalog_resolver=lambda: self.catalog
        )
        return (
            no_resolver.verify_candidate_path(
                project_id=self.journey.project_id,
                package=self.package,
                candidate=candidate,
                target_path="design.randomization",
                proposed_value="randomized",
            ),
            resolver.verify_candidate_path(
                project_id=self.journey.project_id,
                package=self.package,
                candidate=candidate,
                target_path="design.randomization",
                proposed_value="randomized",
            ),
        )

    def test_promoted_recommended_rejected_in_both_modes(self):
        no_resolver, resolver = self._verify(self._candidate("recommended"))
        self.assertFalse(no_resolver)
        self.assertFalse(resolver)

    def test_promoted_alternative_rejected_in_both_modes(self):
        no_resolver, resolver = self._verify(self._candidate("alternative"))
        self.assertFalse(no_resolver)
        self.assertFalse(resolver)

    def test_pending_decision_accepted_in_both_modes(self):
        no_resolver, resolver = self._verify(self._candidate("pending_decision"))
        self.assertTrue(no_resolver)
        self.assertTrue(resolver)


# ---------------------------------------------------------------------------
# Adoption-time catalog reconstruction (adversarial gap: generation and
# adoption rebuild byte-identical catalogs only when both analysis and
# source readers succeed; missing or mismatched source evidence fails closed)
# ---------------------------------------------------------------------------


class ReconstructionFailClosedTests(unittest.TestCase):

    def _catalog(self, analysis_reader, source_reader):
        journey = _journey(research_pipeline=_research_pipeline())
        return build_evidence_catalog(
            journey,
            corpus_analysis_reader=analysis_reader,
            corpus_source_reader=source_reader,
        )

    def test_rebuild_with_missing_analysis_row_fails_closed(self):
        first = self._catalog(_memory_reader(_analysis_row()), _memory_source_reader())
        self.assertEqual(4, len(first.entries))
        # Adoption-time rebuild: the persisted analysis row is gone.
        with self.assertRaises(CorpusPrefillBridgeError):
            self._catalog(_memory_reader(None), _memory_source_reader())

    def test_rebuild_with_mismatched_document_hash_fails_closed(self):
        with self.assertRaises(CorpusPrefillBridgeError):
            self._catalog(
                _memory_reader(_analysis_row()),
                _memory_source_reader(
                    _source_composite(artifact_content_sha256="9" * 64)
                ),
            )

    def test_rebuild_with_mismatched_span_locator_fails_closed(self):
        with self.assertRaises(CorpusPrefillBridgeError):
            self._catalog(
                _memory_reader(_analysis_row()),
                _memory_source_reader(
                    _source_composite(span_source_locator="page-999")
                ),
            )

    def test_rebuild_with_missing_span_fails_closed(self):
        with self.assertRaises(CorpusPrefillBridgeError):
            self._catalog(
                _memory_reader(_analysis_row()),
                _memory_source_reader(
                    missing=(("art_protocol_1", "span_001"),)
                ),
            )

    def test_rebuild_with_same_readers_is_byte_identical(self):
        row = _analysis_row()
        reader = _memory_reader(row)
        source_reader = _memory_source_reader()
        first = self._catalog(reader, source_reader)
        second = self._catalog(reader, source_reader)
        self.assertEqual(first.catalog_id, second.catalog_id)
        self.assertEqual(first.catalog_sha256, second.catalog_sha256)
        self.assertEqual(
            first.model_dump(mode="json"),
            second.model_dump(mode="json"),
        )


# ---------------------------------------------------------------------------
# Journey-input fingerprint and package staleness
# ---------------------------------------------------------------------------


class FingerprintStalenessTests(unittest.TestCase):

    def _fingerprint(self, journey):
        from services.api.app.medical_writing_authoring_prefill import (
            journey_input_fingerprint,
        )

        return journey_input_fingerprint(journey)

    def test_unbound_fingerprint_unchanged(self):
        fp = self._fingerprint(_journey())
        self.assertEqual(64, len(fp))
        # Stable across calls and equivalent to an explicitly empty binding.
        self.assertEqual(fp, self._fingerprint(_journey()))
        self.assertEqual(
            fp, self._fingerprint(_journey(research_pipeline={}))
        )

    def test_bound_fingerprint_differs_from_unbound(self):
        fp_unbound = self._fingerprint(_journey())
        fp_bound = self._fingerprint(
            _journey(research_pipeline=_research_pipeline())
        )
        self.assertNotEqual(fp_unbound, fp_bound)

    def test_analysis_identity_change_alters_fingerprint(self):
        fp = self._fingerprint(
            _journey(research_pipeline=_research_pipeline())
        )
        changed_id = self._fingerprint(
            _journey(
                research_pipeline=_research_pipeline(
                    round1_analysis_id="mwca_other000000000000000"
                )
            )
        )
        changed_hash = self._fingerprint(
            _journey(
                research_pipeline=_research_pipeline(
                    round1_analysis_output_hash="9" * 64
                )
            )
        )
        route = _ai_route()
        route["identity_hash"] = "f" * 64
        changed_route = self._fingerprint(
            _journey(
                research_pipeline=_research_pipeline(round1_ai_route=route)
            )
        )
        self.assertNotEqual(fp, changed_id)
        self.assertNotEqual(fp, changed_hash)
        self.assertNotEqual(fp, changed_route)

    def test_package_is_stale_after_analysis_bound(self):
        from datetime import datetime as _datetime

        from packages.contracts.workbench_contracts import (
            AuthoringPrefillPackage,
        )
        from services.api.app.medical_writing_authoring_prefill import (
            package_is_stale,
            search_fingerprint,
        )

        unbound = _journey()
        package = AuthoringPrefillPackage(
            package_id="pkg_stale",
            project_id=PROJECT_ID,
            package_revision=1,
            journey_revision=1,
            input_fingerprint=self._fingerprint(unbound),
            search_fingerprint=search_fingerprint(unbound, None),
            generated_at=_datetime.now(),
            updated_at=_datetime.now(),
        )
        # Same unbound state: not stale.
        self.assertFalse(package_is_stale(package, unbound))
        # The same journey bound to the round-1 analysis: stale (the package
        # was generated without the analysis identity).
        bound = _journey(research_pipeline=_research_pipeline())
        self.assertTrue(package_is_stale(package, bound))
        # A package generated under the bound analysis is not stale for the
        # same bound state.
        fresh = package.model_copy(
            update={"input_fingerprint": self._fingerprint(bound)}
        )
        self.assertFalse(package_is_stale(fresh, bound))


# ---------------------------------------------------------------------------
# Worker_03 corrective: dual-count wording at the bridge/display boundary
# ---------------------------------------------------------------------------


class DualCountWordingTests(unittest.TestCase):
    """P3-1 corrective: the qualifying support count and the bound original
    source count are visibly distinct; no stale 当前N wording surfaces."""

    def _limited_row(self, unresolved_gaps: list[str]) -> dict:
        payload = _analysis_payload(
            _finding(
                finding_id="f_limited_001",
                module="design",
                reuse_decision=INSUFFICIENT_SUPPORT_REUSE_DECISION,
                bindings=[_binding(evidence_id="cae_limited")],
                unresolved_gaps=unresolved_gaps,
            )
        )
        return _analysis_row(payload=payload, output_hash=_hash_json(payload))

    def test_bridge_rewrites_qualifying_gap_strings(self):
        row = self._limited_row(
            [
                "服务器校验：独立来源不足（当前0，至少需要2）；"
                "不得据此归纳适应症常用措辞或设计规则。",
                "服务器校验：独立申办方不足（当前0，至少需要2）；"
                "需补充其他申办方证据后再评估可迁移性。",
            ]
        )
        entries = build_corpus_analysis_entries(row, "catalog_dual")
        self.assertEqual(1, len(entries))
        gaps = entries[0].provenance["unresolved_gaps"]
        self.assertEqual(
            [
                "可计入本结论通用化门槛的独立来源：0/2；"
                "不得据此归纳适应症常用措辞或设计规则。",
                "可计入本结论通用化门槛的独立申办方：0/2；"
                "需补充其他申办方证据后再评估可迁移性。",
            ],
            gaps,
        )
        self.assertTrue(
            all(
                "当前0" not in gap and "服务器校验" not in gap
                for gap in gaps
            )
        )

    def test_candidate_gaps_show_qualifying_and_live_bound_counts(self):
        row = self._limited_row(
            [
                "服务器校验：独立来源不足（当前0，至少需要2）；"
                "不得据此归纳适应症常用措辞或设计规则。",
            ]
        )
        journey = _journey(
            research_pipeline=_research_pipeline(
                round1_analysis_output_hash=_hash_json(row["analysis"])
            )
        )
        catalog = build_evidence_catalog(
            journey,
            corpus_analysis_reader=_memory_reader(row),
            corpus_source_reader=_memory_source_reader(),
        )
        limited = next(
            e
            for e in catalog.entries
            if e.source_kind == CORPUS_EVIDENCE_SOURCE_KIND
        )
        _cond, _fields, _pkgs, all_c, errors = validate_and_rebind_candidates(
            catalog=catalog,
            sent_entry_ids={e.catalog_entry_id for e in catalog.entries},
            model_output={
                "catalog_id": catalog.catalog_id,
                "catalog_sha256": catalog.catalog_sha256,
                "field_suggestions": {
                    "design.randomization": [
                        {
                            "structured_value": "randomized",
                            "preview": "randomized",
                            "rationale": "test",
                            "recommendation_role": "pending_decision",
                            "claim_bindings": [
                                {
                                    "target_path": "design.randomization",
                                    "value_pointer": "",
                                    "catalog_entry_id": limited.catalog_entry_id,
                                    "support_kind": "competitor_option",
                                }
                            ],
                        }
                    ]
                },
            },
            condition_term_path="framing.clinicaltrials_condition_term",
            eligible_field_paths={"design.randomization"},
            package_target_paths={},
        )
        cands = all_c.get("design.randomization", [])
        self.assertEqual(1, len(cands), errors)
        gaps = cands[0].evidence_gaps
        self.assertIn(
            "可计入本结论通用化门槛的独立来源：0/2；"
            "不得据此归纳适应症常用措辞或设计规则。",
            gaps,
        )
        self.assertIn("已绑定原始来源：1（仅作单项竞品观察）", gaps)
        self.assertTrue(
            all(
                "当前0" not in gap
                and "服务器校验：独立来源不足（当前" not in gap
                for gap in gaps
            )
        )


# ---------------------------------------------------------------------------
# Worker_03 corrective: reader-facing evidence-ref deduplication
# ---------------------------------------------------------------------------


class EvidenceRefDedupTests(unittest.TestCase):
    """P4-1 corrective: three claim bindings to one quote render ONE
    reader-facing evidence ref while every binding is preserved."""

    def setUp(self):
        payload = _analysis_payload(
            _finding(
                finding_id="f_design_001",
                module="design",
                reuse_decision=INSUFFICIENT_SUPPORT_REUSE_DECISION,
                bindings=[_binding(evidence_id="cae_limited")],
            )
        )
        self.row = _analysis_row(
            payload=payload, output_hash=_hash_json(payload)
        )
        self.journey = _journey(
            research_pipeline=_research_pipeline(
                round1_analysis_output_hash=_hash_json(payload)
            )
        )
        self.catalog = build_evidence_catalog(
            self.journey,
            corpus_analysis_reader=_memory_reader(self.row),
            corpus_source_reader=_memory_source_reader(),
        )
        self.limited = next(
            e
            for e in self.catalog.entries
            if e.source_kind == CORPUS_EVIDENCE_SOURCE_KIND
        )

    def test_three_bindings_one_quote_render_one_ref(self):
        design_paths = [
            "design.randomization",
            "design.blinding",
            "design.comparator_type",
        ]
        candidates, errors = build_round1_corpus_review_candidates(
            catalog=self.catalog,
            sent_entry_ids={e.catalog_entry_id for e in self.catalog.entries},
            package_target_paths={"package.design": design_paths},
        )
        self.assertEqual([], errors)
        self.assertEqual(1, len(candidates))
        candidate = candidates[0]
        # 3 extracted design terms -> 3 claim bindings to the single quote.
        self.assertEqual(3, len(candidate.claim_bindings))
        self.assertEqual(1, len(candidate.evidence_refs))
        ref = candidate.evidence_refs[0]
        self.assertEqual(self.limited.source_id, ref.source_id)
        self.assertEqual(self.limited.locator, ref.locator)
        self.assertEqual(self.limited.quote_sha256, ref.quote_sha256)


# ---------------------------------------------------------------------------
# Worker_03 corrective: negation-safe design-term extraction
# ---------------------------------------------------------------------------


class NegationSafeDesignExtractionTests(unittest.TestCase):
    """P4-2 corrective: negated design phrases never generate positive
    randomization/open-label facts; positive terms still extract."""

    def _review_candidates_for_excerpt(
        self, excerpt: str, *, extra_design_paths=()
    ):
        payload = _analysis_payload(
            _finding(
                finding_id="f_neg_001",
                module="design",
                reuse_decision=INSUFFICIENT_SUPPORT_REUSE_DECISION,
                bindings=[
                    _binding(
                        evidence_id="cae_neg",
                        excerpt=excerpt,
                        span_id="span_neg",
                    )
                ],
            )
        )
        row = _analysis_row(payload=payload, output_hash=_hash_json(payload))
        journey = _journey(
            research_pipeline=_research_pipeline(
                round1_analysis_output_hash=_hash_json(payload)
            )
        )
        catalog = build_evidence_catalog(
            journey,
            corpus_analysis_reader=_memory_reader(row),
            corpus_source_reader=_memory_source_reader(
                locators_by_span={"span_neg": "page-12"}
            ),
        )
        design_paths = [
            "design.randomization",
            "design.blinding",
            "design.assignment_model",
            "design.center_model",
            "design.comparator_type",
            "design.adaptive_design",
        ] + list(extra_design_paths)
        candidates, errors = build_round1_corpus_review_candidates(
            catalog=catalog,
            sent_entry_ids={e.catalog_entry_id for e in catalog.entries},
            package_target_paths={"package.design": design_paths},
        )
        return candidates, errors

    def test_negated_randomization_yields_no_positive_value(self):
        candidates, errors = self._review_candidates_for_excerpt(
            "非随机、开放标签的扩展研究"
            "（non-randomized, open-label extension study）"
        )
        self.assertEqual([], errors)
        self.assertEqual(1, len(candidates))
        sv = candidates[0].structured_value
        self.assertEqual("", sv["design.randomization"])
        self.assertEqual("开放标签", sv["design.blinding"])
        # Unmatched design paths stay blank.
        self.assertEqual("", sv["design.adaptive_design"])

    def test_not_randomized_and_unblinded_do_not_extract(self):
        candidates, errors = self._review_candidates_for_excerpt(
            "不随机、未设盲、无安慰剂对照的单臂研究"
        )
        self.assertEqual([], errors)
        self.assertEqual(1, len(candidates))
        sv = candidates[0].structured_value
        self.assertEqual("", sv["design.randomization"])
        self.assertEqual("", sv["design.blinding"])
        self.assertEqual("", sv["design.comparator_type"])
        self.assertEqual("单臂", sv["design.assignment_model"])

    def test_positive_terms_still_extracted(self):
        candidates, errors = self._review_candidates_for_excerpt(
            "多中心、随机、双盲、安慰剂对照、平行分组设计"
        )
        self.assertEqual([], errors)
        self.assertEqual(1, len(candidates))
        sv = candidates[0].structured_value
        self.assertEqual("随机", sv["design.randomization"])
        self.assertEqual("双盲", sv["design.blinding"])
        self.assertEqual("安慰剂对照", sv["design.comparator_type"])
        self.assertEqual("平行分组", sv["design.assignment_model"])
        self.assertEqual("多中心", sv["design.center_model"])
        self.assertEqual("", sv["design.adaptive_design"])

    def test_negated_open_label_extension_yields_no_positive_value(self):
        candidates, errors = self._review_candidates_for_excerpt(
            "非开放标签扩展研究（non-open-label extension study）",
            extra_design_paths=["design.open_label_extension"],
        )
        self.assertEqual([], errors)
        self.assertEqual(0, len(candidates))

    def test_positive_open_label_extension_still_extracts(self):
        candidates, errors = self._review_candidates_for_excerpt(
            "随机、开放标签扩展研究",
            extra_design_paths=["design.open_label_extension"],
        )
        self.assertEqual([], errors)
        self.assertEqual(1, len(candidates))
        sv = candidates[0].structured_value
        self.assertEqual("是", sv["design.open_label_extension"])
        self.assertEqual("随机", sv["design.randomization"])
        self.assertEqual("开放标签", sv["design.blinding"])
        self.assertEqual(
            "竞品Protocol观察：开放标签、随机、开放标签延展",
            candidates[0].preview,
        )


# ---------------------------------------------------------------------------
# Worker_03 corrective: safe recommendation after AI enrichment
# ---------------------------------------------------------------------------


class _CorpusEchoProvider:
    """Canned provider that auto-echoes catalog identity and model name."""

    def __init__(self, response: dict | None = None) -> None:
        # The production bulk schema accepts top-level field_suggestions /
        # package_suggestions; an empty object is a valid no-suggestion reply.
        self.response = response or {
            "field_suggestions": {},
            "package_suggestions": {},
        }
        self.call_count = 0
        self.calls: list[Any] = []

    def run(self, envelope: Any) -> dict:
        self.call_count += 1
        self.calls.append(envelope)
        result = dict(self.response)
        result["_response_model"] = DEEPSEEK_PREFILL_MODEL
        ec = getattr(envelope, "payload", {}).get("evidence_catalog")
        if ec:
            result.setdefault("catalog_id", ec.get("catalog_id", ""))
            result.setdefault("catalog_sha256", ec.get("catalog_sha256", ""))
        return result


class EnrichPackageSafeRecommendationTests(unittest.TestCase):
    """P3-2 end-to-end: after AI enrichment the recommended slot never points
    at an AI/corpus pending card; a pending-only group has an empty
    recommendation; mixed groups pick the first safe non-pending candidate;
    roles are preserved."""

    def _setup(self, *findings):
        payload = _analysis_payload(*findings)
        row = _analysis_row(payload=payload, output_hash=_hash_json(payload))
        journey = _journey(
            research_pipeline=_research_pipeline(
                round1_analysis_output_hash=_hash_json(payload)
            )
        )
        catalog = build_evidence_catalog(
            journey,
            corpus_analysis_reader=_memory_reader(row),
            corpus_source_reader=_memory_source_reader(),
        )
        deterministic = generate_prefill_package(
            state=journey, now=NOW, actor="test"
        )
        return row, journey, catalog, deterministic

    def _limited_finding(self, finding_id: str = "f_design_001"):
        return _finding(
            finding_id=finding_id,
            module="design",
            reuse_decision=INSUFFICIENT_SUPPORT_REUSE_DECISION,
            bindings=[_binding(evidence_id=f"cae_{finding_id}")],
        )

    def _supported_finding(self, finding_id: str = "f_design_sup"):
        # A non-limited design finding: candidates bound to it may carry
        # alternative/recommended roles (not forced pending).
        return _finding(
            finding_id=finding_id,
            module="design",
            reuse_decision="evidence_supported_candidate",
            bindings=[_binding(evidence_id=f"cae_{finding_id}")],
        )

    def _enrich(self, row, journey, deterministic, response: dict):
        provider = _CorpusEchoProvider(response)
        adapter = DeepSeekPrefillAdapter(
            provider=provider,
            model_name=DEEPSEEK_PREFILL_MODEL,
            corpus_analysis_reader=_memory_reader(row),
            corpus_source_reader=_memory_source_reader(),
        )
        enriched = adapter.enrich_package(
            package=deterministic, state=journey
        )
        return enriched, provider

    def test_pending_only_design_group_has_empty_recommendation(self):
        """A pending-only group never points the recommended slot at the
        AI/corpus pending card or at any unbound pending scaffold: with every
        visible candidate pending/manual/unsafe the slot is empty (corrective
        round 2) and every pending role is preserved."""
        row, journey, _catalog, deterministic = self._setup(
            self._limited_finding()
        )
        enriched, provider = self._enrich(
            row, journey, deterministic, {}
        )
        self.assertEqual(1, provider.call_count)
        design_group = enriched.field_candidates["package.design"]
        pending = [
            c
            for c in design_group.candidates
            if c.recommendation_role == "pending_decision"
        ]
        self.assertTrue(pending)
        corpus_pending = [
            c for c in pending if (c.claim_bindings or [])
        ]
        self.assertTrue(corpus_pending)
        # No safe candidate exists: the recommended slot is empty and never
        # points at an AI/corpus pending card or a pending scaffold.
        self.assertEqual("", design_group.recommended_candidate_id)
        self.assertNotIn(
            design_group.recommended_candidate_id,
            {c.candidate_id for c in corpus_pending},
        )
        # Pending roles are preserved (never demoted/promoted by selection).
        self.assertTrue(
            all(
                c.recommendation_role == "pending_decision"
                for c in pending
            )
        )

    def test_mixed_group_picks_first_safe_non_pending_candidate(self):
        row, journey, catalog, deterministic = self._setup(
            self._supported_finding()
        )
        entry = next(
            e
            for e in catalog.entries
            if e.source_kind == CORPUS_EVIDENCE_SOURCE_KIND
        )
        response = {
            "field_suggestions": {
                "picos.design_archetype": [
                    {
                        "structured_value": "随机双盲安慰剂对照",
                        "preview": "随机双盲安慰剂对照",
                        "rationale": "参考竞品方案。",
                        "recommendation_role": "alternative",
                        "claim_bindings": [
                            {
                                "target_path": "picos.design_archetype",
                                "value_pointer": "",
                                "catalog_entry_id": entry.catalog_entry_id,
                                "support_kind": "competitor_option",
                            }
                        ],
                    }
                ]
            },
            "package_suggestions": {},
        }
        enriched, provider = self._enrich(
            row, journey, deterministic, response
        )
        self.assertEqual(1, provider.call_count)
        group = enriched.field_candidates["picos.design_archetype"]
        self.assertTrue(group.candidates)
        safe = [
            c
            for c in group.candidates
            if c.recommendation_role != "pending_decision"
        ]
        self.assertTrue(safe)
        # Worker_03 corrective: every visible candidate is manual_only (the
        # AI builders require medical-manager confirmation), so the safe
        # recommendation slot stays EMPTY — a manual-only card is never
        # auto-labeled as the recommended pick.
        self.assertEqual("", group.recommended_candidate_id)
        self.assertTrue(
            all(
                c.recommendation_role == "pending_decision"
                for c in group.candidates
                if c.recommendation_role == "pending_decision"
            )
        )
        # A batch-allowed sibling WOULD occupy the slot: re-select over the
        # same group with the manual-only exclusion lifted for that card.
        batch_safe = [
            c.model_copy(
                update={"adoption_mode": "batch_allowed"}
            )
            if c.candidate_id == safe[0].candidate_id
            else c
            for c in group.candidates
        ]
        from services.api.app.medical_writing_authoring_prefill import (
            select_safe_recommended_candidate_id,
        )

        self.assertEqual(
            safe[0].candidate_id,
            select_safe_recommended_candidate_id(batch_safe),
        )

    def test_unsupported_substantive_claim_surfaces_with_gap_and_not_recommended(self):
        # The binding validator forces pending_decision on candidates bound
        # to insufficient-support corpus entries; the semantic gate then
        # surfaces the unsupported claim with its visible gap and an
        # insufficient status, and the recommended slot stays off it.
        row, journey, catalog, deterministic = self._setup(
            self._limited_finding()
        )
        entry = next(
            e
            for e in catalog.entries
            if e.source_kind == CORPUS_EVIDENCE_SOURCE_KIND
        )
        response = {
            "field_suggestions": {
                "picos.design_archetype": [
                    {
                        "structured_value": (
                            "AChR抗体阳性且对标准治疗反应不佳的重症肌无力人群"
                        ),
                        "preview": (
                            "AChR抗体阳性且对标准治疗反应不佳的重症肌无力人群"
                        ),
                        "rationale": "参考竞品方案。",
                        "recommendation_role": "pending_decision",
                        "claim_bindings": [
                            {
                                "target_path": "picos.design_archetype",
                                "value_pointer": "",
                                "catalog_entry_id": entry.catalog_entry_id,
                                "support_kind": "competitor_option",
                            }
                        ],
                    }
                ]
            },
            "package_suggestions": {},
        }
        enriched, provider = self._enrich(
            row, journey, deterministic, response
        )
        self.assertEqual(1, provider.call_count)
        group = enriched.field_candidates["picos.design_archetype"]
        surfaced = [
            c
            for c in group.candidates
            if any(
                "声称内容未在引用原文中出现" in str(gap)
                for gap in (c.evidence_gaps or [])
            )
        ]
        self.assertEqual(1, len(surfaced))
        cand = surfaced[0]
        self.assertEqual("insufficient", cand.evidence_status)
        # The pending role is preserved, never promoted/demoted.
        self.assertEqual("pending_decision", cand.recommendation_role)
        self.assertIn(
            "声称内容未在引用原文中出现：AChR抗体阳性相关表述",
            cand.evidence_gaps,
        )
        self.assertIn(
            "声称内容未在引用原文中出现：对标准治疗反应不佳相关表述",
            cand.evidence_gaps,
        )
        self.assertNotEqual(
            cand.candidate_id, group.recommended_candidate_id
        )


if __name__ == "__main__":
    unittest.main()
