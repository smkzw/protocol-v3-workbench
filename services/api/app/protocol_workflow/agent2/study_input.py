"""Pin the actual target study's clinical read set before design generation."""
import hashlib

from app.protocol_workflow.canonical.hashing import canonical_json
from packages.contracts.workbench_contracts.protocol_v3 import StableId
from pydantic import TypeAdapter
from .clinical_worker import PreparedRegimenRequest


def clinical_study_facts(facts):
    return {key: value for key, value in facts.items()
            if key not in {'research.input_context', 'research.regimen_producer'}}


def validate_regimen_study_input(prepared, *, study_definition_id, facts):
    bound = prepared.to_payload().get('confirmed_study')
    if bound is None:
        # Historical receipts are recovered before this fresh-adoption check.
        # A reference-only suggestion has never read existing clinical facts.
        if clinical_study_facts(facts):
            raise ValueError('regimen_clinical_context_not_read')
        return
    if bound['study_definition_id'] != study_definition_id:
        raise ValueError('regimen_target_study_changed')
    if canonical_json(bound['facts']) != canonical_json(clinical_study_facts(facts)):
        raise ValueError('regimen_clinical_facts_changed')


def bind_regimen_study_input(prepared, *, study_definition_id, facts):
    TypeAdapter(StableId).validate_python(study_definition_id)
    payload = prepared.to_payload()
    # These two records describe input selection and the previous producer;
    # neither is a clinical parameter. Preserve every other fact, even unknown
    # vocabulary, so old study values cannot silently disappear from the read set.
    clinical_facts = clinical_study_facts(facts)
    payload['confirmed_study'] = {
        'study_definition_id': study_definition_id, 'facts': clinical_facts,
    }
    payload['instruction'] += (
        '\nconfirmed_study是目标研究已确认的事实，seed候选与历史参考不等于本研究事实。'
        '逐项核对已有给药及相关事实；与参考资料冲突时明确列出冲突和实际待决选择，'
        '不能静默覆盖、忽略旧值或假定用户已经同意修改。'
    )
    text = canonical_json(payload)
    return PreparedRegimenRequest(text, hashlib.sha256(text.encode()).hexdigest())
