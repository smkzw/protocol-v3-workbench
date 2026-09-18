"""Three-state predicates preserve uncertainty; no natural-language inference."""
from itertools import product

import pytest


@pytest.mark.parametrize("value,expected", [
    (True, "applicable"), (False, "not_applicable"),
    (None, "conditional"), ("false", "conditional"),
    (0, "conditional"), ({}, "conditional"),
])
def test_boolean_predicate_does_not_infer_from_truthiness(value, expected):
    from app.protocol_workflow.registries.applicability import FactPredicate, evaluate_predicate
    predicate = FactPredicate(fact_path="statistics.interim.applicable", expected=True)
    result = evaluate_predicate(predicate, {"statistics.interim.applicable": value})
    assert result.value == expected


def test_missing_condition_is_unresolved_not_false():
    from app.protocol_workflow.registries.applicability import FactPredicate, evaluate_predicate
    assert evaluate_predicate(FactPredicate(fact_path="a.b", expected=True), {}).value == "conditional"


def test_dotted_canonical_key_and_explicit_object_member_are_distinct():
    from app.protocol_workflow.registries.applicability import FactPredicate, evaluate_predicate
    predicate = FactPredicate(fact_path="a.b", members=("applicable",), expected=True)
    assert evaluate_predicate(predicate, {"a.b": {"applicable": False}}).value == "not_applicable"
    assert evaluate_predicate(predicate, {"a": {"b": {"applicable": True}}}).value == "conditional"
    assert evaluate_predicate(predicate, {"a.b": {"other": True}}).value == "conditional"


@pytest.mark.parametrize("mode,values,expected", [
    ("any", [False, False], "not_applicable"),
    ("any", [False, None], "conditional"),
    ("any", [True, None], "applicable"),
    ("all", [True, True], "applicable"),
    ("all", [True, None], "conditional"),
    ("all", [False, None], "not_applicable"),
])
def test_multiple_triggers_have_explicit_three_state_combination(mode, values, expected):
    from app.protocol_workflow.registries.applicability import FactPredicate, evaluate_predicates
    predicates = tuple(FactPredicate(fact_path=f"fact:{i}", expected=True) for i in range(len(values)))
    facts = {f"fact:{i}": value for i, value in enumerate(values)}
    assert evaluate_predicates(predicates, facts, mode=mode).value == expected


def test_empty_predicate_set_cannot_claim_applicability():
    from app.protocol_workflow.registries.applicability import evaluate_predicates
    with pytest.raises(ValueError, match="non-empty"):
        evaluate_predicates((), {}, mode="all")


@pytest.mark.parametrize("value,code", [(True, "missing_conditional_fact"), (False, None), (None, "conditional_applicability_unresolved")])
def test_actual_content_checker_executes_rule_from_canonical_facts(value, code):
    from app.protocol_workflow.registries.applicability import FactPredicate, RulePredicate, evaluate_applicable_content
    from app.protocol_workflow.registries.chapters import ChapterContentPayload
    from test_all_chapter_contracts import _objectives_contract, _objectives_positive_content
    from test_chapter_fact_binding import confirmed_study
    contract = _objectives_contract(conditional_applicability_rules=({
        "conditional_applicability_rule_id": "condition:test-extra",
        "triggering_fact_paths": ("test.extra_applicable",),
        "condition": "Synthetic condition for checker behavior",
        "rationale": "Synthetic test, not a scientific predicate",
        "required_when_active_fact_paths": ("test.extra_detail",),
    },))
    predicate = RulePredicate(rule_id="condition:test-extra", source_rule_sha256=contract.conditional_applicability_rules[0].material_sha256(),
                              predicates=(FactPredicate(fact_path="test.extra_applicable", expected=True),))
    study = confirmed_study({"test.extra_applicable": value})
    result = evaluate_applicable_content(contract, ChapterContentPayload.model_validate(_objectives_positive_content()),
                                         study=study, rules=(predicate,), subject_id="test:actual-checker")
    if code:
        assert code in result.error_codes()
        assert not result.passed
    else:
        assert result.passed
    assert not any("conditional_applicability_not_executed" in x for x in result.deferred_qc_obligations)


def test_conditional_claim_source_and_object_are_enforced_by_same_checker():
    from app.protocol_workflow.registries.applicability import FactPredicate, RulePredicate, evaluate_applicable_content
    from app.protocol_workflow.registries.chapters import ChapterContentPayload
    from test_all_chapter_contracts import _objectives_contract, _objectives_positive_content
    from test_chapter_fact_binding import confirmed_study
    contract = _objectives_contract(conditional_applicability_rules=({
        "conditional_applicability_rule_id": "condition:test-obligations",
        "triggering_fact_paths": ("test.extra_applicable",),
        "condition": "Synthetic condition",
        "rationale": "Test all declared obligation families",
        "required_when_active_claim_types": ("test.extra_claim",),
        "required_when_active_source_roles": ("peer_reviewed",),
        "required_when_active_structural_objects": ("figure",),
    },))
    declaration = RulePredicate(rule_id="condition:test-obligations",
                                source_rule_sha256=contract.conditional_applicability_rules[0].material_sha256(),
                                predicates=(FactPredicate(fact_path="test.extra_applicable", expected=True),))
    content = ChapterContentPayload.model_validate(_objectives_positive_content())
    result = evaluate_applicable_content(contract, content, study=confirmed_study({"test.extra_applicable": True}),
                                         rules=(declaration,), subject_id="test:obligations")
    assert {"missing_conditional_claim", "missing_conditional_source", "missing_conditional_object"} <= set(result.error_codes())
    inactive = evaluate_applicable_content(contract, content, study=confirmed_study({"test.extra_applicable": False}),
                                           rules=(declaration,), subject_id="test:inactive")
    assert inactive.passed
    unresolved = evaluate_applicable_content(contract, content, study=confirmed_study({"other": True}),
                                             rules=(declaration,), subject_id="test:unknown")
    assert "conditional_applicability_unresolved" in unresolved.error_codes()
    stale = declaration.model_copy(update={"source_rule_sha256": "0" * 64})
    result = evaluate_applicable_content(contract, content, study=confirmed_study({"test.extra_applicable": True}),
                                         rules=(stale,), subject_id="test:changed-source")
    assert "conditional_predicate_source_changed" in result.error_codes()


def test_nonfinite_value_does_not_resolve_a_condition():
    from app.protocol_workflow.registries.applicability import FactPredicate, evaluate_predicate
    assert evaluate_predicate(FactPredicate(fact_path="test.value", expected=1.0), {"test.value": float("nan")}).value == "conditional"


def interim_case():
    import json
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from app.protocol_workflow.registries.applicability import FactPredicate, RulePredicate
    contract = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / "chapter_contracts/v2_n_11_4_9.json").read_text())
    rule = contract.conditional_applicability_rules[0]
    declaration = next(r for r in real_rule_catalog().rules
                       if r.rule_id == rule.conditional_applicability_rule_id)
    return contract, declaration


def test_real_no_interim_needs_disposition_not_eleven_details_or_table():
    from app.protocol_workflow.registries.applicability import evaluate_applicable_content
    from app.protocol_workflow.registries.chapters import ChapterContentPayload
    from test_chapter_fact_binding import confirmed_study
    contract, declaration = interim_case()
    content = ChapterContentPayload.model_validate({
        "facts": [{"fact_path": "statistics.interim.applicable", "value": False}],
        "claims": [{"claim_type": "interim_not_planned", "statement": "本研究不计划开展期中分析。"}],
        "evidence": [{"source_role": "project_primary", "admission_claim_type": "interim_not_planned",
                      "locator_kind": "body", "locator": "test:synthetic-confirmed-design",
                      "context": "合成测试确认不进行期中分析，非真实项目批准。", "quality_score": 1.0}],
    })
    result = evaluate_applicable_content(contract, content,
                                         study=confirmed_study({"statistics.interim.applicable": False}),
                                         rules=real_rule_catalog().rules, subject_id="test:no-interim")
    assert result.passed, result.error_codes()
    assert "statistics.interim.canonical_reference" in declaration.conditional_fact_paths
    assert not content.objects



@pytest.mark.parametrize("flag", [False, True, None])
def test_real_interim_conflict_active_and_unresolved_are_distinct(flag):
    from app.protocol_workflow.registries.applicability import evaluate_applicable_content
    from app.protocol_workflow.registries.chapters import ChapterContentPayload
    from test_chapter_fact_binding import confirmed_study
    contract, declaration = interim_case()
    content = ChapterContentPayload.model_validate({"facts": [
        {"fact_path": "statistics.interim.applicable", "value": flag},
        {"fact_path": "statistics.interim.timing", "value": "synthetic event threshold"},
        {"fact_path": "statistics.interim.canonical_reference", "value": "synthetic chapter link"},
    ]})
    result = evaluate_applicable_content(contract, content,
                                         study=confirmed_study({"statistics.interim.applicable": flag}),
                                         rules=real_rule_catalog().rules, subject_id="test:interim-states")
    codes = result.error_codes()
    assert not result.passed
    if flag is False:
        conflicts = {f.location for f in result.findings if f.code == "inactive_conditional_fact_present"}
        assert conflicts == {"statistics.interim.timing", "statistics.interim.canonical_reference"}
        assert "missing_conditional_fact" not in codes
    elif flag is True:
        assert "missing_conditional_fact" in codes
        assert "inactive_conditional_fact_present" not in codes
    else:
        assert "conditional_applicability_unresolved" in codes
        assert "inactive_conditional_fact_present" not in codes



def test_no_interim_can_reach_actual_skill_input_without_inactive_parameters():
    from app.protocol_workflow.registries.applicability import bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    contract, declaration = interim_case()
    bindings = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR / "fact_bindings.json").read_text()).bindings
    bound = bind_applicable_input(confirmed_study({"statistics.interim.applicable": False}), contract, bindings, rules=real_rule_catalog().rules)
    assert bound.resolved_facts == {"statistics.interim.applicable": False}
    assert bound.active_conditional_rule_ids == ()
    assert bound.applicability_rules_sha256 is not None
    with pytest.raises(FactBindingError, match="missing_required_fact"):
        bind_applicable_input(confirmed_study({"statistics.interim.applicable": True, "statistics.interim.features": {"information_fraction": True, "efficacy_testing": True, "idmc_review": True}, "irc.applicable": True}), contract, bindings, rules=real_rule_catalog().rules)
    with pytest.raises(ApplicabilityResolutionError, match="conditional_applicability_unresolved"):
        bind_applicable_input(confirmed_study({"statistics.interim.applicable": None}), contract, bindings, rules=real_rule_catalog().rules)
    with pytest.raises(ApplicabilityResolutionError, match="inactive_conditional_fact_present"):
        bind_applicable_input(confirmed_study({"statistics.interim.applicable": False, "statistics.interim.timing": "stale timing"}),
                              contract, bindings, rules=real_rule_catalog().rules)



def test_bound_no_interim_output_is_checked_against_same_facts_and_rules():
    from app.protocol_workflow.registries.applicability import bind_applicable_input, check_applicable_output
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from app.protocol_workflow.registries.chapters import ChapterSkillOutput
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    contract, declaration = interim_case()
    bindings = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR / "fact_bindings.json").read_text()).bindings
    study = confirmed_study({"statistics.interim.applicable": False})
    bound = bind_applicable_input(study, contract, bindings, rules=real_rule_catalog().rules)
    payload = {
        "chapter_contract_id": contract.chapter_contract_id, "node_id": contract.semantic_node_id,
        "facts": [{"fact_path": "statistics.interim.applicable", "value": False}],
        "claims": [{"claim_type": "interim_not_planned", "statement": "本研究不计划开展期中分析。"}],
        "evidence": [{"source_role": "project_primary", "admission_claim_type": "interim_not_planned", "locator_kind": "body",
                      "locator": "test:confirmed-design", "context": "Synthetic approved-design fixture only", "quality_score": 1.0}],
    }
    output = ChapterSkillOutput.model_validate(payload)
    result = check_applicable_output(bound, output, study, contract, bindings, rules=real_rule_catalog().rules)
    assert result.passed
    assert "medical_and_qc_judgment_not_executed" in result.deferred_qc_obligations
    empty = output.model_copy(update={"facts": ()})
    assert "missing_required_fact" in check_applicable_output(bound, empty, study, contract, bindings, rules=real_rule_catalog().rules).error_codes()
    changed_rule = declaration.model_copy(update={"mode": "any"})
    with pytest.raises(FactBindingError, match="chapter_input_binding_mismatch"):
        check_applicable_output(bound, output, study, contract, bindings, rules=tuple(changed_rule if item.rule_id == changed_rule.rule_id else item for item in real_rule_catalog().rules))



@pytest.mark.parametrize("value,status", [(False, "applicable"), (None, "conditional")])
def test_existing_snapshot_distinguishes_chapter_presence_from_inner_condition(value, status):
    from datetime import datetime, timezone
    from app.protocol_workflow.registries.applicability import build_applicability_snapshot
    from packages.contracts.workbench_contracts.protocol_v3 import ApplicabilitySnapshot
    from app.protocol_workflow.canonical.study_definition import study_revision_hash
    from test_chapter_fact_binding import confirmed_study
    contract, rule = interim_case()
    study = confirmed_study({"statistics.interim.applicable": value})
    snapshot = build_applicability_snapshot((contract,), study, real_rule_catalog().rules, created_at=datetime(2026, 9, 13, tzinfo=timezone.utc))
    reopened = ApplicabilitySnapshot.model_validate_json(snapshot.model_dump_json())
    assert reopened.entries[0].semantic_node_id == contract.semantic_node_id
    assert reopened.entries[0].status.value == status
    assert reopened.study_definition_sha256 == study_revision_hash(study)



def test_explicit_whole_appendix_condition_can_exclude_ecog():
    from datetime import datetime, timezone
    from app.protocol_workflow.registries.applicability import FactPredicate, RulePredicate, build_applicability_snapshot
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    contract = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / "chapter_contracts/v2_n_16_x1.json").read_text())
    source_rule = contract.conditional_applicability_rules[0]
    rule = RulePredicate(rule_id=source_rule.conditional_applicability_rule_id,
                          source_rule_sha256=source_rule.material_sha256(), source_contract_sha256=contract.material_sha256(),
                          predicates=(FactPredicate(fact_path="appendix.ecog_assessment_applicable", expected=True),),
                          affects_chapter_presence=True)
    snapshot = build_applicability_snapshot((contract,), confirmed_study({"appendix.ecog_assessment_applicable": False}),
                                             (rule,), created_at=datetime(2026, 9, 13, tzinfo=timezone.utc))
    assert snapshot.entries[0].status.value == "not_applicable"


def test_interim_reference_resolves_to_real_oversight_node_before_generation():
    from app.protocol_workflow.registries.applicability import bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    contract, rule = interim_case()
    facts = {item.fact_path: "synthetic detail" for item in contract.substantive_content.fact_requirements if item.obligation.value == "required"}
    facts["statistics.interim.applicable"] = True
    facts["statistics.interim.features"] = {"information_fraction": True, "efficacy_testing": True, "idmc_review": True}
    facts["irc.applicable"] = True
    facts["statistics.interim.canonical_reference"] = "v2_n_13_x"
    bindings = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR / "fact_bindings.json").read_text()).bindings
    with pytest.raises(ApplicabilityResolutionError, match="unresolved_reference_target"):
        bind_applicable_input(confirmed_study(facts), contract, bindings, rules=real_rule_catalog().rules)
    facts["statistics.interim.canonical_reference"] = "v2_n_14_7"
    result = bind_applicable_input(confirmed_study(facts), contract, bindings, rules=real_rule_catalog().rules)
    assert result.resolved_facts["statistics.interim.canonical_reference"] == "v2_n_14_7"
    assert (REAL_TEMPLATE_DIR / "chapter_contracts/v2_n_14_7.json").is_file()
    assert "v2_n_13_x" not in " ".join(contract.substantive_content.project_specific_elements)



@pytest.mark.parametrize("flags,keep,error", [
    ((True, False), True, None),
    ((False, True), True, None),
    ((False, False), False, None),
    ((True, None), True, "conditional_applicability_unresolved"),
    ((False, None), False, "conditional_applicability_unresolved"),
])
def test_shared_fact_obligation_survives_any_active_analysis(flags, keep, error):
    from app.protocol_workflow.registries.applicability import (
        FactPredicate, RulePredicate, evaluate_applicable_content,
    )
    from app.protocol_workflow.registries.chapters import ChapterContentPayload
    from test_all_chapter_contracts import _objectives_contract, _objectives_positive_content
    from test_chapter_fact_binding import confirmed_study
    shared = "picos.objective.primary"
    contract = _objectives_contract(conditional_applicability_rules=tuple({
        "conditional_applicability_rule_id": f"condition:shared-{i}",
        "triggering_fact_paths": (f"test.analysis.{i}",),
        "condition": "Synthetic shared analysis requirement",
        "rationale": "Both independent analyses use the same source fact",
        "required_when_active_fact_paths": (shared,),
    } for i in range(2)))
    declarations = tuple(RulePredicate(
        rule_id=rule.conditional_applicability_rule_id,
        source_rule_sha256=rule.material_sha256(),
        source_contract_sha256=contract.material_sha256(),
        predicates=(FactPredicate(fact_path=f"test.analysis.{i}", expected=True),),
        conditional_fact_paths=(shared,),
    ) for i, rule in enumerate(contract.conditional_applicability_rules))
    payload = _objectives_positive_content()
    if not keep:
        payload["facts"] = [f for f in payload["facts"] if f["fact_path"] != shared]
    result = evaluate_applicable_content(
        contract, ChapterContentPayload.model_validate(payload),
        study=confirmed_study({f"test.analysis.{i}": flag for i, flag in enumerate(flags)}),
        rules=declarations, subject_id="test:shared-analysis")
    if error:
        assert error in result.error_codes()
        assert not result.passed
    else:
        assert result.passed, result.error_codes()
    assert "inactive_conditional_fact_present" not in result.error_codes()


def test_no_temporary_hold_still_requires_permanent_and_trial_stop_facts():
    from app.protocol_workflow.registries.applicability import FactPredicate, RulePredicate, bind_applicable_input
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    contract = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / "chapter_contracts/v2_n_8_1.json").read_text())
    declarations = real_rule_catalog().rules
    bindings = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR / "fact_bindings.json").read_text()).bindings
    facts = {f.fact_path: "synthetic confirmed parameter" for f in contract.substantive_content.fact_requirements
             if f.obligation.value == "required" and f.fact_path not in {"discontinuation.individual_hold_criteria", "discontinuation.personal_hold"}}
    facts.update({rule.triggering_fact_paths[0]: False for rule in contract.conditional_applicability_rules})
    bound = bind_applicable_input(confirmed_study(facts), contract, bindings, rules=declarations)
    assert "discontinuation.individual_hold_criteria" not in bound.resolved_facts
    assert "discontinuation.permanent_stop_recording" in bound.resolved_facts
    assert "discontinuation.trial_stop_decision_authority" in bound.resolved_facts
    del facts["discontinuation.permanent_stop_recording"]
    with pytest.raises(FactBindingError, match="missing_required_fact") as caught:
        bind_applicable_input(confirmed_study(facts), contract, bindings, rules=declarations)
    assert "discontinuation.permanent_stop_recording" in caught.value.fact_paths


@pytest.mark.parametrize("confirmatory,with_link,expected_error", [
    (False, False, None), (True, False, "missing_required_fact"),
    (None, False, "conditional_applicability_unresolved"), (True, True, None),
])
def test_real_exploratory_pk_does_not_require_confirmatory_link(confirmatory, with_link, expected_error):
    from app.protocol_workflow.registries.applicability import (
        FactPredicate, RulePredicate, bind_applicable_input, ApplicabilityResolutionError,
    )
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    contract = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / "chapter_contracts/v2_n_11_4_6.json").read_text())
    declarations = real_rule_catalog().rules
    bindings = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR / "fact_bindings.json").read_text()).bindings
    facts = {f.fact_path: "synthetic confirmed analysis" for f in contract.substantive_content.fact_requirements
             if f.obligation.value == "required"}
    facts.update({f"statistics.pk_pd_er.{kind}_applicable": kind == "pk" for kind in ("pk", "pd", "er")})
    facts["statistics.pk_pd_er.pk_confirmatory"] = confirmatory
    if with_link:
        facts["statistics.pk_pd_er.confirmatory_analysis_link"] = {"pk": "contract:v2-n-11-4-3-1:v2"}
    # Inactive PD/E-R do not require a made-up purpose decision.
    if expected_error:
        with pytest.raises((FactBindingError, ApplicabilityResolutionError), match=expected_error):
            bind_applicable_input(confirmed_study(facts), contract, bindings, rules=declarations)
    else:
        bound = bind_applicable_input(confirmed_study(facts), contract, bindings, rules=declarations)
        assert ("statistics.pk_pd_er.confirmatory_analysis_link" in bound.resolved_facts) is with_link


def real_rule_catalog():
    from app.protocol_workflow.registries.applicability import load_applicability_rules
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    contracts = tuple(ChapterContractV2.model_validate_json(p.read_text())
                      for p in sorted((REAL_TEMPLATE_DIR / "chapter_contracts").glob("*.json")))
    return load_applicability_rules(REAL_TEMPLATE_DIR / "applicability_rules.json", contracts)


def test_product_rules_allow_no_pk_pd_er_without_fabricated_sampling_or_purpose():
    from app.protocol_workflow.registries.applicability import bind_applicable_input
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / "chapter_contracts/v2_n_11_4_6.json").read_text())
    facts = {"statistics.exploratory_analysis." + key: "synthetic other exploratory analysis"
             for key in ("endpoints", "methods", "data_definition")}
    facts.update({f"statistics.pk_pd_er.{k}_applicable": False for k in ("pk", "pd", "er")})
    bindings = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR / "fact_bindings.json").read_text()).bindings
    result = bind_applicable_input(confirmed_study(facts), c, bindings, rules=real_rule_catalog().rules)
    assert dict(result.resolved_facts) == facts
    assert result.active_conditional_rule_ids == ()


@pytest.mark.parametrize("node", ["v2_n_14_1", "v2_n_14_3", "v2_n_15"])
@pytest.mark.parametrize("flag", [False, True, None])
def test_product_optional_plans_preserve_base_and_require_only_active_details(node, flag):
    from app.protocol_workflow.registries.applicability import bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / f"chapter_contracts/{node}.json").read_text())
    rule = c.conditional_applicability_rules[0]
    facts = {f.fact_path: "synthetic confirmed base arrangement" for f in c.substantive_content.fact_requirements
             if f.obligation.value == "required"}
    facts[rule.triggering_fact_paths[0]] = flag
    bindings = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR / "fact_bindings.json").read_text()).bindings
    if flag is False:
        result = bind_applicable_input(confirmed_study(facts), c, bindings, rules=real_rule_catalog().rules)
        assert dict(result.resolved_facts) == facts
    elif flag is True:
        with pytest.raises(FactBindingError, match="missing_required_fact") as caught:
            bind_applicable_input(confirmed_study(facts), c, bindings, rules=real_rule_catalog().rules)
        assert set(caught.value.fact_paths) == set(rule.required_when_active_fact_paths)
        facts.update({p: "synthetic confirmed applicable detail" for p in rule.required_when_active_fact_paths})
        result = bind_applicable_input(confirmed_study(facts), c, bindings, rules=real_rule_catalog().rules)
        assert dict(result.resolved_facts) == facts
    else:
        with pytest.raises(ApplicabilityResolutionError, match="conditional_applicability_unresolved"):
            bind_applicable_input(confirmed_study(facts), c, bindings, rules=real_rule_catalog().rules)


@pytest.mark.parametrize("scale,node", [("ecog", "v2_n_16_x1"), ("nyha", "v2_n_16_x2")])
def test_applicable_scale_requires_evidence_for_its_verified_contents(scale, node):
    import json
    from app.protocol_workflow.registries.applicability import evaluate_applicable_content
    from app.protocol_workflow.registries.chapters import ChapterContentPayload
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR, REPO_ROOT
    from test_chapter_fact_binding import confirmed_study
    c = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / f"chapter_contracts/{node}.json").read_text())
    fixtures = json.loads((REPO_ROOT / "tests/fixtures/protocol_v3/chapter_content_v2/batch8.json").read_text())["fixtures"]
    content = next(f["content"] for f in fixtures if f["chapter_contract_id"] == c.chapter_contract_id and f["fixture_kind"] == "positive")
    for fact in content["facts"]:
        if fact["fact_path"] == f"appendix.{scale}_assessment_applicable":
            fact["value"] = True
    study = confirmed_study({f["fact_path"]: f["value"] for f in content["facts"]})
    source = {"source_role": "peer_reviewed", "admission_claim_type": "unrelated_claim",
              "locator_kind": "body", "locator": "synthetic scale source",
              "context": "synthetic content verification window", "quality_score": 1.0}
    content["evidence"].append(source)
    result = evaluate_applicable_content(c, ChapterContentPayload.model_validate(content), study=study,
                                         rules=real_rule_catalog().rules, subject_id="test:scale-source")
    assert not result.passed
    source["admission_claim_type"] = f"appendix.{scale}_version_and_contents_verified"
    result = evaluate_applicable_content(c, ChapterContentPayload.model_validate(content), study=study,
                                         rules=real_rule_catalog().rules, subject_id="test:scale-source")
    assert result.passed, result.error_codes()
    source["context"] = ""
    result = evaluate_applicable_content(c, ChapterContentPayload.model_validate(content), study=study,
                                         rules=real_rule_catalog().rules, subject_id="test:scale-source")
    assert not result.passed


@pytest.mark.parametrize("value,state", [("planned", "not_applicable"), ("draft", "not_applicable"),
                                          ("approved", "applicable"), ("apprvoed", "conditional"),
                                          (None, "conditional")])
def test_enumerated_condition_does_not_treat_unknown_status_as_negative(value, state):
    from app.protocol_workflow.registries.applicability import FactPredicate, evaluate_predicate
    predicate = FactPredicate(fact_path="test.charter_status", expected="approved",
                              accepted_values=("planned", "draft", "approved"))
    assert evaluate_predicate(predicate, {"test.charter_status": value}).value == state


@pytest.mark.parametrize("status,expected_error", [("planned", None), ("draft", None),
                                                   ("approved", "missing_required_fact"),
                                                   ("apprvoed", "conditional_applicability_unresolved")])
def test_charter_drafting_does_not_require_a_future_approval_record(status, expected_error):
    from app.protocol_workflow.registries.applicability import FactPredicate, RulePredicate, bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / "chapter_contracts/v2_n_14_7.json").read_text())
    rules = real_rule_catalog().rules
    facts = {f.fact_path: "synthetic planned oversight arrangement" for f in c.substantive_content.fact_requirements
             if f.obligation.value == "required"}
    facts.update({"quality.oversight_charter_applicable": True, "quality.oversight_charter_status": status})
    if status in ("draft", "approved"):
        facts["quality.oversight_charter_version"] = "synthetic version 1"
    bindings = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR / "fact_bindings.json").read_text()).bindings
    if expected_error:
        with pytest.raises((FactBindingError, ApplicabilityResolutionError), match=expected_error) as caught:
            bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules)
        if status == "approved":
            assert caught.value.fact_paths == ("quality.oversight_charter_approval_record",)
            facts["quality.oversight_charter_approval_record"] = {"record_ref": "synthetic approval evidence"}
            bound = bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules)
            assert bound.resolved_facts["quality.oversight_charter_approval_record"] == facts["quality.oversight_charter_approval_record"]
    else:
        bound = bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules)
        assert "quality.oversight_charter_approval_record" not in bound.resolved_facts


@pytest.mark.parametrize("central", [False, True, None])
def test_central_lab_requires_its_scope_without_releasing_local_units(central):
    from app.protocol_workflow.registries.applicability import FactPredicate, RulePredicate, bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / "chapter_contracts/v2_n_9_2.json").read_text())
    rule = c.conditional_applicability_rules[0]
    declarations = real_rule_catalog().rules
    facts = {f.fact_path: "synthetic project assessment" for f in c.substantive_content.fact_requirements if f.obligation.value == "required"}
    facts["safety.central_lab_applicable"] = central
    bindings = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR / "fact_bindings.json").read_text()).bindings
    if central is None:
        with pytest.raises(ApplicabilityResolutionError, match="conditional_applicability_unresolved"):
            bind_applicable_input(confirmed_study(facts), c, bindings, rules=declarations)
    else:
        if central:
            with pytest.raises(FactBindingError, match="missing_required_fact") as caught:
                bind_applicable_input(confirmed_study(facts), c, bindings, rules=declarations)
            assert set(caught.value.fact_paths) == {"safety.central_lab_qualification", "safety.central_lab_assay_scope"}
            facts.update({p: "synthetic confirmed central detail" for p in caught.value.fact_paths})
        result = bind_applicable_input(confirmed_study(facts), c, bindings, rules=declarations)
        assert "safety.lab_units_and_reference_ranges" in result.resolved_facts
        del facts["safety.lab_units_and_reference_ranges"]
        with pytest.raises(FactBindingError, match="missing_required_fact"):
            bind_applicable_input(confirmed_study(facts), c, bindings, rules=declarations)


@pytest.mark.parametrize("flag", [False, True, None])
def test_conditional_table_cells_do_not_remove_the_whole_table(flag):
    from app.protocol_workflow.registries.applicability import FactPredicate, RulePredicate, evaluate_applicable_content
    from app.protocol_workflow.registries.chapters import ChapterContentPayload
    from test_all_chapter_contracts import _objectives_contract, _objectives_positive_content
    from test_chapter_fact_binding import confirmed_study
    c = _objectives_contract(conditional_applicability_rules=({
        "conditional_applicability_rule_id": "condition:table-detail", "triggering_fact_paths": ("test.table_detail",),
        "condition": "Synthetic optional table detail", "rationale": "Keep base table while varying one cell",
        "required_when_active_fact_paths": ("picos.objective.primary",),
    },))
    cell = "test:conditional-table-detail"
    objects = tuple(o.model_copy(update={"required_object_cells": o.required_object_cells + (cell,)})
                    if o.object_kind.value == "table" else o for o in c.substantive_content.structural_object_obligations)
    c = c.model_copy(update={"substantive_content": c.substantive_content.model_copy(update={"structural_object_obligations": objects})})
    rule = c.conditional_applicability_rules[0]
    declaration = RulePredicate(rule_id=rule.conditional_applicability_rule_id, source_rule_sha256=rule.material_sha256(),
                                source_contract_sha256=c.material_sha256(), predicates=(FactPredicate(fact_path="test.table_detail", expected=True),),
                                conditional_object_cells=(cell,))
    payload = _objectives_positive_content()
    result = evaluate_applicable_content(c, ChapterContentPayload.model_validate(payload),
                                         study=confirmed_study({"test.table_detail": flag}), rules=(declaration,), subject_id="test:table-cell")
    if flag is False:
        assert result.passed, result.error_codes()
        payload["objects"] = [o for o in payload["objects"] if o["object_kind"] != "table"]
        assert not evaluate_applicable_content(c, ChapterContentPayload.model_validate(payload),
                   study=confirmed_study({"test.table_detail": flag}), rules=(declaration,), subject_id="test:no-table").passed
        payload = _objectives_positive_content()
        next(o for o in payload["objects"] if o["object_kind"] == "table")["cells"].append({"cell_id": cell, "value": "stale detail"})
        stale = evaluate_applicable_content(c, ChapterContentPayload.model_validate(payload),
                   study=confirmed_study({"test.table_detail": flag}), rules=(declaration,), subject_id="test:stale-cell")
        assert "inactive_conditional_cell_present" in stale.error_codes()
    elif flag is True:
        assert not result.passed
        next(o for o in payload["objects"] if o["object_kind"] == "table")["cells"].append({"cell_id": cell, "value": "synthetic detail"})
        assert evaluate_applicable_content(c, ChapterContentPayload.model_validate(payload),
                   study=confirmed_study({"test.table_detail": flag}), rules=(declaration,), subject_id="test:cell-present").passed
    else:
        assert "conditional_applicability_unresolved" in result.error_codes()


def test_actual_interim_without_efficacy_testing_or_committees_needs_no_fake_details():
    from app.protocol_workflow.registries.applicability import bind_applicable_input
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c, _ = interim_case()
    optional_details = {"statistics.interim.information_fraction", "statistics.interim.efficacy_alpha_spending",
                        "statistics.interim.idmc_responsibilities", "statistics.interim.endpoint_irc_responsibilities"}
    facts = {f.fact_path: "synthetic interim arrangement" for f in c.substantive_content.fact_requirements
             if f.obligation.value == "required" and f.fact_path not in optional_details}
    facts.update({"statistics.interim.applicable": True, "statistics.interim.canonical_reference": "v2_n_14_7",
                  "statistics.interim.features": {"information_fraction": False, "efficacy_testing": False, "idmc_review": False},
                  "irc.applicable": False})
    bindings = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR / "fact_bindings.json").read_text()).bindings
    result = bind_applicable_input(confirmed_study(facts), c, bindings, rules=real_rule_catalog().rules)
    assert not (optional_details & set(result.resolved_facts))
    facts["statistics.interim.features"]["efficacy_testing"] = True
    with pytest.raises(FactBindingError, match="missing_required_fact") as caught:
        bind_applicable_input(confirmed_study(facts), c, bindings, rules=real_rule_catalog().rules)
    assert caught.value.fact_paths == ("statistics.interim.efficacy_alpha_spending",)



def actual_interim_output_case(flags):
    import json
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    from app.protocol_workflow.registries.chapters import ChapterContentPayload
    path = REAL_TEMPLATE_DIR.parents[4] / 'tests/fixtures/protocol_v3/chapter_content_v2/batch6.json'
    fixture = next(item for item in json.loads(path.read_text())['fixtures']
                   if item['fixture_id'] == 'fixture:batch6:v2-n-11-4-9:positive')
    raw = fixture['content']
    options = (
        ('information_fraction', 'information_fraction', 'information-fraction'),
        ('efficacy_testing', 'efficacy_alpha_spending', 'efficacy-alpha'),
        ('idmc_review', 'idmc_responsibilities', 'idmc'),
        (None, 'endpoint_irc_responsibilities', 'irc'),
    )
    inactive_facts = {'statistics.interim.' + field for (_, field, _), flag in zip(options, flags) if not flag}
    inactive_cells = {'interim:cell:' + cell for (_, _, cell), flag in zip(options, flags) if not flag}
    facts = {item['fact_path']: item['value'] for item in raw['facts'] if item['fact_path'] not in inactive_facts}
    facts.update({'statistics.interim.applicable': True, 'statistics.interim.canonical_reference': 'v2_n_14_7',
                  'statistics.interim.features': {key: flag for (key, _, _), flag in zip(options, flags) if key},
                  'irc.applicable': flags[3]})
    raw['facts'] = [{'fact_path': key, 'value': value} for key, value in facts.items()]
    raw['objects'][0]['cells'] = [item for item in raw['objects'][0]['cells'] if item['cell_id'] not in inactive_cells]
    return confirmed_study(facts), ChapterContentPayload.model_validate(raw)


@pytest.mark.parametrize('flags', product((False, True), repeat=4))
def test_actual_interim_output_obligations_follow_each_confirmed_purpose(flags):
    from app.protocol_workflow.registries.applicability import evaluate_applicable_content
    contract, _ = interim_case()
    study, content = actual_interim_output_case(flags)
    result = evaluate_applicable_content(contract, content, study=study,
                                        rules=real_rule_catalog().rules, subject_id='test:interim-purposes')
    assert result.passed, result.error_codes()
    incomplete = content.model_copy(update={'objects': ()})
    assert not evaluate_applicable_content(contract, incomplete, study=study,
                                          rules=real_rule_catalog().rules, subject_id='test:missing-interim-table').passed


def test_active_interim_rejects_opposite_disposition_in_output():
    from app.protocol_workflow.registries.applicability import evaluate_applicable_content
    from app.protocol_workflow.registries.chapters import ContentClaim
    contract, _ = interim_case()
    study, content = actual_interim_output_case((False, False, False, False))
    content = content.model_copy(update={'claims': content.claims + (
        ContentClaim(claim_type='interim_not_planned', statement='本研究不计划开展期中分析。'),)})
    result = evaluate_applicable_content(contract, content, study=study,
                                        rules=real_rule_catalog().rules, subject_id='test:opposite-interim-disposition')
    assert 'inactive_disposition_claim_present' in result.error_codes()


@pytest.mark.parametrize('flag', [False, True, None])
def test_sample_size_interim_uses_design_justification_not_mandatory_spending_value(flag):
    from app.protocol_workflow.registries.applicability import bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / 'chapter_contracts/v2_n_11_1.json').read_text())
    bindings = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR / 'fact_bindings.json').read_text()).bindings
    facts = {item.fact_path: 'synthetic sample-size parameter' for item in c.substantive_content.fact_requirements
             if item.obligation.value == 'required'}
    facts['statistics.sample_size.interim_applicable'] = flag
    rules = real_rule_catalog().rules
    if flag is None:
        with pytest.raises(ApplicabilityResolutionError, match='conditional_applicability_unresolved'):
            bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules)
    elif flag is False:
        result = bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules)
        assert 'statistics.sample_size.interim_adjustment' not in result.resolved_facts
        assert 'statistics.sample_size.interim_alpha_adjustment' not in result.resolved_facts
    else:
        facts['statistics.sample_size.interim_adjustment'] = 'Synthetic prespecified sample-size reassessment and its impact.'
        with pytest.raises(FactBindingError, match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules)
        assert caught.value.fact_paths == ('statistics.sample_size.interim_alpha_adjustment',)
        justification = {'conclusion': 'no_additional_adjustment', 'method': 'Synthetic method only',
                         'source_locator': 'test:design-specific-error-rate-proof'}
        facts['statistics.sample_size.interim_alpha_adjustment'] = justification
        result = bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules)
        assert result.resolved_facts['statistics.sample_size.interim_alpha_adjustment'] == justification


@pytest.mark.parametrize('flag', [False, True, None])
def test_irc_configuration_keeps_decision_without_inventing_committee_details(flag):
    from app.protocol_workflow.registries.applicability import bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / 'chapter_contracts/v2_n_9_4.json').read_text())
    bindings = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR / 'fact_bindings.json').read_text()).bindings
    facts = {'irc.applicable': flag}
    rules = real_rule_catalog().rules
    if flag is None:
        with pytest.raises(ApplicabilityResolutionError, match='conditional_applicability_unresolved'):
            bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules)
    elif flag is False:
        result = bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules)
        assert result.resolved_facts == facts
        facts['irc.charter_and_independence'] = 'Stale committee charter'
        with pytest.raises(ApplicabilityResolutionError, match='inactive_conditional_fact_present'):
            bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules)
    else:
        with pytest.raises(FactBindingError, match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules)
        assert set(caught.value.fact_paths) == set(c.conditional_applicability_rules[0].required_when_active_fact_paths)
        facts.update({key: 'Synthetic confirmed IRC arrangement' for key in caught.value.fact_paths})
        assert bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules).resolved_facts == facts


def test_no_irc_output_still_requires_actual_decision_and_its_source():
    from app.protocol_workflow.registries.applicability import evaluate_applicable_content
    from app.protocol_workflow.registries.chapters import ChapterContentPayload
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / 'chapter_contracts/v2_n_9_4.json').read_text())
    content = ChapterContentPayload.model_validate({
        'facts': [{'fact_path': 'irc.applicable', 'value': False}],
        'claims': [{'claim_type': 'irc_applicability_decision', 'statement': 'Synthetic project decision: no IRC.'}],
        'evidence': [{'source_role': 'project_primary', 'admission_claim_type': 'irc_applicability_decision',
                      'locator_kind': 'body', 'locator': 'test:confirmed-design', 'context': 'Synthetic decision evidence only',
                      'quality_score': 1.0}],
        'objects': [{'object_kind': 'paragraph', 'occurrences': 2,
                     'text': 'Synthetic project disposition and source-bound rationale; no invented committee.'}],
    })
    def check(payload):
        return evaluate_applicable_content(c, payload, study=confirmed_study({'irc.applicable': False}),
                                            rules=real_rule_catalog().rules, subject_id='test:no-irc-output')
    assert check(content).passed
    assert not check(content.model_copy(update={'claims': ()})).passed
    assert not check(content.model_copy(update={'evidence': ()})).passed


@pytest.mark.parametrize('flag', [False, True, None])
def test_future_use_does_not_release_current_study_disposition(flag):
    from app.protocol_workflow.registries.applicability import bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / 'chapter_contracts/v2_n_12_7.json').read_text())
    bindings = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR / 'fact_bindings.json').read_text()).bindings
    separation = 'Synthetic current-protocol assay retention and disposition remain applicable independently.'
    facts = {'future_use.applicable': flag, 'future_use.current_study_assay_separation': separation}
    rules = real_rule_catalog().rules
    if flag is None:
        with pytest.raises(ApplicabilityResolutionError, match='conditional_applicability_unresolved'):
            bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules)
    elif flag is False:
        result = bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules)
        assert result.resolved_facts == facts
        with pytest.raises(FactBindingError, match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study({'future_use.applicable': False}), c, bindings, rules=rules)
        assert caught.value.fact_paths == ('future_use.current_study_assay_separation',)
    else:
        with pytest.raises(FactBindingError, match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules)
        assert set(caught.value.fact_paths) == set(c.conditional_applicability_rules[0].required_when_active_fact_paths) - {'future_use.current_study_assay_separation'}
        facts.update({key: 'Synthetic future-use arrangement' for key in caught.value.fact_paths})
        assert bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules).resolved_facts == facts


def test_no_future_use_output_preserves_current_assay_scope_and_source():
    from app.protocol_workflow.registries.applicability import evaluate_applicable_content
    from app.protocol_workflow.registries.chapters import ChapterContentPayload, ContentFact
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / 'chapter_contracts/v2_n_12_7.json').read_text())
    facts = {'future_use.applicable': False, 'future_use.current_study_assay_separation': 'Synthetic current study retention and disposition remain governed by its protocol.'}
    content = ChapterContentPayload.model_validate({
        'facts': [{'fact_path': key, 'value': value} for key, value in facts.items()],
        'claims': [{'claim_type': 'future_use.separation', 'statement': 'Synthetic no-future-use decision does not change current trial assay arrangements.'}],
        'evidence': [{'source_role': 'project_primary', 'admission_claim_type': 'future_use.separation',
                      'locator_kind': 'body', 'locator': 'test:confirmed-materials-scope',
                      'context': 'Synthetic project decision and current trial scope only', 'quality_score': 1.0}],
    })
    def check(payload):
        return evaluate_applicable_content(c, payload, study=confirmed_study(facts),
                                            rules=real_rule_catalog().rules, subject_id='test:no-future-use')
    assert check(content).passed
    assert not check(content.model_copy(update={'evidence': ()})).passed
    wrong = content.model_copy(update={'facts': content.facts + (
        ContentFact(fact_path='future_use.universal_withdrawal_conclusion', value='Destroy all current-study materials'),)})
    assert 'forbidden_fact_present' in check(wrong).error_codes()
    stale = content.model_copy(update={'facts': content.facts + (ContentFact(fact_path='future_use.purpose', value='Old future purpose'),)})
    assert 'inactive_conditional_fact_present' in check(stale).error_codes()


@pytest.mark.parametrize('flag', [False, True, None])
def test_immunogenicity_applicability_requires_only_active_strategy(flag):
    from app.protocol_workflow.registries.applicability import bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / 'chapter_contracts/v2_n_9_3.json').read_text())
    bindings = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR / 'fact_bindings.json').read_text()).bindings
    facts = {item.fact_path: 'Synthetic other analysis arrangement' for item in c.substantive_content.fact_requirements
             if item.obligation.value == 'required'}
    facts['exploratory.immunogenicity_applicable'] = flag
    facts.update({key: True for key in ('exploratory.population_pk_applicable', 'statistics.pk_pd_er.pk_applicable', 'statistics.pk_pd_er.pd_applicable', 'statistics.pk_pd_er.er_applicable')})
    rules = real_rule_catalog().rules
    if flag is None:
        with pytest.raises(ApplicabilityResolutionError, match='conditional_applicability_unresolved'):
            bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules)
    elif flag is False:
        assert bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules).resolved_facts == facts
        facts['exploratory.immunogenicity'] = 'Stale testing strategy'
        with pytest.raises(ApplicabilityResolutionError, match='inactive_conditional_fact_present'):
            bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules)
    else:
        with pytest.raises(FactBindingError, match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules)
        assert caught.value.fact_paths == ('exploratory.immunogenicity',)
        facts['exploratory.immunogenicity'] = {'endpoint': 'Synthetic test endpoint', 'sampling': 'Synthetic schedule', 'method': 'Synthetic analysis'}
        assert bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules).resolved_facts == facts


def test_exploratory_objective_uses_explicit_flags_not_analysis_text():
    from app.protocol_workflow.registries.applicability import bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / 'chapter_contracts/v2_n_3_4_1.json').read_text())
    bindings = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR / 'fact_bindings.json').read_text()).bindings
    facts = {'picos.exploratory_objectives': 'Synthetic no additional exploratory objectives',
             'exploratory.disposition': 'Synthetic confirmed disposition',
             'exploratory.population_pk_applicable': False, 'statistics.pk_pd_er.er_applicable': False,
             'exploratory.immunogenicity_applicable': False, 'exploratory.biomarker_applicable': False}
    rules = real_rule_catalog().rules
    assert bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules).resolved_facts == facts
    facts['exploratory.population_pk_applicable'] = True
    with pytest.raises(FactBindingError, match='missing_required_fact') as caught:
        bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules)
    assert caught.value.fact_paths == ('exploratory.population_pk',)
    facts['exploratory.population_pk'] = {'objective': 'Synthetic population PK objective'}
    assert bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules).resolved_facts == facts
    facts['exploratory.biomarker_applicable'] = None
    with pytest.raises(ApplicabilityResolutionError, match='conditional_applicability_unresolved'):
        bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules)


@pytest.mark.parametrize('active', [None, 'population_pk', 'pk', 'pd', 'er'])
def test_pk_assessment_keeps_shared_sampling_for_each_actual_analysis(active):
    from app.protocol_workflow.registries.applicability import bind_applicable_input
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / 'chapter_contracts/v2_n_9_3.json').read_text())
    bindings = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR / 'fact_bindings.json').read_text()).bindings
    paths = {'population_pk': 'exploratory.population_pk_applicable', 'pk': 'statistics.pk_pd_er.pk_applicable',
             'pd': 'statistics.pk_pd_er.pd_applicable', 'er': 'statistics.pk_pd_er.er_applicable'}
    facts = {path: name == active for name, path in paths.items()}
    facts['exploratory.immunogenicity_applicable'] = False
    rules = real_rule_catalog().rules
    if active is None:
        assert bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules).resolved_facts == facts
    else:
        expected = {'pk.pd_analysis_requirements', 'pk.linked_endpoints', 'pk.sampling_schedule'}
        if active == 'population_pk': expected.add('exploratory.population_pk')
        if active == 'er': expected.add('exploratory.exposure_response')
        with pytest.raises(FactBindingError, match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules)
        assert set(caught.value.fact_paths) == expected
        facts.update({key: 'Synthetic confirmed analysis arrangement' for key in expected})
        result = bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules)
        assert result.resolved_facts == facts


@pytest.mark.parametrize('immunogenicity', [False, True])
def test_no_pk_output_does_not_suppress_independent_immunogenicity(immunogenicity):
    from app.protocol_workflow.registries.applicability import evaluate_applicable_content
    from app.protocol_workflow.registries.chapters import ChapterContentPayload, ContentEvidence
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / 'chapter_contracts/v2_n_9_3.json').read_text())
    facts = {key: False for key in ('exploratory.population_pk_applicable','statistics.pk_pd_er.pk_applicable',
                                   'statistics.pk_pd_er.pd_applicable','statistics.pk_pd_er.er_applicable')}
    facts['exploratory.immunogenicity_applicable'] = immunogenicity
    claims = [{'claim_type': 'exploratory_disposition', 'statement': 'Synthetic project decision: no PK/PD/E-R analyses.'}]
    if immunogenicity:
        facts['exploratory.immunogenicity'] = {'endpoint': 'Synthetic immunogenicity endpoint', 'schedule': 'Synthetic independent sampling'}
        claims.append({'claim_type': 'immunogenicity_strategy', 'statement': 'Synthetic independent immunogenicity assessment.'})
    content = ChapterContentPayload.model_validate({
        'facts': [{'fact_path': key, 'value': value} for key, value in facts.items()], 'claims': claims,
        'evidence': [{'source_role': 'project_primary','admission_claim_type': 'exploratory_disposition',
                      'locator_kind': 'body','locator': 'test:analysis-scope','context': 'Synthetic project disposition only','quality_score': 1.0}],
        'objects': [{'object_kind': 'paragraph','occurrences': 2,'text': 'Synthetic analysis disposition and independent assessment arrangements.'}],
    })
    def check(payload):
        return evaluate_applicable_content(c,payload,study=confirmed_study(facts),rules=real_rule_catalog().rules,subject_id='test:independent-analysis')
    if immunogenicity:
        content = content.model_copy(update={'evidence': content.evidence + (ContentEvidence(source_role='project_primary',admission_claim_type='immunogenicity_strategy',locator_kind='body',locator='test:immunogenicity-strategy',context='Synthetic independent strategy source',quality_score=1.0),)})
    result = check(content)
    assert result.passed, result.error_codes()
    assert not check(content.model_copy(update={'evidence': ()})).passed
    if immunogenicity:
        assert 'missing_conditional_claim' in check(content.model_copy(update={'claims': content.claims[:1]})).error_codes()
        assert not check(content.model_copy(update={'evidence': content.evidence[:1]})).passed



def test_inclusion_chapter_has_required_content_without_patient_eligibility_switch():
    from app.protocol_workflow.registries.applicability import evaluate_applicable_content
    from app.protocol_workflow.registries.chapters import ChapterContentPayload
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / 'chapter_contracts/v2_n_5_1.json').read_text())
    result = evaluate_applicable_content(c, ChapterContentPayload(), study=confirmed_study({'test.anchor': 'Synthetic confirmed project'}),
                                        rules=real_rule_catalog().rules, subject_id='test:inclusion-content-obligation')
    assert 'conditional_predicate_missing' not in result.error_codes()
    assert 'missing_required_fact' in result.error_codes()
    assert 'missing_required_claim' in result.error_codes()
    assert any('all-applicable-criteria' in item for item in c.substantive_content.project_specific_elements)


@pytest.mark.parametrize('flag', [False, True, None])
def test_rescreening_does_not_control_screen_failure_records(flag):
    from app.protocol_workflow.registries.applicability import bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / 'chapter_contracts/v2_n_5_4.json').read_text())
    bindings = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR / 'fact_bindings.json').read_text()).bindings
    facts = {f.fact_path: 'Synthetic screening arrangement' for f in c.substantive_content.fact_requirements
             if f.obligation.value == 'required' and not f.fact_path.startswith('population.rescreening.')}
    facts['population.rescreening.allowed'] = flag
    rules = real_rule_catalog().rules
    if flag is None:
        with pytest.raises(ApplicabilityResolutionError, match='conditional_applicability_unresolved'):
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
    elif flag is False:
        assert bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules).resolved_facts == facts
        del facts['population.screen_failure.records']
        with pytest.raises(FactBindingError, match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        assert caught.value.fact_paths == ('population.screen_failure.records',)
    else:
        with pytest.raises(FactBindingError, match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        assert set(caught.value.fact_paths) == {'population.rescreening.'+key for key in ('definition','permitted_reasons','timing','records')}
        facts.update({key: 'Synthetic confirmed rescreening arrangement' for key in caught.value.fact_paths})
        assert bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules).resolved_facts == facts


@pytest.mark.parametrize('allowed', [False, True])
def test_rescreening_output_keeps_screen_failure_table_and_evidence(allowed):
    import json
    from app.protocol_workflow.registries.applicability import evaluate_applicable_content
    from app.protocol_workflow.registries.chapters import ChapterContentPayload
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / 'chapter_contracts/v2_n_5_4.json').read_text())
    fixture_path = REAL_TEMPLATE_DIR.parents[4] / 'tests/fixtures/protocol_v3/chapter_content_v2/batch3.json'
    raw = next(f['content'] for f in json.loads(fixture_path.read_text())['fixtures']
               if f['chapter_contract_id'] == c.chapter_contract_id and f['fixture_kind'] == 'positive')
    if not allowed:
        raw['facts'] = [f for f in raw['facts'] if not f['fact_path'].startswith('population.rescreening.')]
        for obj in raw['objects']:
            if 'cells' in obj: obj['cells'] = [cell for cell in obj['cells'] if not cell['cell_id'].startswith('rescreen:')]
        for claim in raw['claims']:
            if claim['claim_type'] == 'rescreening_eligibility': claim['statement'] = 'Synthetic confirmed decision: rescreening is not permitted.'
    raw['facts'].append({'fact_path': 'population.rescreening.allowed', 'value': allowed})
    content = ChapterContentPayload.model_validate(raw)
    study = confirmed_study({item.fact_path: item.value for item in content.facts})
    def check(payload):
        return evaluate_applicable_content(c,payload,study=study,rules=real_rule_catalog().rules,subject_id='test:rescreen-output')
    result = check(content)
    assert result.passed, result.error_codes()
    assert not check(content.model_copy(update={'evidence': tuple(e for e in content.evidence if e.admission_claim_type != 'rescreening_eligibility')})).passed
    incomplete = content.model_copy(update={'objects': tuple(o for o in content.objects if o.object_kind.value != 'table')})
    assert not check(incomplete).passed


@pytest.mark.parametrize('flag', [False, True, None])
def test_figure_index_requires_current_inventory_only_when_figures_exist(flag):
    from app.protocol_workflow.registries.applicability import bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / 'chapter_contracts/v2_n_front_8.json').read_text())
    bindings = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR / 'fact_bindings.json').read_text()).bindings
    facts = {'figure_index.has_figures': flag}
    rules = real_rule_catalog().rules
    if flag is None:
        with pytest.raises(ApplicabilityResolutionError, match='conditional_applicability_unresolved'):
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
    elif flag is False:
        assert bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules).resolved_facts == facts
        facts['figure_index.caption_inventory'] = [{'id': 'test:stale-figure','caption': 'Old figure'}]
        with pytest.raises(ApplicabilityResolutionError, match='inactive_conditional_fact_present'):
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
    else:
        with pytest.raises(FactBindingError, match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        assert caught.value.fact_paths == ('figure_index.caption_inventory',)
        facts['figure_index.caption_inventory'] = [{'id': 'test:figure-1','caption': 'Synthetic current figure'}]
        assert bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules).resolved_facts == facts


@pytest.mark.parametrize('randomized,escalation', [(False,False),(True,False),(False,True),(True,True),(None,False)])
def test_diagram_design_branches_do_not_invent_allocation_or_escalation(randomized,escalation):
    from app.protocol_workflow.registries.applicability import bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / 'chapter_contracts/v2_n_1_2.json').read_text())
    bindings = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR / 'fact_bindings.json').read_text()).bindings
    facts = {'diagram.phase_arm_structure': 'Synthetic study arms', 'diagram.visit_timepoints': 'Synthetic SOA visits',
             'diagram.randomized': randomized, 'diagram.escalation_design': escalation}
    rules = real_rule_catalog().rules
    if randomized is None:
        with pytest.raises(ApplicabilityResolutionError, match='conditional_applicability_unresolved'):
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        return
    expected = set()
    if randomized: expected.add('diagram.allocation_ratio')
    if escalation: expected.add('diagram.escalation_transition')
    if expected:
        with pytest.raises(FactBindingError, match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        assert set(caught.value.fact_paths) == expected
        facts.update({key: 'Synthetic confirmed design value' for key in expected})
    assert bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules).resolved_facts == facts


@pytest.mark.parametrize('flag', [False, True, None])
def test_soa_pk_condition_preserves_other_visit_obligations(flag):
    from app.protocol_workflow.registries.applicability import bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / 'chapter_contracts/v2_n_1_3.json').read_text())
    bindings = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR / 'fact_bindings.json').read_text()).bindings
    facts = {f.fact_path: 'Synthetic visit arrangement' for f in c.substantive_content.fact_requirements if f.obligation.value == 'required'}
    facts['soa.pk_sampling_present'] = flag
    rules = real_rule_catalog().rules
    if flag is None:
        with pytest.raises(ApplicabilityResolutionError, match='conditional_applicability_unresolved'):
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
    elif flag is False:
        result = bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        assert result.resolved_facts == facts
        del facts['soa.safety_followup']
        with pytest.raises(FactBindingError, match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        assert caught.value.fact_paths == ('soa.safety_followup',)
    else:
        with pytest.raises(FactBindingError, match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        assert caught.value.fact_paths == ('soa.pk_timing_units',)
        facts['soa.pk_timing_units'] = {'unit': 'minute', 'reference_event': 'Synthetic dose administration', 'offset': 30}
        assert bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules).resolved_facts == facts


@pytest.mark.parametrize('node,trigger,detail', [
    ('v2_n_front_1','document_control.amendment_exists','document_control.change_rationale'),
    ('v2_n_front_3','signature.additional_signatory_applicable','signature.additional_signatory_identity'),
    ('v2_n_front_4','contact.service_parties_applicable','contact.service_parties'),
])
@pytest.mark.parametrize('flag',[False,True,None])
def test_frontmatter_conditions_keep_actual_required_parties_and_history(node,trigger,detail,flag):
    from app.protocol_workflow.registries.applicability import bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / 'chapter_contracts' / (node+'.json')).read_text())
    bindings = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR / 'fact_bindings.json').read_text()).bindings
    facts = {f.fact_path: 'Synthetic actual project metadata' for f in c.substantive_content.fact_requirements if f.obligation.value == 'required'}
    facts[trigger] = flag
    rules = real_rule_catalog().rules
    if flag is None:
        with pytest.raises(ApplicabilityResolutionError, match='conditional_applicability_unresolved'):
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        return
    if flag:
        with pytest.raises(FactBindingError, match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        assert caught.value.fact_paths == (detail,)
        facts[detail] = {'record': 'Synthetic confirmed metadata; no signature or approval'}
    assert bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules).resolved_facts == facts
    if not flag:
        facts[detail] = 'Stale metadata from another scope'
        with pytest.raises(ApplicabilityResolutionError, match='inactive_conditional_fact_present'):
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)


@pytest.mark.parametrize('flag',[False,True,None])
def test_background_therapy_condition_keeps_other_allowed_treatments(flag):
    from app.protocol_workflow.registries.applicability import bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / 'chapter_contracts/v2_n_6_4_2.json').read_text())
    bindings = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR / 'fact_bindings.json').read_text()).bindings
    facts = {'intervention.allowed_treatments':'Synthetic allowed treatment list', 'intervention.allowed_timing':'Synthetic allowed timing',
             'intervention.background_therapy_applicable':flag}
    rules=real_rule_catalog().rules
    if flag is None:
        with pytest.raises(ApplicabilityResolutionError,match='conditional_applicability_unresolved'):
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        return
    if flag:
        with pytest.raises(FactBindingError,match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        assert caught.value.fact_paths == ('intervention.background_therapy_rules',)
        facts['intervention.background_therapy_rules']='Synthetic confirmed mandatory background treatment'
    assert bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules).resolved_facts == facts
    del facts['intervention.allowed_timing']
    with pytest.raises(FactBindingError,match='missing_required_fact') as caught:
        bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
    assert caught.value.fact_paths == ('intervention.allowed_timing',)


@pytest.mark.parametrize('modify',[False,True,None])
def test_dose_actions_do_not_release_permanent_stop_or_force_all_adjustments(modify):
    from app.protocol_workflow.registries.applicability import bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR / 'chapter_contracts/v2_n_6_1_2.json').read_text())
    bindings = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR / 'fact_bindings.json').read_text()).bindings
    conditional = {'intervention.dose_hold_criteria','intervention.dose_reduction_rules','intervention.restart_criteria','intervention.dose_escalation_or_dlt_logic'}
    facts={f.fact_path:'Synthetic dose arrangement' for f in c.substantive_content.fact_requirements if f.obligation.value=='required' and f.fact_path not in conditional}
    facts.update({'intervention.dose_modification_required':modify,'intervention.dose_escalation_or_dlt_applicable':False})
    rules=real_rule_catalog().rules
    if modify is None:
        with pytest.raises(ApplicabilityResolutionError,match='conditional_applicability_unresolved'):
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        return
    if modify:
        facts['intervention.dose_modification_features']={'hold':False,'reduction':True,'restart':False}
        with pytest.raises(FactBindingError,match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        assert caught.value.fact_paths==('intervention.dose_reduction_rules',)
        facts['intervention.dose_reduction_rules']='Synthetic confirmed reduction scheme'
    assert bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules).resolved_facts==facts
    del facts['intervention.permanent_discontinuation_criteria']
    with pytest.raises(FactBindingError,match='missing_required_fact') as caught:
        bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
    assert caught.value.fact_paths==('intervention.permanent_discontinuation_criteria',)


@pytest.mark.parametrize('hold,reduction,restart,escalation',product((False,True),repeat=4))
def test_dose_action_output_combinations_keep_permanent_stop(hold,reduction,restart,escalation):
    import json
    from app.protocol_workflow.registries.applicability import evaluate_applicable_content
    from app.protocol_workflow.registries.chapters import ChapterContentPayload
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_6_1_2.json').read_text())
    path=REAL_TEMPLATE_DIR.parents[4]/'tests/fixtures/protocol_v3/chapter_content_v2/batch4.json'
    raw=next(f['content'] for f in json.loads(path.read_text())['fixtures'] if f['chapter_contract_id']==c.chapter_contract_id and f['fixture_kind']=='positive')
    options={'intervention.dose_hold_criteria':hold,'intervention.dose_reduction_rules':reduction,
             'intervention.restart_criteria':restart,'intervention.dose_escalation_or_dlt_logic':escalation}
    facts={f['fact_path']:f['value'] for f in raw['facts'] if f['fact_path'] not in options or options[f['fact_path']]}
    modify=any((hold,reduction,restart))
    facts.update({'intervention.dose_modification_required':modify,'intervention.dose_escalation_or_dlt_applicable':escalation})
    if modify:facts['intervention.dose_modification_features']={'hold':hold,'reduction':reduction,'restart':restart}
    raw['facts']=[{'fact_path':k,'value':v} for k,v in facts.items()]
    content=ChapterContentPayload.model_validate(raw)
    def check(payload):
        return evaluate_applicable_content(c,payload,study=confirmed_study(facts),rules=real_rule_catalog().rules,subject_id='test:dose-actions-output')
    result=check(content)
    assert result.passed,result.error_codes()
    without_stop=content.model_copy(update={'facts':tuple(f for f in content.facts if f.fact_path!='intervention.permanent_discontinuation_criteria')})
    assert 'missing_required_fact' in check(without_stop).error_codes()


@pytest.mark.parametrize('flag',[False,True,None])
def test_oncology_exception_keeps_general_ae_and_teae_definitions(flag):
    from app.protocol_workflow.registries.applicability import bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_10_1_1.json').read_text())
    bindings=FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR/'fact_bindings.json').read_text()).bindings
    facts={f.fact_path:'Synthetic AE definition detail' for f in c.substantive_content.fact_requirements if f.obligation.value=='required'}
    facts['ae.oncology_progression_exception_applicable']=flag
    rules=real_rule_catalog().rules
    if flag is None:
        with pytest.raises(ApplicabilityResolutionError,match='conditional_applicability_unresolved'):
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        return
    if flag:
        with pytest.raises(FactBindingError,match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        assert caught.value.fact_paths==('ae.oncology_progression_exception',)
        facts['ae.oncology_progression_exception']='Synthetic protocol-specific exception scope, not a medical conclusion'
    assert bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules).resolved_facts==facts
    del facts['ae.definition']
    with pytest.raises(FactBindingError,match='missing_required_fact') as caught:
        bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
    assert caught.value.fact_paths==('ae.definition',)


@pytest.mark.parametrize('flag', [False, True, None])
def test_injection_decision_uses_explicit_member_and_requires_reason(flag):
    from app.protocol_workflow.registries.applicability import bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c = ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_3_3_1.json').read_text())
    bindings = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR/'fact_bindings.json').read_text()).bindings
    facts = {f.fact_path: 'Synthetic safety objective' for f in c.substantive_content.fact_requirements if f.obligation.value == 'required'}
    decision = 'safety.injection_reaction_applicability'
    facts[decision] = {'applicable': flag, 'reason': '据方案'}
    rules = real_rule_catalog().rules
    if flag is None:
        with pytest.raises(ApplicabilityResolutionError, match='conditional_applicability_unresolved'):
            bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules)
        return
    if flag:
        with pytest.raises(FactBindingError, match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules)
        assert caught.value.fact_paths == ('safety.injection_reaction_definitions',)
        facts['safety.injection_reaction_definitions'] = 'Synthetic protocol-specific definitions'
    assert bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules).resolved_facts == facts
    facts[decision] = {'applicable': flag}
    with pytest.raises(FactBindingError, match='fact_member_invalid'):
        bind_applicable_input(confirmed_study(facts), c, bindings, rules=rules)


@pytest.mark.parametrize("randomized,on_day1", [(False,False),(True,False),(True,True),(None,False)])
def test_treatment_randomization_is_not_limited_to_day_one(randomized,on_day1):
    from app.protocol_workflow.registries.applicability import bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_7_2.json').read_text())
    bindings=FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR/'fact_bindings.json').read_text()).bindings
    facts={f.fact_path:'Synthetic treatment detail' for f in c.substantive_content.fact_requirements if f.obligation.value=='required' and f.fact_path!='procedure.randomization_day_rules'}
    facts.update({'diagram.randomized':randomized,'procedure.randomized_on_day1':on_day1})
    rules=real_rule_catalog().rules
    if randomized is None:
        with pytest.raises(ApplicabilityResolutionError,match='conditional_applicability_unresolved'):
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        return
    if randomized:
        with pytest.raises(FactBindingError,match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        assert caught.value.fact_paths==('procedure.randomization_day_rules',)
        facts['procedure.randomization_day_rules']='Synthetic confirmed timing, not necessarily D1'
    assert bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules).resolved_facts==facts
    del facts['procedure.dosing_start_rules']
    with pytest.raises(FactBindingError,match='missing_required_fact') as caught:
        bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
    assert caught.value.fact_paths==('procedure.dosing_start_rules',)


@pytest.mark.parametrize('randomized', [False, True])
def test_treatment_output_keeps_visit_source_when_randomization_inactive(randomized):
    import json
    from app.protocol_workflow.registries.applicability import evaluate_applicable_content
    from app.protocol_workflow.registries.chapters import ChapterContentPayload
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_7_2.json').read_text())
    p=REAL_TEMPLATE_DIR.parents[4]/'tests/fixtures/protocol_v3/chapter_content_v2/batch4.json'
    raw=next(f['content'] for f in json.loads(p.read_text())['fixtures'] if f['chapter_contract_id']==c.chapter_contract_id and f['fixture_kind']=='positive')
    facts={f['fact_path']:f['value'] for f in raw['facts'] if randomized or f['fact_path']!='procedure.randomization_day_rules'}
    facts.update({'diagram.randomized':randomized,'procedure.randomized_on_day1':False})
    raw['facts']=[{'fact_path':k,'value':v} for k,v in facts.items()]
    content=ChapterContentPayload.model_validate(raw)
    def check(payload):
        return evaluate_applicable_content(c,payload,study=confirmed_study(facts),rules=real_rule_catalog().rules,subject_id='test:treatment-output')
    result=check(content)
    assert result.passed,result.error_codes()
    assert not check(content.model_copy(update={'evidence':()})).passed
    assert not check(content.model_copy(update={'facts':tuple(f for f in content.facts if f.fact_path!='procedure.treatment_visit_procedures')})).passed


@pytest.mark.parametrize('randomized,blind,emergency,personnel', [(False,False,False,False),(True,False,False,False),(True,True,False,False),(True,True,True,True),(True,None,False,False)])
def test_randomization_and_partial_blinding_obligations_are_independent(randomized,blind,emergency,personnel):
    from app.protocol_workflow.registries.applicability import bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_4_5.json').read_text())
    bindings=FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR/'fact_bindings.json').read_text()).bindings
    prefix='framing.structured_design.'
    options={prefix+'randomization_procedure':randomized,prefix+'allocation_ratio':randomized,prefix+'masking_maintenance':blind,prefix+'accidental_unblinding':blind,prefix+'unblinding_records':blind,prefix+'emergency_unblinding':blind and emergency,prefix+'unblinded_personnel':blind and personnel}
    facts={f.fact_path:'Synthetic confirmed design detail' for f in c.substantive_content.fact_requirements if f.obligation.value=='required' and f.fact_path not in options}
    facts.update({'diagram.randomized':randomized,prefix+'masking_features':{'blinding_applied':blind,'emergency_unblinding_required':emergency,'unblinded_personnel_present':personnel}})
    rules=real_rule_catalog().rules
    if blind is None:
        with pytest.raises(ApplicabilityResolutionError,match='conditional_applicability_unresolved'):
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        return
    active={k for k,v in options.items() if v}
    if active:
        with pytest.raises(FactBindingError,match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        assert set(caught.value.fact_paths)==active
    facts.update({k:'Synthetic confirmed detail' for k in active})
    assert bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules).resolved_facts==facts
    del facts[prefix+'masking_procedure']
    with pytest.raises(FactBindingError,match='missing_required_fact'):
        bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)


@pytest.mark.parametrize('randomized,blind,emergency,personnel', product((False,True),repeat=4))
def test_masking_output_combinations_keep_open_design_bias_controls(randomized,blind,emergency,personnel):
    import json
    from app.protocol_workflow.registries.applicability import evaluate_applicable_content
    from app.protocol_workflow.registries.chapters import ChapterContentPayload
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_4_5.json').read_text())
    p=REAL_TEMPLATE_DIR.parents[4]/'tests/fixtures/protocol_v3/chapter_content_v2/batch3.json'
    raw=next(f['content'] for f in json.loads(p.read_text())['fixtures'] if f['chapter_contract_id']==c.chapter_contract_id and f['fixture_kind']=='positive')
    prefix='framing.structured_design.'
    options={prefix+'randomization_procedure':randomized,prefix+'allocation_ratio':randomized,prefix+'masking_maintenance':blind,prefix+'accidental_unblinding':blind,prefix+'unblinding_records':blind,prefix+'emergency_unblinding':blind and emergency,prefix+'unblinded_personnel':blind and personnel}
    facts={f['fact_path']:f['value'] for f in raw['facts'] if f['fact_path'] not in options or options[f['fact_path']]}
    facts.update({'diagram.randomized':randomized,prefix+'masking_features':{'blinding_applied':blind,'emergency_unblinding_required':emergency,'unblinded_personnel_present':personnel}})
    raw['facts']=[{'fact_path':k,'value':v} for k,v in facts.items()]
    if not blind:
        raw['claims']=[x for x in raw['claims'] if x['claim_type']!='unblinding_procedure']
        raw['evidence']=[x for x in raw['evidence'] if x['admission_claim_type']!='unblinding_procedure']
    cells={'randomization:procedure':randomized,'randomization:ratio':randomized,'masking:maintenance':blind,'unblinding:records':blind,'unblinding:emergency':blind and emergency}
    for obj in raw['objects']:
        if 'cells' in obj:obj['cells']=[x for x in obj['cells'] if x['cell_id'] not in cells or cells[x['cell_id']]]
    content=ChapterContentPayload.model_validate(raw)
    def check(payload):
        return evaluate_applicable_content(c,payload,study=confirmed_study(facts),rules=real_rule_catalog().rules,subject_id='test:masking-output')
    result=check(content)
    assert result.passed,result.error_codes()
    missing_bias_control=content.model_copy(update={'claims':tuple(x for x in content.claims if x.claim_type!='masking_procedure')})
    assert not check(missing_bias_control).passed
    missing_source=content.model_copy(update={'evidence':tuple(x for x in content.evidence if x.admission_claim_type!='masking_procedure')})
    assert not check(missing_source).passed


@pytest.mark.parametrize('background,rescue', [(False,False),(True,False),(False,True),(False,None)])
def test_estimand_treatment_uses_background_or_rescue_states(background,rescue):
    from app.protocol_workflow.registries.applicability import bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_3_1_2_3.json').read_text())
    bindings=FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR/'fact_bindings.json').read_text()).bindings
    detail='estimand.primary.rescue_treatment_handling'
    facts={f.fact_path:'Synthetic treatment attribute' for f in c.substantive_content.fact_requirements if f.obligation.value=='required' and f.fact_path!=detail}
    facts.update({'intervention.background_therapy_applicable':background,'design.rescue_treatment_planned':rescue})
    rules=real_rule_catalog().rules
    if rescue is None:
        with pytest.raises(ApplicabilityResolutionError,match='conditional_applicability_unresolved'):
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        return
    if background or rescue:
        with pytest.raises(FactBindingError,match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        assert caught.value.fact_paths==(detail,)
        facts[detail]='Synthetic handling bound to actual intervention'
    assert bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules).resolved_facts==facts


@pytest.mark.parametrize('background,rescue', product((False,True),repeat=2))
def test_estimand_treatment_output_requires_specific_consistency_source(background,rescue):
    import json
    from app.protocol_workflow.registries.applicability import evaluate_applicable_content
    from app.protocol_workflow.registries.chapters import ChapterContentPayload
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_3_1_2_3.json').read_text())
    p=REAL_TEMPLATE_DIR.parents[4]/'tests/fixtures/protocol_v3/chapter_content_v2/batch2.json'
    raw=next(f['content'] for f in json.loads(p.read_text())['fixtures'] if f['chapter_contract_id']==c.chapter_contract_id and f['fixture_kind']=='positive')
    active=background or rescue
    facts={f['fact_path']:f['value'] for f in raw['facts'] if active or f['fact_path']!='estimand.primary.rescue_treatment_handling'}
    facts.update({'intervention.background_therapy_applicable':background,'design.rescue_treatment_planned':rescue})
    raw['facts']=[{'fact_path':k,'value':v} for k,v in facts.items()]
    claim='estimand_cross_contract_consistency'
    raw['claims']=[x for x in raw['claims'] if x['claim_type']!=claim]
    raw['evidence']=[x for x in raw['evidence'] if x['admission_claim_type']!=claim]
    if active:
        raw['claims'].append({'claim_type':claim,'statement':'Synthetic confirmed cross-contract handling'})
        raw['evidence'].append({'source_role':'project_primary','admission_claim_type':claim,'locator_kind':'body','locator':'synthetic:intervention:1','context':'Synthetic agreed handling evidence','quality_score':0.95})
    content=ChapterContentPayload.model_validate(raw)
    def check(payload):
        return evaluate_applicable_content(c,payload,study=confirmed_study(facts),rules=real_rule_catalog().rules,subject_id='test:estimand-treatment-output')
    result=check(content)
    assert result.passed,result.error_codes()
    if active:
        assert not check(content.model_copy(update={'evidence':tuple(x for x in content.evidence if x.admission_claim_type!=claim)})).passed
    assert not check(content.model_copy(update={'facts':tuple(x for x in content.facts if x.fact_path!='estimand.primary.treatment_condition')})).passed


@pytest.mark.parametrize('ni,placebo', [(False,False),(True,False),(False,True),(True,True),(None,False)])
def test_design_rationale_only_requires_applicable_margin_and_placebo_decisions(ni,placebo):
    from app.protocol_workflow.registries.applicability import bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_4_2.json').read_text())
    bindings=FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR/'fact_bindings.json').read_text()).bindings
    facts={f.fact_path:'Synthetic confirmed design rationale' for f in c.substantive_content.fact_requirements if f.obligation.value=='required'}
    facts.update({'design.noninferiority_applicable':ni,'design.placebo_control_applicable':placebo})
    rules=real_rule_catalog().rules
    if ni is None:
        with pytest.raises(ApplicabilityResolutionError,match='conditional_applicability_unresolved'):
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        return
    active=set()
    if ni:active.add('framing.structured_design.noninferiority_margin_decision')
    if placebo:active.add('framing.structured_design.placebo_decision')
    if active:
        with pytest.raises(FactBindingError,match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        assert set(caught.value.fact_paths)==active
    facts.update({k:'Synthetic reasoned project decision' for k in active})
    assert bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules).resolved_facts==facts
    del facts['framing.structured_design.comparator_rationale']
    with pytest.raises(FactBindingError,match='missing_required_fact'):
        bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)


@pytest.mark.parametrize('ni,placebo', product((False,True),repeat=2))
def test_design_rationale_output_requires_margin_source_only_when_applicable(ni,placebo):
    import json
    from app.protocol_workflow.registries.applicability import evaluate_applicable_content
    from app.protocol_workflow.registries.chapters import ChapterContentPayload
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_4_2.json').read_text())
    p=REAL_TEMPLATE_DIR.parents[4]/'tests/fixtures/protocol_v3/chapter_content_v2/batch3.json'
    raw=next(f['content'] for f in json.loads(p.read_text())['fixtures'] if f['chapter_contract_id']==c.chapter_contract_id and f['fixture_kind']=='positive')
    selected={'framing.structured_design.noninferiority_margin_decision':ni,'framing.structured_design.placebo_decision':placebo}
    facts={f['fact_path']:f['value'] for f in raw['facts'] if f['fact_path'] not in selected or selected[f['fact_path']]}
    facts.update({'design.noninferiority_applicable':ni,'design.placebo_control_applicable':placebo})
    for path,active in selected.items():
        if active:facts[path]='Synthetic reasoned project decision'
    raw['facts']=[{'fact_path':k,'value':v} for k,v in facts.items()]
    claim='noninferiority_margin_decision'
    raw['claims']=[x for x in raw['claims'] if x['claim_type']!=claim]
    raw['evidence']=[x for x in raw['evidence'] if x['admission_claim_type']!=claim]
    if ni:
        raw['claims'].append({'claim_type':claim,'statement':'Synthetic margin decision；仅在项目确认采用非劣效设计且完成界值论证时。'})
        raw['evidence'].append({'source_role':'project_primary','admission_claim_type':claim,'locator_kind':'body','locator':'synthetic:margin:1','context':'Synthetic margin justification, not medical approval','quality_score':0.95})
    content=ChapterContentPayload.model_validate(raw)
    def check(payload):
        return evaluate_applicable_content(c,payload,study=confirmed_study(facts),rules=real_rule_catalog().rules,subject_id='test:design-rationale-output')
    result=check(content)
    assert result.passed,result.error_codes()
    if ni:
        assert not check(content.model_copy(update={'evidence':tuple(x for x in content.evidence if x.admission_claim_type!=claim)})).passed
    assert not check(content.model_copy(update={'facts':tuple(x for x in content.facts if x.fact_path!='framing.structured_design.comparator_rationale')})).passed


@pytest.mark.parametrize('background,rescue', [(False,False),(True,False),(False,True),(False,None)])
def test_ice_crosscheck_never_releases_other_intercurrent_event_strategies(background,rescue):
    from app.protocol_workflow.registries.applicability import bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_3_1_2_4.json').read_text())
    bindings=FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR/'fact_bindings.json').read_text()).bindings
    facts={f.fact_path:'Synthetic confirmed ICE attribute' for f in c.substantive_content.fact_requirements if f.obligation.value=='required'}
    facts.update({'intervention.background_therapy_applicable':background,'design.rescue_treatment_planned':rescue})
    rules=real_rule_catalog().rules
    if rescue is None:
        with pytest.raises(ApplicabilityResolutionError,match='conditional_applicability_unresolved'):
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        return
    if background or rescue:
        with pytest.raises(FactBindingError,match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        assert caught.value.fact_paths==('estimand.primary.ice_strategy_crosscheck',)
        facts['estimand.primary.ice_strategy_crosscheck']='Synthetic crosscheck with followup and analysis'
    assert bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules).resolved_facts==facts
    del facts['estimand.primary.ice_strategy']
    with pytest.raises(FactBindingError,match='missing_required_fact') as caught:
        bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
    assert caught.value.fact_paths==('estimand.primary.ice_strategy',)


@pytest.mark.parametrize('flag',[False,True,None])
def test_optional_compensation_does_not_release_recruitment_or_ethics_plan(flag):
    from app.protocol_workflow.registries.applicability import bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_5_5.json').read_text())
    bindings=FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR/'fact_bindings.json').read_text()).bindings
    facts={f.fact_path:'Synthetic recruitment plan' for f in c.substantive_content.fact_requirements if f.obligation.value=='required'}
    facts['population.recruitment.compensation_applicable']=flag
    rules=real_rule_catalog().rules
    if flag is None:
        with pytest.raises(ApplicabilityResolutionError,match='conditional_applicability_unresolved'):
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        return
    if flag:
        with pytest.raises(FactBindingError,match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        assert caught.value.fact_paths==('population.recruitment.compensation_arrangement',)
        facts['population.recruitment.compensation_arrangement']={'scope':'Synthetic travel cost','amount':'Synthetic amount','payment':'Synthetic timing','records':'Synthetic record plan'}
    assert bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules).resolved_facts==facts
    del facts['population.recruitment.ethics_review_plan']
    with pytest.raises(FactBindingError,match='missing_required_fact') as caught:
        bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
    assert caught.value.fact_paths==('population.recruitment.ethics_review_plan',)


@pytest.mark.parametrize('active',[False,True])
def test_compensation_output_keeps_recruitment_and_requires_project_basis(active):
    import json
    from app.protocol_workflow.registries.applicability import evaluate_applicable_content
    from app.protocol_workflow.registries.chapters import ChapterContentPayload
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_5_5.json').read_text())
    p=REAL_TEMPLATE_DIR.parents[4]/'tests/fixtures/protocol_v3/chapter_content_v2/batch3.json'
    raw=next(f['content'] for f in json.loads(p.read_text())['fixtures'] if f['chapter_contract_id']==c.chapter_contract_id and f['fixture_kind']=='positive')
    facts={f['fact_path']:f['value'] for f in raw['facts']}
    facts['population.recruitment.compensation_applicable']=active
    if active:facts['population.recruitment.compensation_arrangement']='Synthetic proposed compensation and records, not payment receipt'
    raw['facts']=[{'fact_path':k,'value':v} for k,v in facts.items()]
    claim='compensation_arrangement'
    if not active:
        raw['claims']=[x for x in raw['claims'] if x['claim_type']!=claim]
        raw['evidence']=[x for x in raw['evidence'] if x['admission_claim_type']!=claim]
    else:
        if not any(x['claim_type']==claim for x in raw['claims']):raw['claims'].append({'claim_type':claim,'statement':'Synthetic proposed arrangement'})
        raw['evidence'].append({'source_role':'project_primary','admission_claim_type':claim,'locator_kind':'body','locator':'synthetic:compensation:1','context':'Synthetic project arrangement','quality_score':0.95})
    content=ChapterContentPayload.model_validate(raw)
    def check(payload):
        return evaluate_applicable_content(c,payload,study=confirmed_study(facts),rules=real_rule_catalog().rules,subject_id='test:compensation-output')
    result=check(content)
    assert result.passed,result.error_codes()
    if active:
        assert not check(content.model_copy(update={'evidence':tuple(x for x in content.evidence if not(x.admission_claim_type==claim and x.source_role=='project_primary'))})).passed
    assert not check(content.model_copy(update={'claims':tuple(x for x in content.claims if x.claim_type!='recruitment_plan')})).passed


def test_followup_protocol_needs_recording_plan_not_future_visit_dates():
    from app.protocol_workflow.registries.applicability import bind_applicable_input
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_7_3.json').read_text())
    bindings=FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR/'fact_bindings.json').read_text()).bindings
    key='procedure.unscheduled_contact_recording_plan'
    facts={f.fact_path:'Synthetic followup definition' for f in c.substantive_content.fact_requirements if f.obligation.value=='required' and f.fact_path!=key}
    rules=real_rule_catalog().rules
    with pytest.raises(FactBindingError,match='missing_required_fact') as caught:
        bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
    assert caught.value.fact_paths==(key,)
    facts[key]={k:'Synthetic recording instruction, not an event' for k in ['date_recording','modality_recording','reason_recording','assessment_rules','safety_information_handling']}
    study=confirmed_study(facts)
    assert bind_applicable_input(study,c,bindings,rules=rules).resolved_facts==facts
    legacy_study=confirmed_study({**facts,'procedure.contact_visit_date':'2025-01-03'})
    assert bind_applicable_input(legacy_study,c,bindings,rules=rules).resolved_facts==facts
    assert legacy_study.facts['procedure.contact_visit_date']=='2025-01-03'
    facts[key]=dict(facts[key]);del facts[key]['safety_information_handling']
    with pytest.raises(FactBindingError,match='fact_member_invalid'):
        bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)


def test_followup_bound_output_cannot_replace_recording_plan_with_event_date():
    import json
    from app.protocol_workflow.registries.applicability import bind_applicable_input, check_applicable_output
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from app.protocol_workflow.registries.chapters import ChapterSkillOutput, ContentFact
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_7_3.json').read_text())
    bindings=FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR/'fact_bindings.json').read_text()).bindings
    p=REAL_TEMPLATE_DIR.parents[4]/'tests/fixtures/protocol_v3/chapter_content_v2/batch4.json'
    raw=next(f['content'] for f in json.loads(p.read_text())['fixtures'] if f['chapter_contract_id']==c.chapter_contract_id and f['fixture_kind']=='positive')
    study=confirmed_study({f['fact_path']:f['value'] for f in raw['facts']})
    rules=real_rule_catalog().rules
    bound=bind_applicable_input(study,c,bindings,rules=rules)
    output=ChapterSkillOutput.model_validate({'chapter_contract_id':c.chapter_contract_id,'node_id':c.semantic_node_id,**raw})
    assert check_applicable_output(bound,output,study,c,bindings,rules=rules).passed
    key='procedure.unscheduled_contact_recording_plan'
    wrong=output.model_copy(update={'facts':tuple(f for f in output.facts if f.fact_path!=key)+(ContentFact(fact_path=key,value='2027-01-01'),)})
    with pytest.raises(FactBindingError,match='output_fact_mismatch'):
        check_applicable_output(bound,wrong,study,c,bindings,rules=rules)


@pytest.mark.parametrize('no_adjustment',[False,True,None])
def test_multiplicity_disposition_never_releases_confirmatory_family(no_adjustment):
    from app.protocol_workflow.registries.applicability import bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_11_4_8.json').read_text())
    bindings=FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR/'fact_bindings.json').read_text()).bindings
    facts={f.fact_path:'Synthetic project multiplicity rationale' for f in c.substantive_content.fact_requirements if f.obligation.value=='required'}
    facts['statistics.multiplicity.no_adjustment_applicable']=no_adjustment
    rules=real_rule_catalog().rules
    if no_adjustment is None:
        with pytest.raises(ApplicabilityResolutionError,match='conditional_applicability_unresolved'):
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        return
    assert bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules).resolved_facts==facts
    for required in ['statistics.multiplicity.confirmatory_family','statistics.multiplicity.applicability_disposition','statistics.multiplicity.procedure']:
        with pytest.raises(FactBindingError,match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study({k:v for k,v in facts.items() if k!=required}),c,bindings,rules=rules)
        assert caught.value.fact_paths==(required,)


def test_exploratory_interpretation_limit_is_not_optional_prose():
    import json
    from app.protocol_workflow.registries.chapters import ChapterContentPayload,evaluate_chapter_content
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_3_4_2.json').read_text())
    p=REAL_TEMPLATE_DIR.parents[4]/'tests/fixtures/protocol_v3/chapter_content_v2/batch2.json'
    raw=next(f['content'] for f in json.loads(p.read_text())['fixtures'] if f['chapter_contract_id']==c.chapter_contract_id and f['fixture_kind']=='positive')
    raw['claims']=[x for x in raw['claims'] if x['claim_type']!='exploratory_non_confirmatory']
    result=evaluate_chapter_content(c,ChapterContentPayload.model_validate(raw),subject_id='test:exploratory-limit')
    assert 'missing_required_claim' in result.error_codes()


def test_exploratory_output_interpretation_has_its_own_project_source():
    import json
    from app.protocol_workflow.registries.applicability import bind_applicable_input,check_applicable_output
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog
    from app.protocol_workflow.registries.chapters import ChapterSkillOutput
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_3_4_2.json').read_text())
    bindings=FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR/'fact_bindings.json').read_text()).bindings
    p=REAL_TEMPLATE_DIR.parents[4]/'tests/fixtures/protocol_v3/chapter_content_v2/batch2.json'
    raw=next(f['content'] for f in json.loads(p.read_text())['fixtures'] if f['chapter_contract_id']==c.chapter_contract_id and f['fixture_kind']=='positive')
    study=confirmed_study({f['fact_path']:f['value'] for f in raw['facts']});rules=real_rule_catalog().rules
    bound=bind_applicable_input(study,c,bindings,rules=rules)
    output=ChapterSkillOutput.model_validate({'chapter_contract_id':c.chapter_contract_id,'node_id':c.semantic_node_id,**raw})
    assert check_applicable_output(bound,output,study,c,bindings,rules=rules).passed
    missing=output.model_copy(update={'evidence':tuple(x for x in output.evidence if x.admission_claim_type!='exploratory_non_confirmatory')})
    assert not check_applicable_output(bound,missing,study,c,bindings,rules=rules).passed


@pytest.mark.parametrize('flag',[False,True,None])
def test_labeling_review_controls_extra_text_not_base_packaging(flag):
    from app.protocol_workflow.registries.applicability import bind_applicable_input, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_6_2_2.json').read_text())
    bindings=FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR/'fact_bindings.json').read_text()).bindings
    facts={'intervention.packaging_and_labeling':{'version':'synthetic:v1','description':'Synthetic project packaging'},'intervention.regulatory_labeling_check':flag}
    rules=real_rule_catalog().rules
    if flag is None:
        with pytest.raises(ApplicabilityResolutionError,match='conditional_applicability_unresolved'):
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        return
    if flag:
        with pytest.raises(FactBindingError,match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        assert caught.value.fact_paths==('intervention.label_text',)
        facts['intervention.label_text']='Synthetic versioned text, not a compliance conclusion'
    assert bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules).resolved_facts==facts
    del facts['intervention.packaging_and_labeling']
    with pytest.raises(FactBindingError,match='missing_required_fact') as caught:
        bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
    assert caught.value.fact_paths==('intervention.packaging_and_labeling',)


@pytest.mark.parametrize('node,detail',[('v2_n_5_2','population.exclusion.contraception_criterion_ref'),('v2_n_5_3','population.lifestyle.contraception_duration')])
@pytest.mark.parametrize('flag',[False,True,None])
def test_contraception_shared_decision_controls_only_specific_obligations(node,detail,flag):
    from app.protocol_workflow.registries.applicability import bind_applicable_input,ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog,FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/f'chapter_contracts/{node}.json').read_text())
    bindings=FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR/'fact_bindings.json').read_text()).bindings
    facts={f.fact_path:'Synthetic project eligibility/lifestyle fact' for f in c.substantive_content.fact_requirements if f.obligation.value=='required' and f.fact_path!=detail}
    facts['picos.risk.pregnancy_contraception']={'applicable':flag,'reason':'项目判断'}
    rules=real_rule_catalog().rules
    if flag is None:
        with pytest.raises(ApplicabilityResolutionError,match='conditional_applicability_unresolved'):
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        return
    if flag:
        with pytest.raises(FactBindingError,match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        assert caught.value.fact_paths==(detail,)
        facts[detail]='Synthetic project-specific criterion reference or justified duration'
    assert bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules).resolved_facts==facts
    facts['picos.risk.pregnancy_contraception']={'applicable':flag}
    with pytest.raises(FactBindingError,match='fact_member_invalid'):
        bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)


@pytest.mark.parametrize('node,detail',[('v2_n_5_2','population.exclusion.contraception_criterion_ref'),('v2_n_5_3','population.lifestyle.contraception_duration')])
@pytest.mark.parametrize('active',[False,True])
def test_contraception_output_projection_preserves_eligibility_and_lifestyle(node,detail,active):
    import json
    from app.protocol_workflow.registries.applicability import evaluate_applicable_content
    from app.protocol_workflow.registries.chapters import ChapterContentPayload
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/f'chapter_contracts/{node}.json').read_text())
    p=REAL_TEMPLATE_DIR.parents[4]/'tests/fixtures/protocol_v3/chapter_content_v2/batch3.json'
    raw=next(f['content'] for f in json.loads(p.read_text())['fixtures'] if f['chapter_contract_id']==c.chapter_contract_id and f['fixture_kind']=='positive')
    facts={f['fact_path']:f['value'] for f in raw['facts'] if active or f['fact_path']!=detail}
    facts['picos.risk.pregnancy_contraception']={'applicable':active,'reason':'Synthetic project decision'}
    if active:facts[detail]='Synthetic project-specific reference or justified duration'
    raw['facts']=[{'fact_path':k,'value':v} for k,v in facts.items()]
    if not active:
        for obj in raw['objects']:
            if 'cells' in obj:obj['cells']=[x for x in obj['cells'] if x['cell_id']!='lifestyle:contraception']
    content=ChapterContentPayload.model_validate(raw)
    def check(payload):
        return evaluate_applicable_content(c,payload,study=confirmed_study(facts),rules=real_rule_catalog().rules,subject_id='test:contraception-output')
    result=check(content)
    assert result.passed,result.error_codes()
    assert not check(content.model_copy(update={'evidence':()})).passed
    if node=='v2_n_5_3':
        assert not check(content.model_copy(update={'facts':tuple(x for x in content.facts if x.fact_path!='population.lifestyle.constraints')})).passed


@pytest.mark.parametrize('followup,assessment',[(False,False),(True,False),(False,True),(True,True),(None,False)])
def test_study_end_keeps_completion_and_separates_planned_phases(followup,assessment):
    from app.protocol_workflow.registries.applicability import bind_applicable_input,ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog,FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_4_4.json').read_text())
    bindings=FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR/'fact_bindings.json').read_text()).bindings
    options={'picos.study_epochs.follow_up_definition':followup,'picos.study_epochs.follow_up_window':followup,'picos.study_epochs.post_treatment_assessment':assessment}
    facts={f.fact_path:'Synthetic study completion definition' for f in c.substantive_content.fact_requirements if f.obligation.value=='required' and f.fact_path not in options}
    facts['picos.study_epochs.features']={'follow_up':followup,'post_treatment_assessment':assessment}
    rules=real_rule_catalog().rules
    if followup is None:
        with pytest.raises(ApplicabilityResolutionError,match='conditional_applicability_unresolved'):
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        return
    active={k for k,v in options.items() if v}
    if active:
        with pytest.raises(FactBindingError,match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        assert set(caught.value.fact_paths)==active
    facts.update({k:'Synthetic planned phase definition' for k in active})
    assert bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules).resolved_facts==facts
    del facts['picos.study_epochs.overall_end_trigger']
    with pytest.raises(FactBindingError,match='missing_required_fact') as caught:
        bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
    assert caught.value.fact_paths==('picos.study_epochs.overall_end_trigger',)


@pytest.mark.parametrize('followup,assessment',product((False,True),repeat=2))
def test_study_end_output_preserves_overall_end_when_optional_phase_absent(followup,assessment):
    import json
    from app.protocol_workflow.registries.applicability import evaluate_applicable_content
    from app.protocol_workflow.registries.chapters import ChapterContentPayload
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_4_4.json').read_text())
    p=REAL_TEMPLATE_DIR.parents[4]/'tests/fixtures/protocol_v3/chapter_content_v2/batch3.json'
    raw=next(f['content'] for f in json.loads(p.read_text())['fixtures'] if f['chapter_contract_id']==c.chapter_contract_id and f['fixture_kind']=='positive')
    options={'picos.study_epochs.follow_up_definition':followup,'picos.study_epochs.follow_up_window':followup,'picos.study_epochs.post_treatment_assessment':assessment}
    facts={f['fact_path']:f['value'] for f in raw['facts'] if f['fact_path'] not in options or options[f['fact_path']]}
    facts['picos.study_epochs.features']={'follow_up':followup,'post_treatment_assessment':assessment}
    raw['facts']=[{'fact_path':k,'value':v} for k,v in facts.items()]
    if not followup:
        raw['claims']=[x for x in raw['claims'] if x['claim_type']!='study_follow_up_definition']
        raw['evidence']=[x for x in raw['evidence'] if x['admission_claim_type']!='study_follow_up_definition']
    cells={'end:follow-up-window':followup,'end:post-treatment-assessment':assessment}
    for obj in raw['objects']:
        if 'cells' in obj:obj['cells']=[x for x in obj['cells'] if x['cell_id'] not in cells or cells[x['cell_id']]]
    content=ChapterContentPayload.model_validate(raw)
    def check(payload):return evaluate_applicable_content(c,payload,study=confirmed_study(facts),rules=real_rule_catalog().rules,subject_id='test:study-end-output')
    result=check(content)
    assert result.passed,result.error_codes()
    assert not check(content.model_copy(update={'claims':tuple(x for x in content.claims if x.claim_type!='overall_study_end_definition')})).passed
    assert not check(content.model_copy(update={'evidence':tuple(x for x in content.evidence if x.admission_claim_type!='participant_completion_definition')})).passed


def test_dose_rationale_requires_planned_maximum_even_without_escalation():
    from app.protocol_workflow.registries.fact_bindings import bind_chapter_input,FactBindingCatalog,FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_4_3.json').read_text())
    bindings=FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR/'fact_bindings.json').read_text()).bindings
    key='picos.intervention_dose_regimen.maximum_dose'
    facts={f.fact_path:'Synthetic project dose rationale' for f in c.substantive_content.fact_requirements if f.obligation.value=='required' and f.fact_path!=key}
    with pytest.raises(FactBindingError,match='missing_required_fact') as caught:
        bind_chapter_input(confirmed_study(facts),c,bindings)
    assert caught.value.fact_paths==(key,)


@pytest.mark.parametrize('interim,stratification,substudy',list(product((False,True),repeat=3))+[(None,False,False)])
def test_overall_design_requires_only_confirmed_optional_feature_details(interim,stratification,substudy):
    from app.protocol_workflow.registries.applicability import bind_applicable_input,ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog,FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_4_1.json').read_text())
    bindings=FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR/'fact_bindings.json').read_text()).bindings
    facts={f.fact_path:'Synthetic confirmed overall design' for f in c.substantive_content.fact_requirements if f.obligation.value=='required'}
    facts.update({'statistics.interim.applicable':interim,'framing.structured_design.features':{'stratification':stratification,'substudy':substudy}})
    rules=real_rule_catalog().rules
    if interim is None:
        with pytest.raises(ApplicabilityResolutionError,match='conditional_applicability_unresolved'):
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        return
    options={'framing.structured_design.interim_analysis':interim,'framing.structured_design.stratification':stratification,'framing.structured_design.substudy':substudy}
    active={k for k,v in options.items() if v}
    if active:
        with pytest.raises(FactBindingError,match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        assert set(caught.value.fact_paths)==active
    facts.update({k:'Synthetic confirmed feature detail' for k in active})
    assert bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules).resolved_facts==facts
    del facts['framing.structured_design.hypothesis']
    with pytest.raises(FactBindingError,match='missing_required_fact'):
        bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)


@pytest.mark.parametrize('flag',[False,True,None])
def test_primary_objective_rescue_branch_preserves_clinical_question(flag):
    from app.protocol_workflow.registries.applicability import bind_applicable_input,ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog,FactBindingError
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_3_1_1.json').read_text())
    bindings=FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR/'fact_bindings.json').read_text()).bindings
    facts={f.fact_path:'Synthetic confirmed objective detail' for f in c.substantive_content.fact_requirements if f.obligation.value=='required'}
    question='picos.primary_clinical_question';facts[question]='Synthetic clinical question retains confirmed treatment-discontinuation handling regardless of rescue use'
    facts['design.rescue_treatment_planned']=flag;rules=real_rule_catalog().rules
    if flag is None:
        with pytest.raises(ApplicabilityResolutionError,match='conditional_applicability_unresolved'):
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        return
    if flag:
        with pytest.raises(FactBindingError,match='missing_required_fact') as caught:
            bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
        assert caught.value.fact_paths==('design.discontinuation_rescue_strategy',)
        facts['design.discontinuation_rescue_strategy']='Synthetic rescue handling consistent with confirmed clinical question and estimand'
    assert bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules).resolved_facts==facts
    del facts[question]
    with pytest.raises(FactBindingError,match='missing_required_fact') as caught:
        bind_applicable_input(confirmed_study(facts),c,bindings,rules=rules)
    assert caught.value.fact_paths==(question,)


@pytest.mark.parametrize('interim,stratification,substudy',product((False,True),repeat=3))
def test_overall_design_output_keeps_base_design_for_all_feature_combinations(interim,stratification,substudy):
    import json
    from app.protocol_workflow.registries.applicability import evaluate_applicable_content
    from app.protocol_workflow.registries.chapters import ChapterContentPayload
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_4_1.json').read_text())
    p=REAL_TEMPLATE_DIR.parents[4]/'tests/fixtures/protocol_v3/chapter_content_v2/batch3.json'
    raw=next(f['content'] for f in json.loads(p.read_text())['fixtures'] if f['chapter_contract_id']==c.chapter_contract_id and f['fixture_kind']=='positive')
    options={'framing.structured_design.interim_analysis':interim,'framing.structured_design.stratification':stratification,'framing.structured_design.substudy':substudy}
    facts={f['fact_path']:f['value'] for f in raw['facts'] if f['fact_path'] not in options or options[f['fact_path']]}
    facts.update({k:'Synthetic confirmed feature' for k,v in options.items() if v})
    facts.update({'statistics.interim.applicable':interim,'framing.structured_design.features':{'stratification':stratification,'substudy':substudy}})
    raw['facts']=[{'fact_path':k,'value':v} for k,v in facts.items()];content=ChapterContentPayload.model_validate(raw)
    def check(payload):return evaluate_applicable_content(c,payload,study=confirmed_study(facts),rules=real_rule_catalog().rules,subject_id='test:overall-design-output')
    result=check(content);assert result.passed,result.error_codes()
    assert not check(content.model_copy(update={'claims':tuple(x for x in content.claims if x.claim_type!='design_description')})).passed


@pytest.mark.parametrize('active',[False,True])
def test_primary_objective_output_keeps_question_and_requires_rescue_source(active):
    import json
    from app.protocol_workflow.registries.applicability import evaluate_applicable_content
    from app.protocol_workflow.registries.chapters import ChapterContentPayload
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    c=ChapterContractV2.model_validate_json((REAL_TEMPLATE_DIR/'chapter_contracts/v2_n_3_1_1.json').read_text())
    p=REAL_TEMPLATE_DIR.parents[4]/'tests/fixtures/protocol_v3/chapter_content_v2/batch2.json'
    raw=next(f['content'] for f in json.loads(p.read_text())['fixtures'] if f['chapter_contract_id']==c.chapter_contract_id and f['fixture_kind']=='positive')
    facts={f['fact_path']:f['value'] for f in raw['facts'] if active or f['fact_path']!='design.discontinuation_rescue_strategy'}
    facts['design.rescue_treatment_planned']=active
    if active:facts['design.discontinuation_rescue_strategy']='Synthetic rescue handling'
    raw['facts']=[{'fact_path':k,'value':v} for k,v in facts.items()];claim='rescue_strategy_statement'
    raw['claims']=[x for x in raw['claims'] if x['claim_type']!=claim];raw['evidence']=[x for x in raw['evidence'] if x['admission_claim_type']!=claim]
    if active:
        raw['claims'].append({'claim_type':claim,'statement':'Synthetic confirmed rescue handling'})
        raw['evidence'].append({'source_role':'project_primary','admission_claim_type':claim,'locator_kind':'body','locator':'synthetic:rescue:1','context':'Synthetic confirmed strategy source','quality_score':0.95})
    content=ChapterContentPayload.model_validate(raw)
    def check(payload):return evaluate_applicable_content(c,payload,study=confirmed_study(facts),rules=real_rule_catalog().rules,subject_id='test:primary-objective-output')
    result=check(content);assert result.passed,result.error_codes()
    if active:assert not check(content.model_copy(update={'evidence':tuple(x for x in content.evidence if x.admission_claim_type!=claim)})).passed
    assert not check(content.model_copy(update={'facts':tuple(x for x in content.facts if x.fact_path!='picos.primary_clinical_question')})).passed
