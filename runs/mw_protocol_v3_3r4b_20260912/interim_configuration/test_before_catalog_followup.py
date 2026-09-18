"""Three-state predicates preserve uncertainty; no natural-language inference."""
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
        bind_applicable_input(confirmed_study({"statistics.interim.applicable": True}), contract, bindings, rules=real_rule_catalog().rules)
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
        check_applicable_output(bound, output, study, contract, bindings, rules=(changed_rule,))



@pytest.mark.parametrize("value,status", [(False, "applicable"), (None, "conditional")])
def test_existing_snapshot_distinguishes_chapter_presence_from_inner_condition(value, status):
    from datetime import datetime, timezone
    from app.protocol_workflow.registries.applicability import build_applicability_snapshot
    from packages.contracts.workbench_contracts.protocol_v3 import ApplicabilitySnapshot
    from app.protocol_workflow.canonical.study_definition import study_revision_hash
    from test_chapter_fact_binding import confirmed_study
    contract, rule = interim_case()
    study = confirmed_study({"statistics.interim.applicable": value})
    snapshot = build_applicability_snapshot((contract,), study, (rule,), created_at=datetime(2026, 9, 13, tzinfo=timezone.utc))
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
    facts["statistics.interim.canonical_reference"] = "v2_n_13_x"
    bindings = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR / "fact_bindings.json").read_text()).bindings
    with pytest.raises(ApplicabilityResolutionError, match="unresolved_reference_target"):
        bind_applicable_input(confirmed_study(facts), contract, bindings, rules=(rule,))
    facts["statistics.interim.canonical_reference"] = "v2_n_14_7"
    result = bind_applicable_input(confirmed_study(facts), contract, bindings, rules=(rule,))
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

