"""AI object revision scope and recovery (audit G3: F07/F08).

A patch must touch exactly the authorized sub-range (table cell / text
range) with everything outside preserved byte-for-byte, and the operation
must carry one frozen identity from prepare through apply and recovery, with
an operation-level status that never degrades to a blind retry.
"""
import json

import pytest

from test_manuscript_edit_control import seed_working_document
from test_mounted_api_integration import PROJECT, SD_ID


TABLE = {'columns': ['项目', '约定值', '来源'],
    'rows': [
        {'cells': ['给药途径', '口服', '研究设计'],
         'notes': []},
        {'cells': ['给药频率', '每日一次', '研究设计'],
         'notes': []},
    ]}


@pytest.fixture()
def doc_service(tmp_path):
    from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory
    from app.protocol_workflow.application.manuscript_documents import ManuscriptDocumentService
    from datetime import datetime, timezone as _tz
    from packages.contracts.workbench_contracts.protocol_v3 import (
        SemanticBlock, SemanticDocumentRevision, CanonicalState)
    from app.protocol_workflow.application.manuscript_documents import manuscript_document_id
    from app.protocol_workflow.canonical.document import document_revision_hash
    from app.protocol_workflow.events.models import EventEnvelopeBuilder
    from packages.contracts.workbench_contracts.protocol_v3 import ActorType
    db = tmp_path / 'product.sqlite'
    service = ManuscriptDocumentService(
        build_unit_of_work_factory({'backend': 'sqlite', 'path': str(db)}),
        clock=lambda: datetime.now(_tz.utc))
    now = datetime.now(_tz.utc)
    blocks = [
        SemanticBlock(semantic_block_id='blk:para', semantic_node_id='v2_n_4_1',
            chapter_contract_id='c:1', substantive_content_contract_id='sc:1',
            block_kind='paragraph',
            content='本研究给药剂量为100mg，每日一次口服。',
            fact_paths=('intervention.dose_regimen',), claim_evidence_link_ids=(),
            medical_admission_unit_ids=(),
            content_sha256='0' * 64, canonical_state=CanonicalState.PROPOSED),
        SemanticBlock(semantic_block_id='blk:table', semantic_node_id='v2_n_4_1',
            chapter_contract_id='c:1', substantive_content_contract_id='sc:1',
            block_kind='table',
            content=json.dumps({'table': TABLE}, ensure_ascii=False),
            fact_paths=('intervention.dose_regimen',), claim_evidence_link_ids=(),
            medical_admission_unit_ids=(),
            content_sha256='0' * 64, canonical_state=CanonicalState.PROPOSED),
    ]
    revision = SemanticDocumentRevision(
        semantic_document_revision_id=manuscript_document_id(PROJECT, SD_ID),
        project_id=PROJECT, study_definition_id=SD_ID, study_definition_sha256='a' * 64,
        revision=1, previous_revision_sha256=None,
        applicability_snapshot_id='snap:t', applicability_snapshot_sha256='b' * 64,
        semantic_blocks=tuple(blocks), chapter_contract_hashes=('c' * 64,),
        updated_at=now, canonical_state=CanonicalState.PROPOSED)
    envelope = EventEnvelopeBuilder().build(
        domain_event_id='seed:' + revision.semantic_document_revision_id,
        stream_id=revision.semantic_document_revision_id, sequence=1,
        event_type='manuscript_working_document_saved.v1',
        payload_schema_version='mw_protocol_v3_event_v1', upcaster_id='noop:v1',
        actor_type=ActorType.USER, actor_id='user:example',
        action='save_working_manuscript', reason='测试夹具',
        payload={'operation_id': 'op:seed', 'intent_sha256': 'seed',
            'workflow_run_id': 'run:fixture', 'document': revision.model_dump(mode='json'),
            'document_sha256': document_revision_hash(revision),
            'acceptance_scope': 'working_draft_only'},
        emitted_at=now, previous_event_sha256=None)
    with service.uow_factory() as uow:
        uow.event_stream_repository.append_events(PROJECT,
            revision.semantic_document_revision_id, [envelope])
        uow.semantic_document_cas_repository.save_with_expected_revision(
            PROJECT, revision, expected_revision=0)
        uow.commit()
    return service


def _prepare(service, op, block_id, scope, instruction, target=None,
             expected_content_sha256=''):
    current = service.current(PROJECT, SD_ID)
    return service.prepare_object_revision(PROJECT, SD_ID, {
        'operation_id': op, 'actor_id': 'user:example',
        'expected_revision': current['expected_revision'],
        'expected_document_sha256': current['expected_document_sha256'],
        'semantic_block_id': block_id, 'expected_content_sha256': expected_content_sha256,
        'scope': scope, 'instruction': instruction, 'target': target})


def _apply(service, op, block_id, scope, instruction, candidate, target=None,
           expected_content_sha256=''):
    current = service.current(PROJECT, SD_ID)
    return service.apply_object_revision(PROJECT, SD_ID, {}, {
        'operation_id': op, 'actor_id': 'user:example',
        'expected_revision': current['expected_revision'],
        'expected_document_sha256': current['expected_document_sha256'],
        'semantic_block_id': block_id, 'expected_content_sha256': expected_content_sha256,
        'scope': scope, 'instruction': instruction, 'target': target,
        'candidate_content': candidate})


def test_patch_without_target_is_refused(doc_service):
    with pytest.raises(ValueError, match='manuscript_object_target_invalid'):
        _prepare(doc_service, 'op:p1', 'blk:table', 'patch_object', '更新第二行', None)


def test_table_cell_patch_touches_only_the_target_cell(doc_service):
    material = _prepare(doc_service, 'op:p2', 'blk:table', 'patch_object',
        '把给药频率的来源改为方案定稿', {'kind': 'table_cell', 'row': 1, 'column': 2})
    assert material['target'] == {'kind': 'table_cell', 'row': 1, 'column': 2}
    outcome = _apply(doc_service, 'op:p2', 'blk:table', 'patch_object',
        '把给药频率的来源改为方案定稿', '方案定稿',
        target={'kind': 'table_cell', 'row': 1, 'column': 2})
    table_block = next(block for block in outcome['document']['semantic_blocks']
        if block['semantic_block_id'] == 'blk:table')
    table = json.loads(table_block['content'])['table']
    assert table['rows'][1]['cells'][2] == '方案定稿', 'the target cell takes the candidate'
    assert table['rows'][0]['cells'][2] == '研究设计', 'an untouched cell survives verbatim'
    assert table['rows'][1]['cells'][0] == '给药频率', 'an untouched cell survives verbatim'


def test_text_range_patch_preserves_surrounding_prose(doc_service):
    _prepare(doc_service, 'op:p3', 'blk:para', 'patch_object', '把100mg改为200mg',
        {'kind': 'text_range', 'start': 8, 'end': 13})
    outcome = _apply(doc_service, 'op:p3', 'blk:para', 'patch_object', '把100mg改为200mg',
        '200mg', target={'kind': 'text_range', 'start': 8, 'end': 13})
    para = next(block for block in outcome['document']['semantic_blocks']
        if block['semantic_block_id'] == 'blk:para')
    assert para['content'] == '本研究给药剂量为200mg，每日一次口服。'


def test_frozen_intent_recovers_from_the_original_prepare_request(doc_service):
    """F08: prepare with no expected_content_sha256; apply fills the real
    anchor hash. The recovery lookup with the *original* sparse request must
    still replay the same operation."""
    material = _prepare(doc_service, 'op:p4', 'blk:para', 'replace_object', '整段改为定稿文本')
    assert material['intent_sha256']
    outcome = _apply(doc_service, 'op:p4', 'blk:para', 'replace_object', '整段改为定稿文本',
        '本研究给药剂量为200mg，每日一次口服。')
    assert outcome['replayed'] is False
    sparse = dict(_apply.__defaults__ and {})  # noqa: F841 — readability only
    current = doc_service.current(PROJECT, SD_ID)
    replay = doc_service.recover_object_revision(PROJECT, SD_ID, {
        'operation_id': 'op:p4', 'actor_id': 'user:example',
        'expected_revision': current['expected_revision'],
        'expected_document_sha256': current['expected_document_sha256'],
        'semantic_block_id': 'blk:para', 'expected_content_sha256': '',
        'scope': 'replace_object', 'instruction': '整段改为定稿文本'})
    assert replay['replayed'] is True, 'the original sparse request recovers the save'


def test_operation_status_never_degrades_to_blind_retry(doc_service):
    # 未登记的操作：显式 unknown，允许重新发起。
    state = doc_service.object_revision_status(PROJECT, SD_ID, 'blk:para', 'op:none')
    assert state['status'] == 'unknown'
    # 已 prepare 未 apply：running_or_unknown —— 提示先恢复原操作。
    _prepare(doc_service, 'op:p5', 'blk:para', 'replace_object', '整段改为新文本')
    state = doc_service.object_revision_status(PROJECT, SD_ID, 'blk:para', 'op:p5')
    assert state['status'] == 'running_or_unknown'
    assert 'recover' in state['next_step'] or '恢复' in state['next_step']
    # apply 之后：completed。
    _apply(doc_service, 'op:p5', 'blk:para', 'replace_object', '整段改为新文本',
        '新的完整段落文本。')
    state = doc_service.object_revision_status(PROJECT, SD_ID, 'blk:para', 'op:p5')
    assert state['status'] == 'completed'
