"""Save one complete working document through the product's existing UoW."""
import hashlib

from packages.contracts.workbench_contracts.protocol_v3 import ActorType, SemanticDocumentRevision
from app.protocol_workflow.canonical.hashing import canonical_json
from app.protocol_workflow.canonical.document import document_revision_hash
from app.protocol_workflow.events.models import verify_event_integrity
from app.protocol_workflow.events.unit_of_work import EventSourcedUnitOfWork
from app.protocol_workflow.agent3.manuscript_document import assemble_working_manuscript
from app.protocol_workflow.qc.manuscript_qc import run_manuscript_qc
from .manuscript_edits import (
    _digit_bounded, _negated, block_content_text, edit_intent_sha256, reclassify_edit)


def manuscript_document_id(project_id, study_id):
    return 'manuscript:' + hashlib.sha256(canonical_json([project_id, study_id]).encode()).hexdigest()


class OfficeWorkingCopyConflictError(Exception):
    """Another Office session advanced the working copy past the client's base.

    Carries the latest snapshot receipt so the caller can surface the real
    current version instead of a bare 409 (audit G1/F04).
    """

    def __init__(self, latest_receipt):
        super().__init__('manuscript_office_base_conflict')
        self.latest_receipt = latest_receipt


class ManuscriptDocumentService:
    def __init__(self, uow_factory, clock, office_store=None):
        self.uow_factory = uow_factory
        self.clock = clock
        self.atomic = EventSourcedUnitOfWork(clock=clock)
        self.office_store = office_store

    def current(self, project_id, study_id):
        document_id = manuscript_document_id(project_id, study_id)
        with self.uow_factory() as uow:
            document = uow.semantic_document_repository.get_current(project_id, document_id)
        return {'semantic_document_revision_id': document_id,
            'expected_revision': document.revision if document else 0,
            'expected_document_sha256': document_revision_hash(document) if document else None}

    def saved(self, project_id, study_id):
        """Full current saved revision (semantic blocks included) or None."""
        document_id = manuscript_document_id(project_id, study_id)
        with self.uow_factory() as uow:
            document = uow.semantic_document_repository.get_current(project_id, document_id)
        if document is None:
            return None
        return {'document': document.model_dump(mode='json'),
            'document_sha256': document_revision_hash(document),
            'revision': document.revision}

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
    # Free working-draft edits (requirements-v2 R3): every edit persists as
    # a new version.  The deterministic classifier no longer gates saving;
    # its ruling rides on each saved edit as a reconciliation clue for the
    # explicit snapshot-based reconciliation stage.  Technical checks
    # (identity, revision, structure, server-owned hashes) still apply.
    # ------------------------------------------------------------------

    #: Editors may replace only these block fields; anything else in the
    #: incoming dict is ignored instead of blindly merged (R-C03).
    EDITABLE_BLOCK_FIELDS = ('content', 'block_kind')

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

    # ------------------------------------------------------------------
    # Snapshot-bound reconciliation (T09/A09-A11): deterministic recomputation
    # for the current saved revision only.  Analyses are never stored as
    # state — the view recomputes from (document revision, confirmed facts,
    # resolve events), so an old analysis can never mark a newer document
    # clean, and a resolved difference stays bound to the revision it was
    # acknowledged at.
    # ------------------------------------------------------------------

    def reconciliation(self, project_id, study_id, confirmed_facts, study_revision_sha256):
        document_id = manuscript_document_id(project_id, study_id)
        with self.uow_factory() as uow:
            document = uow.semantic_document_repository.get_current(project_id, document_id)
            if document is None:
                return None
            events = uow.event_stream_repository.read_events(project_id, document_id)
        blocks = {block.semantic_block_id: block for block in document.semantic_blocks}
        clues = {}
        for event in events:
            if event.event_type not in ('manuscript_working_document_edited.v1',
                                        'manuscript_object_revised.v1'):
                continue
            for clue in event.payload.get('edit_clues', []):
                # Signals accumulate per block: a later edit must not erase an
                # earlier deviation that still exists in the current text.
                block_clue = clues.setdefault(clue['semantic_block_id'],
                    {'semantic_block_id': clue['semantic_block_id'],
                     'edit_class': clue.get('edit_class'),
                     'affected_fact_paths': [], 'signals': [], 'reason': ''})
                block_clue['signals'].extend(clue.get('signals') or ())
                for path in clue.get('affected_fact_paths') or ():
                    if path not in block_clue['affected_fact_paths']:
                        block_clue['affected_fact_paths'].append(path)
        resolutions = {(event.payload.get('semantic_block_id'), event.payload.get('document_revision'))
                       for event in events
                       if event.event_type == 'manuscript_reconciliation_resolved.v1'}
        items, differences = [], 0
        for block_id in sorted(clues):
            clue = clues[block_id]
            signals = clue.get('signals') or ()
            block = blocks.get(block_id)
            if block is None:
                continue
            text = block_content_text(block.model_dump(mode='json'))
            paths = tuple(clue.get('affected_fact_paths') or ())
            missing = []
            for signal in signals:
                value = signal.get('value_text') or ''
                if not value:
                    continue
                present_now = _digit_bounded(text, value)
                negated_now = _negated(text, value)
                if signal.get('present_in_old') and not present_now:
                    if signal.get('fact_path') not in missing:
                        missing.append(signal['fact_path'])
                elif present_now and signal.get('negated_in_old') != negated_now:
                    if signal.get('fact_path') not in missing:
                        missing.append(signal['fact_path'])
            status = ('difference' if missing else 'consistent')
            resolved = (block_id, document.revision) in resolutions
            if status == 'difference' and not resolved:
                differences += 1
            items.append({'semantic_block_id': block_id,
                'edit_class': clue.get('edit_class'),
                'affected_fact_paths': list(paths),
                'missing_fact_paths': missing,
                'status': status, 'resolved': resolved})
        return {'schema_version': 'manuscript-reconciliation.v1',
            'document_revision': document.revision,
            'document_sha256': document_revision_hash(document),
            'study_revision_sha256': study_revision_sha256,
            'study_matches_current': True,
            'items': items, 'differences': differences,
            'status': 'pending' if not clues else ('differences' if differences else 'consistent')}

    def _resolve_intent(self, project_id, study_id, intent):
        return hashlib.sha256(canonical_json([project_id, study_id, 'manuscript-reconcile',
            intent['operation_id'], intent['expected_revision'],
            intent.get('semantic_block_id'), intent.get('decision')]).encode()).hexdigest()

    def resolve_reconciliation(self, project_id, study_id, intent):
        """Acknowledge a difference for the current revision; idempotent replay."""
        document_id = manuscript_document_id(project_id, study_id)
        with self.uow_factory() as uow:
            for event in uow.event_stream_repository.read_events(project_id, document_id):
                if event.event_type != 'manuscript_reconciliation_resolved.v1' \
                        or event.payload.get('operation_id') != intent['operation_id']:
                    continue
                verify_event_integrity(event)
                if event.payload['intent_sha256'] != self._resolve_intent(project_id, study_id, intent):
                    raise ValueError('manuscript_reconcile_intent_changed')
                return {'operation_id': intent['operation_id'], 'replayed': True,
                        'status': 'reconciliation_resolved'}
            current = uow.semantic_document_repository.get_current(project_id, document_id)
            if current is None:
                raise ValueError('manuscript_document_missing')
            if current.revision != intent['expected_revision']:
                raise ValueError('manuscript_document_revision_changed')
            now = self.clock()
            payload = {'operation_id': intent['operation_id'],
                'intent_sha256': self._resolve_intent(project_id, study_id, intent),
                'semantic_block_id': intent.get('semantic_block_id'),
                'decision': intent.get('decision', 'accepted'),
                'document_revision': current.revision,
                'acceptance_scope': 'working_draft_only'}
            # A resolution changes no document content: append the event to the
            # stream only — the document CAS stays untouched.
            params = {
                'domain_event_id': 'manuscript-reconcile:' + hashlib.sha256(canonical_json(
                    [document_id, intent['operation_id']]).encode()).hexdigest(),
                'stream_id': document_id, 'event_type': 'manuscript_reconciliation_resolved.v1',
                'payload_schema_version': 'mw_protocol_v3_event_v1', 'upcaster_id': 'noop:v1',
                'actor_type': ActorType.USER, 'actor_id': intent['actor_id'],
                'action': 'resolve_manuscript_reconciliation',
                'reason': '用户确认该差异按当前工作稿保留；仅绑定本次文档版本。',
                'payload': payload, 'emitted_at': now}
            head = uow.event_stream_repository.get_stream_head(project_id, document_id)
            if head is None:
                built = self.atomic.builder.build(sequence=1, previous_event_sha256=None, **params)
            else:
                built = self.atomic.builder.continue_chain(
                    head_sha256=head.last_event_sha256,
                    head_sequence=head.last_sequence, **params)
            uow.event_stream_repository.append_events(project_id, document_id, [built])
            uow.commit()
            return {'operation_id': intent['operation_id'], 'replayed': False,
                    'status': 'reconciliation_resolved'}

    # ------------------------------------------------------------------
    # Scoped AI object revisions (T12/A15/A16): replace_object /
    # patch_object on ONE anchored block.  Every operation binds target
    # block, document revision and expected content hash; if the user
    # edited the block while the candidate was being prepared, the anchor
    # no longer matches and the apply refuses instead of overwriting.
    # Nothing outside the anchored block changes, so "只改流程表" can never
    # become a whole-draft rewrite.
    # ------------------------------------------------------------------

    OBJECT_EDITABLE_KINDS = ('paragraph', 'table')
    OBJECT_REVISION_SCOPES = ('replace_object', 'patch_object')

    def _object_revision_intent(self, project_id, study_id, intent):
        return hashlib.sha256(canonical_json([project_id, study_id, 'object-revision',
            intent['operation_id'], intent['expected_revision'],
            intent['semantic_block_id'], intent.get('expected_content_sha256'),
            intent.get('scope'), intent.get('instruction')]).encode()).hexdigest()

    def prepare_object_revision(self, project_id, study_id, intent):
        """Freeze the anchor and material for one AI object revision."""
        if intent.get('scope') not in self.OBJECT_REVISION_SCOPES:
            raise ValueError('manuscript_object_scope_invalid')
        if not str(intent.get('instruction') or '').strip():
            raise ValueError('manuscript_object_instruction_missing')
        document_id = manuscript_document_id(project_id, study_id)
        with self.uow_factory() as uow:
            current = uow.semantic_document_repository.get_current(project_id, document_id)
            if current is None:
                raise ValueError('manuscript_document_missing')
            if current.revision != intent['expected_revision'] or \
                    document_revision_hash(current) != intent['expected_document_sha256']:
                raise ValueError('manuscript_document_revision_changed')
            block = next((b for b in current.semantic_blocks
                          if b.semantic_block_id == intent['semantic_block_id']), None)
            if block is None:
                raise ValueError('manuscript_edit_block_unknown')
            if block.block_kind.value not in self.OBJECT_EDITABLE_KINDS:
                raise ValueError('manuscript_object_kind_unsupported')
            content_sha = hashlib.sha256((block.content or '').encode()).hexdigest()
            expected = intent.get('expected_content_sha256')
            if expected and expected != content_sha:
                raise ValueError('manuscript_object_anchor_changed')
        return {'schema_version': 'object-revision-request.v1',
            'scope': intent['scope'],
            'instruction': intent['instruction'],
            'semantic_block_id': intent['semantic_block_id'],
            'block_kind': block.block_kind.value,
            'current_content': block.content,
            'current_content_sha256': content_sha,
            'document_revision': current.revision,
            'document_sha256': document_revision_hash(current)}

    def recover_object_revision(self, project_id, study_id, intent):
        document_id = manuscript_document_id(project_id, study_id)
        with self.uow_factory() as uow:
            for event in uow.event_stream_repository.read_events(project_id, document_id):
                if event.event_type != 'manuscript_object_revised.v1' \
                        or event.payload.get('operation_id') != intent['operation_id']:
                    continue
                verify_event_integrity(event)
                if event.payload['intent_sha256'] != self._object_revision_intent(project_id, study_id, intent):
                    raise ValueError('manuscript_object_intent_changed')
                document = SemanticDocumentRevision.model_validate(event.payload['document'])
                return {'document': document.model_dump(mode='json'),
                    'document_sha256': document_revision_hash(document),
                    'operation_id': intent['operation_id'], 'replayed': True,
                    'status': 'working_draft', 'scope': event.payload.get('scope')}
        return None

    def apply_object_revision(self, project_id, study_id, confirmed_facts, intent):
        """Apply the candidate to exactly the anchored block under CAS (A15)."""
        existing = self.recover_object_revision(project_id, study_id, intent)
        if existing is not None:
            return existing
        if intent.get('scope') not in self.OBJECT_REVISION_SCOPES:
            raise ValueError('manuscript_object_scope_invalid')
        candidate = intent.get('candidate_content')
        if not isinstance(candidate, str) or not candidate.strip():
            raise ValueError('manuscript_object_candidate_invalid')
        document_id = manuscript_document_id(project_id, study_id)
        with self.uow_factory() as uow:
            current = uow.semantic_document_repository.get_current(project_id, document_id)
            if current is None:
                raise ValueError('manuscript_document_missing')
            if current.revision != intent['expected_revision'] or \
                    document_revision_hash(current) != intent['expected_document_sha256']:
                raise ValueError('manuscript_document_revision_changed')
            block = next((b for b in current.semantic_blocks
                          if b.semantic_block_id == intent['semantic_block_id']), None)
            if block is None:
                raise ValueError('manuscript_edit_block_unknown')
            if block.block_kind.value not in self.OBJECT_EDITABLE_KINDS:
                raise ValueError('manuscript_object_kind_unsupported')
            content_sha = hashlib.sha256((block.content or '').encode()).hexdigest()
            expected = intent.get('expected_content_sha256')
            if expected and expected != content_sha:
                # The user touched this object while the candidate was being
                # prepared: surface the conflict, never overwrite silently.
                raise ValueError('manuscript_object_anchor_changed')
            if block.block_kind.value == 'table':
                import json as _json
                try:
                    parsed = _json.loads(candidate)
                    table = parsed.get('table') if isinstance(parsed, dict) else None
                    if not isinstance(table, dict) or not table.get('rows') or not table.get('columns'):
                        raise ValueError('manuscript_object_table_content_invalid')
                except (TypeError, ValueError) as exc:
                    if str(exc) == 'manuscript_object_table_content_invalid':
                        raise
                    raise ValueError('manuscript_object_table_content_invalid') from exc
            now = self.clock()
            old_text = block_content_text(block.model_dump(mode='json'))
            merged = {**block.model_dump(mode='json'), 'content': candidate,
                'content_sha256': hashlib.sha256(candidate.encode()).hexdigest()}
            new_text = block_content_text(merged)
            ruling = reclassify_edit(old_text=old_text, new_text=new_text,
                confirmed_facts=confirmed_facts, claimed_class=None)
            raw = current.model_dump(mode='json')
            by_id = {b['semantic_block_id']: b for b in raw['semantic_blocks']}
            by_id[block.semantic_block_id] = merged
            raw['semantic_blocks'] = [by_id[b['semantic_block_id']] for b in raw['semantic_blocks']]
            document = SemanticDocumentRevision.model_validate({
                **raw, 'revision': current.revision + 1,
                'previous_revision_sha256': document_revision_hash(current),
                'updated_at': now, 'canonical_state': 'proposed'})
            payload = {'operation_id': intent['operation_id'],
                'intent_sha256': self._object_revision_intent(project_id, study_id, intent),
                'document': document.model_dump(mode='json'),
                'document_sha256': document_revision_hash(document),
                'scope': intent['scope'],
                'semantic_block_id': block.semantic_block_id,
                'expected_content_sha256': content_sha,
                'edit_clues': [{'semantic_block_id': block.semantic_block_id,
                    'edit_class': ruling['edit_class'],
                    'affected_fact_paths': list(ruling['affected_fact_paths']),
                    'signals': list(ruling.get('signals') or ()),
                    'reason': ruling['reason'] or ''}],
                'reconciliation_status': 'pending',
                'undo': {'semantic_block_id': block.semantic_block_id,
                    'previous_revision': current.revision,
                    'previous_content_sha256': content_sha,
                    'previous_content': block.content},
                'acceptance_scope': 'working_draft_only'}
            self.atomic.build_and_apply(uow, project_id=project_id, stream_id=document_id,
                aggregate=document, cas_repository_handle_name='semantic_document_cas_repository',
                expected_revision=intent['expected_revision'], event={
                    'domain_event_id': 'manuscript-object:' + hashlib.sha256(canonical_json(
                        [document_id, intent['operation_id']]).encode()).hexdigest(),
                    'stream_id': document_id, 'event_type': 'manuscript_object_revised.v1',
                    'payload_schema_version': 'mw_protocol_v3_event_v1', 'upcaster_id': 'noop:v1',
                    'actor_type': ActorType.USER, 'actor_id': intent['actor_id'],
                    'action': 'apply_object_revision',
                    'reason': '范围受限的AI对象修订：仅替换锚定对象，保留撤销信息。',
                    'payload': payload, 'emitted_at': now})
            return {'document': document.model_dump(mode='json'),
                'document_sha256': document_revision_hash(document),
                'operation_id': intent['operation_id'], 'replayed': False,
                'status': 'working_draft', 'scope': intent['scope'],
                'semantic_block_id': block.semantic_block_id,
                'reconciliation_status': 'pending',
                'undo': payload['undo'],
                'qc': run_manuscript_qc(document.model_dump(mode='json'))}


    # ------------------------------------------------------------------
    # Office working copies (T10): immutable DOCX snapshots persisted in the
    # artifact store and bound to the current semantic revision + study
    # revision.  The bytes never enter the event stream — the event carries
    # the content hash and artifact revision; the store deduplicates bytes.
    # ------------------------------------------------------------------

    def _office_snapshot_intent(self, project_id, study_id, intent):
        import base64 as _base64
        content_sha = hashlib.sha256(_base64.b64decode(intent.get('content_base64') or b'')).hexdigest()
        return hashlib.sha256(canonical_json([project_id, study_id, 'office-snapshot',
            intent['operation_id'], intent['expected_revision'], content_sha]).encode()).hexdigest()

    def _office_event(self, project_id, study_id, document_id, intent, payload_extra):
        params = {
            'domain_event_id': 'manuscript-office:' + hashlib.sha256(canonical_json(
                [document_id, intent['operation_id']]).encode()).hexdigest(),
            'stream_id': document_id, 'event_type': 'manuscript_office_snapshot.v1',
            'payload_schema_version': 'mw_protocol_v3_event_v1', 'upcaster_id': 'noop:v1',
            'actor_type': ActorType.USER, 'actor_id': intent['actor_id'],
            'action': 'save_office_snapshot',
            'reason': '持久化不可变Office工作副本，绑定当前语义版本与研究版本。',
            'payload': payload_extra, 'emitted_at': self.clock()}
        return params

    def office_snapshot(self, project_id, study_id, intent):
        """Persist one immutable Office snapshot; idempotent by operation_id.

        The current-working-copy invariant (audit G1/F04): the client pins the
        ``base_artifact_revision`` it opened; when another Office session has
        advanced the working copy since, the save is refused with the latest
        receipt instead of silently becoming the new head.  The research
        baseline the draft was opened against is recorded as-is; the route
        additionally records what it observed as current at save time, so an
        old draft is never silently re-labelled with a newer study version.
        """
        import base64 as _base64
        import io as _io
        import zipfile as _zipfile
        existing = self.recover_office_snapshot(project_id, study_id, intent)
        if existing is not None:
            return existing
        if self.office_store is None:
            raise ValueError('manuscript_office_store_missing')
        document_id = manuscript_document_id(project_id, study_id)
        # Read the current working-copy head outside the write transaction: a
        # nested connection on the same sqlite file would deadlock the lock.
        latest = self.latest_office_snapshot(project_id, study_id)
        base_artifact_revision = intent.get('base_artifact_revision')
        if latest is not None and base_artifact_revision is not None \
                and latest.get('artifact_revision') != base_artifact_revision:
            raise OfficeWorkingCopyConflictError(latest)
        with self.uow_factory() as uow:
            current = uow.semantic_document_repository.get_current(project_id, document_id)
            if current is None:
                raise ValueError('manuscript_document_missing')
            if current.revision != intent['expected_revision'] or \
                    document_revision_hash(current) != intent['expected_document_sha256']:
                raise ValueError('manuscript_document_revision_changed')
            try:
                content = _base64.b64decode(intent.get('content_base64') or '', validate=True)
            except Exception as exc:
                raise ValueError('manuscript_office_content_invalid') from exc
            # A bare "PK" prefix is not a Word document: require a readable
            # zip container carrying the main document part (F12).
            try:
                valid_docx = _zipfile.is_zipfile(_io.BytesIO(content)) and \
                    'word/document.xml' in _zipfile.ZipFile(_io.BytesIO(content)).namelist()
            except Exception:
                valid_docx = False
            if not valid_docx:
                raise ValueError('manuscript_office_content_invalid')
            meta = self.office_store.store(
                f'office-draft:{project_id}:{study_id}', content,
                media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                created_at=self.clock())
            payload = {'operation_id': intent['operation_id'],
                'intent_sha256': self._office_snapshot_intent(project_id, study_id, intent),
                'snapshot_id': 'office-snapshot:' + meta.content_sha256,
                'content_sha256': meta.content_sha256,
                'artifact_revision': meta.revision,
                'base_artifact_revision': base_artifact_revision,
                'size_bytes': meta.size_bytes,
                'document_revision': current.revision,
                'document_sha256': document_revision_hash(current),
                'study_revision_sha256': intent.get('study_revision_sha256'),
                'study_revision_sha256_current_observed': intent.get(
                    'study_revision_sha256_current_observed'),
                'mapping_status': 'pending',
                'acceptance_scope': 'working_draft_only'}
            params = self._office_event(project_id, study_id, document_id, intent, payload)
            head = uow.event_stream_repository.get_stream_head(project_id, document_id)
            if head is None:
                built = self.atomic.builder.build(sequence=1, previous_event_sha256=None, **params)
            else:
                built = self.atomic.builder.continue_chain(
                    head_sha256=head.last_event_sha256,
                    head_sequence=head.last_sequence, **params)
            uow.event_stream_repository.append_events(project_id, document_id, [built])
            uow.commit()
        return {'snapshot_id': payload['snapshot_id'],
            'content_sha256': payload['content_sha256'],
            'artifact_revision': payload['artifact_revision'],
            'base_artifact_revision': payload['base_artifact_revision'],
            'document_revision': payload['document_revision'],
            'study_revision_sha256': payload['study_revision_sha256'],
            'study_revision_sha256_current_observed': payload['study_revision_sha256_current_observed'],
            'mapping_status': 'pending', 'persisted': True,
            'operation_id': intent['operation_id'], 'replayed': False}

    def recover_office_snapshot(self, project_id, study_id, intent):
        document_id = manuscript_document_id(project_id, study_id)
        with self.uow_factory() as uow:
            for event in uow.event_stream_repository.read_events(project_id, document_id):
                if event.event_type != 'manuscript_office_snapshot.v1' \
                        or event.payload.get('operation_id') != intent['operation_id']:
                    continue
                verify_event_integrity(event)
                if event.payload['intent_sha256'] != self._office_snapshot_intent(project_id, study_id, intent):
                    raise ValueError('manuscript_office_snapshot_intent_changed')
                payload = dict(event.payload)
                payload['replayed'] = True
                payload['persisted'] = True
                return payload
        return None

    def latest_office_snapshot(self, project_id, study_id):
        document_id = manuscript_document_id(project_id, study_id)
        latest = None
        with self.uow_factory() as uow:
            for event in uow.event_stream_repository.read_events(project_id, document_id):
                if event.event_type != 'manuscript_office_snapshot.v1':
                    continue
                latest = event.payload
        return latest

    def office_snapshot_content(self, project_id, study_id, operation_id):
        """Read-only byte lookup by operation_id; no intent recomputation."""
        document_id = manuscript_document_id(project_id, study_id)
        with self.uow_factory() as uow:
            for event in uow.event_stream_repository.read_events(project_id, document_id):
                if event.event_type != 'manuscript_office_snapshot.v1' \
                        or event.payload.get('operation_id') != operation_id:
                    continue
                verify_event_integrity(event)
                if self.office_store is None:
                    return None
                return self.office_store.read_by_sha256(event.payload['content_sha256'])
        return None


    def edit(self, project_id, study_id, confirmed_facts, intent):
        """Apply free working-draft edits under CAS; nothing is refused on
        scientific grounds (R3/A09).

        ``confirmed_facts`` feed the deterministic edit classifier, whose
        ruling is saved as a per-edit reconciliation clue — it never rejects
        the batch.  Identity, revision and structure checks still fail loudly;
        the saved version carries recomputed block hashes and an updated
        timestamp (B04) for the reconciliation stage to bind against.
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
            now = self.clock()
            raw = current.model_dump(mode='json')
            by_id = {b['semantic_block_id']: b for b in raw['semantic_blocks']}
            clues = []
            for edit in intent['edits']:
                block = blocks.get(edit.get('semantic_block_id'))
                if block is None:
                    raise ValueError('manuscript_edit_block_unknown')
                replacement = edit.get('block') or {}
                allowed = {key: replacement[key] for key in self.EDITABLE_BLOCK_FIELDS
                           if key in replacement}
                old_text = block_content_text(block.model_dump(mode='json'))
                merged = {**block.model_dump(mode='json'), **allowed}
                new_text = block_content_text(merged)
                ruling = reclassify_edit(old_text=old_text, new_text=new_text,
                    confirmed_facts=confirmed_facts, claimed_class=edit.get('claimed_class'))
                # Server-owned derived fields, recomputed from the merged content.
                content = merged.get('content')
                if isinstance(content, str):
                    merged['content_sha256'] = hashlib.sha256(content.encode()).hexdigest()
                by_id[edit['semantic_block_id']] = merged
                clues.append({'semantic_block_id': edit['semantic_block_id'],
                    'edit_class': ruling['edit_class'],
                    'affected_fact_paths': list(ruling['affected_fact_paths']),
                    'signals': list(ruling.get('signals') or ()),
                    'reason': ruling['reason'] or ''})
            raw['semantic_blocks'] = [by_id[b['semantic_block_id']] for b in raw['semantic_blocks']]
            document = SemanticDocumentRevision.model_validate({
                **raw, 'revision': current.revision + 1,
                'previous_revision_sha256': document_revision_hash(current),
                'updated_at': now,
                'canonical_state': 'proposed'})
            fact_clues = [clue for clue in clues if clue['edit_class'] == 'fact_or_uncertain']
            payload = {'operation_id': intent['operation_id'],
                'intent_sha256': self._edit_intent(project_id, study_id, intent),
                'document': document.model_dump(mode='json'),
                'document_sha256': document_revision_hash(document),
                'edit_count': len(clues),
                'edit_clues': clues,
                'reconciliation_status': 'pending',
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
                    'reason': '自由工作稿编辑已保存为新版本；事实相关修改作为核对线索留待显式核对。',
                    'payload': payload, 'emitted_at': now})
            return {'document': document.model_dump(mode='json'),
                'document_sha256': document_revision_hash(document),
                'operation_id': intent['operation_id'], 'replayed': False, 'status': 'working_draft',
                'reconciliation_status': 'pending', 'edit_clues': clues,
                'fact_clue_count': len(fact_clues),
                'qc': run_manuscript_qc(document.model_dump(mode='json'))}
