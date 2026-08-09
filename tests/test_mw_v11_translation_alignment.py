"""V11 medical-writing translation alignment deterministic behavior tests.

Covers the 12 required V11 behavior points from the task contract:

 1.  Dense 114-bullet/estimand-style fixture chunks around the 3000-char
     target and preserves all bullets and ordered source units.
 2.  Long eligibility lines split before a new numbered criterion and around
     sentence/list boundaries without breaking ``2.0``, ``e.g.``, ``>=`` or
     ``EASI-50``.
 3.  Missing/duplicate/reordered/empty/unknown markers fail closed.
 4.  Broad title-case words are not classified as abbreviations;
     eCRF/eGFR/mITT/vIGA-AD and uppercase clinical abbreviations are.
 5.  Hy response ``finish_reason=length``, empty output or missing markers
     fails closed.
 6.  First compressed Hy output triggers one correction, corrected output
     continues; a second bad output blocks and the call count is exactly two.
 7.  Flash preserves markers, strips them from the final Chinese and
     performs at most one corrective pass.
 8.  Unit-level unsupported 疗效 addition is caught even when a different
     unit legitimately contains efficacy.
 9.  ``(62)`` omission, ``at least 28 days`` weakening, ``4 weeks -> 4天``,
     TCI -> tacrolimus narrowing and comparator reversal remain blocked.
10.  En-dash age range, ``满12个月``, ``2.0 x ULN`` word order and the
     accepted IUS equivalent pass, while nearby true defects still fail.
11.  The prompt/contract bump invalidates v10-style chunk/integration reuse
     without mutating immutable records.
12.  Direct translation and batch translation use the same aligned contract.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from packages.contracts.workbench_contracts.models import (
    ChapterIntegrationResult,
    TranslationChunkRecord,
)

import services.api.app.chapter_translation_pipeline as pipeline_module
import services.api.app.writing_reference_translation_batch as batch_module
from services.api.app.chapter_translation_pipeline import (
    CHUNK_TARGET_CHARS,
    FLASH_QC_PROMPT_VERSION,
    HY_MT2_MODEL_ID,
    HY_MT2_PROMPT_VERSION,
    POST_HY_NORMALIZATION_VERSION,
    TRANSLATION_CONTRACT_FINGERPRINT,
    TRANSLATION_ALIGNMENT_CONTRACT,
    ChapterTranslationPipeline,
    DocumentPlanResult,
    FidelityBlockedError,
    FakeFlashQcRunner,
    FakeFlashPlanner,
    FakeHyMt2Translator,
    FakeOcrRunner,
    FlashQcResult,
    HyMt2TranslationResult,
    TranslationUnit,
    _normalize_en_dash_ranges,
    _sha256,
    build_correction_note,
    build_chunks_from_plan,
    call_flash_qc_with_note,
    call_hy_mt2_translator,
    contains_unit_markers,
    evaluate_translation_fidelity_aligned_units,
    format_unit_delimited_source,
    integrate_units_with_flash,
    parse_unit_delimited_output,
    normalize_post_hy_unit_output,
    reconstruct_unit_map,
    reject_misaligned_output,
    restore_abbreviation_definition_keys,
    split_source_into_units,
    structural_cardinality_failures,
    translate_units_with_bounded_correction,
    validate_completion_payload,
)
from services.api.app.chapter_translation_pipeline import (
    ChapterTranslationPipelineError,
)
from services.api.app.writing_reference import (
    COMPOSITE_TRANSLATION_PROMPT_VERSION,
    composite_translation_contract_hash,
    detect_clinical_abbreviations,
    evaluate_translation_fidelity,
)
from services.api.app.regulatory_translation_glossary import (
    participant_terminology_mismatch,
)
from services.api.app.writing_reference_repository import (
    WritingReferenceConflictError,
    WritingReferenceRepository,
)


def _controlled_translation_body_role(api_main):
    return patch.object(
        api_main,
        "_runtime_role_context",
        return_value=(
            SimpleNamespace(model=HY_MT2_MODEL_ID),
            SimpleNamespace(provider="omlx"),
            {
                "WORKBENCH_AI_BASE_URL": "http://127.0.0.1:8000/v1",
                "WORKBENCH_AI_API_KEY": "",
            },
        ),
    )


def _unit_source(marked: str, ordinal: int) -> str:
    match = re.search(
        rf"\[\[CMS_SEG_{ordinal:04d}\]\]\s*(.*?)\s*\[\[/CMS_SEG_{ordinal:04d}\]\]",
        marked,
        re.DOTALL,
    )
    return match.group(1) if match else ""


def _hy_result(
    chapter_id: str, chunk_id: str, translated: str
) -> HyMt2TranslationResult:
    return HyMt2TranslationResult(
        chapter_id=chapter_id,
        chunk_id=chunk_id,
        translated_text=translated,
        translated_text_sha256=_sha256(translated),
        model=HY_MT2_MODEL_ID,
        prompt_version=HY_MT2_PROMPT_VERSION,
        input_hash=_sha256(translated),
        output_hash=_sha256(translated),
    )


def _flash_result(
    passed: bool, integrated: str, codes: tuple[str, ...] = ()
) -> FlashQcResult:
    return FlashQcResult(
        passed=passed,
        failure_codes=codes,
        qc_prompt_version=FLASH_QC_PROMPT_VERSION,
        qc_model="deepseek-v4-flash",
        qc_input_hash="in",
        qc_output_hash="out",
        integrated_text=integrated,
        integrated_text_sha256=_sha256(integrated),
        notes="stub",
    )


# ---------------------------------------------------------------------------
# Point 1: dense 114-bullet fixture — chunks ~3000, bullets + units preserved
# ---------------------------------------------------------------------------


class DenseBulletChunkTests(unittest.TestCase):
    def _dense_source(self, count: int = 114) -> str:
        bullets = [
            f"• Achievement of EASI-{10 + index} at Week 16 with change in "
            f"SCORAD score from baseline to Week 16 endpoint {index}."
            for index in range(count)
        ]
        return "Panel 3: Objectives and endpoints\n\n" + "\n".join(bullets)

    def test_chunking_preserves_all_bullets(self) -> None:
        source = self._dense_source()
        span = SimpleNamespace(span_id="s1", source_text=source)
        plan = DocumentPlanResult(
            flash_plan=None,  # type: ignore[arg-type]
            chapters=(("ch1", "Objectives", "endpoints", ("s1",)),),
            document_role="protocol",
            ambiguity_codes=(),
        )
        chapter_chunks = build_chunks_from_plan(plan, (span,))
        chunks = list(chapter_chunks[0].values())[0]
        self.assertGreater(len(chunks), 1)
        total_bullets = sum(chunk.source_text.count("•") for chunk in chunks)
        self.assertEqual(114, total_bullets)
        # Ordinary chunks stay around the reduced 3000-char target.
        for chunk in chunks:
            self.assertLessEqual(len(chunk.source_text), CHUNK_TARGET_CHARS + 200)
        # No chunk starts or ends mid-bullet line: each chunk's bullet lines
        # are intact (every "•" opens a full line ending with a period).
        for chunk in chunks:
            for line in chunk.source_text.split("\n"):
                if line.strip().startswith("•"):
                    self.assertTrue(line.strip().endswith("."))

    def test_units_and_marked_round_trip_preserve_order(self) -> None:
        source = self._dense_source()
        span = SimpleNamespace(span_id="s1", source_text=source)
        plan = DocumentPlanResult(
            flash_plan=None,  # type: ignore[arg-type]
            chapters=(("ch1", "Objectives", "endpoints", ("s1",)),),
            document_role="protocol",
            ambiguity_codes=(),
        )
        chunks = list(build_chunks_from_plan(plan, (span,))[0].values())[0]
        for chunk in chunks:
            units = split_source_into_units(chunk.source_text)
            self.assertEqual(list(range(1, len(units) + 1)), [u.ordinal for u in units])
            # All bullets survive unit splitting.
            self.assertEqual(
                chunk.source_text.count("•"),
                sum(u.text.count("•") for u in units),
            )
            # A marker-preserving translator round-trips every unit exactly
            # once, in order.
            translator = FakeHyMt2Translator()
            delimited = format_unit_delimited_source(units)
            result = translator(delimited, "", "ch1", chunk.chunk_id)
            parsed, errors = parse_unit_delimited_output(
                result.translated_text,
                expected_ordinals=[u.ordinal for u in units],
            )
            self.assertEqual([], errors)
            self.assertEqual(len(units), len(parsed))

    def test_adjacent_context_never_crosses_chapter_boundary(self) -> None:
        spans = (
            SimpleNamespace(span_id="objective_1", source_text="Primary objective."),
            SimpleNamespace(
                span_id="eligibility_1",
                source_text="Participants must be 18 years or older.",
            ),
        )
        plan = DocumentPlanResult(
            flash_plan=None,  # type: ignore[arg-type]
            chapters=(
                (
                    "ch_objectives",
                    "Objectives",
                    "objectives_endpoints",
                    ("objective_1",),
                ),
                ("ch_eligibility", "Eligibility", "eligibility", ("eligibility_1",)),
            ),
            document_role="protocol",
            ambiguity_codes=(),
        )
        chapter_chunks = build_chunks_from_plan(plan, spans)
        objective_chunk = list(chapter_chunks[0].values())[0][0]
        eligibility_chunk = list(chapter_chunks[1].values())[0][0]
        self.assertEqual("", objective_chunk.adjacent_context)
        self.assertEqual("", eligibility_chunk.adjacent_context)


# ---------------------------------------------------------------------------
# Point 2: long eligibility line — safe semantic splitting
# ---------------------------------------------------------------------------


class LongLineSplitTests(unittest.TestCase):
    LINE = (
        "Type of subject and disease characteristics 4. At screening, diagnosis "
        "of AD as defined by the Hanifin and Rajka (1980) criteria for AD "
        "( ( 62 ) and Appendix 3 [Section 12.3 ]) . - History of AD for ≥1 year. "
        "5. Subjects who have a recent history (within 12 months before "
        "screening) with documented inadequate response to treatment with TCS "
        "(±TCI as appropriate) or for whom these topical AD treatments are "
        "medically inadvisable (e.g. due to important side effects or safety "
        "risks). - Inadequate response is defined as failure to maintain "
        "remission despite 2.0 x ULN comparators and EASI-50 endpoints with "
        ">= 4 weeks of follow-up data recorded in the eCRF system for review."
    )

    def test_long_line_splits_at_safe_boundaries(self) -> None:
        units = split_source_into_units(self.LINE, target_chars=200)
        self.assertGreaterEqual(len(units), 3)
        # A new numbered criterion opens its own unit.
        self.assertTrue(any(u.text.startswith("5.") for u in units))
        # Order and coverage are preserved.
        self.assertTrue(units[0].text.startswith("Type of subject"))
        self.assertTrue(units[-1].text.endswith("for review."))
        joined = " ".join(u.text for u in units)
        for token in ("Hanifin", "e.g.", "EASI-50", ">= 4 weeks", "2.0 x ULN"):
            self.assertIn(token, joined)

    def test_decimals_abbreviations_comparators_never_broken(self) -> None:
        units = split_source_into_units(self.LINE, target_chars=200)
        for unit in units:
            text = unit.text
            # Decimal numbers: never split "2.0" into "2." + "0".
            self.assertFalse(text.rstrip().endswith(" 2."))
            self.assertFalse(text.startswith("0 x"))
            # Abbreviation boundary: never split after "e.g.".
            self.assertFalse(text.rstrip().endswith("e.g."))
            self.assertFalse(text.startswith("due to important"))
            # Endpoint scale: never split "EASI-50".
            self.assertFalse(text.rstrip().endswith("EASI-"))
            self.assertFalse(text.startswith("50 "))
            # Comparator: never leave a dangling ">=".
            self.assertFalse(text.rstrip().endswith(">="))

    def test_table_rows_are_not_split(self) -> None:
        row = "| Objective | Endpoint | Population | Summary | " + "x" * 300 + " |"
        source = f"Header line.\n\n{row}"
        units = split_source_into_units(source, target_chars=120)
        row_units = [u for u in units if u.text.startswith("|")]
        self.assertEqual(1, len(row_units))
        self.assertEqual(row, row_units[0].text)

    def test_pdf_physical_fragments_are_merged_into_complete_eligibility_units(
        self,
    ) -> None:
        source = (
            "Informed consent 1. Signed and dated informed consent has been\n\n"
            "obtained prior to any protocol-related procedures.\n\n"
            "Age 2. 18–75 years old at screening (Visit 1). For requirements "
            "specific for JP,\n\n"
            "see Section 12.5.4 .\n\n"
            "Type of subject and disease characteristics 4. At screening, "
            "diagnosis of AD as defined by the Hanifin and Rajka (1980) "
            "criteria for AD\n\n"
            "( ( 62 ) and Appendix 3 [Section 12.3 ]) . - History of AD for "
            "≥1 year. 5. Subjects with documented\n\n"
            "inadequate response to treatment with TCS (±TCI as appropriate)."
        )
        units = split_source_into_units(source)
        self.assertEqual(5, len(units))
        self.assertIn("has been obtained prior", units[0].text)
        self.assertIn("For requirements specific for JP, see Section", units[1].text)
        self.assertIn("criteria for AD ( ( 62 )", units[2].text)
        self.assertNotIn("5. Subjects", units[2].text)
        self.assertTrue(units[3].text.startswith("- History of AD"))
        self.assertTrue(units[4].text.startswith("5. Subjects"))
        self.assertIn("documented inadequate response", units[4].text)

    def test_lowercase_scale_criterion_and_preceding_rule_split_independently(
        self,
    ) -> None:
        source = (
            "- Inadequate response requires 28 days of treatment. "
            "*Important risks are assessed by the investigator. "
            "6. EASI score ≥12 at screening and ≥16 at baseline. "
            "7. vIGA-AD score ≥3 at screening and baseline."
        )
        units = split_source_into_units(source)
        self.assertEqual(4, len(units))
        self.assertTrue(units[0].text.startswith("- Inadequate response"))
        self.assertTrue(units[1].text.startswith("*Important"))
        self.assertTrue(units[2].text.startswith("6. EASI"))
        self.assertTrue(units[3].text.startswith("7. vIGA-AD"))

    def test_inline_pdf_bullets_split_before_threshold_criteria(self) -> None:
        source = (
            "- Inadequate response requires at least 28 days. "
            "- Subjects treated systemically are inadequate responders. "
            "*Important risks include intolerance. "
            "6. EASI score ≥12 at screening and ≥16 at baseline. "
            "7. vIGA-AD score ≥3 at screening and baseline."
        )
        units = split_source_into_units(source)
        self.assertEqual(5, len(units))
        self.assertTrue(units[0].text.startswith("- Inadequate"))
        self.assertTrue(units[1].text.startswith("- Subjects"))
        self.assertTrue(units[2].text.startswith("*Important"))
        self.assertTrue(units[3].text.startswith("6. EASI"))
        self.assertTrue(units[4].text.startswith("7. vIGA-AD"))

    def test_flattened_lettered_questionnaire_items_split_independently(self) -> None:
        source = (
            "3. Does health limit activities? "
            "a. Vigorous activities. ❑ Yes, limited a lot. "
            "❑ Yes, limited a little. ❑ No, not limited at all. "
            "b. Moderate activities. ❑ Yes, limited a lot. "
            "❑ Yes, limited a little. ❑ No, not limited at all. "
            "c. Lifting groceries. ❑ Yes, limited a lot. "
            "❑ Yes, limited a little. ❑ No, not limited at all."
        )
        units = split_source_into_units(source, target_chars=1200)
        self.assertTrue(any(unit.text.startswith("a.") for unit in units))
        self.assertTrue(any(unit.text.startswith("b.") for unit in units))
        self.assertTrue(any(unit.text.startswith("c.") for unit in units))
        self.assertEqual(source.count("❑"), sum(unit.text.count("❑") for unit in units))

    def test_flattened_lettered_materials_split_when_item_starts_with_number(
        self,
    ) -> None:
        source = (
            "A. CryoStor CS10 freezing medium. "
            "B. 2 mL cryogenic vials. "
            "C. 4 mm biopsy punch. "
            "D. Disposable gloves."
        )
        units = split_source_into_units(source, target_chars=1200)
        self.assertEqual(
            ["A.", "B.", "C.", "D."],
            [unit.text.split(maxsplit=1)[0] for unit in units],
        )

    def test_chinese_footnote_marker_does_not_require_trailing_space(self) -> None:
        codes = structural_cardinality_failures(
            "* A woman of childbearing potential is defined as...",
            "*所谓具有生育能力的女性，是指……",
        )
        self.assertNotIn("bullet_cardinality_changed", codes)

    def test_checkbox_loss_is_a_structural_failure(self) -> None:
        codes = structural_cardinality_failures(
            "❑ Yes. ❑ No. ❑ Not applicable.",
            "❑ 是。❑ 否。",
        )
        self.assertIn("bullet_cardinality_changed", codes)

    def test_chunk_boundary_keeps_a_physical_continuation_with_its_sentence(
        self,
    ) -> None:
        prefix = "Complete eligibility context. " * 95
        spans = (
            SimpleNamespace(
                span_id="s1",
                source_text=prefix + "Signed informed consent has been",
            ),
            SimpleNamespace(
                span_id="s2",
                source_text="obtained before any protocol-related procedure.",
            ),
        )
        plan = DocumentPlanResult(
            flash_plan=None,  # type: ignore[arg-type]
            chapters=(("ch1", "Eligibility", "eligibility", ("s1", "s2")),),
            document_role="protocol",
            ambiguity_codes=(),
        )
        chunks = list(build_chunks_from_plan(plan, spans)[0].values())[0]
        self.assertEqual(1, len(chunks))
        self.assertIn("has been\n\nobtained", chunks[0].source_text)

    def test_objective_endpoint_table_merges_nonadjacent_page_continuation(
        self,
    ) -> None:
        def span(span_id, page, block_index, text, bbox, heading):
            return SimpleNamespace(
                span_id=span_id,
                source_text=text,
                physical_page=page,
                block_index=block_index,
                section_heading=heading,
                source_fragments=(SimpleNamespace(bbox=bbox),),
            )

        spans = (
            span(
                "complete_safety_row",
                41,
                0,
                "• Number of TEAEs recorded through Week 16. "
                "Exploratory endpoint (safety)",
                (272.0, 640.0, 520.0, 680.0),
                "Objectives Endpoints",
            ),
            span(
                "left_start",
                41,
                1,
                "To compare the efficacy of four regimens with",
                (73.0, 690.0, 245.0, 716.0),
                "Objectives Endpoints",
            ),
            span(
                "endpoint",
                42,
                3,
                "• Reduction of ADSD Worst score ≥4 at Week 16.",
                (272.0, 105.0, 520.0, 133.0),
                "Objectives Endpoints",
            ),
            span(
                "objective",
                42,
                4,
                "Objectives Endpoints placebo in subjects with AD.",
                (73.0, 91.0, 413.0, 156.0),
                "Objectives Endpoints placebo in subjects with AD.",
            ),
            span(
                "next_heading",
                42,
                5,
                "Exploratory endpoint (PRO)",
                (254.0, 161.0, 382.0, 173.0),
                "Objectives Endpoints placebo in subjects with AD.",
            ),
        )
        plan = DocumentPlanResult(
            flash_plan=None,  # type: ignore[arg-type]
            chapters=(
                (
                    "ch1",
                    "Objectives and endpoints",
                    "objectives_endpoints",
                    (
                        "complete_safety_row",
                        "left_start",
                        "endpoint",
                        "objective",
                        "next_heading",
                    ),
                ),
            ),
            document_role="protocol",
            ambiguity_codes=(),
        )
        chunks = list(build_chunks_from_plan(plan, spans)[0].values())[0]
        source = "\n\n".join(chunk.source_text for chunk in chunks)
        self.assertIn(
            "four regimens with placebo in subjects with AD.",
            source,
        )
        self.assertNotIn("Objectives Endpoints placebo", source)
        self.assertNotIn(
            "Exploratory endpoint (safety) placebo",
            source,
        )
        self.assertIn("Reduction of ADSD", source)
        self.assertIn(
            "objective",
            {
                source_span_id
                for chunk in chunks
                for source_span_id in chunk.source_span_ids
            },
        )

    def test_markdown_objective_row_merges_across_repeated_header(self) -> None:
        spans = (
            SimpleNamespace(
                span_id="row_start",
                source_text=(
                    "| To compare efficacy of four regimens with | "
                    "Exploratory endpoint (PRO) |"
                ),
                physical_page=41,
                section_heading="Objectives Endpoints",
                source_fragments=(),
            ),
            SimpleNamespace(
                span_id="repeated_header",
                source_text="| Objectives | Endpoints |",
                physical_page=42,
                section_heading="Objectives Endpoints",
                source_fragments=(),
            ),
            SimpleNamespace(
                span_id="row_continuation",
                source_text=(
                    "| placebo in subjects with AD. | "
                    "• Reduction of ADSD Worst score ≥4 at Week 16. |"
                ),
                physical_page=42,
                section_heading="Objectives Endpoints",
                source_fragments=(),
            ),
        )
        plan = DocumentPlanResult(
            flash_plan=None,  # type: ignore[arg-type]
            chapters=(
                (
                    "ch1",
                    "Objectives and endpoints",
                    "objectives_endpoints",
                    ("row_start", "repeated_header", "row_continuation"),
                ),
            ),
            document_role="protocol",
            ambiguity_codes=(),
        )
        chunks = list(build_chunks_from_plan(plan, spans)[0].values())[0]
        source = "\n\n".join(chunk.source_text for chunk in chunks)
        self.assertIn(
            "| To compare efficacy of four regimens with placebo in subjects with AD. "
            "| Exploratory endpoint (PRO) • Reduction of ADSD Worst score ≥4 at Week 16. |",
            source,
        )
        self.assertEqual(1, source.count("placebo in subjects with AD."))

    def test_each_markdown_table_row_is_an_isolated_context_free_chunk(self) -> None:
        spans = tuple(
            SimpleNamespace(
                span_id=f"row_{index}",
                source_text=f"| Objective {index} | Endpoint at Week {index} |",
                physical_page=40,
                section_heading="Objectives Endpoints",
                source_fragments=(),
            )
            for index in range(1, 4)
        )
        plan = DocumentPlanResult(
            flash_plan=None,  # type: ignore[arg-type]
            chapters=(
                (
                    "ch1",
                    "Objectives and endpoints",
                    "objectives_endpoints",
                    tuple(span.span_id for span in spans),
                ),
            ),
            document_role="protocol",
            ambiguity_codes=(),
        )
        chunks = list(build_chunks_from_plan(plan, spans)[0].values())[0]

        self.assertEqual(3, len(chunks))
        self.assertTrue(all(chunk.adjacent_context == "" for chunk in chunks))
        self.assertEqual(
            [span.source_text for span in spans],
            [chunk.source_text for chunk in chunks],
        )

    def test_abbreviation_footnote_is_an_isolated_context_free_chunk(self) -> None:
        spans = (
            SimpleNamespace(
                span_id="before",
                source_text="Exploratory endpoint description.",
            ),
            SimpleNamespace(
                span_id="abbreviations",
                source_text=(
                    "Abbreviations: EASI = Eczema Area and Severity Index; "
                    "EASI-100 = 100% reduction in EASI score; "
                    "PK = pharmacokinetics;"
                ),
            ),
            SimpleNamespace(
                span_id="panel",
                source_text="Panel 4: Objectives, estimands, and endpoints",
            ),
        )
        plan = DocumentPlanResult(
            flash_plan=None,  # type: ignore[arg-type]
            chapters=(
                (
                    "ch1",
                    "Objectives and endpoints",
                    "objectives_endpoints",
                    tuple(span.span_id for span in spans),
                ),
            ),
            document_role="protocol",
            ambiguity_codes=(),
        )
        chunks = list(build_chunks_from_plan(plan, spans)[0].values())[0]
        abbreviation_chunk = next(
            chunk for chunk in chunks if chunk.source_span_ids == ("abbreviations",)
        )

        self.assertEqual("", abbreviation_chunk.adjacent_context)
        self.assertNotIn("Panel 4", abbreviation_chunk.source_text)

    def test_chunk_identity_is_stable_for_exact_input_and_changes_with_source(self) -> None:
        def build(source_text: str):
            spans = (
                SimpleNamespace(
                    span_id="stable_span",
                    source_text=source_text,
                ),
            )
            plan = DocumentPlanResult(
                flash_plan=None,  # type: ignore[arg-type]
                chapters=(
                    (
                        "ch1",
                        "Eligibility",
                        "eligibility",
                        ("stable_span",),
                    ),
                ),
                document_role="protocol",
                ambiguity_codes=(),
            )
            return list(build_chunks_from_plan(plan, spans)[0].values())[0][0]

        first = build("Participants must be 18 years of age or older.")
        replay = build("Participants must be 18 years of age or older.")
        changed = build("Participants must be 21 years of age or older.")

        self.assertEqual(first.chunk_id, replay.chunk_id)
        self.assertEqual(first.chunk_fingerprint, replay.chunk_fingerprint)
        self.assertNotEqual(first.chunk_id, changed.chunk_id)
        self.assertNotEqual(first.chunk_fingerprint, changed.chunk_fingerprint)
        self.assertEqual(("stable_span",), first.source_span_ids)

    def test_oversized_markdown_table_row_remains_one_unit(self) -> None:
        row = (
            "| To compare active treatment with placebo. | "
            + " • Change from baseline to Week 16." * 80
            + " |"
        )
        self.assertGreater(len(row), 1200)
        units = split_source_into_units(row)
        self.assertEqual(1, len(units))
        self.assertEqual(row, units[0].text)
        self.assertEqual(3, units[0].text.count("|"))

    def test_range_inclusivity_correction_note_is_explicit(self) -> None:
        note = build_correction_note(("unit_9:range_inclusivity_changed",))
        self.assertIn("18至75周岁（含两端值）", note)
        self.assertIn("不得写成“75周岁以下”", note)

    def test_dense_translation_correction_note_is_actionable(self) -> None:
        note = build_correction_note(
            (
                "unit_1:numeric_tokens_changed",
                "unit_1:unit_sequence_changed",
                "unit_1:bullet_cardinality_changed",
                "unit_7:source_abbreviation_missing",
                "unit_11:regulatory_chinese_term_calque",
            )
        )
        self.assertIn("不得把“4”改写成“四”", note)
        self.assertIn("EASI-50/75/90/100", note)
        self.assertIn("EASI score ≥12 at screening and ≥16 at baseline", note)
        self.assertIn("不得把基线阈值省略成", note)
        self.assertIn("不得跨条目移动", note)
        self.assertIn("第X周较基线的变化", note)
        self.assertIn("不得改成冒号、顿号或直接删除", note)
        self.assertIn("规范中文（原缩略语）", note)
        self.assertIn("受控中英术语表", note)

    def test_table_structure_correction_note_preserves_literal_boundaries(self) -> None:
        note = build_correction_note(
            (
                "unit_1:table_row_cardinality_changed",
                "unit_1:table_cell_cardinality_changed",
            )
        )
        self.assertIn("表格结构专门要求", note)
        self.assertIn("竖线“|”", note)
        self.assertIn("项目符号“•”", note)

    def test_term_and_untranslated_connector_correction_is_actionable(self) -> None:
        note = build_correction_note(
            (
                "unit_9:controlled_term_missing:patient_reported_outcome",
                "unit_12:untranslated_source_connector",
            )
        )
        self.assertIn("受控术语专门要求", note)
        self.assertIn("preferred_zh", note)
        self.assertIn("未译英文专门要求", note)
        self.assertIn("等号右侧定义", note)

    def test_imp_and_subject_clause_correction_is_actionable(self) -> None:
        note = build_correction_note(
            (
                "unit_9:unsupported_medical_concept_added",
                "unit_12:controlled_term_missing:participant",
            )
        )
        self.assertIn("试验药物的评估", note)
        self.assertIn("不得新增疗效", note)
        self.assertIn("受试者主语专门要求", note)

    def test_scale_identity_correction_keeps_hy_mt2_on_the_same_scale(self) -> None:
        note = build_correction_note(("unit_1:unsupported_scale_identity_added:EASI",))
        self.assertIn("量表身份专门要求", note)
        self.assertIn("原文只出现IGA时只能保留IGA", note)
        self.assertIn("不得新增或替换为EASI", note)
        self.assertIn("不得建立EASI与IGA/vIGA-AD之间", note)

    def test_hy_provider_prompt_requires_table_bullet_preservation(self) -> None:
        from services.api.app import main as api_main

        captured: list[dict] = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps(
                    {
                        "choices": [
                            {
                                "finish_reason": "stop",
                                "message": {
                                    "content": (
                                        "[[CMS_SEG_0001]]\n"
                                        "| 研究目的 | 探索性终点 • 第1周浓度。 |\n"
                                        "[[/CMS_SEG_0001]]"
                                    )
                                },
                            }
                        ]
                    }
                ).encode()

        def fake_urlopen(request, timeout):
            del timeout
            captured.append(json.loads(request.data.decode()))
            return Response()

        source = (
            "[[CMS_SEG_0001]]\n"
            "| Objective | Exploratory endpoint • Concentration at Week 1. |\n"
            "[[/CMS_SEG_0001]]"
        )
        with (
            _controlled_translation_body_role(api_main),
            patch("urllib.request.urlopen", side_effect=fake_urlopen),
        ):
            api_main._hy_mt2_translator_adapter(
                source, "glossary-a", "ch07", "c1", "", ""
            )

        system_prompt = captured[0]["messages"][0]["content"]
        self.assertIn("每个“•”项目符号", system_prompt)
        self.assertIn("不得改成冒号、顿号或直接删除", system_prompt)
        self.assertIn("Epub完整日期", system_prompt)
        self.assertIn("不得缩短页码", system_prompt)


# ---------------------------------------------------------------------------
# Point 3: malformed marker output fails closed
# ---------------------------------------------------------------------------


class MarkerValidationTests(unittest.TestCase):
    def _marked(self, ordinal: int, text: str) -> str:
        return f"[[CMS_SEG_{ordinal:04d}]]\n{text}\n[[/CMS_SEG_{ordinal:04d}]]"

    def test_missing_marker_fails(self) -> None:
        _, errors = parse_unit_delimited_output(
            self._marked(1, "译文一"), expected_ordinals=[1, 2]
        )
        self.assertIn("missing_unit_output:2", errors)

    def test_single_unit_markerless_output_fails(self) -> None:
        _, errors = parse_unit_delimited_output(
            "只有一段但没有标记的译文", expected_ordinals=[1]
        )
        self.assertEqual(["no_unit_markers_in_output"], errors)

    def test_duplicate_marker_fails(self) -> None:
        output = self._marked(1, "译文一") + "\n\n" + self._marked(1, "译文一重复")
        _, errors = parse_unit_delimited_output(output, expected_ordinals=[1])
        self.assertIn("duplicate_unit_output:1", errors)

    def test_reordered_markers_fail(self) -> None:
        output = self._marked(2, "译文二") + "\n\n" + self._marked(1, "译文一")
        _, errors = parse_unit_delimited_output(output, expected_ordinals=[1, 2])
        self.assertIn("reordered_unit_output", errors)

    def test_unknown_marker_fails(self) -> None:
        output = self._marked(1, "译文一") + "\n\n" + self._marked(3, "译文三")
        _, errors = parse_unit_delimited_output(output, expected_ordinals=[1, 2])
        self.assertIn("extra_unit_output:3", errors)

    def test_text_outside_markers_fails(self) -> None:
        output = "以下为译文：\n" + self._marked(1, "译文一")
        _, errors = parse_unit_delimited_output(output, expected_ordinals=[1])
        self.assertIn("text_outside_unit_markers", errors)

    def test_stray_close_marker_fails(self) -> None:
        output = self._marked(1, "译文一") + "\n[[/CMS_SEG_0001]]"
        _, errors = parse_unit_delimited_output(output, expected_ordinals=[1])
        self.assertIn("unexpected_close_unit_output:1", errors)

    def test_nested_marker_fails(self) -> None:
        output = (
            "[[CMS_SEG_0001]]\n译文一\n"
            "[[CMS_SEG_0002]]\n译文二\n"
            "[[/CMS_SEG_0002]]\n[[/CMS_SEG_0001]]"
        )
        _, errors = parse_unit_delimited_output(output, expected_ordinals=[1, 2])
        self.assertIn("nested_unit_output:2", errors)

    def test_noncanonical_marker_padding_fails(self) -> None:
        output = "[[CMS_SEG_1]]\n译文一\n[[/CMS_SEG_1]]"
        _, errors = parse_unit_delimited_output(output, expected_ordinals=[1])
        self.assertIn("noncanonical_unit_marker:1", errors)

    def test_empty_unit_fails(self) -> None:
        units = (
            TranslationUnit(ordinal=1, text="Source one."),
            TranslationUnit(ordinal=2, text="Source two."),
        )
        codes = reject_misaligned_output(units, {1: "译文一", 2: "  "})
        self.assertIn("empty_unit_output:2", codes)

    def test_well_formed_output_passes(self) -> None:
        output = self._marked(1, "译文一") + "\n\n" + self._marked(2, "译文二")
        parsed, errors = parse_unit_delimited_output(output, expected_ordinals=[1, 2])
        self.assertEqual([], errors)
        self.assertEqual({1: "译文一", 2: "译文二"}, parsed)


# ---------------------------------------------------------------------------
# Point 4: clinical abbreviation detection — no title-case guessing
# ---------------------------------------------------------------------------


class AbbreviationDetectionTests(unittest.TestCase):
    def test_protocol_visit_schedule_labels_are_not_abbreviations_but_ecg_is(
        self,
    ) -> None:
        detected = detect_clinical_abbreviations("12. VISIT SCHEDULE — ECG")

        self.assertEqual(("ECG",), detected)
        self.assertNotIn("VISIT", detected)
        self.assertNotIn("SCHEDULE", detected)
        self.assertIn("ECG", detected)

    def test_chinese_protocol_heading_preserves_number_without_abbreviation_failure(
        self,
    ) -> None:
        result = evaluate_translation_fidelity(
            "12. VISIT SCHEDULE",
            "12. 访视安排",
        )

        self.assertTrue(result.passed)
        self.assertEqual((), result.failure_codes)
        self.assertEqual(("12",), result.source_numeric_tokens)
        self.assertEqual(("12",), result.translated_numeric_tokens)

    def test_real_clinical_abbreviation_removed_from_mixed_header_still_blocks(
        self,
    ) -> None:
        source = "12. VISIT SCHEDULE — ECG"
        self.assertEqual(
            ("ECG",),
            detect_clinical_abbreviations(source),
        )

        result = evaluate_translation_fidelity(
            source,
            "12. 访视安排",
        )

        self.assertFalse(result.passed)
        self.assertIn("source_abbreviation_missing", result.failure_codes)

    def test_mixed_case_clinical_forms_detected(self) -> None:
        text = (
            "The Trial used eCRF entry, eGFR screening, mITT analysis and "
            "vIGA-AD scoring with AE and SAEs reporting per Protocol."
        )
        detected = detect_clinical_abbreviations(text)
        for expected in ("eCRF", "eGFR", "mITT", "vIGA-AD", "AE", "SAEs"):
            self.assertIn(expected, detected)

    def test_title_case_words_not_detected(self) -> None:
        text = "The Trial was Randomized at each Visit per Protocol Section."
        detected = detect_clinical_abbreviations(text)
        for word in ("The", "Trial", "Randomized", "Visit", "Protocol", "Section"):
            self.assertNotIn(word, detected)

    def test_roman_numeral_class_range_is_not_an_abbreviation(self) -> None:
        detected = detect_clinical_abbreviations(
            "Use EU class II-IV topical treatment with TCS."
        )
        self.assertNotIn("II-IV", detected)
        self.assertIn("EU", detected)
        self.assertIn("TCS", detected)

    def test_ad_protocol_abbreviation_equivalents_and_chinese_negation_pass(
        self,
    ) -> None:
        result = evaluate_translation_fidelity(
            (
                "Subjects with AD must not be put at undue risk. "
                "Change in BSA after treatment with TCS."
            ),
            (
                "特应性皮炎受试者不会因参加试验而面临过度风险。"
                "外用类固醇治疗后受累皮肤面积的变化。"
            ),
        )
        self.assertNotIn("source_abbreviation_missing", result.failure_codes)
        self.assertNotIn("negation_signal_missing", result.failure_codes)

    def test_ad_endpoint_abbreviation_full_terms_are_faithful(self) -> None:
        pairs = (
            ("An AE related to worsening of AD.", "与特应性皮炎加重相关的不良事件。"),
            (
                "Percent change in EASI score.",
                "湿疹面积和严重程度指数评分的百分比变化。",
            ),
            ("Reduction of DLQI ≥4.", "皮肤病生活质量指数评分下降幅度≥4。"),
            ("Reduction of POEM ≥4.", "患者导向型湿疹评估量表评分下降幅度≥4。"),
            ("To evaluate the PK.", "评估药代动力学特征。"),
            ("Exploratory endpoints (PD).", "探索性药效学终点。"),
            ("Exploratory endpoint (PRO).", "探索性患者报告结局终点。"),
        )
        for source, target in pairs:
            with self.subTest(source=source):
                result = evaluate_translation_fidelity(source, target)
                self.assertNotIn(
                    "source_abbreviation_missing",
                    result.failure_codes,
                )


# ---------------------------------------------------------------------------
# Point 5: Hy truncation/empty/missing markers fail closed
# ---------------------------------------------------------------------------


class HyMalformedOutputTests(unittest.TestCase):
    def test_finish_reason_length_fails(self) -> None:
        payload = {
            "choices": [{"finish_reason": "length", "message": {"content": "部分译文"}}]
        }
        with self.assertRaises(ChapterTranslationPipelineError):
            validate_completion_payload(payload, "Hy-MT2")

    def test_empty_content_fails(self) -> None:
        payload = {"choices": [{"finish_reason": "stop", "message": {"content": "  "}}]}
        with self.assertRaises(ChapterTranslationPipelineError):
            validate_completion_payload(payload, "Hy-MT2")

    def test_missing_choices_fails(self) -> None:
        with self.assertRaises(ChapterTranslationPipelineError):
            validate_completion_payload({"choices": []}, "Hy-MT2")

    def test_valid_payload_returns_content(self) -> None:
        payload = {
            "choices": [{"finish_reason": "stop", "message": {"content": "译文"}}]
        }
        self.assertEqual("译文", validate_completion_payload(payload, "Hy-MT2"))

    def test_non_stop_finish_reason_fails(self) -> None:
        for reason in (None, "content_filter", "tool_calls"):
            payload = {
                "choices": [{"finish_reason": reason, "message": {"content": "译文"}}]
            }
            with self.subTest(reason=reason):
                with self.assertRaises(ChapterTranslationPipelineError):
                    validate_completion_payload(payload, "Hy-MT2")

    def test_missing_markers_fail_after_bounded_retry(self) -> None:
        calls: list[str] = []

        def unmarked_translator(source, glossary, chapter_id, chunk_id, *args):
            calls.append(source)
            return _hy_result(chapter_id, chunk_id, "无标记译文全文")

        units = (
            TranslationUnit(ordinal=1, text="First source unit."),
            TranslationUnit(ordinal=2, text="Second source unit."),
        )
        with self.assertRaises(FidelityBlockedError) as raised:
            translate_units_with_bounded_correction(
                unmarked_translator,
                units=units,
                glossary="",
                chapter_id="ch1",
                chunk_id="c1",
            )
        self.assertIn("no_unit_markers_in_output", raised.exception.failure_codes)
        self.assertEqual(2, len(calls))

    def test_single_unit_markerless_output_recovers_after_bounded_retry(self) -> None:
        calls: list[str] = []

        def unmarked_translator(source, glossary, chapter_id, chunk_id, *args):
            del glossary, args
            calls.append(source)
            return _hy_result(
                chapter_id,
                chunk_id,
                "所有不良事件均应随访直至恢复。",
            )

        units = (
            TranslationUnit(
                ordinal=1,
                text="All adverse events should be followed until resolution.",
            ),
        )
        result, parsed = translate_units_with_bounded_correction(
            unmarked_translator,
            units=units,
            glossary="",
            chapter_id="ch1",
            chunk_id="c1",
        )

        self.assertEqual(2, len(calls))
        self.assertEqual(
            "hy_mt2_single_unit_envelope_recovery",
            result.translation_strategy,
        )
        self.assertEqual({1: "所有不良事件均应随访直至恢复。"}, parsed)

    def test_single_unit_unclosed_open_marker_recovers_after_bounded_retry(self) -> None:
        calls: list[str] = []

        def unclosed_translator(source, glossary, chapter_id, chunk_id, *args):
            del glossary, args
            calls.append(source)
            return _hy_result(
                chapter_id,
                chunk_id,
                "[[CMS_SEG_0001]]\n"
                "皮肤活检样本将在基线和研究结束访视时采集。",
            )

        units = (
            TranslationUnit(
                ordinal=1,
                text=(
                    "Skin biopsy samples will be collected at baseline and "
                    "at the end-of-study visit."
                ),
            ),
        )
        result, parsed = translate_units_with_bounded_correction(
            unclosed_translator,
            units=units,
            glossary="",
            chapter_id="ch3",
            chunk_id="c-real-unclosed",
        )

        self.assertEqual(2, len(calls))
        self.assertEqual(
            "hy_mt2_single_unit_envelope_recovery",
            result.translation_strategy,
        )
        self.assertEqual(
            {1: "皮肤活检样本将在基线和研究结束访视时采集。"},
            parsed,
        )

    def test_single_unit_wrong_or_extra_marker_remains_blocked(self) -> None:
        units = (TranslationUnit(ordinal=1, text="Source text."),)

        def malformed_translator(source, glossary, chapter_id, chunk_id, *args):
            del source, glossary, args
            return _hy_result(
                chapter_id,
                chunk_id,
                "[[CMS_SEG_0002]]\n错误单元\n[[/CMS_SEG_0002]]",
            )

        with self.assertRaises(FidelityBlockedError):
            translate_units_with_bounded_correction(
                malformed_translator,
                units=units,
                glossary="",
                chapter_id="ch1",
                chunk_id="c-wrong-marker",
            )


# ---------------------------------------------------------------------------
# Point 6: one bounded Hy correction; second failure blocks
# ---------------------------------------------------------------------------


class HyBoundedCorrectionTests(unittest.TestCase):
    def _translator(self, correct_on_retry: bool):
        state = {"calls": [], "notes": []}

        def translator(
            source,
            glossary,
            chapter_id,
            chunk_id,
            read_only_context="",
            correction_note="",
        ):
            state["calls"].append(source)
            state["notes"].append(correction_note)
            ordinals = [
                int(m.group(1))
                for m in re.finditer(r"\[\[CMS_SEG_(\d{1,4})\]\]", source)
            ]
            keep = (
                ordinals
                if (correction_note or correct_on_retry is None)
                else ordinals[:1]
            )
            if correct_on_retry is False:
                keep = ordinals[:1]
            blocks = [
                f"[[CMS_SEG_{o:04d}]]\n第{o}单元译文\n[[/CMS_SEG_{o:04d}]]"
                for o in keep
            ]
            return _hy_result(chapter_id, chunk_id, "\n\n".join(blocks))

        return state, translator

    def test_compressed_output_triggers_one_correction_then_continues(self) -> None:
        state, translator = self._translator(correct_on_retry=True)
        units = (
            TranslationUnit(ordinal=1, text="First source unit."),
            TranslationUnit(ordinal=2, text="Second source unit."),
        )
        _, parsed = translate_units_with_bounded_correction(
            translator, units=units, glossary="", chapter_id="ch1", chunk_id="c1"
        )
        self.assertEqual(2, len(state["calls"]))
        self.assertEqual([1, 2], sorted(parsed))
        # The correction note names the exact failing unit IDs and codes.
        self.assertIn("missing_unit_output:2", state["notes"][1])

    def test_second_bad_output_blocks_with_exactly_two_calls(self) -> None:
        state, translator = self._translator(correct_on_retry=False)
        units = (
            TranslationUnit(ordinal=1, text="First source unit."),
            TranslationUnit(ordinal=2, text="Second source unit."),
        )
        with self.assertRaises(FidelityBlockedError) as raised:
            translate_units_with_bounded_correction(
                translator, units=units, glossary="", chapter_id="ch1", chunk_id="c1"
            )
        self.assertEqual(2, len(state["calls"]))
        self.assertIn("missing_unit_output:2", raised.exception.failure_codes)

    def test_group_fidelity_failure_retranslates_only_failed_units_with_hy(self) -> None:
        calls: list[tuple[str, list[int]]] = []
        units = (
            TranslationUnit(
                ordinal=1,
                text="Comparable to IGA 0=clear to 2=mild.",
            ),
            TranslationUnit(
                ordinal=4,
                text="6. EASI score ≥12 at screening and ≥16 at baseline.",
            ),
        )

        def translator(
            source,
            glossary,
            chapter_id,
            chunk_id,
            read_only_context="",
            correction_note="",
        ):
            del glossary, read_only_context, correction_note
            ordinals = [
                int(match.group(1))
                for match in re.finditer(r"\[\[CMS_SEG_(\d{1,4})\]\]", source)
            ]
            calls.append((chunk_id, ordinals))
            if len(ordinals) > 1:
                translated = (
                    "[[CMS_SEG_0001]]\n"
                    "相当于湿疹面积和严重程度指数（EASI）评分0（清除）至2（轻度）。\n"
                    "[[/CMS_SEG_0001]]\n\n"
                    "[[CMS_SEG_0004]]\n"
                    "6. 筛选时EASI评分≥12分，基线时也需满足该分值。\n"
                    "[[/CMS_SEG_0004]]"
                )
            else:
                translated_by_ordinal = {
                    1: "相当于研究者整体评估（IGA）评分0（清除）至2（轻度）。",
                    4: "6. 筛选时EASI评分≥12分且基线时≥16分。",
                }
                ordinal = ordinals[0]
                translated = (
                    f"[[CMS_SEG_{ordinal:04d}]]\n"
                    f"{translated_by_ordinal[ordinal]}\n"
                    f"[[/CMS_SEG_{ordinal:04d}]]"
                )
            return _hy_result(chapter_id, chunk_id, translated)

        result, parsed = translate_units_with_bounded_correction(
            translator,
            units=units,
            glossary="",
            chapter_id="ch09",
            chunk_id="eligibility",
        )

        self.assertEqual(
            [
                ("eligibility", [1, 4]),
                ("eligibility", [1, 4]),
                ("eligibility:failed_unit_1", [1]),
                ("eligibility:failed_unit_4", [4]),
            ],
            calls,
        )
        self.assertNotIn("EASI", parsed[1])
        self.assertIn("IGA", parsed[1])
        self.assertIn("≥12", parsed[4])
        self.assertIn("≥16", parsed[4])
        self.assertEqual(
            "hy_mt2_failed_unit_isolation_fallback",
            result.translation_strategy,
        )

    def test_malformed_group_retry_uses_prior_aligned_failure_units(self) -> None:
        calls: list[tuple[str, list[int]]] = []
        units = (
            TranslationUnit(
                ordinal=1,
                text="Comparable to IGA 0=clear to 2=mild.",
            ),
            TranslationUnit(
                ordinal=4,
                text="6. EASI score ≥12 at screening and ≥16 at baseline.",
            ),
        )

        def translator(
            source,
            glossary,
            chapter_id,
            chunk_id,
            read_only_context="",
            correction_note="",
        ):
            del glossary, read_only_context
            ordinals = [
                int(match.group(1))
                for match in re.finditer(r"\[\[CMS_SEG_(\d{1,4})\]\]", source)
            ]
            calls.append((chunk_id, ordinals))
            if len(ordinals) > 1 and not correction_note:
                translated = (
                    "[[CMS_SEG_0001]]\n"
                    "相当于湿疹面积和严重程度指数（EASI）评分0（清除）至2（轻度）。\n"
                    "[[/CMS_SEG_0001]]\n\n"
                    "[[CMS_SEG_0004]]\n"
                    "6. 筛选时EASI评分≥12分，基线时也需满足该分值。\n"
                    "[[/CMS_SEG_0004]]"
                )
            elif len(ordinals) > 1:
                translated = (
                    "[[CMS_SEG_0001]]\n"
                    "[[CMS_SEG_0001]]\n重复嵌套标记\n[[/CMS_SEG_0001]]\n"
                    "[[/CMS_SEG_0001]]"
                )
            else:
                translated_by_ordinal = {
                    1: "相当于研究者整体评估（IGA）评分0（清除）至2（轻度）。",
                    4: "6. 筛选时EASI评分≥12分且基线时≥16分。",
                }
                ordinal = ordinals[0]
                translated = (
                    f"[[CMS_SEG_{ordinal:04d}]]\n"
                    f"{translated_by_ordinal[ordinal]}\n"
                    f"[[/CMS_SEG_{ordinal:04d}]]"
                )
            return _hy_result(chapter_id, chunk_id, translated)

        result, parsed = translate_units_with_bounded_correction(
            translator,
            units=units,
            glossary="",
            chapter_id="ch09",
            chunk_id="eligibility",
        )

        self.assertEqual(
            [
                ("eligibility", [1, 4]),
                ("eligibility", [1, 4]),
                ("eligibility:failed_unit_1", [1]),
                ("eligibility:failed_unit_4", [4]),
            ],
            calls,
        )
        self.assertNotIn("EASI", parsed[1])
        self.assertIn("IGA", parsed[1])
        self.assertIn("≥12", parsed[4])
        self.assertIn("≥16", parsed[4])
        self.assertEqual(
            "hy_mt2_failed_unit_isolation_fallback",
            result.translation_strategy,
        )

    def test_large_unit_set_is_translated_in_bounded_hy_only_batches(self) -> None:
        calls: list[tuple[str, list[int]]] = []

        def translator(
            source,
            glossary,
            chapter_id,
            chunk_id,
            read_only_context="",
            correction_note="",
        ):
            del glossary, read_only_context, correction_note
            ordinals = [
                int(match.group(1))
                for match in re.finditer(r"\[\[CMS_SEG_(\d{1,4})\]\]", source)
            ]
            calls.append((chunk_id, ordinals))
            translated = "\n\n".join(
                f"[[CMS_SEG_{ordinal:04d}]]\n安全性监测。\n[[/CMS_SEG_{ordinal:04d}]]"
                for ordinal in ordinals
            )
            return _hy_result(chapter_id, chunk_id, translated)

        units = tuple(
            TranslationUnit(ordinal=ordinal, text="Safety monitoring.")
            for ordinal in range(1, 12)
        )
        result, parsed = translate_units_with_bounded_correction(
            translator,
            units=units,
            glossary="",
            chapter_id="ch9",
            chunk_id="chunk2",
        )

        self.assertEqual(
            [
                ("chunk2:unit_batch_1", [1, 2, 3, 4, 5, 6]),
                ("chunk2:unit_batch_2", [7, 8, 9, 10, 11]),
            ],
            calls,
        )
        self.assertEqual(list(range(1, 12)), sorted(parsed))
        self.assertTrue(all(text == "安全性监测。" for text in parsed.values()))
        self.assertEqual("chunk2", result.chunk_id)
        self.assertEqual(
            result.translated_text_sha256,
            _sha256(result.translated_text),
        )

    def test_dense_table_row_falls_back_to_hy_only_fragment_translation(self) -> None:
        calls: list[str] = []

        def translator(
            source,
            glossary,
            chapter_id,
            chunk_id,
            read_only_context="",
            correction_note="",
        ):
            del glossary, read_only_context, correction_note
            calls.append(chunk_id)
            ordinals = [
                int(match.group(1))
                for match in re.finditer(r"\[\[CMS_SEG_(\d{1,4})\]\]", source)
            ]
            if "|" in source:
                translated = (
                    f"[[CMS_SEG_{ordinals[0]:04d}]]\n"
                    "整行普通段落\n"
                    f"[[/CMS_SEG_{ordinals[0]:04d}]]"
                )
            else:
                preferred = {
                    1: "研究目的。",
                    2: "主要终点",
                    3: "终点一。",
                    4: "终点二。",
                }
                translated = "\n\n".join(
                    f"[[CMS_SEG_{ordinal:04d}]]\n{preferred[ordinal]}\n"
                    f"[[/CMS_SEG_{ordinal:04d}]]"
                    for ordinal in ordinals
                )
            return _hy_result(chapter_id, chunk_id, translated)

        source_row = (
            "| Objective text. | Primary endpoint • Endpoint one. • Endpoint two. |"
        )
        result, parsed = translate_units_with_bounded_correction(
            translator,
            units=(TranslationUnit(ordinal=1, text=source_row),),
            glossary="",
            chapter_id="ch7",
            chunk_id="dense_table",
        )

        self.assertEqual(
            [
                "dense_table",
                "dense_table",
                "dense_table:table_fragments",
            ],
            calls,
        )
        self.assertEqual(3, parsed[1].count("|"))
        self.assertEqual(2, parsed[1].count("•"))
        self.assertTrue(parsed[1].startswith("| "))
        self.assertTrue(parsed[1].endswith(" |"))
        self.assertEqual(result.output_hash, _sha256(result.translated_text))
        self.assertEqual(
            "hy_mt2_table_fragment_fallback",
            result.translation_strategy,
        )

    def test_post_hy_normalization_is_persisted_without_an_extra_model_retry(
        self,
    ) -> None:
        calls = 0

        def translator(source, glossary, chapter_id, chunk_id, *args):
            nonlocal calls
            calls += 1
            del source, glossary, args
            return _hy_result(
                chapter_id,
                chunk_id,
                "[[CMS_SEG_0001]]\n"
                "湿疹面积和严重程度指数 = 湿疹面积和严重程度指数；\n"
                "[[/CMS_SEG_0001]]\n\n"
                "[[CMS_SEG_0002]]\n患者必须完成筛选。\n"
                "[[/CMS_SEG_0002]]",
            )

        units = (
            TranslationUnit(
                ordinal=1,
                text="EASI = Eczema Area and Severity Index;",
            ),
            TranslationUnit(
                ordinal=2,
                text="Subjects must complete screening.",
            ),
        )

        _, parsed = translate_units_with_bounded_correction(
            translator,
            units=units,
            glossary="",
            chapter_id="ch1",
            chunk_id="c1",
        )

        self.assertEqual(1, calls)
        self.assertEqual("EASI = 湿疹面积和严重程度指数；", parsed[1])
        self.assertEqual("受试者必须完成筛选。", parsed[2])

    def test_post_hy_normalization_deduplicates_source_bound_easi_endpoint(
        self,
    ) -> None:
        normalized = normalize_post_hy_unit_output(
            "Achievement of EASI-100 at Week 16.",
            "第16周达到湿疹面积和严重程度指数-100（EASI-100）标准。",
        )
        self.assertEqual("第16周达到EASI-100标准。", normalized)

    def test_post_hy_normalization_uses_controlled_definition_values(self) -> None:
        normalized = normalize_post_hy_unit_output(
            (
                "SCORAD = SCORing Atopic Dermatitis; "
                "TEAEs = treatment-emergent adverse events;"
            ),
            (
                "特应性皮炎评分 = 用于量化皮肤病变的工具；"
                "治疗期间出现的不良事件 = 任何新发反应。"
            ),
        )
        self.assertEqual(
            "SCORAD = 特应性皮炎评分；TEAEs = 治疗期间出现的不良事件。",
            normalized,
        )

    def test_post_hy_normalization_uses_actual_comma_definition_separator(self) -> None:
        normalized = normalize_post_hy_unit_output(
            "PK = pharmacokinetics, PD = pharmacodynamics;",
            "药代动力学 = pharmacokinetics，药效动力学 = pharmacodynamics；",
        )
        self.assertEqual(
            "PK = 药代动力学，PD = 药效动力学；",
            normalized,
        )

    def test_post_hy_normalization_restores_inline_crf_abbreviation(self) -> None:
        normalized = normalize_post_hy_unit_output(
            "The event must be documented on the appropriate CRF page.",
            "该事件必须记录在相应的病例报告表页面。",
        )
        self.assertEqual(
            "该事件必须记录在相应的病例报告表（CRF）页面。",
            normalized,
        )


class CallableCompatibilityTests(unittest.TestCase):
    def test_hy_internal_type_error_is_not_retried_as_legacy_arity(self) -> None:
        calls = 0

        def translator(
            source,
            glossary,
            chapter_id,
            chunk_id,
            read_only_context="",
            correction_note="",
        ):
            nonlocal calls
            calls += 1
            raise TypeError("provider implementation defect")

        with self.assertRaisesRegex(TypeError, "provider implementation defect"):
            call_hy_mt2_translator(
                translator,
                source_text="source",
                glossary="glossary",
                chapter_id="ch1",
                chunk_id="chunk1",
                read_only_context="context",
                correction_note="correct",
            )
        self.assertEqual(1, calls)

    def test_flash_internal_type_error_is_not_retried_without_note(self) -> None:
        calls = 0

        def runner(translated, source, correction_note=""):
            nonlocal calls
            calls += 1
            raise TypeError("provider implementation defect")

        with self.assertRaisesRegex(TypeError, "provider implementation defect"):
            call_flash_qc_with_note(
                runner, "translated", "source", correction_note="correct"
            )
        self.assertEqual(1, calls)

    def test_legacy_arity_is_selected_before_invocation(self) -> None:
        hy_calls = 0
        flash_calls = 0

        def legacy_hy(source, glossary, chapter_id, chunk_id):
            nonlocal hy_calls
            hy_calls += 1
            return _hy_result(chapter_id, chunk_id, source)

        def legacy_flash(translated, source):
            nonlocal flash_calls
            flash_calls += 1
            return _flash_result(True, translated)

        call_hy_mt2_translator(
            legacy_hy,
            source_text="source",
            glossary="glossary",
            chapter_id="ch1",
            chunk_id="chunk1",
            read_only_context="context",
            correction_note="correct",
        )
        call_flash_qc_with_note(
            legacy_flash, "translated", "source", correction_note="correct"
        )
        self.assertEqual(1, hy_calls)
        self.assertEqual(1, flash_calls)


class ProviderInputLineageTests(unittest.TestCase):
    def test_hy_prompt_never_injects_a_literal_age_example(self) -> None:
        from services.api.app import main as api_main

        captured: list[dict] = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps(
                    {
                        "choices": [
                            {
                                "finish_reason": "stop",
                                "message": {
                                    "content": (
                                        "[[CMS_SEG_0001]]\n达到4分及以上\n"
                                        "[[/CMS_SEG_0001]]"
                                    )
                                },
                            }
                        ]
                    }
                ).encode()

        def fake_urlopen(request, timeout):
            del timeout
            captured.append(json.loads(request.data.decode()))
            return Response()

        source = "[[CMS_SEG_0001]]\nAchieve a score of >=4.\n[[/CMS_SEG_0001]]"
        with (
            _controlled_translation_body_role(api_main),
            patch("urllib.request.urlopen", side_effect=fake_urlopen),
        ):
            api_main._hy_mt2_translator_adapter(
                source, "glossary-a", "ch07", "c1", "", ""
            )

        system_prompt = captured[0]["messages"][0]["content"]
        self.assertNotIn("18", system_prompt)
        self.assertIn("只能使用原文实际下界", system_prompt)

    def test_abbreviation_definition_footnote_is_split_into_exact_units(self) -> None:
        units = split_source_into_units(
            "Abbreviations: AD = atopic dermatitis; "
            "EASI-50 = at least 50% reduction in EASI score; "
            "PK = pharmacokinetics; PD = pharmacodynamics; "
            "PRO = patient reported outcome; TEAE = treatment-emergent adverse event."
        )

        self.assertEqual(3, len(units))
        self.assertEqual(
            "Abbreviations: AD = atopic dermatitis; "
            "EASI-50 = at least 50% reduction in EASI score;",
            units[0].text,
        )
        self.assertEqual(
            "PK = pharmacokinetics; PD = pharmacodynamics;",
            units[1].text,
        )
        self.assertEqual(
            "PRO = patient reported outcome; TEAE = treatment-emergent adverse event.",
            units[2].text,
        )

    def test_abbreviation_definition_continuation_without_label_is_split(self) -> None:
        units = split_source_into_units(
            "EASI = Eczema Area and Severity Index; "
            "EQ-5D-5L = EuroQoL 5 Dimension Health Questionnaire 5 Level; "
            "IMP = investigational medicinal product; "
            "Suppl. = supplementary; VAS = Visual Analogue Scale;"
        )

        self.assertEqual(3, len(units))
        self.assertEqual(
            "EASI = Eczema Area and Severity Index; "
            "EQ-5D-5L = EuroQoL 5 Dimension Health Questionnaire 5 Level;",
            units[0].text,
        )
        self.assertEqual(
            "IMP = investigational medicinal product; Suppl. = supplementary;",
            units[1].text,
        )
        self.assertEqual("VAS = Visual Analogue Scale;", units[2].text)

    def test_comma_joined_abbreviation_definitions_are_independently_checked(
        self,
    ) -> None:
        source = "PK = pharmacokinetics, PD = pharmacodynamics;"
        self.assertIn(
            "abbreviation_definition_key_changed",
            structural_cardinality_failures(
                source,
                "PK = 药代动力学，PD表示药效动力学；",
            ),
        )

    def test_easi_100_definition_is_an_isolated_translation_unit(self) -> None:
        units = split_source_into_units(
            "Abbreviations: EASI-75 = at least 75% reduction in EASI score; "
            "EASI-90 = at least 90% reduction in EASI score; "
            "EASI-100 = 100% reduction in EASI score; "
            "PK = pharmacokinetics;"
        )

        self.assertEqual(3, len(units))
        self.assertEqual(
            "EASI-100 = 100% reduction in EASI score;",
            units[1].text,
        )

    def test_abbreviation_definition_keys_must_remain_exact(self) -> None:
        source = (
            "EASI = Eczema Area and Severity Index; "
            "EASI-50 = at least 50% reduction in EASI score;"
        )
        self.assertEqual(
            (),
            structural_cardinality_failures(
                source,
                "EASI = 湿疹面积和严重程度指数；EASI-50 = EASI评分降低至少50%；",
            ),
        )
        self.assertIn(
            "abbreviation_definition_key_changed",
            structural_cardinality_failures(
                source,
                "湿疹面积和严重程度指数 = 湿疹面积和严重程度指数；"
                "EASI-50 = EASI评分降低至少50%；",
            ),
        )

    def test_post_hy_restores_only_abbreviation_definition_left_keys(self) -> None:
        source = (
            "Abbreviations: EASI = Eczema Area and Severity Index; "
            "EQ-5D-5L = EuroQoL 5 Dimension Health Questionnaire 5 Level; "
            "Suppl. = supplementary;"
        )
        target = (
            "缩略语：湿疹面积和严重程度指数 = 湿疹面积和严重程度指数；"
            "欧洲五维健康量表五级版本 = 欧洲五维健康量表五级版本；"
            "补充内容 = 补充内容；"
        )

        restored = restore_abbreviation_definition_keys(source, target)

        self.assertEqual(
            "缩略语：EASI = 湿疹面积和严重程度指数；"
            "EQ-5D-5L = 欧洲五维健康量表五级版本；"
            "Suppl. = 补充内容；",
            restored,
        )
        self.assertEqual(
            [part.split("=", 1)[1] for part in target.split("；") if "=" in part],
            [part.split("=", 1)[1] for part in restored.split("；") if "=" in part],
        )

    def test_post_hy_abbreviation_restore_fails_closed_on_equals_count_mismatch(
        self,
    ) -> None:
        source = "EASI = Eczema Area and Severity Index; PK = pharmacokinetics;"
        target = "湿疹面积和严重程度指数表示湿疹面积和严重程度指数；PK = 药代动力学；"

        self.assertEqual(target, restore_abbreviation_definition_keys(source, target))
        self.assertIn(
            "abbreviation_definition_key_changed",
            structural_cardinality_failures(source, target),
        )

    def test_post_hy_abbreviation_restore_does_not_rewrite_rhs_equation(self) -> None:
        source = "AE = adverse event; PK = pharmacokinetics;"
        target = "不良事件 = 事件，其中x = y；药代动力学。"

        self.assertEqual(target, restore_abbreviation_definition_keys(source, target))
        self.assertIn(
            "abbreviation_definition_key_changed",
            structural_cardinality_failures(source, target),
        )

    def test_post_hy_normalizes_participant_without_changing_measure_name(self) -> None:
        source = (
            "Subjects with moderate AD will complete the Patient-Oriented "
            "Eczema Measure and patient-reported outcomes."
        )
        target = "中度特应性皮炎患者将完成患者导向型湿疹评估量表和患者报告结局。"

        normalized = normalize_post_hy_unit_output(source, target)

        self.assertEqual(
            "中度特应性皮炎受试者将完成患者导向型湿疹评估量表和患者报告结局。",
            normalized,
        )

    def test_post_hy_preserves_generic_patient_oriented_measure_name(self) -> None:
        source = "Subjects complete a patient-oriented scale."
        target = "患者完成患者导向量表。"

        self.assertEqual(
            "受试者完成患者导向量表。",
            normalize_post_hy_unit_output(source, target),
        )

    def test_post_hy_does_not_normalize_patient_when_source_has_patient_referent(
        self,
    ) -> None:
        source = "Subjects and patients will be enrolled in separate cohorts."
        target = "受试者和患者将分别纳入不同队列。"

        self.assertEqual(target, normalize_post_hy_unit_output(source, target))

    def test_post_hy_expands_elided_subject_clauses_without_free_rewrite(self) -> None:
        source = (
            "Subjects with a negative HBsAg and a positive anti-HBc or anti-HBs "
            "will have reflex testing for HBV-DNA. Subjects who have HBV-DNA "
            "above LLQ will be excluded."
        )
        target = (
            "筛选时HBsAg检测呈阴性但抗-HBc或抗-HBs检测结果呈阳性者需接受"
            "HBV-DNA检测；若其体内HBV-DNA水平高于LLQ则将被排除。"
        )

        self.assertEqual(
            "筛选时HBsAg检测呈阴性但抗-HBc或抗-HBs检测结果呈阳性的受试者"
            "需接受HBV-DNA检测；若受试者体内HBV-DNA水平高于LLQ则将被排除。",
            normalize_post_hy_unit_output(source, target),
        )

    def test_post_hy_does_not_rewrite_investigator_suffix(self) -> None:
        source = "Subjects will be assessed by the investigator."
        target = "研究者将对受试者进行评估。"

        self.assertEqual(target, normalize_post_hy_unit_output(source, target))

    def test_including_but_not_limited_to_preserves_negation_signal(self) -> None:
        result = evaluate_translation_fidelity(
            "Any cell-depleting agents including but not limited to rituximab.",
            "任何清除淋巴细胞的药物，包括但不限于利妥昔单抗。",
        )

        self.assertNotIn("negation_signal_missing", result.failure_codes)

    def test_true_must_not_omission_still_blocks(self) -> None:
        result = evaluate_translation_fidelity(
            "Participants must not receive SCS within 14 days.",
            "受试者在14天内接受SCS。",
        )

        self.assertIn("negation_signal_missing", result.failure_codes)

    def test_one_or_more_criteria_matches_at_least_one_item(self) -> None:
        result = evaluate_translation_fidelity(
            "Subjects do not meet 1 or more eligibility criteria.",
            "受试者未能满足至少一项入组资格要求。",
        )

        self.assertNotIn("numeric_tokens_changed", result.failure_codes)
        self.assertNotIn("comparison_direction_changed", result.failure_codes)

    def test_two_or_more_criteria_does_not_match_at_least_one_item(self) -> None:
        result = evaluate_translation_fidelity(
            "Subjects do not meet 2 or more eligibility criteria.",
            "受试者未能满足至少一项入组资格要求。",
        )

        self.assertIn("numeric_tokens_changed", result.failure_codes)

    def test_protocol_header_labels_are_not_clinical_abbreviations(self) -> None:
        result = evaluate_translation_fidelity(
            "STUDY DRUG: Oral Treprostinil",
            "研究药物：口服 Treprostinil",
        )

        self.assertNotIn("source_abbreviation_missing", result.failure_codes)

    def test_standard_degree_and_sae_chinese_equivalents_preserve_identity(self) -> None:
        degree = evaluate_translation_fidelity(
            "SPONSOR INVESTIGATOR: Lorinda Chung, MD, MS",
            "申办方研究者：Lorinda Chung，医学博士、MS。",
        )
        safety = evaluate_translation_fidelity(
            "All SAEs and AEs must be followed and CRF pages updated.",
            "所有严重不良事件和不良事件均须随访，并更新病例报告表（CRF）。",
        )

        self.assertNotIn("source_abbreviation_missing", degree.failure_codes)
        self.assertNotIn("source_abbreviation_missing", safety.failure_codes)

    def test_standard_ms_chinese_degree_preserves_identity(self) -> None:
        result = evaluate_translation_fidelity(
            "SPONSOR INVESTIGATOR: Lorinda Chung, MD, MS",
            "申办方研究者：Lorinda Chung，医学博士、理学硕士。",
        )

        self.assertNotIn("source_abbreviation_missing", result.failure_codes)

    def test_indefinite_article_duration_matches_chinese_one_year(self) -> None:
        result = evaluate_translation_fidelity(
            "❑ Much better now than a year ago "
            "❑ Somewhat better now than a year ago "
            "❑ About the same as one year ago "
            "❑ Somewhat worse now than a year ago "
            "❑ Much worse now than a year ago",
            "❑ 目前状况比一年前好很多 "
            "❑ 目前状况较一年前有所改善 "
            "❑ 目前状况与一年前大致相同 "
            "❑ 目前状况比一年前稍差一些 "
            "❑ 目前状况较一年前糟糕很多",
        )

        self.assertNotIn("numeric_tokens_changed", result.failure_codes)

    def test_cc_and_millilitre_are_equivalent_volume_units(self) -> None:
        result = evaluate_translation_fidelity(
            "Inject 1-2 cc of lidocaine.",
            "注入1至2毫升利多卡因。",
        )

        self.assertNotIn("unit_sequence_changed", result.failure_codes)
        self.assertNotIn("numeric_tokens_changed", result.failure_codes)

    def test_english_month_name_matches_numeric_chinese_month(self) -> None:
        result = evaluate_translation_fidelity(
            "Ann Rheum Dis. 2011 Apr;70(4):630-633. Epub 2010 Dec.",
            "《风湿病年鉴》2011年4月；70卷（4期）：630-633页。"
            "在线发表于2010年12月。",
        )

        self.assertNotIn("numeric_tokens_changed", result.failure_codes)

    def test_modal_may_is_not_normalized_as_calendar_month(self) -> None:
        result = evaluate_translation_fidelity(
            "An AE may include abnormal laboratory findings.",
            "不良事件可包括实验室检查异常。",
        )

        self.assertNotIn("numeric_tokens_changed", result.failure_codes)

    def test_compact_source_units_preserve_numeric_tokens(self) -> None:
        result = evaluate_translation_fidelity(
            "B. 2ml CryoVials or 2ml sample tube C. 4mm biopsy tool",
            "B. 2毫升冷冻管或2毫升样品管 C. 4毫米活检工具",
        )

        self.assertNotIn("numeric_tokens_changed", result.failure_codes)

    def test_bibliographic_elided_page_range_matches_expanded_chinese_range(self) -> None:
        result = evaluate_translation_fidelity(
            "Ann Rheum Dis. 2011 Apr;70(4):630-3. Epub 2010/12/07.",
            "《风湿病年鉴》2011年4月；70卷（4期）：630-633页。"
            "在线发表于2010年12月7日。",
        )

        self.assertNotIn("numeric_tokens_changed", result.failure_codes)

    def test_bibliographic_missing_epub_day_remains_blocked(self) -> None:
        result = evaluate_translation_fidelity(
            "Semin Arthritis Rheum. 2011 Apr;40(5):455-60. Epub 2010/09/25.",
            "《关节炎与风湿病学研讨会》2011年4月；40卷第5期：455-460页。"
            "在线发表于2010年9月。",
        )

        self.assertIn("numeric_tokens_changed", result.failure_codes)

    def test_mixed_subject_patient_sequence_must_remain_exact(self) -> None:
        source = "Subjects in cohort A and subjects in cohort B will counsel patients."
        correct = "A队列受试者和B队列受试者将为患者提供咨询。"
        wrong = "A队列受试者和B队列患者将为患者提供咨询。"

        self.assertFalse(participant_terminology_mismatch(source, correct))
        self.assertTrue(participant_terminology_mismatch(source, wrong))

    def test_eq_5d_5l_standard_chinese_name_preserves_numeric_semantics(self) -> None:
        result = evaluate_translation_fidelity(
            "EQ-5D-5L = EuroQoL 5 Dimension Health Questionnaire 5 Level;",
            "EQ-5D-5L = 欧洲五维健康量表五级版本；",
        )

        self.assertNotIn("numeric_tokens_changed", result.failure_codes)

    def test_eq_5d_5l_chinese_expansion_does_not_hide_visit_number_drift(self) -> None:
        source = "Change in EQ-5D-5L index score from baseline to Week 16."
        faithful = evaluate_translation_fidelity(
            source,
            "欧洲五维健康量表五级版本指数评分较基线至第16周的变化值。",
        )
        drifted = evaluate_translation_fidelity(
            source,
            "欧洲五维健康量表五级版本指数评分较基线至第12周的变化值。",
        )

        self.assertNotIn("numeric_tokens_changed", faithful.failure_codes)
        self.assertIn("numeric_tokens_changed", drifted.failure_codes)

    def test_hy_input_hash_covers_context_glossary_and_correction(self) -> None:
        from services.api.app import main as api_main

        captured: list[dict] = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps(
                    {
                        "choices": [
                            {
                                "finish_reason": "stop",
                                "message": {
                                    "content": (
                                        "[[CMS_SEG_0001]]\n译文\n[[/CMS_SEG_0001]]"
                                    )
                                },
                            }
                        ]
                    }
                ).encode()

        def fake_urlopen(request, timeout):
            del timeout
            captured.append(json.loads(request.data.decode()))
            return Response()

        source = "[[CMS_SEG_0001]]\nSource.\n[[/CMS_SEG_0001]]"
        with (
            _controlled_translation_body_role(api_main),
            patch("urllib.request.urlopen", side_effect=fake_urlopen),
        ):
            base = api_main._hy_mt2_translator_adapter(
                source, "glossary-a", "ch1", "c1", "context-a", ""
            )
            corrected = api_main._hy_mt2_translator_adapter(
                source,
                "glossary-a",
                "ch1",
                "c1",
                "context-a",
                "missing_unit_output:1",
            )
            changed_context = api_main._hy_mt2_translator_adapter(
                source, "glossary-a", "ch1", "c1", "context-b", ""
            )
        self.assertEqual(3, len(captured))
        self.assertNotEqual(base.input_hash, corrected.input_hash)
        self.assertNotEqual(base.input_hash, changed_context.input_hash)
        self.assertIn(
            "subjects/participants 必须统一译为“受试者”",
            captured[0]["messages"][0]["content"],
        )

    def test_hy_prompt_uses_only_source_specific_inclusive_age_bounds(self) -> None:
        from services.api.app import main as api_main

        captured: list[dict] = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps(
                    {
                        "choices": [
                            {
                                "finish_reason": "stop",
                                "message": {
                                    "content": (
                                        "[[CMS_SEG_0001]]\n译文\n[[/CMS_SEG_0001]]"
                                    )
                                },
                            }
                        ]
                    }
                ).encode()

        def fake_urlopen(request, timeout):
            del timeout
            captured.append(json.loads(request.data.decode()))
            return Response()

        inclusive_source = (
            "[[CMS_SEG_0001]]\n"
            "Age 2. 20-65 years old (both included) at screening."
            "\n[[/CMS_SEG_0001]]"
        )
        ordinary_source = "[[CMS_SEG_0001]]\nNo age range is stated.\n[[/CMS_SEG_0001]]"
        with (
            _controlled_translation_body_role(api_main),
            patch("urllib.request.urlopen", side_effect=fake_urlopen),
        ):
            api_main._hy_mt2_translator_adapter(
                inclusive_source, "glossary-a", "ch1", "c1"
            )
            api_main._hy_mt2_translator_adapter(
                ordinary_source, "glossary-a", "ch1", "c2"
            )

        inclusive_prompt = captured[0]["messages"][0]["content"]
        ordinary_prompt = captured[1]["messages"][0]["content"]
        self.assertIn("20至65周岁（含两端值）", inclusive_prompt)
        self.assertIn("不得使用“65周岁以下”", inclusive_prompt)
        self.assertNotIn("18至75周岁", inclusive_prompt)
        self.assertNotIn("【本源文年龄边界】", ordinary_prompt)

    def test_flash_input_hash_covers_correction_note(self) -> None:
        from services.api.app import main as api_main

        class Provider:
            def run(self, envelope):
                return {
                    "passed": True,
                    "failure_codes": [],
                    "integrated_text": ("[[CMS_SEG_0001]]\n译文\n[[/CMS_SEG_0001]]"),
                }

        with patch.object(
            api_main, "configured_ai_provider_from_env", return_value=Provider()
        ):
            base = api_main._flash_qc_runner_adapter("translated", "source", "")
            corrected = api_main._flash_qc_runner_adapter(
                "translated", "source", "missing_unit_output:1"
            )
        self.assertNotEqual(base.qc_input_hash, corrected.qc_input_hash)


class CurrentContractReuseTests(unittest.TestCase):
    def test_missing_unit_targets_fail_closed_instead_of_paragraph_guessing(
        self,
    ) -> None:
        units = (
            TranslationUnit(ordinal=1, text="Source one."),
            TranslationUnit(ordinal=2, text="Source two."),
        )
        with self.assertRaisesRegex(
            ChapterTranslationPipelineError, "must be retranslated"
        ):
            reconstruct_unit_map("译文一\n\n译文二", {}, units)

    def test_complete_unit_targets_are_reused_exactly(self) -> None:
        units = (
            TranslationUnit(ordinal=1, text="Source one."),
            TranslationUnit(ordinal=2, text="Source two."),
        )
        self.assertEqual(
            {1: "译文一", 2: "译文二"},
            reconstruct_unit_map(
                "ignored reassembled text",
                {"1": "译文一", "2": "译文二"},
                units,
            ),
        )

    def test_extra_or_empty_unit_targets_fail_closed(self) -> None:
        units = (
            TranslationUnit(ordinal=1, text="Source one."),
            TranslationUnit(ordinal=2, text="Source two."),
        )
        for stored in (
            {"1": "译文一", "2": ""},
            {"1": "译文一", "2": "译文二", "3": "额外译文"},
        ):
            with self.subTest(stored=stored):
                with self.assertRaisesRegex(
                    ChapterTranslationPipelineError, "must be retranslated"
                ):
                    reconstruct_unit_map("ignored", stored, units)


# ---------------------------------------------------------------------------
# Point 7: Flash marker preservation, stripping, one corrective pass
# ---------------------------------------------------------------------------


class FlashAlignedIntegrationTests(unittest.TestCase):
    UNITS = (
        TranslationUnit(ordinal=1, text="First source unit."),
        TranslationUnit(ordinal=2, text="Second source unit."),
    )
    DRAFTS = {1: "第一单元译文", 2: "第二单元译文"}

    def _good_flash(self):
        def flash(translated, source, correction_note=""):
            from services.api.app.chapter_translation_pipeline import (
                extract_draft_map_from_envelope,
            )

            drafts = extract_draft_map_from_envelope(translated)
            integrated = "\n\n".join(
                f"[[CMS_SEG_{o:04d}]]\n{d}\n[[/CMS_SEG_{o:04d}]]"
                for o, d in sorted(drafts.items())
            )
            return _flash_result(True, integrated)

        return flash

    def test_markers_preserved_then_stripped_from_final(self) -> None:
        outcome = integrate_units_with_flash(
            self._good_flash(), units=self.UNITS, target_map=self.DRAFTS
        )
        self.assertTrue(outcome.passed)
        self.assertEqual(1, outcome.attempts)
        self.assertFalse(contains_unit_markers(outcome.final_text))
        self.assertIn("第一单元译文", outcome.final_text)
        self.assertIn("第二单元译文", outcome.final_text)

    def test_one_corrective_pass_on_marker_failure(self) -> None:
        calls: list[str] = []

        def flaky_flash(translated, source, correction_note=""):
            from services.api.app.chapter_translation_pipeline import (
                extract_draft_map_from_envelope,
            )

            calls.append(correction_note)
            drafts = extract_draft_map_from_envelope(translated)
            keep = sorted(drafts) if correction_note else sorted(drafts)[:1]
            integrated = "\n\n".join(
                f"[[CMS_SEG_{o:04d}]]\n{drafts[o]}\n[[/CMS_SEG_{o:04d}]]" for o in keep
            )
            return _flash_result(True, integrated)

        outcome = integrate_units_with_flash(
            flaky_flash, units=self.UNITS, target_map=self.DRAFTS
        )
        self.assertTrue(outcome.passed)
        self.assertEqual(2, outcome.attempts)
        self.assertEqual(2, len(calls))
        self.assertIn("missing_unit_output:2", calls[1])
        self.assertFalse(contains_unit_markers(outcome.final_text))

    def test_second_flash_drift_falls_back_to_valid_hy_draft(self) -> None:
        calls: list[str] = []

        def bad_flash(translated, source, correction_note=""):
            from services.api.app.chapter_translation_pipeline import (
                extract_draft_map_from_envelope,
            )

            calls.append(correction_note)
            drafts = extract_draft_map_from_envelope(translated)
            first = sorted(drafts)[0]
            integrated = (
                f"[[CMS_SEG_{first:04d}]]\n{drafts[first]}\n[[/CMS_SEG_{first:04d}]]"
            )
            return _flash_result(True, integrated)

        outcome = integrate_units_with_flash(
            bad_flash, units=self.UNITS, target_map=self.DRAFTS
        )
        self.assertTrue(outcome.passed)
        self.assertEqual(2, outcome.attempts)
        self.assertTrue(outcome.fallback_used)
        self.assertEqual((), outcome.failure_codes)
        self.assertIn(
            "flash_integration_drift_fallback_to_hy",
            outcome.diagnostic_codes,
        )
        self.assertIn("missing_unit_output:2", outcome.diagnostic_codes)
        self.assertIn("第二单元译文", outcome.final_text)

    def test_second_flash_failure_blocks_when_hy_draft_is_invalid(self) -> None:
        def bad_flash(translated, source, correction_note=""):
            return _flash_result(
                True,
                "[[CMS_SEG_0001]]\n第一单元译文\n[[/CMS_SEG_0001]]",
            )

        outcome = integrate_units_with_flash(
            bad_flash,
            units=self.UNITS,
            target_map={1: "第一单元译文", 2: ""},
        )
        self.assertFalse(outcome.passed)
        self.assertFalse(outcome.fallback_used)
        self.assertIn("missing_unit_output:2", outcome.failure_codes)

    def test_model_reported_failure_is_advisory_when_hy_is_deterministically_valid(
        self,
    ) -> None:
        outcome = integrate_units_with_flash(
            lambda translated, source, correction_note="": _flash_result(
                False, "", ("MISSING_CONTENT",)
            ),
            units=self.UNITS,
            target_map=self.DRAFTS,
        )
        self.assertTrue(outcome.passed)
        self.assertTrue(outcome.fallback_used)
        self.assertEqual((), outcome.failure_codes)
        self.assertIn(
            "flash_qc_advisory:MISSING_CONTENT",
            outcome.diagnostic_codes,
        )

    def test_model_reported_defect_never_triggers_flash_body_correction(self) -> None:
        calls: list[str] = []

        def correcting_flash(translated, source, correction_note=""):
            calls.append(correction_note)
            integrated = "\n\n".join(
                f"[[CMS_SEG_{o:04d}]]\n{text}\n[[/CMS_SEG_{o:04d}]]"
                for o, text in sorted(self.DRAFTS.items())
            )
            if not correction_note:
                return _flash_result(False, integrated, ("REVIEW_REQUIRED",))
            return _flash_result(True, integrated)

        outcome = integrate_units_with_flash(
            correcting_flash, units=self.UNITS, target_map=self.DRAFTS
        )
        self.assertTrue(outcome.passed)
        self.assertEqual(1, outcome.attempts)
        self.assertEqual(1, len(calls))
        self.assertEqual(
            "第一单元译文\n\n第二单元译文",
            outcome.final_text,
        )
        self.assertIn(
            "flash_qc_advisory:REVIEW_REQUIRED",
            outcome.diagnostic_codes,
        )

    def test_flash_semantic_rewrite_never_becomes_final_body(self) -> None:
        calls: list[str] = []

        def rewriting_flash(translated, source, correction_note=""):
            calls.append(correction_note)
            integrated = (
                "[[CMS_SEG_0001]]\n第一单元改写稿\n[[/CMS_SEG_0001]]\n\n"
                "[[CMS_SEG_0002]]\n第二单元译文\n[[/CMS_SEG_0002]]"
            )
            return _flash_result(True, integrated)

        outcome = integrate_units_with_flash(
            rewriting_flash, units=self.UNITS, target_map=self.DRAFTS
        )

        self.assertTrue(outcome.passed)
        self.assertEqual(2, outcome.attempts)
        self.assertEqual(2, len(calls))
        self.assertTrue(outcome.fallback_used)
        self.assertEqual("第一单元译文\n\n第二单元译文", outcome.final_text)
        self.assertNotIn("第一单元改写稿", outcome.final_text)
        self.assertIn(
            "unit_1:flash_qc_body_mutation_forbidden",
            outcome.diagnostic_codes,
        )


# ---------------------------------------------------------------------------
# Point 8: unit-level unsupported addition is not masked by a legit unit
# ---------------------------------------------------------------------------


class UnitLevelFidelityMaskingTests(unittest.TestCase):
    def test_unsupported_efficacy_caught_per_unit(self) -> None:
        units = (
            TranslationUnit(ordinal=1, text="The efficacy of the regimen is compared."),
            TranslationUnit(
                ordinal=2,
                text="The visit schedule may interfere with evaluation of the IMP.",
            ),
        )
        targets = {
            1: "比较该方案的疗效。",
            2: "访视安排可能干扰研究药物疗效评估。",
        }
        codes = evaluate_translation_fidelity_aligned_units(units, targets)
        self.assertIn("unit_2:unsupported_medical_concept_added", codes)
        self.assertNotIn("unit_1:unsupported_medical_concept_added", codes)

    def test_treatment_assessment_licenses_chinese_treatment_effect_wording(
        self,
    ) -> None:
        result = evaluate_translation_fidelity(
            "A condition that could interfere with assessment of the treatment.",
            "可能影响治疗效果评估的疾病。",
        )
        self.assertNotIn(
            "unsupported_medical_concept_added",
            result.failure_codes,
        )

    def test_structural_cardinality_checked_per_unit(self) -> None:
        units = (
            TranslationUnit(ordinal=1, text="• Alpha.\n• Beta.\n• Gamma."),
            TranslationUnit(ordinal=2, text="Plain prose without lists."),
        )
        targets = {1: "• 甲。\n• 乙。", 2: "没有列表的散文。"}
        codes = evaluate_translation_fidelity_aligned_units(units, targets)
        self.assertIn("unit_1:bullet_cardinality_changed", codes)
        self.assertNotIn("unit_2:bullet_cardinality_changed", codes)

    def test_week_number_is_not_misread_as_a_numbered_criterion(self) -> None:
        units = (
            TranslationUnit(
                ordinal=1,
                text=(
                    "• Percent change in EASI score from baseline to Week 16. "
                    "Exploratory endpoint."
                ),
            ),
        )
        targets = {1: "• 从基线至第16周EASI评分的百分比变化。探索性终点。"}
        codes = evaluate_translation_fidelity_aligned_units(units, targets)
        self.assertNotIn("unit_1:numbered_criterion_cardinality_changed", codes)

    def test_numbered_criterion_before_chinese_text_preserves_cardinality(self) -> None:
        units = (
            TranslationUnit(
                ordinal=1,
                text="Informed consent 1. Signed and dated informed consent.",
            ),
        )
        targets = {1: "知情同意 1. 已签署并注明日期的知情同意书。"}
        codes = evaluate_translation_fidelity_aligned_units(units, targets)
        self.assertNotIn("unit_1:numbered_criterion_cardinality_changed", codes)

    def test_arabic_numbered_step_matches_chinese_numbered_step(self) -> None:
        units = (
            TranslationUnit(
                ordinal=1,
                text="1. Close the wound with nylon sutures.",
            ),
        )
        targets = {1: "一、使用尼龙缝线缝合伤口。"}
        codes = evaluate_translation_fidelity_aligned_units(units, targets)
        self.assertNotIn("unit_1:numbered_criterion_cardinality_changed", codes)


# ---------------------------------------------------------------------------
# Point 9: confirmed v10 defects remain blocked
# ---------------------------------------------------------------------------


class TrueDefectBlockingTests(unittest.TestCase):
    def test_ascii_integer_range_upper_bound_omission_blocked(self) -> None:
        result = evaluate_translation_fidelity(
            "Participants aged 18-65 years are eligible.",
            "年龄18岁的受试者可入组。",
        )
        self.assertIn("numeric_tokens_changed", result.failure_codes)

    def test_ascii_decimal_range_upper_bound_omission_blocked(self) -> None:
        result = evaluate_translation_fidelity(
            "Score 1.5-3.0 is required.",
            "评分须为1.5。",
        )
        self.assertIn("numeric_tokens_changed", result.failure_codes)

    def test_ascii_range_with_both_bounds_preserved_passes_numeric_gate(
        self,
    ) -> None:
        result = evaluate_translation_fidelity(
            "Participants aged 18-65 years are eligible.",
            "年龄18至65岁的受试者可入组。",
        )
        self.assertNotIn("numeric_tokens_changed", result.failure_codes)

    def test_negative_number_sign_is_preserved(self) -> None:
        faithful = evaluate_translation_fidelity(
            "The permitted change is -1.5 to 2.0.",
            "允许的变化范围为-1.5至2.0。",
        )
        drifted = evaluate_translation_fidelity(
            "The permitted change is -1.5 to 2.0.",
            "允许的变化范围为1.5至2.0。",
        )
        self.assertNotIn("numeric_tokens_changed", faithful.failure_codes)
        self.assertIn("numeric_tokens_changed", drifted.failure_codes)

    def test_unicode_minus_sign_is_preserved(self) -> None:
        faithful = evaluate_translation_fidelity(
            "The permitted change is −1.5 to 2.0.",
            "允许的变化范围为-1.5至2.0。",
        )
        drifted = evaluate_translation_fidelity(
            "The permitted change is −1.5 to 2.0.",
            "允许的变化范围为1.5至2.0。",
        )
        self.assertNotIn("numeric_tokens_changed", faithful.failure_codes)
        self.assertIn("numeric_tokens_changed", drifted.failure_codes)

    def test_strict_greater_than_cannot_become_inclusive(self) -> None:
        result = evaluate_translation_fidelity(
            "Participants must be more than 18 years old.",
            "受试者年龄必须为18岁及以上。",
        )
        self.assertIn("comparison_direction_changed", result.failure_codes)

    def test_strict_greater_than_preserved_passes_comparator_gate(self) -> None:
        result = evaluate_translation_fidelity(
            "Participants must be more than 18 years old.",
            "受试者年龄必须大于18岁。",
        )
        self.assertNotIn("comparison_direction_changed", result.failure_codes)

    def test_strict_less_than_cannot_become_inclusive(self) -> None:
        result = evaluate_translation_fidelity(
            "Participants must be less than 18 years old.",
            "受试者年龄必须为18岁及以下。",
        )
        self.assertIn("comparison_direction_changed", result.failure_codes)

    def test_citation_marker_omission_blocked(self) -> None:
        result = evaluate_translation_fidelity(
            "diagnosis of AD by the Hanifin and Rajka (1980) criteria ( ( 62 ) and Appendix 3 ).",
            "根据Hanifin和Rajka（1980年）AD标准（附录3）诊断。",
        )
        self.assertIn("numeric_tokens_changed", result.failure_codes)

    def test_at_least_weakening_blocked(self) -> None:
        result = evaluate_translation_fidelity(
            "daily use of a TCS for at least 28 days",
            "每日使用外用皮质类固醇连续28天",
        )
        self.assertIn("comparison_direction_changed", result.failure_codes)

    def test_weeks_to_days_blocked(self) -> None:
        result = evaluate_translation_fidelity(
            "Use of tanning beds within 4 weeks prior to baseline.",
            "基线前4天内使用日光浴床。",
        )
        self.assertIn("unit_sequence_changed", result.failure_codes)

    def test_tci_category_narrowing_blocked(self) -> None:
        result = evaluate_translation_fidelity(
            "inadequate response to treatment with TCS (±TCI as appropriate)",
            "对外用皮质类固醇治疗反应不佳（±酌情联合他克莫司软膏）",
        )
        self.assertIn("source_abbreviation_missing", result.failure_codes)

    def test_tcs_and_tci_class_swap_is_blocked_by_controlled_terms(self) -> None:
        result = evaluate_translation_fidelity(
            "inadequate response to treatment with TCS (±TCI as appropriate)",
            "对钙调神经磷酸酶抑制剂类（±TCI）治疗反应不佳",
        )
        self.assertIn(
            "controlled_term_missing:topical_corticosteroid",
            result.failure_codes,
        )

    def test_comparator_reversal_blocked(self) -> None:
        result = evaluate_translation_fidelity(
            "EASI score ≥12 at screening.",
            "筛选时EASI评分<12。",
        )
        self.assertIn("comparison_direction_changed", result.failure_codes)


# ---------------------------------------------------------------------------
# Point 10: precision fixes pass; nearby true defects still fail
# ---------------------------------------------------------------------------


class PrecisionFixTests(unittest.TestCase):
    def test_en_dash_age_range_passes(self) -> None:
        result = evaluate_translation_fidelity(
            "Age 2. 18–75 years old (both included) at screening.",
            "年龄 2. 筛选时18至75周岁（含两端值）。",
        )
        self.assertEqual((), result.failure_codes)

    def test_explicitly_inclusive_age_range_cannot_become_exclusive(self) -> None:
        result = evaluate_translation_fidelity(
            "Age 2. 18–75 years old (both included) at screening.",
            "年龄 2. 筛选时年龄为18周岁及以上至75周岁以下。",
        )
        self.assertIn("range_inclusivity_changed", result.failure_codes)

    def test_minimum_scores_out_of_days_chinese_word_order_passes(self) -> None:
        result = evaluate_translation_fidelity(
            "A minimum of 4 scores out of the 7 days is required.",
            "至少需获取这7天中的4日评分值。",
        )
        self.assertNotIn("comparison_direction_changed", result.failure_codes)
        self.assertNotIn("unit_sequence_changed", result.failure_codes)

    def test_minimum_scores_days_first_chinese_word_order_passes(self) -> None:
        result = evaluate_translation_fidelity(
            "A minimum of 4 scores out of the 7 days is required.",
            "这7天中至少需有4天的评分数据。",
        )
        self.assertNotIn("comparison_direction_changed", result.failure_codes)
        self.assertNotIn("unit_sequence_changed", result.failure_codes)

    def test_suffix_comparator_is_paired_with_preceding_number(self) -> None:
        result = evaluate_translation_fidelity(
            "The score must be ≥4 at baseline.",
            "基线时评分需达到4分及以上。",
        )
        self.assertNotIn("comparison_direction_changed", result.failure_codes)

    def test_redundant_chinese_inclusive_age_comparator_is_equivalent(self) -> None:
        result = evaluate_translation_fidelity(
            "A female subject aged ≥12 years.",
            "年满12周岁及以上的女受试者。",
        )
        self.assertNotIn("comparison_direction_changed", result.failure_codes)

    def test_redundant_chinese_duration_comparator_is_equivalent(self) -> None:
        result = evaluate_translation_fidelity(
            "History of AD for ≥1 year.",
            "特应性皮炎病史已满1年及以上。",
        )
        self.assertNotIn("comparison_direction_changed", result.failure_codes)

    def test_redundant_chinese_minimum_duration_wording_is_equivalent(self) -> None:
        result = evaluate_translation_fidelity(
            "Treatment was applied for at least 28 days.",
            "治疗用药时长至少满28天。",
        )
        self.assertNotIn("comparison_direction_changed", result.failure_codes)

    def test_chinese_duration_number_word_matches_arabic_source(self) -> None:
        result = evaluate_translation_fidelity(
            "Treatment was documented in the past 1 year.",
            "治疗记录见于过去一年内。",
        )
        self.assertNotIn("numeric_tokens_changed", result.failure_codes)
        self.assertNotIn("unit_sequence_changed", result.failure_codes)

    def test_different_chinese_duration_number_remains_blocked(self) -> None:
        result = evaluate_translation_fidelity(
            "Treatment was documented in the past 1 year.",
            "治疗记录见于过去两年内。",
        )
        self.assertIn("numeric_tokens_changed", result.failure_codes)

    def test_iga_approved_chinese_expansion_preserves_scale_identity(self) -> None:
        result = evaluate_translation_fidelity(
            "comparable to IGA 0=clear to 2=mild",
            "相当于研究者整体评估评分0分=无皮损至2分=轻度",
        )
        self.assertNotIn("source_abbreviation_missing", result.failure_codes)

    def test_iv_abbreviation_may_use_standard_chinese_route(self) -> None:
        result = evaluate_translation_fidelity(
            "IV or intramuscular antibiotics are permitted.",
            "允许使用静脉或肌肉注射抗生素。",
        )
        self.assertNotIn("source_abbreviation_missing", result.failure_codes)

    def test_abbreviation_only_tcs_reference_may_remain_tcs(self) -> None:
        result = evaluate_translation_fidelity(
            "Subjects are inadequate responders to TCS treatment.",
            "受试者对TCS治疗应答不佳。",
        )
        self.assertNotIn(
            "controlled_term_missing:topical_corticosteroid",
            result.failure_codes,
        )

    def test_expanded_tcs_source_cannot_be_reduced_to_abbreviation_only(self) -> None:
        result = evaluate_translation_fidelity(
            "Subjects receive topical corticosteroid treatment.",
            "受试者接受TCS治疗。",
        )
        self.assertIn(
            "controlled_term_missing:topical_corticosteroid",
            result.failure_codes,
        )

    def test_minimum_scores_out_of_days_still_blocks_wrong_count(self) -> None:
        result = evaluate_translation_fidelity(
            "A minimum of 4 scores out of the 7 days is required.",
            "至少需获取这7天中的3日评分值。",
        )
        self.assertIn("numeric_tokens_changed", result.failure_codes)

    def test_man_minimum_duration_passes(self) -> None:
        result = evaluate_translation_fidelity(
            "in remission and completed radical treatment at least 12 months ago",
            "处于缓解期且完成根治性治疗满12个月",
        )
        self.assertEqual((), result.failure_codes)

    def test_man_wrong_duration_still_fails(self) -> None:
        result = evaluate_translation_fidelity(
            "in remission and completed radical treatment at least 12 months ago",
            "处于缓解期且完成根治性治疗满10个月",
        )
        self.assertIn("numeric_tokens_changed", result.failure_codes)

    def test_uln_word_order_passes(self) -> None:
        result = evaluate_translation_fidelity(
            "ALT or AST level ≥2.0 times the ULN at screening.",
            "筛选时ALT或AST水平≥正常值上限的2倍。",
        )
        self.assertEqual((), result.failure_codes)

    def test_ius_equivalent_passes(self) -> None:
        result = evaluate_translation_fidelity(
            "Use of an IUS is acceptable for contraception.",
            "可使用宫内节育系统（IUS）避孕。",
        )
        self.assertEqual((), result.failure_codes)

    def test_generic_ius_cannot_be_narrowed_to_levonorgestrel(self) -> None:
        result = evaluate_translation_fidelity(
            "Use of an IUS is acceptable for contraception.",
            "可使用释放左炔诺孕酮的宫内系统避孕。",
        )
        self.assertIn("ius_category_narrowed", result.failure_codes)

    def test_important_side_effects_cannot_be_upcoded_to_severe(self) -> None:
        result = evaluate_translation_fidelity(
            "Important side effects or safety risks must be assessed.",
            "必须评估严重不良反应或安全性风险。",
        )
        self.assertIn(
            "important_side_effect_severity_upcoded",
            result.failure_codes,
        )

    def test_tubal_occlusion_cannot_be_narrowed_to_ligation(self) -> None:
        result = evaluate_translation_fidelity(
            "Bilateral tubal occlusion is acceptable.",
            "可接受双侧输卵管结扎术。",
        )
        self.assertIn(
            "bilateral_tubal_occlusion_narrowed_to_ligation",
            result.failure_codes,
        )

    def test_same_sex_partner_omission_is_blocked(self) -> None:
        result = evaluate_translation_fidelity(
            "Acceptable options include a same-sex partner or vasectomized partner.",
            "可接受已行输精管结扎术的伴侣。",
        )
        self.assertIn("same_sex_partner_omitted", result.failure_codes)

    def test_abstinence_current_partner_condition_cannot_be_inverted(self) -> None:
        result = evaluate_translation_fidelity(
            "Abstinence is acceptable when it is not just being without a current partner.",
            "仅当受试者禁欲且当前并无性伴侣时方可接受。",
        )
        self.assertIn(
            "abstinence_partner_condition_inverted",
            result.failure_codes,
        )

    def test_abstinence_explicit_negation_of_partner_absence_passes(self) -> None:
        result = evaluate_translation_fidelity(
            "Abstinence is acceptable when it is not just being without a current partner.",
            "仅当该方式符合惯常生活模式，且并非因暂时无伴侣所致时方可接受。",
        )
        self.assertNotIn(
            "abstinence_partner_condition_inverted",
            result.failure_codes,
        )

    def test_en_dash_normalization(self) -> None:
        self.assertIn("18 to 65", _normalize_en_dash_ranges("Ages 18–65 years."))
        self.assertIn("2 to 4", _normalize_en_dash_ranges("Weeks 2-4."))


# ---------------------------------------------------------------------------
# Point 11: contract bump invalidates stale reuse, old rows immutable
# ---------------------------------------------------------------------------


class ContractIdentityTests(unittest.TestCase):
    @staticmethod
    def _previous_translation_contract_fingerprint() -> str:
        with (
            patch.object(
                pipeline_module,
                "HY_MT2_PROMPT_VERSION",
                "hy_mt2_chapter_translation_v0_29_reference_metadata_fidelity",
            ),
            patch.object(
                pipeline_module,
                "TRANSLATION_ALIGNMENT_CONTRACT",
                "cms_seg_aligned_units_v35_source_bound_blocked_projection",
            ),
        ):
            return pipeline_module.translation_contract_fingerprint()

    def test_prompt_versions_bumped(self) -> None:
        self.assertEqual(
            "cms_seg_aligned_units_v36_protocol_heading_abbreviation_stopwords",
            TRANSLATION_ALIGNMENT_CONTRACT,
        )
        self.assertEqual(
            "hy_mt2_chapter_translation_v0_30_protocol_heading_abbreviation_stopwords",
            HY_MT2_PROMPT_VERSION,
        )
        self.assertEqual(
            "post_hy_v0_6_inline_crf_restoration",
            POST_HY_NORMALIZATION_VERSION,
        )
        self.assertEqual(
            "flash_integration_qc_v0_6_traceable_advisory",
            FLASH_QC_PROMPT_VERSION,
        )
        self.assertEqual(
            "composite_chapter_translation_v0_4_hy_body_only",
            COMPOSITE_TRANSLATION_PROMPT_VERSION,
        )
        for stale in (
            "hy_mt2_chapter_translation_v0_1",
            "hy_mt2_chapter_translation_v0_2_aligned_units",
            "hy_mt2_chapter_translation_v0_15_subject_terminology",
            "hy_mt2_chapter_translation_v0_29_reference_metadata_fidelity",
            "cms_seg_aligned_units_v3_semantic",
            "cms_seg_aligned_units_v35_source_bound_blocked_projection",
            "flash_integration_qc_v0_2_full_chapter",
            "flash_integration_qc_v0_3_aligned_units",
            "flash_integration_qc_v0_4_aligned_units",
            "composite_chapter_translation_v0_1",
            "composite_chapter_translation_v0_2",
            "composite_chapter_translation_v0_3",
        ):
            self.assertNotIn(
                stale,
                (
                    HY_MT2_PROMPT_VERSION,
                    TRANSLATION_ALIGNMENT_CONTRACT,
                    FLASH_QC_PROMPT_VERSION,
                    COMPOSITE_TRANSLATION_PROMPT_VERSION,
                ),
            )

    def test_contract_hashes_track_glossary_and_downstream_contract(self) -> None:
        with patch(
            "services.api.app.regulatory_translation_glossary."
            "regulatory_translation_glossary_hash",
            return_value="glossary-v1",
        ):
            downstream_v1 = pipeline_module.translation_contract_fingerprint()
        with patch(
            "services.api.app.regulatory_translation_glossary."
            "regulatory_translation_glossary_hash",
            return_value="glossary-v2",
        ):
            downstream_v2 = pipeline_module.translation_contract_fingerprint()

        self.assertNotEqual(downstream_v1, downstream_v2)
        self.assertNotEqual(
            composite_translation_contract_hash(
                downstream_fingerprint=downstream_v1,
            ),
            composite_translation_contract_hash(
                downstream_fingerprint=downstream_v2,
            ),
        )

    def test_composite_only_prompt_bump_changes_candidate_contract(self) -> None:
        from services.api.app import writing_reference as writing_reference_module

        current = writing_reference_module.composite_translation_contract_hash()
        with patch.object(
            writing_reference_module,
            "COMPOSITE_TRANSLATION_PROMPT_VERSION",
            "composite_chapter_translation_future_contract",
        ):
            bumped = writing_reference_module.composite_translation_contract_hash()
        self.assertNotEqual(current, bumped)
        self.assertEqual(
            TRANSLATION_CONTRACT_FINGERPRINT,
            pipeline_module.TRANSLATION_CONTRACT_FINGERPRINT,
        )

    def test_v36_contract_bump_propagates_plan_chunk_and_candidate_identity(
        self,
    ) -> None:
        source = "Participants must not receive systemic corticosteroids for 14 days."
        span = SimpleNamespace(span_id="s1", source_text=source)
        plan = DocumentPlanResult(
            flash_plan=None,  # type: ignore[arg-type]
            chapters=(("ch1", "Eligibility", "eligibility", ("s1",)),),
            document_role="protocol",
            ambiguity_codes=(),
        )
        base_plan = dict(
            artifact_id="artifact_1",
            extraction_revision="r1",
            planner_model="deepseek-v4-flash",
            planner_prompt_version="flash_toc_planning_v0_2_segment_ranges",
            document_sha256="d" * 64,
        )
        current_plan_identity = pipeline_module._planner_contract_fingerprint(
            **base_plan,
            translation_contract=TRANSLATION_CONTRACT_FINGERPRINT,
        )
        current_chunk = list(build_chunks_from_plan(plan, (span,))[0].values())[0][0]
        current_candidate = composite_translation_contract_hash(
            downstream_fingerprint=TRANSLATION_CONTRACT_FINGERPRINT,
        )
        current_candidate_id = (
            batch_module.WritingReferenceTranslationBatchService
            ._chapter_translation_id(
                "proj_1",
                current_plan_identity,
                "ch1",
            )
        )

        previous_contract = self._previous_translation_contract_fingerprint()
        with patch.object(
            pipeline_module, "TRANSLATION_CONTRACT_FINGERPRINT", previous_contract
        ):
            previous_chunk = list(
                build_chunks_from_plan(plan, (span,))[0].values()
            )[0][0]
        previous_plan_identity = pipeline_module._planner_contract_fingerprint(
            **base_plan,
            translation_contract=previous_contract,
        )
        previous_candidate = composite_translation_contract_hash(
            downstream_fingerprint=previous_contract,
        )
        with patch.object(
            batch_module,
            "COMPOSITE_TRANSLATION_CONTRACT_HASH",
            previous_candidate,
        ):
            previous_candidate_id = (
                batch_module.WritingReferenceTranslationBatchService
                ._chapter_translation_id(
                    "proj_1",
                    previous_plan_identity,
                    "ch1",
                )
            )

        self.assertNotEqual(TRANSLATION_CONTRACT_FINGERPRINT, previous_contract)
        self.assertNotEqual(current_plan_identity, previous_plan_identity)
        self.assertNotEqual(
            current_chunk.chunk_fingerprint,
            previous_chunk.chunk_fingerprint,
        )
        self.assertNotEqual(current_candidate, previous_candidate)
        self.assertNotEqual(current_candidate_id, previous_candidate_id)

    def test_chunk_fingerprint_includes_translation_contract(self) -> None:
        source = "Chunk fingerprint probe text."
        span = SimpleNamespace(span_id="s1", source_text=source)
        plan = DocumentPlanResult(
            flash_plan=None,  # type: ignore[arg-type]
            chapters=(("ch1", "T", "eligibility", ("s1",)),),
            document_role="protocol",
            ambiguity_codes=(),
        )
        current = list(build_chunks_from_plan(plan, (span,))[0].values())[0]
        with patch.object(
            pipeline_module, "TRANSLATION_CONTRACT_FINGERPRINT", "stale-contract"
        ):
            stale = list(build_chunks_from_plan(plan, (span,))[0].values())[0]
        self.assertNotEqual(current[0].chunk_fingerprint, stale[0].chunk_fingerprint)

    def _integration(
        self, fingerprint: str, integration_id: str, plan_id: str
    ) -> ChapterIntegrationResult:
        return ChapterIntegrationResult(
            integration_id=integration_id,
            plan_id=plan_id,
            project_id="proj_1",
            artifact_id="artifact_1",
            chapter_id="ch1",
            chunk_ids=["c1"],
            chunk_hashes=["h1"],
            integrated_chinese_text="译文",
            integrated_text_sha256="hash",
            flash_model="deepseek-v4-flash",
            flash_prompt_version="flash_integration_qc_v0_2_full_chapter",
            flash_input_hash="in",
            flash_output_hash="out",
            fidelity_status="passed",
            translation_contract_fingerprint=fingerprint,
            created_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
        )

    def test_stale_integration_not_reused_and_old_row_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = WritingReferenceRepository(Path(tmp) / "wr.sqlite3")
            previous_contract = (
                self._previous_translation_contract_fingerprint()
            )
            old = self._integration(
                previous_contract,
                "integration_old",
                "plan_old",
            )
            repo.save_chapter_integration_result(
                old, idempotency_key="integration:plan_old:ch1:old"
            )
            # Current-contract lookup on the old plan identity must NOT
            # return the stale row.
            self.assertIsNone(
                repo.chapter_integration_result(
                    "proj_1",
                    "plan_old",
                    "ch1",
                    translation_contract_fingerprint=TRANSLATION_CONTRACT_FINGERPRINT,
                )
            )
            # The old row is untouched and still retrievable without a filter.
            retained = repo.chapter_integration_result("proj_1", "plan_old", "ch1")
            self.assertIsNotNone(retained)
            self.assertEqual("integration_old", retained.integration_id)
            # New contract -> new plan identity -> a new immutable row; the
            # old row is never updated or deleted.
            new = self._integration(
                TRANSLATION_CONTRACT_FINGERPRINT, "integration_new", "plan_new"
            )
            repo.save_chapter_integration_result(
                new,
                idempotency_key=(
                    f"integration:plan_new:ch1:{TRANSLATION_CONTRACT_FINGERPRINT[:12]}"
                ),
            )
            current = repo.chapter_integration_result(
                "proj_1",
                "plan_new",
                "ch1",
                translation_contract_fingerprint=TRANSLATION_CONTRACT_FINGERPRINT,
            )
            self.assertIsNotNone(current)
            self.assertEqual("integration_new", current.integration_id)
            retained_again = repo.chapter_integration_result(
                "proj_1", "plan_old", "ch1"
            )
            self.assertIsNotNone(retained_again)
            self.assertEqual("integration_old", retained_again.integration_id)
            self.assertEqual(
                previous_contract,
                retained_again.translation_contract_fingerprint,
            )

    def test_integration_identity_collision_with_different_contract_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = WritingReferenceRepository(Path(tmp) / "wr.sqlite3")
            original = self._integration(
                "contract_a",
                "integration_a",
                "plan_collision",
            )
            repo.save_chapter_integration_result(
                original,
                idempotency_key="integration-plan-collision-contract-a",
            )
            conflicting = self._integration(
                "contract_b",
                "integration_b",
                "plan_collision",
            )

            with self.assertRaisesRegex(
                WritingReferenceConflictError,
                "different translation contract fingerprint",
            ):
                repo.save_chapter_integration_result(
                    conflicting,
                    idempotency_key="integration-plan-collision-contract-b",
                )

    def test_chunk_identity_collision_with_different_fingerprint_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = WritingReferenceRepository(Path(tmp) / "wr.sqlite3")
            base = dict(
                chunk_id="chunk_collision",
                plan_id="plan_collision",
                project_id="proj_1",
                artifact_id="artifact_1",
                chapter_id="ch1",
                chunk_order=1,
                source_span_ids=["span_1"],
                source_text="Source text.",
                source_text_sha256="source_hash",
                hy_mt2_model=HY_MT2_MODEL_ID,
                hy_mt2_prompt_version=HY_MT2_PROMPT_VERSION,
                hy_mt2_input_hash="input_hash",
                translated_text="译文。",
                translated_text_sha256="target_hash",
                unit_targets={"1": "译文。"},
                created_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
            )
            repo.save_translation_chunk(
                TranslationChunkRecord(
                    **base,
                    chunk_fingerprint="fingerprint_a",
                ),
                idempotency_key="chunk-collision-contract-a",
            )

            with self.assertRaisesRegex(
                WritingReferenceConflictError,
                "different fingerprint",
            ):
                repo.save_translation_chunk(
                    TranslationChunkRecord(
                        **base,
                        chunk_fingerprint="fingerprint_b",
                    ),
                    idempotency_key="chunk-collision-contract-b",
                )

    def test_planner_fingerprint_folds_translation_contract(self) -> None:
        base = dict(
            artifact_id="a1",
            extraction_revision="r1",
            planner_model="deepseek-v4-flash",
            planner_prompt_version="flash_toc_planning_v0_2_segment_ranges",
            document_sha256="d" * 64,
        )
        with_contract = pipeline_module._planner_contract_fingerprint(
            **base, translation_contract=TRANSLATION_CONTRACT_FINGERPRINT
        )
        legacy = pipeline_module._planner_contract_fingerprint(**base)
        stale_contract = pipeline_module._planner_contract_fingerprint(
            **base, translation_contract="stale-contract"
        )
        self.assertNotEqual(with_contract, legacy)
        self.assertNotEqual(with_contract, stale_contract)


# ---------------------------------------------------------------------------
# Point 12: direct and batch translation share the same aligned contract
# ---------------------------------------------------------------------------


class SharedAlignedContractTests(unittest.TestCase):
    def test_direct_path_uses_marked_units_and_strips_markers(self) -> None:
        translator = FakeHyMt2Translator()
        qc = FakeFlashQcRunner()
        pipeline = ChapterTranslationPipeline(
            ocr_runner=FakeOcrRunner(),
            flash_planner=FakeFlashPlanner(),
            hy_mt2_translator=translator,
            flash_qc_runner=qc,
        )
        candidate = pipeline.translate_chapter(
            source_text="First protocol sentence.\n\nSecond protocol sentence.",
            document_sha256="d" * 64,
            extraction_revision="r1",
            chapter_id="ch1",
            chunk_id="c1",
            glossary_version="v1",
        )
        # Hy-MT2 received stable ASCII unit markers.
        self.assertIn("[[CMS_SEG_0001]]", translator.calls[0][0])
        # Flash received the aligned marked envelope.
        self.assertIn("DRAFT_ZH:", qc.calls[0][0])
        self.assertIn("[[CMS_SEG_0001]]", qc.calls[0][0])
        # The admitted candidate is marker-free Chinese.
        self.assertFalse(contains_unit_markers(candidate.translated_text))
        self.assertEqual(HY_MT2_PROMPT_VERSION, candidate.hy_mt2.prompt_version)
        self.assertEqual(FLASH_QC_PROMPT_VERSION, candidate.flash_qc.qc_prompt_version)

    def test_batch_wires_same_aligned_helpers(self) -> None:
        # The batch chapter path calls the exact same aligned-unit helpers as
        # the direct pipeline path (same objects, not divergent copies).
        self.assertIs(
            batch_module.translate_units_with_bounded_correction,
            pipeline_module.translate_units_with_bounded_correction,
        )
        self.assertIs(
            batch_module.integrate_units_with_flash,
            pipeline_module.integrate_units_with_flash,
        )
        self.assertIs(
            batch_module.TRANSLATION_CONTRACT_FINGERPRINT,
            pipeline_module.TRANSLATION_CONTRACT_FINGERPRINT,
        )


if __name__ == "__main__":
    unittest.main()
