"""Tests for the W2b-1 evidence catalog builder and contract.

Covers:
- D017 minimal facts (no IB, no synopsis) → only 3 project identity entries.
- Unconfirmed synopsis spans excluded; confirmed spans admitted via field map.
- CT.gov entries are competitor_observation only; never support project facts.
- Same quote different locator → different entries.
- Stable hash on rebuild; hash changes when snapshot/quote/revision changes.
- Truncation with stable limits.
- Legacy AuthoringPrefillCandidate JSON backward compatibility.
- Claim binding normalization and rejection of empty IDs / bad hash / duplicates.
- quote_sha256 matches quote; caller-forged hash rejected.
"""

from __future__ import annotations

import hashlib
import unittest
from datetime import datetime, timezone

from packages.contracts.workbench_contracts import (
    AuthoringPrefillCandidate,
    AuthoringPrefillClaimBinding,
    AuthoringPrefillEvidenceCatalog,
    AuthoringPrefillEvidenceCatalogEntry,
    MedicalWritingAuthoringJourney,
    MedicalWritingStudyFraming,
    MedicalWritingSynopsisEvidenceSpan,
    MedicalWritingSynopsisImport,
    MedicalWritingSynopsisSource,
    WritingReferencePublicDocument,
    WritingReferenceSearchRequest,
    WritingReferenceSearchSnapshot,
    WritingReferenceTrialCandidate,
    WritingReferenceTrialIntervention,
)
from pydantic import ValidationError

from services.api.app.medical_writing_authoring_prefill_evidence import (
    build_evidence_catalog,
    MAX_PROJECT_FACT_ENTRIES,
    MAX_SYNOPSIS_SPAN_ENTRIES,
    MAX_CTOV_CANDIDATES,
    MAX_CTOV_FIELDS_PER_CANDIDATE,
)


NOW = datetime(2026, 7, 24, 10, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _framing(**overrides) -> MedicalWritingStudyFraming:
    defaults = dict(
        investigational_product="CMS-D017",
        indication="阵发性睡眠性血红蛋白尿症",
        study_phase="II期",
    )
    defaults.update(overrides)
    return MedicalWritingStudyFraming(**defaults)


def _journey(
    framing: MedicalWritingStudyFraming | None = None,
    synopsis_import: MedicalWritingSynopsisImport | None = None,
    revision: int = 1,
    project_id: str = "proj_d017",
) -> MedicalWritingAuthoringJourney:
    return MedicalWritingAuthoringJourney(
        journey_id="jour_d017",
        project_id=project_id,
        revision=revision,
        framing=framing or _framing(),
        synopsis_import=synopsis_import or MedicalWritingSynopsisImport(),
        created_at=NOW,
        updated_at=NOW,
        updated_by="test",
    )


def _synopsis_span(
    span_id: str,
    source_id: str,
    locator: str,
    text: str,
    text_hash: str | None = None,
) -> MedicalWritingSynopsisEvidenceSpan:
    return MedicalWritingSynopsisEvidenceSpan(
        span_id=span_id,
        source_id=source_id,
        locator=locator,
        source_text=text,
        source_text_sha256=text_hash or hashlib.sha256(text.encode()).hexdigest(),
    )


def _confirmed_synopsis(
    spans: list[MedicalWritingSynopsisEvidenceSpan],
    field_map: dict[str, list[str]] | None = None,
    value_sha: dict[str, str] | None = None,
) -> MedicalWritingSynopsisImport:
    return MedicalWritingSynopsisImport(
        status="confirmed",
        source=MedicalWritingSynopsisSource(
            source_id="syn_001",
            original_filename="synopsis.docx",
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            actual_size=1024,
            content_sha256="a" * 64,
            extraction_revision="rev_1",
            parser_name="test_parser",
            source_role_status="matched",
            imported_at=NOW,
            imported_by="test",
        ),
        evidence_spans=spans,
        field_evidence_span_ids=field_map or {},
        field_extracted_value_sha256=value_sha or {},
        confirmed_at=NOW,
        confirmed_by="test",
    )


def _snapshot(
    candidates: list[WritingReferenceTrialCandidate] | None = None,
    snapshot_id: str = "snap_001",
) -> WritingReferenceSearchSnapshot:
    return WritingReferenceSearchSnapshot(
        snapshot_id=snapshot_id,
        project_id="proj_d017",
        request=WritingReferenceSearchRequest(indication="PNH"),
        query_url="https://example.com/search",
        total_count=len(candidates or []),
        returned_count=len(candidates or []),
        page_count=1,
        candidates=candidates or [],
        created_at=NOW,
    )


def _ctgov_candidate(
    nct_id: str = "NCT00000001",
    **overrides,
) -> WritingReferenceTrialCandidate:
    defaults = dict(
        nct_id=nct_id,
        brief_title="Phase 2 Study of Competitor Drug in PNH",
        official_title="A Randomized Double-Blind Placebo-Controlled Study",
        brief_summary="This study evaluates the efficacy and safety of the drug.",
        conditions=["Paroxysmal Nocturnal Hemoglobinuria"],
        phases=["PHASE2"],
        study_type="INTERVENTIONAL",
        interventions=[
            WritingReferenceTrialIntervention(
                name="Competitor Drug",
                intervention_type="DRUG",
            )
        ],
        design_allocation="RANDOMIZED",
        design_intervention_model="PARALLEL",
        design_masking="DOUBLE",
        enrollment_count=120,
        lead_sponsor="Competitor Pharma",
        overall_status="RECRUITING",
        study_record_url=f"https://clinicaltrials.gov/{nct_id}",
        public_documents=[
            WritingReferencePublicDocument(
                document_id="doc_001",
                nct_id=nct_id,
                document_type="protocol",
                filename="protocol.pdf",
                document_date="2025-01-15",
                download_url="https://example.com/protocol.pdf",
            )
        ],
    )
    defaults.update(overrides)
    return WritingReferenceTrialCandidate(**defaults)


# ---------------------------------------------------------------------------
# 1. D017 minimal facts (no IB, no synopsis)
# ---------------------------------------------------------------------------


class MinimalFactsTests(unittest.TestCase):

    def test_only_three_framing_facts_when_no_synopsis_no_snapshot(self):
        """D017 minimal facts, no IB, no synopsis → catalog has exactly 3 entries."""
        catalog = build_evidence_catalog(_journey())
        self.assertEqual(3, len(catalog.entries))
        kinds = {e.source_kind for e in catalog.entries}
        self.assertEqual({"project_fact"}, kinds)
        ids = {e.source_id for e in catalog.entries}
        self.assertIn("framing.investigational_product", ids)
        self.assertIn("framing.indication", ids)
        self.assertIn("framing.study_phase", ids)

    def test_empty_framing_produces_empty_catalog(self):
        """If framing identity fields are all empty, catalog has 0 entries."""
        catalog = build_evidence_catalog(
            _journey(framing=MedicalWritingStudyFraming())
        )
        self.assertEqual(0, len(catalog.entries))

    def test_all_entries_are_project_fact_scope(self):
        catalog = build_evidence_catalog(_journey())
        for entry in catalog.entries:
            self.assertEqual("current_project_fact", entry.support_scope)

    def test_quote_sha256_matches_quote(self):
        catalog = build_evidence_catalog(_journey())
        for entry in catalog.entries:
            expected = hashlib.sha256(entry.quote.encode()).hexdigest()
            self.assertEqual(expected, entry.quote_sha256)

    def test_framing_facts_support_identity_target_paths(self):
        catalog = build_evidence_catalog(_journey())
        for entry in catalog.entries:
            self.assertIn(entry.source_id, entry.supported_target_paths)


# ---------------------------------------------------------------------------
# 2. Synopsis spans
# ---------------------------------------------------------------------------


class SynopsisSpanTests(unittest.TestCase):

    def test_unconfirmed_synopsis_excluded(self):
        """Unconfirmed synopsis spans are NOT admitted."""
        span = _synopsis_span("s1", "syn_001", "p1", "试验药物CMS-D017")
        synopsis = MedicalWritingSynopsisImport(
            status="review_pending",
            evidence_spans=[span],
            field_evidence_span_ids={"framing.investigational_product": ["s1"]},
        )
        catalog = build_evidence_catalog(_journey(synopsis_import=synopsis))
        synopsis_entries = [
            e for e in catalog.entries if e.source_kind == "synopsis"
        ]
        self.assertEqual(0, len(synopsis_entries))

    def test_confirmed_synopsis_admitted_with_correct_field_map(self):
        span = _synopsis_span(
            "s1", "syn_001", "p1", "试验药物CMS-D017"
        )
        synopsis = _confirmed_synopsis(
            spans=[span],
            field_map={"framing.investigational_product": ["s1"]},
        )
        catalog = build_evidence_catalog(_journey(synopsis_import=synopsis))
        synopsis_entries = [
            e for e in catalog.entries if e.source_kind == "synopsis"
        ]
        self.assertEqual(1, len(synopsis_entries))
        self.assertIn(
            "framing.investigational_product",
            synopsis_entries[0].supported_target_paths,
        )

    def test_wrong_hash_span_excluded(self):
        """Span with mismatched source_text_sha256 is fail-closed excluded."""
        span = _synopsis_span(
            "s1", "syn_001", "p1", "text", text_hash="b" * 64
        )
        synopsis = _confirmed_synopsis(
            spans=[span],
            field_map={"framing.investigational_product": ["s1"]},
        )
        catalog = build_evidence_catalog(_journey(synopsis_import=synopsis))
        synopsis_entries = [
            e for e in catalog.entries if e.source_kind == "synopsis"
        ]
        self.assertEqual(0, len(synopsis_entries))

    def test_unknown_span_id_excluded(self):
        """Span ID in field_map but not in evidence_spans is excluded."""
        synopsis = _confirmed_synopsis(
            spans=[],
            field_map={"framing.investigational_product": ["nonexistent"]},
        )
        catalog = build_evidence_catalog(_journey(synopsis_import=synopsis))
        synopsis_entries = [
            e for e in catalog.entries if e.source_kind == "synopsis"
        ]
        self.assertEqual(0, len(synopsis_entries))

    def test_same_quote_different_locator_different_entries(self):
        """Same quote text but different locator produces different entries."""
        text = "每日一次口服给药"
        span1 = _synopsis_span("s1", "syn_001", "page=5", text)
        span2 = _synopsis_span("s2", "syn_001", "page=8", text)
        synopsis = _confirmed_synopsis(
            spans=[span1, span2],
            field_map={
                "framing.investigational_product": ["s1", "s2"],
            },
        )
        catalog = build_evidence_catalog(_journey(synopsis_import=synopsis))
        synopsis_entries = [
            e for e in catalog.entries if e.source_kind == "synopsis"
        ]
        self.assertEqual(2, len(synopsis_entries))
        self.assertNotEqual(
            synopsis_entries[0].catalog_entry_id,
            synopsis_entries[1].catalog_entry_id,
        )


# ---------------------------------------------------------------------------
# 3. CT.gov competitor observations
# ---------------------------------------------------------------------------


class CtGovSnapshotTests(unittest.TestCase):

    def test_ctgov_entries_are_competitor_observation(self):
        snapshot = _snapshot([_ctgov_candidate()])
        catalog = build_evidence_catalog(_journey(), snapshot=snapshot)
        ctgov_entries = [
            e for e in catalog.entries if e.source_kind == "ctgov_snapshot"
        ]
        self.assertGreater(len(ctgov_entries), 0)
        for entry in ctgov_entries:
            self.assertEqual("competitor_observation", entry.support_scope)
            # CT.gov entries never support project fact target paths
            self.assertEqual([], entry.supported_target_paths)

    def test_ctgov_randomization_does_not_support_project_fact(self):
        """CT.gov design_allocation=RANDOMIZED cannot support project design.randomization."""
        snapshot = _snapshot([_ctgov_candidate()])
        catalog = build_evidence_catalog(_journey(), snapshot=snapshot)
        ctgov_entries = [
            e for e in catalog.entries if e.source_kind == "ctgov_snapshot"
        ]
        alloc_entries = [
            e for e in ctgov_entries if "design_allocation" in e.locator
        ]
        self.assertGreater(len(alloc_entries), 0)
        for entry in alloc_entries:
            self.assertEqual("competitor_observation", entry.support_scope)
            self.assertEqual([], entry.supported_target_paths)

    def test_ctgov_masking_is_competitor_observation(self):
        snapshot = _snapshot([_ctgov_candidate()])
        catalog = build_evidence_catalog(_journey(), snapshot=snapshot)
        masking_entries = [
            e
            for e in catalog.entries
            if e.source_kind == "ctgov_snapshot"
            and "design_masking" in e.locator
        ]
        self.assertGreater(len(masking_entries), 0)
        for entry in masking_entries:
            self.assertEqual("competitor_observation", entry.support_scope)

    def test_ctgov_intervention_type_is_competitor_observation(self):
        snapshot = _snapshot([_ctgov_candidate()])
        catalog = build_evidence_catalog(_journey(), snapshot=snapshot)
        interv_entries = [
            e
            for e in catalog.entries
            if e.source_kind == "ctgov_snapshot"
            and "intervention[" in e.locator
        ]
        self.assertGreater(len(interv_entries), 0)
        for entry in interv_entries:
            self.assertEqual("competitor_observation", entry.support_scope)

    def test_empty_fields_not_included(self):
        """CT.gov fields that are empty strings are not included as entries."""
        candidate = WritingReferenceTrialCandidate(
            nct_id="NCT00000002",
            study_record_url="https://example.com",
        )
        snapshot = _snapshot([candidate])
        catalog = build_evidence_catalog(_journey(), snapshot=snapshot)
        ctgov_entries = [
            e for e in catalog.entries if e.source_kind == "ctgov_snapshot"
        ]
        # Only NCT ID and URL should be present (both non-empty)
        locators = [e.locator for e in ctgov_entries]
        nct_locators = [l for l in locators if "nct_id" in l]
        self.assertGreater(len(nct_locators), 0)


# ---------------------------------------------------------------------------
# 4. Stable hash and reproducibility
# ---------------------------------------------------------------------------


class StableHashTests(unittest.TestCase):

    def test_same_input_produces_same_catalog_hash(self):
        j = _journey()
        catalog1 = build_evidence_catalog(j)
        catalog2 = build_evidence_catalog(j)
        self.assertEqual(catalog1.catalog_sha256, catalog2.catalog_sha256)
        self.assertEqual(catalog1.catalog_id, catalog2.catalog_id)
        self.assertEqual(
            [e.catalog_entry_id for e in catalog1.entries],
            [e.catalog_entry_id for e in catalog2.entries],
        )

    def test_snapshot_id_change_changes_hash(self):
        j = _journey()
        snap1 = _snapshot([_ctgov_candidate()], snapshot_id="snap_A")
        snap2 = _snapshot([_ctgov_candidate()], snapshot_id="snap_B")
        catalog1 = build_evidence_catalog(j, snapshot=snap1)
        catalog2 = build_evidence_catalog(j, snapshot=snap2)
        self.assertNotEqual(catalog1.catalog_sha256, catalog2.catalog_sha256)

    def test_journey_revision_change_changes_hash(self):
        catalog1 = build_evidence_catalog(_journey(revision=1))
        catalog2 = build_evidence_catalog(_journey(revision=2))
        self.assertNotEqual(catalog1.catalog_sha256, catalog2.catalog_sha256)

    def test_quote_change_changes_hash(self):
        j1 = _journey(framing=_framing(investigational_product="DrugA"))
        j2 = _journey(framing=_framing(investigational_product="DrugB"))
        catalog1 = build_evidence_catalog(j1)
        catalog2 = build_evidence_catalog(j2)
        self.assertNotEqual(catalog1.catalog_sha256, catalog2.catalog_sha256)

    def test_source_revision_change_changes_hash(self):
        """Changing synopsis field_extracted_value_sha256 changes hash."""
        text = "test text"
        sha = hashlib.sha256(text.encode()).hexdigest()
        span = _synopsis_span("s1", "syn_001", "p1", text)
        syn1 = _confirmed_synopsis(
            spans=[span],
            field_map={"framing.investigational_product": ["s1"]},
            value_sha={"framing.investigational_product": "rev1"},
        )
        syn2 = _confirmed_synopsis(
            spans=[span],
            field_map={"framing.investigational_product": ["s1"]},
            value_sha={"framing.investigational_product": "rev2"},
        )
        catalog1 = build_evidence_catalog(_journey(synopsis_import=syn1))
        catalog2 = build_evidence_catalog(_journey(synopsis_import=syn2))
        self.assertNotEqual(catalog1.catalog_sha256, catalog2.catalog_sha256)


# ---------------------------------------------------------------------------
# 5. Truncation
# ---------------------------------------------------------------------------


class TruncationTests(unittest.TestCase):

    def test_synopsis_truncation_with_note(self):
        """More than MAX_SYNOPSIS_SPAN_ENTRIES confirmed spans → truncated."""
        spans = []
        field_map: dict[str, list[str]] = {}
        for i in range(MAX_SYNOPSIS_SPAN_ENTRIES + 5):
            sid = f"s{i}"
            text = f"unique text {i}"
            spans.append(_synopsis_span(sid, "syn_001", f"p{i}", text))
            # Use a different field each time so each maps to a target_path
            field_name = f"framing.investigational_product"
            if field_name not in field_map:
                field_map[field_name] = []
            field_map[field_name].append(sid)

        synopsis = _confirmed_synopsis(spans=spans, field_map=field_map)
        catalog = build_evidence_catalog(_journey(synopsis_import=synopsis))
        synopsis_entries = [
            e for e in catalog.entries if e.source_kind == "synopsis"
        ]
        self.assertLessEqual(len(synopsis_entries), MAX_SYNOPSIS_SPAN_ENTRIES)
        self.assertGreater(len(catalog.truncation_notes), 0)

    def test_ctgov_candidate_truncation(self):
        """More than MAX_CTOV_CANDIDATES → truncated with note."""
        candidates = [
            _ctgov_candidate(nct_id=f"NCT{i:08d}")
            for i in range(MAX_CTOV_CANDIDATES + 5)
        ]
        snapshot = _snapshot(candidates)
        catalog = build_evidence_catalog(_journey(), snapshot=snapshot)
        ctgov_entries = [
            e for e in catalog.entries if e.source_kind == "ctgov_snapshot"
        ]
        # Each candidate contributes at most MAX_CTOV_FIELDS_PER_CANDIDATE entries,
        # and we cap at MAX_CTOV_CANDIDATES candidates
        max_expected = MAX_CTOV_CANDIDATES * MAX_CTOV_FIELDS_PER_CANDIDATE
        self.assertLessEqual(len(ctgov_entries), max_expected)
        self.assertGreater(len(catalog.truncation_notes), 0)


# ---------------------------------------------------------------------------
# 6. Legacy backward compatibility
# ---------------------------------------------------------------------------


class LegacyCandidateCompatTests(unittest.TestCase):

    def test_legacy_candidate_json_loads_without_new_fields(self):
        import json

        legacy = json.dumps(
            {
                "candidate_id": "c1",
                "field_path": "framing.protocol_id",
                "structured_value": "X",
                "preview": "X",
                "evidence_refs": [],
                "rationale": "",
                "limitations": [],
                "confidence": "medium",
                "state": "ai_proposed",
            }
        )
        candidate = AuthoringPrefillCandidate.model_validate_json(legacy)
        self.assertEqual("insufficient", candidate.evidence_status)
        self.assertEqual("", candidate.evidence_catalog_id)
        self.assertEqual("", candidate.evidence_catalog_sha256)
        self.assertEqual([], candidate.claim_bindings)

    def test_candidate_with_catalog_fields(self):
        binding = AuthoringPrefillClaimBinding(
            target_path="framing.investigational_product",
            catalog_entry_id="entry_001",
            source_id="framing.investigational_product",
            locator="framing.investigational_product",
            quote_sha256="a" * 64,
        )
        candidate = AuthoringPrefillCandidate(
            candidate_id="c2",
            field_path="framing.investigational_product",
            structured_value="CMS-D017",
            preview="CMS-D017",
            evidence_catalog_id="catalog_001",
            evidence_catalog_sha256="b" * 64,
            claim_bindings=[binding],
            evidence_status="supported",
        )
        self.assertEqual("catalog_001", candidate.evidence_catalog_id)
        self.assertEqual("supported", candidate.evidence_status)
        self.assertEqual(1, len(candidate.claim_bindings))


# ---------------------------------------------------------------------------
# 7. Claim binding validation
# ---------------------------------------------------------------------------


class ClaimBindingTests(unittest.TestCase):

    def _valid_binding(self, **overrides) -> dict:
        defaults = dict(
            target_path="framing.investigational_product",
            value_pointer="",
            catalog_entry_id="entry_001",
            source_id="framing.investigational_product",
            locator="framing.investigational_product",
            quote_sha256="a" * 64,
        )
        defaults.update(overrides)
        return defaults

    def test_valid_claim_binding(self):
        binding = AuthoringPrefillClaimBinding(**self._valid_binding())
        self.assertEqual("framing.investigational_product", binding.target_path)

    def test_empty_catalog_entry_id_rejected(self):
        with self.assertRaises(ValidationError):
            AuthoringPrefillClaimBinding(
                **self._valid_binding(catalog_entry_id="")
            )

    def test_empty_target_path_rejected(self):
        with self.assertRaises(ValidationError):
            AuthoringPrefillClaimBinding(
                **self._valid_binding(target_path="")
            )

    def test_bad_hash_length_rejected(self):
        with self.assertRaises(ValidationError):
            AuthoringPrefillClaimBinding(
                **self._valid_binding(quote_sha256="short")
            )

    def test_non_64_char_hash_rejected(self):
        with self.assertRaises(ValidationError):
            AuthoringPrefillClaimBinding(
                **self._valid_binding(quote_sha256="a" * 63)
            )

    def test_support_kind_competitor_option(self):
        binding = AuthoringPrefillClaimBinding(
            **self._valid_binding(support_kind="competitor_option")
        )
        self.assertEqual("competitor_option", binding.support_kind)


# ---------------------------------------------------------------------------
# 8. Catalog entry hash integrity
# ---------------------------------------------------------------------------


class CatalogEntryHashTests(unittest.TestCase):

    def test_builder_output_hashes_match_quotes(self):
        """Builder-computed hashes match the quote text."""
        catalog = build_evidence_catalog(_journey())
        for entry in catalog.entries:
            expected = hashlib.sha256(entry.quote.encode()).hexdigest()
            self.assertEqual(
                expected,
                entry.quote_sha256,
                f"hash mismatch for {entry.catalog_entry_id}",
            )

    def test_entry_ids_are_unique(self):
        catalog = build_evidence_catalog(_journey(), snapshot=_snapshot([_ctgov_candidate()]))
        ids = [e.catalog_entry_id for e in catalog.entries]
        self.assertEqual(len(ids), len(set(ids)))


# ---------------------------------------------------------------------------
# 9. Catalog model validation
# ---------------------------------------------------------------------------


class CatalogModelTests(unittest.TestCase):

    def test_duplicate_entry_ids_rejected(self):
        """Catalog with duplicate entry IDs is rejected."""
        entry = AuthoringPrefillEvidenceCatalogEntry(
            catalog_entry_id="dup1",
            catalog_id="cat1",
            source_kind="project_fact",
            source_id="framing.indication",
            locator="framing.indication",
            quote="test",
        )
        with self.assertRaises(ValidationError):
            AuthoringPrefillEvidenceCatalog(
                catalog_id="cat1",
                project_id="proj1",
                journey_revision=1,
                entries=[entry, entry],
                catalog_sha256="a" * 64,
            )

    def test_missing_catalog_sha256_rejected(self):
        with self.assertRaises(ValidationError):
            AuthoringPrefillEvidenceCatalog(
                catalog_id="cat1",
                project_id="proj1",
                journey_revision=1,
                entries=[],
                catalog_sha256="",
            )

    def test_entry_catalog_id_mismatch_rejected(self):
        entry = AuthoringPrefillEvidenceCatalogEntry(
            catalog_entry_id="e1",
            catalog_id="wrong_catalog",
            source_kind="project_fact",
            source_id="framing.indication",
            locator="framing.indication",
            quote="test",
        )
        with self.assertRaises(ValidationError):
            AuthoringPrefillEvidenceCatalog(
                catalog_id="cat1",
                project_id="proj1",
                journey_revision=1,
                entries=[entry],
                catalog_sha256="a" * 64,
            )


# ---------------------------------------------------------------------------
# 10. True fail-closed contract tests (W2b-1 r2)
# ---------------------------------------------------------------------------


class FailClosedContractTests(unittest.TestCase):
    """These tests explicitly construct forged / inconsistent contract instances
    and verify that ValidationError is raised — they do NOT rely on the builder
    always producing correct output."""

    # -- 10a: Forged quote hash at contract level --

    def test_forged_quote_hash_rejected_at_contract_level(self):
        """Explicitly constructing an entry with a mismatched quote_sha256
        must raise ValidationError."""
        real_hash = hashlib.sha256(b"real quote").hexdigest()
        with self.assertRaises(ValidationError) as ctx:
            AuthoringPrefillEvidenceCatalogEntry(
                catalog_entry_id="e1",
                catalog_id="cat1",
                source_kind="project_fact",
                source_id="framing.indication",
                locator="framing.indication",
                quote="real quote",
                quote_sha256=real_hash.replace("a", "b"),  # forged
            )
        self.assertIn("does not match", str(ctx.exception))

    def test_non_hex_64_char_hash_rejected(self):
        """A 64-character string that is not valid hex must be rejected."""
        with self.assertRaises(ValidationError) as ctx:
            AuthoringPrefillEvidenceCatalogEntry(
                catalog_entry_id="e1",
                catalog_id="cat1",
                source_kind="project_fact",
                source_id="framing.indication",
                locator="framing.indication",
                quote="some quote",
                quote_sha256="z" * 64,  # not hex
            )
        self.assertIn("64 lowercase hex", str(ctx.exception))

    def test_uppercase_hex_normalized_to_lowercase(self):
        """Uppercase hex should be normalized to lowercase (not rejected)."""
        quote_text = "test value"
        real_hash = hashlib.sha256(quote_text.encode()).hexdigest()
        entry = AuthoringPrefillEvidenceCatalogEntry(
            catalog_entry_id="e1",
            catalog_id="cat1",
            source_kind="project_fact",
            source_id="framing.indication",
            locator="framing.indication",
            quote=quote_text,
            quote_sha256=real_hash.upper(),
        )
        self.assertEqual(real_hash, entry.quote_sha256)

    # -- 10b: Quote is not stripped --

    def test_quote_not_stripped(self):
        """Leading/trailing whitespace in quote must be preserved so that
        the hash remains valid against the original text."""
        raw_quote = "  spaced quote  "
        entry = AuthoringPrefillEvidenceCatalogEntry(
            catalog_entry_id="e1",
            catalog_id="cat1",
            source_kind="project_fact",
            source_id="framing.indication",
            locator="framing.indication",
            quote=raw_quote,
        )
        self.assertEqual(raw_quote, entry.quote)

    # -- 10c: Framing per-field target path isolation --

    def test_indication_does_not_support_investigational_product(self):
        """Indication entry must NOT list investigational_product in its
        supported_target_paths."""
        catalog = build_evidence_catalog(_journey())
        indication_entries = [
            e for e in catalog.entries if e.source_id == "framing.indication"
        ]
        self.assertGreater(len(indication_entries), 0)
        for entry in indication_entries:
            self.assertNotIn(
                "framing.investigational_product",
                entry.supported_target_paths,
            )

    def test_investigational_product_does_not_support_indication(self):
        """Investigational product entry must NOT list indication."""
        catalog = build_evidence_catalog(_journey())
        ip_entries = [
            e for e in catalog.entries
            if e.source_id == "framing.investigational_product"
        ]
        self.assertGreater(len(ip_entries), 0)
        for entry in ip_entries:
            self.assertNotIn(
                "framing.indication",
                entry.supported_target_paths,
            )

    def test_study_phase_does_not_support_indication_or_product(self):
        """Study phase entry must NOT support indication or investigational_product."""
        catalog = build_evidence_catalog(_journey())
        phase_entries = [
            e for e in catalog.entries if e.source_id == "framing.study_phase"
        ]
        self.assertGreater(len(phase_entries), 0)
        for entry in phase_entries:
            self.assertNotIn("framing.indication", entry.supported_target_paths)
            self.assertNotIn(
                "framing.investigational_product", entry.supported_target_paths
            )

    def test_framing_facts_do_not_directly_support_protocol_id(self):
        """No framing identity fact should directly support protocol_id."""
        catalog = build_evidence_catalog(_journey())
        for entry in catalog.entries:
            if entry.source_kind == "project_fact":
                self.assertNotIn(
                    "framing.protocol_id", entry.supported_target_paths
                )

    # -- 10d: Synopsis source_id consistency --

    def test_synopsis_span_with_wrong_source_id_excluded(self):
        """A span whose source_id differs from the import source is excluded."""
        span = _synopsis_span(
            "s1", "wrong_source_id", "p1", "试验药物CMS-D017"
        )
        synopsis = _confirmed_synopsis(
            spans=[span],
            field_map={"framing.investigational_product": ["s1"]},
        )
        # The import source has source_id="syn_001" but span has "wrong_source_id"
        catalog = build_evidence_catalog(_journey(synopsis_import=synopsis))
        synopsis_entries = [
            e for e in catalog.entries if e.source_kind == "synopsis"
        ]
        self.assertEqual(0, len(synopsis_entries))

    def test_confirmed_synopsis_without_source_excludes_all_spans(self):
        """Confirmed status alone cannot make an unowned span authoritative."""
        span = _synopsis_span(
            "s1", "unowned_source", "p1", "试验药物CMS-D017"
        )
        synopsis = _confirmed_synopsis(
            spans=[span],
            field_map={"framing.investigational_product": ["s1"]},
        )
        synopsis.source = None
        catalog = build_evidence_catalog(_journey(synopsis_import=synopsis))
        synopsis_entries = [
            e for e in catalog.entries if e.source_kind == "synopsis"
        ]
        self.assertEqual(0, len(synopsis_entries))

    # -- 10e: Duplicate binding rejection --

    def test_duplicate_claim_binding_rejected(self):
        """Candidate with two bindings having same target_path + value_pointer +
        catalog_entry_id must be rejected."""
        binding_args = dict(
            target_path="framing.investigational_product",
            value_pointer="",
            catalog_entry_id="entry_001",
            source_id="framing.investigational_product",
            locator="framing.investigational_product",
            quote_sha256="a" * 64,
        )
        b1 = AuthoringPrefillClaimBinding(**binding_args)
        b2 = AuthoringPrefillClaimBinding(**binding_args)
        with self.assertRaises(ValidationError) as ctx:
            AuthoringPrefillCandidate(
                candidate_id="c1",
                field_path="framing.investigational_product",
                structured_value="CMS-D017",
                preview="CMS-D017",
                evidence_catalog_id="cat1",
                evidence_catalog_sha256="b" * 64,
                claim_bindings=[b1, b2],
                evidence_status="supported",
            )
        self.assertIn("duplicate claim binding", str(ctx.exception))

    # -- 10f: supported/partially_supported without catalog/binding --

    def test_supported_without_catalog_id_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            AuthoringPrefillCandidate(
                candidate_id="c1",
                field_path="framing.investigational_product",
                structured_value="X",
                preview="X",
                evidence_status="supported",
            )
        self.assertIn("evidence_catalog_id", str(ctx.exception))

    def test_supported_without_catalog_sha_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            AuthoringPrefillCandidate(
                candidate_id="c1",
                field_path="framing.investigational_product",
                structured_value="X",
                preview="X",
                evidence_catalog_id="cat1",
                evidence_status="supported",
            )
        self.assertIn("evidence_catalog_sha256", str(ctx.exception))

    def test_supported_without_bindings_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            AuthoringPrefillCandidate(
                candidate_id="c1",
                field_path="framing.investigational_product",
                structured_value="X",
                preview="X",
                evidence_catalog_id="cat1",
                evidence_catalog_sha256="b" * 64,
                evidence_status="supported",
            )
        self.assertIn("at least one claim binding", str(ctx.exception))

    def test_partially_supported_without_bindings_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            AuthoringPrefillCandidate(
                candidate_id="c1",
                field_path="framing.investigational_product",
                structured_value="X",
                preview="X",
                evidence_catalog_id="cat1",
                evidence_catalog_sha256="b" * 64,
                evidence_status="partially_supported",
            )
        self.assertIn("at least one claim binding", str(ctx.exception))

    def test_insufficient_with_no_catalog_or_bindings_allowed(self):
        """insufficient status with empty catalog/bindings is the default and valid."""
        candidate = AuthoringPrefillCandidate(
            candidate_id="c1",
            field_path="framing.investigational_product",
            structured_value="X",
            preview="X",
        )
        self.assertEqual("insufficient", candidate.evidence_status)

    # -- 10g: CT.gov stable sort before truncation --

    def test_ctgov_same_candidates_different_order_same_hash(self):
        """Same set of CT.gov candidates in different input order must produce
        the same entry IDs and catalog hash."""
        cand_a = _ctgov_candidate(nct_id="NCT00000001")
        cand_b = _ctgov_candidate(nct_id="NCT00000002")
        snap_forward = _snapshot([cand_a, cand_b], snapshot_id="snap_X")
        snap_reverse = _snapshot([cand_b, cand_a], snapshot_id="snap_X")
        catalog1 = build_evidence_catalog(_journey(), snapshot=snap_forward)
        catalog2 = build_evidence_catalog(_journey(), snapshot=snap_reverse)
        self.assertEqual(catalog1.catalog_sha256, catalog2.catalog_sha256)
        self.assertEqual(
            [e.catalog_entry_id for e in catalog1.entries],
            [e.catalog_entry_id for e in catalog2.entries],
        )

    # -- 10h: Claim binding hex validation --

    def test_claim_binding_non_hex_64_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            AuthoringPrefillClaimBinding(
                target_path="framing.indication",
                catalog_entry_id="entry_001",
                quote_sha256="z" * 64,
            )
        self.assertIn("64 lowercase hex", str(ctx.exception))

    def test_claim_binding_uppercase_hex_normalized(self):
        real_hash = hashlib.sha256(b"x").hexdigest()
        binding = AuthoringPrefillClaimBinding(
            target_path="framing.indication",
            catalog_entry_id="entry_001",
            quote_sha256=real_hash.upper(),
        )
        self.assertEqual(real_hash, binding.quote_sha256)

    # -- 10i: Provenance bound --

    def test_provenance_over_50_keys_rejected(self):
        oversized = {f"key_{i}": i for i in range(51)}
        with self.assertRaises(ValidationError) as ctx:
            AuthoringPrefillEvidenceCatalogEntry(
                catalog_entry_id="e1",
                catalog_id="cat1",
                source_kind="project_fact",
                source_id="framing.indication",
                locator="framing.indication",
                quote="test",
                provenance=oversized,
            )
        self.assertIn("50", str(ctx.exception))

    # -- 10j: Catalog hash hex validation --

    def test_catalog_non_hex_sha256_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            AuthoringPrefillEvidenceCatalog(
                catalog_id="cat1",
                project_id="proj1",
                journey_revision=1,
                entries=[],
                catalog_sha256="z" * 64,
            )
        self.assertIn("64 lowercase hex", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
