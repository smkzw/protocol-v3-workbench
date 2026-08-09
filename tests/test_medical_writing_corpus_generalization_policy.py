from services.api.app.medical_writing_corpus_policy import (
    CorpusSourcePolicy,
    assess_corpus_support,
    corpus_generalization_prompt_contract,
    corpus_text_facet_match,
    cross_indication_transfer_scope,
    plan_corpus_facets,
    project_match_score,
    reuse_policy,
)


def _policy(**overrides):
    values = {
        "governance_status": "clean_full_protocol",
        "indication_terms": ("类风湿关节炎", "RA"),
        "phase_terms": ("II", "2期"),
    }
    values.update(overrides)
    return CorpusSourcePolicy(**values)


def _typed_record(
    *,
    source_file,
    sponsor,
    claim_value,
    pattern_kind="wording_convention",
    indication="类风湿关节炎",
    phase="II期",
    research_purpose="概念验证",
    mechanism="JAK抑制",
    technology_type="小分子",
    dosage_form="片剂",
    administration_route="口服",
    design_module="随机双盲安慰剂对照",
):
    return {
        "source_file": source_file,
        "lead_sponsor": sponsor,
        "claim_value": claim_value,
        "pattern_kind": pattern_kind,
        "layer": {
            "indication": indication,
            "phase": phase,
            "research_purpose": research_purpose,
            "mechanism": mechanism,
            "technology_type": technology_type,
            "dosage_form": dosage_form,
            "administration_route": administration_route,
            "design_module": design_module,
        },
    }


def _target_layer(**overrides):
    layer = {
        "indication": "类风湿关节炎",
        "phase": "II期",
        "research_purpose": "概念验证",
        "mechanism": "JAK抑制",
        "technology_type": "小分子",
        "dosage_form": "片剂",
        "administration_route": "口服",
        "design_module": "随机双盲安慰剂对照",
    }
    layer.update(overrides)
    return layer


def test_plan_facets_preserve_full_design_layering_axes():
    drivers = [
        {
            "driver_kind": "phase",
            "decision_state": "required",
            "value_summary": "II期",
        },
        {
            "driver_kind": "research_purpose",
            "decision_state": "design_driven",
            "value_summary": "概念验证",
        },
        {
            "driver_kind": "drug_modality",
            "decision_state": "design_driven",
            "value_summary": "单克隆抗体",
        },
        {
            "driver_kind": "drug_route",
            "decision_state": "design_driven",
            "value_summary": "鼻喷",
        },
        {
            "driver_kind": "dosage_form",
            "decision_state": "design_driven",
            "value_summary": "喷雾剂",
        },
        {
            "driver_kind": "control",
            "decision_state": "design_driven",
            "value_summary": "安慰剂对照",
        },
    ]

    facets = plan_corpus_facets(drivers)

    assert facets == {
        "phase": "II期",
        "research_purpose": "概念验证",
        "modality": "单克隆抗体",
        "route": "鼻喷",
        "dosage_form": "喷雾剂",
        "control": "安慰剂对照",
    }


def test_cross_indication_disease_logic_receives_hard_ranking_penalty():
    policy = _policy(indication_terms=("特应性皮炎", "AD"))

    adjustment, reasons = corpus_text_facet_match(
        "主要终点为第16周EASI较基线的变化，受试者须维持稳定背景治疗。",
        "ad_phase2_protocol.docx",
        policy,
        {"indication": "类风湿关节炎", "phase": "II期"},
    )

    assert adjustment <= -0.45
    assert any("cross_indication_non_transferable" in reason for reason in reasons)
    assert any("endpoint" in reason for reason in reasons)
    assert any("background_treatment" in reason for reason in reasons)


def test_cross_indication_regulatory_common_clause_is_structure_only():
    policy = _policy(indication_terms=("特应性皮炎", "AD"))

    adjustment, reasons = corpus_text_facet_match(
        "受试者签署知情同意书前，不得实施任何试验相关程序。",
        "ad_phase2_protocol.docx",
        policy,
        {"indication": "类风湿关节炎", "phase": "II期"},
    )

    assert -0.10 < adjustment < 0
    assert reasons == ["cross_indication_structure_regulatory_only"]
    scope, blocked = cross_indication_transfer_scope(
        "受试者签署知情同意书前，不得实施任何试验相关程序。"
    )
    assert scope == "structure_or_regulatory_common_only"
    assert blocked == ()


def test_same_indication_is_still_penalized_for_phase_and_route_mismatch():
    policy = _policy(
        phase_terms=("III", "3期"),
        route_terms=("口服",),
        dosage_form_terms=("片剂",),
    )

    adjustment, reasons = corpus_text_facet_match(
        "本研究药物采用口服片剂，每日给药。",
        "ra_phase3_oral_protocol.docx",
        policy,
        {
            "indication": "类风湿关节炎",
            "phase": "II期",
            "route": "鼻喷",
            "dosage_form": "喷雾剂",
        },
    )

    assert adjustment <= -0.40
    assert any("phase_mismatch" in reason for reason in reasons)
    assert any("facet_mismatch:route" in reason for reason in reasons)
    assert any("facet_mismatch:dosage_form" in reason for reason in reasons)


def test_same_indication_design_mismatch_is_not_hidden_by_indication_match():
    policy = _policy(design_terms=("随机双盲安慰剂对照平行设计",))

    adjustment, reasons = corpus_text_facet_match(
        "本研究采用随机、双盲、安慰剂对照、平行组设计。",
        "ra_phase2_protocol.docx",
        policy,
        {
            "indication": "类风湿关节炎",
            "phase": "II期",
            "randomization": "非随机",
            "blinding": "开放标签",
            "control": "阳性对照",
            "allocation": "交叉设计",
        },
    )

    assert adjustment <= -0.45
    assert sum("facet_mismatch:" in reason for reason in reasons) >= 4


def test_cross_indication_common_clause_can_only_be_adapted_not_verbatim():
    row = {
        "text": "受试者签署知情同意书前，不得实施任何试验相关程序。",
        "reuse_level": "common_candidate",
    }

    result = reuse_policy(
        row,
        _policy(),
        project_match=0.0,
        fact_slots=[],
    )

    assert result == "adapt_required"


def test_single_source_never_becomes_high_confidence():
    assessment = assess_corpus_support(
        [
            {
                "source_file": "protocol_a.docx",
                "lead_sponsor": "Sponsor A",
                "claim_value": "每4周给药一次",
            }
        ]
    )

    assert assessment.support_level == "single_source_low_strength"
    assert assessment.high_confidence_eligible is False
    assert "fewer_than_two_independent_sources" in assessment.reasons
    assert "fewer_than_two_sponsors" in assessment.reasons


def test_two_sponsors_consistent_can_reach_high_confidence():
    assessment = assess_corpus_support(
        [
            {
                "source_file": "protocol_a.docx",
                "lead_sponsor": "Sponsor A",
                "claim_value": "每4周给药一次",
            },
            {
                "source_file": "protocol_b.docx",
                "lead_sponsor": "Sponsor B",
                "claim_value": "每4周给药一次",
            },
        ]
    )

    assert assessment.support_level == "multi_source_multi_sponsor_consistent"
    assert assessment.high_confidence_eligible is True


def test_multi_sponsor_conflict_is_preserved_and_not_passed():
    assessment = assess_corpus_support(
        [
            {
                "source_file": "protocol_a.docx",
                "lead_sponsor": "Sponsor A",
                "claim_value": "洗脱期4周",
            },
            {
                "source_file": "protocol_b.docx",
                "lead_sponsor": "Sponsor B",
                "claim_value": "洗脱期8周",
            },
        ]
    )

    assert assessment.support_level == "conflicting_requires_medical_review"
    assert assessment.high_confidence_eligible is False
    assert assessment.conflicting_values == ("洗脱期4周", "洗脱期8周")
    assert "conflicting_claim_values_preserved" in assessment.reasons


def test_indication_specific_wording_requires_two_sources_two_sponsors_same_layer():
    records = [
        _typed_record(
            source_file="ra_a.docx",
            sponsor="Sponsor A",
            claim_value="本研究拟评价研究药物在类风湿关节炎受试者中的有效性和安全性。",
        ),
        _typed_record(
            source_file="ra_b.docx",
            sponsor="Sponsor B",
            claim_value="本研究拟评价研究药物在类风湿关节炎受试者中的有效性和安全性。",
        ),
    ]

    assessment = assess_corpus_support(
        records,
        pattern_kind="wording_convention",
        target_layer=_target_layer(),
    )

    assert assessment.pattern_kind == "wording_convention"
    assert assessment.generalization_scope == "same_indication_layered_only"
    assert assessment.high_confidence_eligible is True
    assert assessment.medical_confirmation_required is False
    assert {
        profile["source_id"] for profile in assessment.evidence_profiles
    } == {"ra_a.docx", "ra_b.docx"}
    assert {
        profile["sponsor"] for profile in assessment.evidence_profiles
    } == {"Sponsor A", "Sponsor B"}
    assert all(
        tuple(profile["layer"]) == (
            "indication",
            "phase",
            "research_purpose",
            "mechanism",
            "technology_type",
            "dosage_form",
            "administration_route",
            "design_module",
        )
        for profile in assessment.evidence_profiles
    )


def test_same_indication_wording_is_layered_and_preserves_other_phase_counterexample():
    records = [
        _typed_record(
            source_file="ra_iia.docx",
            sponsor="Sponsor A",
            claim_value="拟评价研究药物的有效性和安全性。",
        ),
        _typed_record(
            source_file="ra_iib.docx",
            sponsor="Sponsor B",
            claim_value="拟评价研究药物的有效性和安全性。",
        ),
        _typed_record(
            source_file="ra_iii.docx",
            sponsor="Sponsor C",
            phase="III期",
            research_purpose="确证性研究",
            claim_value="旨在确证研究药物的疗效和安全性。",
        ),
    ]

    assessment = assess_corpus_support(
        records,
        pattern_kind="wording_convention",
        target_layer=_target_layer(),
    )

    assert assessment.high_confidence_eligible is True
    assert assessment.source_count == 2
    assert assessment.sponsor_count == 2
    assert len(assessment.counterexamples) == 1
    assert assessment.counterexamples[0]["source_id"] == "ra_iii.docx"
    assert "phase" in assessment.counterexamples[0]["reason"]
    assert "research_purpose" in assessment.counterexamples[0]["reason"]
    assert "counterexamples_preserved" in assessment.reasons


def test_clinical_design_requirement_cannot_generalize_from_indication_alone():
    records = [
        _typed_record(
            source_file="ra_ii.docx",
            sponsor="Sponsor A",
            claim_value="研究设置安慰剂对照。",
            pattern_kind="clinical_design_requirement",
        ),
        _typed_record(
            source_file="ra_iii.docx",
            sponsor="Sponsor B",
            phase="III期",
            research_purpose="确证性研究",
            claim_value="研究设置安慰剂对照。",
            pattern_kind="clinical_design_requirement",
        ),
    ]

    assessment = assess_corpus_support(
        records,
        pattern_kind="clinical_design_requirement",
        target_layer={"indication": "类风湿关节炎"},
    )

    assert assessment.high_confidence_eligible is False
    assert assessment.medical_confirmation_required is True
    assert any(
        reason.startswith("target_layer_incomplete:")
        for reason in assessment.reasons
    )


def test_wording_convention_missing_provenance_axes_cannot_be_high_confidence():
    records = [
        {
            "source_file": "ra_a.docx",
            "lead_sponsor": "Sponsor A",
            "claim_value": "拟评价研究药物的有效性和安全性。",
            "pattern_kind": "wording_convention",
            "indication": "类风湿关节炎",
            "phase": "II期",
        },
        {
            "source_file": "ra_b.docx",
            "lead_sponsor": "Sponsor B",
            "claim_value": "拟评价研究药物的有效性和安全性。",
            "pattern_kind": "wording_convention",
            "indication": "类风湿关节炎",
            "phase": "II期",
        },
    ]

    assessment = assess_corpus_support(
        records,
        pattern_kind="wording_convention",
        target_layer={"indication": "类风湿关节炎", "phase": "II期"},
    )

    assert assessment.high_confidence_eligible is False
    assert assessment.medical_confirmation_required is True
    assert any(
        reason.startswith("wording_provenance_axes_not_declared:")
        for reason in assessment.reasons
    )


def test_mixed_pattern_types_must_be_separated_before_generalization():
    records = [
        _typed_record(
            source_file="ra_a.docx",
            sponsor="Sponsor A",
            claim_value="拟评价研究药物的有效性和安全性。",
            pattern_kind="wording_convention",
        ),
        _typed_record(
            source_file="ra_b.docx",
            sponsor="Sponsor B",
            claim_value="主要终点设于第12周。",
            pattern_kind="clinical_design_requirement",
        ),
    ]

    assessment = assess_corpus_support(records, target_layer=_target_layer())

    assert assessment.support_level == "mixed_pattern_types_require_separation"
    assert assessment.high_confidence_eligible is False
    assert "mixed_pattern_types_require_separation" in assessment.reasons


def test_cross_indication_regulatory_common_structure_can_transfer_without_clinical_logic():
    records = [
        _typed_record(
            source_file="ra_a.docx",
            sponsor="Sponsor A",
            claim_value="受试者签署知情同意书前，不得实施任何试验相关程序。",
            pattern_kind="regulatory_common_structure",
        ),
        _typed_record(
            source_file="ad_b.docx",
            sponsor="Sponsor B",
            indication="特应性皮炎",
            phase="III期",
            research_purpose="确证性研究",
            mechanism="IL-13抑制",
            technology_type="单克隆抗体",
            dosage_form="注射液",
            administration_route="皮下注射",
            claim_value="受试者签署知情同意书前，不得实施任何试验相关程序。",
            pattern_kind="regulatory_common_structure",
        ),
    ]

    assessment = assess_corpus_support(
        records,
        pattern_kind="regulatory_common_structure",
        target_layer={"indication": "类风湿关节炎"},
    )

    assert assessment.high_confidence_eligible is True
    assert (
        assessment.generalization_scope
        == "cross_indication_structure_or_regulatory_common_only"
    )


def test_cross_indication_endpoint_is_rejected_even_if_labelled_regulatory_common():
    records = [
        _typed_record(
            source_file="ra_a.docx",
            sponsor="Sponsor A",
            claim_value="受试者签署知情同意书前，不得实施任何试验相关程序。",
            pattern_kind="regulatory_common_structure",
        ),
        _typed_record(
            source_file="ad_b.docx",
            sponsor="Sponsor B",
            indication="特应性皮炎",
            claim_value="主要终点为第16周EASI较基线的变化。",
            pattern_kind="regulatory_common_structure",
        ),
    ]

    assessment = assess_corpus_support(
        records,
        pattern_kind="regulatory_common_structure",
        target_layer={"indication": "类风湿关节炎"},
    )

    assert assessment.high_confidence_eligible is False
    assert assessment.source_count == 1
    assert assessment.counterexamples[0]["source_id"] == "ad_b.docx"
    assert "regulatory_common_structure_contains_clinical_logic" in (
        assessment.counterexamples[0]["reason"]
    )
    assert "cross_indication_clinical_logic_not_transferable" in assessment.reasons


def test_same_indication_endpoint_cannot_be_misclassified_as_regulatory_common():
    assessment = assess_corpus_support(
        [
            _typed_record(
                source_file="ra_a.docx",
                sponsor="Sponsor A",
                claim_value="主要终点为第12周DAS28较基线的变化。",
                pattern_kind="regulatory_common_structure",
            )
        ],
        pattern_kind="regulatory_common_structure",
        target_layer={"indication": "类风湿关节炎"},
    )

    assert assessment.source_count == 0
    assert assessment.high_confidence_eligible is False
    assert assessment.counterexamples[0]["reason"].startswith(
        "regulatory_common_structure_contains_clinical_logic:"
    )


def test_duplicate_document_hash_is_not_counted_as_independent_evidence():
    records = [
        {
            **_typed_record(
                source_file="ra_copy_a.docx",
                sponsor="Sponsor A",
                claim_value="拟评价研究药物的有效性和安全性。",
            ),
            "document_sha256": "same-document-hash",
        },
        {
            **_typed_record(
                source_file="ra_copy_b.docx",
                sponsor="Sponsor B",
                claim_value="拟评价研究药物的有效性和安全性。",
            ),
            "document_sha256": "same-document-hash",
        },
    ]

    assessment = assess_corpus_support(
        records,
        pattern_kind="wording_convention",
        target_layer=_target_layer(),
    )

    assert assessment.source_count == 1
    assert assessment.sponsor_count == 2
    assert assessment.high_confidence_eligible is False
    assert "fewer_than_two_independent_sources" in assessment.reasons


def test_small_indication_sparse_evidence_returns_low_confidence_medical_confirmation():
    assessment = assess_corpus_support(
        [
            _typed_record(
                source_file="rare_a.docx",
                sponsor="Sponsor A",
                indication="阵发性睡眠性血红蛋白尿症",
                phase="II期",
                mechanism="补体抑制",
                technology_type="单克隆抗体",
                dosage_form="注射液",
                administration_route="皮下注射",
                design_module="单臂开放标签",
                claim_value="拟评价研究药物在PNH受试者中的安全性和有效性。",
            )
        ],
        pattern_kind="wording_convention",
        target_layer=_target_layer(
            indication="阵发性睡眠性血红蛋白尿症",
            mechanism="补体抑制",
            technology_type="单克隆抗体",
            dosage_form="注射液",
            administration_route="皮下注射",
            design_module="单臂开放标签",
        ),
    )

    assert assessment.support_level == "single_source_low_strength"
    assert assessment.high_confidence_eligible is False
    assert assessment.medical_confirmation_required is True
    assert "fewer_than_two_independent_sources" in assessment.reasons
    assert "fewer_than_two_sponsors" in assessment.reasons


def test_prompt_contract_forbids_overfit_and_cross_indication_fact_transfer():
    rules = "\n".join(corpus_generalization_prompt_contract())

    for required in (
        "wording_convention",
        "clinical_design_requirement",
        "regulatory_common_structure",
        "表达措辞惯例",
        "临床设计要求",
        "监管共性",
        "来源文件/来源ID",
        "申办方",
        "反例",
        "不得一刀切",
        "研究分期",
        "研究目的",
        "技术类型",
        "剂型",
        "给药途径",
        "疾病活动度",
        "终点",
        "背景治疗",
        "洗脱期",
        "安全性风险",
        "访视",
        "单一来源",
        "两个申办方",
        "小适应症",
        "低置信候选",
        "待医学确认",
        "unresolved_gaps",
        "多份方案",
        "均采用",
        "同疾病领域或相近研究设计",
        "结构模板、监管固定语、适应症特异措辞和项目事实参照",
        "常用",
        "corpus override",
    ):
        assert required in rules


# ---------------------------------------------------------------------------
# Cluster B (G3/G4/G5) — facet taxonomy precision
# ---------------------------------------------------------------------------

import pytest

from services.api.app.medical_writing_corpus_policy import (
    _facet_concepts as _fc,
    _layer_match_tokens,
)


# ---- S4: injection routes remain distinct (G3) ----

_SC_IV_IM_PAIRS = [
    # (source_value, target_value, description)
    ("皮下注射", "静脉注射", "SC vs IV (Chinese)"),
    ("皮下", "静脉", "SC vs IV short (Chinese)"),
    ("肌内注射", "皮下注射", "IM vs SC (Chinese)"),
    ("肌内", "静脉", "IM vs IV short (Chinese)"),
    ("subcutaneous", "intravenous", "SC vs IV (English)"),
    ("intramuscular", "subcutaneous", "IM vs SC (English)"),
    ("intramuscular", "intravenous", "IM vs IV (English)"),
]


@pytest.mark.parametrize("source_value, target_value, description", _SC_IV_IM_PAIRS)
def test_injection_routes_remain_distinct_for_typed_support(source_value, target_value, description):
    """G3: SC, IV, IM are clinically distinct and must not share the same
    high-confidence concept token."""
    source_tokens = _layer_match_tokens("administration_route", (source_value,))
    target_tokens = _layer_match_tokens("administration_route", (target_value,))
    assert source_tokens, f"source '{source_value}' produced no tokens"
    assert target_tokens, f"target '{target_value}' produced no tokens"
    assert source_tokens.isdisjoint(target_tokens), (
        f"{description}: '{source_value}' and '{target_value}' collapsed to "
        f"shared token(s) {source_tokens & target_tokens}"
    )


@pytest.mark.parametrize(
    "generic_value",
    ["注射", "injection", "注射液", "注射给药"],
)
def test_generic_injection_label_does_not_prove_specific_route(generic_value):
    """A generic 'injection' label must not activate a specific route subtype."""
    concepts = _fc("route", generic_value)
    assert not any(
        c in concepts
        for c in ("subcutaneous", "intravenous", "intramuscular")
    ), f"Generic '{generic_value}' activated specific route subtype(s): {concepts}"


# ---- S5: modality subclasses do not share high confidence (G4) ----

_MODALITY_DISTINCT_PAIRS = [
    ("siRNA", "mRNA", "siRNA vs mRNA"),
    ("siRNA", "寡核苷酸", "siRNA vs oligonucleotide (broad)"),
    ("mRNA", "寡核苷酸", "mRNA vs oligonucleotide (broad)"),
    ("单克隆抗体", "ADC", "mAb vs ADC (Chinese acronym)"),
    ("monoclonal antibody", "antibody-drug conjugate", "mAb vs ADC (English)"),
    ("细胞治疗", "基因治疗", "cell vs gene therapy"),
    ("cell therapy", "gene therapy", "cell vs gene therapy (English)"),
    ("CAR-T", "单克隆抗体", "CAR-T vs naked mAb"),
]


@pytest.mark.parametrize("source_value, target_value, description", _MODALITY_DISTINCT_PAIRS)
def test_modality_subclasses_do_not_share_high_confidence(source_value, target_value, description):
    """G4: mRNA/siRNA/oligo, cell/gene, mAb/ADC are clinically distinct."""
    source_tokens = _layer_match_tokens("technology_type", (source_value,))
    target_tokens = _layer_match_tokens("technology_type", (target_value,))
    assert source_tokens, f"source '{source_value}' produced no tokens"
    assert target_tokens, f"target '{target_value}' produced no tokens"
    assert source_tokens.isdisjoint(target_tokens), (
        f"{description}: '{source_value}' and '{target_value}' collapsed to "
        f"shared token(s) {source_tokens & target_tokens}"
    )


@pytest.mark.parametrize(
    "generic_value",
    ["RNA", "RNA therapy", "rna"],
)
def test_generic_rna_label_does_not_prove_specific_modality(generic_value):
    """A generic 'RNA' label must not prove siRNA, mRNA, or oligonucleotide."""
    concepts = _fc("modality", generic_value)
    assert not any(
        c in concepts for c in ("sirna", "mrna", "oligonucleotide")
    ), f"Generic '{generic_value}' activated specific modality subtype(s): {concepts}"


# ---- S6: dosage forms remain distinct (G5) ----

_DOSAGE_DISTINCT_PAIRS = [
    ("片剂", "胶囊", "tablet vs capsule (Chinese)"),
    ("tablet", "capsule", "tablet vs capsule (English)"),
    ("乳膏", "软膏", "cream vs ointment (Chinese)"),
    ("cream", "ointment", "cream vs ointment (English)"),
]


@pytest.mark.parametrize("source_value, target_value, description", _DOSAGE_DISTINCT_PAIRS)
def test_dosage_forms_remain_distinct_for_typed_support(source_value, target_value, description):
    """G5: tablet/capsule and cream/ointment are clinically distinct."""
    source_tokens = _layer_match_tokens("dosage_form", (source_value,))
    target_tokens = _layer_match_tokens("dosage_form", (target_value,))
    assert source_tokens, f"source '{source_value}' produced no tokens"
    assert target_tokens, f"target '{target_value}' produced no tokens"
    assert source_tokens.isdisjoint(target_tokens), (
        f"{description}: '{source_value}' and '{target_value}' collapsed to "
        f"shared token(s) {source_tokens & target_tokens}"
    )


# ---- S4b/S5b: same-subtype Chinese/English still match ----

_SAME_SUBTYPE_PAIRS = [
    # route
    ("administration_route", "皮下注射", "subcutaneous injection"),
    ("administration_route", "静脉注射", "intravenous injection"),
    ("administration_route", "肌内注射", "intramuscular injection"),
    # modality
    ("technology_type", "siRNA", "small interfering RNA"),
    ("technology_type", "单克隆抗体", "monoclonal antibody"),
    ("technology_type", "细胞治疗", "cell therapy"),
    ("technology_type", "基因治疗", "gene therapy"),
    # dosage_form
    ("dosage_form", "片剂", "tablet"),
    ("dosage_form", "胶囊", "capsule"),
    ("dosage_form", "乳膏", "cream"),
    ("dosage_form", "软膏", "ointment"),
]


@pytest.mark.parametrize("axis, zh_value, en_value", _SAME_SUBTYPE_PAIRS)
def test_same_subtype_chinese_english_pairs_still_match(axis, zh_value, en_value):
    """Positive: Chinese and English expressions of the same exact subtype
    must still produce overlapping concept tokens."""
    zh_tokens = _layer_match_tokens(axis, (zh_value,))
    en_tokens = _layer_match_tokens(axis, (en_value,))
    assert zh_tokens, f"Chinese '{zh_value}' produced no tokens"
    assert en_tokens, f"English '{en_value}' produced no tokens"
    assert not zh_tokens.isdisjoint(en_tokens), (
        f"Same-subtype pair ({zh_value} / {en_value}) on {axis} "
        f"produced disjoint tokens: {zh_tokens} vs {en_tokens}"
    )


@pytest.mark.parametrize(
    "combined_phase,single_phase",
    [
        ("Phase I/II", "Phase II"),
        ("Phase II/III", "Phase III"),
        ("Phase IIa/IIb", "Phase IIb"),
    ],
)
def test_combined_phase_requires_stage_specific_binding(
    combined_phase,
    single_phase,
):
    """G6: a study-level combined phase cannot lend every Part to a span."""
    combined_tokens = _layer_match_tokens("phase", (combined_phase,))
    single_tokens = _layer_match_tokens("phase", (single_phase,))

    assert combined_tokens
    assert single_tokens
    assert combined_tokens.isdisjoint(single_tokens), (
        f"{combined_phase} collapsed into {single_phase}: "
        f"{combined_tokens & single_tokens}"
    )


@pytest.mark.parametrize(
    "combined_phase",
    ["Phase I/II", "Phase II/III", "Phase IIa/IIb"],
)
def test_same_combined_phase_expression_remains_matchable(combined_phase):
    """G6 positive: the exact same combined framework can still be reused."""
    left = _layer_match_tokens("phase", (combined_phase,))
    right = _layer_match_tokens("phase", (combined_phase,))

    assert left
    assert left == right


def test_multiple_phase_values_are_a_combined_framework_not_independent_parts():
    """G6: ClinicalTrials.gov phase arrays cannot lend one Part by overlap."""
    combined_tokens = _layer_match_tokens(
        "phase",
        ("PHASE1", "PHASE2"),
    )
    phase_two_tokens = _layer_match_tokens("phase", ("PHASE2",))

    assert combined_tokens == {"combined:1+2"}
    assert combined_tokens.isdisjoint(phase_two_tokens)


def test_combined_phase_can_match_only_through_explicit_part_binding():
    """G6 positive: explicit Part metadata binds wording to one stage."""
    records = []
    for source_file, sponsor in (
        ("ra_i_ii_part_b_a.docx", "Sponsor A"),
        ("ra_i_ii_part_b_b.docx", "Sponsor B"),
    ):
        record = _typed_record(
            source_file=source_file,
            sponsor=sponsor,
            phase="Phase I/II",
            claim_value="拟评价研究药物在患者中的有效性和安全性。",
        )
        record["layer"]["phase_part"] = "Phase II"
        records.append(record)

    assessment = assess_corpus_support(
        records,
        pattern_kind="wording_convention",
        target_layer=_target_layer(phase="Phase II"),
    )

    assert assessment.high_confidence_eligible is True
    assert assessment.source_count == 2
    assert not assessment.counterexamples


def test_project_policy_combined_phase_does_not_match_single_phase_target():
    """G6: source-policy ranking follows the same no-cross-Part rule."""
    policy = _policy(phase_terms=("Phase I/II", "Phase 1/2"))

    single_score, single_reason = project_match_score(
        policy,
        "类风湿关节炎",
        "Phase II",
    )
    combined_score, combined_reason = project_match_score(
        policy,
        "类风湿关节炎",
        "Phase I/II",
    )

    assert single_score == 0.65
    assert "phase_mismatch" in single_reason
    assert combined_score == 1.0
    assert "matched_phase:combined:1+2" in combined_reason



# ---------------------------------------------------------------------------
# Cluster C — regulatory_common_structure axis-independence (delta 20260727)
# ---------------------------------------------------------------------------


def test_regulatory_common_structure_transfers_despite_mechanism_mismatch():
    """GCP/ethics boilerplate must not be blocked by mechanism mismatch.

    Before the 20260727 fix, assess_corpus_support stripped only the
    indication axis from the comparison target for regulatory_common_structure.
    A GCP clause from an IL-13 AD protocol was counterexampled against a TNF
    RA target because mechanism differed, even though the clause is
    design-axis-independent.
    """
    records = [
        _typed_record(
            source_file="ad_protocol_A.docx",
            sponsor="Sponsor AD",
            indication="特应性皮炎",
            phase="III期",
            research_purpose="确证性研究",
            mechanism="IL-13抑制",
            technology_type="单克隆抗体",
            dosage_form="注射液",
            administration_route="皮下注射",
            claim_value="本研究遵循ICH-GCP E6(R2)和赫尔辛基宣言。",
            pattern_kind="regulatory_common_structure",
        ),
        _typed_record(
            source_file="onc_protocol_A.docx",
            sponsor="Sponsor Onc",
            indication="非小细胞肺癌",
            phase="II期",
            research_purpose="概念验证",
            mechanism="PD-1抑制",
            technology_type="单克隆抗体",
            dosage_form="注射液",
            administration_route="静脉注射",
            claim_value="本研究遵循ICH-GCP E6(R2)和赫尔辛基宣言。",
            pattern_kind="regulatory_common_structure",
        ),
    ]
    assessment = assess_corpus_support(
        records,
        pattern_kind="regulatory_common_structure",
        target_layer={
            "indication": "类风湿关节炎",
            "phase": "III期",
            "research_purpose": "确证性研究",
            "mechanism": "TNF抑制",
            "technology_type": "单克隆抗体",
            "dosage_form": "注射液",
            "administration_route": "皮下注射",
            "design_module": "随机双盲安慰剂对照",
        },
    )
    assert assessment.high_confidence_eligible is True
    assert assessment.source_count == 2
    assert assessment.sponsor_count == 2
    assert not assessment.counterexamples
    assert (
        assessment.generalization_scope
        == "cross_indication_structure_or_regulatory_common_only"
    )


def test_regulatory_common_structure_transfers_despite_phase_and_route_mismatch():
    """Phase I oral source must not block a GCP clause for Phase III SC target."""
    records = [
        _typed_record(
            source_file="ra_p1_oral_A.docx",
            sponsor="Sponsor A",
            indication="类风湿关节炎",
            phase="I期",
            research_purpose="首次人体",
            mechanism="JAK抑制",
            technology_type="小分子",
            dosage_form="片剂",
            administration_route="口服",
            claim_value="受试者签署知情同意书前，不得实施任何试验相关程序。",
            pattern_kind="regulatory_common_structure",
        ),
        _typed_record(
            source_file="ad_p3_sc_B.docx",
            sponsor="Sponsor B",
            indication="特应性皮炎",
            phase="III期",
            research_purpose="确证性研究",
            mechanism="IL-4/IL-13抑制",
            technology_type="单克隆抗体",
            dosage_form="注射液",
            administration_route="皮下注射",
            claim_value="受试者签署知情同意书前，不得实施任何试验相关程序。",
            pattern_kind="regulatory_common_structure",
        ),
    ]
    assessment = assess_corpus_support(
        records,
        pattern_kind="regulatory_common_structure",
        target_layer={
            "indication": "类风湿关节炎",
            "phase": "III期",
            "research_purpose": "确证性研究",
            "mechanism": "TNF抑制",
            "technology_type": "单克隆抗体",
            "dosage_form": "注射液",
            "administration_route": "皮下注射",
            "design_module": "随机双盲安慰剂对照",
        },
    )
    assert assessment.high_confidence_eligible is True
    assert assessment.source_count == 2
    assert not assessment.counterexamples


def test_regulatory_common_structure_clinical_logic_still_blocked_after_axis_relaxation():
    """Endpoint/disease-activity content must remain blocked even though
    axis comparison is now fully relaxed for regulatory_common_structure."""
    records = [
        _typed_record(
            source_file="ra_a.docx",
            sponsor="Sponsor A",
            indication="类风湿关节炎",
            phase="III期",
            mechanism="TNF抑制",
            claim_value="主要终点为第24周ACR20应答率。",
            pattern_kind="regulatory_common_structure",
        ),
        _typed_record(
            source_file="ra_b.docx",
            sponsor="Sponsor B",
            indication="类风湿关节炎",
            phase="III期",
            mechanism="IL-6抑制",
            claim_value="主要终点为第24周ACR20应答率。",
            pattern_kind="regulatory_common_structure",
        ),
    ]
    assessment = assess_corpus_support(
        records,
        pattern_kind="regulatory_common_structure",
        target_layer={
            "indication": "特应性皮炎",
            "phase": "III期",
            "mechanism": "JAK抑制",
        },
    )
    assert assessment.high_confidence_eligible is False
    assert "cross_indication_clinical_logic_not_transferable" in assessment.reasons
    assert len(assessment.counterexamples) == 2
