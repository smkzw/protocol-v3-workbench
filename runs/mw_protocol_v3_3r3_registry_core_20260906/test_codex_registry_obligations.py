"""Independent functional counterexamples for the initial registry implementation."""
import copy
import json

import pytest
import test_all_chapter_contracts as h
from app.protocol_workflow.registries.chapters import (
    ChapterContentPayload, ChapterSkillOutput, check_skill_output,
    evaluate_chapter_content, lint_registry, load_chapter_registry,
)
from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2


def evaluate(payload, content):
    return evaluate_chapter_content(
        ChapterContractV2.model_validate(payload),
        ChapterContentPayload.model_validate(content), subject_id="codex-probe",
    )


def test_optional_context_is_actually_optional():
    contract = h._objectives_contract().model_dump(mode="json")
    contract["substantive_content"]["evidence_source_requirements"][0]["require_context_window"] = False
    content = h._objectives_positive_content()
    content["evidence"][0]["context"] = None
    result = evaluate(contract, content)
    assert result.passed, result.error_codes()


def test_two_valid_evidence_groups_do_not_reject_each_other():
    contract = h._objectives_contract().model_dump(mode="json")
    groups = contract["substantive_content"]["evidence_source_requirements"]
    groups[0]["source_roles"] = ["regulatory_or_guideline"]
    second = copy.deepcopy(groups[0])
    second["admission_claim_types"] = ["safety_tolerability"]
    groups.append(second)
    content = h._objectives_positive_content()
    content["evidence"][0]["source_role"] = "regulatory_or_guideline"
    item = copy.deepcopy(content["evidence"][0])
    item["admission_claim_type"] = "safety_tolerability"
    content["evidence"].append(item)
    result = evaluate(contract, content)
    assert result.passed, result.error_codes()


def test_output_cannot_belong_to_another_node():
    output = ChapterSkillOutput(
        chapter_contract_id="contract:v2-n-3-1-1:v2", node_id="v2_n_16",
        **h._objectives_positive_content(),
    )
    result = check_skill_output(h._make_document(), output)
    assert not result.passed


def syn_payload():
    return h._syn_registry_payload([
        h._entry_payload(h._syn_cover_contract(), "cover"),
        h._entry_payload(h._syn_chapter(1)),
        h._entry_payload(h._syn_chapter(2)),
    ])


def test_cover_receives_vocabulary_checks(tmp_path):
    payload = syn_payload()
    payload["chapters"][0]["contract"]["substantive_content"]["fact_requirements"][0]["fact_path"] = "unknown.cover.fact"
    report = lint_registry(h._synthetic_template_dir(tmp_path), load_chapter_registry(payload))
    assert "unknown_fact_path" in {f.code for f in report.errors()}


def test_skill_version_must_match_contract(tmp_path):
    payload = syn_payload()
    payload["chapters"][1]["skills"][0]["skill_version"] = "999.0.0"
    report = lint_registry(h._synthetic_template_dir(tmp_path), load_chapter_registry(payload))
    assert report.errors(), "Mismatched skill version was accepted as complete"


@pytest.mark.parametrize("location", ["condition", "evidence"])
def test_all_claim_references_resolve_in_vocabulary(tmp_path, location):
    payload = syn_payload()
    contract = payload["chapters"][1]["contract"]
    if location == "condition":
        contract["conditional_applicability_rules"] = [{
            "conditional_applicability_rule_id": "condition:unknown-claim",
            "triggering_fact_paths": ["provenance.template.version"],
            "condition": "A selected version", "rationale": "Probe conditional vocabulary",
            "required_when_active_claim_types": ["unknown.condition.claim"],
        }]
    else:
        contract["substantive_content"]["evidence_source_requirements"] = [{
            "source_roles": ["regulatory_or_guideline"],
            "admission_claim_types": ["unknown.evidence.claim"],
            "allowed_locator_kinds": ["body"], "require_context_window": True,
            "minimum_quality_score": 0.8,
        }]
    report = lint_registry(h._synthetic_template_dir(tmp_path), load_chapter_registry(payload))
    assert "unknown_claim_type" in {f.code for f in report.errors()}


@pytest.mark.parametrize("kind,content", [
    ("positive", {}),
    ("skeleton", {
        "facts": [{"fact_path": "provenance.template.version", "value": "v1"}],
        "objects": [{"object_kind": "paragraph", "occurrences": 1, "text": "Actual synthetic content"}],
    }),
])
def test_cli_fixture_expectation_failure_changes_exit_status(tmp_path, kind, content):
    payload = syn_payload()
    payload["fixtures"] = [h._fixture_payload(
        "fixture:codex:mislabelled", "contract:syn-1:v2", kind, content,
    )]
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    template = h._synthetic_template_dir(tmp_path / "template")
    result = h._run_cli([
        "--registry", str(path), "--template-dir", str(template),
        "--json", "--check-fixtures",
    ], h.REPO_ROOT)
    assert result.returncode == 1, result.stdout
