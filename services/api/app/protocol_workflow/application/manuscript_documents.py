"""Save one complete working document through the product's existing UoW."""
import hashlib

from packages.contracts.workbench_contracts.protocol_v3 import ActorType, SemanticDocumentRevision
from app.protocol_workflow.canonical.hashing import canonical_json
from app.protocol_workflow.canonical.document import document_revision_hash
from app.protocol_workflow.events.models import verify_event_integrity
from app.protocol_workflow.events.unit_of_work import EventSourcedUnitOfWork
from app.protocol_workflow.agent3.manuscript_document import assemble_working_manuscript
from app.protocol_workflow.qc.manuscript_qc import run_manuscript_qc
from .manuscript_edits import block_content_text, edit_intent_sha256, reclassify_edit


def manuscript_document_id(project_id, study_id):
    return 'manuscript:' + hashlib.sha256(canonical_json([project_id, study_id]).encode()).hexdigest()


class ManuscriptDocumentService:
    def __init__(self, uow_factory, clock):
        self.uow_factory = uow_factory
        self.clock = clock
        self.atomic = EventSourcedUnitOfWork(clock=clock)

    def current(self, project_id, study_id):
        document_id = manuscript_document_id(project_id, study_id)
        with self.uow_factory() as uow:
            document = uow.semantic_document_repository.get_current(project_id, document_id)
        return {'semantic_document_revision_id': document_id,
            'expected_revision': document.revision if document else 0,
            'expected_document_sha256': document_revision_hash(document) if document else None}

    @staticmethod
    def _intent(project_id, study_id, run_id, intent):
        return hashlib.sha256(canonical_json([project_id, study_id, run_id, intent]).encode()).hexdigest()

    def _receipt(self, uow, project_id, study_id, run_id, intent):
        document_id = manuscript_document_id(project_id, study_id)
        for event in uow.event_stream_repository.read_events(project_id, document_id):
            if event.event_type != 'manuscript_working_document_saved.v1' or event.payload.get('operation_id') != intent['operation_id']:
                continue
            verify_event_integrity(event)
            if event.payload['intent_sha256'] != self._intent(project_id, study_id, run_id, intent):
                raise ValueError('manuscript_save_intent_changed')
            document = SemanticDocumentRevision.model_validate(event.payload['document'])
            if document_revision_hash(document) != event.payload['document_sha256']:
                raise ValueError('manuscript_saved_document_changed')
            return {'document': document.model_dump(mode='json'), 'document_sha256': document_revision_hash(document),
                'operation_id': intent['operation_id'], 'replayed': True, 'status': 'working_draft'}
        return None

    def recover(self, project_id, study_id, run_id, intent):
        with self.uow_factory() as uow:
            return self._receipt(uow, project_id, study_id, run_id, intent)

    def save(self, project_id, study_id, owner, run_id, intent):
        existing = self.recover(project_id, study_id, run_id, intent)
        if existing is not None:
            return existing
        prepared, state = owner.prepared_request(run_id), owner.read(run_id)
        document_id = manuscript_document_id(project_id, study_id)
        with self.uow_factory() as uow:
            # Recheck inside the transaction after any competing saver commits.
            existing = self._receipt(uow, project_id, study_id, run_id, intent)
            if existing is not None:
                return existing
            current = uow.semantic_document_repository.get_current(project_id, document_id)
            if ((current.revision if current else 0) != intent['expected_revision']
                    or (document_revision_hash(current) if current else None) != intent['expected_document_sha256']):
                raise ValueError('manuscript_document_revision_changed')
            study = uow.study_definition_repository.get_current(project_id, study_id)
            if study is None:
                raise ValueError('manuscript_study_missing')
            now = self.clock()
            document = assemble_working_manuscript(prepared, state, study,
                document_id=document_id, now=now, current=current)
            payload = {'operation_id': intent['operation_id'],
                'intent_sha256': self._intent(project_id, study_id, run_id, intent),
                'workflow_run_id': run_id, 'document': document.model_dump(mode='json'),
                'document_sha256': document_revision_hash(document),
                'provenance': {'manuscript_input_sha256': prepared.input_sha256,
                    'source_run_id': prepared.to_payload()['source_run_id']},
                'acceptance_scope': 'working_draft_only'}
            self.atomic.build_and_apply(uow, project_id=project_id, stream_id=document_id,
                aggregate=document, cas_repository_handle_name='semantic_document_cas_repository',
                expected_revision=intent['expected_revision'], event={
                    'domain_event_id': 'manuscript-save:' + hashlib.sha256(canonical_json([document_id, intent['operation_id']]).encode()).hexdigest(),
                    'stream_id': document_id, 'event_type': 'manuscript_working_document_saved.v1',
                    'payload_schema_version': 'mw_protocol_v3_event_v1', 'upcaster_id': 'noop:v1',
                    'actor_type': ActorType.USER, 'actor_id': intent['actor_id'],
                    'action': 'save_working_manuscript', 'reason': '保留完整初稿用于阅读与修改；尚未完成医学和Word验收。',
                    'payload': payload, 'emitted_at': now})
            return {'document': document.model_dump(mode='json'), 'document_sha256': document_revision_hash(document),
                'operation_id': intent['operation_id'], 'replayed': False, 'status': 'working_draft',
                'qc': run_manuscript_qc(document.model_dump(mode='json'))}

    # ------------------------------------------------------------------
    # Controlled edits: server reclassifies every edit; a single fact-class
    # edit rejects the whole batch (never a partial silent apply) and returns
    # the fact proposals for the StudyDefinition confirmation path.
    # ------------------------------------------------------------------

    def _edit_intent(self, project_id, study_id, intent):
        return hashlib.sha256(canonical_json([project_id, study_id, 'manuscript-edit',
            intent['operation_id'], intent['expected_revision'], intent['edits']]).encode()).hexdigest()

    def recover_edit(self, project_id, study_id, intent):
        document_id = manuscript_document_id(project_id, study_id)
        with self.uow_factory() as uow:
            for event in uow.event_stream_repository.read_events(project_id, document_id):
                if event.event_type != 'manuscript_working_document_edited.v1' \
                        or event.payload.get('operation_id') != intent['operation_id']:
                    continue
                verify_event_integrity(event)
                if event.payload['intent_sha256'] != self._edit_intent(project_id, study_id, intent):
                    raise ValueError('manuscript_edit_intent_changed')
                document = SemanticDocumentRevision.model_validate(event.payload['document'])
                return {'document': document.model_dump(mode='json'),
                    'document_sha256': document_revision_hash(document),
                    'operation_id': intent['operation_id'], 'replayed': True, 'status': 'working_draft'}
        return None

    def edit(self, project_id, study_id, confirmed_facts, intent):
        """Apply wording-level edits under CAS; fact edits become proposals.

        ``confirmed_facts`` are the caller's authoritative read of the current
        StudyDefinition facts; reclassification never trusts the client's
        claimed edit class.
        """
        existing = self.recover_edit(project_id, study_id, intent)
        if existing is not None:
            return existing
        document_id = manuscript_document_id(project_id, study_id)
        with self.uow_factory() as uow:
            current = uow.semantic_document_repository.get_current(project_id, document_id)
            if current is None:
                raise ValueError('manuscript_document_missing')
            if current.revision != intent['expected_revision'] or \
                    document_revision_hash(current) != intent['expected_document_sha256']:
                raise ValueError('manuscript_document_revision_changed')
            blocks = {block.semantic_block_id: block for block in current.semantic_blocks}
            proposals = []
            applied = []
            for edit in intent['edits']:
                block = blocks.get(edit.get('semantic_block_id'))
                if block is None:
                    raise ValueError('manuscript_edit_block_unknown')
                old_text = block_content_text(block.model_dump(mode='json'))
                new_block = edit.get('block') or {}
                new_text = block_content_text({**block.model_dump(mode='json'), **new_block})
                ruling = reclassify_edit(old_text=old_text, new_text=new_text,
                    confirmed_facts=confirmed_facts, claimed_class=edit.get('claimed_class'))
                if ruling['edit_class'] == 'fact_or_uncertain':
                    proposals.append({'semantic_block_id': edit['semantic_block_id'],
                        'affected_fact_paths': list(ruling['affected_fact_paths']),
                        'reason': ruling['reason'] or '按事实相关编辑处理。',
                        'proposed_text': new_text})
                    continue
                applied.append((edit, ruling))
            if proposals:
                return {'status': 'needs_fact_confirmation', 'fact_proposals': proposals,
                    'operation_id': intent['operation_id'], 'document': None}
            updated_blocks = []
            for edit, _ruling in applied:
                new_block = edit.get('block') or {}
                updated_blocks.append((edit['semantic_block_id'], new_block))
            now = self.clock()
            raw = current.model_dump(mode='json')
            by_id = {b['semantic_block_id']: b for b in raw['semantic_blocks']}
            for block_id, replacement in updated_blocks:
                by_id[block_id].update(replacement)
            document = SemanticDocumentRevision.model_validate({
                **raw, 'revision': current.revision + 1,
                'previous_revision_sha256': document_revision_hash(current),
                'canonical_state': 'proposed'})
            payload = {'operation_id': intent['operation_id'],
                'intent_sha256': self._edit_intent(project_id, study_id, intent),
                'document': document.model_dump(mode='json'),
                'document_sha256': document_revision_hash(document),
                'edit_count': len(applied),
                'acceptance_scope': 'working_draft_only'}
            self.atomic.build_and_apply(uow, project_id=project_id, stream_id=document_id,
                aggregate=document, cas_repository_handle_name='semantic_document_cas_repository',
                expected_revision=intent['expected_revision'], event={
                    'domain_event_id': 'manuscript-edit:' + hashlib.sha256(canonical_json(
                        [document_id, intent['operation_id']]).encode()).hexdigest(),
                    'stream_id': document_id, 'event_type': 'manuscript_working_document_edited.v1',
                    'payload_schema_version': 'mw_protocol_v3_event_v1', 'upcaster_id': 'noop:v1',
                    'actor_type': ActorType.USER, 'actor_id': intent['actor_id'],
                    'action': 'edit_working_manuscript',
                    'reason': '受控措辞编辑；事实相关修改走研究事实确认流程。',
                    'payload': payload, 'emitted_at': now})
            return {'document': document.model_dump(mode='json'),
                'document_sha256': document_revision_hash(document),
                'operation_id': intent['operation_id'], 'replayed': False, 'status': 'working_draft',
                'qc': run_manuscript_qc(document.model_dump(mode='json'))}
