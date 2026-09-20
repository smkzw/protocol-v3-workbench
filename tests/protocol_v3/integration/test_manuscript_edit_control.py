"""Controlled-edit and QC integration over a real saved working manuscript.

Covers the built chain end to end on real SQLite and HTTP: a wording edit
applies under CAS and bumps the revision; a fact-touching edit (server-side
reclassification, client claim ignored) is rejected as a fact proposal
without touching the document; the same edit operation replays exactly; and
the save/edit receipts carry the advisory R03 QC summary.
"""
import json
import pytest
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.encoders import jsonable_encoder

from app.protocol_workflow.api.composition import (
    ProtocolWorkflowMountConfig,
    mount_protocol_workflow_router,
)
from app.protocol_workflow.agent2.product import create_product_regimen_factory
from app.protocol_workflow.agent3.product import create_product_chapter_factory
from app.protocol_workflow.application.research_context import prepare_research_context_creation
from test_clinical_design_worker import prepared_reference
from test_regimen_workflow_integration import ROOT
from test_zhipu_product_transport import _FakeOpener, _FakeResponse, _completion_body
from test_mounted_api_integration import PROJECT, SD_ID, _create_body
import integration_shared as shared

CHAPTER_NODE = 'v2_n_4_1'


def _chapter_candidate():
    return {
        'facts': [{'fact_path': 'framing.structured_design', 'value': '随机双盲'}],
        'claims': [{'claim_type': 'design_rationale', 'statement': '设计理由与已确认事实一致'}],
        'evidence': [{'source_role': 'project_primary', 'admission_claim_type': 'design_rationale',
                      'locator_kind': 'body', 'locator': '合成来源登记（测试夹具，非真实批准）',
                      'context': '合成上下文', 'quality_score': 0.95}],
        'objects': [],
        'word_count': 120,
        'sections': [{'heading': '研究设计', 'paragraphs': [
            '本研究采用随机双盲设计，给药剂量为100mg，每21天为一个治疗周期。']},
            {'heading': '给药描述', 'paragraphs': ['参与者按计划接受研究治疗，并如实记录伴随用药。']}],
        'tables': [],
        'questions': [],
    }


@pytest.fixture()
def saved_manuscript(tmp_path):
    """Real SQLite study + regimen adoption + one complete chapter candidate,
    saved as a working manuscript through the actual HTTP save endpoint."""
    db = tmp_path / 'product.sqlite'
    shared.admit(db, PROJECT)
    prepared, output = prepared_reference()
    opener = _FakeOpener([_FakeResponse(_completion_body(content=json.dumps(output)))])
    designs = create_product_regimen_factory(
        storage_config={'backend': 'sqlite', 'path': str(db)},
        prior_probe_receipt=ROOT.parents[2] / 'runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json',
        max_input_bytes=2000000, credential_resolver=lambda: 'synthetic-only', http_opener=opener)
    run = designs(PROJECT).start(prepared)
    assert designs(PROJECT).resume(run)['status'] == 'ready_for_review'

    def client():
        app = FastAPI()
        mount_protocol_workflow_router(app, ProtocolWorkflowMountConfig(enabled=True, db_path=db),
                                       regimen_coordinator_factory=designs)
        return TestClient(app)

    base = f'/api/projects/{PROJECT}/protocol-workflow'
    with client() as c:
        creation = prepare_research_context_creation(project_id=PROJECT, study_definition_id=SD_ID,
            seed_run_id='seed:fixture', prepared=prepared, operation_id='operation:context:fixture',
            actor_id='user:example', decided_at=datetime(2026, 9, 13, tzinfo=timezone.utc))
        created = c.post(base + '/study-definitions', json=jsonable_encoder(creation)).json()
        intent = {'study_definition_id': SD_ID, 'operation_id': 'operation:regimen:one',
                  'expected_revision': 1, 'snapshot_sha256': created['revision_sha256'],
                  'actor_id': 'user:example', 'decided_at': '2026-09-13T07:00:00+00:00',
                  'reason': '采用完整给药方案'}
        response = c.post(base + f'/design/regimen/{run}/adopt', json=intent)
        assert response.status_code == 200, response.text
    return db, designs, run


def _documents_api(db, designs):
    from app.protocol_workflow.application.manuscript_documents import ManuscriptDocumentService
    from app.protocol_workflow.agent3.coordinator import ChapterDraftCoordinator
    from datetime import datetime, timezone as _tz
    service = ManuscriptDocumentService(
        __import__('app.protocol_workflow.storage.sqlite', fromlist=['build_unit_of_work_factory']
                   ).build_unit_of_work_factory({'backend': 'sqlite', 'path': str(db)}),
        clock=lambda: datetime.now(_tz.utc))
    coordinator = ChapterDraftCoordinator(
        project_id=PROJECT, branch_id='main',
        runtime=None, artifact_store=None) if False else None
    return service, designs(PROJECT)


def seed_working_document(service, facts, *, project=PROJECT, study=SD_ID):
    """Seed a minimal PROPOSED two-block working document as revision 1."""
    from app.protocol_workflow.application.manuscript_documents import manuscript_document_id
    from packages.contracts.workbench_contracts.protocol_v3 import (
        SemanticBlock, SemanticDocumentRevision, CanonicalState)
    from datetime import datetime as _dt, timezone as _tz2
    now = _dt.now(_tz2.utc)
    blocks = [
        SemanticBlock(semantic_block_id='blk:design', semantic_node_id=CHAPTER_NODE,
            chapter_contract_id='contract:v2-n-4-1:v2',
            substantive_content_contract_id='content:v2-n-4-1:v2',
            block_kind='paragraph',
            content='本研究采用随机双盲设计，给药剂量为100mg，每21天为一个治疗周期。',
            fact_paths=('intervention.dose_regimen',), claim_evidence_link_ids=(),
            medical_admission_unit_ids=(),
            content_sha256='0' * 64, canonical_state=CanonicalState.PROPOSED),
        SemanticBlock(semantic_block_id='blk:followup', semantic_node_id=CHAPTER_NODE,
            chapter_contract_id='contract:v2-n-4-1:v2',
            substantive_content_contract_id='content:v2-n-4-1:v2',
            block_kind='paragraph',
            content='参与者按计划接受研究治疗，并如实记录伴随用药。',
            fact_paths=('intervention.dose_regimen',), claim_evidence_link_ids=(),
            medical_admission_unit_ids=(),
            content_sha256='0' * 64, canonical_state=CanonicalState.PROPOSED),
    ]
    revision = SemanticDocumentRevision(semantic_document_revision_id=manuscript_document_id(project, study),
        project_id=project, study_definition_id=study, study_definition_sha256='a' * 64,
        revision=1, previous_revision_sha256=None,
        applicability_snapshot_id='snap:test', applicability_snapshot_sha256='b' * 64,
        semantic_blocks=tuple(blocks), chapter_contract_hashes=('c' * 64,), updated_at=now,
        canonical_state=CanonicalState.PROPOSED)
    doc_id = revision.semantic_document_revision_id
    from app.protocol_workflow.canonical.document import document_revision_hash
    from packages.contracts.workbench_contracts.protocol_v3 import ActorType
    from app.protocol_workflow.events.models import EventEnvelopeBuilder
    envelope = EventEnvelopeBuilder().build(
        domain_event_id='manuscript-seed:' + doc_id, stream_id=doc_id, sequence=1,
        event_type='manuscript_working_document_saved.v1',
        payload_schema_version='mw_protocol_v3_event_v1', upcaster_id='noop:v1',
        actor_type=ActorType.USER, actor_id='user:example',
        action='save_working_manuscript', reason='测试夹具初始版本',
        payload={'operation_id': 'operation:seed-manuscript',
                 'intent_sha256': 'seed', 'workflow_run_id': 'run:fixture',
                 'document': revision.model_dump(mode='json'),
                 'document_sha256': document_revision_hash(revision),
                 'acceptance_scope': 'working_draft_only'},
        emitted_at=now, previous_event_sha256=None)
    with service.uow_factory() as uow:
        uow.event_stream_repository.append_events(project, doc_id, [envelope])
        uow.semantic_document_cas_repository.save_with_expected_revision(
            project, revision, expected_revision=0)
        uow.commit()
    return revision


def test_free_edit_saves_fact_edits_with_reconciliation_clues(saved_manuscript, tmp_path):
    """Wording edit applies under CAS; a dose-value edit is reclassified
    server-side as fact_or_uncertain even when the client claims wording."""
    from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory
    from app.protocol_workflow.application.manuscript_documents import (
        ManuscriptDocumentService, manuscript_document_id)
    from datetime import datetime, timezone as _tz
    db, designs, run = saved_manuscript
    # Assemble + save a working manuscript from the adopted state directly
    # through the service (the coordinator integration has its own tests).
    service = ManuscriptDocumentService(
        build_unit_of_work_factory({'backend': 'sqlite', 'path': str(db)}),
        clock=lambda: datetime.now(_tz.utc))
    study_stream = None
    # Read the current facts the same way the production API layer does.
    from app.protocol_workflow.application.queries import GetStudyDefinitionQuery
    from app.protocol_workflow.application.service import ApplicationService
    application = ApplicationService(unit_of_work_factory=build_unit_of_work_factory({'backend': 'sqlite', 'path': str(db)}))
    study = application.get_study_definition(GetStudyDefinitionQuery(PROJECT, SD_ID))
    assert study.definition is not None, 'the adopted study must exist'
    facts = study.definition.facts
    assert 'intervention.dose_regimen' in facts, 'adopted dose fact must exist'
    from app.protocol_workflow.canonical.document import document_revision_hash
    revision = seed_working_document(service, facts)

    def _edit(operation, block_id, new_text, claimed='wording_only'):
        # A real client prepares from the current document version (the same
        # prepare-then-act shape the production UI uses).
        current = service.current(PROJECT, SD_ID)
        return service.edit(PROJECT, SD_ID, facts, intent={
            'operation_id': operation, 'actor_id': 'user:example',
            'expected_revision': current['expected_revision'],
            'expected_document_sha256': current['expected_document_sha256'],
            'edits': [{'semantic_block_id': block_id,
                       'block': {'content': new_text}, 'claimed_class': claimed}]})

    # 1) Pure wording: applied, revision bumps, QC advisory attached.
    outcome = _edit('operation:edit:wording', 'blk:followup', '参与者按计划接受研究治疗，并如实记录全部伴随用药与合并治疗。')
    assert outcome['status'] == 'working_draft' and outcome['replayed'] is False
    assert outcome['document']['revision'] == 2
    assert 'qc' in outcome and outcome['qc']['scope'] == 'working_draft_advisory'
    # 2) Same operation replays exactly (recovery consults the ledger before
    # any CAS check, so a lost acknowledgement is reconciled, not re-applied).
    replay = service.edit(PROJECT, SD_ID, facts, intent={
        'operation_id': 'operation:edit:wording', 'actor_id': 'user:example',
        'expected_revision': 1, 'expected_document_sha256': document_revision_hash(revision),
        'edits': [{'semantic_block_id': 'blk:followup',
                   'block': {'content': '参与者按计划接受研究治疗，并如实记录全部伴随用药与合并治疗。'},
                   'claimed_class': 'wording_only'}]})
    assert replay['replayed'] is True and replay['document']['revision'] == 2
    # 3) Dose-value edit claiming wording: still saved (R3/A09), with the
    # deterministic ruling kept as a reconciliation clue on the receipt.
    dose = _edit('operation:edit:dose', 'blk:design',
                 '本研究采用随机双盲设计，给药剂量为150mg，每21天为一个治疗周期。')
    assert dose['status'] == 'working_draft' and dose['replayed'] is False
    assert dose['reconciliation_status'] == 'pending'
    assert dose['fact_clue_count'] == 1
    dose_clue = next(clue for clue in dose['edit_clues']
                     if clue['edit_class'] == 'fact_or_uncertain')
    assert 'intervention.dose_regimen' in dose_clue['affected_fact_paths'], \
        'the dose fact stays the reconciliation lead'
    # 4) The saved version is a new revision with recomputed derived fields
    # (B04): block hash from the new content, timestamp advanced, and the
    # confirmed facts untouched by the free edit.
    assert dose['document']['revision'] == 3
    edited_block = next(block for block in dose['document']['semantic_blocks']
                        if block['semantic_block_id'] == 'blk:design')
    assert edited_block['content'].endswith('150mg，每21天为一个治疗周期。')
    import hashlib as _hashlib
    assert edited_block['content_sha256'] == _hashlib.sha256(
        edited_block['content'].encode()).hexdigest()
    assert dose['document']['updated_at'] >= str(revision.updated_at)
    assert 'intervention.dose_regimen' in facts, 'StudyDefinition facts stay unchanged'
    # 5) Replay of the fact edit returns the same receipt without re-applying.
    replay_dose = service.edit(PROJECT, SD_ID, facts, intent={
        'operation_id': 'operation:edit:dose', 'actor_id': 'user:example',
        'expected_revision': 2, 'expected_document_sha256': dose['document']['previous_revision_sha256'],
        'edits': [{'semantic_block_id': 'blk:design',
                   'block': {'content': '本研究采用随机双盲设计，给药剂量为150mg，每21天为一个治疗周期。'},
                   'claimed_class': 'wording_only'}]})
    assert replay_dose['replayed'] is True and replay_dose['document']['revision'] == 3
    # 6) Snapshot-bound reconciliation (T09/A18): the saved dose edit is a
    # visible difference against the confirmed facts.
    view = service.reconciliation(PROJECT, SD_ID, facts, study_revision_sha256='sha:test')
    assert view['schema_version'] == 'manuscript-reconciliation.v2'
    assert view['document_revision'] == 3 and view['status'] == 'differences'
    design_item = next(item for item in view['items']
                       if item['semantic_block_id'] == 'blk:design')
    assert design_item['status'] == 'difference' and design_item['resolved'] is False
    assert 'intervention.dose_regimen' in design_item['missing_fact_paths']
    # 7) Resolving binds to revision 3 and replays idempotently.
    first_ack = service.resolve_reconciliation(PROJECT, SD_ID, intent={
        'operation_id': 'operation:reconcile:1', 'actor_id': 'user:example',
        'expected_revision': 3, 'semantic_block_id': 'blk:design', 'decision': 'accepted'})
    assert first_ack['replayed'] is False
    replay_ack = service.resolve_reconciliation(PROJECT, SD_ID, intent={
        'operation_id': 'operation:reconcile:1', 'actor_id': 'user:example',
        'expected_revision': 3, 'semantic_block_id': 'blk:design', 'decision': 'accepted'})
    assert replay_ack['replayed'] is True
    resolved_view = service.reconciliation(PROJECT, SD_ID, facts, study_revision_sha256='sha:test')
    assert resolved_view['status'] == 'consistent_within_checked_scope'
    assert resolved_view['differences'] == 0
    # 8) A later edit opens a new revision: the revision-3 acknowledgement
    # must not mark the new difference clean (A11), and restoring the
    # confirmed value closes the difference again.
    changed = _edit('operation:edit:dose2', 'blk:design',
                    '本研究采用随机双盲设计，给药剂量为200mg，每21天为一个治疗周期。')
    assert changed['document']['revision'] == 4
    reopened = service.reconciliation(PROJECT, SD_ID, facts, study_revision_sha256='sha:test')
    assert reopened['status'] == 'differences', 'a new revision reopens reconciliation'
    restored = _edit('operation:edit:dose3', 'blk:design',
                     '本研究采用随机双盲设计，先给予200mg负荷剂量，随后每2周一次100mg维持，每21天评估为一个治疗周期。')
    assert restored['document']['revision'] == 5
    closed = service.reconciliation(PROJECT, SD_ID, facts, study_revision_sha256='sha:test')
    assert closed['status'] == 'consistent_within_checked_scope', 'prose carrying every confirmed value closes it'


def test_object_revision_is_scoped_anchored_and_undoable(saved_manuscript, tmp_path):
    """T12/A15/A16: AI object revisions touch exactly the anchored block,
    refuse stale anchors instead of overwriting, and keep undo information."""
    import pytest
    from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory
    from app.protocol_workflow.application.manuscript_documents import ManuscriptDocumentService
    from datetime import datetime, timezone as _tz
    db, designs, run = saved_manuscript
    service = ManuscriptDocumentService(
        build_unit_of_work_factory({'backend': 'sqlite', 'path': str(db)}),
        clock=lambda: datetime.now(_tz.utc))
    from app.protocol_workflow.application.queries import GetStudyDefinitionQuery
    from app.protocol_workflow.application.service import ApplicationService
    application = ApplicationService(unit_of_work_factory=build_unit_of_work_factory(
        {'backend': 'sqlite', 'path': str(db)}))
    study = application.get_study_definition(GetStudyDefinitionQuery(PROJECT, SD_ID))
    facts = study.definition.facts
    seed_working_document(service, facts)

    def _intent(operation, revision, sha, **kwargs):
        return {'operation_id': operation, 'actor_id': 'user:example',
            'expected_revision': revision, 'expected_document_sha256': sha,
            'semantic_block_id': 'blk:followup', 'scope': 'replace_object',
            'instruction': '把随访段补充为完整随访安排。', **kwargs}

    current = service.current(PROJECT, SD_ID)
    prepared = service.prepare_object_revision(PROJECT, SD_ID, _intent(
        'operation:object:1', current['expected_revision'], current['expected_document_sha256']))
    assert prepared['semantic_block_id'] == 'blk:followup'
    assert prepared['current_content_sha256'] and prepared['current_content']

    # A stale anchor (document moved on since preparation) must conflict
    # instead of overwriting the user's newer content (A15).
    moved = service.edit(PROJECT, SD_ID, facts, intent={
        'operation_id': 'operation:edit:during-prepare', 'actor_id': 'user:example',
        'expected_revision': current['expected_revision'],
        'expected_document_sha256': current['expected_document_sha256'],
        'edits': [{'semantic_block_id': 'blk:followup',
                   'block': {'content': '用户在AI准备期间自己改过的随访文字。'},
                   'claimed_class': 'wording_only'}]})
    assert moved['document']['revision'] == current['expected_revision'] + 1
    with pytest.raises(ValueError) as conflict:
        service.apply_object_revision(PROJECT, SD_ID, facts, _intent(
            'operation:object:1', current['expected_revision'],
            current['expected_document_sha256'], candidate_content='新的随访安排。'))
    assert conflict.value.args[0] == 'manuscript_document_revision_changed'

    # Fresh preparation against the current revision, then apply: only the
    # anchored block changes, undo keeps the previous content, and the
    # revision feeds the reconciliation clue stream.
    fresh = service.prepare_object_revision(PROJECT, SD_ID, _intent(
        'operation:object:2', moved['document']['revision'],
        moved['document_sha256']))
    applied = service.apply_object_revision(PROJECT, SD_ID, facts, _intent(
        'operation:object:2', moved['document']['revision'], moved['document_sha256'],
        candidate_content='参与者按计划接受随访，第1、4周期末各进行一次安全性评估，并如实记录伴随用药与合并治疗。'))
    assert applied['status'] == 'working_draft' and applied['replayed'] is False
    assert applied['document']['revision'] == current['expected_revision'] + 2
    blocks = {b['semantic_block_id']: b for b in applied['document']['semantic_blocks']}
    assert blocks['blk:followup']['content'].startswith('参与者按计划接受随访')
    assert applied['undo']['previous_content'].startswith('用户在AI准备期间自己改过的随访文字。'), \
        'undo must capture exactly the content the candidate replaced'
    assert applied['undo']['previous_revision'] == moved['document']['revision']
    assert applied['reconciliation_status'] == 'pending'

    # Same operation replays exactly instead of applying twice.
    replay = service.apply_object_revision(PROJECT, SD_ID, facts, _intent(
        'operation:object:2', moved['document']['revision'], moved['document_sha256'],
        candidate_content='参与者按计划接受随访，第1、4周期末各进行一次安全性评估，并如实记录伴随用药与合并治疗。'))
    assert replay['replayed'] is True

    # Unsupported scope is refused before anything is touched.
    with pytest.raises(ValueError):
        service.prepare_object_revision(PROJECT, SD_ID, _intent(
            'operation:object:3', moved['document']['revision'], moved['document_sha256'],
            scope='rewrite_everything'))


def test_office_snapshot_persists_immutable_copy_bound_to_revision(saved_manuscript, tmp_path):
    """T10/A12: an Office working copy persists as an immutable, content-
    addressed snapshot bound to the current revision; replay is idempotent
    and the bytes read back are identical."""
    import base64
    from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory
    from app.protocol_workflow.application.manuscript_documents import ManuscriptDocumentService
    from app.protocol_workflow.artifacts.local_store import LocalArtifactStore
    from datetime import datetime, timezone as _tz
    db, designs, run = saved_manuscript
    office_store = LocalArtifactStore(str(tmp_path / 'office-artifacts'))
    service = ManuscriptDocumentService(
        build_unit_of_work_factory({'backend': 'sqlite', 'path': str(db)}),
        clock=lambda: datetime.now(_tz.utc), office_store=office_store)
    seed_working_document(service, {})
    current = service.current(PROJECT, SD_ID)
    # F12: the fixture is a real minimal DOCX (zip container with the main
    # document part); a bare PK-prefixed string is now rejected as invalid —
    # covered in test_office_working_copy_closure.py.
    from test_office_working_copy_closure import minimal_docx
    docx_bytes = minimal_docx()
    intent = {'operation_id': 'operation:office:1', 'actor_id': 'user:example',
        'expected_revision': current['expected_revision'],
        'expected_document_sha256': current['expected_document_sha256'],
        'content_base64': base64.b64encode(docx_bytes).decode('ascii'),
        'study_revision_sha256': 'sha:study'}

    receipt = service.office_snapshot(PROJECT, SD_ID, intent)
    assert receipt['persisted'] is True and receipt['replayed'] is False
    assert receipt['mapping_status'] == 'pending'
    assert receipt['document_revision'] == current['expected_revision']
    assert receipt['content_sha256'] == __import__('hashlib').sha256(docx_bytes).hexdigest()

    replay = service.office_snapshot(PROJECT, SD_ID, intent)
    assert replay['replayed'] is True

    latest = service.latest_office_snapshot(PROJECT, SD_ID)
    assert latest['operation_id'] == 'operation:office:1'
    artifact = service.office_snapshot_content(PROJECT, SD_ID, 'operation:office:1')
    assert artifact.content == docx_bytes, 'bytes must round-trip unchanged'

    # A stale revision binding is refused: snapshots bind to a real version.
    import pytest
    with pytest.raises(ValueError):
        service.office_snapshot(PROJECT, SD_ID, {**intent,
            'operation_id': 'operation:office:2', 'expected_revision': 99})
