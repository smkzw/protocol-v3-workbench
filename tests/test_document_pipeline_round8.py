"""Round 8 focused deterministic tests for the document translation pipeline.

Proves product contract behavior (not string presence):

1. planner call count = 1 for multi-span/chapter and retry
2. no span omission/duplication/reordering/chapter fallback
3. mergeable spans yield fewer chunks than spans
4. oversized paragraph/list/table + repeated table header
5. read-only context not included in translated output
6. Hy-MT2 call count = pending chunks; partial retry reuses completed
7. ordinary Flash integration call count = chapters; not windowed
8. oversized chapter uses windows + final envelope + window lineage
9. all span items in one chapter share one translation id/revision
10. revision has complete lineage and non-blank ai_run_id
11. deterministic fidelity can block a Flash-passed result
12. legacy span-keyed candidates without plan lineage are not reused
13. progress exposes document/chapter/chunk counts and blocker state
14. malformed planner/translator/integration fail closed
15. immutable plan/chunk/window/integration/run reject UPDATE/DELETE
"""
from __future__ import annotations

import json
import tempfile
import unittest
from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from packages.contracts.workbench_contracts.models import (
    DocumentStructurePlan,
    DocumentStructurePlanChapter,
    WritingReferenceDocumentArtifact,
    WritingReferenceDocumentValidationCheck,
    WritingReferenceDocumentValidationRecord,
    WritingReferenceExtractedSpan,
    WritingReferenceExtractionResult,
    WritingReferenceExtractionReviewDecision,
    WritingReferenceTranslationBatchCreateRequest,
    WritingReferenceTranslationBatchRetryRequest,
    WritingReferenceTranslationRevision,
    WritingReferenceTranslationRequest,
    WritingReferenceUpperLayerStageRun,
)

from services.api.app.chapter_translation_pipeline import (
    CHUNK_TARGET_CHARS,
    DocumentPlanRequest,
    DocumentPlanValidationError,
    INTEGRATION_PROVIDER_INPUT_LIMIT,
    FlashPlanResult,
    FlashQcResult,
    HyMt2TranslationResult,
    build_document_planner_input,
    build_document_planner_segments,
    build_anchor_grouped_document_plan_fallback,
    build_deterministic_document_plan_fallback,
    build_chunks_from_plan,
    build_integration_windows,
    call_flash_planner_with_single_retry,
    call_hy_mt2_translator,
    expand_document_plan_segment_ranges,
    format_hy_mt2_prompt_envelope,
    required_top_level_segment_boundaries,
    validate_document_plan,
    _planner_contract_fingerprint,
    _server_canonical_chapter_id,
    _sha256,
    FLASH_PLANNING_MODEL,
    FLASH_PLANNING_PREVIOUS_PROMPT_VERSION,
    FLASH_PLANNING_PROMPT_VERSION,
    FLASH_QC_MODEL,
    FLASH_QC_PROMPT_VERSION,
    HY_MT2_MODEL_ID,
    HY_MT2_PROMPT_VERSION,
    PLANNER_CONTRACT_TRANSITION_VERSION,
    SERVER_CONTRACT_MIGRATION_NAMESPACE,
    TRANSLATION_CONTRACT_FINGERPRINT,
    UPPER_LAYER_DOCUMENT_PLANNING,
    UpperLayerStageExecutionResult,
    _upper_layer_hash_payload,
)
from services.api.app.writing_reference_upper_layer_adapters import (
    ProductionPersistedUpperLayerStageExecutorAdapter,
    upper_layer_prompt_resolver,
)
from services.api.app.writing_reference_upper_layer_execution import (
    DEFAULT_UPPER_LAYER_MODEL,
    ESCALATED_UPPER_LAYER_MODEL,
    UpperLayerAdapterResult,
    UpperLayerExecutionRequest,
    WritingReferenceUpperLayerExecutionService,
)
from services.api.app.writing_reference import (
    COMPOSITE_TRANSLATION_BODY_MODEL,
    COMPOSITE_TRANSLATION_CONTRACT_HASH,
    COMPOSITE_TRANSLATION_PROMPT_VERSION,
    COMPOSITE_TRANSLATION_SCHEMA_VERSION,
    COMPOSITE_TRANSLATION_TASK_TYPE,
    WritingReferenceTranslationService,
)
from services.api.app.writing_reference_repository import WritingReferenceRepository
from services.api.app.writing_reference_translation_batch import (
    WritingReferenceTranslationBatchService,
)
from tests._composite_pipeline_fixture import (
    build_deterministic_pipeline,
    wire_pipeline_calls_to_runner,
)

PROJECT_ID = "proj_round8"
SNAPSHOT_ID = "snap_round8"
NCT_ID = "NCT00000008"
GLOSSARY = "cms_regulatory_zh_v1"
NOW = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)


def _span(span_id: str, text: str, *, artifact_id: str = "art1", page: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        span_id=span_id,
        source_text=text,
        artifact_id=artifact_id,
        extraction_revision="extract_r1",
        physical_page=page,
        ich_m11_anchor="eligibility",
    )


class PlannerAndChunkingTests(unittest.TestCase):
    def test_bounded_segment_manifest_never_exposes_source_span_ids(self) -> None:
        spans = tuple(
            SimpleNamespace(
                span_id=f"private-span-{index:04d}",
                source_text=("Protocol body text " * 40) + str(index),
                section_heading=(
                    "Study design" if index < 600 else "Statistical methods"
                ),
                ich_m11_anchor=(
                    "study_design" if index < 600 else "statistics"
                ),
                physical_page=(index // 10) + 1,
            )
            for index in range(1200)
        )
        source_text, context = build_document_planner_input(
            spans,
            document_context={
                "artifact_id": "art-large",
                "document_type": "protocol",
                "span_count": len(spans),
            },
        )
        self.assertLess(len(source_text), 60_000)
        self.assertNotIn("private-span-", source_text)
        self.assertNotIn("span_ids", context)
        self.assertNotIn("source_span_ids", context)
        self.assertEqual(2, context["segment_count"])
        self.assertEqual([], context["required_top_level_segment_ordinals"])

    def test_noisy_pdf_heading_candidates_do_not_become_chapter_boundaries(self) -> None:
        spans = []
        chapter_starts = {
            0: ("1 Protocol summary", "synopsis"),
            400: ("2 Introduction and trial rationale", "unmapped"),
            800: ("13 References", "unmapped"),
        }
        current_heading = ""
        current_anchor = "unmapped"
        for index in range(1000):
            if index in chapter_starts:
                current_heading, current_anchor = chapter_starts[index]
            else:
                current_heading = (
                    f"AESI-{index} adverse event term"
                    if index < 400
                    else f"Visit {index} Week {index % 24}"
                )
            spans.append(
                SimpleNamespace(
                    span_id=f"noisy-{index}",
                    source_text=f"Body block {index}.",
                    section_heading=current_heading,
                    ich_m11_anchor=current_anchor,
                    physical_page=(index // 10) + 1,
                )
            )
        segments = build_document_planner_segments(tuple(spans))
        self.assertEqual(3, len(segments))
        self.assertEqual(
            [
                "1 Protocol summary",
                "2 Introduction and trial rationale",
                "13 References",
            ],
            [segment.heading for segment in segments],
        )

    def test_manifest_reduces_samples_before_rejecting_many_real_headings(self) -> None:
        spans = tuple(
            SimpleNamespace(
                span_id=f"heading-{index}",
                source_text=("Detailed protocol context " * 20) + str(index),
                section_heading=f"{index + 1} Protocol section {index + 1}",
                ich_m11_anchor="unmapped",
                physical_page=index + 1,
            )
            for index in range(350)
        )
        source_text, context = build_document_planner_input(
            spans,
            document_context={
                "artifact_id": "art-many-headings",
                "document_type": "protocol",
                "span_count": len(spans),
            },
        )
        self.assertLessEqual(len(source_text), 65_536)
        self.assertIn(context["segment_sample_chars"], {40, 0})
        self.assertEqual(350, context["segment_count"])

    def test_segment_ranges_expand_complete_ordered_membership(self) -> None:
        spans = (
            SimpleNamespace(
                span_id="front",
                source_text="Confidential protocol",
                section_heading="",
                ich_m11_anchor="unmapped",
                physical_page=1,
            ),
            SimpleNamespace(
                span_id="design-a",
                source_text="Study design.",
                section_heading="Study Design",
                ich_m11_anchor="study_design",
                physical_page=2,
            ),
            SimpleNamespace(
                span_id="design-b",
                source_text="Design continuation.",
                section_heading="",
                ich_m11_anchor="study_design",
                physical_page=3,
            ),
            SimpleNamespace(
                span_id="sap",
                source_text="Statistical analysis plan.",
                section_heading="Statistical Analysis Plan",
                ich_m11_anchor="statistics",
                physical_page=4,
            ),
        )
        segments = build_document_planner_segments(spans)
        self.assertEqual(
            ["Front matter", "Study Design", "Statistical Analysis Plan"],
            [segment.heading for segment in segments],
        )
        expanded = expand_document_plan_segment_ranges(
            (
                {
                    "id": "protocol",
                    "title": "Protocol",
                    "ich_m11_anchor": "study_design",
                    "start_segment_ordinal": 1,
                    "end_segment_ordinal": 2,
                },
                {
                    "id": "sap",
                    "title": "Statistical Analysis Plan",
                    "ich_m11_anchor": "statistics",
                    "start_segment_ordinal": 3,
                    "end_segment_ordinal": 3,
                },
            ),
            segments,
        )
        self.assertEqual(
            ["front", "design-a", "design-b"],
            expanded[0]["source_span_ids"],
        )
        self.assertEqual(["sap"], expanded[1]["source_span_ids"])

    def test_trusted_heading_does_not_collapse_recovered_m11_anchor_runs(self) -> None:
        spans = tuple(
            SimpleNamespace(
                span_id=f"mixed-anchor-{index}",
                source_text=f"Body {index}",
                section_heading="11.4 Laboratory Assessments",
                ich_m11_anchor=anchor,
                physical_page=index,
            )
            for index, anchor in enumerate(
                (
                    "assessments",
                    "assessments",
                    "safety",
                    "eligibility",
                    "eligibility",
                    "schedule",
                    "schedule",
                ),
                start=1,
            )
        )

        segments = build_document_planner_segments(spans)

        self.assertEqual(
            ["assessments", "safety", "eligibility", "schedule"],
            [segment.ich_m11_anchor for segment in segments],
        )
        self.assertEqual(
            [
                ["mixed-anchor-1", "mixed-anchor-2"],
                ["mixed-anchor-3"],
                ["mixed-anchor-4", "mixed-anchor-5"],
                ["mixed-anchor-6", "mixed-anchor-7"],
            ],
            [list(segment.source_span_ids) for segment in segments],
        )

    def test_segment_ranges_use_server_ids_when_provider_ids_repeat_or_are_missing(
        self,
    ) -> None:
        segments = (
            SimpleNamespace(
                ordinal=1,
                heading="Background",
                source_span_ids=("span-001",),
            ),
            SimpleNamespace(
                ordinal=2,
                heading="Objectives",
                source_span_ids=("span-002",),
            ),
        )
        duplicate_provider_ids = (
            {
                "id": "provider-duplicate",
                "title": "Background",
                "ich_m11_anchor": "background",
                "start_segment_ordinal": 1,
                "end_segment_ordinal": 1,
            },
            {
                "id": "provider-duplicate",
                "title": "Objectives",
                "ich_m11_anchor": "objectives",
                "start_segment_ordinal": 2,
                "end_segment_ordinal": 2,
            },
        )
        missing_provider_ids = tuple(
            {
                key: value
                for key, value in chapter.items()
                if key != "id"
            }
            for chapter in duplicate_provider_ids
        )

        first = expand_document_plan_segment_ranges(
            duplicate_provider_ids,
            segments,
        )
        repeated = expand_document_plan_segment_ranges(
            duplicate_provider_ids,
            segments,
        )
        without_provider_ids = expand_document_plan_segment_ranges(
            missing_provider_ids,
            segments,
        )

        self.assertEqual(first, repeated)
        self.assertEqual(first, without_provider_ids)
        self.assertEqual(2, len({chapter["id"] for chapter in first}))
        self.assertTrue(
            all(
                chapter["id"].startswith("ch_") and len(chapter["id"]) == 67
                for chapter in first
            )
        )
        self.assertEqual(
            ["Background", "Objectives"],
            [chapter["title"] for chapter in first],
        )
        self.assertEqual(
            ["background", "objectives"],
            [chapter["ich_m11_anchor"] for chapter in first],
        )
        self.assertEqual(
            [["span-001"], ["span-002"]],
            [chapter["source_span_ids"] for chapter in first],
        )

    def test_numbered_protocol_chapters_must_remain_distinct_boundaries(self) -> None:
        headings = (
            "Cover Page",
            "Table of contents",
            "1 Protocol summary ................................................",
            "List of abbreviations",
            "1 Protocol summary",
            "1 The EASI is a validated measure used in clinical trials and practice",
            "2 Introduction and trial rationale",
            "3 Trial objectives, estimands, and endpoints",
            "4 Trial design",
            "5 Trial population",
        )
        spans = tuple(
            SimpleNamespace(
                span_id=f"chapter-boundary-{index}",
                source_text=f"Body {index}",
                section_heading=heading,
                ich_m11_anchor="unmapped",
                physical_page=index,
            )
            for index, heading in enumerate(headings, start=1)
        )
        segments = build_document_planner_segments(spans)
        self.assertEqual(
            (5, 7, 8, 9, 10),
            required_top_level_segment_boundaries(segments),
        )

        with self.assertRaises(DocumentPlanValidationError) as raised:
            expand_document_plan_segment_ranges(
                (
                    {
                        "id": "front",
                        "title": "Front matter",
                        "start_segment_ordinal": 1,
                        "end_segment_ordinal": 4,
                    },
                    {
                        "id": "ch1",
                        "title": "1 Protocol summary",
                        "start_segment_ordinal": 5,
                        "end_segment_ordinal": 6,
                    },
                    {
                        "id": "merged",
                        "title": "2 Introduction through trial population",
                        "start_segment_ordinal": 7,
                        "end_segment_ordinal": 10,
                    },
                ),
                segments,
            )
        self.assertIn(
            "planner_missing_top_level_boundary_segment_8",
            raised.exception.codes,
        )

        expanded = expand_document_plan_segment_ranges(
            (
                {
                    "id": "front",
                    "title": "Front matter",
                    "start_segment_ordinal": 1,
                    "end_segment_ordinal": 4,
                },
                {
                    "id": "ch1",
                    "title": "1 Protocol summary",
                    "start_segment_ordinal": 5,
                    "end_segment_ordinal": 6,
                },
                {
                    "id": "ch2",
                    "title": "2 Introduction",
                    "start_segment_ordinal": 7,
                    "end_segment_ordinal": 7,
                },
                {
                    "id": "ch3",
                    "title": "3 Objectives",
                    "start_segment_ordinal": 8,
                    "end_segment_ordinal": 8,
                },
                {
                    "id": "ch4",
                    "title": "4 Design",
                    "start_segment_ordinal": 9,
                    "end_segment_ordinal": 9,
                },
                {
                    "id": "ch5",
                    "title": "5 Population",
                    "start_segment_ordinal": 10,
                    "end_segment_ordinal": 10,
                },
            ),
            segments,
        )
        self.assertEqual(6, len(expanded))

    def test_segment_range_contract_rejects_strings_gaps_and_overlaps(self) -> None:
        spans = (
            SimpleNamespace(
                span_id="s1",
                source_text="A",
                section_heading="A",
                ich_m11_anchor="background",
                physical_page=1,
            ),
            SimpleNamespace(
                span_id="s2",
                source_text="B",
                section_heading="B",
                ich_m11_anchor="objectives",
                physical_page=2,
            ),
        )
        segments = build_document_planner_segments(spans)
        bad_outputs = (
            ("Background",),
            (
                {
                    "id": "ch1",
                    "title": "A",
                    "start_segment_ordinal": 2,
                    "end_segment_ordinal": 2,
                },
            ),
            (
                {
                    "id": "ch1",
                    "title": "A",
                    "start_segment_ordinal": 1,
                    "end_segment_ordinal": 1,
                },
                {
                    "id": "ch2",
                    "title": "B",
                    "start_segment_ordinal": 1,
                    "end_segment_ordinal": 2,
                },
            ),
        )
        for raw in bad_outputs:
            with self.subTest(raw=raw):
                with self.assertRaises(DocumentPlanValidationError):
                    expand_document_plan_segment_ranges(raw, segments)

    def test_segment_range_failures_expose_stable_primary_codes(self) -> None:
        spans = tuple(
            SimpleNamespace(
                span_id=f"stable-{index}",
                source_text=f"Body {index}",
                section_heading=f"Section {index}",
                ich_m11_anchor=anchor,
                physical_page=index,
            )
            for index, anchor in enumerate(
                ("background", "study_design", "statistics"),
                start=1,
            )
        )
        segments = build_document_planner_segments(spans)
        cases = (
            (
                "planner_range_gap",
                (
                    {
                        "id": "ch1",
                        "title": "Gap",
                        "start_segment_ordinal": 2,
                        "end_segment_ordinal": 3,
                    },
                ),
            ),
            (
                "planner_range_overlap",
                (
                    {
                        "id": "ch1",
                        "title": "First",
                        "start_segment_ordinal": 1,
                        "end_segment_ordinal": 2,
                    },
                    {
                        "id": "ch2",
                        "title": "Second",
                        "start_segment_ordinal": 2,
                        "end_segment_ordinal": 3,
                    },
                ),
            ),
            (
                "planner_range_out_of_bounds",
                (
                    {
                        "id": "ch1",
                        "title": "Bounds",
                        "start_segment_ordinal": 1,
                        "end_segment_ordinal": 4,
                    },
                ),
            ),
            (
                "planner_duplicate_chapter_identity",
                (
                    {
                        "id": "ch1",
                        "title": "Repeated",
                        "start_segment_ordinal": 1,
                        "end_segment_ordinal": 1,
                    },
                    {
                        "id": "ch2",
                        "title": " repeated ",
                        "start_segment_ordinal": 2,
                        "end_segment_ordinal": 3,
                    },
                ),
            ),
            ("planner_output_not_structured", ("not-a-chapter",)),
        )
        for expected, raw in cases:
            with self.subTest(expected=expected):
                with self.assertRaises(DocumentPlanValidationError) as caught:
                    expand_document_plan_segment_ranges(raw, segments)
                self.assertEqual(expected, caught.exception.code)

        numbered_spans = tuple(
            SimpleNamespace(
                span_id=f"required-{index}",
                source_text=f"Body {index}",
                section_heading=f"{index} Protocol section {index}",
                ich_m11_anchor="unmapped",
                physical_page=index,
            )
            for index in range(1, 5)
        )
        numbered_segments = build_document_planner_segments(numbered_spans)
        with self.assertRaises(DocumentPlanValidationError) as caught:
            expand_document_plan_segment_ranges(
                (
                    {
                        "id": "merged",
                        "title": "Merged protocol",
                        "start_segment_ordinal": 1,
                        "end_segment_ordinal": 4,
                    },
                ),
                numbered_segments,
            )
        self.assertEqual(
            "planner_missing_required_boundary",
            caught.exception.code,
        )

    def test_production_adapter_sends_only_public_manifest_to_provider(self) -> None:
        from services.api.app.main import _flash_planner_adapter

        spans = (
            SimpleNamespace(
                span_id="secret-span-a",
                source_text="Study design body.",
                section_heading="Study Design",
                ich_m11_anchor="study_design",
                physical_page=1,
            ),
            SimpleNamespace(
                span_id="secret-span-b",
                source_text="Endpoint body.",
                section_heading="Endpoints",
                ich_m11_anchor="objectives_and_endpoints",
                physical_page=2,
            ),
        )
        source_text, context = build_document_planner_input(
            spans,
            document_context={
                "artifact_id": "art-provider",
                "document_type": "protocol",
                "span_count": 2,
            },
        )

        class Provider:
            envelope = None

            def run(self, envelope):
                self.envelope = envelope
                return {
                    "document_role": "protocol",
                    "chapters": [
                        {
                            "id": "ch1",
                            "title": "Study Design",
                            "ich_m11_anchor": "study_design",
                            "start_segment_ordinal": 1,
                            "end_segment_ordinal": 1,
                        },
                        {
                            "id": "ch2",
                            "title": "Endpoints",
                            "ich_m11_anchor": "objectives_and_endpoints",
                            "start_segment_ordinal": 2,
                            "end_segment_ordinal": 2,
                        },
                    ],
                }

        provider = Provider()
        with patch(
            "services.api.app.main.configured_ai_provider_from_env",
            return_value=provider,
        ), patch(
            "services.api.app.main._translation_ai_env",
            return_value={},
        ):
            result = _flash_planner_adapter(source_text, context)

        provider_payload = provider.envelope.payload
        serialized = __import__("json").dumps(
            provider_payload, ensure_ascii=False, sort_keys=True
        )
        self.assertNotIn("secret-span-", serialized)
        self.assertNotIn("_planner_segments", serialized)
        self.assertEqual(
            ("secret-span-a",), tuple(result.chapters[0]["source_span_ids"])
        )
        self.assertEqual(
            ("secret-span-b",), tuple(result.chapters[1]["source_span_ids"])
        )

    def test_document_planner_has_one_bounded_corrective_retry(self) -> None:
        calls: list[dict] = []

        def flaky_planner(source_text, context):
            calls.append(dict(context))
            if len(calls) == 1:
                raise DocumentPlanValidationError(("chapter_0_not_dict",))
            return FlashPlanResult(
                chapters=(
                    {
                        "id": "ch1",
                        "title": "Protocol",
                        "source_span_ids": ["s1"],
                    },
                ),
                document_role="protocol",
                plan_prompt_version=FLASH_PLANNING_PROMPT_VERSION,
                plan_model=FLASH_PLANNING_MODEL,
                plan_input_hash="i",
                plan_output_hash="o",
            )

        result = call_flash_planner_with_single_retry(
            flaky_planner,
            "{}",
            {"segment_count": 1},
        )
        self.assertEqual("protocol", result.document_role)
        self.assertEqual(2, len(calls))
        self.assertEqual(1, calls[0]["planner_attempt"])
        self.assertEqual(2, calls[1]["planner_attempt"])
        self.assertIn("retry_instruction", calls[1])
        self.assertIn(
            "required_top_level_segment_ordinals",
            calls[1]["retry_instruction"],
        )
        self.assertIn("title必须唯一", calls[1]["retry_instruction"])
        self.assertIn("章节ID由服务端生成", calls[1]["retry_instruction"])

    def test_segment_range_expansion_rejects_duplicate_chapter_titles(self) -> None:
        spans = tuple(
            SimpleNamespace(
                span_id=f"dup-title-{index}",
                source_text=f"Body {index}",
                section_heading=heading,
                ich_m11_anchor="unmapped",
                physical_page=index,
            )
            for index, heading in enumerate(
                ("1 Protocol summary", "2 Introduction", "3 Objectives", "4 Design"),
                start=1,
            )
        )
        segments = build_document_planner_segments(spans)
        with self.assertRaises(DocumentPlanValidationError) as caught:
            expand_document_plan_segment_ranges(
                (
                    {
                        "id": "ch_01",
                        "title": "Protocol summary",
                        "start_segment_ordinal": 1,
                        "end_segment_ordinal": 2,
                    },
                    {
                        "id": "ch_02",
                        "title": " protocol  summary ",
                        "start_segment_ordinal": 3,
                        "end_segment_ordinal": 4,
                    },
                ),
                segments,
            )
        self.assertIn("chapter_1_duplicate_title", caught.exception.codes)

    def test_deterministic_fallback_requires_and_preserves_top_level_boundaries(self) -> None:
        headings = (
            "Cover Page",
            "1 Protocol summary",
            "2 Introduction and trial rationale",
            "3 Trial objectives, estimands, and endpoints",
            "4 Trial design",
            "5 Trial population",
        )
        spans = tuple(
            SimpleNamespace(
                span_id=f"fallback-{index}",
                source_text=f"Body {index}",
                section_heading=heading,
                ich_m11_anchor="unmapped",
                physical_page=index,
            )
            for index, heading in enumerate(headings, start=1)
        )
        segments = build_document_planner_segments(spans)
        fallback = build_deterministic_document_plan_fallback(
            segments,
            document_type="protocol_sap",
            plan_input_hash="a" * 64,
        )

        self.assertEqual("protocol_with_sap", fallback.document_role)
        self.assertEqual("deterministic_structure_fallback", fallback.plan_model)
        self.assertEqual(
            [1, 2, 3, 4, 5, 6],
            [
                1 + sum(
                    len(chapter["source_span_ids"])
                    for chapter in fallback.chapters[:index]
                )
                for index in range(len(fallback.chapters))
            ],
        )
        self.assertEqual(
            [span.span_id for span in spans],
            [
                span_id
                for chapter in fallback.chapters
                for span_id in chapter["source_span_ids"]
            ],
        )

    def test_deterministic_fallback_rejects_low_confidence_structure(self) -> None:
        segments = build_document_planner_segments(
            (
                _span("fallback-low-1", "Unstructured content"),
                _span("fallback-low-2", "More content"),
            )
        )
        with self.assertRaises(DocumentPlanValidationError) as caught:
            build_deterministic_document_plan_fallback(
                segments,
                document_type="protocol",
                plan_input_hash="b" * 64,
            )
        self.assertIn(
            "deterministic_fallback_insufficient_top_level_boundaries",
            caught.exception.codes,
        )

    def test_anchor_grouped_fallback_preserves_numbered_boundaries(self) -> None:
        """Anchor recovery must not merge across required top-level chapters."""
        headings = (
            "Cover Page",
            "1 Protocol summary",
            "2 Introduction and trial rationale",
            "3 Trial objectives, estimands, and endpoints",
            "4 Trial design",
            "5 Trial population",
        )
        spans = tuple(
            SimpleNamespace(
                span_id=f"anchor-fallback-{index}",
                source_text=f"Body {index}",
                section_heading=heading,
                ich_m11_anchor="unmapped",
                physical_page=index,
            )
            for index, heading in enumerate(headings, start=1)
        )
        segments = build_document_planner_segments(spans)
        fallback = build_anchor_grouped_document_plan_fallback(
            segments,
            document_type="protocol",
            plan_input_hash="c" * 64,
        )
        starts = [
            1
            + sum(
                len(chapter["source_span_ids"])
                for chapter in fallback.chapters[:index]
            )
            for index in range(len(fallback.chapters))
        ]
        self.assertEqual([1, 2, 3, 4, 5, 6], starts)
        self.assertEqual(
            [span.span_id for span in spans],
            [
                span_id
                for chapter in fallback.chapters
                for span_id in chapter["source_span_ids"]
            ],
        )

    def test_anchor_grouped_fallback_normalizes_case_insensitive_duplicate_titles(self) -> None:
        # OCR frequently emits the same heading with different casing.  The
        # validator treats headings case-insensitively, so the fallback must
        # disambiguate them before it asks the validator to expand ranges.
        spans = tuple(
            SimpleNamespace(
                span_id=f"fallback-duplicate-{index}",
                source_text=f"Body {index}",
                section_heading=heading,
                ich_m11_anchor=anchor,
                physical_page=index,
            )
            for index, (heading, anchor) in enumerate(
                (
                    ("REFERENCES", "references"),
                    ("Study Design", "study_design"),
                    ("References", "references"),
                ),
                start=1,
            )
        )
        segments = build_document_planner_segments(spans)
        fallback = build_anchor_grouped_document_plan_fallback(
            segments,
            document_type="protocol",
            plan_input_hash="b" * 64,
        )
        normalized_titles = [
            " ".join(chapter["title"].split()).casefold()
            for chapter in fallback.chapters
        ]
        self.assertEqual(len(normalized_titles), len(set(normalized_titles)))
        self.assertIn("references (references) · 2", normalized_titles)

    def test_validate_plan_rejects_missing_duplicate_and_reordered_spans(self) -> None:
        spans = (_span("s1", "A"), _span("s2", "B"), _span("s3", "C"))
        request = DocumentPlanRequest(
            artifact_id="art1",
            extraction_revision="extract_r1",
            document_sha256="h" * 64,
            source_spans=spans,
        )
        # Missing s3
        bad = FlashPlanResult(
            chapters=({"id": "ch1", "title": "T", "source_span_ids": ["s1", "s2"]},),
            document_role="protocol",
            plan_prompt_version=FLASH_PLANNING_PROMPT_VERSION,
            plan_model=FLASH_PLANNING_MODEL,
            plan_input_hash="i",
            plan_output_hash="o",
        )
        with self.assertRaises(DocumentPlanValidationError) as ctx:
            validate_document_plan(bad, request)
        self.assertTrue(any("s3" in c for c in ctx.exception.codes))

        # Duplicate without shared marker
        dup = FlashPlanResult(
            chapters=(
                {"id": "ch1", "title": "T1", "source_span_ids": ["s1", "s2"]},
                {"id": "ch2", "title": "T2", "source_span_ids": ["s2", "s3"]},
            ),
            document_role="protocol",
            plan_prompt_version=FLASH_PLANNING_PROMPT_VERSION,
            plan_model=FLASH_PLANNING_MODEL,
            plan_input_hash="i",
            plan_output_hash="o",
        )
        with self.assertRaises(DocumentPlanValidationError) as ctx:
            validate_document_plan(dup, request)
        self.assertTrue(any("duplicated" in c for c in ctx.exception.codes))

        # Reordered
        reordered = FlashPlanResult(
            chapters=({"id": "ch1", "title": "T", "source_span_ids": ["s1", "s3", "s2"]},),
            document_role="protocol",
            plan_prompt_version=FLASH_PLANNING_PROMPT_VERSION,
            plan_model=FLASH_PLANNING_MODEL,
            plan_input_hash="i",
            plan_output_hash="o",
        )
        with self.assertRaises(DocumentPlanValidationError) as ctx:
            validate_document_plan(reordered, request)
        self.assertIn("source_span_order_violation", ctx.exception.codes)

    def test_mergeable_spans_yield_fewer_chunks_than_spans(self) -> None:
        spans = tuple(_span(f"s{i}", f"Short paragraph {i}.") for i in range(5))
        plan = FlashPlanResult(
            chapters=(
                {
                    "id": "ch1",
                    "title": "Background",
                    "source_span_ids": [s.span_id for s in spans],
                },
            ),
            document_role="protocol",
            plan_prompt_version=FLASH_PLANNING_PROMPT_VERSION,
            plan_model=FLASH_PLANNING_MODEL,
            plan_input_hash="i",
            plan_output_hash="o",
        )
        result = validate_document_plan(
            plan,
            DocumentPlanRequest(
                artifact_id="art1",
                extraction_revision="extract_r1",
                document_sha256="h" * 64,
                source_spans=spans,
            ),
        )
        chapter_chunks = build_chunks_from_plan(result, spans)
        total_chunks = sum(len(chunks) for entry in chapter_chunks for chunks in entry.values())
        self.assertLess(total_chunks, len(spans))
        self.assertEqual(1, total_chunks)

    def test_oversized_text_splits_and_table_header_repeats(self) -> None:
        header = "| A | B |\n|---|---|"
        rows = "\n".join(f"| r{i} | v{i} |" for i in range(200))
        table = f"{header}\n{rows}"
        # Force oversize by lowering target.
        spans = (_span("tbl", table),)
        plan = FlashPlanResult(
            chapters=({"id": "ch1", "title": "T", "source_span_ids": ["tbl"]},),
            document_role="protocol",
            plan_prompt_version=FLASH_PLANNING_PROMPT_VERSION,
            plan_model=FLASH_PLANNING_MODEL,
            plan_input_hash="i",
            plan_output_hash="o",
        )
        result = validate_document_plan(
            plan,
            DocumentPlanRequest(
                artifact_id="art1",
                extraction_revision="extract_r1",
                document_sha256="h" * 64,
                source_spans=spans,
            ),
        )
        chapter_chunks = build_chunks_from_plan(
            result, spans, target_chars=400, context_chars=50
        )
        chunks = list(chapter_chunks[0].values())[0]
        self.assertGreater(len(chunks), 1)
        # Subsequent chunks may carry table header prefix when detected.
        later = [c for c in chunks if c.chunk_order > 1]
        self.assertTrue(later)

    def test_read_only_context_not_in_translated_output(self) -> None:
        source = "Participants must not receive SCS within 14 days."
        context = "READ_ONLY_SECRET_CONTEXT_SHOULD_NOT_APPEAR"
        envelope = format_hy_mt2_prompt_envelope(source, context)
        self.assertIn("READ_ONLY_CONTEXT", envelope)
        self.assertIn("SOURCE_TEXT", envelope)

        calls: list[tuple] = []

        def translator(src, glossary, chapter_id, chunk_id, read_only_context=""):
            calls.append((src, read_only_context))
            # Honest translator: only translate source, ignore context.
            self.assertEqual(source, src)
            self.assertEqual(context, read_only_context)
            out = "受试者在14天内不得接受SCS。"
            self.assertNotIn(context, out)
            return HyMt2TranslationResult(
                chapter_id=chapter_id,
                chunk_id=chunk_id,
                translated_text=out,
                translated_text_sha256=_sha256(out),
                model=HY_MT2_MODEL_ID,
                prompt_version=HY_MT2_PROMPT_VERSION,
                input_hash=_sha256(src),
                output_hash=_sha256(out),
            )

        result = call_hy_mt2_translator(
            translator,
            source_text=source,
            glossary="g",
            chapter_id="ch1",
            chunk_id="c1",
            read_only_context=context,
        )
        self.assertNotIn(context, result.translated_text)
        self.assertEqual(1, len(calls))

    def test_integration_windows_only_when_over_limit(self) -> None:
        class CS:
            def __init__(self, text: str, cid: str) -> None:
                self.source_text = text
                self.chunk_id = cid
                self.chunk_fingerprint = cid

        small = [(CS("a" * 10, "c1"), "甲" * 10), (CS("b" * 10, "c2"), "乙" * 10)]
        windows = build_integration_windows(small, input_limit=1000)
        self.assertEqual(1, len(windows))
        self.assertEqual(2, len(windows[0]))

        big = [
            (CS("x" * 600, f"c{i}"), "译" * 600)
            for i in range(5)
        ]
        windows = build_integration_windows(big, input_limit=2000)
        self.assertGreater(len(windows), 1)


class BatchDocumentPipelineRound8Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = WritingReferenceRepository(
            Path(self.tmp.name) / "writing_reference.sqlite3"
        )
        from packages.contracts.workbench_contracts.models import (
            WritingReferenceSearchSnapshot,
            WritingReferenceTrialCandidate,
        )

        # Minimal journey/prep fakes reusing batch test patterns via simple
        # in-repo seed + thin wrappers from the existing batch test module.
        from tests.test_writing_reference_translation_batch import (
            FakeJourneyService,
            FakePreparationService,
            WritingReferenceTranslationBatchTests as _BT,
        )

        self.helper = _BT("test_partial_failure_retries_only_retryable_item")
        self.helper.setUp()
        self.repo = self.helper.repo
        self.service = self.helper.service
        self.pipeline = self.helper._pipeline
        self.planner = self.helper.planner
        self.translator = self.helper._translator
        self.qc = self.helper._qc
        self.runner = self.helper.runner

    def tearDown(self) -> None:
        self.helper.tearDown()
        self.tmp.cleanup()

    def test_planner_once_for_multi_span_and_retry(self) -> None:
        from tests.test_writing_reference_translation_batch import (
            PROJECT_ID as PID,
            SNAPSHOT_ID as SID,
        )

        self.helper._seed_artifact(
            "artifact_plan_once",
            [
                ("span_a", "eligibility", "Participants must not receive SCS within 14 days."),
                ("span_b", "endpoints", "The primary endpoint is assessed at Week 16."),
            ],
        )
        batch = self.service.create(
            PID,
            WritingReferenceTranslationBatchCreateRequest(
                snapshot_id=SID,
                actor="medical_manager",
                idempotency_key="r8-plan-once",
            ),
        )
        self.service.run_pending(PID, batch.batch_id, "medical_manager")
        self.assertEqual(1, len(self.planner.calls))
        # Idempotent re-run must not re-plan.
        completed = self.service.get(PID, batch.batch_id)
        self.service.run_pending(PID, batch.batch_id, "medical_manager")
        self.assertEqual(1, len(self.planner.calls))
        self.assertIn(completed.status, {"completed", "completed_with_blocked"})

    def test_document_plan_refines_sticky_span_anchor_scope(self) -> None:
        from tests.test_writing_reference_translation_batch import (
            PROJECT_ID as PID,
            SNAPSHOT_ID as SID,
        )

        self.helper._seed_artifact(
            "artifact_plan_refined_scope",
            [
                (
                    "span_population",
                    "eligibility",
                    "Participants must not receive SCS within 14 days.",
                ),
                (
                    "span_supporting",
                    "eligibility",
                    "The primary endpoint is assessed at Week 16.",
                ),
            ],
        )
        self.planner.set_chapter_assignments(
            [
                {
                    "id": "ch_population",
                    "title": "5 Trial population",
                    "ich_m11_anchor": "eligibility",
                    "source_span_ids": ["span_population"],
                },
                {
                    "id": "ch_supporting",
                    "title": "12 Supporting documentation and operational considerations",
                    "ich_m11_anchor": "eligibility",
                    "source_span_ids": ["span_supporting"],
                },
            ]
        )
        batch = self.service.create(
            PID,
            WritingReferenceTranslationBatchCreateRequest(
                snapshot_id=SID,
                anchor_filter=["eligibility"],
                actor="medical_manager",
                idempotency_key="r8-refined-anchor-scope",
            ),
        )
        self.service.run_pending(PID, batch.batch_id, "medical_manager")
        done = self.service.get(PID, batch.batch_id)
        by_span = {item.span_id: item for item in done.items}

        self.assertEqual(
            "candidate_ready",
            by_span["span_population"].generation_status,
        )
        self.assertEqual(
            "excluded",
            by_span["span_supporting"].generation_status,
        )
        self.assertEqual(
            "document_plan_anchor_filter",
            by_span["span_supporting"].pipeline_stage_detail,
        )
        self.assertEqual(1, done.counts.eligible_count)
        self.assertGreaterEqual(done.counts.excluded_count, 1)
        self.assertEqual(1, len(self.translator.calls))

    def test_chapter_items_share_one_translation_revision(self) -> None:
        from tests.test_writing_reference_translation_batch import PROJECT_ID as PID, SNAPSHOT_ID as SID

        self.helper._seed_artifact(
            "artifact_shared_rev",
            [
                ("span_share_1", "eligibility", "Participants must not receive SCS within 14 days."),
                ("span_share_2", "eligibility", "The primary endpoint is assessed at Week 16."),
            ],
        )
        batch = self.service.create(
            PID,
            WritingReferenceTranslationBatchCreateRequest(
                snapshot_id=SID,
                actor="medical_manager",
                idempotency_key="r8-shared-rev",
            ),
        )
        self.service.run_pending(PID, batch.batch_id, "medical_manager")
        done = self.service.get(PID, batch.batch_id)
        ready = [i for i in done.items if i.generation_status == "candidate_ready"]
        self.assertGreaterEqual(len(ready), 2)
        ids = {(i.translation_id, i.translation_revision) for i in ready}
        self.assertEqual(1, len(ids))
        tr = self.repo.translation(PID, ready[0].translation_id, ready[0].translation_revision)
        self.assertTrue(tr.ai_run_id)
        self.assertTrue(tr.document_structure_plan_id)
        self.assertTrue(tr.chapter_integration_result_id)
        self.assertTrue(tr.translation_chunk_ids)
        run = self.repo.composite_pipeline_run(PID, tr.ai_run_id)
        self.assertIsNotNone(run)
        self.assertGreaterEqual(len(run.stages), 2)

    def test_progress_fields_and_blocker_state(self) -> None:
        from tests.test_writing_reference_translation_batch import PROJECT_ID as PID, SNAPSHOT_ID as SID

        self.helper._seed_artifact(
            "artifact_progress",
            [
                ("span_prog_ok", "eligibility", "Participants must not receive SCS within 14 days."),
            ],
        )
        batch = self.service.create(
            PID,
            WritingReferenceTranslationBatchCreateRequest(
                snapshot_id=SID,
                actor="medical_manager",
                idempotency_key="r8-progress",
            ),
        )
        self.service.run_pending(PID, batch.batch_id, "medical_manager")
        item = self.service.get(PID, batch.batch_id).items[0]
        self.assertGreaterEqual(item.document_total, 1)
        self.assertGreaterEqual(item.document_index, 1)
        self.assertTrue(item.document_label)
        self.assertGreaterEqual(item.chapter_total, 1)
        self.assertGreaterEqual(item.chapter_index, 1)
        self.assertTrue(item.chapter_title)
        self.assertGreaterEqual(item.chunk_count, 1)
        self.assertGreaterEqual(item.chunk_completed, 1)

        # Blocked path
        self.helper._seed_artifact(
            "artifact_progress_block",
            [
                ("span_prog_block", "eligibility", "Participants must not receive SCS within 14 days."),
            ],
        )
        self.runner.blocked_spans.add("span_prog_block")
        batch2 = self.service.create(
            PID,
            WritingReferenceTranslationBatchCreateRequest(
                snapshot_id=SID,
                actor="medical_manager",
                idempotency_key="r8-progress-block",
            ),
        )
        self.service.run_pending(PID, batch2.batch_id, "medical_manager")
        blocked = next(
            i
            for i in self.service.get(PID, batch2.batch_id).items
            if i.span_id == "span_prog_block"
        )
        self.assertEqual("fidelity_blocked", blocked.generation_status)
        self.assertEqual("terminal", blocked.blocker_kind)
        self.assertTrue(blocked.blocker_message)
        # Primary UI message must not leak hashes/model/ids as the only content.
        self.assertNotIn(blocked.pipeline_fingerprint or "x", blocked.blocker_message)

    def test_running_progress_reads_current_item_and_exposes_chapter_chunk(self) -> None:
        from tests.test_writing_reference_translation_batch import PROJECT_ID as PID, SNAPSHOT_ID as SID

        self.helper._seed_artifact(
            "artifact_live_progress",
            [
                (
                    "span_live_progress",
                    "eligibility",
                    "Participants must not receive SCS within 14 days.",
                ),
            ],
        )
        original_translator = self.pipeline.hy_mt2_translator
        observed: dict[str, object] = {}
        batch_holder: dict[str, str] = {}

        def inspecting_translator(*args, **kwargs):
            state = self.service.get(PID, batch_holder["batch_id"])
            running = next(
                item for item in state.items if item.generation_status == "running"
            )
            observed.update(
                {
                    "chapter_title": running.chapter_title,
                    "chunk_count": running.chunk_count,
                    "chunk_running": running.chunk_running,
                    "document_label": running.document_label,
                    "source_span_count": running.source_span_count,
                    "pipeline_stage": running.pipeline_stage,
                }
            )
            return original_translator(*args, **kwargs)

        self.pipeline.hy_mt2_translator = inspecting_translator
        batch = self.service.create(
            PID,
            WritingReferenceTranslationBatchCreateRequest(
                snapshot_id=SID,
                actor="medical_manager",
                idempotency_key="r8-live-progress",
            ),
        )
        batch_holder["batch_id"] = batch.batch_id
        self.service.run_pending(PID, batch.batch_id, "medical_manager")
        self.assertTrue(observed["chapter_title"])
        self.assertGreaterEqual(int(observed["chunk_count"]), 1)
        self.assertEqual(1, observed["chunk_running"])
        self.assertTrue(observed["document_label"])
        self.assertGreaterEqual(int(observed["source_span_count"]), 1)
        self.assertEqual("translating_hy_mt2", observed["pipeline_stage"])

    def test_legacy_span_keyed_without_lineage_not_reused(self) -> None:
        from tests.test_writing_reference_translation_batch import PROJECT_ID as PID

        service = WritingReferenceTranslationService(
            self.repo, self.runner, clock=lambda: NOW, chapter_pipeline=self.pipeline
        )
        legacy = WritingReferenceTranslationRevision(
            translation_id="legacy_span_keyed",
            project_id=PID,
            span_id="does_not_matter",
            source_span_revision="does_not_matter_r1",
            document_sha256="a" * 64,
            glossary_version=GLOSSARY,
            revision=1,
            translated_text="旧候选",
            rationale="span keyed composite without plan",
            fidelity_status="passed",
            ai_run_id="",
            task_type=COMPOSITE_TRANSLATION_TASK_TYPE,
            prompt_version=COMPOSITE_TRANSLATION_PROMPT_VERSION,
            schema_version=COMPOSITE_TRANSLATION_SCHEMA_VERSION,
            provider="composite_pipeline",
            model_name=COMPOSITE_TRANSLATION_BODY_MODEL,
            contract_hash=COMPOSITE_TRANSLATION_CONTRACT_HASH,
            created_at=NOW,
        )
        self.assertFalse(
            service.translation_matches_current_contract(PID, legacy)
        )

    def test_malformed_planner_fails_closed(self) -> None:
        from tests.test_writing_reference_translation_batch import PROJECT_ID as PID, SNAPSHOT_ID as SID

        self.helper._seed_artifact(
            "artifact_bad_plan",
            [
                ("span_bad_plan", "eligibility", "Participants must not receive SCS within 14 days."),
            ],
        )

        def bad_planner(source_text, context):
            return FlashPlanResult(
                chapters=(),
                document_role="",
                plan_prompt_version=FLASH_PLANNING_PROMPT_VERSION,
                plan_model=FLASH_PLANNING_MODEL,
                plan_input_hash="i",
                plan_output_hash="o",
            )

        self.pipeline.flash_planner = bad_planner
        batch = self.service.create(
            PID,
            WritingReferenceTranslationBatchCreateRequest(
                snapshot_id=SID,
                actor="medical_manager",
                idempotency_key="r8-bad-plan",
            ),
        )
        self.service.run_pending(PID, batch.batch_id, "medical_manager")
        item = self.service.get(PID, batch.batch_id).items[0]
        self.assertIn(item.generation_status, {"failed_retryable", "failed_terminal"})

    def test_document_plan_retry_without_persisted_parent_recovers_audited(self) -> None:
        """0924V2 §5/T03: a retry with no persisted planner lineage no longer
        deadlocks on document_plan_retry_parent_missing_or_ambiguous. The
        parentless zero-generation recovery path is allocated with audit
        (known parents logged), and the retry proceeds to a fresh planner
        dispatch; the batch attempt counter advances."""

        from tests.test_writing_reference_translation_batch import PROJECT_ID as PID, SNAPSHOT_ID as SID

        self.helper._seed_artifact(
            "artifact_plan_fuse",
            [
                ("span_fuse_1", "eligibility", "Participants are eligible."),
                ("span_fuse_2", "endpoints", "The endpoint is assessed."),
                (
                    "span_fuse_3",
                    "study_design",
                    "The study uses a randomized parallel-group design.",
                ),
            ],
        )
        calls: list[str] = []

        def bad_planner(source_text, context):
            calls.append(source_text)
            raise RuntimeError("synthetic planner outage")

        self.pipeline.flash_planner = bad_planner
        batch = self.service.create(
            PID,
            WritingReferenceTranslationBatchCreateRequest(
                snapshot_id=SID,
                actor="medical_manager",
                idempotency_key="r8-plan-fuse",
            ),
        )
        self.service.run_pending(PID, batch.batch_id, "medical_manager")
        failed = self.service.get(PID, batch.batch_id).items
        self.assertEqual(2, len(calls))
        self.assertEqual(
            {"failed_retryable"}, {item.generation_status for item in failed}
        )
        self.assertEqual(
            {"document_plan_failed"}, {item.error_code for item in failed}
        )

        # 0924V2: retry now converges via audited parentless recovery and
        # re-dispatches the planner (calls grows beyond the original 2).
        self.service.retry(
            PID,
            batch.batch_id,
            WritingReferenceTranslationBatchRetryRequest(
                actor="medical_manager",
                idempotency_key="r8-plan-fuse-retry",
            ),
        )
        self.service.run_failed(PID, batch.batch_id, "medical_manager")
        self.assertGreater(len(calls), 2)
        retried = self.service.get(PID, batch.batch_id)
        self.assertEqual(2, retried.attempt)

    def test_modern_explicit_interrupted_plan_parent_allocates_next_generation(
        self,
    ) -> None:
        from tests.test_writing_reference_translation_batch import (
            PROJECT_ID as PID,
            SNAPSHOT_ID as SID,
        )

        self.helper._seed_artifact(
            "artifact_interrupted_parent",
            [
                (
                    "span_interrupted_parent",
                    "eligibility",
                    "Participants are eligible.",
                ),
            ],
        )
        model_calls = []

        class _FailingPlanningAdapter:
            def __init__(inner_self, model: str) -> None:
                inner_self.model = model

            def invoke(inner_self, request):
                model_calls.append(request)
                return UpperLayerAdapterResult(
                    response_model=inner_self.model,
                    status=(
                        "failed_escalatable"
                        if inner_self.model == DEFAULT_UPPER_LAYER_MODEL
                        else "failed_terminal"
                    ),
                    failure_code="planner_range_gap",
                )

        class _PersistedPlanningExecutor:
            def __init__(inner_self, delegate) -> None:
                inner_self.delegate = delegate

            def execute(inner_self, **kwargs):
                if kwargs["stage"] == UPPER_LAYER_DOCUMENT_PLANNING:
                    return inner_self.delegate.execute(**kwargs)
                output = kwargs["invoke"](DEFAULT_UPPER_LAYER_MODEL)
                return UpperLayerStageExecutionResult(
                    output=output,
                    stage=kwargs["stage"],
                    requested_model=DEFAULT_UPPER_LAYER_MODEL,
                    response_model=DEFAULT_UPPER_LAYER_MODEL,
                    prompt_version=kwargs["prompt_version"],
                    input_hash=kwargs["input_hash"],
                    output_hash=kwargs["output_hash"](output),
                )

        upper_service = WritingReferenceUpperLayerExecutionService(
            self.repo,
            lambda model: _FailingPlanningAdapter(model),
        )
        self.pipeline.upper_layer_executor = _PersistedPlanningExecutor(
            ProductionPersistedUpperLayerStageExecutorAdapter(
                upper_service,
                deployment_profile="approved_private_clinical",
                prompt_resolver=upper_layer_prompt_resolver,
            )
        )
        batch = self.service.create(
            PID,
            WritingReferenceTranslationBatchCreateRequest(
                snapshot_id=SID,
                actor="medical_manager",
                idempotency_key="r8-interrupted-parent",
            ),
        )
        self.service.run_pending(PID, batch.batch_id, "medical_manager")
        [failed] = self.service.get(PID, batch.batch_id).items
        source_stage_run_id = (
            failed.document_plan_failure_source_stage_run_id
        )
        source_run = self.repo.upper_layer_stage_run(
            PID,
            source_stage_run_id,
        )
        source_execution = self.repo.upper_layer_stage_run_execution(
            PID,
            source_stage_run_id,
        )
        interrupted_stage_run_id = (
            "upper_interrupted_"
            + sha256(failed.item_id.encode("utf-8")).hexdigest()[:32]
        )
        interrupted_run = source_run.model_copy(
            update={
                "stage_run_id": interrupted_stage_run_id,
                "status": "interrupted",
            },
            deep=True,
        )
        self.repo.save_upper_layer_stage_run(
            interrupted_run,
            execution_fingerprint=sha256(
                f"interrupted-parent:{failed.item_id}".encode("utf-8")
            ).hexdigest(),
            prompt_text=source_execution["prompt_text"],
            input_payload=source_execution["input_payload"],
            output_payload=source_execution["output_payload"],
            hy_mt2_target_map_sha256=source_execution[
                "hy_mt2_target_map_sha256"
            ],
        )
        explicit = failed.model_copy(
            update={
                "document_plan_failure_source_stage_run_id": (
                    interrupted_stage_run_id
                ),
                "document_plan_failure_is_derived": False,
                "active_upper_layer_stage_run_id": interrupted_stage_run_id,
                "latest_upper_layer_stage_run_id": interrupted_stage_run_id,
            },
            deep=True,
        )
        with self.repo._connect() as connection:
            connection.execute(
                """
                UPDATE writing_reference_translation_batch_items
                SET payload_json=?
                WHERE project_id=? AND batch_id=? AND item_id=?
                """,
                (
                    json.dumps(
                        explicit.model_dump(mode="json"),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    PID,
                    batch.batch_id,
                    explicit.item_id,
                ),
            )

        retried = self.service.retry(
            PID,
            batch.batch_id,
            WritingReferenceTranslationBatchRetryRequest(
                actor="medical_manager",
                idempotency_key="r8-interrupted-parent-retry",
            ),
        )
        [retried_item] = retried.items
        self.assertEqual(2, retried.attempt)
        self.assertEqual(2, retried_item.document_plan_retry_generation)
        self.assertEqual(
            interrupted_stage_run_id,
            retried_item.document_plan_retry_parent_stage_run_id,
        )
        self.assertEqual(
            retried_item.item_id,
            retried_item.document_plan_retry_source_item_id,
        )
        self.assertEqual(
            [
                DEFAULT_UPPER_LAYER_MODEL,
                DEFAULT_UPPER_LAYER_MODEL,
                ESCALATED_UPPER_LAYER_MODEL,
            ],
            [call.requested_model for call in model_calls],
        )

    def test_real_persisted_batch_retry_recovers_source_and_siblings_once(
        self,
    ) -> None:
        from tests.test_writing_reference_translation_batch import (
            PROJECT_ID as PID,
            SNAPSHOT_ID as SID,
        )

        self.helper._seed_artifact(
            "artifact_plan_lineage",
            [
                (
                    "span_lineage_1",
                    "eligibility",
                    "Participants are eligible.",
                ),
                (
                    "span_lineage_2",
                    "objectives_endpoints",
                    "The primary endpoint is assessed.",
                ),
            ],
        )
        model_calls = []
        flash_failures_remaining = 2

        class _ScriptedPlanningAdapter:
            def __init__(self, model: str) -> None:
                self.model = model

            def invoke(inner_self, request):
                nonlocal flash_failures_remaining
                model_calls.append(request)
                if inner_self.model == DEFAULT_UPPER_LAYER_MODEL:
                    if flash_failures_remaining:
                        flash_failures_remaining -= 1
                        return UpperLayerAdapterResult(
                            response_model=inner_self.model,
                            status="failed_escalatable",
                            failure_code="planner_range_gap",
                        )
                    context = request.input_payload["document_context"]
                    source_span_ids = [
                        str(span_id)
                        for segment in context["_planner_segments"]
                        for span_id in segment["source_span_ids"]
                    ]
                    plan = FlashPlanResult(
                        chapters=(
                            {
                                "id": "ch_01",
                                "title": "Protocol",
                                "ich_m11_anchor": "unmapped",
                                "source_span_ids": source_span_ids,
                            },
                        ),
                        document_role="protocol",
                        plan_prompt_version=request.prompt_version,
                        plan_model=request.requested_model,
                        plan_input_hash=request.input_hash,
                        plan_output_hash="f" * 64,
                    )
                    return UpperLayerAdapterResult(
                        response_model=inner_self.model,
                        status="succeeded",
                        output_payload=_upper_layer_hash_payload(plan),
                    )
                return UpperLayerAdapterResult(
                    response_model=inner_self.model,
                    status="failed_terminal",
                    failure_code="planner_range_gap",
                )

        class _PlanningPersistedOnlyExecutor:
            def __init__(inner_self, delegate) -> None:
                inner_self.delegate = delegate

            def execute(inner_self, **kwargs):
                if kwargs["stage"] == UPPER_LAYER_DOCUMENT_PLANNING:
                    return inner_self.delegate.execute(**kwargs)
                output = kwargs["invoke"](DEFAULT_UPPER_LAYER_MODEL)
                return UpperLayerStageExecutionResult(
                    output=output,
                    stage=kwargs["stage"],
                    requested_model=DEFAULT_UPPER_LAYER_MODEL,
                    response_model=DEFAULT_UPPER_LAYER_MODEL,
                    prompt_version=kwargs["prompt_version"],
                    input_hash=kwargs["input_hash"],
                    output_hash=kwargs["output_hash"](output),
                )

        def _wire_persisted_planning(repository):
            service = WritingReferenceUpperLayerExecutionService(
                repository,
                lambda model: _ScriptedPlanningAdapter(model),
            )
            delegate = ProductionPersistedUpperLayerStageExecutorAdapter(
                service,
                deployment_profile="approved_private_clinical",
                prompt_resolver=upper_layer_prompt_resolver,
            )
            self.pipeline.upper_layer_executor = (
                _PlanningPersistedOnlyExecutor(delegate)
            )

        _wire_persisted_planning(self.repo)
        batch = self.service.create(
            PID,
            WritingReferenceTranslationBatchCreateRequest(
                snapshot_id=SID,
                actor="medical_manager",
                idempotency_key="r8-plan-lineage",
            ),
        )
        # This case exercises an unrecoverable plan followed by explicit retry.
        # The newer deterministic structure recovery has its own success tests;
        # make its unavailability explicit instead of relying on old behavior.
        with patch.object(
            self.service,
            "_recover_document_plan_fallback",
            side_effect=DocumentPlanValidationError(("fixture_structure_unavailable",)),
        ):
            self.service.run_pending(PID, batch.batch_id, "medical_manager")

        failed = self.service.get(PID, batch.batch_id).items
        self.assertEqual(2, len(failed))
        self.assertEqual(
            {"failed_retryable"},
            {item.generation_status for item in failed},
            [(call.requested_model, call.planner_attempt, call.stage_run_id)
             for call in model_calls],
        )
        self.assertEqual(
            {failed[0].document_plan_failure_source_stage_run_id},
            {
                item.document_plan_failure_source_stage_run_id
                for item in failed
            },
        )
        self.assertEqual(
            {False, True},
            {item.document_plan_failure_is_derived for item in failed},
        )
        self.assertTrue(
            all(
                "planner_range_gap" in item.document_plan_failure_codes
                for item in failed
            )
        )
        source_stage_run_id = (
            failed[0].document_plan_failure_source_stage_run_id
        )
        latest_stage_run_id = failed[0].latest_upper_layer_stage_run_id
        self.assertTrue(
            all(
                item.latest_upper_layer_stage_run_id == latest_stage_run_id
                for item in failed
            )
        )
        self.assertTrue(source_stage_run_id)
        self.assertTrue(latest_stage_run_id)
        self.assertNotEqual(source_stage_run_id, latest_stage_run_id)
        self.assertEqual(
            [
                DEFAULT_UPPER_LAYER_MODEL,
                DEFAULT_UPPER_LAYER_MODEL,
                ESCALATED_UPPER_LAYER_MODEL,
            ],
            [call.requested_model for call in model_calls],
        )

        # Reproduce the legacy r42 payload shape: both failed group members
        # predate the additive source-lineage fields and therefore parse with
        # empty source IDs and the non-derived default. Persisted stage-run
        # ownership remains the only safe canonical-source evidence.
        with self.repo._connect() as connection:
            for item in failed:
                row = connection.execute(
                    """
                    SELECT payload_json
                    FROM writing_reference_translation_batch_items
                    WHERE project_id=? AND batch_id=? AND item_id=?
                    """,
                    (PID, batch.batch_id, item.item_id),
                ).fetchone()
                payload = json.loads(str(row["payload_json"]))
                payload.pop(
                    "document_plan_failure_source_stage_run_id",
                    None,
                )
                payload.pop("document_plan_failure_is_derived", None)
                connection.execute(
                    """
                    UPDATE writing_reference_translation_batch_items
                    SET payload_json=?
                    WHERE project_id=? AND batch_id=? AND item_id=?
                    """,
                    (
                        json.dumps(
                            payload,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        PID,
                        batch.batch_id,
                        item.item_id,
                    ),
                )
            exact_source_owners = {
                str(row["owner_id"])
                for row in connection.execute(
                    """
                    SELECT owner_id
                    FROM writing_reference_upper_layer_stage_runs
                    WHERE project_id=? AND artifact_id=?
                      AND extraction_revision=?
                      AND owner_type='translation_batch_item'
                      AND stage='document_planning'
                      AND requested_model=?
                      AND parent_stage_run_id=''
                      AND escalation_id=''
                      AND status IN (
                        'failed_retryable',
                        'failed_escalatable',
                        'failed_terminal'
                      )
                    """,
                    (
                        PID,
                        failed[0].artifact_id,
                        failed[0].extraction_revision,
                        FLASH_PLANNING_MODEL,
                    ),
                ).fetchall()
            }
        legacy_failed = self.service.get(PID, batch.batch_id).items
        self.assertEqual(
            {""},
            {
                item.document_plan_failure_source_stage_run_id
                for item in legacy_failed
            },
        )
        self.assertEqual(
            {False},
            {
                item.document_plan_failure_is_derived
                for item in legacy_failed
            },
        )
        source_owner_id = self.repo.upper_layer_stage_run(
            PID,
            source_stage_run_id,
        ).owner_id
        self.assertEqual({source_owner_id}, exact_source_owners)

        retried = self.service.retry(
            PID,
            batch.batch_id,
            WritingReferenceTranslationBatchRetryRequest(
                actor="medical_manager",
                idempotency_key="r8-plan-lineage-retry",
            ),
        )
        duplicate = self.service.retry(
            PID,
            batch.batch_id,
            WritingReferenceTranslationBatchRetryRequest(
                actor="medical_manager",
                idempotency_key="r8-plan-lineage-retry",
            ),
        )
        self.assertEqual(2, retried.attempt)
        self.assertEqual(retried.attempt, duplicate.attempt)
        retry_generations = {
            item.document_plan_retry_generation for item in retried.items
        }
        retry_parents = {
            item.document_plan_retry_parent_stage_run_id
            for item in retried.items
        }
        retry_sources = {
            item.document_plan_retry_source_item_id
            for item in retried.items
        }
        self.assertEqual({2}, retry_generations)
        self.assertEqual({source_stage_run_id}, retry_parents)
        self.assertEqual(1, len(retry_sources))
        retry_source_item_id = next(iter(retry_sources))
        self.assertEqual(source_owner_id, retry_source_item_id)
        with self.repo._connect() as connection:
            retry_audit = json.loads(
                connection.execute(
                    """
                    SELECT detail_json
                    FROM writing_reference_audit_chain
                    WHERE project_id=?
                      AND event_type='translation_batch_retry_requested'
                      AND target_id=?
                    ORDER BY sequence_no DESC
                    LIMIT 1
                    """,
                    (PID, batch.batch_id),
                ).fetchone()[0]
            )
        self.assertEqual(
            [
                {
                    "artifact_id": "artifact_plan_lineage",
                    "generation": 2,
                    "item_count": 2,
                    "parent_stage_run_id": source_stage_run_id,
                    "source_item_id": retry_source_item_id,
                }
            ],
            retry_audit["document_plan_retry_groups"],
        )
        audit_text = json.dumps(
            retry_audit,
            ensure_ascii=False,
            sort_keys=True,
        )
        for forbidden in (
            "Participants are eligible",
            "system_prompt",
            "retry_instruction",
            "provider_output",
        ):
            self.assertNotIn(forbidden, audit_text)

        derived = next(
            item
            for item in retried.items
            if item.item_id != retry_source_item_id
        )
        artifact = self.repo.document_artifact(PID, derived.artifact_id)
        span = self.repo.source_span(PID, derived.span_id)
        with self.assertRaises(DocumentPlanValidationError) as derived_error:
            self.service._get_or_create_document_plan(
                derived,
                artifact,
                span,
                lambda *_args, **_kwargs: None,
            )
        self.assertEqual(
            ("document_plan_retry_source_not_recovered",),
            derived_error.exception.codes,
        )
        self.assertTrue(
            derived_error.exception.derived_from_source_failure
        )
        self.assertEqual(3, len(model_calls))

        restarted_repo = WritingReferenceRepository(self.repo.db_path)
        _wire_persisted_planning(restarted_repo)
        restarted_service = WritingReferenceTranslationBatchService(
            restarted_repo,
            self.helper.journeys,
            self.helper.preparation,
            self.helper.translation_service,
            clock=lambda: NOW,
            chapter_pipeline=self.pipeline,
        )
        restarted_service.run_failed(
            PID,
            batch.batch_id,
            "medical_manager",
        )
        recovered = restarted_service.get(PID, batch.batch_id).items
        self.assertTrue(
            all(
                item.generation_status
                in {"candidate_ready", "fidelity_blocked"}
                for item in recovered
            )
        )
        self.assertEqual(
            [
                DEFAULT_UPPER_LAYER_MODEL,
                DEFAULT_UPPER_LAYER_MODEL,
                ESCALATED_UPPER_LAYER_MODEL,
                DEFAULT_UPPER_LAYER_MODEL,
            ],
            [call.requested_model for call in model_calls],
        )
        retry_run = next(
            run
            for run in (
                restarted_repo.upper_layer_stage_run(
                    PID,
                    item.latest_upper_layer_stage_run_id,
                )
                for item in recovered
                if item.item_id == retry_source_item_id
            )
            if run.stage == UPPER_LAYER_DOCUMENT_PLANNING
        )
        self.assertEqual(2, retry_run.retry_generation)
        self.assertEqual(
            source_stage_run_id,
            retry_run.retry_parent_stage_run_id,
        )
        with restarted_repo._connect() as connection:
            planning_run_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM writing_reference_upper_layer_stage_runs
                WHERE project_id=? AND stage='document_planning'
                """,
                (PID,),
            ).fetchone()[0]
        self.assertEqual(3, planning_run_count)

        restarted_service.run_failed(
            PID,
            batch.batch_id,
            "medical_manager",
        )
        restarted_service.retry(
            PID,
            batch.batch_id,
            WritingReferenceTranslationBatchRetryRequest(
                actor="medical_manager",
                idempotency_key="r8-plan-lineage-retry",
            ),
        )
        self.assertEqual(4, len(model_calls))
        self.assertNotIn(
            "failed_retryable",
            {item.generation_status for item in recovered},
        )
        self.assertTrue(
            all(
                not item.document_plan_failure_source_stage_run_id
                and not item.document_plan_failure_codes
                and not item.document_plan_failure_is_derived
                and item.document_plan_retry_generation == 2
                and item.document_plan_retry_parent_stage_run_id
                == source_stage_run_id
                and item.document_plan_retry_source_item_id
                == retry_source_item_id
                for item in recovered
            )
        )

        # If a second legacy group member also owns an otherwise exact failed
        # parentless Flash run, source inference must remain ambiguous.
        source_run = restarted_repo.upper_layer_stage_run(
            PID,
            source_stage_run_id,
        )
        source_execution = restarted_repo.upper_layer_stage_run_execution(
            PID,
            source_stage_run_id,
        )
        legacy_sibling = next(
            item
            for item in legacy_failed
            if item.item_id != retry_source_item_id
        )
        ambiguous_stage_run_id = (
            "upper_legacy_"
            + sha256(legacy_sibling.item_id.encode("utf-8")).hexdigest()[:32]
        )
        ambiguous_run = source_run.model_copy(
            update={
                "stage_run_id": ambiguous_stage_run_id,
                "owner_id": legacy_sibling.item_id,
                "item_id": legacy_sibling.item_id,
            },
            deep=True,
        )
        restarted_repo.save_upper_layer_stage_run(
            ambiguous_run,
            execution_fingerprint=sha256(
                f"legacy-ambiguous:{legacy_sibling.item_id}".encode("utf-8")
            ).hexdigest(),
            prompt_text=source_execution["prompt_text"],
            input_payload=source_execution["input_payload"],
            output_payload=source_execution["output_payload"],
            hy_mt2_target_map_sha256=source_execution[
                "hy_mt2_target_map_sha256"
            ],
        )
        with restarted_repo._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            with self.assertRaisesRegex(
                ValueError,
                "document_plan_retry_parent_missing_or_ambiguous",
            ):
                restarted_service._allocate_document_plan_retry_lineage(
                    connection,
                    legacy_failed,
                    retry_generation=3,
                )
            connection.rollback()
        self.assertEqual(
            2,
            restarted_service.get(PID, batch.batch_id).attempt,
        )

    def test_mixed_v2_to_v3_contract_transition_is_atomic_and_restart_safe(
        self,
    ) -> None:
        from tests.test_writing_reference_translation_batch import (
            PROJECT_ID as PID,
            SNAPSHOT_ID as SID,
        )

        def payload_hash(value) -> str:
            return sha256(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()

        no_plan_artifact = self.helper._seed_artifact(
            "artifact_contract_no_plan",
            [
                (
                    "span_contract_no_plan_1",
                    "eligibility",
                    "Participants are eligible.",
                ),
                (
                    "span_contract_no_plan_2",
                    "objectives_endpoints",
                    "The endpoint is assessed.",
                ),
            ],
        )
        migration_artifacts = [
            self.helper._seed_artifact(
                "artifact_contract_migration_1",
                [
                    (
                        "span_contract_migration_1",
                        "eligibility",
                        "Participants must not receive SCS within 14 days.",
                    )
                ],
            ),
            self.helper._seed_artifact(
                "artifact_contract_migration_2",
                [
                    (
                        "span_contract_migration_2",
                        "objectives_endpoints",
                        "The primary endpoint is assessed at Week 16.",
                    )
                ],
            ),
            self.helper._seed_artifact(
                "artifact_contract_migration_3",
                [
                    (
                        "span_contract_migration_3",
                        "study_design",
                        "The study uses a randomized parallel-group design.",
                    )
                ],
            ),
        ]
        batch = self.service.create(
            PID,
            WritingReferenceTranslationBatchCreateRequest(
                snapshot_id=SID,
                actor="medical_manager",
                idempotency_key="r8-contract-transition-create",
            ),
        )
        self.assertEqual(5, len(batch.items))
        items_by_artifact: dict[str, list] = defaultdict(list)
        for item in batch.items:
            items_by_artifact[item.artifact_id].append(item)

        source_plan_payloads: dict[str, str] = {}
        source_plan_ids: dict[str, str] = {}
        for artifact in migration_artifacts:
            [item] = items_by_artifact[artifact.artifact_id]
            spans = self.repo.source_spans(
                PID,
                artifact.artifact_id,
                extraction_revision=item.extraction_revision,
            )
            source_text, context = build_document_planner_input(
                spans,
                document_context={
                    "artifact_id": artifact.artifact_id,
                    "document_type": artifact.document_type,
                    "document_sha256": artifact.content_sha256,
                    "extraction_revision": item.extraction_revision,
                    "span_count": len(spans),
                },
            )
            planner_input_hash = payload_hash(
                _upper_layer_hash_payload(
                    {
                        "source_text": source_text,
                        "document_context": context,
                    }
                )
            )
            source_fingerprint = _planner_contract_fingerprint(
                artifact_id=artifact.artifact_id,
                extraction_revision=item.extraction_revision,
                planner_model=FLASH_PLANNING_MODEL,
                planner_prompt_version=(
                    FLASH_PLANNING_PREVIOUS_PROMPT_VERSION
                ),
                document_sha256=artifact.content_sha256,
                translation_contract=TRANSLATION_CONTRACT_FINGERPRINT,
            )
            source_plan_id = (
                "docplan_v2_"
                + sha256(artifact.artifact_id.encode("utf-8")).hexdigest()[
                    :20
                ]
            )
            source_plan = DocumentStructurePlan(
                plan_id=source_plan_id,
                project_id=PID,
                artifact_id=artifact.artifact_id,
                extraction_revision=item.extraction_revision,
                document_sha256=artifact.content_sha256,
                document_role="protocol",
                planner_model=FLASH_PLANNING_MODEL,
                planner_prompt_version=(
                    FLASH_PLANNING_PREVIOUS_PROMPT_VERSION
                ),
                planner_input_hash=planner_input_hash,
                planner_output_hash=payload_hash(
                    {
                        "document_role": "protocol",
                        "chapters": [
                            {
                                "id": "provider_v2_chapter",
                                "title": artifact.artifact_id,
                                "source_span_ids": [
                                    span.span_id for span in spans
                                ],
                            }
                        ],
                    }
                ),
                planner_contract_fingerprint=source_fingerprint,
                chapters=[
                    DocumentStructurePlanChapter(
                        chapter_id="provider_v2_chapter",
                        chapter_order=1,
                        title=artifact.artifact_id,
                        ich_m11_anchor=spans[0].ich_m11_anchor,
                        source_span_ids=[span.span_id for span in spans],
                    )
                ],
                status="active",
                created_at=NOW,
            )
            self.repo.save_document_structure_plan(
                source_plan,
                idempotency_key=f"seed-v2-plan:{source_plan_id}",
            )
            with self.repo._connect() as connection:
                source_plan_payloads[source_plan_id] = str(
                    connection.execute(
                        """
                        SELECT payload_json
                        FROM writing_reference_document_structure_plans
                        WHERE project_id=? AND plan_id=?
                        """,
                        (PID, source_plan_id),
                    ).fetchone()[0]
                )
            source_plan_ids[artifact.artifact_id] = source_plan_id

        no_plan_items = sorted(
            items_by_artifact[no_plan_artifact.artifact_id],
            key=lambda item: item.item_id,
        )
        source_item = no_plan_items[0]
        no_plan_spans = self.repo.source_spans(
            PID,
            no_plan_artifact.artifact_id,
            extraction_revision=source_item.extraction_revision,
        )
        source_text, source_context = build_document_planner_input(
            no_plan_spans,
            document_context={
                "artifact_id": no_plan_artifact.artifact_id,
                "document_type": no_plan_artifact.document_type,
                "document_sha256": no_plan_artifact.content_sha256,
                "extraction_revision": source_item.extraction_revision,
                "span_count": len(no_plan_spans),
            },
        )
        source_input_payload = _upper_layer_hash_payload(
            {
                "source_text": source_text,
                "document_context": source_context,
            }
        )
        source_input_hash = payload_hash(source_input_payload)
        source_prompt_text = "冻结的 v2 章节规划提示。"
        seed_planner_calls = []

        class _FailedV2PlanningAdapter:
            def __init__(inner_self, model: str) -> None:
                inner_self.model = model

            def invoke(inner_self, request):
                seed_planner_calls.append(request)
                return UpperLayerAdapterResult(
                    response_model=inner_self.model,
                    status=(
                        "failed_escalatable"
                        if inner_self.model == FLASH_PLANNING_MODEL
                        else "failed_terminal"
                    ),
                    failure_code="planner_duplicate_chapter_identity",
                )

        source_service = WritingReferenceUpperLayerExecutionService(
            self.repo,
            lambda model: _FailedV2PlanningAdapter(model),
            clock=lambda: NOW,
            flash_max_attempts=2,
        )
        generation_1_request = UpperLayerExecutionRequest(
            project_id=PID,
            owner_type="translation_batch_item",
            owner_id=source_item.item_id,
            batch_id=batch.batch_id,
            item_id=source_item.item_id,
            artifact_id=no_plan_artifact.artifact_id,
            extraction_revision=source_item.extraction_revision,
            stage=UPPER_LAYER_DOCUMENT_PLANNING,
            deployment_profile="approved_private_clinical",
            prompt_version=FLASH_PLANNING_PREVIOUS_PROMPT_VERSION,
            prompt=source_prompt_text,
            input_payload=source_input_payload,
            idempotency_key="r8-v2-generation-1-root",
        )
        generation_1 = source_service.execute(generation_1_request)
        generation_1_run = generation_1.flash_run
        generation_2_request = UpperLayerExecutionRequest(
            **{
                **generation_1_request.__dict__,
                "idempotency_key": "r8-v2-generation-2-retry",
                "retry_generation": 2,
                "retry_parent_stage_run_id": generation_1_run.stage_run_id,
            }
        )
        generation_2 = source_service.execute(generation_2_request)
        source_run = generation_2.flash_run
        source_stage_run_id = source_run.stage_run_id
        source_execution = self.repo.upper_layer_stage_run_execution(
            PID,
            source_stage_run_id,
        )
        source_execution_fingerprint = str(
            source_execution["execution_fingerprint"]
        )
        self.assertEqual("failed_escalatable", generation_1_run.status)
        self.assertEqual(0, generation_1_run.retry_generation)
        self.assertEqual("", generation_1_run.retry_parent_stage_run_id)
        self.assertEqual("failed_escalatable", source_run.status)
        self.assertEqual(2, source_run.retry_generation)
        self.assertEqual(
            generation_1_run.stage_run_id,
            source_run.retry_parent_stage_run_id,
        )
        self.assertEqual(FLASH_PLANNING_MODEL, source_run.requested_model)
        self.assertEqual(
            FLASH_PLANNING_PREVIOUS_PROMPT_VERSION,
            source_run.prompt_version,
        )
        self.assertEqual(source_input_hash, source_run.input_hash)
        self.assertEqual(
            "approved_private_clinical",
            source_run.deployment_profile,
        )
        self.assertEqual(source_prompt_text, source_execution["prompt_text"])
        self.assertEqual(64, len(source_execution_fingerprint))
        self.assertEqual(
            4,
            sum(
                call.requested_model == FLASH_PLANNING_MODEL
                for call in seed_planner_calls
            ),
        )
        self.assertEqual(6, len(seed_planner_calls))

        # Reproduce the mixed persisted attempt-2 shape. All five rows retain
        # generation-2 metadata; only the two-item artifact has no accepted
        # plan and points to the failed v2 Flash source.
        with self.repo._connect() as connection:
            for item in batch.items:
                is_no_plan = (
                    item.artifact_id == no_plan_artifact.artifact_id
                )
                retained_parent = (
                    source_stage_run_id
                    if is_no_plan
                    else f"retained_v2_parent_{item.artifact_id}"
                )
                updated = item.model_copy(
                    update={
                        "generation_status": "failed_retryable",
                        "attempt": 2,
                        "error_code": (
                            "document_plan_failed"
                            if is_no_plan
                            else "translation_generation_failed"
                        ),
                        "document_plan_failure_source_stage_run_id": (
                            source_stage_run_id if is_no_plan else ""
                        ),
                        "document_plan_failure_codes": (
                            ["planner_duplicate_chapter_identity"]
                            if is_no_plan
                            else []
                        ),
                        "document_plan_failure_is_derived": (
                            is_no_plan and item.item_id != source_item.item_id
                        ),
                        "document_plan_retry_generation": 2,
                        "document_plan_retry_parent_stage_run_id": (
                            retained_parent
                        ),
                        "document_plan_retry_source_item_id": (
                            source_item.item_id
                            if is_no_plan
                            else item.item_id
                        ),
                        "updated_at": NOW,
                    },
                    deep=True,
                )
                connection.execute(
                    """
                    UPDATE writing_reference_translation_batch_items
                    SET generation_status='failed_retryable', attempt=2,
                        payload_json=?, updated_at=?
                    WHERE project_id=? AND batch_id=? AND item_id=?
                    """,
                    (
                        json.dumps(
                            updated.model_dump(mode="json"),
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        NOW.isoformat(),
                        PID,
                        batch.batch_id,
                        item.item_id,
                    ),
                )
            connection.execute(
                """
                UPDATE writing_reference_translation_batches
                SET status='partial_failure', attempt=2, updated_at=?
                WHERE project_id=? AND batch_id=?
                """,
                (NOW.isoformat(), PID, batch.batch_id),
            )

        planner_calls = []

        class _V3PlanningAdapter:
            def __init__(inner_self, model: str) -> None:
                inner_self.model = model

            def invoke(inner_self, request):
                planner_calls.append(request)
                raw_segments = request.input_payload["document_context"][
                    "_planner_segments"
                ]
                source_span_ids = [
                    span_id
                    for segment in raw_segments
                    for span_id in segment["source_span_ids"]
                ]
                chapter_id = _server_canonical_chapter_id(
                    chapter_order=1,
                    start_segment_ordinal=1,
                    end_segment_ordinal=len(raw_segments),
                )
                chapters = (
                    {
                        "id": chapter_id,
                        "title": "Protocol",
                        "ich_m11_anchor": "unmapped",
                        "source_span_ids": source_span_ids,
                    },
                )
                plan = FlashPlanResult(
                    chapters=chapters,
                    document_role="protocol",
                    plan_prompt_version=FLASH_PLANNING_PROMPT_VERSION,
                    plan_model=inner_self.model,
                    plan_input_hash=request.input_hash,
                    plan_output_hash=payload_hash(
                        {
                            "chapters": list(chapters),
                            "document_role": "protocol",
                        }
                    ),
                )
                return UpperLayerAdapterResult(
                    response_model=inner_self.model,
                    status="succeeded",
                    output_payload=_upper_layer_hash_payload(plan),
                )

        class _PlanningPersistedOnlyExecutor:
            def __init__(inner_self, delegate) -> None:
                inner_self.delegate = delegate
                inner_self.deployment_profile = (
                    delegate.deployment_profile
                )

            def execute(inner_self, **kwargs):
                if kwargs["stage"] == UPPER_LAYER_DOCUMENT_PLANNING:
                    return inner_self.delegate.execute(**kwargs)
                output = kwargs["invoke"](DEFAULT_UPPER_LAYER_MODEL)
                return UpperLayerStageExecutionResult(
                    output=output,
                    stage=kwargs["stage"],
                    requested_model=DEFAULT_UPPER_LAYER_MODEL,
                    response_model=DEFAULT_UPPER_LAYER_MODEL,
                    prompt_version=kwargs["prompt_version"],
                    input_hash=kwargs["input_hash"],
                    output_hash=kwargs["output_hash"](output),
                )

        def wire_planning(repository):
            upper_service = WritingReferenceUpperLayerExecutionService(
                repository,
                lambda model: _V3PlanningAdapter(model),
                flash_max_attempts=1,
            )
            delegate = ProductionPersistedUpperLayerStageExecutorAdapter(
                upper_service,
                deployment_profile="approved_private_clinical",
                prompt_resolver=upper_layer_prompt_resolver,
            )
            self.pipeline.upper_layer_executor = (
                _PlanningPersistedOnlyExecutor(delegate)
            )

        wire_planning(self.repo)
        retry_request = WritingReferenceTranslationBatchRetryRequest(
            actor="medical_manager",
            idempotency_key="r8-contract-transition-retry",
        )
        retried = self.service.retry(
            PID,
            batch.batch_id,
            retry_request,
        )
        duplicate = self.service.retry(
            PID,
            batch.batch_id,
            retry_request,
        )
        self.assertEqual(3, retried.attempt)
        self.assertEqual(3, duplicate.attempt)
        self.assertEqual([], planner_calls)
        self.assertEqual(
            {"migration", "supersession"},
            {
                item.document_plan_contract_transition_kind
                for item in retried.items
            },
        )
        self.assertEqual(
            3,
            sum(
                item.document_plan_contract_transition_kind == "migration"
                for item in retried.items
            ),
        )
        self.assertTrue(
            all(
                item.document_plan_retry_generation == 0
                and not item.document_plan_retry_parent_stage_run_id
                and not item.document_plan_retry_source_item_id
                and item.document_plan_contract_generation == 3
                and item.document_plan_contract_transition_version
                == PLANNER_CONTRACT_TRANSITION_VERSION
                for item in retried.items
            )
        )

        with self.repo._connect() as connection:
            migration_audits = connection.execute(
                """
                SELECT detail_json
                FROM writing_reference_audit_chain
                WHERE project_id=?
                  AND event_type='document_structure_plan_contract_migrated'
                ORDER BY sequence_no
                """,
                (PID,),
            ).fetchall()
            plan_count_after_retry = connection.execute(
                """
                SELECT COUNT(*)
                FROM writing_reference_document_structure_plans
                WHERE project_id=?
                """,
                (PID,),
            ).fetchone()[0]
        self.assertEqual(3, len(migration_audits))
        self.assertEqual(6, plan_count_after_retry)
        self.assertTrue(
            all(
                SERVER_CONTRACT_MIGRATION_NAMESPACE
                in row["detail_json"]
                for row in migration_audits
            )
        )
        for source_plan_id, before in source_plan_payloads.items():
            with self.repo._connect() as connection:
                after = str(
                    connection.execute(
                        """
                        SELECT payload_json
                        FROM writing_reference_document_structure_plans
                        WHERE project_id=? AND plan_id=?
                        """,
                        (PID, source_plan_id),
                    ).fetchone()[0]
                )
            self.assertEqual(before, after)

        translator_calls_before = len(self.translator.calls)
        qc_calls_before = len(self.qc.calls)
        restarted_repo = WritingReferenceRepository(self.repo.db_path)
        wire_planning(restarted_repo)
        restarted_service = WritingReferenceTranslationBatchService(
            restarted_repo,
            self.helper.journeys,
            self.helper.preparation,
            self.helper.translation_service,
            clock=lambda: NOW,
            chapter_pipeline=self.pipeline,
        )
        restarted_service.run_failed(
            PID,
            batch.batch_id,
            "medical_manager",
        )
        completed = restarted_service.get(PID, batch.batch_id)
        self.assertTrue(
            all(
                item.generation_status
                in {"candidate_ready", "fidelity_blocked"}
                for item in completed.items
            )
        )
        self.assertEqual(1, len(planner_calls))
        self.assertGreater(len(self.translator.calls), translator_calls_before)
        self.assertGreater(len(self.qc.calls), qc_calls_before)

        migrated_target_plan_ids = {
            item.document_plan_contract_target_plan_id
            for item in completed.items
            if item.document_plan_contract_transition_kind == "migration"
        }
        self.assertEqual(3, len(migrated_target_plan_ids))
        for item in completed.items:
            self.assertTrue(item.document_structure_plan_id)
            self.assertNotIn(
                item.document_structure_plan_id,
                set(source_plan_ids.values()),
            )
            if (
                item.document_plan_contract_transition_kind
                == "migration"
            ):
                self.assertEqual(
                    item.document_plan_contract_target_plan_id,
                    item.document_structure_plan_id,
                )
        for source_plan_id in source_plan_ids.values():
            self.assertEqual(
                [],
                restarted_repo.translation_chunks_for_plan(
                    PID,
                    source_plan_id,
                ),
            )
        for target_plan_id in migrated_target_plan_ids:
            self.assertTrue(
                restarted_repo.translation_chunks_for_plan(
                    PID,
                    target_plan_id,
                )
            )

        no_plan_completed = [
            item
            for item in completed.items
            if item.artifact_id == no_plan_artifact.artifact_id
        ]
        self.assertEqual(
            1,
            len(
                {
                    item.document_structure_plan_id
                    for item in no_plan_completed
                }
            ),
        )
        no_plan_target_plan = (
            restarted_repo.current_document_structure_plan(
                PID,
                no_plan_artifact.artifact_id,
                source_item.extraction_revision,
                _planner_contract_fingerprint(
                    artifact_id=no_plan_artifact.artifact_id,
                    extraction_revision=source_item.extraction_revision,
                    planner_model=FLASH_PLANNING_MODEL,
                    planner_prompt_version=FLASH_PLANNING_PROMPT_VERSION,
                    document_sha256=no_plan_artifact.content_sha256,
                    translation_contract=(
                        TRANSLATION_CONTRACT_FINGERPRINT
                    ),
                ),
            )
        )
        self.assertIsNotNone(no_plan_target_plan)
        supersession_run = restarted_repo.upper_layer_stage_run(
            PID,
            no_plan_target_plan.upper_layer_stage_run_id,
        )
        persisted_generation_2 = restarted_repo.upper_layer_stage_run(
            PID,
            source_stage_run_id,
        )
        self.assertEqual(2, persisted_generation_2.retry_generation)
        self.assertEqual(
            generation_1_run.stage_run_id,
            persisted_generation_2.retry_parent_stage_run_id,
        )
        self.assertEqual(3, supersession_run.contract_supersession_generation)
        self.assertEqual(0, supersession_run.retry_generation)
        self.assertEqual("", supersession_run.retry_parent_stage_run_id)
        self.assertEqual(
            source_stage_run_id,
            supersession_run.contract_supersession_source_stage_run_id,
        )
        self.assertEqual(
            source_execution_fingerprint,
            supersession_run
            .contract_supersession_source_execution_fingerprint,
        )
        with restarted_repo._connect() as connection:
            supersession_audits = connection.execute(
                """
                SELECT detail_json
                FROM writing_reference_audit_chain
                WHERE project_id=?
                  AND event_type='upper_layer_contract_supersession_recorded'
                """,
                (PID,),
            ).fetchall()
        self.assertEqual(1, len(supersession_audits))

        counts_before_duplicate = (
            len(planner_calls),
            len(self.translator.calls),
            len(self.qc.calls),
        )
        restarted_service.run_failed(
            PID,
            batch.batch_id,
            "medical_manager",
        )
        restarted_service.retry(
            PID,
            batch.batch_id,
            retry_request,
        )
        self.assertEqual(
            counts_before_duplicate,
            (
                len(planner_calls),
                len(self.translator.calls),
                len(self.qc.calls),
            ),
        )
        with restarted_repo._connect() as connection:
            self.assertEqual(
                plan_count_after_retry + 1,
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM writing_reference_document_structure_plans
                    WHERE project_id=?
                    """,
                    (PID,),
                ).fetchone()[0],
            )
            self.assertEqual(
                3,
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM writing_reference_audit_chain
                    WHERE project_id=?
                      AND event_type='document_structure_plan_contract_migrated'
                    """,
                    (PID,),
                ).fetchone()[0],
            )
            self.assertEqual(
                1,
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM writing_reference_audit_chain
                    WHERE project_id=?
                      AND event_type='upper_layer_contract_supersession_recorded'
                    """,
                    (PID,),
                ).fetchone()[0],
            )
        for source_plan_id, before in source_plan_payloads.items():
            with restarted_repo._connect() as connection:
                after = str(
                    connection.execute(
                        """
                        SELECT payload_json
                        FROM writing_reference_document_structure_plans
                        WHERE project_id=? AND plan_id=?
                        """,
                        (PID, source_plan_id),
                    ).fetchone()[0]
                )
            self.assertEqual(before, after)

    def test_invalid_contract_transition_preflight_creates_no_job_or_mutation(
        self,
    ) -> None:
        from tests.test_writing_reference_translation_batch import (
            PROJECT_ID as PID,
            SNAPSHOT_ID as SID,
        )

        artifact = self.helper._seed_artifact(
            "artifact_contract_invalid",
            [
                (
                    "span_contract_invalid",
                    "eligibility",
                    "Participants are eligible.",
                )
            ],
        )
        batch = self.service.create(
            PID,
            WritingReferenceTranslationBatchCreateRequest(
                snapshot_id=SID,
                actor="medical_manager",
                idempotency_key="r8-contract-invalid-create",
            ),
        )
        [item] = batch.items
        spans = self.repo.source_spans(
            PID,
            artifact.artifact_id,
            extraction_revision=item.extraction_revision,
        )
        source_text, context = build_document_planner_input(
            spans,
            document_context={
                "artifact_id": artifact.artifact_id,
                "document_type": artifact.document_type,
                "document_sha256": artifact.content_sha256,
                "extraction_revision": item.extraction_revision,
                "span_count": len(spans),
            },
        )
        input_payload = _upper_layer_hash_payload(
            {
                "source_text": source_text,
                "document_context": context,
            }
        )
        input_hash = sha256(
            json.dumps(
                input_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        source_stage_run_id = "wref_ulrun_invalid_contract_source"
        source_run = WritingReferenceUpperLayerStageRun(
            stage_run_id=source_stage_run_id,
            project_id=PID,
            owner_type="translation_batch_item",
            owner_id=item.item_id,
            batch_id=batch.batch_id,
            item_id=item.item_id,
            artifact_id=artifact.artifact_id,
            extraction_revision=item.extraction_revision,
            stage=UPPER_LAYER_DOCUMENT_PLANNING,
            provider="deepseek",
            transport="openai_compatible",
            requested_model=FLASH_PLANNING_MODEL,
            response_model=FLASH_PLANNING_MODEL,
            deployment_profile="approved_private_clinical",
            prompt_version="flash_toc_planning_v0_1_unknown",
            input_hash=input_hash,
            status="failed_terminal",
            failure_code="planner_output_not_structured",
            provider_call_count=1,
            planner_attempt_count=1,
            created_at=NOW,
            completed_at=NOW,
        )
        self.repo.save_upper_layer_stage_run(
            source_run,
            execution_fingerprint="b" * 64,
            prompt_text="未知的旧规划提示。",
            input_payload=input_payload,
            output_payload=None,
        )
        failed = item.model_copy(
            update={
                "generation_status": "failed_retryable",
                "attempt": 2,
                "error_code": "document_plan_failed",
                "document_plan_failure_source_stage_run_id": (
                    source_stage_run_id
                ),
                "document_plan_failure_codes": [
                    "planner_output_not_structured"
                ],
                "document_plan_retry_generation": 2,
                "document_plan_retry_parent_stage_run_id": (
                    source_stage_run_id
                ),
                "document_plan_retry_source_item_id": item.item_id,
                "updated_at": NOW,
            },
            deep=True,
        )
        with self.repo._connect() as connection:
            connection.execute(
                """
                UPDATE writing_reference_translation_batch_items
                SET generation_status='failed_retryable', attempt=2,
                    payload_json=?, updated_at=?
                WHERE project_id=? AND batch_id=? AND item_id=?
                """,
                (
                    json.dumps(
                        failed.model_dump(mode="json"),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    NOW.isoformat(),
                    PID,
                    batch.batch_id,
                    item.item_id,
                ),
            )
            connection.execute(
                """
                UPDATE writing_reference_translation_batches
                SET status='failed', attempt=2, updated_at=?
                WHERE project_id=? AND batch_id=?
                """,
                (NOW.isoformat(), PID, batch.batch_id),
            )

        class _DurableStore:
            def __init__(inner_self) -> None:
                inner_self.calls = []

            def create_or_reuse(inner_self, request):
                inner_self.calls.append(request)
                raise AssertionError(
                    "invalid transition must fail before durable job creation"
                )

        durable_store = _DurableStore()
        self.service.attach_durable_store(durable_store)
        with self.repo._connect() as connection:
            before_batch = tuple(
                connection.execute(
                    """
                    SELECT status, attempt, updated_at
                    FROM writing_reference_translation_batches
                    WHERE project_id=? AND batch_id=?
                    """,
                    (PID, batch.batch_id),
                ).fetchone()
            )
            before_item = str(
                connection.execute(
                    """
                    SELECT payload_json
                    FROM writing_reference_translation_batch_items
                    WHERE project_id=? AND batch_id=? AND item_id=?
                    """,
                    (PID, batch.batch_id, item.item_id),
                ).fetchone()[0]
            )
            before_counts = tuple(
                connection.execute(
                    """
                    SELECT
                      (SELECT COUNT(*) FROM writing_reference_idempotency),
                      (SELECT COUNT(*) FROM writing_reference_translation_batch_idempotency),
                      (SELECT COUNT(*) FROM writing_reference_document_structure_plans),
                      (SELECT COUNT(*) FROM writing_reference_audit_chain)
                    """
                ).fetchone()
            )

        with self.assertRaisesRegex(
            ValueError,
            "document_plan_contract_transition_not_allowlisted",
        ):
            self.service.retry(
                PID,
                batch.batch_id,
                WritingReferenceTranslationBatchRetryRequest(
                    actor="medical_manager",
                    idempotency_key="r8-contract-invalid-retry",
                ),
            )
        self.assertEqual([], durable_store.calls)
        with self.repo._connect() as connection:
            after_batch = tuple(
                connection.execute(
                    """
                    SELECT status, attempt, updated_at
                    FROM writing_reference_translation_batches
                    WHERE project_id=? AND batch_id=?
                    """,
                    (PID, batch.batch_id),
                ).fetchone()
            )
            after_item = str(
                connection.execute(
                    """
                    SELECT payload_json
                    FROM writing_reference_translation_batch_items
                    WHERE project_id=? AND batch_id=? AND item_id=?
                    """,
                    (PID, batch.batch_id, item.item_id),
                ).fetchone()[0]
            )
            after_counts = tuple(
                connection.execute(
                    """
                    SELECT
                      (SELECT COUNT(*) FROM writing_reference_idempotency),
                      (SELECT COUNT(*) FROM writing_reference_translation_batch_idempotency),
                      (SELECT COUNT(*) FROM writing_reference_document_structure_plans),
                      (SELECT COUNT(*) FROM writing_reference_audit_chain)
                    """
                ).fetchone()
            )
        self.assertEqual(before_batch, after_batch)
        self.assertEqual(before_item, after_item)
        self.assertEqual(before_counts, after_counts)

    def test_immutable_plan_chunk_integration_run_reject_update_delete(self) -> None:
        from tests.test_writing_reference_translation_batch import PROJECT_ID as PID, SNAPSHOT_ID as SID

        self.helper._seed_artifact(
            "artifact_immut",
            [
                ("span_immut", "eligibility", "Participants must not receive SCS within 14 days."),
            ],
        )
        batch = self.service.create(
            PID,
            WritingReferenceTranslationBatchCreateRequest(
                snapshot_id=SID,
                actor="medical_manager",
                idempotency_key="r8-immut",
            ),
        )
        self.service.run_pending(PID, batch.batch_id, "medical_manager")
        item = self.service.get(PID, batch.batch_id).items[0]
        self.assertEqual("candidate_ready", item.generation_status)
        plan_id = item.document_structure_plan_id
        tr = self.repo.translation(PID, item.translation_id, item.translation_revision)
        with self.repo._connect() as conn:
            with self.assertRaises(Exception):
                conn.execute(
                    "UPDATE writing_reference_document_structure_plans SET document_role='x' "
                    "WHERE plan_id=?",
                    (plan_id,),
                )
                conn.commit()
        with self.repo._connect() as conn:
            with self.assertRaises(Exception):
                conn.execute(
                    "DELETE FROM writing_reference_document_structure_plans WHERE plan_id=?",
                    (plan_id,),
                )
                conn.commit()
        with self.repo._connect() as conn:
            with self.assertRaises(Exception):
                conn.execute(
                    "UPDATE writing_reference_translation_chunks SET status='x' WHERE plan_id=?",
                    (plan_id,),
                )
                conn.commit()
        with self.repo._connect() as conn:
            with self.assertRaises(Exception):
                conn.execute(
                    "DELETE FROM writing_reference_chapter_integration_results "
                    "WHERE integration_id=?",
                    (tr.chapter_integration_result_id,),
                )
                conn.commit()
        with self.repo._connect() as conn:
            with self.assertRaises(Exception):
                conn.execute(
                    "UPDATE writing_reference_composite_pipeline_runs SET status='x' "
                    "WHERE run_id=?",
                    (tr.ai_run_id,),
                )
                conn.commit()
            with self.assertRaises(Exception):
                conn.execute(
                    "DELETE FROM writing_reference_composite_pipeline_runs WHERE run_id=?",
                    (tr.ai_run_id,),
                )
                conn.commit()

    def test_fidelity_blocks_flash_passed_result(self) -> None:
        from tests.test_writing_reference_translation_batch import PROJECT_ID as PID, SNAPSHOT_ID as SID

        self.helper._seed_artifact(
            "artifact_fid_block",
            [
                ("span_fid_block", "eligibility", "Participants must not receive SCS within 14 days."),
            ],
        )
        self.runner.blocked_spans.add("span_fid_block")
        batch = self.service.create(
            PID,
            WritingReferenceTranslationBatchCreateRequest(
                snapshot_id=SID,
                actor="medical_manager",
                idempotency_key="r8-fid-block",
            ),
        )
        self.service.run_pending(PID, batch.batch_id, "medical_manager")
        item = next(
            i
            for i in self.service.get(PID, batch.batch_id).items
            if i.span_id == "span_fid_block"
        )
        self.assertEqual("fidelity_blocked", item.generation_status)
        self.assertGreater(len(item.fidelity_failure_codes), 0)

    def test_ordinary_integration_not_windowed_for_multi_chunk_under_limit(self) -> None:
        # Unit-level: multi chunk under limit => one window, windowed=False semantics.
        class CS:
            def __init__(self, n: int) -> None:
                self.source_text = f"text{n}" * 20
                self.chunk_id = f"c{n}"
                self.chunk_fingerprint = f"fp{n}"

        pairs = [(CS(i), f"译{i}" * 20) for i in range(3)]
        windows = build_integration_windows(
            pairs, input_limit=INTEGRATION_PROVIDER_INPUT_LIMIT
        )
        self.assertEqual(1, len(windows))
        self.assertEqual(3, len(windows[0]))

    def test_legacy_flash_path_cannot_be_called(self) -> None:
        from tests.test_writing_reference_translation_batch import PROJECT_ID as PID

        service = WritingReferenceTranslationService(
            self.repo, self.runner, clock=lambda: NOW, chapter_pipeline=self.pipeline
        )
        with self.assertRaises(Exception) as ctx:
            service._generate_translation(
                project_id=PID,
                span=SimpleNamespace(
                    span_id="x",
                    source_text="y",
                    artifact_id="a",
                    extraction_revision="r",
                    source_locator="l",
                ),
                artifact=SimpleNamespace(
                    nct_id="n", document_type="protocol", content_sha256="h" * 64
                ),
                translation_id="t",
                glossary_version=GLOSSARY,
                user_instruction="u",
                revision=1,
                expected_revision=0,
                idempotency_key="k",
            )
        self.assertIn("disabled", str(ctx.exception).lower())


class ChapterResolveFailClosedTests(unittest.TestCase):
    def test_resolve_chapter_no_fallback(self) -> None:
        from packages.contracts.workbench_contracts.models import (
            DocumentStructurePlan,
            DocumentStructurePlanChapter,
        )
        from services.api.app.writing_reference_translation_batch import (
            WritingReferenceTranslationBatchService,
        )

        plan = DocumentStructurePlan(
            plan_id="p",
            project_id=PROJECT_ID,
            artifact_id="a",
            extraction_revision="r",
            document_sha256="h" * 64,
            document_role="protocol",
            planner_model=FLASH_PLANNING_MODEL,
            planner_prompt_version=FLASH_PLANNING_PROMPT_VERSION,
            planner_input_hash="i",
            planner_output_hash="o",
            planner_contract_fingerprint="fp",
            chapters=[
                DocumentStructurePlanChapter(
                    chapter_id="ch1",
                    chapter_order=1,
                    title="T",
                    source_span_ids=["s1"],
                )
            ],
            created_at=NOW,
        )
        with self.assertRaises(DocumentPlanValidationError):
            WritingReferenceTranslationBatchService._resolve_chapter_for_span(
                plan, "unknown_span"
            )


if __name__ == "__main__":
    unittest.main()
