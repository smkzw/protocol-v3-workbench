"""Codex counterexamples: permissions/prohibitions are not positive obligations."""
import pytest
from pydantic import ValidationError
from packages.contracts.workbench_contracts.protocol_v3 import (
    ChapterContractV2, SubstantiveContentContractV2, StructuralObjectObligation,
)
from test_chapter_contract_schema import _chapter_contract_v2


@pytest.mark.parametrize('field,entry', [
    ('fact_requirements', {'fact_path': 'study.optional', 'obligation': 'optional', 'rationale': 'optional'}),
    ('fact_requirements', {'fact_path': 'study.obsolete', 'obligation': 'forbidden', 'rationale': 'obsolete'}),
    ('claim_requirements', {'claim_type': 'optional_claim', 'obligation': 'allowed', 'rationale': 'optional'}),
    ('claim_requirements', {'claim_type': 'prohibited_claim', 'obligation': 'forbidden', 'rationale': 'prohibited'}),
    ('claim_requirements', {'claim_type': 'qualified_claim', 'obligation': 'qualified', 'rationale': 'conditional permission', 'qualifying_conditions': ['if supported']}),
])
def test_no_positive_content_obligation_is_rejected(field, entry):
    with pytest.raises(ValidationError):
        SubstantiveContentContractV2(
            substantive_content_contract_id='content:empty:v2',
            chapter_contract_id='chapter:empty:v2',
            skeleton_risk_rules=('reject empty body',),
            **{field: [entry]},
        )


def test_chapter_cannot_be_declared_with_only_format_and_qc_text():
    with pytest.raises(ValidationError):
        ChapterContractV2(
            chapter_contract_id='chapter:empty:v2', semantic_node_id='node:empty',
            contract_version='2', template_id='template:test', template_sha256='a'*64,
            chapter_skill_id='skill:test', chapter_skill_version='2',
            word_rules={'word_formatting_rules_id': 'word:test', 'required_styles': ['Normal']},
            positive_qc_rules=[{'positive_qc_rule_id': 'qc:test', 'rule': 'check body'}],
        )


def test_declared_dependencies_need_repair_ownership():
    with pytest.raises(ValidationError):
        _chapter_contract_v2(dependency_repair_policy=None)


def test_structured_cell_obligations_roundtrip():
    value = StructuralObjectObligation(
        object_kind='schedule_of_activities', minimum_occurrences=1,
        project_specific_specification='project visit cells',
        required_object_cells=('soa:visit:week12',),
    )
    assert StructuralObjectObligation.model_validate_json(value.model_dump_json()) == value


def test_embedded_content_must_belong_to_chapter_and_affects_hash():
    chapter = _chapter_contract_v2()
    payload = chapter.model_dump(mode='json')
    payload['substantive_content']['chapter_contract_id'] = 'chapter:other'
    with pytest.raises(ValidationError, match='different chapter'):
        ChapterContractV2.model_validate(payload)
    payload = chapter.model_dump(mode='json')
    payload['substantive_content']['project_specific_elements'].append('additional project obligation')
    changed = ChapterContractV2.model_validate(payload)
    assert chapter.material_sha256() != changed.material_sha256()
