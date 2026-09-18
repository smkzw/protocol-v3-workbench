"""Typed-value transport checks; these synthetic values are not medical approval."""
import json

import pytest
from pydantic import ValidationError

from app.protocol_workflow.registries.chapters import (
    ChapterContentPayload,
    ChapterSkillInput,
    ContentFact,
    evaluate_chapter_content,
)
from packages.contracts.workbench_contracts.protocol_v3 import WordFormattingRules
from test_all_chapter_contracts import (
    TEMPLATE_ID,
    TEMPLATE_SHA256,
    _objectives_contract,
    _objectives_positive_content,
)


def make_input(value):
    return ChapterSkillInput(
        chapter_contract_id="contract:v2-n-3-1-1:v2",
        node_id="v2_n_3_1_1",
        template_id=TEMPLATE_ID,
        template_sha256=TEMPLATE_SHA256,
        resolved_facts={"study.value": value},
        word_rules=WordFormattingRules(
            word_formatting_rules_id="word:typed-facts", required_styles=("Heading 3",)
        ),
    )


@pytest.mark.parametrize("value", [False, True, 0, 0.5, [False, 0], {"applicable": False}, "false"])
def test_skill_input_preserves_json_type_through_reopen(value):
    data = json.loads(make_input(value).model_dump_json())
    reopened = ChapterSkillInput.model_validate(data)
    actual = reopened.resolved_facts["study.value"]
    assert type(actual) is type(value) or isinstance(actual, type(value))
    assert actual == value
    assert json.loads(reopened.model_dump_json()) == data


@pytest.mark.parametrize("value", [False, 0, 0.5, [0], {"applicable": False}])
def test_typed_fact_survives_output_and_is_present_to_structural_checker(value):
    payload = _objectives_positive_content()
    payload["facts"][0]["value"] = value
    content = ChapterContentPayload.model_validate(payload)
    result = evaluate_chapter_content(_objectives_contract(), content, subject_id="test:typed-fact")
    assert not any(item.code == "missing_required_fact" for item in result.findings)
    assert json.loads(content.model_dump_json())["facts"][0]["value"] == value


@pytest.mark.parametrize("value", [None, "", "   "])
def test_unresolved_input_still_rejected(value):
    with pytest.raises(ValidationError):
        make_input(value)


def test_frozen_input_cannot_be_changed_through_nested_values():
    original = {"values": [False, 0]}
    skill_input = make_input(original)
    original["values"].append(4)
    assert skill_input.resolved_facts["study.value"]["values"] == [False, 0]
    with pytest.raises(TypeError):
        skill_input.resolved_facts["study.value"]["values"].append(4)


def test_frozen_output_fact_cannot_be_changed_after_validation():
    fact = ContentFact(fact_path="study.value", value={"values": [False, 0]})
    with pytest.raises(TypeError):
        fact.value["values"].append(1)


@pytest.mark.parametrize("value", [[], {}, {"items": []}])
def test_empty_structures_are_preserved_without_claiming_substantive_content(value):
    from app.protocol_workflow.registries.fact_bindings import bind_chapter_input
    from app.protocol_workflow.registries.chapters import _has_fact_value
    study = confirmed_study({"study.objective": value})
    bound = bind_chapter_input(study, _objectives_contract(), bindings_for_objective())
    assert json.loads(bound.model_dump_json())["resolved_facts"]["picos.objective.primary"] == value
    assert not _has_fact_value(value)


def bindings_for_objective(value_type="json", canonical_path="study.objective"):
    from app.protocol_workflow.registries.fact_bindings import FactBinding
    return (FactBinding(
        fact_path="picos.objective.primary",
        canonical_path=canonical_path,
        value_type=value_type,
        source_refs=("test:synthetic-binding",),
    ),)


def confirmed_study(facts, **kwargs):
    from test_study_definition_reducer import _study_definition
    return _study_definition(facts=facts, canonical_state="confirmed", **kwargs)


@pytest.mark.parametrize("value", [False, 0, [False, 0], {"applicable": False}])
def test_canonical_snapshot_to_bound_input_keeps_value_and_revision(value):
    from app.protocol_workflow.registries.fact_bindings import bind_chapter_input, BoundChapterSkillInput
    from app.protocol_workflow.canonical.study_definition import study_revision_hash
    study = confirmed_study({"study.objective": value})
    result = bind_chapter_input(study, _objectives_contract(), bindings_for_objective())
    reopened = BoundChapterSkillInput.model_validate_json(result.model_dump_json())
    assert reopened.resolved_facts["picos.objective.primary"] == value
    assert reopened.project_id == study.project_id
    assert reopened.study_revision == study.revision
    assert reopened.study_sha256 == study_revision_hash(study)
    assert "picos.objective.primary" not in study.facts


@pytest.mark.parametrize("kind,raw,expected", [
    ("boolean", "false", False), ("integer", "0", 0),
    ("number", "0.5", 0.5), ("string", "false", "false"),
])
def test_legacy_conversion_requires_explicit_declared_type(kind, raw, expected):
    from app.protocol_workflow.registries.fact_bindings import bind_chapter_input
    result = bind_chapter_input(
        confirmed_study({"study.objective": raw}), _objectives_contract(),
        bindings_for_objective(kind), source_format="legacy_strings_v1",
    )
    value = result.resolved_facts["picos.objective.primary"]
    assert value == expected and type(value) is type(expected)


def test_native_string_false_does_not_silently_become_confirmed_boolean():
    from app.protocol_workflow.registries.fact_bindings import bind_chapter_input, FactBindingError
    with pytest.raises(FactBindingError, match="fact_type_mismatch"):
        bind_chapter_input(
            confirmed_study({"study.objective": "false"}), _objectives_contract(),
            bindings_for_objective("boolean"),
        )


def test_conflicting_alias_is_reported_instead_of_overwriting_canonical():
    from app.protocol_workflow.registries.fact_bindings import bind_chapter_input, FactBindingError
    with pytest.raises(FactBindingError, match="fact_alias_conflict"):
        bind_chapter_input(
            confirmed_study({"study.objective": False, "picos.objective.primary": True}),
            _objectives_contract(), bindings_for_objective(),
        )


def test_missing_required_fact_returns_exact_path():
    from app.protocol_workflow.registries.fact_bindings import bind_chapter_input, FactBindingError
    with pytest.raises(FactBindingError) as caught:
        bind_chapter_input(confirmed_study({"other": 1}), _objectives_contract(), bindings_for_objective())
    assert caught.value.fact_paths == ("picos.objective.primary",)


def test_output_cannot_replace_canonical_false_with_numeric_zero_or_new_value():
    from app.protocol_workflow.registries.fact_bindings import bind_chapter_input, validate_output_facts, FactBindingError
    from app.protocol_workflow.registries.chapters import ChapterSkillOutput
    study = confirmed_study({"study.objective": False})
    bound = bind_chapter_input(study, _objectives_contract(), bindings_for_objective())
    for value in (0, True, "false"):
        output = ChapterSkillOutput(
            chapter_contract_id=bound.chapter_contract_id, node_id=bound.node_id,
            facts=(ContentFact(fact_path="picos.objective.primary", value=value),),
        )
        with pytest.raises(FactBindingError, match="output_fact_mismatch"):
            validate_output_facts(bound, output, study, contract=_objectives_contract(), bindings=bindings_for_objective())


def test_output_from_old_snapshot_not_adoptable_against_new_revision():
    from app.protocol_workflow.registries.fact_bindings import bind_chapter_input, validate_output_facts, FactBindingError
    from app.protocol_workflow.registries.chapters import ChapterSkillOutput
    study = confirmed_study({"study.objective": False})
    bound = bind_chapter_input(study, _objectives_contract(), bindings_for_objective())
    output = ChapterSkillOutput(
        chapter_contract_id=bound.chapter_contract_id, node_id=bound.node_id,
        facts=(ContentFact(fact_path="picos.objective.primary", value=False),),
    )
    validate_output_facts(bound, output, study, contract=_objectives_contract(), bindings=bindings_for_objective())
    with pytest.raises(FactBindingError, match="study_snapshot_stale"):
        validate_output_facts(bound, output, confirmed_study({"study.objective": False}, revision=2),
                              contract=_objectives_contract(), bindings=bindings_for_objective())


def test_generic_legacy_string_needs_type_evidence():
    from app.protocol_workflow.registries.fact_bindings import bind_chapter_input, FactBindingError
    with pytest.raises(FactBindingError, match="legacy_fact_type_unresolved"):
        bind_chapter_input(
            confirmed_study({"study.objective": "false"}), _objectives_contract(),
            bindings_for_objective(), source_format="legacy_strings_v1",
        )


def test_bound_fact_copy_is_checked_against_current_canonical_not_itself():
    from app.protocol_workflow.registries.fact_bindings import bind_chapter_input, validate_output_facts, FactBindingError
    from app.protocol_workflow.registries.chapters import ChapterSkillOutput
    study = confirmed_study({"study.objective": False})
    bound = bind_chapter_input(study, _objectives_contract(), bindings_for_objective())
    changed_copy = bound.model_copy(update={"resolved_facts": {"picos.objective.primary": True}})
    output = ChapterSkillOutput(chapter_contract_id=bound.chapter_contract_id, node_id=bound.node_id,
                               facts=(ContentFact(fact_path="picos.objective.primary", value=True),))
    with pytest.raises(FactBindingError, match="chapter_input_binding_mismatch"):
        validate_output_facts(changed_copy, output, study,
                              contract=_objectives_contract(), bindings=bindings_for_objective())


def test_shipped_fact_catalog_covers_registry_and_binds_current_contracts(tmp_path):
    from app.protocol_workflow.registries.chapters import load_chapter_registry
    from app.protocol_workflow.registries.fact_bindings import load_fact_catalog, FactBindingError
    from test_all_chapter_contracts import REPO_ROOT, REAL_TEMPLATE_DIR
    # Rebuild from current source; no assumption that a historical report is latest.
    from scripts.qc.protocol_v3.assemble_chapter_registry import assemble_registries
    registry = load_chapter_registry(assemble_registries(
        REAL_TEMPLATE_DIR / "chapter_contracts", REAL_TEMPLATE_DIR / "chapter_skills",
        [REPO_ROOT / f"tests/fixtures/protocol_v3/chapter_content_v2/batch{i}.json" for i in range(1, 9)],
    ))
    catalog_path = REAL_TEMPLATE_DIR / "fact_bindings.json"
    catalog = load_fact_catalog(catalog_path, registry)
    from app.protocol_workflow.registries.fact_bindings import build_direct_fact_catalog
    rebuilt = build_direct_fact_catalog(registry, declarations=catalog.bindings)
    assert rebuilt == catalog
    assert {item.fact_path for item in catalog.bindings} == set(registry.fact_vocabulary)
    assert all(item.source_refs for item in catalog.bindings)
    by_path = {item.fact_path: item for item in catalog.bindings}
    assert by_path["synopsis.sample_size"].canonical_path == "statistics.sample_size.reproducible_result"
    assert next(item for item in catalog.bindings if item.fact_path == "irc.applicable").value_type == "boolean"
    changed = json.loads(catalog.model_dump_json())
    changed["template_sha256"] = "a" * 64
    other = tmp_path / "changed.json"
    other.write_text(json.dumps(changed))
    with pytest.raises(FactBindingError, match="fact_catalog_source_changed"):
        load_fact_catalog(other, registry)


def test_canonical_sample_size_change_reaches_summary_without_second_fact_store():
    from pathlib import Path
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog, affected_chapter_fact_paths
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    catalog = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR / "fact_bindings.json").read_text())
    changed = affected_chapter_fact_paths(catalog.bindings, ["statistics.sample_size.reproducible_result"])
    assert changed == ("statistics.sample_size.reproducible_result", "synopsis.sample_size")
    assert affected_chapter_fact_paths(catalog.bindings, ["unrelated.new_fact"]) == ()


@pytest.mark.parametrize("value", ["  first\nsecond  ", {"text": "  first\nsecond  "}, ["  first  ", "\nsecond\n"]])
def test_fact_text_is_not_normalized_by_transport(value):
    from app.protocol_workflow.registries.fact_bindings import bind_chapter_input
    study = confirmed_study({"study.objective": value})
    assert json.loads(study.model_dump_json())["facts"]["study.objective"] == value
    bound = bind_chapter_input(study, _objectives_contract(), bindings_for_objective())
    assert json.loads(bound.model_dump_json())["resolved_facts"]["picos.objective.primary"] == value
    assert json.loads(ContentFact(fact_path="  study.objective  ", value=value).model_dump_json())["value"] == value
    assert ContentFact(fact_path="  study.objective  ", value=value).fact_path == "study.objective"


@pytest.mark.parametrize("value", [float("nan"), [float("inf")], {"nested": float("nan")}])
def test_nonfinite_output_is_reported_as_fact_error(value):
    from app.protocol_workflow.registries.fact_bindings import bind_chapter_input, validate_output_facts, FactBindingError
    from app.protocol_workflow.registries.chapters import ChapterSkillOutput
    study = confirmed_study({"study.objective": 1})
    bound = bind_chapter_input(study, _objectives_contract(), bindings_for_objective())
    output = ChapterSkillOutput(chapter_contract_id=bound.chapter_contract_id, node_id=bound.node_id,
                               facts=(ContentFact(fact_path="picos.objective.primary", value=value),))
    with pytest.raises(FactBindingError, match="output_fact_mismatch"):
        validate_output_facts(bound, output, study, contract=_objectives_contract(), bindings=bindings_for_objective())


def test_every_real_contract_reads_confirmed_canonical_values_without_projection_copies():
    from app.protocol_workflow.registries.chapters import load_chapter_registry
    from app.protocol_workflow.registries.fact_bindings import load_fact_catalog, bind_chapter_input, FactBindingError
    from scripts.qc.protocol_v3.assemble_chapter_registry import assemble_registries
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR, REPO_ROOT
    registry = load_chapter_registry(assemble_registries(
        REAL_TEMPLATE_DIR / "chapter_contracts", REAL_TEMPLATE_DIR / "chapter_skills",
        [REPO_ROOT / f"tests/fixtures/protocol_v3/chapter_content_v2/batch{i}.json" for i in range(1, 9)],
    ))
    catalog = load_fact_catalog(REAL_TEMPLATE_DIR / "fact_bindings.json", registry)
    # Synthetic addressing test, not medical acceptance. The five explicitly
    # declared new canonical keys are supplied exactly like existing keys.
    facts = {b.canonical_path: (False if b.value_type == "boolean" else {"text": f"synthetic:{b.canonical_path}"})
             for b in catalog.bindings if b.canonical_path is not None}
    study = confirmed_study(facts)
    by_path = {b.fact_path: b for b in catalog.bindings}
    for entry in registry.chapters:
        bound = bind_chapter_input(study, entry.contract, catalog.bindings)
        for path, value in bound.resolved_facts.items():
            assert value == facts[by_path[path].canonical_path], (entry.node_id, path)
    synopsis = next(e.contract for e in registry.chapters if e.node_id == "v2_n_1_1")
    assert "synopsis.sponsor" not in study.facts
    missing_sponsor = {k: v for k, v in facts.items() if k != "contact.sponsor_organization"}
    with pytest.raises(FactBindingError) as error:
        bind_chapter_input(confirmed_study(missing_sponsor), synopsis, catalog.bindings)
    assert error.value.code == "missing_required_fact"
    assert error.value.fact_paths == ("synopsis.sponsor",)


def test_nested_output_preserves_fact_text_and_registration_reproduces_evidence():
    from app.protocol_workflow.registries.chapters import ChapterSkillOutput
    from scripts.qc.protocol_v3.export_fact_resolution_registration import registration
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR, REPO_ROOT
    value = "  first\nsecond  "
    output = ChapterSkillOutput(chapter_contract_id="contract:test", node_id="node:test",
                               facts=(ContentFact(fact_path="fact:test", value=value),))
    assert json.loads(output.model_dump_json())["facts"][0]["value"] == value
    catalog = json.loads((REAL_TEMPLATE_DIR / "fact_bindings.json").read_text())
    report = registration(catalog)
    assert {row["fact_path"] for row in report["rows"]} == {row["fact_path"] for row in catalog["bindings"]}
    assert report["unsupported_fact_paths"] == []
    assert report["legacy_type_unresolved_paths"] == [b["fact_path"] for b in catalog["bindings"] if b["value_type"] == "json"]
