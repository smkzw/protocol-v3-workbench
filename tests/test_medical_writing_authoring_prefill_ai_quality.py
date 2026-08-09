"""Quality-gate tests for the production DeepSeek prefill AI adapter.

Tests the language and evidence-determinism quality gates (L1+L2) added to
``medical_writing_authoring_prefill_ai.py``:

- English condition term is preserved and can be recommended.
- English protocol title is hard-dropped (not demoted); Chinese safe title
  is still recommended.
- Unconfirmed facts (成人PNH患者, 随机双盲安慰剂对照, 口服给药) are
  hard-dropped, even when an unrelated evidence ref is attached.
- Abbreviations like CMS-D017, PNH, PK/PD, SAD/MAD do not trigger false
  rejection.
- Candidates with registered source IDs are preserved by the merge rules
  when they pass the quality gate.
- All user-visible limitations/rationale use natural Chinese — no English
  development labels like "AI proposed".
- All existing prefill tests remain green.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from packages.contracts.workbench_contracts import (
    AuthoringPrefillCandidate,
    AuthoringPrefillEvidenceRef,
    MedicalWritingAuthoringJourneyCreateRequest,
    MedicalWritingStudyFraming,
)
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyService,
)
from services.api.app.medical_writing_authoring_prefill import (
    generate_prefill_package,
)
from services.api.app.medical_writing_authoring_prefill_ai import (
    DEEPSEEK_PREFILL_MODEL,
    _build_condition_candidate,
    _detect_unconfirmed_fact,
    _detect_whole_sentence_english,
    _has_real_evidence,
    _is_english_token,
    _merge_ai_candidates,
    _passes_language_and_evidence_gate,
    DeepSeekPrefillAdapter,
)

NOW = datetime(2026, 7, 24, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pnh_create_request(**overrides) -> MedicalWritingAuthoringJourneyCreateRequest:
    framing_fields: dict[str, Any] = {
        "investigational_product": "CMS-D017",
        "indication": "阵发性睡眠性血红蛋白尿症（PNH）",
        "study_phase": "II期",
    }
    request_fields: dict[str, Any] = {
        "actor": "medical_manager_test",
        "idempotency_key": "create-pnh-quality-001",
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

    W2b-2 r2: Auto-echoes catalog identity from request payload.
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
        ec = getattr(envelope, "payload", {}).get("evidence_catalog")
        if ec:
            cat_id = ec.get("catalog_id", "")
            cat_sha = ec.get("catalog_sha256", "")
            if "catalog_id" not in result:
                result["catalog_id"] = cat_id
            if "catalog_sha256" not in result:
                result["catalog_sha256"] = cat_sha
            ps = result.get("prefill_suggestions")
            if isinstance(ps, dict):
                if "catalog_id" not in ps:
                    ps["catalog_id"] = cat_id
                if "catalog_sha256" not in ps:
                    ps["catalog_sha256"] = cat_sha
        return result


def _make_candidate(
    field_path: str,
    value: str,
    *,
    evidence_refs: list[AuthoringPrefillEvidenceRef] | None = None,
    rationale: str = "",
    preview: str = "",
    candidate_id: str = "",
) -> AuthoringPrefillCandidate:
    import hashlib
    import json

    digest = hashlib.sha256(
        json.dumps(
            {"field_path": field_path, "value": value, "suffix": candidate_id or "test"},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:16]
    return AuthoringPrefillCandidate(
        candidate_id=candidate_id or f"mwprefilltest_{digest}",
        field_path=field_path,
        structured_value=value,
        preview=preview or value,
        evidence_refs=evidence_refs or [],
        rationale=rationale or "测试候选",
        limitations=["测试候选限制"],
        confidence="medium",
        state="ai_proposed",
    )


def _make_evidence_ref(
    source_id: str = "",
    source_text: str = "",
) -> AuthoringPrefillEvidenceRef:
    return AuthoringPrefillEvidenceRef(
        source_kind="study_definition",
        source_id=source_id,
        source_text=source_text,
        locator="test_locator",
    )


# ---------------------------------------------------------------------------
# 1. English condition term preserved and recommended
# ---------------------------------------------------------------------------

class EnglishConditionTermPreservedTests(unittest.TestCase):
    """The English ClinicalTrials.gov condition term must remain a valid,
    recommendable candidate — the language gate must NOT reject it."""

    def test_english_condition_term_passes_language_gate(self):
        """The condition-term path is exempt from the language gate."""
        passed, _reason, _gap_notes = _passes_language_and_evidence_gate(
            "framing.clinicaltrials_condition_term",
            "Paroxysmal Nocturnal Hemoglobinuria",
            "Paroxysmal Nocturnal Hemoglobinuria",
            "AI提出的英文检索词",
            evidence_refs=[],
        )
        self.assertTrue(passed)

    def test_english_condition_term_candidate_is_built_correctly(self):
        """_build_condition_candidate returns a valid candidate with English
        value and Chinese rationale."""
        candidate = _build_condition_candidate(
            "Paroxysmal Nocturnal Hemoglobinuria",
            indication="阵发性睡眠性血红蛋白尿症（PNH）",
            phase="II期",
        )
        self.assertIsNotNone(candidate)
        self.assertEqual(
            "Paroxysmal Nocturnal Hemoglobinuria",
            str(candidate.structured_value),
        )
        # Rationale and limitations must be in Chinese.
        self.assertIn("阵发性睡眠性血红蛋白尿症", candidate.rationale)
        self.assertIn("医学经理", candidate.limitations[0])
        # No English dev phrase.
        for lim in candidate.limitations:
            self.assertNotIn("AI proposed", lim)
            self.assertNotIn("medical manager", lim.lower())

    def test_condition_term_survives_enrich_package(self):
        """End-to-end: enrich_package produces a recommendable English
        condition-term candidate for a PNH project."""
        tmpdir = tempfile.TemporaryDirectory()
        try:
            service = MedicalWritingAuthoringJourneyService(
                Path(tmpdir.name) / "test.sqlite3"
            )
            service.create("proj_pnh_q", _pnh_create_request())
            journey = service.get("proj_pnh_q")
            deterministic = generate_prefill_package(
                state=journey, now=NOW, actor="test"
            )
            provider = _CountingProvider({
                "_response_model": DEEPSEEK_PREFILL_MODEL,
                "clinicaltrials_condition_term_en": "Paroxysmal Nocturnal Hemoglobinuria",
                "field_suggestions": {},
            })
            adapter = DeepSeekPrefillAdapter(
                provider=provider, model_name=DEEPSEEK_PREFILL_MODEL
            )
            enriched = adapter.enrich_package(
                package=deterministic, state=journey
            )
            group = enriched.field_candidates.get(
                "framing.clinicaltrials_condition_term"
            )
            self.assertIsNotNone(group)
            recommended = group.candidates[0]
            self.assertEqual(
                "Paroxysmal Nocturnal Hemoglobinuria",
                str(recommended.structured_value),
            )
        finally:
            tmpdir.cleanup()


# ---------------------------------------------------------------------------
# 2. English protocol title hard-dropped, Chinese title recommended
# ---------------------------------------------------------------------------

class EnglishTitleRejectedTests(unittest.TestCase):
    """English whole-sentence titles must be hard-dropped by the quality
    gate during merge — they must not appear as selectable candidates at
    all, not even as non-recommended alternatives."""

    def test_english_whole_sentence_title_rejected_by_gate(self):
        """A title like 'Phase 2 Study of CMS-D017 in PNH' is rejected
        because it is a whole-sentence English string in a non-condition
        path."""
        passed, reason, _gap_notes = _passes_language_and_evidence_gate(
            "framing.document_title",
            "Phase 2 Study of CMS-D017 in PNH",
            "Phase 2 Study of CMS-D017 in PNH",
            "AI rephrased title",
            evidence_refs=[],
        )
        self.assertFalse(passed)
        self.assertIn("whole_sentence_english", reason)

    def test_short_english_title_rejected_by_gate(self):
        """'Phase II Study' (3 English words, no Chinese) is rejected."""
        passed, reason, _gap_notes = _passes_language_and_evidence_gate(
            "framing.document_title",
            "Phase II Study",
            "Phase II Study",
            "AI title",
            evidence_refs=[],
        )
        self.assertFalse(passed)
        self.assertIn("whole_sentence_english", reason)

    def test_single_english_word_rejected_by_gate(self):
        """A single non-allowlisted English word like 'Study' without
        Chinese context is rejected."""
        passed, _reason, _gap_notes = _passes_language_and_evidence_gate(
            "framing.document_title",
            "Study",
            "Study",
            "",
            evidence_refs=[],
        )
        self.assertFalse(passed)

    def test_english_title_hard_dropped_in_merge(self):
        """The merge function completely drops the English title candidate.
        It must NOT appear anywhere in the result — not as recommendation,
        not as alternative."""
        ai = _make_candidate(
            "framing.document_title",
            "Phase 2 Study of CMS-D017 in PNH Patients",
            rationale="AI rephrased title",
        )
        det = _make_candidate(
            "framing.document_title",
            "CMS-D017治疗PNH的II期方案",
            rationale="确定性默认",
        )
        merged = _merge_ai_candidates(
            field_path="framing.document_title",
            deterministic=[det],
            ai_candidates=[ai],
        )
        values = [str(c.structured_value) for c in merged]
        self.assertNotIn(
            "Phase 2 Study of CMS-D017 in PNH Patients", values,
            "English title must be completely hard-dropped, not demoted",
        )
        # Chinese deterministic title survives.
        self.assertIn("CMS-D017治疗PNH的II期方案", values)

    def test_english_title_with_evidence_still_dropped(self):
        """Even with an evidence ref, a whole-sentence English title is
        dropped — the language gate is absolute for non-condition paths."""
        ref = _make_evidence_ref(
            source_id="protocol_artifact_001",
            source_text="some source text",
        )
        ai = _make_candidate(
            "framing.document_title",
            "Phase 2 Study of CMS-D017 in PNH",
            evidence_refs=[ref],
            rationale="AI title with evidence",
        )
        merged = _merge_ai_candidates(
            field_path="framing.document_title",
            deterministic=[],
            ai_candidates=[ai],
        )
        self.assertEqual(
            [], merged,
            "English title must be dropped even with an evidence ref",
        )

    def test_chinese_title_passes_gate(self):
        """A proper Chinese title passes the quality gate."""
        passed, _reason, _gap_notes = _passes_language_and_evidence_gate(
            "framing.document_title",
            "CMS-D017治疗阵发性睡眠性血红蛋白尿症（PNH）的II期临床研究方案",
            "CMS-D017治疗PNH的II期临床研究方案",
            "基于试验药物和适应症生成标题建议",
            evidence_refs=[],
        )
        self.assertTrue(passed)

    def test_chinese_title_accepted_in_merge(self):
        """The merge accepts a Chinese title."""
        ai = _make_candidate(
            "framing.document_title",
            "CMS-D017治疗阵发性睡眠性血红蛋白尿症的II期临床研究方案",
            rationale="基于试验药物和适应症生成标题建议",
        )
        merged = _merge_ai_candidates(
            field_path="framing.document_title",
            deterministic=[],
            ai_candidates=[ai],
        )
        self.assertEqual(1, len(merged))
        self.assertIn("CMS-D017", str(merged[0].structured_value))

    # --- Per-field language gate (L1 must check each field independently) ---

    def test_english_value_chinese_rationale_rejected(self):
        """English value + Chinese rationale must be rejected.  The Chinese
        rationale must not mask the English value."""
        passed, reason, _gap_notes = _passes_language_and_evidence_gate(
            "framing.document_title",
            "Phase 2 Study of CMS-D017 in PNH",
            "Phase 2 Study of CMS-D017 in PNH",
            "根据项目信息生成的标题候选",
            evidence_refs=[],
        )
        self.assertFalse(passed)
        self.assertIn("whole_sentence_english", reason)
        self.assertIn("value", reason)

    def test_chinese_value_english_preview_rejected(self):
        """Chinese value + English preview must be rejected."""
        passed, reason, _gap_notes = _passes_language_and_evidence_gate(
            "framing.document_title",
            "CMS-D017治疗PNH的II期方案",
            "Phase 2 Study of CMS-D017 in PNH",
            "基于项目信息生成",
            evidence_refs=[],
        )
        self.assertFalse(passed)
        self.assertIn("whole_sentence_english", reason)
        self.assertIn("preview", reason)

    def test_chinese_value_preview_english_rationale_rejected(self):
        """Chinese value/preview + English rationale must be rejected."""
        passed, reason, _gap_notes = _passes_language_and_evidence_gate(
            "framing.document_title",
            "CMS-D017治疗PNH的II期方案",
            "CMS-D017治疗PNH的II期方案",
            "AI proposed title based on project info",
            evidence_refs=[],
        )
        self.assertFalse(passed)
        self.assertIn("whole_sentence_english", reason)
        self.assertIn("rationale", reason)

    def test_chinese_with_necessary_abbreviations_passes(self):
        """Chinese text containing necessary abbreviations (CMS-D017, PNH,
        PK/PD) passes the per-field language gate."""
        passed, _reason, _gap_notes = _passes_language_and_evidence_gate(
            "framing.document_title",
            "CMS-D017治疗PNH的II期临床研究方案",
            "CMS-D017治疗PNH的II期方案",
            "包含药物代号和疾病缩写的中文标题",
            evidence_refs=[],
        )
        self.assertTrue(passed)

    def test_abbreviation_only_value_passes(self):
        """A value composed entirely of allowlisted abbreviations passes."""
        passed, _reason, _gap_notes = _passes_language_and_evidence_gate(
            "picos.intervention_summary",
            "PK/PD",
            "PK/PD",
            "药代动力学研究",
            evidence_refs=[],
        )
        self.assertTrue(passed)

    def test_protocol_and_registration_identifiers_are_not_numeric_claims(self):
        for value in ("CMS-D017", "CMS-RA-201", "NCT01234567"):
            passed, reason, _gap_notes = _passes_language_and_evidence_gate(
                "framing.protocol_id",
                value,
                value,
                "项目或注册标识符",
                evidence_refs=[],
            )
            self.assertTrue(passed, reason)

    def test_unbound_clinical_number_remains_fail_closed(self):
        passed, reason, _gap_notes = _passes_language_and_evidence_gate(
            "picos.intervention_summary",
            "每次给药120 mg",
            "剂量为120 mg",
            "AI建议剂量",
            evidence_refs=[],
        )
        self.assertFalse(passed)
        self.assertIn("unconfirmed_fact", reason)


# ---------------------------------------------------------------------------
# 3. Unconfirmed facts hard-dropped (even with evidence refs)
# ---------------------------------------------------------------------------

class UnconfirmedFactRejectionTests(unittest.TestCase):
    """Candidates that assert unconfirmed design/population facts must be
    hard-dropped during merge, regardless of evidence_refs.  The current
    bulk request only provides registered source IDs without verifiable
    source excerpts, so there is no semantic way to prove the cited source
    supports the asserted fact."""

    def test_adult_pnh_population_rejected_without_evidence(self):
        """'成人PNH患者' without a source is rejected."""
        passed, reason, _gap_notes = _passes_language_and_evidence_gate(
            "framing.population_intent",
            "成人PNH患者",
            "成人PNH患者",
            "AI建议的目标人群",
            evidence_refs=[],
        )
        self.assertFalse(passed)
        self.assertIn("unconfirmed_fact", reason)

    def test_adult_pnh_rejected_even_with_unrelated_evidence(self):
        """Even with an unrelated evidence ref, '成人PNH患者' is rejected.
        The bulk request provides only source IDs, not source excerpts,
        so any ref is treated as insufficient to verify the claim."""
        ref = _make_evidence_ref(
            source_id="protocol_artifact_001",
            source_text="unrelated source text",
        )
        passed, reason, _gap_notes = _passes_language_and_evidence_gate(
            "framing.population_intent",
            "成人PNH患者",
            "成人PNH患者",
            "AI建议的目标人群",
            evidence_refs=[ref],
        )
        self.assertFalse(passed)
        self.assertIn("unconfirmed_fact", reason)

    def test_adult_pnh_hard_dropped_in_merge(self):
        """The merge function completely drops unconfirmed-fact candidates."""
        ai = _make_candidate(
            "framing.population_intent",
            "成人PNH患者",
            rationale="AI建议",
        )
        det = _make_candidate(
            "framing.population_intent",
            "符合诊断标准的PNH目标人群",
            rationale="确定性默认",
        )
        merged = _merge_ai_candidates(
            field_path="framing.population_intent",
            deterministic=[det],
            ai_candidates=[ai],
        )
        values = [str(c.structured_value) for c in merged]
        self.assertNotIn(
            "成人PNH患者", values,
            "unconfirmed-fact candidate must be hard-dropped",
        )
        self.assertIn("符合诊断标准的PNH目标人群", values)

    def test_randomized_double_blind_placebo_rejected_without_evidence(self):
        """'随机双盲安慰剂对照' without a source is rejected."""
        passed, reason, _gap_notes = _passes_language_and_evidence_gate(
            "framing.design_pattern",
            "随机、双盲、安慰剂对照试验",
            "随机双盲安慰剂对照",
            "AI建议设计",
            evidence_refs=[],
        )
        self.assertFalse(passed)
        self.assertIn("unconfirmed_fact", reason)

    def test_randomized_double_blind_placebo_rejected_with_evidence(self):
        """'随机双盲安慰剂对照' with an unrelated evidence ref is still
        rejected — no semantic binding exists."""
        ref = _make_evidence_ref(
            source_id="protocol_artifact_001",
            source_text="some text",
        )
        passed, reason, _gap_notes = _passes_language_and_evidence_gate(
            "framing.design_pattern",
            "随机、双盲、安慰剂对照试验",
            "随机双盲安慰剂对照",
            "AI建议设计",
            evidence_refs=[ref],
        )
        self.assertFalse(passed)
        self.assertIn("unconfirmed_fact", reason)

    def test_randomized_double_blind_placebo_hard_dropped_in_merge(self):
        ai = _make_candidate(
            "framing.design_pattern",
            "随机、双盲、安慰剂对照",
            rationale="AI",
        )
        det = _make_candidate(
            "framing.design_pattern",
            "待确认研究设计",
            rationale="确定性默认",
        )
        merged = _merge_ai_candidates(
            field_path="framing.design_pattern",
            deterministic=[det],
            ai_candidates=[ai],
        )
        values = [str(c.structured_value) for c in merged]
        self.assertNotIn("随机、双盲、安慰剂对照", values)
        self.assertIn("待确认研究设计", values)

    def test_oral_administration_rejected_without_evidence(self):
        """'口服给药' without a source is rejected."""
        passed, reason, _gap_notes = _passes_language_and_evidence_gate(
            "picos.intervention_summary",
            "口服给药的小分子抑制剂",
            "口服给药",
            "AI建议给药途径",
            evidence_refs=[],
        )
        self.assertFalse(passed)
        self.assertIn("unconfirmed_fact", reason)

    def test_oral_administration_hard_dropped_in_merge(self):
        ai = _make_candidate(
            "picos.intervention_summary",
            "口服给药",
            rationale="AI",
        )
        det = _make_candidate(
            "picos.intervention_summary",
            "待确认给药信息",
            rationale="确定性默认",
        )
        merged = _merge_ai_candidates(
            field_path="picos.intervention_summary",
            deterministic=[det],
            ai_candidates=[ai],
        )
        values = [str(c.structured_value) for c in merged]
        self.assertNotIn("口服给药", values)
        self.assertIn("待确认给药信息", values)

    def test_mechanism_rejected_without_evidence(self):
        """'单克隆抗体' (monoclonal antibody) without a source is rejected."""
        passed, reason, _gap_notes = _passes_language_and_evidence_gate(
            "picos.intervention_summary",
            "针对IL-6的单克隆抗体",
            "单克隆抗体",
            "AI建议机制",
            evidence_refs=[],
        )
        self.assertFalse(passed)
        self.assertIn("unconfirmed_fact", reason)


# ---------------------------------------------------------------------------
# 4. Abbreviations do not trigger false rejection
# ---------------------------------------------------------------------------

class AbbreviationSafetyTests(unittest.TestCase):
    """Necessary English abbreviations must not be rejected as
    whole-sentence English."""

    def test_cms_d017_not_rejected(self):
        """'CMS-D017' is not a whole-sentence English string."""
        self.assertFalse(_detect_whole_sentence_english("CMS-D017"))

    def test_pnh_not_rejected(self):
        """'PNH' is not rejected."""
        self.assertFalse(_detect_whole_sentence_english("PNH"))

    def test_pk_pd_not_rejected(self):
        """'PK/PD' is not rejected."""
        self.assertFalse(_detect_whole_sentence_english("PK/PD"))

    def test_sad_mad_not_rejected(self):
        """'SAD/MAD' is not rejected."""
        self.assertFalse(_detect_whole_sentence_english("SAD/MAD"))

    def test_nct_id_not_rejected(self):
        """An NCT ID is not rejected."""
        self.assertFalse(_detect_whole_sentence_english("NCT01234567"))

    def test_chinese_with_abbreviations_not_rejected(self):
        """Chinese text containing English abbreviations is not rejected."""
        passed, _reason, _gap_notes = _passes_language_and_evidence_gate(
            "framing.document_title",
            "CMS-D017治疗PNH的II期临床研究方案",
            "CMS-D017治疗PNH的II期方案",
            "包含药物代号和疾病缩写的中文标题",
            evidence_refs=[],
        )
        self.assertTrue(passed)

    def test_is_english_token_recognizes_real_english(self):
        """_is_english_token correctly identifies English words."""
        self.assertTrue(_is_english_token("Study"))
        self.assertTrue(_is_english_token("Phase"))
        self.assertTrue(_is_english_token("randomized"))

    def test_is_english_token_exempts_abbreviations(self):
        """_is_english_token returns False for allowlisted tokens."""
        self.assertFalse(_is_english_token("CMS-D017"))
        self.assertFalse(_is_english_token("PNH"))
        self.assertFalse(_is_english_token("PK"))
        self.assertFalse(_is_english_token("SAD"))
        self.assertFalse(_is_english_token("NCT01234567"))


# ---------------------------------------------------------------------------
# 5. Merge ranking: evidence-bound candidates not displaced
# ---------------------------------------------------------------------------

class MergeRankingTests(unittest.TestCase):
    """The corrected merge function must not let evidence-free AI candidates
    displace evidence-bound candidates from the recommendation slot."""

    def test_ai_without_evidence_does_not_displace_deterministic_with_evidence(self):
        """When a deterministic candidate has real evidence and the AI
        candidate does not, the deterministic candidate must rank first
        (be the recommendation)."""
        det = _make_candidate(
            "framing.document_title",
            "CMS-D017治疗PNH的II期方案",
            evidence_refs=[_make_evidence_ref(
                source_id="protocol_artifact_001",
                source_text="confirmed title from protocol",
            )],
            rationale="基于已登记方案",
        )
        ai = _make_candidate(
            "framing.document_title",
            "CMS-D017在PNH中的II期研究方案",
            evidence_refs=[],  # no evidence
            rationale="AI改写标题",
        )
        merged = _merge_ai_candidates(
            field_path="framing.document_title",
            deterministic=[det],
            ai_candidates=[ai],
        )
        self.assertGreater(len(merged), 0)
        # The evidence-bound deterministic candidate must be the recommendation.
        self.assertEqual(
            str(det.structured_value),
            str(merged[0].structured_value),
        )

    def test_ai_with_evidence_can_become_recommendation(self):
        """When an AI candidate carries real source_text evidence, it can
        legitimately rank above an evidence-free deterministic candidate."""
        det = _make_candidate(
            "framing.document_title",
            "CMS-D017治疗PNH的II期方案",
            evidence_refs=[],
            rationale="确定性默认",
        )
        ai = _make_candidate(
            "framing.document_title",
            "CMS-D017治疗阵发性睡眠性血红蛋白尿症的II期方案",
            evidence_refs=[_make_evidence_ref(
                source_id="protocol_artifact_001",
                source_text="confirmed title",
            )],
            rationale="基于已登记方案确认",
        )
        merged = _merge_ai_candidates(
            field_path="framing.document_title",
            deterministic=[det],
            ai_candidates=[ai],
        )
        self.assertGreater(len(merged), 0)
        # AI candidate with evidence ranks first.
        self.assertEqual(
            str(ai.structured_value),
            str(merged[0].structured_value),
        )

    def test_pure_rephrasing_ai_kept_as_alternative(self):
        """A pure rephrasing AI candidate without evidence is kept as an
        alternative but does not displace evidence-bound candidates."""
        det = _make_candidate(
            "framing.document_title",
            "确定性标题",
            evidence_refs=[_make_evidence_ref(source_text="evidence")],
        )
        ai = _make_candidate(
            "framing.document_title",
            "AI改写的确定性标题变体",
            evidence_refs=[],
        )
        merged = _merge_ai_candidates(
            field_path="framing.document_title",
            deterministic=[det],
            ai_candidates=[ai],
        )
        # Both should be present.
        self.assertEqual(2, len(merged))
        # Evidence-bound candidate is recommendation.
        self.assertEqual(str(det.structured_value), str(merged[0].structured_value))


# ---------------------------------------------------------------------------
# 6. No English dev phrases in limitations/rationale
# ---------------------------------------------------------------------------

class NoEnglishDevPhrasesTests(unittest.TestCase):
    """AI candidate limitations and rationale must use natural Chinese,
    with no English development labels like 'AI proposed'."""

    def test_parse_field_suggestions_default_limitation_is_chinese(self):
        from services.api.app.medical_writing_authoring_prefill_ai import (
            _parse_field_suggestions,
        )
        registered = frozenset({"framing.indication"})
        candidates = _parse_field_suggestions(
            "framing.document_title",
            [{"value": "CMS-D017测试标题", "preview": "测试", "rationale": ""}],
            registered_source_ids=registered,
        )
        self.assertEqual(1, len(candidates))
        lim = candidates[0].limitations[0]
        self.assertNotIn("AI proposed", lim)
        self.assertNotIn("not yet adopted", lim)
        self.assertNotIn("medical manager", lim.lower())
        self.assertIn("医学经理", lim)

    def test_condition_candidate_limitations_are_chinese(self):
        candidate = _build_condition_candidate(
            "Paroxysmal Nocturnal Hemoglobinuria",
            indication="阵发性睡眠性血红蛋白尿症",
            phase="II期",
        )
        for lim in candidate.limitations:
            self.assertNotIn("AI proposed", lim)
            self.assertNotIn("not yet adopted", lim)
            self.assertNotIn("medical manager", lim.lower())
            self.assertIn("医学经理", lim)


# ---------------------------------------------------------------------------
# 7. _detect_whole_sentence_english edge cases
# ---------------------------------------------------------------------------

class WholeSentenceEnglishDetectionTests(unittest.TestCase):

    def test_short_english_phrase_rejected(self):
        """Even 'Phase II Study' (3 words, no Chinese) is rejected."""
        self.assertTrue(_detect_whole_sentence_english("Phase II Study"))

    def test_long_english_sentence_rejected(self):
        """5+ consecutive English words are rejected."""
        self.assertTrue(_detect_whole_sentence_english(
            "A Phase Two Study of CMS-D017 in PNH Patients"
        ))

    def test_single_english_word_rejected(self):
        """A single non-allowlisted English word without Chinese is
        rejected."""
        self.assertTrue(_detect_whole_sentence_english("Study"))
        self.assertTrue(_detect_whole_sentence_english("randomized"))

    def test_mixed_cn_en_not_rejected(self):
        """Text with Chinese characters is never rejected as whole-sentence
        English."""
        self.assertFalse(_detect_whole_sentence_english(
            "CMS-D017的Phase II研究"
        ))

    def test_empty_string_not_rejected(self):
        self.assertFalse(_detect_whole_sentence_english(""))

    def test_abbreviation_only_not_rejected(self):
        """Strings composed entirely of allowlisted tokens are not
        rejected."""
        self.assertFalse(_detect_whole_sentence_english("CMS-D017 PNH"))
        self.assertFalse(_detect_whole_sentence_english("PK/PD"))
        self.assertFalse(_detect_whole_sentence_english("SAD/MAD"))


# ---------------------------------------------------------------------------
# 8. _detect_unconfirmed_fact edge cases
# ---------------------------------------------------------------------------

class UnconfirmedFactDetectionTests(unittest.TestCase):

    def test_detects_english_adult(self):
        self.assertTrue(_detect_unconfirmed_fact("Adult PNH patients"))

    def test_detects_chinese_adult(self):
        self.assertTrue(_detect_unconfirmed_fact("成人PNH患者"))

    def test_detects_randomized(self):
        self.assertTrue(_detect_unconfirmed_fact("randomized controlled trial"))
        self.assertTrue(_detect_unconfirmed_fact("随机对照试验"))

    def test_detects_double_blind(self):
        self.assertTrue(_detect_unconfirmed_fact("double-blind study"))
        self.assertTrue(_detect_unconfirmed_fact("双盲研究"))

    def test_detects_placebo_controlled(self):
        self.assertTrue(_detect_unconfirmed_fact("placebo-controlled"))
        self.assertTrue(_detect_unconfirmed_fact("安慰剂对照"))

    def test_detects_oral(self):
        self.assertTrue(_detect_unconfirmed_fact("oral administration"))
        self.assertTrue(_detect_unconfirmed_fact("口服给药"))

    def test_does_not_detect_simple_text(self):
        """Plain indication text without design facts is not flagged."""
        self.assertFalse(_detect_unconfirmed_fact("阵发性睡眠性血红蛋白尿症"))
        self.assertFalse(_detect_unconfirmed_fact("PNH"))


# ---------------------------------------------------------------------------
# 9. _has_real_evidence
# ---------------------------------------------------------------------------

class HasRealEvidenceTests(unittest.TestCase):

    def test_candidate_with_artifact_source_id_has_real_evidence(self):
        cand = _make_candidate(
            "framing.document_title",
            "test",
            evidence_refs=[_make_evidence_ref(source_id="protocol_artifact_001")],
        )
        self.assertTrue(_has_real_evidence(cand))

    def test_candidate_with_source_text_has_real_evidence(self):
        cand = _make_candidate(
            "framing.document_title",
            "test",
            evidence_refs=[_make_evidence_ref(source_text="some evidence text")],
        )
        self.assertTrue(_has_real_evidence(cand))

    def test_candidate_with_only_framing_source_id_no_real_evidence(self):
        """A candidate citing only framing.indication as source does not
        have 'real' evidence in the merge-ranking sense."""
        cand = _make_candidate(
            "framing.document_title",
            "test",
            evidence_refs=[_make_evidence_ref(source_id="framing.indication")],
        )
        self.assertFalse(_has_real_evidence(cand))

    def test_candidate_with_no_evidence_refs(self):
        cand = _make_candidate(
            "framing.document_title",
            "test",
            evidence_refs=[],
        )
        self.assertFalse(_has_real_evidence(cand))


if __name__ == "__main__":
    unittest.main()
